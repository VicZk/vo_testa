"""Testes E2E (navegador real via Playwright) dos fluxos críticos.

Rodam no próprio `manage.py test` usando StaticLiveServerTestCase (sobe um servidor
de verdade) + Playwright headless. Pulam sozinhos se o Playwright não estiver
instalado — não quebram a suíte de quem não tem. No CI rodam num job próprio
("Fluxos no navegador", testes.yml) com `E2E_OBRIGATORIO=1`: lá, faltar o Playwright
é erro, para o job nunca ficar verde pulando tudo.

Para rodar localmente:
    .venv/bin/pip install playwright==1.64.0 && .venv/bin/playwright install chromium
    .venv/bin/python manage.py test apps.site.tests_e2e
"""
import os
import unittest

# Playwright (sync) sobe um event loop; sem isto o Django acha que está em contexto
# async e recusa as operações de DB do LiveServer. É só para os testes E2E.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

from django.contrib.staticfiles.testing import StaticLiveServerTestCase

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_OK = True
except ImportError:  # pragma: no cover
    if os.environ.get("E2E_OBRIGATORIO") == "1":
        raise
    _PLAYWRIGHT_OK = False


class _BaseE2E(StaticLiveServerTestCase):
    """Sobe um navegador headless por classe; uma aba (page) por teste.

    Atenção: StaticLiveServerTestCase é um TransactionTestCase — ele dá FLUSH no banco
    após cada teste, o que APAGA os dados semeados por migração (etapas do funil
    comercial, módulos, formas de pagamento…). Classes que dependem desses seeds
    precisam recriá-los no próprio setUp (ver `FunilBuscaE2ETests`), pois outra classe
    E2E rodando antes pode já ter limpado o banco.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        self.page = self._browser.new_page()

    def tearDown(self):
        self.page.close()

    def url(self, caminho):
        return self.live_server_url + caminho


class _UnidadeVendavelMixin:
    """Semeia um quarto físico vendável pelo site (venda por unidade): TipoUH + UH
    ATIVA + VitrineQuarto publicada + site.Quarto como recibo do canal. A fonte da
    verdade do preço/disponibilidade é o CRM, igual à produção."""

    def _semear_unidade(self, *, capacidade=2, tarifa="400.00"):
        from decimal import Decimal

        from apps.nucleo.models import UH, TipoUH
        from apps.site.models import CategoriaQuarto, Quarto, VitrineQuarto
        tipo = TipoUH.objects.create(
            nome="Suíte E2E", tarifa_base=Decimal(tarifa), capacidade=capacidade)
        uh = UH.objects.create(
            numero="E2E-1", tipo=tipo, nome_tematico="Cabine do Lago E2E",
            vista_lago=True)
        VitrineQuarto.objects.create(
            uh=uh, publicar=True, destaque=True, metragem=25)
        cat, _ = CategoriaQuarto.objects.get_or_create(nome="Suíte E2E")
        Quarto.objects.create(
            nome="Cabine E2E", categoria=cat, descricao="x", descricao_curta="x",
            capacidade=capacidade, metragem=25, preco_base=Decimal(tarifa),
            status="disponivel", tipo_uh=tipo)
        return uh

    def _datas(self, dias_ini=10, dias_fim=13):
        from datetime import date, timedelta
        hoje = date.today()
        return (hoje + timedelta(days=dias_ini), hoje + timedelta(days=dias_fim))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class ReservaSiteE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    """Fluxo de reserva do site ponta a ponta no navegador real: lista de quartos
    (passo 2) → dados do hóspede (passo 3) → resumo (passo 4) → confirmação (passo 5).
    Prova que o clique-a-clique cria a PRÉ-RESERVA no CRM (fonte da verdade) e o
    recibo do canal (`site.Reserva`), sem overbooking."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()  # o rate-limit do site vive em LocMemCache entre testes
        self.uh = self._semear_unidade()

    def test_reserva_ponta_a_ponta(self):
        checkin, checkout = self._datas()
        # Passo 2 — entra direto com as datas (o calendário tem teste próprio) e
        # confere que o quarto físico aparece com o nome temático.
        self.page.goto(self.url(
            f"/reservar/?checkin={checkin:%Y-%m-%d}"
            f"&checkout={checkout:%Y-%m-%d}&hospedes=2"))
        self.page.wait_for_selector("text=Cabine do Lago E2E", timeout=10000)
        self.page.get_by_role("link", name="Reservar").first.click()

        # Passo 3 — dados do hóspede (CPF válido p/ passar na validação do form).
        self.page.wait_for_selector("input[name=nome]", timeout=10000)
        self.page.fill("input[name=nome]", "Maria Teste E2E")
        self.page.fill("input[name=email]", "maria.e2e@exemplo.com")
        self.page.fill("input[name=telefone]", "(49) 99143-8813")
        self.page.fill("input[name=cpf]", "111.444.777-35")
        self.page.get_by_role("button", name="Continuar").click()

        # Passo 4 — resumo e confirmação.
        self.page.wait_for_selector("text=Confirmar Reserva", timeout=10000)
        # Sem o aceite da política o navegador não deixa enviar (caixa obrigatória).
        self.page.check("input[name=aceite_politica]")
        self.page.get_by_role("button", name="Confirmar Reserva").click()

        # Passo 5 — página de confirmação (URL com token /reserva/<uuid>/).
        self.page.wait_for_selector("text=Reserva Registrada!", timeout=10000)
        self.assertIn("/reserva/", self.page.url)

        # Invariante: a reserva do canal e a PRÉ-RESERVA no CRM foram criadas.
        from apps.reservas.models import Reserva as ReservaCRM
        from apps.site.models import Reserva as ReservaSite
        rs = ReservaSite.objects.get(hospede__nome="Maria Teste E2E")
        self.assertEqual(rs.status, "aguardando")
        self.assertIsNotNone(rs.crm_reserva_id)
        crm = ReservaCRM.objects.get(pk=rs.crm_reserva_id)
        self.assertEqual(crm.uh_id, self.uh.pk)
        self.assertEqual(crm.status, ReservaCRM.Status.PRE_RESERVA)
        self.assertEqual(crm.checkin, checkin)
        self.assertEqual(crm.checkout, checkout)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class CalendarioDatasE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    """Passo 1 real: dirige o calendário (flatpickr, servido local em /static) e o
    stepper de hóspedes, provando que selecionar um intervalo habilita o botão e leva
    à lista de quartos. Guarda o tipo de regressão de UI que só aparece no navegador."""

    def setUp(self):
        super().setUp()
        self._semear_unidade(capacidade=4)  # comporta os 3 hóspedes do stepper

    def test_selecionar_intervalo_habilita_e_lista_quartos(self):
        self.page.goto(self.url("/reservar/"))
        # inline flatpickr insere o calendário como IRMÃO de #calendario-inline.
        self.page.wait_for_selector(".flatpickr-calendar", timeout=10000)
        cal = self.page.locator(".flatpickr-calendar")

        # Mês seguinte: todos os dias são futuros (robusto em qualquer dia do mês).
        cal.locator(".flatpickr-next-month").click()
        self.page.wait_for_timeout(200)
        # Intervalo (range): dia 10 = check-in, dia 13 = check-out.
        cal.get_by_text("10", exact=True).first.click()
        cal.get_by_text("13", exact=True).first.click()

        # +1 hóspede pelo stepper (3 pessoas) — exercita o controle customizado.
        self.page.click("#hosp-mais")
        self.assertEqual(self.page.input_value("#f-hospedes"), "3")

        # Com check-in + check-out preenchidos, o botão deixa de ser desabilitado.
        self.page.wait_for_function(
            "() => { const b = document.getElementById('btn-ver-quartos');"
            "        return b && !b.disabled; }",
            timeout=6000)
        self.assertNotEqual(self.page.input_value("#f-checkin"), "")
        self.assertNotEqual(self.page.input_value("#f-checkout"), "")

        # Submete → passo 2 (lista de quartos) com as datas na URL.
        self.page.click("#btn-ver-quartos")
        self.page.wait_for_selector("text=Cabine do Lago E2E", timeout=10000)
        self.assertIn("checkin=", self.page.url)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class SiteHomeE2ETests(_BaseE2E):
    def test_hero_mostra_campanha(self):
        self.page.goto(self.url("/"))
        self.page.wait_for_selector("text=É a casa do vô!", timeout=10000)
        self.assertTrue(self.page.get_by_text("É a casa do vô!").is_visible())

    def test_secao_revela(self):
        # Guarda o bug de reveal (fade-section com opacity travada em 0): a seção de
        # experiências precisa ficar VISÍVEL (opacity → 1) ao entrar na viewport ou
        # pelo fail-safe. Semeia 1 experiência para a seção ter conteúdo.
        from apps.site.models import Experiencia
        Experiencia.objects.create(
            nome="Trilha do Teste E2E", descricao="desc", destaque=True)
        self.page.goto(self.url("/"))
        self.page.get_by_text("Trilha do Teste E2E").scroll_into_view_if_needed()
        self.page.wait_for_function(
            "() => { const s = document.querySelector('#experiencias .fade-section');"
            "        return s && getComputedStyle(s).opacity === '1'; }",
            timeout=6000)
        op = self.page.eval_on_selector(
            "#experiencias .fade-section", "el => getComputedStyle(el).opacity")
        self.assertEqual(op, "1")


