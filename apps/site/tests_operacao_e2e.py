"""Fluxos de operação e regressões visuais com dados fictícios.

Testa a tela e o efeito no estoque/caixa, contra PostgreSQL descartável.
Os gateways são simulados; nenhuma mensagem ou pagamento real é enviado.
Roda no CI junto de tests_e2e; sem Playwright, segue o mesmo skip explícito.
"""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import saldo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E, _FunilComercialMixin

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(
    PAGAMENTOS_GATEWAY="simulado",
    EMAIL_GATEWAY="simulado",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_ENVIO_ASSINCRONO=False,
)
class OperacaoUsabilidadeE2ETests(_FunilComercialMixin, _BaseE2E):
    LOCALE = "pt-BR"

    def test_navegacao_dos_modulos_mostra_todas_as_opcoes_sem_cortar(self):
        p = self.page
        for rota in ("escala:grade", "comercial:funil", "marketing:quadro", "estoque:posicao"):
            for largura in (320, 390, 821, 1440):
                with self.subTest(rota=rota, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(rota)))
                    p.evaluate("document.fonts.ready")
                    grupos = p.locator(".seg-filtro, .segmentado, .est-abas").evaluate_all("""els => els.map(el => {
                        const r = el.getBoundingClientRect();
                        return {largura:el.clientWidth, conteudo:el.scrollWidth,
                            fora:[...el.querySelectorAll('a,button')].filter(a => {
                                const b=a.getBoundingClientRect();
                                return b.left<r.left-1 || b.right>r.right+1 || b.top<r.top-1 || b.bottom>r.bottom+1;
                            }).map(a=>a.textContent.trim())};
                    })""")
                    self.assertTrue(grupos)
                    for grupo in grupos:
                        self.assertLessEqual(grupo["conteudo"], grupo["largura"] + 1)
                        self.assertFalse(grupo["fora"], grupo)

    def test_telas_acesso_mostram_formulario_com_e_sem_sessao(self):
        p = self.page
        paginas = [("login", [], "Entrar no sistema"),
                   ("senha_esqueci", [], "Esqueci minha senha"),
                   ("senha_enviada", [], "Confira seu e-mail"),
                   ("senha_trocada", [], "Senha trocada"),
                   ("password_reset_confirm", ["invalido", "invalido"], "Link expirado")]
        for conectado in (True, False):
            if not conectado:
                p.context.clear_cookies()
            for nome, args, titulo in paginas:
                for largura in (320, 390, 821, 1440):
                    with self.subTest(conectado=conectado, pagina=nome, largura=largura):
                        p.set_viewport_size({"width": largura, "height": 844})
                        p.goto(self.url(reverse(nome, args=args)))
                        expect(p.get_by_role("heading", name=titulo, exact=True)).to_be_visible()
                        p.wait_for_function("['.login-pagina', '.login-cartao'].every(s => getComputedStyle(document.querySelector(s)).opacity === '1')", timeout=6000)
                        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                        if nome == "senha_esqueci" and largura in (390, 1440) and conectado:
                            self._foto(f"senha-recuperacao-{largura}.png")

    def test_lps_so_confirmam_apos_gravar_e_permitem_corrigir_falha(self):
        from apps.comercial.models import Oportunidade, PaginaCaptacao

        p = self.page
        p.context.clear_cookies()
        paginas = [("fundador", "fundador"), ("fundador_2", "fundador-2"),
                   ("inauguracao", "inauguracao_31_10_2026")]
        for numero, (nome, slug) in enumerate(paginas):
            pagina = PaginaCaptacao.objects.create(
                nome=f"LP fictícia QA {numero}", slug=slug, status="publicada", criado_por=self.op
            )
            for largura in (320, 390, 1440):
                with self.subTest(pagina=nome, largura=largura):
                    cache.clear()
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(f"lp:{nome}")), wait_until="domcontentloaded")
                    if p.get_by_role("button", name="Recusar", exact=True).is_visible():
                        p.get_by_role("button", name="Recusar", exact=True).click()
                    form = p.locator("#formInaug" if nome == "inauguracao" else "#form-lista")
                    identidade = f"Contato LP QA {nome} {largura}"
                    telefone = f"49999{numero}{largura:04d}1"
                    form.locator("input[name=nome]").fill(identidade)
                    form.locator("input[name=whats]").fill(telefone)
                    if nome == "fundador":
                        form.locator("input[name=email]").fill(f"qa-{largura}@example.invalid")
                    form.locator("input[type=checkbox]").check()
                    enviar = form.locator("button").first
                    erro = form.locator("#formAlert" if nome == "inauguracao" else ".lp-captacao-erro")
                    endpoint = self.url(reverse(f"lp:{nome}_lead"))
                    # Tempo mínimo real do antirrobô; não desliga a defesa para o teste.
                    p.wait_for_timeout(1700)
                    with patch("apps.comercial.services.capturar_lead_site", side_effect=RuntimeError), p.expect_response(endpoint, timeout=6000) as resposta:
                        enviar.click()
                    self.assertEqual(resposta.value.status, 503)
                    expect(erro).to_be_visible()
                    expect(erro).to_be_focused()
                    expect(form.locator("input[name=nome]")).to_have_value(identidade)
                    expect(enviar).to_be_enabled()
                    self.assertFalse(Oportunidade.objects.filter(pessoa__nome=identidade).exists())
                    self._foto(f"lp-{nome}-erro-{largura}.png")
                    # HTTP 200 sem confirmação do CRM também deve manter o formulário.
                    p.route(endpoint, lambda rota: rota.fulfill(status=200, json={"ok": False}))
                    with p.expect_response(endpoint):
                        enviar.click()
                    expect(erro).to_be_visible()
                    expect(enviar).to_be_enabled()
                    p.unroute(endpoint)
                    form.locator("input[name=whats]").fill("20999990000")
                    with p.expect_response(endpoint) as invalido:
                        enviar.click()
                    self.assertEqual(invalido.value.status, 400)
                    expect(erro).to_contain_text("DDD 20 inválido")
                    expect(enviar).to_be_enabled()
                    self.assertFalse(Oportunidade.objects.filter(pessoa__nome=identidade).exists())
                    if largura == 390:
                        self._foto(f"lp-{nome}-dados-invalidos-390.png")
                    form.locator("input[name=whats]").fill(telefone)
                    with p.expect_response(endpoint):
                        enviar.click(click_count=2)
                    sucesso = p.locator("#ticketTitle" if nome == "inauguracao" else "#sucesso")
                    if nome == "inauguracao":
                        p.wait_for_function("document.querySelector('#card3d').classList.contains('flipped') && document.body.classList.contains('confirmado')", timeout=6000)
                    expect(sucesso).to_be_visible()
                    expect(sucesso).to_be_focused()
                    if nome == "inauguracao":
                        caixa = sucesso.bounding_box()
                        self.assertGreaterEqual(caixa["y"], 80)
                        self.assertLessEqual(caixa["y"] + caixa["height"], 844)
                    lead = Oportunidade.objects.get(pessoa__nome=identidade)
                    self.assertEqual(lead.pagina_captacao, pagina)
                    self.assertEqual("".join(c for c in lead.pessoa.telefone if c.isdigit()), telefone)
                    self.assertTrue(lead.pessoa.aceita_whatsapp)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    self._foto(f"lp-{nome}-sucesso-{largura}.png")
                    p.evaluate("localStorage.removeItem('vt_inaug_conf')")

    def setUp(self):
        super().setUp()
        from apps.comercial import services as comercial
        from apps.comercial.models import CampanhaEmail, EtapaFunil, PaginaCaptacao, TemplateEmail
        from apps.lavanderia import services as lavanderia
        from apps.lavanderia.models import ServicoLavanderia
        from apps.manutencao import services as manutencao
        from apps.nucleo.models import (
            UH,
            CategoriaProduto,
            ConfiguracaoReservas,
            FormaPagamento,
            Hospede,
            LocalEstoque,
            ModuloContratado,
            Pessoa,
            PosicaoCama,
            Produto,
            SessaoCaixa,
            TipoUH,
            Usuario,
            registrar_entrada,
        )
        from apps.nucleo.modulos import Modulo
        from apps.pagamentos.services import criar_cobranca
        from apps.portal.services import get_acesso
        from apps.reservas import services as reservas
        from apps.restaurante import services as restaurante

        cache.clear()
        self.op = Usuario.objects.create_superuser(
            username="operacao-e2e", password="forte-123-abc"
        )
        for codigo, _ in Modulo.choices:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )
        self.kind = TipoUH.objects.create(
            nome="QA Standard", tarifa_base=Decimal("300"), capacidade=4
        )
        self.room = UH.objects.create(numero="QA-01", tipo=self.kind)
        UH.objects.create(numero="QA-02", tipo=self.kind)
        quarto_hospedado = UH.objects.create(numero="QA-03", tipo=self.kind)
        for quarto in UH.objects.filter(tipo=self.kind):
            PosicaoCama.objects.create(uh=quarto, nome="Quarto", montagem_padrao="casal")
        self.guest = Pessoa.objects.create(
            nome="Hóspede fictício QA", email="guest@example.invalid"
        )
        Hospede.objects.create(pessoa=self.guest)
        self.cash, _ = FormaPagamento.objects.get_or_create(
            nome="QA Dinheiro", defaults={"tipo": "dinheiro"}
        )
        categoria = CategoriaProduto.objects.create(nome="QA Bebidas")
        self.shop = LocalEstoque.objects.create(nome="QA Loja", modulo="loja")
        self.kitchen = LocalEstoque.objects.create(nome="QA Restaurante", modulo="restaurante")
        self.product = Produto.objects.create(
            nome="QA Água", categoria=categoria, preco_venda=Decimal("7")
        )
        for local in (self.shop, self.kitchen):
            registrar_entrada(self.product, local, Decimal("20"), Decimal("2"), self.op)
        for modulo in ("reservas", "loja", "restaurante", "lavanderia", "nucleo"):
            SessaoCaixa.objects.create(operador=self.op, modulo=modulo, fundo_troco=Decimal("100"))
        self.today = timezone.localdate()
        self.hospedagem = reservas.criar_prereserva(
            uh=quarto_hospedado,
            checkin=self.today,
            checkout=self.today + timedelta(days=2),
            hospede=self.guest,
            usuario=self.op,
            valor_diaria=Decimal("300"),
        )
        reservas.confirmar_reserva(self.hospedagem.pk, self.op)
        self.hospedagem.refresh_from_db()
        with override_settings(FNRH_BLOQUEAR_CHECKIN=False):
            self.conta = self.hospedagem.fazer_checkin(self.op)
        self.acesso = get_acesso(self.hospedagem.pk)
        self.comanda = restaurante.abrir_comanda(self.op, self.kitchen, rotulo="Mesa da família QA")
        restaurante.adicionar_item(self.comanda, self.product, 2, self.op)
        self.ordem = lavanderia.abrir_ordem(self.op, cliente=self.guest)
        servico = ServicoLavanderia.objects.create(nome="Lavagem de camisa QA", preco=Decimal("12"))
        lavanderia.adicionar_item(self.ordem, servico, 1, self.op)
        self.chamado = manutencao.abrir_os(
            self.op, area="Piscina QA", titulo="Verificar iluminação da piscina QA"
        )
        etapa, _ = EtapaFunil.objects.get_or_create(nome="Atendimento QA")
        self.lead = comercial.criar_oportunidade(
            usuario=self.op,
            pessoa=self.guest,
            titulo="Fim de semana em família QA",
            etapa=etapa,
            checkin_previsto=self.today + timedelta(days=5),
            checkout_previsto=self.today + timedelta(days=7),
            adultos=2,
            hospedes=2,
            disparar_crm=False,
        )
        self.pagina = PaginaCaptacao.objects.create(
            nome="Campanha de férias QA", slug="ferias-qa", status="publicada", criado_por=self.op
        )
        self.template = TemplateEmail.objects.create(
            nome="Proposta QA",
            assunto="Sua estadia",
            corpo="Olá, {primeiro_nome}.",
            criado_por=self.op,
        )
        self.email = CampanhaEmail.objects.create(
            nome="Férias QA",
            assunto="Sua próxima estadia",
            corpo="Mensagem fictícia.",
            criado_por=self.op,
        )
        self.cobranca = criar_cobranca(
            self.op, valor=Decimal("150"), metodo="pix", descricao="Cobrança fictícia de teste"
        )
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("operacao-e2e", "forte-123-abc")

    def _foto(self, nome, full_page=False):
        destino = os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("""async () => {
                await document.fonts.ready;
                if (document.activeViewTransition) await document.activeViewTransition.finished;
                const transicoes = document.getAnimations().filter(a => {
                    const tempo = a.effect?.getComputedTiming();
                    return tempo && Number.isFinite(tempo.endTime) && tempo.endTime <= 3000;
                });
                await Promise.all(transicoes.map(a => a.finished.catch(() => {})));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }""")
            if full_page:
                self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(pasta / nome), full_page=full_page)

    def abrir(self, nome, *args):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.url(reverse(nome, args=args)))

    def test_grupo_adiciona_quarto_faz_checkin_e_recebe_pelas_telas(self):
        from apps.reservas.models import PagamentoConta, Reserva
        from apps.reservas.services import criar_grupo

        grupo = criar_grupo(
            rotulo="Família QA", titular=self.guest, checkin=self.today,
            checkout=self.today + timedelta(days=2), usuario=self.op,
        )
        p = self.page
        self.abrir("reservas:grupo_detalhe", grupo.pk)
        p.get_by_label("Quarto", exact=True).select_option(str(self.room.pk))
        p.get_by_label("Hóspede do quarto", exact=True).fill(self.guest.nome)
        p.get_by_role("option", name=self.guest.nome, exact=True).click()
        self.enviar("Adicionar quarto")
        reserva = Reserva.objects.get(grupo=grupo)
        self.assertEqual(reserva.uh_id, self.room.pk)
        self.enviar("Confirmar grupo")
        with override_settings(FNRH_BLOQUEAR_CHECKIN=False):
            self.enviar("Check-in do grupo")
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.HOSPEDADA)
        receber = p.get_by_role("form", name="Receber pagamento do grupo")
        receber.get_by_label("Forma de pagamento").select_option(str(self.cash.pk))
        receber.get_by_label("Valor recebido (R$)").fill("120,00")
        receber.get_by_label("Observação (opcional)").fill("Recebimento fictício QA")
        self.enviar("Registrar recebimento")
        self._foto("grupo-recebimento-390.png", full_page=True)
        expect(p.get_by_text("Recebimento do folio registrado.", exact=True)).to_be_visible()
        pagamento = PagamentoConta.objects.get(conta=grupo.folio)
        self.assertEqual(pagamento.valor, Decimal("120"))
        self.assertEqual(pagamento.movimento_caixa.valor, Decimal("120"))
        self.assertEqual(grupo.folio.saldo(), Decimal("480"))

    def test_grupo_fiscal_e_captacao_cabem_com_campos_utilizaveis(self):
        from apps.fiscal.models import DocumentoFiscal
        from apps.reservas.services import criar_grupo

        grupo = criar_grupo(
            rotulo="Famílias QA", titular=self.guest,
            checkin=self.today + timedelta(days=20),
            checkout=self.today + timedelta(days=22), usuario=self.op,
        )
        fiscal = DocumentoFiscal.objects.create(
            tipo="nfse", natureza="servico", descricao="Documento fictício QA",
            valor="300", gateway="simulado", chave="1234567890" * 4 + "1234", criado_por=self.op,
        )
        p = self.page
        rotas = (("reservas:grupo_detalhe", grupo.pk, "grupo"),
                 ("fiscal:detalhe", fiscal.pk, "fiscal"),
                 ("captacao:publica", self.pagina.slug, "captacao"))
        for rota, chave, nome in rotas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(rota, args=[chave])), wait_until="networkidle")
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    if nome == "grupo":
                        for campo in p.locator(".grupo-form input:visible, .grupo-form select").all():
                            caixa = campo.bounding_box()
                            self.assertGreaterEqual(caixa["width"], 180)
                            self.assertLessEqual(caixa["x"] + caixa["width"], largura)
                    if nome == "fiscal":
                        chave_fiscal = p.get_by_text(fiscal.chave, exact=True).bounding_box()
                        self.assertLessEqual(chave_fiscal["x"] + chave_fiscal["width"], largura)
                    if nome == "captacao":
                        aceitar = p.locator("input[name=consent]").bounding_box()
                        self.assertLessEqual(aceitar["width"], 24)
                        self.assertGreaterEqual(aceitar["width"], 18)
                        for campo in p.locator(".datas input").all():
                            self.assertGreaterEqual(campo.bounding_box()["width"], 180)
                    self._foto(f"{nome}-final-{largura}.png", full_page=True)

    def test_captacao_publica_corrige_datas_preserva_campos_e_atribui_campanha(self):
        from apps.comercial.models import Campanha, Oportunidade

        campanha = Campanha.objects.create(
            nome="Férias de novembro QA", codigo="novembro-qa", provedor="outro",
            pagina_captacao=self.pagina, criado_por=self.op,
        )
        p = self.page
        p.context.clear_cookies()
        p.set_viewport_size({"width": 320, "height": 844})
        url = self.url(reverse("captacao:publica", args=[self.pagina.slug])) + "?utm_campaign=novembro-qa&utm_source=qa"
        p.goto(url, wait_until="networkidle")
        p.get_by_role("button", name="Recusar", exact=True).click()
        p.get_by_label("Seu nome", exact=True).fill("Contato público fictício QA")
        p.get_by_label("WhatsApp (com DDD)", exact=True).fill("(49) 99999-1234")
        p.get_by_label("E-mail (opcional)", exact=True).fill("publico-qa@example.invalid")
        inicio = self.today + timedelta(days=14)
        p.get_by_label("Entrada", exact=True).fill(inicio.isoformat())
        p.get_by_label("Saída", exact=True).fill((inicio - timedelta(days=1)).isoformat())
        p.get_by_label("Quantas pessoas?", exact=True).select_option("4")
        p.locator("input[name=consent]").check()
        # O antirrobô de produção exige dois segundos de preenchimento real.
        p.wait_for_timeout(2100)
        with p.expect_navigation():
            p.locator(".form button[type=submit]").click()
        expect(p.get_by_text("A saída precisa ser depois da entrada.", exact=True)).to_be_visible()
        expect(p.get_by_label("Seu nome", exact=True)).to_have_value("Contato público fictício QA")
        expect(p.locator("input[name=consent]")).to_be_checked()
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())
        self._foto("captacao-erro-320.png", full_page=True)
        p.get_by_label("Saída", exact=True).fill((inicio + timedelta(days=2)).isoformat())
        p.wait_for_timeout(2100)
        with p.expect_navigation():
            p.locator(".form button[type=submit]").click()
        expect(p.get_by_role("heading", name="Recebemos o seu contato! 🥂")).to_be_visible()
        lead = Oportunidade.objects.get(pagina_captacao=self.pagina)
        self.assertEqual(lead.campanha_id, campanha.pk)
        self.assertEqual(lead.hospedes, 4)
        self.assertEqual(lead.checkin_previsto, inicio)
        self.assertEqual(lead.checkout_previsto, inicio + timedelta(days=2))
        self.assertTrue(lead.pessoa.aceita_email)
        self.assertTrue(lead.pessoa.aceita_whatsapp)

    def enviar(self, nome):
        with self.page.expect_navigation():
            self.page.get_by_role("button", name=nome, exact=True).click()

    def test_estoque_recusa_excesso_preserva_campos_e_transfere(self):
        p = self.page
        self.abrir("estoque:transferencia")
        p.locator("#id_produto").fill("QA Água")
        p.get_by_role("option", name="QA Água", exact=False).click()
        p.get_by_role("radiogroup", name="2. Sai de").locator("label").filter(
            has_text="QA Loja"
        ).click()
        p.get_by_role("radiogroup", name="3. Vai para").locator("label").filter(
            has_text="QA Restaurante"
        ).click()
        p.locator("#id_quantidade").fill("25")
        self.enviar("Transferir")
        expect(p.get_by_text("Saldo insuficiente", exact=False)).to_be_visible()
        self._foto("estoque-recusa-390.png", full_page=True)
        expect(p.locator("#id_quantidade")).to_have_value("25")
        expect(p.locator("input[name=produto]")).to_have_value(str(self.product.pk))
        expect(p.locator(f'input[name=origem][value="{self.shop.pk}"]')).to_be_checked()
        expect(p.locator(f'input[name=destino][value="{self.kitchen.pk}"]')).to_be_checked()
        self.assertEqual(saldo(self.product, self.shop), Decimal("20"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("18"))
        p.locator("#id_quantidade").fill("3")
        self.enviar("Transferir")
        self.assertEqual(saldo(self.product, self.shop), Decimal("17"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("21"))

    def test_loja_cobra_uma_vez_e_baixa_estoque(self):
        from apps.loja.models import Venda

        p = self.page
        self.abrir("loja:pdv")
        produto = p.locator(".pdv-produto").filter(has_text="QA Água")
        produto.click()
        produto.click()
        p.get_by_role("button", name="Carrinho (2) R$ 14,00", exact=True).click()
        p.locator(".pdv-finalizar").click()
        expect(p.get_by_text("Escolha a forma de pagamento.", exact=True)).to_be_visible()
        self.assertEqual(Venda.objects.count(), 0)
        p.locator("select[x-model=forma_id]").select_option(str(self.cash.pk))
        with p.expect_navigation():
            p.locator(".pdv-finalizar").click(click_count=2)
        venda = Venda.objects.get()
        self.assertEqual(venda.total, Decimal("14"))
        self.assertEqual(venda.movimento_caixa.valor, Decimal("14"))
        self.assertEqual(saldo(self.product, self.shop), Decimal("18"))
        total = p.get_by_text("Total da venda: R$ 14,00", exact=True)
        expect(total).to_be_visible()
        medidas = total.bounding_box()
        self.assertLessEqual(medidas["x"] + medidas["width"], 390)
        self._foto("loja-venda-390.png", full_page=True)

    def test_ajuste_zero_mostra_o_saldo_e_registra_a_diferenca(self):
        from apps.nucleo.models import MovimentoEstoque

        p = self.page
        self.abrir("estoque:ajuste")
        p.locator("#id_produto").fill("QA Água")
        p.get_by_role("option", name="QA Água", exact=False).click()
        p.locator("label.est-local-opt").filter(has_text="QA Loja").click()
        p.locator("#id_quantidade").fill("0")
        p.locator("#id_motivo").fill("Contagem fictícia: prateleira vazia.")
        expect(p.locator(".est-previa-destaque dd")).to_have_text("0 un")
        self.enviar("Registrar ajuste")
        self.assertEqual(saldo(self.product, self.shop), Decimal("0"))
        movimento = MovimentoEstoque.objects.filter(produto=self.product, local=self.shop).latest(
            "pk"
        )
        self.assertEqual(movimento.tipo, MovimentoEstoque.Tipo.AJUSTE)
        self.assertEqual(movimento.quantidade, Decimal("-20"))

    def test_restaurante_fecha_comanda_com_saldo_e_caixa_corretos(self):
        p = self.page
        self.abrir("restaurante:comanda", self.comanda.pk)
        p.locator(".pdv-produto").filter(has_text="QA Água").click()
        expect(p.locator("#comanda-itens .comanda-total-linha")).to_contain_text("21,00")
        p.locator("select[name=forma]").select_option(str(self.cash.pk))
        self.enviar("Fechar comanda")
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "fechada")
        self.assertEqual(self.comanda.total(), Decimal("21"))
        self.assertEqual(self.comanda.movimento_caixa.valor, Decimal("21"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("17"))
        expect(p.get_by_role("button", name="Fechar comanda")).to_have_count(0)
        self._foto("restaurante-fechada-390.png", full_page=True)

    def test_lavanderia_avanca_e_cobra_as_pecas(self):
        p = self.page
        self.abrir("lavanderia:ordem", self.ordem.pk)
        p.locator(".pdv-produto").filter(has_text="Lavagem de camisa QA").click()
        expect(p.locator("#ordem-itens .comanda-total-linha")).to_contain_text("24,00")
        self.enviar("Enviar para lavagem")
        self.enviar("Marcar como pronta")
        p.locator("select[name=forma]").select_option(str(self.cash.pk))
        self.enviar("Entregar e cobrar")
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "entregue")
        self.assertEqual(self.ordem.total(), Decimal("24"))
        self.assertEqual(self.ordem.movimento_caixa.valor, Decimal("24"))
        self._foto("lavanderia-entregue-390.png", full_page=True)

    def test_manutencao_registra_resolucao_e_custo(self):
        p = self.page
        self.abrir("manutencao:detalhe", self.chamado.pk)
        self.enviar("Iniciar (em andamento)")
        p.locator("input[name=custo_maodeobra]").fill("25.50")
        p.locator("input[name=custo_pecas]").fill("10")
        p.locator("textarea[name=resolucao]").fill("Lâmpada substituída e funcionamento conferido.")
        self.enviar("Concluir")
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, "concluida")
        self.assertEqual(self.chamado.custo_total, Decimal("35.50"))
        self.assertIn("funcionamento conferido", self.chamado.resolucao)
        self._foto("manutencao-concluida-390.png", full_page=True)

    def test_portal_envia_pedido_limpeza_e_manutencao(self):
        from apps.governanca.models import TarefaGovernanca
        from apps.manutencao.models import OrdemServico
        from apps.portal.models import SolicitacaoPortal
        from apps.restaurante.models import Comanda

        p = self.page
        p.context.clear_cookies()
        self.abrir("portal:home", self.acesso.token)
        self.enviar("Enviar pedido ao quarto")
        expect(p.get_by_text("Escolha ao menos um item.", exact=True)).to_be_visible()
        self.assertEqual(SolicitacaoPortal.objects.count(), 0)
        p.locator(f"input[name=qtd_{self.product.pk}]").fill("2")
        self.enviar("Enviar pedido ao quarto")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
        pedido = Comanda.objects.exclude(pk=self.comanda.pk).get()
        self.assertEqual(pedido.total(), Decimal("14"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("16"))
        self.enviar("Pedir limpeza extra")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="limpeza").count(), 1)
        self.assertTrue(
            TarefaGovernanca.objects.filter(uh_id=self.hospedagem.uh_id, origem="portal").exists()
        )
        p.locator("#pt-descricao").fill("Ar-condicionado sem resfriar no quarto QA.")
        self.enviar("Chamar a manutenção")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="manutencao").count(), 1)
        self.assertTrue(
            OrdemServico.objects.filter(
                uh_id=self.hospedagem.uh_id, descricao__contains="sem resfriar"
            ).exists()
        )
        self._foto("portal-pedidos-390.png", full_page=True)

    def test_pagamento_publico_aceita_formulario_local_e_barra_origem_externa(self):
        p = self.page
        p.context.clear_cookies()
        self.abrir("pagamentos:pagar", self.cobranca.token)
        token = p.locator("input[name=csrfmiddlewaretoken]").input_value()
        resposta = p.request.post(
            self.url(reverse("pagamentos:pagar_simular", args=[self.cobranca.token])),
            form={"csrfmiddlewaretoken": token},
            headers={"Origin": "https://origem-invalida.example"},
        )
        self.assertEqual(resposta.status, 403)
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, "pendente")
        self.enviar("Já paguei")
        expect(p.locator(".pay-ok")).to_contain_text("Pagamento confirmado")
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, "pago")
        self._foto("pagamento-simulado-390.png", full_page=True)

    def test_comparacao_de_quartos_fecha_com_escape(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(reverse("comercial:oportunidade", args=[self.lead.pk])))
                p.locator(".pq-cmp-check input").nth(0).check()
                p.locator(".pq-cmp-check input").nth(1).check()
                p.get_by_role("button", name="Comparar ⇄", exact=True).click()
                p.locator("#modal-conteudo .comparacao-quartos").wait_for()
                self._conferir_modal(largura)
                for caixa in p.locator(".pq-cmp-bar button").all():
                    medidas = caixa.bounding_box()
                    self.assertGreaterEqual(medidas["x"], 0)
                    self.assertLessEqual(medidas["x"] + medidas["width"], largura)
                p.get_by_role("dialog").get_by_role("button", name="Fechar", exact=True).last.click(
                    trial=True
                )
                self._foto(f"comparador-aberto-{largura}.png")
                p.keyboard.press("Escape")
                expect(p.locator("#modal-conteudo .comparacao-quartos")).to_be_hidden(timeout=2000)
                expect(p.get_by_role("button", name="Comparar ⇄", exact=True)).to_be_focused()
                self.assertFalse(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def test_confirmacao_email_mantem_foco_dentro_e_devolve_ao_fechar(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(reverse("comercial:enviar_email_lead", args=[self.lead.pk])))
                p.locator("#id_destinatario").fill("guest@example.invalid")
                p.get_by_role("button", name="Enviar ao lead", exact=True).click()
                expect(p.get_by_role("dialog")).to_be_visible()
                self._conferir_modal(largura)
                p.get_by_role("dialog").get_by_role(
                    "button", name="Enviar agora", exact=True
                ).click(trial=True)
                self._foto(f"confirmacao-email-{largura}.png")
                for _ in range(8):
                    p.keyboard.press("Tab")
                    self.assertTrue(
                        p.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                    )
                p.keyboard.press("Escape")
                expect(p.get_by_role("dialog")).to_be_hidden()
                expect(p.get_by_role("button", name="Enviar ao lead", exact=True)).to_be_focused()
                self.assertFalse(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def _conferir_modal(self, largura):
        p = self.page
        p.wait_for_function(
            "getComputedStyle(document.querySelector('.modal-caixa')).transform === 'none' && getComputedStyle(document.querySelector('.modal-caixa')).opacity === '1'"
        )
        caixa = p.get_by_role("dialog").bounding_box()
        self.assertGreaterEqual(caixa["x"], 0)
        self.assertGreaterEqual(caixa["y"], 0)
        self.assertLessEqual(caixa["x"] + caixa["width"], largura + 1)
        self.assertLessEqual(caixa["y"] + caixa["height"], 845)
        self.assertTrue(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def test_listas_vazias_mostram_a_mensagem_sem_arrastar(self):
        from apps.comercial.models import CampanhaEmail

        CampanhaEmail.objects.all().delete()
        p = self.page
        nomes = [
            "loja:vendas",
            "comercial:tarefas",
            "contas",
            "conciliacao:manual",
            "lavanderia:historico",
            "lavanderia:rouparia",
            "reservas:grupos",
            "reservas:restricoes",
            "temporadas",
            "comercial:email_campanhas",
        ]
        for nome in nomes:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(nome)))
                    vazios = p.locator("td.vazio[colspan],td.vazio-el[colspan]")
                    self.assertGreater(vazios.count(), 0, nome)
                    for i in range(vazios.count()):
                        medidas = vazios.nth(i).evaluate("""el => {
                            const r=el.getBoundingClientRect();
                            const texto=document.createRange();texto.selectNodeContents(el);
                            const t=texto.getBoundingClientRect();
                            return {left:r.left,right:r.right,textLeft:t.left,textRight:t.right};
                        }""")
                        self.assertGreaterEqual(medidas["left"], 0, medidas)
                        self.assertLessEqual(medidas["right"], largura + 1, medidas)
                        self.assertGreaterEqual(medidas["textLeft"], 0, medidas)
                        self.assertLessEqual(medidas["textRight"], largura + 1, medidas)
                    if largura == 320:
                        self._foto(f"vazio-{nome.replace(':', '-')}-320.png")

    def test_campos_de_busca_e_dias_da_semana_cabem_no_celular(self):
        p = self.page
        p.set_viewport_size({"width": 320, "height": 844})
        p.goto(self.url(reverse("loja:pdv")))
        self.assertGreaterEqual(p.locator(".pdv-busca").bounding_box()["width"], 220)
        self._foto("pdv-campos-320.png")
        p.goto(self.url(reverse("reservas:lista")))
        self.assertGreaterEqual(p.get_by_role("searchbox").bounding_box()["width"], 220)
        self._foto("reservas-busca-320.png")
        p.goto(self.url(reverse("temporada_nova")))
        label = p.get_by_label("Segunda", exact=True).locator("..")
        self.assertGreaterEqual(label.bounding_box()["height"], 44)
        self.assertLessEqual(label.bounding_box()["height"], 50)
        label.click()
        expect(p.get_by_label("Segunda", exact=True)).to_be_checked()
        self._foto("temporada-dias-320.png")
        p.goto(self.url(reverse("marketing:calendario")))
        caixa = p.locator(".mk-cal-vazio").bounding_box()
        self.assertLessEqual(caixa["x"] + caixa["width"], 320)
        self._foto("calendario-vazio-320.png")

    def test_email_captacao_e_paginas_publicas_cabem_nas_quatro_larguras(self):
        p = self.page
        erros = []
        p.on("pageerror", lambda erro: erros.append(str(erro)))
        paginas = [
            ("comercial:pagina_detalhe", [self.pagina.pk]),
            ("comercial:enviar_email_lead", [self.lead.pk]),
            ("portal:home", [self.acesso.token]),
            ("portal:nps", [self.acesso.token]),
            ("pagamentos:pagar", [self.cobranca.token]),
            ("nps:painel", []),
            ("fiscal:painel", []),
        ]
        for nome, argumentos in paginas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    erros.clear()
                    p.set_viewport_size({"width": largura, "height": 844})
                    resposta = p.goto(
                        self.url(reverse(nome, args=argumentos)), wait_until="networkidle"
                    )
                    self.assertEqual(resposta.status, 200)
                    self.assertLessEqual(
                        p.evaluate("document.documentElement.scrollWidth"), largura + 1
                    )
                    self.assertFalse(erros, erros)
                    if largura in (320, 1440):
                        self._foto(f"operacao-{nome.replace(':', '-')}-{largura}.png")

    def test_email_invalido_nao_envia_e_confirmacao_envia_uma_vez(self):
        from django.core import mail

        from apps.comercial.models import EnvioEmail

        p = self.page
        self.abrir("comercial:enviar_email_lead", self.lead.pk)
        p.locator("#id_destinatario").fill("email-invalido")
        p.get_by_role("button", name="Enviar ao lead", exact=True).click()
        expect(p.get_by_role("dialog")).to_be_hidden()
        expect(p.locator("#id_destinatario")).to_be_focused()
        self.assertEqual(EnvioEmail.objects.count(), 0)
        p.locator("#id_destinatario").fill("guest@example.invalid")
        p.locator("#id_assunto").fill("Proposta fictícia QA")
        p.get_by_role("button", name="Enviar ao lead", exact=True).click()
        with p.expect_navigation():
            p.get_by_role("button", name="Enviar agora", exact=True).click(click_count=2)
        expect(p).to_have_url(self.url(reverse("comercial:oportunidade", args=[self.lead.pk])))
        envio = EnvioEmail.objects.get(oportunidade=self.lead)
        self.assertEqual(envio.status, "enviado")
        self.assertEqual(envio.email, "guest@example.invalid")
        self.assertEqual(envio.assunto, "Proposta fictícia QA")
        self.assertEqual(len(mail.outbox), 1)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class PdvVisualE2ETests(_FunilComercialMixin, _BaseE2E):
    """Catálogo e carrinho reais, incluindo arraste, toque e reenvio da venda."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import (
            CategoriaProduto,
            FormaPagamento,
            LocalEstoque,
            ModuloContratado,
            Produto,
            SessaoCaixa,
            Usuario,
            registrar_entrada,
        )
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="pdv-ui", password="forte-123-abc")
        for codigo in ("estoque", "loja"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.local = LocalEstoque.objects.create(nome="Balcão QA", modulo="loja")
        self.forma = FormaPagamento.objects.create(nome="Dinheiro QA", tipo="dinheiro")
        SessaoCaixa.objects.create(operador=self.op, modulo="loja", fundo_troco=0)
        bebidas = CategoriaProduto.objects.create(nome="Bebidas")
        lanches = CategoriaProduto.objects.create(nome="Lanches")
        self.agua = Produto.objects.create(nome="Água mineral com gás", categoria=bebidas, preco_venda="5.50")
        self.lanche = Produto.objects.create(
            nome="Hambúrguer artesanal com cebola caramelizada e queijo colonial",
            categoria=lanches, preco_venda="34.90",
        )
        Produto.objects.create(nome="Suco esgotado", categoria=bebidas, preco_venda="9.00")
        registrar_entrada(self.agua, self.local, 2, Decimal("1"), self.op)
        registrar_entrada(self.lanche, self.local, 12, Decimal("8"), self.op)
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("pdv-ui", "forte-123-abc")

    def abrir(self, largura=390):
        self.page.set_viewport_size({"width": largura, "height": 844})
        self.page.goto(self.url(reverse("loja:pdv")))
        expect(self.page.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)).to_be_visible()

    def carrinho(self):
        self.page.locator(".pdv-etapas button").filter(has_text="Carrinho").click()

    def test_categoria_busca_sem_acento_e_limite_do_estoque(self):
        p = self.page
        self.abrir()
        p.get_by_role("button", name="Lanches 1", exact=True).click()
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_label("Buscar produto", exact=True).fill("hamburguer queijo")
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_role("button", name="Limpar filtros", exact=True).click()
        expect(p.locator(".pdv-produto")).to_have_count(3)
        p.get_by_label("Buscar produto", exact=True).fill("agua gas")
        agua = p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)
        agua.click()
        agua.click()
        expect(agua).to_be_disabled()
        expect(p.get_by_label("Local de estoque", exact=True)).to_be_disabled()
        self.carrinho()
        expect(p.get_by_role("button", name="Aumentar Água mineral com gás", exact=True)).to_be_disabled()
        p.get_by_role("button", name="Diminuir Água mineral com gás", exact=True).click()
        p.get_by_role("button", name="Produtos", exact=True).click()
        expect(agua).to_be_enabled()
        self.assertEqual(saldo(self.agua, self.local), Decimal("2"))

    def test_carrinho_cabe_no_celular_e_menu_aberto_sem_perder_itens(self):
        p = self.page
        self.abrir(1440)
        p.get_by_role("button", name=f"Adicionar {self.lanche.nome} ao carrinho", exact=True).click()
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                if p.locator(".pdv-etapas").is_visible():
                    self.carrinho()
                expect(p.locator(".pdv-item-nome")).to_have_text(self.lanche.nome)
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                medidas = p.locator(".pdv-item").evaluate("""el => ({
                    largura: el.clientWidth, conteudo: el.scrollWidth,
                    botoes: [...el.querySelectorAll('button')].map(b => ({w:b.offsetWidth,h:b.offsetHeight})),
                    nome: getComputedStyle(el.querySelector('.pdv-item-nome')).whiteSpace
                })""")
                self.assertLessEqual(medidas["conteudo"], medidas["largura"] + 1)
                self.assertEqual(medidas["nome"], "normal")
                self.assertTrue(all(b["w"] >= 44 and b["h"] >= 44 for b in medidas["botoes"]))
                if os.environ.get("E2E_EVIDENCIAS"):
                    p.screenshot(path=str(Path(os.environ["E2E_EVIDENCIAS"]) / f"pdv-carrinho-{largura}.png"))
        expect(p.locator(".pdv-etapas")).to_be_hidden()
        expect(p.locator(".pdv-produtos")).to_be_visible()
        expect(p.locator(".pdv-painel")).to_be_visible()
        self.assertEqual(p.locator(".pdv-item").count(), 1)

    def test_arraste_real_adiciona_so_o_produto_conhecido_e_nao_cobra(self):
        from apps.loja.models import Venda
        p = self.page
        self.abrir(1440)
        origem = p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)
        origem.drag_to(p.locator(".pdv-painel"))
        expect(p.locator(".pdv-item-nome")).to_have_text(self.agua.nome)
        expect(p.locator(".pdv-qtd span")).to_have_text("1")
        p.locator(".pdv-painel").evaluate("""el => {
            const dt = new DataTransfer();
            dt.setData('text/plain', '9999');
            el.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:dt}));
        }""")
        expect(p.locator(".pdv-qtd span")).to_have_text("1")
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(saldo(self.agua, self.local), Decimal("2"))

    def test_falha_de_conexao_mantem_carrinho_e_reenvia_mesma_chave(self):
        from apps.loja.models import Venda
        p = self.page
        self.abrir()
        p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True).click()
        self.carrinho()
        p.get_by_label("Forma de pagamento", exact=True).select_option(str(self.forma.pk))
        requisicoes = []
        url = self.url(reverse("loja:finalizar"))

        def perder_resposta(route):
            requisicoes.append(route.request.post_data_json)
            route.fetch()  # o servidor gravou, mas a resposta se perdeu
            route.abort()

        p.route(url, perder_resposta)
        p.locator(".pdv-finalizar").click()
        expect(p.get_by_text("Falha de conexão. Tente de novo: a venda não sai em dobro.", exact=True)).to_be_visible()
        expect(p.locator(".pdv-item-nome")).to_have_text(self.agua.nome)
        p.unroute(url, perder_resposta)
        p.on("request", lambda req: requisicoes.append(req.post_data_json) if req.url == url else None)
        with p.expect_navigation():
            p.locator(".pdv-finalizar").click()
        self.assertEqual(len(requisicoes), 2)
        self.assertEqual(requisicoes[0]["chave"], requisicoes[1]["chave"])
        self.assertEqual(Venda.objects.count(), 1)
        self.assertEqual(saldo(self.agua, self.local), Decimal("1"))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class GaleriaVisualE2ETests(_BaseE2E):
    def setUp(self):
        super().setUp()
        from apps.site.models import FotoGaleria
        cache.clear()
        FotoGaleria.objects.create(imagem="", legenda="Foto indisponível", categoria="pousada", ordem=0)
        for numero in range(1, 12):
            FotoGaleria.objects.create(
                imagem=f"galeria/qa-{numero}.svg", legenda=f"Paisagem de teste {numero}",
                categoria="natureza", ordem=numero,
            )
        self.page.route("**/media/galeria/*", lambda r: r.fulfill(
            content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#2E483E"/></svg>'
        ))

    def test_galeria_na_top_layer_cabe_em_telas_pequenas_e_paisagem(self):
        p = self.page
        for largura, altura in ((320, 568), (390, 844), (821, 844), (844, 390), (1440, 900)):
            with self.subTest(largura=largura, altura=altura):
                p.set_viewport_size({"width": largura, "height": altura})
                p.goto(self.url(reverse("core:home")))
                if p.get_by_role("button", name="Recusar", exact=True).is_visible():
                    p.get_by_role("button", name="Recusar", exact=True).click()
                origem = p.locator('[data-galeria-item][data-src$="qa-11.svg"]')
                origem.click()
                dialog = p.get_by_role("dialog", name="Galeria de fotos", exact=True)
                expect(dialog).to_be_visible()
                expect(dialog.locator("[data-gl-legenda]")).to_have_text("Paisagem de teste 11")
                expect(dialog.locator("[data-gl-contador]")).to_have_text("11 / 11")
                geometria = dialog.evaluate("""el => ({
                    modal:el.matches(':modal'), largura:el.scrollWidth, altura:el.scrollHeight,
                    botoes:[...el.querySelectorAll('button,a')].map(b => {
                        const r=b.getBoundingClientRect();
                        return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height};
                    }), imagem:getComputedStyle(el.querySelector('img')).objectFit
                })""")
                self.assertTrue(geometria["modal"])
                self.assertEqual(geometria["imagem"], "contain")
                self.assertLessEqual(geometria["largura"], largura + 1)
                self.assertLessEqual(geometria["altura"], altura + 1)
                for botao in geometria["botoes"]:
                    self.assertGreaterEqual(botao["x"], 0)
                    self.assertGreaterEqual(botao["y"], 0)
                    self.assertLessEqual(botao["right"], largura)
                    self.assertLessEqual(botao["bottom"], altura)
                    self.assertGreaterEqual(botao["w"], 44)
                    self.assertGreaterEqual(botao["h"], 44)
                dialog.get_by_role("button", name="Próxima foto", exact=True).click()
                expect(dialog.locator("[data-gl-legenda]")).to_have_text("Paisagem de teste 1")
                p.keyboard.press("ArrowLeft")
                expect(dialog.locator("[data-gl-contador]")).to_have_text("11 / 11")
                p.keyboard.press("Escape")
                expect(dialog).to_be_hidden()
                expect(origem).to_be_focused()
                p.wait_for_function("document.body.style.overflow !== 'hidden'")
                self.assertNotEqual(p.evaluate("document.body.style.overflow"), "hidden")
