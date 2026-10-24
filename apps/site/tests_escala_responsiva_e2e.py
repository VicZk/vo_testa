"""A semana da Escala deve caber e continuar editável em cada largura útil."""

import os
import unittest
from datetime import time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.escala import services
from apps.escala.models import Atribuicao, HoraExtra, Turno
from apps.nucleo.models import Funcionario, ModuloContratado, Pessoa, Usuario

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class EscalaResponsivaE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True), (2560, False))

    def setUp(self):
        super().setUp()
        ModuloContratado.objects.update(ativo=False)
        ModuloContratado.objects.update_or_create(codigo="escala", defaults={"ativo": True})
        cache.clear()
        self.usuario = Usuario.objects.create_superuser(username="escala-responsiva", password="senha-qa")
        self.funcionarios = [
            Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=nome), cargo="Atendimento", setor="recepcao")
            for nome in ("Ana Carolina de Albuquerque e Silva", "Bruno Henrique Fernandes de Oliveira",
                         "Camila Aparecida dos Santos e Costa", "Daniel Augusto Figueiredo de Albuquerque")
        ]
        self.turnos = [Turno.objects.create(nome=nome, setor="recepcao", inicio=time(inicio), fim=time(fim))
                       for nome, inicio, fim in (("Recepção e atendimento da manhã", 7, 13),
                                                ("Recepção e atendimento da tarde", 13, 19))]
        self.dia = services.inicio_da_semana(timezone.localdate()) + timedelta(days=7)
        self.atribuicoes = []
        for turno, func in zip(self.turnos, self.funcionarios):
            for deslocamento in (0, 6):
                self.atribuicoes.append(Atribuicao.objects.create(
                    turno=turno, funcionario=func, data=self.dia + timedelta(days=deslocamento)))
        self.atribuicoes.append(Atribuicao.objects.create(
            turno=self.turnos[0], funcionario=self.funcionarios[2], data=self.dia))
        for func, tipo, deslocamento in ((self.funcionarios[0], "banco", 0),
                                         (self.funcionarios[1], "extra", 6)):
            HoraExtra.objects.create(funcionario=func, data=self.dia + timedelta(days=deslocamento),
                                     inicio=time(19), fim=time(21), tipo=tipo)
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self, largura, trilho=False):
        p = self.page
        p.set_viewport_size({"width": largura, "height": 900})
        p.goto(self.url(reverse("escala:grade")) + f"?inicio={self.dia.isoformat()}&setor=recepcao")
        expect(p.locator(".escala-grade")).to_be_visible()
        p.evaluate("document.fonts.ready")
        if largura > 820:
            recolhida = p.locator(".app").evaluate("el => el.classList.contains('recolhida')")
            if recolhida != trilho:
                p.locator(".sidebar-toggle").click()
            p.wait_for_function("""trilho => {
                const app = document.querySelector('.app'), css = getComputedStyle(app);
                const alvo = parseFloat(css.getPropertyValue(trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                return app.classList.contains('recolhida') === trilho &&
                    Math.abs(parseFloat(css.gridTemplateColumns) - alvo) < .1 &&
                    Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width - alvo) < .1;
            }""", arg=trilho)

    def conferir_limites(self, largura):
        p = self.page
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
        erros = p.locator(".escala-grade-wrap").evaluate("""wrap => {
            const fora = [];
            for (const el of [wrap, ...wrap.querySelectorAll('td, .escala-chip, .he-card, .he-form')]) {
                if (el.scrollWidth > el.clientWidth + 1) fora.push(`${el.className}: ${el.scrollWidth}/${el.clientWidth}`);
            }
            for (const el of wrap.querySelectorAll('td, .escala-chip, .he-card, .he-form, button, input')) {
                const caixa = el.getBoundingClientRect();
                const pai = el.closest('td') || wrap;
                const limite = pai.getBoundingClientRect();
                if (caixa.left < limite.left - 1 || caixa.right > limite.right + 1)
                    fora.push(`${el.className || el.tagName}: fora da célula`);
            }
            return fora;
        }""")
        self.assertEqual(erros, [], erros)
        if largura <= 820:
            for botao in p.locator(".escala-grade :is(.he-add, .chip-x, .he-x)").all():
                caixa = botao.bounding_box()
                self.assertGreaterEqual(caixa["width"], 44)
                self.assertGreaterEqual(caixa["height"], 44)

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(pasta / f"escala-responsiva-{nome}.png"),
                                 full_page=True, animations="disabled")

    def test_semana_completa_cabe_em_cinco_estados_e_volta_a_matriz_quando_ha_espaco(self):
        p = self.page
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self.abrir(largura, trilho)
                expect(p.locator(".escala-celula")).to_have_count(14)
                expect(p.locator(".escala-chip")).to_have_count(5)
                expect(p.locator(".he-card")).to_have_count(2)
                expect(p.locator(".escala-dia-vazio")).to_have_count(10)
                self.conferir_limites(largura)
                modo = p.locator(".escala-grade").evaluate("el => getComputedStyle(el).display")
                self.assertEqual(modo, "table" if largura == 2560 else "block")
                for linha in p.locator(".escala-grade tbody tr").all():
                    expect(linha.locator("th[scope=row]")).to_be_visible()
                    self.assertEqual(linha.locator("td").evaluate_all("els => els.map(e => e.dataset.data)"),
                                     [(self.dia + timedelta(days=n)).isoformat() for n in range(7)])
                    if largura < 2560:
                        for rotulo in linha.locator(".escala-dia-celula").all():
                            expect(rotulo).to_be_visible()
                p.locator(".he-add").first.click()
                expect(p.locator(".he-form")).to_be_visible()
                self.conferir_limites(largura)
                self.foto(f"{largura}-{'trilho' if trilho else 'aberta'}")
                p.get_by_role("button", name="Cancelar", exact=True).click()
                expect(p.locator(".he-form")).to_have_count(0)

    def test_celular_salva_e_remove_hora_extra_e_atribuicao_na_semana_filtrada(self):
        p = self.page
        self.abrir(320)
        atribuicao = self.atribuicoes[-1]
        p.locator(f'[data-atribuicao="{atribuicao.pk}"] .he-add').click()
        formulario = p.locator(".he-form")
        formulario.locator(".ini").fill("16:00")
        formulario.locator(".fim").fill("17:30")
        formulario.locator('[value="extra"]').check()
        expect(formulario.locator(".tt")).to_have_text("1h30")
        self.conferir_limites(320)
        with p.expect_response(lambda r: r.request.method == "POST" and r.url.endswith(reverse("escala:editar"))):
            formulario.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.locator(".he-card")).to_have_count(3)
        he = HoraExtra.objects.get(funcionario=self.funcionarios[2])
        self.assertEqual((he.data, he.inicio, he.fim, he.tipo), (self.dia, time(16), time(17, 30), "extra"))
        expect(p.locator(".escala-he-resumo")).to_contain_text("5h30")
        self.conferir_limites(320)
        with p.expect_response(lambda r: r.request.method == "POST"):
            p.locator(f'[data-he="{he.pk}"]').click()
        expect(p.locator(".he-card")).to_have_count(2)
        self.assertFalse(HoraExtra.objects.filter(pk=he.pk).exists())
        with p.expect_response(lambda r: r.request.method == "POST"):
            p.locator(f'[data-remover="{atribuicao.pk}"]').click()
        expect(p.locator(".escala-chip")).to_have_count(4)
        self.assertFalse(Atribuicao.objects.filter(pk=atribuicao.pk).exists())
        expect(p.locator("#f-setor")).to_have_value("recepcao")
        expect(p.locator("#escala-page")).to_have_attribute("data-inicio", self.dia.isoformat())
        self.conferir_limites(320)

    def test_arrasto_no_turno_em_cartoes_mantem_destino_e_impressao_usa_colunas(self):
        p = self.page
        self.abrir(1440)
        atribuicao = self.atribuicoes[-1]
        destino = self.dia + timedelta(days=2)
        celula = p.locator(f'.escala-drop[data-turno="{self.turnos[0].pk}"][data-data="{destino}"]')
        with p.expect_response(lambda r: r.request.method == "POST"):
            p.locator(f'[data-atribuicao="{atribuicao.pk}"]').drag_to(celula)
        expect(celula.locator(f'[data-atribuicao="{atribuicao.pk}"]')).to_be_visible()
        atribuicao.refresh_from_db()
        self.assertEqual((atribuicao.data, atribuicao.turno_id), (destino, self.turnos[0].pk))
        self.conferir_limites(1440)
        p.emulate_media(media="print")
        self.assertEqual(p.locator(".escala-grade").evaluate("el => getComputedStyle(el).display"), "table")
        self.assertEqual(p.locator(".escala-grade thead").evaluate("el => getComputedStyle(el).position"), "static")
