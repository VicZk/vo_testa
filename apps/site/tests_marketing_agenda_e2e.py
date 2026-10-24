"""Agenda semanal, canais e ações de entrega no navegador, inclusive sem JS."""
import os
import unittest
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.marketing.models import Campanha, PecaCampanha
from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class MarketingAgendaE2ETests(_BaseE2E):
    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="agenda-e2e", password="qa-local")
        self.client.force_login(self.usuario)
        self.cookie = {"name": settings.SESSION_COOKIE_NAME,
                       "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                       "url": self.live_server_url}
        self.campanha = Campanha.objects.create(
            nome="Campanha de primavera com uma descrição suficientemente extensa para o celular",
            inicio=date(2026, 10, 19), fim=date(2026, 10, 31), canais=["Instagram", "Rádio local"], fase="producao")
        self.entrega = PecaCampanha.objects.create(
            campanha=self.campanha, nome="Carrossel da programação da pousada e atividades da semana",
            tipo="post", canal="Instagram", data=date(2026, 10, 23))
        PecaCampanha.objects.create(campanha=self.campanha, nome="Chamada na rádio", tipo="anuncio",
                                   canal="Rádio local", data=date(2026, 10, 24))

    def abrir(self, pagina, query="data=2026-10-23"):
        pagina.context.add_cookies([self.cookie])
        pagina.goto(self.url(reverse("marketing:calendario")) + "?" + query)
        pagina.evaluate("document.fonts.ready")

    def conferir(self, pagina):
        medidas = pagina.evaluate("""() => {
            const visiveis = [...document.querySelectorAll('.mkt-calendario a,.mkt-calendario button,.mkt-canais button')].filter(e=>e.getClientRects().length);
            return {largura:document.documentElement.clientWidth, conteudo:document.documentElement.scrollWidth,
                alvos:visiveis.map(e=>{const r=e.getBoundingClientRect();return {texto:e.textContent.trim(),x:r.x,y:r.y,w:r.width,h:r.height}})};
        }""")
        self.assertLessEqual(medidas["conteudo"], medidas["largura"] + 1, medidas)
        for alvo in medidas["alvos"]:
            self.assertGreaterEqual(alvo["x"], -1, alvo)
            self.assertLessEqual(alvo["x"] + alvo["w"], medidas["largura"] + 1, alvo)

    def foto(self, pagina, nome):
        pasta = os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            Path(pasta).mkdir(parents=True, exist_ok=True)
            pagina.screenshot(path=str(Path(pasta) / f"agenda-{nome}.png"), full_page=True)

    def test_semana_mes_e_ano_cabem_em_cinco_estados_do_menu(self):
        for largura, recolhida in ((320, False), (390, False), (821, False), (1440, False), (1440, True)):
            with self.subTest(largura=largura, recolhida=recolhida):
                contexto = self._browser.new_context(viewport={"width": largura, "height": 900}, locale="pt-BR",
                                                     reduced_motion="reduce", has_touch=largura <= 390)
                try:
                    pagina = contexto.new_page()
                    pagina.add_init_script("localStorage.setItem('sidebar', '" + ("recolhida" if recolhida else "aberta") + "')")
                    self.abrir(pagina)
                    expect(pagina.locator(".mkt-agenda-dia")).to_have_count(8)
                    self.conferir(pagina)
                    self.foto(pagina, f"semana-{largura}-{'trilho' if recolhida else 'aberta'}")
                    for escala in ("mes", "ano"):
                        self.abrir(pagina, f"vista={escala}&ano=2026&mes=10")
                        self.conferir(pagina)
                        if largura <= 821:
                            expect(pagina.locator(".cal-scroll")).to_be_hidden()
                            expect(pagina.locator(".mkt-agenda-compacta")).to_be_visible()
                        else:
                            expect(pagina.locator(".cal-scroll")).to_be_visible()
                            expect(pagina.locator(".mkt-agenda-compacta")).to_be_hidden()
                        self.foto(pagina, f"{escala}-{largura}-{'trilho' if recolhida else 'aberta'}")
                finally:
                    contexto.close()

    def test_canal_e_acoes_rapidas_funcionam_sem_javascript(self):
        contexto = self._browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 900}, locale="pt-BR")
        try:
            pagina = contexto.new_page()
            self.abrir(pagina)
            pagina.get_by_role("button", name="Instagram", exact=True).click()
            expect(pagina.get_by_role("button", name="Instagram", exact=True)).to_have_attribute("aria-pressed", "true")
            expect(pagina.locator(".mkt-entrega")).to_have_count(1)
            for nome, estado in (("Iniciar produção", "em_producao"), ("Concluir produção", "pronta"), ("Reabrir produção", "em_producao")):
                pagina.get_by_role("button", name=nome, exact=True).click()
                self.entrega.refresh_from_db()
                self.assertEqual(self.entrega.status, estado)
                self.assertIn("canal=Instagram", pagina.url)
                self.assertIn("data=2026-10-23", pagina.url)
            pagina.get_by_role("link", name="Próximo período", exact=True).click()
            self.assertIn("data=2026-10-26", pagina.url)
            expect(pagina.locator(".mkt-entrega")).to_have_count(0)
            pagina.get_by_role("link", name="Período anterior", exact=True).click()
            expect(pagina.locator(".mkt-entrega")).to_have_count(1)
            self.conferir(pagina)
        finally:
            contexto.close()

    def test_filtro_de_canal_preserva_busca_na_lista_e_na_navegacao_por_teclado(self):
        self.page.context.add_cookies([self.cookie])
        self.page.goto(self.url(reverse("marketing:entregas")) + "?q=Carrossel&tipo=post")
        canal = self.page.get_by_role("button", name="Instagram", exact=True)
        canal.focus()
        canal.press("Enter")
        expect(self.page.get_by_label("Buscar entrega")).to_have_value("Carrossel")
        expect(self.page.get_by_label("Tipo", exact=True)).to_have_value("post")
        expect(self.page.locator(".mkt-entrega")).to_have_count(1)
        self.page.get_by_role("button", name="Todos os canais", exact=True).click()
        expect(self.page.get_by_label("Buscar entrega")).to_have_value("Carrossel")
