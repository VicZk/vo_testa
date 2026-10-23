"""Ações da reserva no celular: hierarquia, teclado e formulários sem JavaScript."""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    ConfiguracaoReservas,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    TipoUH,
    Usuario,
)
from apps.nucleo.modulos import Modulo
from apps.reservas.models import ContaHospedagem, Reserva

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(FNRH_BLOQUEAR_CHECKIN=False, ECA_BLOQUEAR_CHECKIN=False)
class ReservaMobileE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        for codigo in (Modulo.RESERVAS, Modulo.APPSITE, Modulo.FISCAL):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(
            username="reserva-mobile", password="forte-123-abc")
        self.dinheiro, _ = FormaPagamento.objects.get_or_create(
            tipo="dinheiro", defaults={"nome": "Dinheiro"})
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={
            "feriados_automaticos": False, "iss_aliquota": Decimal("0.00"),
            "taxa_turismo_diaria": Decimal("0.00"),
        })
        self.tipo = TipoUH.objects.create(
            nome="Suíte com varanda e vista para o lago", tarifa_base=Decimal("300.00"),
            capacidade=4)
        self.hoje = timezone.localdate()
        self.reservas = {}
        for indice, status in enumerate(Reserva.Status.values, start=1):
            reserva = Reserva.objects.create(
                uh=UH.objects.create(numero=f"M{indice:02d}", tipo=self.tipo),
                hospede=Pessoa.objects.create(
                    nome=f"Maria Aparecida de Albuquerque e Silva — Teste {status}"),
                checkin=self.hoje - timedelta(days=1) if status == Reserva.Status.HOSPEDADA else self.hoje,
                checkout=self.hoje + timedelta(days=2), status=status,
                valor_diaria=Decimal("300.00"), criado_por=self.usuario)
            if status in (Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT):
                ContaHospedagem.objects.create(
                    reserva=reserva,
                    status=ContaHospedagem.Status.ABERTA if status == Reserva.Status.HOSPEDADA else ContaHospedagem.Status.FECHADA)
            self.reservas[status] = reserva
        self.quarto_livre = UH.objects.create(numero="M99", tipo=self.tipo)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def abrir(self, status=Reserva.Status.CONFIRMADA):
        reserva = self.reservas[status]
        self.page.goto(self.url(reverse("reservas:detalhe", args=[reserva.pk])), wait_until="load")
        expect(self.bloco()).to_have_count(1)
        self.page.evaluate("() => document.fonts.ready")
        return reserva

    def bloco(self):
        return self.page.locator("[data-reserva-acoes]")

    def abrir_painel(self, acao):
        gatilho = self.bloco().locator(f'[data-acao="{acao}"]')
        if not gatilho.is_visible():
            self.bloco().locator("details").filter(
                has=self.page.locator(f'[data-acao="{acao}"]')).locator("summary").click()
        gatilho.click()
        painel = self.page.locator("#" + gatilho.get_attribute("aria-controls"))
        expect(painel).to_be_visible()
        expect(gatilho).to_have_attribute("aria-expanded", "true")
        return gatilho, painel

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.bloco().evaluate("el => el.scrollIntoView({block: 'start'})")
            self.page.screenshot(path=str(pasta / f"reserva-{nome}.png"))
            if nome.endswith(("-390", "-1440")):
                self.page.evaluate("window.scrollTo(0, 0)")
                self.page.screenshot(path=str(pasta / f"reserva-{nome}-pagina.png"), full_page=True)

    def test_hierarquia_e_alvos_alinhados_de_320_a_1440_pixels(self):
        for status in (Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA, Reserva.Status.HOSPEDADA):
            self.abrir(status)
            for largura in (320, 390, 768, 1440):
                with self.subTest(status=status, largura=largura):
                    self.page.set_viewport_size({"width": largura, "height": 1000})
                    medidas = self.bloco().evaluate("""bloco => {
                      const rect = el => { const r = el.getBoundingClientRect(); return {
                        left:r.left, right:r.right, top:r.top, bottom:r.bottom,
                        width:r.width, height:r.height}; };
                      const grupos = [...bloco.querySelectorAll('.acoes-reserva-principais, .acoes-reserva-grade')]
                        .filter(el => el.getClientRects().length && el.getBoundingClientRect().height > 0)
                        .map(el => ({caixa:rect(el), itens:[...el.querySelectorAll('button:not([hidden]), a')]
                          .filter(item => item.getClientRects().length).map(rect)}));
                      return {documento:document.documentElement.scrollWidth, bloco:rect(bloco), grupos,
                        principal:rect(bloco.querySelector('.acoes-reserva-principais')),
                        secundaria:rect(bloco.querySelector('.acoes-reserva-secundarias'))};
                    }""")
                    self.assertLessEqual(medidas["documento"], largura + 1, medidas)
                    self.assertLessEqual(medidas["principal"]["bottom"], medidas["secundaria"]["top"], medidas)
                    for grupo in medidas["grupos"]:
                        larguras = [item["width"] for item in grupo["itens"]]
                        self.assertLessEqual(max(larguras) - min(larguras), 1, grupo)
                        for indice, item in enumerate(grupo["itens"]):
                            self.assertGreaterEqual(item["height"], 43, grupo)
                            self.assertGreaterEqual(item["left"], grupo["caixa"]["left"] - 1, grupo)
                            self.assertLessEqual(item["right"], grupo["caixa"]["right"] + 1, grupo)
                            if largura <= 390:
                                self.assertAlmostEqual(item["width"], grupo["caixa"]["width"], delta=1)
                                if indice:
                                    self.assertGreaterEqual(item["top"], grupo["itens"][indice - 1]["bottom"], grupo)
                    if largura in (320, 390, 1440):
                        self.foto(f"{status}-{largura}")

    def test_estados_preservam_acoes_e_limites_de_permissao(self):
        cenarios = {
            Reserva.Status.ORCAMENTO: {"sinal", "lotacao", "datas", "cancelar"},
            Reserva.Status.PRE_RESERVA: {"sinal", "lotacao", "datas", "trocar", "cancelar"},
            Reserva.Status.CONFIRMADA: {"sinal", "lotacao", "datas", "trocar", "cancelar"},
            Reserva.Status.HOSPEDADA: {"estender", "trocar"},
            Reserva.Status.NO_SHOW: {"desfazer"},
            Reserva.Status.CHECKOUT: set(),
            Reserva.Status.CANCELADA: set(),
        }
        for status, acoes in cenarios.items():
            with self.subTest(status=status):
                reserva = self.abrir(status)
                encontrados = set(self.bloco().locator("[data-acao]").evaluate_all(
                    "botoes => botoes.map(botao => botao.dataset.acao)"))
                self.assertEqual(encontrados, acoes)
                for nome, permitido in (
                    ("Confirmar reserva", status in (Reserva.Status.ORCAMENTO, Reserva.Status.PRE_RESERVA)),
                    ("Fazer entrada (check-in)", status in (Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA)),
                    ("Fazer saída (check-out)", status == Reserva.Status.HOSPEDADA),
                ):
                    expect(self.bloco().get_by_role("button", name=nome, exact=True)).to_have_count(int(permitido))
                tem_conta = status in (Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT)
                expect(self.bloco().get_by_role("link", name="Conferir e imprimir conta", exact=True)).to_have_count(int(tem_conta))
                expect(self.bloco().get_by_role("link", name="Preparar NFS-e", exact=True)).to_have_count(int(tem_conta))
                expect(self.bloco().get_by_role("link", name="QR do hóspede", exact=True)).to_have_count(int(status == Reserva.Status.HOSPEDADA))
                reserva.refresh_from_db()
                self.assertEqual(reserva.status, status)

        no_show = self.reservas[Reserva.Status.NO_SHOW]
        Reserva.objects.filter(pk=no_show.pk).update(
            checkin=self.hoje - timedelta(days=2), checkout=self.hoje)
        self.abrir(Reserva.Status.NO_SHOW)
        expect(self.bloco().locator('[data-acao="desfazer"]')).to_have_count(0)

        operador = Usuario.objects.create_user(username="reserva-mobile-operador", password="forte-123-abc")
        operador.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        self.client.force_login(operador)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.abrir()
        expect(self.bloco().locator('[name="manter_preco"], [name="cobrar_tarifa_nova"]')).to_have_count(0)
        with override_settings(FNRH_BLOQUEAR_CHECKIN=True):
            self.abrir()
            expect(self.bloco().get_by_role("button", name="Fazer entrada (check-in)", exact=True)).to_be_disabled()
            expect(self.bloco().get_by_role("link", name="Preencher a FNRH", exact=True)).to_be_visible()

    @override_settings(CSP_REPORT_ONLY=False)
    def test_todos_os_paineis_abrem_e_fecham_sem_enviar_post(self):
        posts = []
        self.page.on("request", lambda request: posts.append(request.url)
                     if request.method == "POST" and "/crm/reservas/" in request.url else None)
        cenarios = (
            (Reserva.Status.CONFIRMADA, ("sinal", "lotacao", "datas", "trocar", "cancelar")),
            (Reserva.Status.HOSPEDADA, ("estender", "trocar")),
            (Reserva.Status.NO_SHOW, ("desfazer",)),
        )
        for status, acoes in cenarios:
            with self.subTest(status=status):
                reserva = self.abrir(status)
                expect(self.bloco().locator(".acao-painel:visible")).to_have_count(0)
                for acao in acoes:
                    with self.subTest(acao=acao):
                        gatilho, painel = self.abrir_painel(acao)
                        expect(self.bloco().locator(".acao-painel:visible")).to_have_count(1)
                        painel.locator("[data-fechar-acao]").click()
                        expect(painel).to_be_hidden()
                        expect(gatilho).to_have_attribute("aria-expanded", "false")
                        expect(gatilho).to_be_focused()
                        gatilho.focus()
                        gatilho.press("Enter")
                        expect(painel).to_be_visible()
                        painel.locator('input:not([type="hidden"]), select, textarea').first.focus()
                        self.page.keyboard.press("Escape")
                        expect(painel).to_be_hidden()
                        expect(gatilho).to_be_focused()
                reserva.refresh_from_db()
                self.assertEqual(reserva.status, status)
        self.assertEqual(posts, [])

    def test_trocar_painel_preserva_campos_e_erro_de_envio(self):
        reserva = self.abrir()
        _, sinal = self.abrir_painel("sinal")
        sinal.locator('[name="valor"]').fill("123,45")
        sinal.locator('[name="forma"]').select_option(str(self.dinheiro.pk))
        self.abrir_painel("lotacao")
        expect(sinal).to_be_hidden()
        _, sinal = self.abrir_painel("sinal")
        expect(sinal.locator('[name="valor"]')).to_have_value("123,45")
        # Sem caixa aberto, o servidor recusa o recebimento e conserva o formulário.
        sinal.get_by_role("button", name="Receber no meu caixa", exact=True).click()
        expect(sinal.locator('[data-erros-envio]')).to_be_visible()
        expect(sinal.locator('[name="valor"]')).to_have_value("123,45")
        expect(sinal.locator('[name="forma"]')).to_have_value(str(self.dinheiro.pk))
        expect(self.bloco().locator('[data-acao="sinal"]')).to_have_attribute("aria-expanded", "true")
        self.assertFalse(reserva.adiantamentos.exists())

    def test_reinicializa_apos_troca_htmx_sem_duplicar_eventos(self):
        self.abrir()
        self.page.evaluate("""async () => {
          const resposta = await fetch(location.href);
          const pagina = new DOMParser().parseFromString(await resposta.text(), 'text/html');
          const novo = pagina.querySelector('[data-reserva-acoes]');
          document.querySelector('[data-reserva-acoes]').replaceWith(novo);
          document.body.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles:true, detail:{target:novo}}));
          document.body.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles:true, detail:{target:novo}}));
        }""")
        _, painel = self.abrir_painel("datas")
        expect(self.bloco().locator(".acao-painel:visible")).to_have_count(1)
        painel.locator('[name="checkin"]').fill((self.hoje + timedelta(days=10)).isoformat())
        self.page.keyboard.press("Escape")
        expect(painel).to_be_hidden()
        self.abrir_painel("datas")
        expect(painel.locator('[name="checkin"]')).to_have_value((self.hoje + timedelta(days=10)).isoformat())

    def test_sem_javascript_os_formularios_continuam_visiveis_e_enviaveis(self):
        contexto = self._browser.new_context(
            java_script_enabled=False, locale="pt-BR", viewport={"width": 390, "height": 844})
        contexto.add_cookies(self.page.context.cookies())
        pagina = contexto.new_page()
        try:
            for status, acoes in (
                (Reserva.Status.CONFIRMADA, ("sinal", "lotacao", "datas", "trocar", "cancelar")),
                (Reserva.Status.HOSPEDADA, ("estender", "trocar")),
                (Reserva.Status.NO_SHOW, ("desfazer",)),
            ):
                with self.subTest(status=status):
                    reserva = self.reservas[status]
                    pagina.goto(self.url(reverse("reservas:detalhe", args=[reserva.pk])), wait_until="load")
                    for acao in acoes:
                        painel = pagina.locator(f"#acao-{acao}")
                        expect(painel).to_be_visible()
                        form = painel.locator("form")
                        expect(form).to_have_attribute("method", "post")
                        expect(form.locator('[name="csrfmiddlewaretoken"]')).to_have_count(1)
                        expect(form.locator('[type="submit"]')).to_be_visible()
        finally:
            contexto.close()
