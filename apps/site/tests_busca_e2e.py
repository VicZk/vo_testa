"""Busca global: geometria, teclado e respostas assíncronas no navegador real."""

import json
import os
import re
import unittest
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Pessoa, Usuario

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class BuscaGlobalE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        usuario = Usuario.objects.create_user(
            username="busca-e2e", password="forte-123-abc", is_superuser=True, is_staff=True)
        self.pessoa = Pessoa.objects.create(
            nome="Busca Maria Aparecida de Albuquerque e Silva — cadastro fictício para conferência")
        self.client.force_login(usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    def abrir(self):
        self.page.goto(self.url(reverse("dashboard")))
        self.page.locator(".busca-global").click()
        expect(self.page.get_by_role("combobox", name="Termo da busca")).to_be_focused()

    def captura(self, nome):
        destino = os.environ.get("BUSCA_E2E_SCREENSHOTS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / (nome + ".png")))

    def test_busca_cabe_na_tela_foco_unico_resultado_longo_e_fechar_no_toque(self):
        self.page.emulate_media(reduced_motion="reduce")
        self.abrir()
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                self.page.set_viewport_size({"width": largura, "height": 900})
                self.page.locator("#paleta-input").fill("")
                expect(self.page.get_by_text("Encontre o que precisa", exact=True)).to_be_visible()
                self.captura(f"busca-inicial-{largura}")
                self.page.locator("#paleta-input").fill("Busca Maria")
                expect(self.page.get_by_role("option")).to_have_count(1)
                expect(self.page.get_by_role("option")).to_contain_text(self.pessoa.nome)
                self.captura(f"busca-resultados-{largura}")
                medidas = self.page.locator(".paleta").evaluate("""el => {
                  const r = e => { const x=e.getBoundingClientRect(); return {left:x.left,right:x.right,top:x.top,bottom:x.bottom,width:x.width,height:x.height}; };
                  const input=el.querySelector('input'), foco=getComputedStyle(input);
                  return {dialogo:r(el), largura:innerWidth,altura:innerHeight,
                    fechar:r(el.querySelector('.paleta-fechar')),
                    partes:[...el.querySelectorAll('input,.paleta-rot,.paleta-tipo,.paleta-fechar')].map(r),
                    outline:foco.outlineStyle,sombra:foco.boxShadow,animacao:getComputedStyle(el).animationName,
                    body: getComputedStyle(document.body).overflow};
                }""")
                self.assertGreaterEqual(medidas["dialogo"]["left"], 0)
                self.assertLessEqual(medidas["dialogo"]["right"], medidas["largura"])
                self.assertLessEqual(medidas["dialogo"]["bottom"], medidas["altura"])
                for parte in medidas["partes"]:
                    self.assertGreaterEqual(parte["left"], medidas["dialogo"]["left"])
                    self.assertLessEqual(parte["right"], medidas["dialogo"]["right"])
                self.assertEqual(medidas["outline"], "none")
                self.assertEqual(medidas["sombra"], "none")
                self.assertEqual(medidas["animacao"], "none")
                self.assertEqual(medidas["body"], "hidden")
                self.assertGreaterEqual(medidas["fechar"]["width"], 44)
                self.assertGreaterEqual(medidas["fechar"]["height"], 44)
        self.page.get_by_role("button", name="Fechar busca", exact=True).click()
        expect(self.page.locator("#paleta")).to_be_hidden()
        expect(self.page.locator(".busca-global")).to_be_focused()
        self.assertNotEqual(self.page.evaluate("getComputedStyle(document.body).overflow"), "hidden")
        self.assertEqual(self.page_errors, [])

    def test_teclado_selecao_tab_escape_e_navegacao(self):
        self.page.goto(self.url(reverse("dashboard")))
        self.page.locator(".busca-global").focus()
        self.page.keyboard.press("Control+k")
        campo = self.page.get_by_role("combobox", name="Termo da busca")
        expect(campo).to_be_focused()
        campo.fill("a")
        expect(self.page.get_by_role("option").nth(1)).to_be_visible()
        campo.press("ArrowDown")
        expect(campo).to_have_attribute("aria-activedescendant", "paleta-item-1")
        expect(self.page.locator("#paleta-item-1")).to_have_attribute("aria-selected", "true")
        campo.press("Tab")
        expect(self.page.get_by_role("button", name="Fechar busca", exact=True)).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(campo).to_be_focused()
        campo.press("Escape")
        expect(self.page.locator("#paleta")).to_be_hidden()
        expect(self.page.locator(".busca-global")).to_be_focused()
        self.page.keyboard.press("Control+k")
        campo.fill("Busca Maria")
        expect(self.page.get_by_role("option")).to_have_count(1)
        campo.press("Enter")
        self.page.wait_for_url(self.url(reverse("pessoa_editar", args=[self.pessoa.pk])))
        self.assertEqual(self.page_errors, [])

    def test_resultado_antigo_nao_sobrescreve_termo_novo_nem_reabre_busca(self):
        pendentes = []
        self.page.route(re.compile(re.escape(reverse("busca_global")) + r"\?"), lambda route: pendentes.append(route))
        self.abrir()
        campo = self.page.locator("#paleta-input")
        with self.page.expect_request(lambda req: "q=Antiga" in req.url):
            campo.fill("Antiga")
        expect(self.page.locator("#paleta-status")).to_have_text("Buscando cadastros…")
        with self.page.expect_request(lambda req: "q=Atual" in req.url):
            campo.fill("Atual")
        self.page.wait_for_timeout(50)
        self.assertEqual(len(pendentes), 2)
        pendentes[1].fulfill(content_type="application/json", body=json.dumps({
            "resultados": [{"rotulo": "Resposta atual", "tipo": "Cadastro", "url": reverse("dashboard")}]}))
        expect(self.page.get_by_role("option")).to_have_text("Resposta atualCadastro")
        pendentes[0].fulfill(content_type="application/json", body=json.dumps({
            "resultados": [{"rotulo": "Resposta antiga", "tipo": "Cadastro", "url": reverse("dashboard")}]}))
        self.page.wait_for_timeout(150)
        expect(self.page.get_by_role("option")).to_have_text("Resposta atualCadastro")
        campo.fill("")
        expect(self.page.get_by_role("option")).to_have_count(0)
        expect(campo).not_to_have_attribute("aria-activedescendant", re.compile(".+"))
        with self.page.expect_request(lambda req: "q=Fechar" in req.url):
            campo.fill("Fechar")
        campo.press("Escape")
        pendentes[-1].fulfill(content_type="application/json", body='{"resultados":[]}')
        expect(self.page.locator("#paleta")).to_be_hidden()
        self.page.locator(".busca-global").click()
        expect(self.page.get_by_text("Encontre o que precisa", exact=True)).to_be_visible()
        self.assertEqual(self.page_errors, [])

    def test_vazio_e_falha_de_rede_sao_estados_diferentes(self):
        self.abrir()
        campo = self.page.locator("#paleta-input")
        campo.fill("NenhumCadastroExisteAssim")
        expect(self.page.get_by_text("Nenhum resultado", exact=True).first).to_be_visible()
        self.page.route(re.compile(re.escape(reverse("busca_global")) + r"\?"), lambda route: route.abort())
        campo.fill("Outra consulta")
        expect(self.page.get_by_text("Busca indisponível", exact=True)).to_be_visible()
        expect(self.page.locator("#paleta-status")).to_have_text("Não foi possível consultar os cadastros")
        self.assertEqual(self.page_errors, [])
