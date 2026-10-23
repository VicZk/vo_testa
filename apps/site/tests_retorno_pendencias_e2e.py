"""Ida e volta da Central, filtros locais, modal, POST e resolução no navegador."""

import os
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from apps.governanca.models import StatusLimpeza, TarefaGovernanca
from apps.manutencao.models import OrdemServico
from apps.nucleo.pendencias import url_pendencias
from apps.nucleo.retorno_pendencias import PARAMETRO
from apps.nucleo.tests_retorno_pendencias import criar_cenario_retorno

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
@override_settings(MFA_OBRIGATORIO=False)
class RetornoPendenciasE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        self.page.close()
        self.context = self._browser.new_context(locale="pt-BR", has_touch=True)
        self.page = self.context.new_page()
        self.c = criar_cenario_retorno()
        self.client.force_login(self.c.usuario)
        self.page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}])
        self.page.add_init_script("localStorage.setItem('sidebar','recolhida')")
        self.page.emulate_media(reduced_motion="reduce")
        self.erros = []
        self.page.on("pageerror", lambda erro: self.erros.append(str(erro)))

    def tearDown(self):
        self.context.close()
        super().tearDown()

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"retorno-{nome}.png"), full_page=True, animations="disabled")

    def conferir_retorno(self, central):
        link = self.page.get_by_role("link", name="Voltar para Pendências", exact=True)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", central)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), self.page.viewport_size["width"] + 1)
        self.assertGreaterEqual(link.bounding_box()["height"], 44)
        self.assertTrue(link.evaluate("e => e.scrollWidth <= e.clientWidth"))
        self.assertEqual(self.erros, [])
        return link

    def abrir_item(self, central, largura):
        self.page.set_viewport_size({"width": largura, "height": 900})
        self.page.goto(self.url(central), wait_until="load")
        expect(self.page.locator("[data-pendencia-id]")).to_have_count(1)
        self.page.locator("[data-pendencia-id] .registro-acoes a").click()
        voltar = self.conferir_retorno(central)
        expect(voltar).to_be_in_viewport(ratio=1)
        return voltar

    def test_governanca_entrada_volta_quatro_larguras_e_ciclo_completo(self):
        central = url_pendencias("governanca", "pendente") + "&pagina=1"
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                voltar = self.abrir_item(central, largura)
                self.foto(f"governanca-{largura}")
                voltar.click()
                expect(self.page).to_have_url(self.url(central))
                expect(self.page.locator("[data-pendencia-id]")).to_have_count(1)
        self.page.locator("[data-pendencia-id] .registro-acoes a").click()
        self.page.get_by_role("button", name="Iniciar limpeza", exact=True).click()
        self.conferir_retorno(central)
        self.page.get_by_role("button", name="Concluir limpeza", exact=True).click()
        self.page.get_by_role("button", name="Aprovar limpeza", exact=True).click()
        expect(self.page.get_by_role("button", name="Aprovar limpeza", exact=True)).to_have_count(0)
        self.conferir_retorno(central).click()
        expect(self.page).to_have_url(self.url(central))
        expect(self.page.locator("[data-pendencias-vazio]")).to_be_visible()
        self.c.tarefa.refresh_from_db()
        self.assertEqual(self.c.tarefa.status, TarefaGovernanca.Status.CONCLUIDA)
        self.assertEqual(StatusLimpeza.objects.get(uh=self.c.uh).situacao, StatusLimpeza.Situacao.INSPECIONADA)
        self.foto("governanca-resolvida")

    def test_manutencao_mantem_origem_ao_filtrar_navegar_e_resolver_via_json(self):
        central = url_pendencias("manutencao", "atencao") + "&pagina=1"
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                voltar = self.abrir_item(central, largura)
                self.foto(f"manutencao-{largura}")
                voltar.click()
                expect(self.page).to_have_url(self.url(central))
        self.page.locator("[data-pendencia-id] .registro-acoes a").click()
        self.page.locator("#conteudo a.voltar").click()
        self.conferir_retorno(central)
        self.page.get_by_label("Buscar OS", exact=True).fill("Janela retorno QA")
        self.page.get_by_role("button", name="Filtrar", exact=True).click()
        self.conferir_retorno(central)
        self.assertEqual(parse_qs(urlsplit(self.page.url).query)[PARAMETRO], [central])
        self.page.get_by_role("link", name="Janela retorno QA", exact=True).click()
        self.page.get_by_label("Resolução", exact=True).fill("Vedação conferida no fluxo de pendências")
        with self.page.expect_response(lambda r: r.request.method == "POST" and "concluir" in r.url) as enviado:
            self.page.get_by_role("button", name="Concluir", exact=True).click()
        self.assertEqual(enviado.value.status, 200)
        self.assertIn("application/json", enviado.value.headers["content-type"])
        self.assertEqual(enviado.value.request.headers["x-form-preserve"], "1")
        self.conferir_retorno(central)
        expect(self.page.locator(".ficha-texto").filter(has_text="Vedação conferida no fluxo de pendências")).to_be_visible()
        self.conferir_retorno(central).click()
        expect(self.page).to_have_url(self.url(central))
        expect(self.page.locator("[data-pendencias-vazio]")).to_be_visible()
        self.c.os.refresh_from_db()
        self.assertEqual(self.c.os.status, OrdemServico.Status.CONCLUIDA)
        self.foto("manutencao-resolvida")

    def test_modal_interno_e_post_conservam_retorno_sem_afetar_outra_aba(self):
        central = url_pendencias("governanca", "pendente")
        self.abrir_item(central, 390)
        # O link Voltar da ficha leva ao módulo; a origem da Central continua.
        self.page.get_by_role("link", name="Voltar", exact=True).click()
        self.conferir_retorno(central)
        self.page.locator("#conteudo a").filter(has_text="Visão geral").first.click()
        self.conferir_retorno(central)
        porta = self.page.locator(f'a.porta[href*="/quarto/{self.c.uh.pk}/"]')
        with self.page.expect_response(lambda r: r.request.method == "GET" and f"/quarto/{self.c.uh.pk}/" in r.url) as aberta:
            porta.click()
        self.assertEqual(parse_qs(urlsplit(aberta.value.url).query)[PARAMETRO], [central])
        modal = self.page.locator("#modal-conteudo")
        expect(modal.get_by_role("heading", name=self.c.uh.numero, exact=True)).to_be_visible()
        self.foto("governanca-modal")
        modal.get_by_role("button", name="Iniciar limpeza", exact=True).click()
        expect(modal.locator("h2")).to_have_count(0)
        self.conferir_retorno(central)
        self.assertEqual(urlsplit(self.page.url).path, reverse("governanca:painel"))
        outra = self.page.context.new_page()
        try:
            outra.goto(self.url(reverse("governanca:quarto", args=[self.c.uh.pk])), wait_until="load")
            expect(outra.locator("[data-retorno-pendencias-link]")).to_have_count(0)
            self.conferir_retorno(central)
        finally:
            outra.close()
        self.conferir_retorno(central).click()
        expect(self.page.locator("[data-pendencias-vazio]")).to_be_visible()

    def test_historico_restaurado_distingue_central_e_destino(self):
        central = url_pendencias("manutencao", "atencao") + "&pagina=1"
        self.abrir_item(central, 390)
        destino = self.page.url
        self.page.go_back()
        expect(self.page).to_have_url(self.url(central))
        expect(self.page.locator("[data-central-pendencias]")).to_be_visible()
        expect(self.page.locator("[data-retorno-pendencias-link]")).to_have_count(0)
        self.assertIsNone(self.page.locator("#conteudo").get_attribute("data-retorno-pendencias"))
        self.page.go_forward()
        expect(self.page).to_have_url(destino)
        self.conferir_retorno(central)

