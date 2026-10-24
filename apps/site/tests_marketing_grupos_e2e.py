"""Cinco grupos legíveis e avanços explícitos que conservam os requisitos reais."""
import os
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.marketing import services
from apps.marketing.models import Campanha
from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class MarketingGruposE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="grupos-e2e")
        self.campanhas = {
            fase: Campanha.objects.create(nome=f"Campanha de hospedagem e experiências · {nome}",
                                          fase=fase, canais=["Instagram"], responsavel=self.usuario,
                                          verba_prevista=Decimal("50"))
            for fase, nome in Campanha.Fase.choices
        }
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self, largura=1440, trilho=False):
        self.page.set_viewport_size({"width": largura, "height": 900})
        self.page.goto(self.url(reverse("marketing:quadro")) + "?canal=Instagram&meus=1")
        self.page.evaluate("document.fonts.ready")
        if largura > 820:
            if self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')") != trilho:
                self.page.locator(".sidebar-toggle").click()
            self.page.wait_for_function("""trilho => {
                const app = document.querySelector('.app'), css = getComputedStyle(app);
                const alvo = parseFloat(css.getPropertyValue(trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                return app.classList.contains('recolhida') === trilho &&
                    Math.abs(parseFloat(css.gridTemplateColumns) - alvo) < .1;
            }""", arg=trilho)

    def test_cinco_grupos_e_sete_subetapas_cabem_nos_cinco_estados_do_menu(self):
        for largura, trilho in ((320, False), (390, False), (821, False), (1440, False), (1440, True)):
            with self.subTest(largura=largura, trilho=trilho):
                self.abrir(largura, trilho)
                expect(self.page.locator(".mk-coluna-nome")).to_have_text(
                    ["Planejamento", "Aprovação", "Produção", "No ar", "Encerradas"])
                expect(self.page.locator(".mk-card")).to_have_count(7)
                expect(self.page.locator('.mk-card[draggable="true"]')).to_have_count(0)
                expect(self.page.locator('[data-grupo="planejamento"] .mk-card-subetapa')).to_have_count(2)
                expect(self.page.locator('[data-grupo="producao"] .mk-card-subetapa')).to_have_count(2)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
                fora = self.page.locator(".mk-colunas").evaluate("""quadro => {
                    const erros = [];
                    for (const el of [quadro, ...quadro.querySelectorAll('.mk-coluna, .mk-card')]) {
                        if (el.scrollWidth > el.clientWidth + 1) erros.push(el.className);
                    }
                    for (const el of quadro.querySelectorAll('button, .mk-card-passo')) {
                        const r = el.getBoundingClientRect(), c = el.closest('.mk-card').getBoundingClientRect();
                        if (r.left < c.left - 1 || r.right > c.right + 1 || r.height < 43.9)
                            erros.push(el.className + ': alvo fora ou menor que 44px');
                    }
                    return erros;
                }""")
                self.assertEqual(fora, [])
                pasta = os.environ.get("E2E_EVIDENCIAS")
                if pasta:
                    destino = Path(pasta)
                    destino.mkdir(parents=True, exist_ok=True)
                    self.page.screenshot(path=str(destino / f"grupos-{largura}-{'trilho' if trilho else 'aberto'}.png"), full_page=True)

    def test_proximo_passo_abre_portao_e_atualiza_subetapa_no_mesmo_grupo(self):
        campanha = self.campanhas["ideia"]
        self.abrir(390)
        card = self.page.locator(f'[data-camp="{campanha.pk}"]')
        card.locator(".mk-card-passo").click()
        avancar = self.page.get_by_role("button", name="Avançar para Proposta", exact=True)
        expect(avancar).to_be_disabled()
        self.page.get_by_role("button", name="Fechar campanha", exact=True).click()
        campanha.objetivo = "Aumentar as reservas do próximo feriado"
        campanha.save()
        card.locator(".mk-card-passo").click()
        expect(avancar).to_be_enabled()
        avancar.click()
        expect(self.page.locator(".fx-cod")).to_contain_text("Proposta")
        expect(self.page.get_by_role("button", name="Avançar para Aprovação", exact=True)).to_be_disabled()
        self.page.get_by_role("button", name="Fechar campanha", exact=True).click()
        expect(card.locator(".mk-card-subetapa")).to_have_text("Subetapa: Proposta")
        expect(card.locator(".mk-card-passo")).to_contain_text("Solicitar aprovação")
        expect(self.page.locator(f'[data-grupo="planejamento"] [data-camp="{campanha.pk}"]')).to_be_visible()
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "proposta")

    def test_aprovar_muda_para_producao_e_mantem_canal_e_so_meus(self):
        campanha = self.campanhas["aprovacao"]
        services.definir_teto(services.mes_atual(), "1000")
        self.abrir()
        self.page.locator(f'[data-camp="{campanha.pk}"]').get_by_role("button", name="Aprovar", exact=True).click()
        expect(self.page.locator(f'[data-grupo="producao"] [data-camp="{campanha.pk}"]')).to_be_visible()
        self.assertIn("canal=Instagram", self.page.url)
        self.assertIn("meus=1", self.page.url)
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "estruturacao")
        self.assertEqual(campanha.verba_travada, Decimal("50"))
