"""Produzir avulsas e entregas vinculadas em cinco estados reais do menu."""
import os
import unittest
from contextlib import contextmanager
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
class MarketingAvulsasE2ETests(_BaseE2E):
    estados = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="avulsas-e2e")
        self.client.force_login(self.usuario)
        self.cookie = {"name": settings.SESSION_COOKIE_NAME,
                       "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                       "url": self.live_server_url}
        self.campanha = Campanha.objects.create(nome="Campanha de referência", fase="producao")
        self.avulsa = PecaCampanha.objects.create(nome="Avulsa de referência", tipo="post", canal="Instagram",
                                                data=date(2026, 10, 23))
        self.vinculada = PecaCampanha.objects.create(campanha=self.campanha, nome="Vinculada de referência",
                                                   tipo="post", canal="Instagram", data=date(2026, 10, 23))

    @contextmanager
    def tela(self, largura, trilho, *, javascript=True):
        contexto = self._browser.new_context(viewport={"width": largura, "height": 900}, locale="pt-BR",
                                             reduced_motion="reduce", has_touch=largura <= 390,
                                             java_script_enabled=javascript)
        try:
            contexto.add_cookies([self.cookie])
            pagina = contexto.new_page()
            if javascript:
                pagina.add_init_script("localStorage.setItem('sidebar', '" + ("recolhida" if trilho else "aberta") + "')")
            yield pagina
        finally:
            contexto.close()

    def abrir(self, pagina, nome="entregas", args=None, query=""):
        pagina.goto(self.url(reverse("marketing:" + nome, args=args)) + ("?" + query if query else ""))
        pagina.evaluate("document.fonts.ready")

    def conferir(self, pagina, largura):
        medidas = pagina.evaluate("""() => {
            const itens=[...document.querySelectorAll('.mkt-entrega,.mkt-entrega-form input,.mkt-entrega-form select,.mkt-entrega-form button,.mkt-entregas-filtros input,.mkt-entregas-filtros select,.mkt-canais button')].filter(e=>e.getClientRects().length);
            return {scroll:document.documentElement.scrollWidth, largura:document.documentElement.clientWidth,
                itens:itens.map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,x:r.x,w:r.width,h:r.height}})};
        }""")
        self.assertLessEqual(medidas["scroll"], medidas["largura"] + 1, medidas)
        for item in medidas["itens"]:
            self.assertGreaterEqual(item["x"], -1, item)
            self.assertLessEqual(item["x"] + item["w"], largura + 1, item)
            if largura <= 390 and item["tag"] == "BUTTON":
                self.assertGreaterEqual(item["h"], 44, item)

    def foto(self, pagina, nome):
        pasta = os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            Path(pasta).mkdir(parents=True, exist_ok=True)
            pagina.screenshot(path=str(Path(pasta) / f"avulsas-{nome}.png"), full_page=True)

    def test_novas_avulsa_e_vinculada_em_cinco_estados(self):
        for largura, trilho in self.estados:
            with self.subTest(largura=largura, trilho=trilho), self.tela(largura, trilho) as pagina:
                for vincular in (False, True):
                    self.abrir(pagina)
                    pagina.get_by_role("link", name="Nova entrega", exact=True).click()
                    expect(pagina.get_by_label("Campanha", exact=True)).to_have_value("")
                    nome = f"Nova {'vinculada' if vincular else 'avulsa'} {largura}-{trilho}"
                    pagina.get_by_label("Nome da entrega", exact=False).fill(nome)
                    pagina.get_by_label("Tipo", exact=False).select_option("post")
                    if vincular:
                        pagina.get_by_label("Campanha", exact=True).select_option(str(self.campanha.pk))
                    self.conferir(pagina, largura)
                    if not vincular:
                        self.foto(pagina, f"nova-{largura}-{'trilho' if trilho else 'aberta'}")
                    pagina.get_by_role("button", name="Salvar entrega", exact=True).click()
                    expect(pagina.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
                    peca = PecaCampanha.objects.get(nome=nome)
                    self.assertEqual(peca.campanha_id, self.campanha.pk if vincular else None)
                self.campanha.refresh_from_db()
                self.assertEqual(self.campanha.fase, "producao")

    def test_chips_filtram_todas_avulsas_e_por_campanha_com_teclado(self):
        for largura, trilho in self.estados:
            with self.subTest(largura=largura, trilho=trilho), self.tela(largura, trilho) as pagina:
                self.abrir(pagina, query="q=refer%C3%AAncia&canal=Instagram")
                chip = pagina.get_by_role("button", name="Sem campanha", exact=True)
                chip.focus()
                self.assertNotEqual(chip.evaluate("e=>getComputedStyle(e).outlineStyle"), "none")
                chip.press("Enter")
                expect(pagina.locator("[data-entrega]")).to_have_count(1)
                expect(pagina.locator(f'[data-entrega="{self.avulsa.pk}"]')).to_be_visible()
                expect(pagina.get_by_role("button", name="Sem campanha", exact=True)).to_have_attribute("aria-pressed", "true")
                expect(pagina.get_by_label("Buscar entrega")).to_have_value("referência")
                self.assertIn("canal=Instagram", pagina.url)
                self.conferir(pagina, largura)
                self.foto(pagina, f"filtro-{largura}-{'trilho' if trilho else 'aberta'}")
                pagina.get_by_role("button", name="Por campanha", exact=True).click()
                expect(pagina.locator("[data-entrega]")).to_have_count(1)
                expect(pagina.locator(f'[data-entrega="{self.vinculada.pk}"]')).to_be_visible()
                pagina.get_by_label("Campanha", exact=True).select_option(str(self.campanha.pk))
                pagina.get_by_role("button", name="Filtrar", exact=True).click()
                expect(pagina.locator("[data-entrega]")).to_have_count(1)
                pagina.get_by_role("button", name="Todas", exact=True).click()
                expect(pagina.locator("[data-entrega]")).to_have_count(2)
                expect(pagina.get_by_label("Campanha", exact=True)).to_have_value("")

    def test_acoes_rapidas_de_avulsa_e_vinculada_em_cinco_estados(self):
        for largura, trilho in self.estados:
            marcador = f"Ações {largura}-{trilho}"
            pares = [PecaCampanha.objects.create(nome=f"{marcador} {i}", tipo="post", campanha=campanha)
                     for i, campanha in enumerate((None, self.campanha))]
            with self.subTest(largura=largura, trilho=trilho), self.tela(largura, trilho) as pagina:
                self.abrir(pagina, query="q=" + marcador)
                for peca in pares:
                    for acao, estado in (("Iniciar produção", "em_producao"), ("Concluir produção", "pronta"),
                                         ("Reabrir produção", "em_producao")):
                        linha = pagina.locator(f'[data-entrega="{peca.pk}"]')
                        linha.get_by_role("button", name=acao, exact=True).click()
                        expect(pagina.locator(f'[data-entrega="{peca.pk}"] .selo')).to_have_text(
                            "Pronta" if estado == "pronta" else "Em produção")
                        peca.refresh_from_db()
                        self.assertEqual(peca.status, estado)
                        self.assertEqual(peca.concluida_por_id, self.usuario.pk if estado == "pronta" else None)
                    self.assertEqual(peca.versao, 4)
                self.conferir(pagina, largura)
                self.campanha.refresh_from_db()
                self.assertEqual(self.campanha.fase, "producao")

    def test_editar_e_vincular_avulsa_preserva_vinculo_em_cinco_estados(self):
        for largura, trilho in self.estados:
            peca = PecaCampanha.objects.create(nome=f"Vínculo {largura}-{trilho}", tipo="post", status="em_producao")
            with self.subTest(largura=largura, trilho=trilho), self.tela(largura, trilho) as pagina:
                self.abrir(pagina, "editar_entrega", [peca.pk])
                expect(pagina.get_by_label("Campanha", exact=True)).to_be_enabled()
                pagina.get_by_label("Nome da entrega", exact=False).fill(peca.nome + " revisto")
                pagina.get_by_role("button", name="Salvar entrega", exact=True).click()
                expect(pagina.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
                peca.refresh_from_db()
                self.assertIsNone(peca.campanha_id)
                self.abrir(pagina, "editar_entrega", [peca.pk])
                pagina.get_by_label("Campanha", exact=True).select_option(str(self.campanha.pk))
                pagina.get_by_role("button", name="Salvar entrega", exact=True).click()
                expect(pagina.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
                peca.refresh_from_db()
                self.assertEqual((peca.campanha_id, peca.status), (self.campanha.pk, "em_producao"))
                self.abrir(pagina, "editar_entrega", [peca.pk])
                expect(pagina.get_by_label("Campanha", exact=True)).to_be_disabled()
                self.conferir(pagina, largura)

    def test_agenda_avulsa_edita_e_volta_ao_periodo_em_cinco_estados(self):
        for largura, trilho in self.estados:
            with self.subTest(largura=largura, trilho=trilho), self.tela(largura, trilho) as pagina:
                for vista in ("semana", "mes", "ano"):
                    query = f"vista={vista}&data=2026-10-23&ano=2026&mes=10&canal=Instagram"
                    self.abrir(pagina, "calendario", query=query)
                    linha = pagina.locator(f'[data-entrega="{self.avulsa.pk}"]')
                    expect(linha).to_be_visible()
                    expect(linha.get_by_text("Sem campanha", exact=True)).to_be_visible()
                    self.assertEqual(linha.locator("a[hx-get]").count(), 0)
                    linha.get_by_role("link", name="Editar entrega", exact=True).click()
                    pagina.get_by_role("link", name="Voltar", exact=True).click()
                    expect(pagina.locator(f'[data-entrega="{self.avulsa.pk}"]')).to_be_visible()
                    self.assertIn("vista=" + vista, pagina.url)
                    self.assertIn("canal=Instagram", pagina.url)
                self.foto(pagina, f"agenda-{largura}-{'trilho' if trilho else 'aberta'}")

    def test_avulsa_sem_javascript_cria_filtra_e_conclui(self):
        for largura, _trilho in self.estados:
            # Sem JavaScript, o menu mantém sua apresentação padrão, inclusive em 1440.
            with self.subTest(largura=largura), self.tela(largura, False, javascript=False) as pagina:
                self.abrir(pagina)
                pagina.get_by_role("link", name="Nova entrega", exact=True).click()
                nome = f"Sem JS {largura}-{_trilho}"
                pagina.get_by_label("Nome da entrega", exact=False).fill(nome)
                pagina.get_by_label("Tipo", exact=False).select_option("post")
                pagina.get_by_role("button", name="Salvar entrega", exact=True).click()
                expect(pagina.get_by_role("heading", name="Entregas", exact=True)).to_be_visible()
                peca = PecaCampanha.objects.get(nome=nome)
                self.assertIsNone(peca.campanha_id)
                pagina.get_by_role("button", name="Sem campanha", exact=True).click()
                for acao in ("Iniciar produção", "Concluir produção"):
                    pagina.locator(f'[data-entrega="{peca.pk}"]').get_by_role("button", name=acao, exact=True).click()
                peca.refresh_from_db()
                self.assertEqual(peca.status, "pronta")
                self.assertIn("vinculo=sem", pagina.url)
                self.conferir(pagina, largura)
