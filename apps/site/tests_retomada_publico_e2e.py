"""Conferências das páginas públicas em navegador, sem enviar contatos reais."""
import os
import unittest
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.urls import reverse

from .icones_experiencias import ICONES_CORRIGIDOS
from .models import Experiencia, VitrineQuarto
from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E, _UnidadeVendavelMixin


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class RetomadaPublicoE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    LOCALE = "pt-BR"

    def foto(self, page, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(destino / f"{nome}.png"))

    def test_lps_preservam_formulario_toque_cor_e_limites_do_hero(self):
        for largura in (320, 390, 821, 1440):
            contexto = self._browser.new_context(viewport={"width": largura, "height": 900},
                                                 is_mobile=largura < 821, has_touch=largura < 821,
                                                 locale="pt-BR", reduced_motion="reduce")
            page = contexto.new_page()
            try:
                for rota in ("lp:fundador", "lp:fundador_2", "lp:inauguracao"):
                    with self.subTest(rota=rota, largura=largura):
                        self.assertEqual(page.goto(self.url(reverse(rota))).status, 200)
                        page.evaluate("document.fonts.ready")
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), largura + 1)
                        checkbox = page.locator('input[type="checkbox"]')
                        self.assertEqual(checkbox.count(), 1)
                        caixa = checkbox.bounding_box()
                        self.assertAlmostEqual(caixa["width"], 24, delta=.5)
                        self.assertAlmostEqual(caixa["height"], 24, delta=.5)
                        alvos = page.locator('header .brand, header .nav-logo, footer .links a, .rodape nav a')
                        self.assertGreater(alvos.count(), 0)
                        for alvo in alvos.all():
                            self.assertGreaterEqual(alvo.bounding_box()["height"], 44)
                        if rota != "lp:inauguracao":
                            cores = page.locator('.btn-primary').evaluate_all(
                                "es => [...new Set(es.map(e => getComputedStyle(e).backgroundColor))]")
                            self.assertEqual(cores, ["rgb(215, 160, 72)"])
                        else:
                            limites = page.locator('.hero-grid > *, .hero-date').evaluate_all("""es => es.map(e => {
                                const r=e.getBoundingClientRect(); return {classe:e.className,l:r.left,r:r.right};
                            })""")
                            for limite in limites:
                                self.assertGreaterEqual(limite["l"], -1, limite)
                                self.assertLessEqual(limite["r"], largura + 1, limite)
                        if rota == "lp:fundador" and largura == 1440:
                            referencia = page.locator('header .wrap').bounding_box()["x"]
                            for seletor in ('.historia .inner', '.local .inner'):
                                self.assertAlmostEqual(page.locator(seletor).bounding_box()["x"], referencia, delta=1)
                        links = page.locator('a[href*="privacidade"]').evaluate_all(
                            "es => es.map(e => ({texto:e.textContent.trim(),url:new URL(e.href).pathname}))")
                        por_texto = {}
                        for link in links:
                            por_texto.setdefault(link["texto"], set()).add(link["url"])
                        self.assertTrue(all(len(urls) == 1 for urls in por_texto.values()), por_texto)
                        self.foto(page, f"publico-{rota.replace(':', '-')}-{largura}")
            finally:
                contexto.close()

    def test_icones_datas_calendario_e_quarto_sem_foto(self):
        uh = self._semear_unidade()
        for ordem, antigo in enumerate(ICONES_CORRIGIDOS):
            Experiencia.objects.create(nome=f"Atividade de teste {ordem}", descricao="Teste visual", icone=antigo)
        call_command("corrigir_icones_experiencias", aplicar=True, stdout=StringIO())
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(self.url(reverse("core:home")))
        self.page.evaluate("document.fonts.ready")
        paths = self.page.locator('section').filter(has_text="Viva Uma Experiência").locator('svg path')
        self.assertEqual(paths.count(), 5)
        for area in paths.evaluate_all("es => es.map(e => {const r=e.getBBox();return r.width*r.height;})"):
            self.assertGreater(area, 200)
        campos = self.page.locator('[data-picker]').evaluate_all(
            "es => es.filter(e => e._flatpickr?.altInput).map(e => e._flatpickr.altInput.placeholder)")
        self.assertGreaterEqual(len(campos), 6)
        self.assertEqual(set(campos), {"Selecione"})
        self.page.goto(self.url(reverse("core:reservar")))
        self.page.evaluate("document.fonts.ready")
        self.assertEqual(self.page.locator('#form-datas').evaluate("e => getComputedStyle(e).alignItems"), "flex-start")
        cartoes = self.page.locator('#form-datas > div').all()
        self.assertEqual(len(cartoes), 2)
        self.assertLess(cartoes[0].bounding_box()["height"], cartoes[1].bounding_box()["height"])
        self.foto(self.page, "publico-reserva-calendario-1440")
        for largura in (320, 390, 821, 1440):
            self.page.set_viewport_size({"width": largura, "height": 900})
            self.assertEqual(self.page.goto(self.url(reverse("core:quarto_detalhe", args=[uh.pk]))).status, 200)
            self.page.evaluate("document.fonts.ready")
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
            self.assertEqual(self.page.locator('.qd__desc').count(), 0)
            if largura == 1440:
                self.assertLessEqual(self.page.locator('.qd__hero').bounding_box()["height"], 400)
            self.foto(self.page, f"publico-quarto-sem-foto-{largura}")
        # A área menor precisa crescer quando a descrição editorial ocupa mais linhas.
        VitrineQuarto.objects.filter(uh=uh).update(descricao="Descrição de conferência. " * 25)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(self.url(reverse("core:quarto_detalhe", args=[uh.pk])))
        self.page.evaluate("document.fonts.ready")
        painel = self.page.locator('.qd__panel').bounding_box()
        palco = self.page.locator('.qd__stage').bounding_box()
        self.assertGreaterEqual(painel['y'], palco['y'])
        self.assertLessEqual(painel['y'] + painel['height'], palco['y'] + palco['height'])
        self.foto(self.page, "publico-quarto-descricao-longa-1440")
