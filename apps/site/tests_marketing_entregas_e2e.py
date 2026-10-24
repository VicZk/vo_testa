"""Entregas por tipo: consulta, edição e material em larguras reais do CRM."""
import os
import unittest
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.marketing.models import Campanha, ItemChecklist, PecaCampanha
from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class MarketingEntregasE2ETests(_BaseE2E):
    def setUp(self):
        super().setUp()
        cache.clear()
        for modulo in (Modulo.MARKETING, Modulo.COMERCIAL):
            ModuloContratado.objects.update_or_create(codigo=modulo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="entregas-e2e", password="teste-local-123")
        self.client.force_login(self.usuario)
        self.cookie = {"name": settings.SESSION_COOKIE_NAME,
                       "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                       "url": self.live_server_url}
        self.campanha = Campanha.objects.create(nome="Inauguração da pousada", fase="producao")
        self.arquivada = Campanha.objects.create(nome="Campanha encerrada", fase="encerrada")
        self.material = ItemChecklist.objects.create(
            campanha=self.campanha, chave="arte_final",
            arquivo=SimpleUploadedFile("arte-final.pdf", b"%PDF-1.4\nMaterial ficticio de QA", "application/pdf"))
        self.pronta = PecaCampanha.objects.create(
            campanha=self.campanha, nome="Flyer da inauguração", tipo="impresso", canal="Recepção",
            status="pronta", material_checklist=self.material)
        PecaCampanha.objects.create(campanha=self.campanha, nome="Anúncio de reservas", tipo="anuncio",
                                   canal="Meta Ads", status="em_producao")
        PecaCampanha.objects.create(campanha=self.campanha, nome="Carrossel da casa", tipo="post",
                                   canal="Instagram", status="a_fazer")
        PecaCampanha.objects.create(campanha=self.arquivada, nome="Peça antiga preservada", status="pronta")

    def preparar(self, pagina):
        pagina.context.add_cookies([self.cookie])
        pagina.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        pagina.emulate_media(reduced_motion="reduce")

    def abrir(self, pagina, nome="entregas", args=None):
        pagina.goto(self.url(reverse("marketing:" + nome, args=args)))
        pagina.wait_for_function("document.fonts.status === 'loaded'")

    def sem_vazamento(self, pagina, seletor):
        medida = pagina.evaluate("({largura: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})")
        self.assertLessEqual(medida["scroll"], medida["largura"] + 1, medida)
        for item in pagina.locator(seletor).all():
            if not item.is_visible():
                continue
            caixa = item.bounding_box()
            self.assertGreaterEqual(caixa["x"], -1, caixa)
            self.assertLessEqual(caixa["x"] + caixa["width"], medida["largura"] + 1, caixa)

    def foto(self, pagina, nome):
        pasta = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            pagina.screenshot(path=str(destino / f"marketing-entregas-{nome}.png"), full_page=True)

    def test_lista_filtros_e_formulario_em_quatro_larguras(self):
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                contexto = self._browser.new_context(
                    viewport={"width": largura, "height": 900}, locale="pt-BR",
                    has_touch=largura <= 390, is_mobile=largura <= 390,
                    reduced_motion="reduce")
                try:
                    pagina = contexto.new_page()
                    self.preparar(pagina)
                    self.abrir(pagina)
                    expect(pagina.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
                    if largura == 821:
                        self.assertNotIn("recolhida", pagina.locator("#app").get_attribute("class"))
                    self.sem_vazamento(pagina, ".mkt-entregas input, .mkt-entregas select, .mkt-entrega, .mkt-entrega-acoes a")
                    self.foto(pagina, f"lista-{largura}")
                    pagina.get_by_label("Tipo", exact=True).select_option("impresso")
                    pagina.get_by_label("Situação", exact=True).select_option("pronta")
                    pagina.get_by_label("Campanha", exact=True).select_option(str(self.campanha.pk))
                    pagina.get_by_label("Buscar entrega").fill("Flyer")
                    pagina.get_by_role("button", name="Filtrar", exact=True).click()
                    expect(pagina.locator("[data-entrega]")).to_have_count(1)
                    expect(pagina.get_by_role("heading", name="Flyer da inauguração")).to_be_visible()
                    expect(pagina.get_by_text("Data de conclusão não registrada", exact=True)).to_be_visible()
                    self.sem_vazamento(pagina, ".mkt-entregas input, .mkt-entregas select, .mkt-entrega")
                    pagina.get_by_role("link", name="Editar entrega", exact=True).click()
                    expect(pagina.get_by_role("heading", name="Editar entrega", exact=True)).to_be_visible()
                    expect(pagina.get_by_label("Situação da produção")).to_have_value("pronta")
                    self.sem_vazamento(pagina, ".mkt-entrega-form input, .mkt-entrega-form select, .mkt-entrega-form button")
                    self.foto(pagina, f"formulario-{largura}")
                    pagina.get_by_role("link", name="Voltar", exact=True).click()
                    expect(pagina.get_by_label("Buscar entrega")).to_have_value("Flyer")
                    expect(pagina.locator("[data-entrega]")).to_have_count(1)
                finally:
                    contexto.close()

    def test_criar_vincular_material_editar_estados_e_abrir_download(self):
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.preparar(self.page)
        self.abrir(self.page)
        self.page.get_by_role("link", name="Nova entrega", exact=True).click()
        expect(self.page.get_by_role("heading", name="Nova entrega", exact=True)).to_be_visible()
        self.page.get_by_label("Campanha", exact=True).select_option(str(self.campanha.pk))
        expect(self.page.get_by_label("Anexo já salvo na campanha").locator("option")).to_have_count(2)
        nome = 'Convite <img src=x onerror="window.injetado=1">'
        self.page.get_by_label("Nome da entrega").fill(nome)
        self.page.get_by_label("Tipo", exact=False).select_option("impresso")
        self.page.get_by_label("Canal", exact=True).fill("Recepção")
        self.page.get_by_label("Situação da produção").select_option("em_producao")
        self.page.get_by_label("Anexo já salvo na campanha").select_option(str(self.material.pk))
        self.page.get_by_role("button", name="Salvar entrega").click()
        expect(self.page.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
        peca = PecaCampanha.objects.get(nome=nome)
        self.assertEqual(peca.status, "em_producao")
        self.assertEqual(peca.material_checklist_id, self.material.pk)
        self.assertIsNone(self.page.evaluate("window.injetado"))
        linha = self.page.locator(f'[data-entrega="{peca.pk}"]')
        expect(linha.get_by_role("heading", name=nome, exact=True)).to_be_visible()
        linha.get_by_role("link", name="Editar entrega").click()
        self.page.get_by_label("Situação da produção").select_option("pronta")
        self.page.get_by_role("button", name="Salvar entrega").click()
        peca.refresh_from_db()
        self.assertIsNotNone(peca.concluida_em)
        self.assertEqual(peca.concluida_por_id, self.usuario.pk)
        linha = self.page.locator(f'[data-entrega="{peca.pk}"]')
        expect(linha.get_by_text("Pronta", exact=True)).to_be_visible()
        with self.page.expect_download() as evento:
            linha.get_by_role("link", name="Baixar anexo").click()
        download = evento.value
        self.assertEqual(download.suggested_filename, "arte-final.pdf")
        self.assertIsNone(download.failure())
        linha.get_by_role("link", name="Editar entrega").click()
        self.page.get_by_label("Situação da produção").select_option("a_fazer")
        self.page.get_by_role("button", name="Salvar entrega").click()
        peca.refresh_from_db()
        self.assertEqual(peca.status, "a_fazer")
        self.assertIsNone(peca.concluida_em)
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.fase, "producao")
        self.assertIsNone(self.campanha.aprovada_em)
