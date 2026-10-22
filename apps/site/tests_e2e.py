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
        self.page = self._browser.new_page(locale=getattr(self, "LOCALE", None))

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
class CampanhaEdicaoE2ETests(_FunilComercialMixin, _BaseE2E):
    """Criação, digitação, erro e fechamento reais, incluindo o espaço no celular."""

    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        from apps.marketing.models import Campanha
        from apps.nucleo.models import ModuloContratado, Usuario
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.MARKETING, defaults={"ativo": True})
        Usuario.objects.create_superuser(username="campanha", password="forte-123-abc")
        self.campanha = Campanha.objects.create(nome="Férias E2E", objetivo="Reservar cabanas")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("campanha", "forte-123-abc")
        self.page.goto(self.url("/crm/marketing/"))

    def _abrir(self):
        self.page.get_by_role("link", name="Férias E2E", exact=True).click()
        self.page.get_by_label("Nome da campanha").wait_for()

    def test_cancelar_nao_cria_e_duplo_clique_cria_uma_vez(self):
        from apps.marketing.models import Campanha
        p = self.page
        p.get_by_role("link", name="Nova campanha", exact=True).click()
        p.get_by_role("button", name="Cancelar", exact=True).click()
        p.locator("#modal-reserva").wait_for(state="hidden")
        self.assertEqual(Campanha.objects.count(), 1)
        p.get_by_role("link", name="Nova campanha", exact=True).click()
        p.get_by_label("Nome da campanha").fill("Semana da família E2E")
        p.get_by_role("button", name="Criar campanha", exact=True).click(click_count=2)
        p.get_by_role("heading", name="Semana da família E2E", exact=True).wait_for()
        self.assertEqual(Campanha.objects.filter(nome="Semana da família E2E").count(), 1)
        p.get_by_role("button", name="Fechar campanha").click()
        p.locator("#modal-reserva").wait_for(state="hidden")
        p.get_by_role("link", name="Semana da família E2E", exact=True).wait_for()
        self.assertEqual(p.evaluate("document.activeElement.textContent.trim()"), "Semana da família E2E")
        self.assertFalse(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def test_digitacao_nao_salva_sozinha_e_erro_preserva_o_preenchimento(self):
        from decimal import Decimal
        p = self.page
        self._abrir()
        p.get_by_label("Nome da campanha").fill("Férias com crianças E2E")
        p.get_by_label("Nome da campanha").press("Tab")
        # O autosave antigo disparava após 600 ms e trocava o campo sob o teclado.
        p.wait_for_timeout(750)
        self.assertEqual(p.evaluate("document.activeElement.id"), "id_objetivo")
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.nome, "Férias E2E")
        p.get_by_label("Investimento previsto (R$)").fill("inválido")
        p.get_by_role("button", name="Salvar dados", exact=True).click()
        p.get_by_text("Digite um número válido, como 150 ou 1.500,50.", exact=True).wait_for()
        self.assertEqual(p.input_value("#id_nome"), "Férias com crianças E2E")
        self.assertEqual(p.input_value("#id_verba_prevista"), "inválido")
        self.assertEqual(p.evaluate("document.activeElement.id"), "id_verba_prevista")
        p.once("dialog", lambda dialog: dialog.dismiss())
        p.get_by_role("button", name="Fechar campanha").click()
        self.assertTrue(p.locator("#modal-conteudo").is_visible())
        p.get_by_label("Investimento previsto (R$)").fill("1.500,50")
        p.get_by_role("button", name="Salvar dados", exact=True).click()
        p.get_by_text("Dados da campanha salvos.", exact=True).wait_for()
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.nome, "Férias com crianças E2E")
        self.assertEqual(self.campanha.verba_prevista, Decimal("1500.50"))
        p.get_by_role("button", name="Fechar campanha").click()
        p.get_by_role("link", name="Férias com crianças E2E", exact=True).wait_for()
        self.assertEqual(p.evaluate("document.activeElement.textContent.trim()"), "Férias com crianças E2E")

    def test_ficha_cabe_e_acoes_ficam_visiveis_nas_quatro_larguras(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                self._abrir()
                p.wait_for_function("getComputedStyle(document.getElementById('modal-conteudo')).transform === 'none'")
                medida = p.evaluate("""() => {
                  const rect = s => { const r = document.querySelector(s).getBoundingClientRect();
                    return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, height:r.height}; };
                  const close = document.querySelector('.fx-gaveta .modal-fechar'), r = close.getBoundingClientRect();
                  const hit = document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
                  return {ficha:rect('.fx-gaveta'), corpo:rect('.fx-corpo'), pe:rect('.fx-pe'),
                    largura:document.documentElement.scrollWidth, tela:innerWidth,
                    fechar:hit === close || close.contains(hit),
                    trava:document.body.classList.contains('sem-rolagem')};
                }""")
                self.assertGreater(medida["corpo"]["height"], 300, medida)
                self.assertGreaterEqual(medida["ficha"]["left"], 0, medida)
                self.assertLessEqual(medida["ficha"]["right"], largura + 1, medida)
                self.assertLessEqual(medida["pe"]["bottom"], 845, medida)
                self.assertLessEqual(medida["largura"], medida["tela"], medida)
                self.assertTrue(medida["fechar"], medida)
                self.assertTrue(medida["trava"], medida)
                # Os campos de responsáveis ficam escondidos na primeira vista.
                # Com a seção aberta, fornecedor e botão escapavam do cartão.
                for dobra in p.locator(".mkt-dobra").all():
                    if dobra.get_attribute("open") is None:
                        dobra.locator(":scope > summary").click()
                p.evaluate("document.fonts.ready")
                fora = p.locator(".fx-envolvidos .fx-row").evaluate_all("""rows => rows.flatMap(row => {
                    const r = row.getBoundingClientRect();
                    return [...row.querySelectorAll('input:not([type=hidden]),select,button,.fx-papel')]
                        .filter(el => { const b = el.getBoundingClientRect();
                            return b.width && (b.left < r.left - 1 || b.right > r.right + 1); })
                        .map(el => el.getAttribute('aria-label') || el.textContent.trim());
                })""")
                self.assertFalse(fora, fora)
                self.assertLessEqual(p.locator(".fx-corpo").evaluate("el => el.scrollWidth"),
                                     p.locator(".fx-corpo").evaluate("el => el.clientWidth") + 1)
                if os.environ.get("E2E_EVIDENCIAS"):
                    from pathlib import Path
                    pasta = Path(os.environ["E2E_EVIDENCIAS"])
                    pasta.mkdir(parents=True, exist_ok=True)
                    p.screenshot(path=str(pasta / f"campanha-{largura}.png"))
                p.get_by_role("button", name="Fechar campanha").click()
                p.locator("#modal-reserva").wait_for(state="hidden")

    def test_teclado_abre_fecha_e_devolve_foco(self):
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        link = p.get_by_role("link", name="Férias E2E", exact=True)
        link.focus()
        link.press("Enter")
        p.get_by_label("Nome da campanha").wait_for()
        p.keyboard.press("Shift+Tab")
        self.assertTrue(p.evaluate("document.getElementById('modal-conteudo').contains(document.activeElement)"))
        p.keyboard.press("Escape")
        p.locator("#modal-reserva").wait_for(state="hidden")
        self.assertEqual(p.evaluate("document.activeElement.textContent.trim()"), "Férias E2E")

    def test_duplicar_pede_decisao_sobre_dados_pendentes(self):
        from apps.marketing.models import Campanha
        p = self.page
        self._abrir()
        p.get_by_label("Nome da campanha").fill("Ainda escrevendo")
        p.once("dialog", lambda dialog: dialog.dismiss())
        p.get_by_role("button", name="Duplicar campanha", exact=True).click()
        self.assertEqual(p.input_value("#id_nome"), "Ainda escrevendo")
        self.assertEqual(Campanha.objects.count(), 1)

    def test_pagina_completa_descarta_com_uma_so_confirmacao(self):
        from django.urls import reverse
        p = self.page
        p.goto(self.url(reverse("marketing:detalhe", args=[self.campanha.pk])))
        p.get_by_label("Nome da campanha").fill("Alteração que será descartada")
        dialogs = []

        def aceitar(dialog):
            dialogs.append(dialog.type)
            dialog.accept()

        p.on("dialog", aceitar)
        p.get_by_role("button", name="Fechar campanha").click()
        p.wait_for_url(self.url(reverse("marketing:quadro")))
        self.assertEqual(dialogs, ["confirm"])
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.nome, "Férias E2E")

    def test_animacao_interrompida_nao_apaga_a_ficha_reaberta(self):
        p = self.page
        self._abrir()
        p.evaluate("() => { fecharModal(); abrirModal(); }")
        p.wait_for_timeout(600)
        self.assertTrue(p.get_by_label("Nome da campanha").is_visible())
        p.get_by_role("button", name="Fechar campanha").click()
        p.locator("#modal-reserva").wait_for(state="hidden")

    def test_animacao_termina_com_quadros_lentos_e_ao_voltar_a_aba(self):
        # Relógio determinístico somente para o motor: reproduz 30 fps, 1 fps e
        # aba suspensa sem depender da velocidade da máquina de CI.
        resultado = self.page.evaluate("""() => {
          const raf = window.requestAnimationFrame, cancel = window.cancelAnimationFrame;
          const resultados = [];
          try {
            for (const passo of [1000/30, 1000, 60000]) {
              for (const bounce of [0, .25, -.2]) {
                let callback, tempo = 0, fim = 0, valores = [];
                window.requestAnimationFrame = fn => { callback = fn; return 1; };
                window.cancelAnimationFrame = () => { callback = null; };
                Fluid.spring({from:1, to:0, response:.22, bounce,
                  onUpdate:v => valores.push(v), onComplete:() => fim++});
                for (let i=0; callback && i<100; i++) {
                  const atual = callback; callback = null; atual(tempo); tempo += passo;
                }
                resultados.push({passo, bounce, fim, ultimo:valores.at(-1),
                  estavel:valores.every(v => Number.isFinite(v) && Math.abs(v) <= 1.01)});
              }
            }
          } finally { window.requestAnimationFrame = raf; window.cancelAnimationFrame = cancel; }
          return resultados;
        }""")
        for caso in resultado:
            self.assertEqual(caso["fim"], 1, caso)
            self.assertEqual(caso["ultimo"], 0, caso)
            self.assertTrue(caso["estavel"], caso)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class LeadManualE2ETests(_FunilComercialMixin, _BaseE2E):
    """Contato, campanha, erro recuperável e mudança de etapa no navegador."""

    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        from apps.comercial.models import Campanha, MotivoPerda
        from apps.marketing.models import Campanha as Planejamento
        from apps.nucleo.models import ModuloContratado, Usuario
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.user = Usuario.objects.create_superuser(username="lead-ui", password="forte-123-abc")
        self.campanha = Campanha.objects.create(nome="Férias de novembro E2E", codigo="ferias-lead-ui", criado_por=self.user)
        self.plano = Planejamento.objects.create(nome="Plano das férias E2E", anuncio=self.campanha)
        MotivoPerda.objects.get_or_create(nome="Mudou de planos")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("lead-ui", "forte-123-abc")
        self.page.goto(self.url(f"/crm/comercial/?campanha={self.campanha.pk}"))

    def _abrir(self):
        self.page.get_by_role("link", name="+ Novo lead", exact=True).click()
        self.page.get_by_label("Nome do contato").wait_for()

    def test_cancelar_nao_cria_e_duplo_clique_nao_duplica(self):
        from apps.comercial.models import Oportunidade
        from apps.nucleo.models import Pessoa
        p = self.page
        self._abrir()
        p.get_by_role("button", name="Cancelar", exact=True).click()
        p.locator("#modal-reserva").wait_for(state="hidden")
        self.assertFalse(Oportunidade.objects.exists())
        self._abrir()
        p.get_by_label("Nome do contato").fill("Família E2E")
        p.get_by_role("button", name="Salvar e abrir atendimento").click(click_count=2)
        p.get_by_role("heading", name="Família E2E", exact=True).wait_for()
        op = Oportunidade.objects.get()
        self.assertEqual(op.campanha, self.campanha)
        self.assertEqual(Pessoa.objects.filter(nome="Família E2E").count(), 1)
        self.assertIn(f"campanha={self.campanha.pk}", p.get_by_role("link", name="Voltar ao funil").get_attribute("href"))

    def test_erro_preserva_contato_e_valor_e_foca_campo(self):
        from decimal import Decimal

        from apps.comercial.models import Oportunidade
        from apps.nucleo.models import Pessoa
        p = self.page
        self._abrir()
        p.get_by_label("Nome do contato").fill("Contato preservado E2E")
        p.get_by_label("O que a pessoa procura?").fill("Quero um quarto com vista")
        p.get_by_text("Mais informações: período, pessoas e responsável", exact=True).click()
        p.get_by_label("Valor estimado").fill("valor inválido")
        p.get_by_role("button", name="Salvar e abrir atendimento").click()
        p.get_by_text("Confira os campos indicados.", exact=False).wait_for()
        self.assertEqual(p.get_by_label("Nome do contato").input_value(), "Contato preservado E2E")
        self.assertEqual(p.get_by_label("Valor estimado").input_value(), "valor inválido")
        p.wait_for_function("document.activeElement.name === 'valor_estimado'")
        self.assertEqual(p.evaluate("document.activeElement.name"), "valor_estimado")
        self.assertFalse(Pessoa.objects.filter(nome="Contato preservado E2E").exists())
        self.assertFalse(Oportunidade.objects.exists())
        p.once("dialog", lambda dialog: dialog.dismiss())
        p.get_by_role("button", name="Cancelar", exact=True).click()
        self.assertTrue(p.get_by_label("Nome do contato").is_visible())
        p.get_by_label("Valor estimado").fill("1.500,50")
        p.get_by_role("button", name="Salvar e abrir atendimento").click()
        p.get_by_role("heading", name="Contato preservado E2E", exact=True).wait_for()
        self.assertEqual(Oportunidade.objects.get().valor_estimado, Decimal("1500.50"))

    def test_busca_contato_existente_sem_cadastro_repetido(self):
        from apps.comercial.models import Oportunidade
        from apps.nucleo.models import Pessoa
        pessoa = Pessoa.objects.create(nome="Cliente Recorrente E2E")
        p = self.page
        self._abrir()
        p.get_by_label("Já cadastrado", exact=True).check()
        p.get_by_role("combobox", name="Buscar contato cadastrado").fill("Recorrente")
        p.get_by_role("option", name="Cliente Recorrente E2E").click()
        p.get_by_role("button", name="Salvar e abrir atendimento").click()
        p.get_by_role("heading", name="Cliente Recorrente E2E", exact=True).wait_for()
        self.assertEqual(Oportunidade.objects.get().pessoa, pessoa)
        self.assertEqual(Pessoa.objects.filter(nome=pessoa.nome).count(), 1)

    def test_formulario_cabe_no_celular_e_desktop(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                self._abrir()
                p.wait_for_function("getComputedStyle(document.querySelector('#modal-conteudo')).transform === 'none'")
                geometria = p.evaluate("""() => {
                    const caixa = document.querySelector('#modal-conteudo');
                    const corpo = caixa.querySelector('.modal-corpo').getBoundingClientRect();
                    const rodape = caixa.querySelector('.modal-acoes').getBoundingClientRect();
                    const fechar = caixa.querySelector('.modal-fechar'), r = fechar.getBoundingClientRect();
                    return {largura: document.documentElement.scrollWidth, viewport: innerWidth,
                            corpo: corpo.height, rodape: rodape.bottom, altura: innerHeight,
                            topo: caixa.getBoundingClientRect().top,
                            fechar: fechar.contains(document.elementFromPoint(r.left+r.width/2, r.top+r.height/2))};
                }""")
                self.assertLessEqual(geometria["largura"], geometria["viewport"] + 1)
                self.assertGreater(geometria["corpo"], 280)
                self.assertLessEqual(geometria["rodape"], geometria["altura"] + 1)
                self.assertGreaterEqual(geometria["topo"], 0)
                self.assertTrue(geometria["fechar"])
                self.assertEqual(p.get_by_label("Nome do contato").evaluate("el => getComputedStyle(el).fontSize"), "16px")
                evidencia = os.environ.get("E2E_EVIDENCIAS")
                if evidencia:
                    from pathlib import Path
                    destino = Path(evidencia)
                    destino.mkdir(parents=True, exist_ok=True)
                    p.screenshot(path=str(destino / f"lead-{largura}.png"))
                p.get_by_text("Mais informações: período, pessoas e responsável", exact=True).click()
                self.assertLessEqual(p.locator("#modal-conteudo .modal-acoes").bounding_box()["y"] +
                                     p.locator("#modal-conteudo .modal-acoes").bounding_box()["height"], 845)
                self.assertTrue(p.get_by_role("button", name="Fechar cadastro de lead").is_visible())
                p.get_by_role("button", name="Cancelar", exact=True).click()
                p.locator("#modal-reserva").wait_for(state="hidden")

    def test_marketing_abre_apenas_leads_da_campanha(self):
        from django.urls import reverse

        from apps.comercial import services
        from apps.nucleo.models import Pessoa
        p = self.page
        for nome, campanha in (("Interessado das férias E2E", self.campanha), ("Outra campanha E2E", None)):
            services.criar_oportunidade(usuario=self.user, pessoa=Pessoa.objects.create(nome=nome),
                                       titulo="Proposta", campanha=campanha, disparar_crm=False)
        p.goto(self.url(reverse("marketing:detalhe", args=[self.plano.pk])))
        p.get_by_text("Interessados e reservas", exact=True).click()
        p.get_by_role("link", name="Ver leads desta campanha").click()
        p.get_by_role("link", name="Interessado das férias E2E", exact=True).wait_for()
        self.assertEqual(p.locator(".funil-card").count(), 1)
        p.get_by_role("link", name="Ver planejamento da campanha").click()
        p.get_by_role("heading", name="Plano das férias E2E", exact=True).wait_for()

    def test_mover_no_celular_preserva_campanha_e_valida_perda(self):
        from apps.comercial import services
        from apps.comercial.models import EtapaFunil, Oportunidade
        from apps.nucleo.models import Pessoa
        op = services.criar_oportunidade(usuario=self.user, pessoa=Pessoa.objects.create(nome="Mover com toque E2E"),
                                        titulo="Proposta", campanha=self.campanha, disparar_crm=False)
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.reload()
        p.get_by_role("link", name="Mover Mover com toque E2E para outra etapa").click()
        p.get_by_role("heading", name="Mover atendimento").wait_for()
        perdida = EtapaFunil.objects.get(tipo="perdido")
        p.get_by_label("Próxima etapa").select_option(str(perdida.pk))
        p.get_by_role("button", name="Salvar etapa", exact=True).click()
        p.get_by_text("Escolha o motivo para registrar a perda.", exact=True).wait_for()
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)
        p.get_by_label("Motivo da perda").select_option(label="Mudou de planos")
        with p.expect_navigation():
            p.get_by_role("button", name="Salvar etapa", exact=True).click()
        p.locator("#funilBoard").wait_for()
        self.assertIn(f"campanha={self.campanha.pk}", p.url)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)

    def test_teclado_e_escape_devolvem_foco(self):
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        p.get_by_role("link", name="+ Novo lead", exact=True).focus()
        p.keyboard.press("Enter")
        p.get_by_role("heading", name="Novo lead", exact=True).wait_for()
        p.keyboard.press("Escape")
        p.locator("#modal-reserva").wait_for(state="hidden")
        self.assertEqual(p.evaluate("document.activeElement.textContent.trim()"), "+ Novo lead")


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver docstring)")
class GovernancaFilaE2ETests(_FunilComercialMixin, _BaseE2E):
    """O perfil de camareira recebe o próximo passo e consegue corrigir um relato."""

    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        from django.urls import reverse

        from apps.governanca import services
        from apps.nucleo.models import UH, ModuloContratado, TipoUH, Usuario

        for codigo in ("governanca", "manutencao", "reservas"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        supervisora = Usuario.objects.create_superuser(username="supervisora-fila-e2e", password=None)
        self.camareira = Usuario.objects.create_user(username="camareira-fila-e2e", password="senha-forte-123")
        self.camareira.modulos.add(ModuloContratado.objects.get(codigo="governanca"))
        tipo = TipoUH.objects.create(nome="Quarto da fila E2E", tarifa_base="300.00")
        self.uh = UH.objects.create(numero="Quarto 21", tipo=tipo)
        self.tarefa = services.abrir_faxina(self.uh, usuario=supervisora)
        self.tarefa.camareira = self.camareira
        self.tarefa.save(update_fields=["camareira"])
        self.fila_url = reverse("governanca:minha_fila")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self._login(self.camareira.username, "senha-forte-123")

    def _abrir_relato(self):
        self.page.get_by_role("link", name="Reportar problema", exact=True).click()
        self.page.locator("#modal-conteudo textarea[name=descricao]").wait_for()

    def test_entrada_direta_e_orientacao_acompanham_a_limpeza(self):
        from playwright.sync_api import expect

        p = self.page
        self.assertTrue(p.url.endswith(self.fila_url))
        expect(p.locator(".gov-orientacao")).to_contain_text("1 quarto")
        p.get_by_role("button", name="Começar", exact=True).click(click_count=2)
        expect(p.get_by_role("button", name="Concluir", exact=True)).to_be_visible()
        expect(p.locator(".gov-orientacao")).to_contain_text("Você está no Quarto 21")
        p.get_by_role("button", name="Concluir", exact=True).click()
        expect(p.locator(".gov-orientacao")).to_contain_text("Você terminou")
        expect(p.get_by_text("Nenhum quarto na sua fila agora.", exact=True)).to_be_visible()
        expect(p.get_by_role("heading", name="Já entreguei hoje 1")).to_be_visible()
        self.tarefa.refresh_from_db()
        self.assertEqual(self.tarefa.status, "concluida")

    def test_erro_no_relato_continua_aberto_e_correcao_cria_um_chamado(self):
        from playwright.sync_api import expect

        from apps.manutencao.models import OrdemServico

        self._abrir_relato()
        p = self.page
        campo = p.locator("#modal-conteudo textarea[name=descricao]")
        campo.fill("   ")
        p.get_by_role("button", name="Abrir chamado", exact=True).click()
        expect(p.locator("#modal-conteudo .erro")).to_contain_text("Descreva o problema")
        expect(campo).to_be_focused()
        campo.fill("Lâmpada do banheiro não acende.")
        p.get_by_role("button", name="Abrir chamado", exact=True).click(click_count=2)
        expect(p.locator("#modal-conteudo form")).to_be_hidden()
        ordem = OrdemServico.objects.get()
        self.assertEqual(ordem.descricao, "Lâmpada do banheiro não acende.")
        self.assertEqual(ordem.uh_id, self.uh.pk)
        self.assertFalse(ordem.bloqueia_uh)
        expect(p.get_by_text("Ele já aparece na lista da manutenção.", exact=False)).to_be_visible()

    def test_cancelar_pergunta_sobre_o_texto_e_nao_abre_chamado(self):
        from playwright.sync_api import expect

        from apps.manutencao.models import OrdemServico

        self._abrir_relato()
        p = self.page
        campo = p.locator("#modal-conteudo textarea[name=descricao]")
        campo.fill("Chuveiro pingando")
        p.once("dialog", lambda dialog: dialog.dismiss())
        p.keyboard.press("Escape")
        expect(campo).to_have_value("Chuveiro pingando")
        p.once("dialog", lambda dialog: dialog.accept())
        p.keyboard.press("Escape")
        expect(p.locator("#modal-conteudo form")).to_be_hidden()
        expect(p.get_by_role("link", name="Reportar problema", exact=True)).to_be_focused()
        self.assertFalse(OrdemServico.objects.exists())

    def test_relato_cabe_e_tem_botoes_visiveis_nas_quatro_larguras(self):
        from pathlib import Path

        from playwright.sync_api import expect

        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(self.fila_url))
                self._abrir_relato()
                expect(p.locator("#modal-conteudo")).to_be_visible()
                p.wait_for_function("getComputedStyle(document.getElementById('modal-conteudo')).transform === 'none'")
                medidas = p.evaluate('''() => {
                    const caixa=document.getElementById('modal-conteudo').getBoundingClientRect();
                    const enviar=document.querySelector('#modal-conteudo button[type=submit]');
                    const r=enviar.getBoundingClientRect();
                    return {largura:document.documentElement.scrollWidth,top:caixa.top,bottom:caixa.bottom,
                        acao:r.height,alvo:enviar.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),
                        bloqueado:document.body.classList.contains('sem-rolagem')};
                }''')
                self.assertLessEqual(medidas["largura"], largura+1)
                self.assertGreaterEqual(medidas["top"], -1)
                self.assertLessEqual(medidas["bottom"], 845)
                self.assertTrue(medidas["alvo"] and medidas["bloqueado"])
                if largura <= 820:
                    self.assertGreaterEqual(medidas["acao"], 44)
                if os.environ.get("E2E_EVIDENCIAS"):
                    pasta = Path(os.environ["E2E_EVIDENCIAS"])
                    pasta.mkdir(parents=True, exist_ok=True)
                    p.screenshot(path=str(pasta / f"governanca-relato-{largura}.png"))
                p.get_by_role("button", name="Cancelar", exact=True).click()
                expect(p.locator("#modal-conteudo form")).to_be_hidden()


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
        p.get_by_role("button", name="Carrinho (0) R$ 0,00", exact=True).click()
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
        from apps.site.models import ConfiguracaoSite
        cfg = ConfiguracaoSite.load()
        cfg.whatsapp, cfg.telefone, cfg.contato_verificado = "554920550005", "(49) 2055-0005", True
        cfg.save()

    def _fim_da_pagina(self):
        self.page.evaluate("() => window.scrollTo(0, document.scrollingElement.scrollHeight)")
        self.page.wait_for_timeout(250)

    def test_cabecalho_cabe_no_tablet_e_menu_curto_permite_reservar(self):
        p = self.page
        p.goto(self.url("/"))
        p.evaluate("document.fonts.ready")
        # A instalação publicada acrescenta este comparador ao cabeçalho.
        # Ele também precisa caber, sem alterar o proxy durante o teste.
        p.evaluate("""() => {
            for (const selector of ['header nav', '#mobileMenu > div']) {
                const nav = document.querySelector(selector), link = document.createElement('a');
                link.href = '#'; link.textContent = 'Versão anterior';
                link.className = nav.querySelector('a').className;
                nav.append(link);
            }
        }""")
        for largura in (320, 390, 821, 1024, 1152, 1280, 1366, 1440, 1600):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 900})
                self.assertEqual(p.locator("#menuBtn").is_visible(), largura < 1440)
                caixas = p.locator("header a, header button").evaluate_all("""els => els
                    .map(e => { const r=e.getBoundingClientRect();
                        return {nome:e.textContent.trim(),left:r.left,right:r.right,width:r.width,height:r.height}; })
                    .filter(r => r.width && r.height).sort((a,b) => a.left-b.left)""")
                for i, caixa in enumerate(caixas):
                    self.assertGreaterEqual(caixa["left"], 0, caixa)
                    self.assertLessEqual(caixa["right"], largura, caixa)
                    if i:
                        self.assertGreaterEqual(caixa["left"], caixas[i - 1]["right"] - 1, caixas)
        p.set_viewport_size({"width": 1024, "height": 390})
        p.get_by_role("button", name="Abrir menu", exact=True).click()
        cta = p.locator("#mobileMenu").get_by_role("link", name="Fazer Reserva", exact=True)
        cta.scroll_into_view_if_needed()
        medida = cta.evaluate("""el => {
            const r=el.getBoundingClientRect(), alvo=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
            return {top:r.top,bottom:r.bottom,header:document.querySelector('header').getBoundingClientRect().bottom,
                acessivel:alvo===el || el.contains(alvo)};
        }""")
        self.assertGreaterEqual(medida["top"], medida["header"])
        self.assertLessEqual(medida["bottom"], 390)
        self.assertTrue(medida["acessivel"])
        p.set_viewport_size({"width": 1440, "height": 900})
        p.wait_for_function("document.body.style.overflow !== 'hidden' && document.querySelector('#menuBtn').getAttribute('aria-expanded') === 'false'")
        self.assertGreater(p.evaluate("document.activeElement.getBoundingClientRect().width"), 0)

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
        # A escolha dos cookies vem primeiro: no celular o botão só entra em cena
        # depois dela (regra do próprio whatsapp.html), e a folga do rodapé só
        # faz diferença com o botão na tela.
        p.wait_for_selector("#consentimento:not([hidden])", timeout=10000)
        p.click("[data-consent-aceitar]")
        p.wait_for_selector(".zap-flutuante", timeout=10000)
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

        # Fechada a gaveta, o aviso volta — ele ainda precisa ser respondido.
        # O botão do WhatsApp não: no celular ele espera a escolha dos cookies
        # (whatsapp.html), e aqui ela ainda não foi feita.
        p.click("#menuBtn")
        p.wait_for_timeout(500)
        aviso = p.evaluate(
            "() => getComputedStyle(document.getElementById('consentimento')).visibility")
        self.assertEqual(aviso, "visible", "o aviso não voltou ao fechar a gaveta")

        # Respondido o aviso, o botão entra; e a gaveta volta a ser a única
        # coisa na tela enquanto está aberta.
        p.click("[data-consent-aceitar]")
        p.wait_for_selector(".zap-flutuante", timeout=10000)
        p.click("#menuBtn")
        p.wait_for_timeout(500)
        com_gaveta = p.evaluate(
            "() => getComputedStyle(document.querySelector('.zap-flutuante')).visibility")
        self.assertEqual(com_gaveta, "hidden", "o WhatsApp ficou por cima da gaveta")
        p.click("#menuBtn")
        p.wait_for_timeout(500)
        sem_gaveta = p.evaluate(
            "() => getComputedStyle(document.querySelector('.zap-flutuante')).visibility")
        self.assertEqual(sem_gaveta, "visible", "o WhatsApp não voltou ao fechar a gaveta")