class _FunilComercialMixin:
    """Prepara o módulo Comercial para as E2E do funil: reativa o módulo e recria as
    etapas de funil no setUp. O flush do TransactionTestCase apaga o seed de migração,
    então uma classe E2E que rode antes deixaria /crm/comercial/ 404 e o funil vazio."""

    # Etapas do funil (espelham a migração comercial.0002).
    _ETAPAS = [
        ("Novo lead", 10, 10, "aberta"), ("Contato feito", 20, 30, "aberta"),
        ("Cotação enviada", 30, 50, "aberta"), ("Negociação", 40, 70, "aberta"),
        ("Ganho", 50, 100, "ganho"), ("Perdido", 60, 0, "perdido"),
    ]

    def setUp(self):
        super().setUp()
        from apps.comercial.models import EtapaFunil
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.COMERCIAL, defaults={"ativo": True})
        for nome, ordem, prob, tipo in self._ETAPAS:
            EtapaFunil.objects.get_or_create(
                nome=nome, defaults={"ordem": ordem, "probabilidade": prob, "tipo": tipo})

    def _login(self, username, senha):
        self.page.goto(self.url("/crm/entrar/"))
        self.page.fill("input[name=username]", username)
        self.page.fill("input[name=password]", senha)
        self.page.press("input[name=password]", "Enter")
        self.page.wait_for_load_state("networkidle")


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class FunilBuscaE2ETests(_FunilComercialMixin, _BaseE2E):
    def test_busca_do_funil_filtra_cards(self):
        from apps.comercial import services
        from apps.nucleo.models import Pessoa, Usuario
        u = Usuario.objects.create_superuser(username="e2e", password="forte-123-abc")
        for nome in ("Alpha Lead E2E", "Beta Lead E2E"):
            p = Pessoa.objects.create(nome=nome)
            services.criar_oportunidade(usuario=u, pessoa=p, titulo="Proposta")

        self._login("e2e", "forte-123-abc")
        self.page.goto(self.url("/crm/comercial/"))
        self.page.wait_for_selector("#funilBusca")
        board = self.page.locator("#funilBoard")  # escopo: só os cards do quadro

        # antes de filtrar: os dois cards aparecem
        self.assertTrue(board.get_by_text("Alpha Lead E2E").is_visible())
        self.assertTrue(board.get_by_text("Beta Lead E2E").is_visible())

        # digita "Alpha" → só o card Alpha permanece
        self.page.fill("#funilBusca", "Alpha")
        self.page.wait_for_timeout(300)
        self.assertTrue(board.get_by_text("Alpha Lead E2E").is_visible())
        self.assertFalse(board.get_by_text("Beta Lead E2E").is_visible())


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class FunilMoverLeadE2ETests(_FunilComercialMixin, _BaseE2E):
    """Caminho feliz: login + arrastar um lead de "Novo lead" para "Contato feito".

    O Kanban usa drag-and-drop nativo (HTML5), que o mouse sintético do Playwright não
    dispara de forma confiável — então simulamos o arrasto despachando os eventos
    dragstart→dragover→drop com um MESMO DataTransfer, exatamente como o `cardDragStart`
    (setData('op', id)) e o `soltarCard` (getData('op') → submete o form-mover) esperam.
    Assim o teste exercita os handlers reais + a view `mover` + o service `mover_etapa`.
    """

    _DRAG_JS = """
    ([origem, destino]) => {
        const src = document.querySelector(origem);
        const tgt = document.querySelector(destino);
        const dt = new DataTransfer();
        src.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: dt}));
        tgt.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));
        tgt.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
        src.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
    }
    """

    def test_mover_lead_entre_etapas(self):
        from apps.comercial import services
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa, Usuario

        u = Usuario.objects.create_superuser(username="mov", password="forte-123-abc")
        pessoa = Pessoa.objects.create(nome="Lead Arrastável E2E")
        op = services.criar_oportunidade(usuario=u, pessoa=pessoa, titulo="Proposta")
        novo = EtapaFunil.objects.get(nome="Novo lead")
        contato = EtapaFunil.objects.get(nome="Contato feito")
        self.assertEqual(op.etapa_id, novo.id)  # nasce em "Novo lead"

        self._login("mov", "forte-123-abc")
        self.page.goto(self.url("/crm/comercial/"))
        self.page.wait_for_selector("#funilBoard")

        card = f'.funil-card[data-op="{op.id}"]'
        coluna_contato = f'.funil-coluna[data-etapa="{contato.id}"]'
        # Estado inicial: o card está na coluna "Novo lead".
        self.assertTrue(self.page.locator(
            f'.funil-coluna[data-etapa="{novo.id}"] {card}').is_visible())

        # Arrasta o card para "Contato feito"; o drop submete o form-mover (reload).
        with self.page.expect_navigation():
            self.page.evaluate(self._DRAG_JS, [card, coluna_contato])

        # UI: o card agora vive dentro da coluna "Contato feito".
        self.page.wait_for_selector(f'{coluna_contato} {card}', timeout=10000)
        self.assertTrue(self.page.locator(f'{coluna_contato} {card}').is_visible())

        # Invariante: a etapa mudou no banco (via mover_etapa), sem tocar outros leads.
        op.refresh_from_db()
        self.assertEqual(op.etapa_id, contato.id)
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class LpInauguracaoE2ETests(_BaseE2E):
    """A LP da Inauguração no navegador. Guarda dois tropeços reais: o aviso de cookies
    nasceu com a classe `.consent`, a mesma do checkbox de LGPD do RSVP — o
    `position: fixed` do aviso arrancava o checkbox do formulário e o botão de enviar
    subia por cima do texto; e as fotos e fontes saíram do HTML (2,1 MB → 89 KB) para
    endereços próprios, que precisam carregar de verdade."""

    URL = "/lp/inauguracao_31_10_2026/"

    def _abrir(self, largura=390, altura=844):
        self.page.set_viewport_size({"width": largura, "height": altura})
        terceiros = []
        base = self.live_server_url

        def filtrar(rota):
            if rota.request.url.startswith(base):
                rota.continue_()
            else:                       # nada sai para Google/Meta/Maps no teste
                terceiros.append(rota.request.url)
                rota.abort()
        self.page.route("**/*", filtrar)
        self.page.goto(self.url(self.URL), wait_until="load")
        return terceiros

    def test_checkbox_do_rsvp_fica_no_formulario_com_o_aviso_na_tela(self):
        self._abrir()
        self.page.locator("#consentimento").wait_for(state="visible")
        geo = self.page.evaluate("""() => {
            const f = document.getElementById('formInaug');
            const l = f.querySelector('label.consent'), b = f.querySelector('button[type=submit]');
            const rf = f.getBoundingClientRect(), rl = l.getBoundingClientRect(), rb = b.getBoundingClientRect();
            return {posicao: getComputedStyle(l).position, dentro: rl.top >= rf.top && rl.bottom <= rf.bottom,
                    botao_abaixo: rb.top >= rl.bottom - 1}; }""")
        self.assertEqual(geo, {"posicao": "static", "dentro": True, "botao_abaixo": True})

    def test_fotos_e_fontes_desembutidas_carregam(self):
        self._abrir(1440, 900)
        self.page.evaluate("() => document.fonts.ready")
        self.page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        self.page.wait_for_function(
            "() => [...document.images].every(i => i.complete)", timeout=10000)
        quebradas = self.page.evaluate(
            "() => [...document.images].filter(i => i.currentSrc && !i.naturalWidth).map(i => i.currentSrc)")
        self.assertEqual(quebradas, [])
        self.assertTrue(self.page.evaluate(
            "() => [...document.fonts].some(f => f.family.includes('Neco') && f.status === 'loaded')"))

    def test_medicao_so_depois_do_aceite(self):
        terceiros = self._abrir()
        guardadas = "() => document.querySelectorAll('script[type=\"text/plain\"][data-consentimento]').length"
        self.assertGreater(self.page.evaluate(guardadas), 0)
        self.assertEqual([u for u in terceiros if "googletagmanager" in u or "facebook" in u], [])
        self.page.get_by_role("button", name="Aceitar").click()
        self.page.locator("#consentimento").wait_for(state="hidden")
        self.assertEqual(self.page.evaluate(guardadas), 0)
        self.assertEqual(self.page.evaluate("() => localStorage.getItem('votesta-consentimento')"), "aceito")
        self.page.reload(wait_until="load")
        self.page.wait_for_timeout(300)
        self.assertFalse(self.page.locator("#consentimento").is_visible())


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class MenuLateralE2ETests(_BaseE2E):
    """O menu lateral do CRM recolhe para o trilho sem pular: cada ícone fica no mesmo x
    nos dois estados, os rótulos somem por opacidade no trilho e, aberto, nenhum rótulo
    passa da borda do menu (o "elementos meio fora, overlap e extrusão" do pedido)."""

    MEDIR = """() => {
      const sb = document.querySelector('.sidebar').getBoundingClientRect();
      const itens = [...document.querySelectorAll('.sidebar .nav-item, .sidebar .acao-topo')];
      return {
        largura: Math.round(sb.width),
        icones: itens.map(i => +(i.querySelector('.ico').getBoundingClientRect().left - sb.left).toFixed(1)),
        opacidades: itens.map(i => getComputedStyle(i.querySelector('.rotulo')).opacity),
        fora: itens.filter(i => {
          const r = i.querySelector('.rotulo').getBoundingClientRect();
          return getComputedStyle(i.querySelector('.rotulo')).opacity !== '0' && r.right > sb.right + .5;
        }).map(i => i.textContent.trim()),
      };
    }"""

    def test_trilho_e_o_menu_aberto_recortado(self):
        from apps.nucleo.models import Usuario
        Usuario.objects.create_superuser(username="menu", password="forte-123-abc")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.goto(self.url("/crm/entrar/"))
        self.page.fill("input[name=username]", "menu")
        self.page.fill("input[name=password]", "forte-123-abc")
        self.page.press("input[name=password]", "Enter")
        self.page.wait_for_selector(".sidebar")
        self.page.evaluate("() => localStorage.setItem('sidebar', 'aberta')")
        self.page.reload(wait_until="load")
        self.page.wait_for_timeout(200)
        aberta = self.page.evaluate(self.MEDIR)
        self.page.click("#btn-recolher")
        self.page.wait_for_function(
            "() => Math.round(document.querySelector('.sidebar').getBoundingClientRect().width) < 100")
        self.page.wait_for_timeout(200)
        trilho = self.page.evaluate(self.MEDIR)

        self.assertGreater(len(aberta["icones"]), 1)
        self.assertEqual(aberta["icones"], trilho["icones"])          # nenhum ícone pula
        self.assertEqual(set(trilho["opacidades"]), {"0"})            # rótulos somem no trilho
        self.assertEqual(set(aberta["opacidades"]), {"1"})
        self.assertEqual(aberta["fora"], [])                          # nada passa da borda
        self.assertLess(trilho["largura"], aberta["largura"])


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class DicasE2ETests(_BaseE2E):
    """O balão de hover (static/js/dicas.js) fica inteiro na tela mesmo encostado na
    borda, aponta para o elemento, e no menu recolhido aparece à direita do ícone."""

    BALAO = """() => { const b = document.getElementById('dica-flutuante');
      if (!b || b.hidden) return null; const r = b.getBoundingClientRect();
      return {l: r.left, r: r.right, t: r.top, b: r.bottom, cy: r.top + r.height / 2,
              lado: b.dataset.lado, texto: b.textContent}; }"""

    def _entrar(self, estado_menu):
        from apps.nucleo.models import Usuario
        Usuario.objects.create_superuser(username="dica", password="forte-123-abc")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.add_init_script(f"localStorage.setItem('sidebar', '{estado_menu}')")
        self.page.goto(self.url("/crm/entrar/"))
        self.page.fill("input[name=username]", "dica")
        self.page.fill("input[name=password]", "forte-123-abc")
        self.page.press("input[name=password]", "Enter")
        self.page.wait_for_selector(".sidebar")
        self.page.wait_for_load_state("load")      # dicas.js vem com defer
        self.page.mouse.move(700, 450)
        # Logo depois de abrir, a página ajusta a rolagem uma vez (e rolar esconde a
        # dica, de propósito): espera assentar antes de apontar.
        self.page.wait_for_timeout(300)

    def test_balao_na_borda_da_tela_fica_inteiro(self):
        self._entrar("aberta")
        self.page.evaluate("""() => { const s = document.createElement('span');
            s.id = 'teste-dica'; s.textContent = 'x';
            s.setAttribute('data-dica', 'Uma dica bem comprida, encostada na borda direita da tela');
            s.style.cssText = 'position:fixed; right:2px; top:300px;';
            document.body.appendChild(s); }""")
        self.page.hover("#teste-dica")
        self.page.wait_for_timeout(150)
        b = self.page.evaluate(self.BALAO)
        self.assertIsNotNone(b)
        self.assertGreaterEqual(b["l"], 0)
        self.assertLessEqual(b["r"], 1440)
        self.assertIn("encostada na borda", b["texto"])

    def test_menu_recolhido_mostra_o_nome_ao_lado_do_icone(self):
        self._entrar("recolhida")
        item = self.page.locator(".sidebar a.nav-item").first
        item.hover()
        self.page.wait_for_timeout(150)
        b = self.page.evaluate(self.BALAO)
        caixa = item.bounding_box()
        self.assertIsNotNone(b)
        self.assertEqual(b["lado"], "direita")
        self.assertGreater(b["l"], caixa["x"] + caixa["width"])
        self.assertLess(abs(b["cy"] - (caixa["y"] + caixa["height"] / 2)), 2)
        self.assertIsNone(item.get_attribute("title"))



