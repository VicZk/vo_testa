"""Regressões confirmadas na retomada da revisão de interface de outubro."""
import os
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from apps.reservas.models import ContaHospedagem, Reserva

from .auditoria_fixtures import criar_cenario_templates
from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class RetomadaFrontE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        self.c = criar_cenario_templates()
        self.client.force_login(self.c.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")

    def abrir(self, rota, largura, trilho=False, args=()):
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse(rota, args=args)))
        self.assertEqual(resposta.status, 200, rota)
        self.page.evaluate("document.fonts.ready")
        if largura > 820:
            app = self.page.locator(".app")
            if app.evaluate("e => e.classList.contains('recolhida')") != trilho:
                self.page.locator(".sidebar-toggle").click()
        self.page.evaluate("""async () => {
            const elementos = [document.querySelector('.app'), document.querySelector('.sidebar')];
            await Promise.all(elementos.flatMap(e => e.getAnimations({subtree:true}))
                .filter(a => Number.isFinite(a.effect?.getComputedTiming().endTime))
                .map(a => a.finished.catch(() => {})));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True)

    def test_selects_preservam_seta_e_espaco_para_a_opcao_em_cinco_estados(self):
        rotas = (("reservas:fnrh", (self.c.reserva.pk,)), ("caixa", ()),
                 ("tabela_precos", ()), ("estoque:compra_receber", ()))
        for rota, args in rotas:
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho, args)
                    medidas = self.page.locator("#conteudo select:visible").evaluate_all("""campos => campos
                        .filter(e => !e.multiple).map(e => {
                            const s=getComputedStyle(e);
                            return {id:e.id, seta:s.backgroundImage, recuo:parseFloat(s.paddingRight)};
                        })""")
                    self.assertTrue(medidas, rota)
                    for medida in medidas:
                        self.assertNotEqual(medida["seta"], "none", medida)
                        self.assertGreaterEqual(medida["recuo"], 28, medida)

    def test_previa_da_compra_aparece_calcula_e_some_ao_limpar_a_embalagem(self):
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self.abrir("estoque:compra_receber", largura, trilho)
                previa = self.page.locator("#compra-previa")
                expect(previa).to_be_hidden()
                self.page.locator("#id_embalagem").select_option(str(self.c.embalagem.pk))
                self.page.locator("#id_quantidade").fill("3")
                self.page.locator("#id_custo_embalagem").fill("27,90")
                expect(previa).to_be_visible()
                expect(self.page.locator("#compra-quantidade")).to_contain_text("36")
                expect(self.page.locator("#compra-total")).to_contain_text("83,70")
                self.page.locator("#id_embalagem").select_option("")
                expect(previa).to_be_hidden()

    def test_quarto_com_saida_hoje_mantem_o_saldo_inteiro_ao_lado_do_aviso(self):
        reserva = self.c.reserva
        reserva.status = Reserva.Status.HOSPEDADA
        reserva.checkin = self.c.hoje - timedelta(days=1)
        reserva.checkout = self.c.hoje
        reserva.valor_diaria = "2649.50"
        reserva.save()
        reserva.refresh_from_db()
        conta = ContaHospedagem.objects.create(reserva=reserva)
        conta.lancar_diarias(self.c.usuario)
        for rota in ("dashboard", "reservas:mapa_quartos"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho)
                    saldo = self.page.locator(".porta-saldo").first
                    expect(saldo).to_be_visible()
                    expect(saldo).to_contain_text("2.650")
                    expect(saldo.locator("..").locator(".porta-flag")).to_contain_text("saída hoje")
                    medida = saldo.evaluate("""e => {
                        const r=e.getBoundingClientRect(), p=e.closest('.porta-rodape').getBoundingClientRect();
                        return {excesso:e.scrollWidth-e.clientWidth, esquerda:r.left-p.left,
                                direita:r.right-p.right, baixo:r.bottom-p.bottom};
                    }""")
                    self.assertLessEqual(medida["excesso"], 1, medida)
                    self.assertGreaterEqual(medida["esquerda"], -1, medida)
                    self.assertLessEqual(medida["direita"], 1, medida)
                    self.assertLessEqual(medida["baixo"], 1, medida)
                    if largura in (320, 1440):
                        self.foto(f"retomada-saldo-{rota.replace(':', '-')}-{largura}-{trilho}")
