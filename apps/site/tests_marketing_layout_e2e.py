"""Posição e acesso aos campos da nova ideia, na janela e na página completa."""

import os
import unittest
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class MarketingLayoutE2ETests(_BaseE2E):
    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        usuario = Usuario.objects.create_superuser(username="marketing-layout", password="teste-local-123")
        self.client.force_login(usuario)
        self.cookie = {"name": settings.SESSION_COOKIE_NAME,
                       "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                       "url": self.live_server_url}
        self.page.context.add_cookies([self.cookie])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self, pagina, nome):
        pagina.goto(self.url(reverse("marketing:" + nome)))
        pagina.wait_for_function("document.fonts.status === 'loaded'")

    def medir(self, pagina, seletor):
        return pagina.locator(seletor).evaluate("""el => {
          const r = el.getBoundingClientRect();
          return {left:r.left, right:r.right, top:r.top, bottom:r.bottom,
                  centerX:(r.left+r.right)/2, centerY:(r.top+r.bottom)/2,
                  width:document.documentElement.clientWidth, height:innerHeight,
                  scroll:document.documentElement.scrollWidth};
        }""")

    def foto(self, pagina, nome):
        pasta = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            pagina.screenshot(path=str(destino / f"marketing-{nome}.png"))

    def test_nova_ideia_centralizada_com_menu_aberto_e_acoes_visiveis(self):
        for largura in (821, 1440, 3440):
            with self.subTest(largura=largura):
                self.page.set_viewport_size({"width": largura, "height": 900})
                self.abrir(self.page, "quadro")
                self.assertNotIn("recolhida", self.page.locator("#app").get_attribute("class"))
                self.page.get_by_role("link", name="+ Nova ideia", exact=True).click()
                dialogo = self.page.get_by_role("dialog", name="Nova campanha")
                expect(dialogo).to_be_visible()
                medidas = self.medir(self.page, "#modal-conteudo")
                fundo = self.medir(self.page, "#modal-reserva")
                self.assertAlmostEqual(medidas["centerX"], fundo["centerX"], delta=1)
                self.assertAlmostEqual(medidas["centerY"], fundo["centerY"], delta=1)
                expect(dialogo.get_by_role("button", name="Criar campanha")).to_be_in_viewport()
                expect(dialogo.get_by_label("Nome da campanha", exact=False)).to_be_focused()
                self.foto(self.page, f"nova-ideia-{largura}")
                dialogo.get_by_role("button", name="Cancelar", exact=True).click()
                expect(dialogo).not_to_be_visible()

    def test_nova_ideia_toque_e_pagina_completa_em_telas_estreitas(self):
        for largura in (320, 390):
            contexto = self._browser.new_context(
                viewport={"width": largura, "height": 740}, has_touch=True, is_mobile=True,
                locale="pt-BR", reduced_motion="reduce")
            try:
                contexto.add_cookies([self.cookie])
                pagina = contexto.new_page()
                self.abrir(pagina, "quadro")
                pagina.get_by_role("link", name="+ Nova ideia", exact=True).click()
                dialogo = pagina.get_by_role("dialog", name="Nova campanha")
                expect(dialogo).to_be_visible()
                medidas = self.medir(pagina, "#modal-conteudo")
                self.assertLessEqual(medidas["scroll"], largura + 1, medidas)
                self.assertAlmostEqual(medidas["centerX"], largura / 2, delta=1)
                self.assertAlmostEqual(medidas["bottom"], medidas["height"], delta=1)
                for nome in ("Cancelar", "Criar campanha"):
                    expect(dialogo.get_by_role("button", name=nome, exact=True)).to_be_in_viewport()
                pagina.get_by_label("Nome da campanha", exact=False).fill("Campanha fictícia")
                pagina.get_by_label("O que queremos conseguir?", exact=True).fill("Conferir o formulário no celular.")
                self.foto(pagina, f"nova-ideia-toque-{largura}")
                # A navegação integral usa o mesmo formulário e deve continuar dentro do cartão.
                pagina.on("dialog", lambda dialog: dialog.accept())
                self.abrir(pagina, "nova_campanha")
                medidas = self.medir(pagina, ".mkt-nova-pagina")
                conteudo = self.medir(pagina, "#conteudo")
                self.assertAlmostEqual(medidas["centerX"], conteudo["centerX"], delta=1)
                self.assertLessEqual(medidas["scroll"], largura + 1, medidas)
                campos = pagina.locator('.mkt-nova-form input:not([type="hidden"]), .mkt-nova-form textarea')
                for campo in campos.all():
                    r = campo.bounding_box()
                    self.assertGreaterEqual(r["x"], medidas["left"])
                    self.assertLessEqual(r["x"] + r["width"], medidas["right"])
                self.foto(pagina, f"nova-pagina-{largura}")
            finally:
                contexto.close()