@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class ComboNoPainelE2ETests(_BaseE2E):
    """No celular, a lista do combo (cliente do PDV) cabe no painel em que o campo mora.

    O `posicionar()` media só a tela: no PDV o campo fica no fim do painel do carrinho
    (que rola sozinho), a lista abria para baixo com 320 px e o painel a cortava pela
    metade — o "dropdown com sobreposição" que o dono viu no celular."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import (
            Hospede,
            LocalEstoque,
            ModuloContratado,
            Pessoa,
            Usuario,
        )
        from apps.nucleo.modulos import Modulo
        # O flush das outras E2E apaga os seeds de migração: módulos e o depósito da Loja
        # (sem ele o PDV mostra só o aviso de configurar, sem o carrinho).
        for modulo in (Modulo.ESTOQUE, Modulo.LOJA):
            ModuloContratado.objects.update_or_create(codigo=modulo, defaults={"ativo": True})
        LocalEstoque.objects.get_or_create(nome="Depósito da Loja", defaults={"modulo": "loja"})
        for i in range(12):
            Hospede.objects.create(pessoa=Pessoa.objects.create(nome=f"Ana Hóspede {i:02d}"))
        Usuario.objects.create_superuser(username="combo", password="forte-123-abc")

    def test_lista_do_cliente_no_pdv_cabe_no_carrinho(self):
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url("/crm/entrar/"))
        p.fill("input[name=username]", "combo")
        p.fill("input[name=password]", "forte-123-abc")
        p.press("input[name=password]", "Enter")
        p.wait_for_load_state("networkidle")
        p.goto(self.url("/crm/loja/"))
        p.wait_for_load_state("networkidle")
        campo = p.locator(".pdv-painel .combo-input").first
        campo.scroll_into_view_if_needed()
        campo.click()
        campo.type("Ana", delay=20)
        p.wait_for_timeout(300)
        medida = p.evaluate("""() => {
          const lista = document.querySelector('.pdv-painel .combo-lista');
          const painel = document.querySelector('.pdv-painel');
          const l = lista.getBoundingClientRect(), r = painel.getBoundingClientRect();
          return {topo: l.top, base: l.bottom, alto: l.height,
                  painel_topo: r.top, painel_base: r.bottom, tela: innerHeight};
        }""")
        self.assertGreater(medida["alto"], 100, medida)                    # abriu de verdade
        self.assertLessEqual(medida["base"], medida["painel_base"] + 1, medida)
        self.assertGreaterEqual(medida["topo"], medida["painel_topo"] - 1, medida)
        self.assertLessEqual(medida["base"], medida["tela"] + 1, medida)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class SiteNoCelularE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    """O site no celular: nada fixo tapando o fim da página e alvo de 44px no
    caminho da reserva.

    Os dois achados que o dono viu no aparelho: o aviso de cookies é
    `position: fixed` no rodapé e comia o fim de toda página (na home, o
    formulário de proposta; em Minha reserva, o "Perdeu o código?"), e o botão
    do WhatsApp ficava por cima da linha de créditos do rodapé.
    """

    CELULAR = {"width": 390, "height": 844}

    # Mede o alvo de verdade: o que ACIONA o controle é o <label> que o embrulha,
    # quando existe — uma caixa de marcar de 13px dentro de um rótulo de 324×44
    # não é um alvo de 13px.
    ALVOS = """
    (sels) => sels.map(s => {
      const el = document.querySelector(s);
      if (!el) return {sel: s, achou: false};
      const lab = el.closest('label');
      const r = (lab || el).getBoundingClientRect();
      return {sel: s, achou: true, w: Math.round(r.width), h: Math.round(r.height)};
    })
    """

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.uh = self._semear_unidade()
        self.page.set_viewport_size(self.CELULAR)

    def _fim_da_pagina(self):
        self.page.evaluate("() => window.scrollTo(0, document.scrollingElement.scrollHeight)")
        self.page.wait_for_timeout(250)

    def test_aviso_de_cookies_reserva_o_proprio_espaco(self):
        """Sem a folga, quem abre o site pela primeira vez não vê o que está
        embaixo do aviso — e não há como rolar mais, a página já acabou."""
        p = self.page
        p.goto(self.url("/minha-reserva/"))
        p.wait_for_selector("#consentimento:not([hidden])", timeout=10000)
        self._fim_da_pagina()
        medida = p.evaluate("""() => {
          const b = document.getElementById('consentimento');
          const r = b.getBoundingClientRect();
          const ancora = [...document.querySelectorAll('a')]
              .find(a => a.textContent.includes('Voltar ao site'));
          const v = ancora.getBoundingClientRect();
          const meio = document.elementFromPoint(v.left + v.width / 2, v.top + v.height / 2);
          return {folga: parseFloat(getComputedStyle(document.body).paddingBottom),
                  aviso: Math.round(r.height), tapado: !!(meio && b.contains(meio))};
        }""")
        self.assertGreaterEqual(medida["folga"], medida["aviso"] - 1, medida)
        self.assertFalse(medida["tapado"], f"o aviso cobre 'Voltar ao site': {medida}")

        # Ao escolher, a folga some junto com o aviso.
        p.click("[data-consent-recusar]")
        p.wait_for_timeout(250)
        folga = p.evaluate("() => getComputedStyle(document.body).paddingBottom")
        self.assertIn(folga, ("0px", "0"), "a folga ficou sobrando depois de escolher")

    def test_botao_do_whatsapp_nao_cobre_o_fim_do_rodape(self):
        p = self.page
        p.goto(self.url("/"))
        p.wait_for_selector(".zap-flutuante", timeout=10000)
        p.click("[data-consent-aceitar]")          # tira o aviso da frente
        p.wait_for_timeout(250)
        self._fim_da_pagina()
        tapado = p.evaluate("""() => {
          const zap = document.querySelector('.zap-flutuante');
          const z = zap.getBoundingClientRect();
          const creditos = [...document.querySelectorAll('footer p')].pop();
          const c = creditos.getBoundingClientRect();
          const cruza = Math.max(z.left, c.left) < Math.min(z.right, c.right)
                     && Math.max(z.top, c.top) < Math.min(z.bottom, c.bottom);
          return {cruza, zap: Math.round(z.top), creditos: Math.round(c.bottom)};
        }""")
        self.assertFalse(tapado["cruza"], f"o WhatsApp está em cima dos créditos: {tapado}")

    def test_whatsapp_nao_encavala_no_formulario_da_primeira_tela(self):
        """Na primeira visita, com o aviso de cookies no pé da tela, o botão do
        WhatsApp subia para cima dele e caía no canto do "Ver Disponibilidade" —
        o "ícone com overlap" que o dono viu na home. No celular ele espera a
        escolha e volta depois."""
        p = self.page
        p.goto(self.url("/"))
        p.wait_for_selector("#consentimento:not([hidden])", timeout=10000)
        p.wait_for_timeout(250)
        medida = p.evaluate("""() => {
          const zap = document.querySelector('.zap-flutuante');
          const z = zap.getBoundingClientRect();
          const f = document.querySelector('#hero-hospedes').closest('form').getBoundingClientRect();
          const cruza = Math.max(z.left, f.left) < Math.min(z.right, f.right)
                     && Math.max(z.top, f.top) < Math.min(z.bottom, f.bottom);
          return {visivel: getComputedStyle(zap).visibility === 'visible', cruza};
        }""")
        self.assertFalse(medida["visivel"] and medida["cruza"],
                         f"o WhatsApp está em cima do formulário de datas: {medida}")
        p.click("[data-consent-aceitar]")
        p.wait_for_timeout(250)
        self.assertEqual(
            p.evaluate("() => getComputedStyle(document.querySelector('.zap-flutuante')).visibility"),
            "visible", "o WhatsApp não voltou depois da escolha")

    def test_caminho_da_reserva_tem_alvo_de_44px(self):
        """Campo de data, botão do hero, CTA do quarto e a escolha das camas —
        tudo entre 20 e 40px antes desta passada."""
        p = self.page
        p.goto(self.url("/"))
        # O flatpickr troca o campo de data por um par (um `hidden` com o valor e
        # um visível ao lado), então aqui se mede o que está NA TELA, não o id.
        hero = p.evaluate("""() => {
            const f = document.querySelector('#hero-hospedes').closest('form');
            return [...f.querySelectorAll('input, button')]
              // `tabindex=-1` é a armadilha do antirrobô: não é alvo de ninguém.
              .filter(e => e.type !== 'hidden' && e.offsetParent && e.tabIndex !== -1)
              .map(e => ({campo: e.id || e.type, h: Math.round(e.getBoundingClientRect().height)}));
        }""")
        self.assertGreaterEqual(len(hero), 4, f"o formulário do hero sumiu: {hero}")
        for item in hero:
            self.assertGreaterEqual(item["h"], 44, f"{item} — {hero}")

        checkin, checkout = self._datas()
        p.goto(self.url(f"/reservar/?checkin={checkin:%Y-%m-%d}"
                        f"&checkout={checkout:%Y-%m-%d}&hospedes=2"))
        p.wait_for_selector("text=Cabine do Lago E2E", timeout=10000)
        cta = p.get_by_role("link", name="Reservar").first.bounding_box()
        self.assertGreaterEqual(round(cta["height"]), 44, cta)
        cta_el = p.get_by_role("link", name="Reservar").first
        cta_el.click()
        p.wait_for_selector("input[name=nome]", timeout=10000)
        for item in p.evaluate(self.ALVOS, ["input[name=arranjo]"]):
            if item["achou"]:
                self.assertGreaterEqual(item["h"], 44, item)

    def test_gaveta_aberta_nao_tem_nada_flutuando_por_cima(self):
        """A gaveta e o véu são z-40; o aviso de cookies (z-90, do componente do
        núcleo) e os flutuantes do site (z-50) passavam por cima dela. O aviso
        cobria a faixa de baixo — inclusive o "Fazer Reserva", que é o fim do
        caminho de quem abriu o menu para reservar."""
        p = self.page
        p.goto(self.url("/"))
        p.wait_for_selector("#consentimento:not([hidden])", timeout=10000)
        p.click("#menuBtn")
        p.wait_for_timeout(500)
        estado = p.evaluate("""() => {
          const gaveta = document.getElementById('mobileMenu');
          const tapados = [];
          for (const el of gaveta.querySelectorAll('a, button')) {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            const x = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1);
            const y = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 1);
            const topo = document.elementFromPoint(x, y);
            if (topo && el !== topo && !el.contains(topo)) {
              tapados.push((el.textContent || '').trim().slice(0, 20) + ' por '
                           + topo.tagName.toLowerCase() + '.' + topo.className);
            }
          }
          const ver = s => getComputedStyle(document.querySelector(s)).visibility;
          return {tapados, aviso: ver('#consentimento'), zap: ver('.zap-flutuante')};
        }""")
        self.assertEqual(estado["tapados"], [], estado)
        self.assertEqual(estado["aviso"], "hidden", estado)
        self.assertEqual(estado["zap"], "hidden", estado)

        # Fechada a gaveta, os dois voltam — o aviso ainda precisa ser respondido.
        p.click("#menuBtn")
        p.wait_for_timeout(500)
        volta = p.evaluate("""() => ({
            aviso: getComputedStyle(document.getElementById('consentimento')).visibility,
            zap: getComputedStyle(document.querySelector('.zap-flutuante')).visibility})""")
        self.assertEqual(volta, {"aviso": "visible", "zap": "visible"})
