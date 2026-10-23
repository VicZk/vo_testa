"""Regressões de geometria: campos de RH e separação dos cartões de NPS."""

import os
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.nps.models import RespostaNPS
from apps.nucleo.models import UH, Funcionario, ModuloContratado, Pessoa, TipoUH, Usuario
from apps.reservas.models import Reserva

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class RhNpsLayoutE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo="reservas", defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="rh-nps-layout", password="senha-ficticia-123")
        self.funcionario = Funcionario.objects.create(
            pessoa=Pessoa.objects.create(nome="Funcionária fictícia de recepção e atendimento"),
            cargo="Atendimento aos hóspedes", setor="Recepção", admissao=timezone.localdate(),
            expediente_inicio="08:00", expediente_fim="17:00", intervalo_inicio="12:00", intervalo_fim="13:00")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self, nome, largura, *args):
        self.page.set_viewport_size({"width": largura, "height": 900})
        self.page.goto(self.url(reverse(nome, args=args)), wait_until="networkidle")
        self.page.wait_for_function("document.fonts.status === 'loaded'")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        if largura > 820:
            self.assertFalse(self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')"))

    def foto(self, nome):
        pasta = os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True)

    def conferir_campos(self):
        falhas = self.page.locator(".ficha-func").evaluate("""form => {
            const falhas = [];
            const campos = [...form.querySelectorAll('input:not([type=hidden]):not([type=checkbox]),select,textarea')]
                .filter(el => el.getClientRects().length);
            for (const el of campos) {
                const r = el.getBoundingClientRect(), p = el.closest('.campo').getBoundingClientRect();
                if (r.left < p.left - 1 || r.right > p.right + 1 || r.left < -1 || r.right > innerWidth + 1)
                    falhas.push({name:el.name, left:r.left, right:r.right, parentRight:p.right});
                if (r.height < 43) falhas.push({name:el.name, height:r.height});
            }
            for (let i=0;i<campos.length;i++) for (let j=i+1;j<campos.length;j++) {
                const a=campos[i].getBoundingClientRect(), b=campos[j].getBoundingClientRect();
                if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)
                    falhas.push({sobreposicao:[campos[i].name,campos[j].name]});
            }
            const blocos = [...form.querySelectorAll('.ficha-cols > .bloco-ficha')];
            for (const bloco of blocos) {
                const r = bloco.getBoundingClientRect(), pai = bloco.parentElement.getBoundingClientRect();
                if (r.width < Math.min(pai.width, 300)-1)
                    falhas.push({blocoEstreito: r.width, larguraDisponivel: pai.width});
            }
            return falhas;
        }""")
        self.assertEqual(falhas, [])
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), self.page.viewport_size["width"] + 1)

    def test_ficha_inline_e_cadastro_cabem_sem_sobrepor_campos(self):
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                self.abrir("funcionarios", largura)
                self.page.locator(".func-linha").filter(has_text=self.funcionario.pessoa.nome).click()
                painel = self.page.locator(f"#painel-{self.funcionario.pk}")
                expect(painel.locator('[name="admissao"]')).to_be_visible()
                for aba in ("Ficha RH", "Acesso Sistema", "Histórico"):
                    botao = painel.get_by_role("button", name=aba, exact=True)
                    botao.click()
                    expect(botao).to_have_class("func-aba on")
                    self.foto(f"rh-inline-{aba.split()[0].lower()}-{largura}")
                    self.conferir_campos()
                    self.assertLessEqual(painel.locator(".func-painel").bounding_box()["width"], largura)
                if largura == 390:
                    painel.get_by_role("button", name="Ficha RH", exact=True).click()
                    painel.locator('[name="cargo"]').fill("Atendimento e reservas")
                    painel.get_by_role("button", name="Salvar ficha", exact=True).click()
                    expect(painel.get_by_text("Ficha salva ✓", exact=True)).to_be_visible()
                    self.funcionario.refresh_from_db()
                    self.assertEqual(self.funcionario.cargo, "Atendimento e reservas")
                    self.assertEqual(str(self.funcionario.expediente_inicio), "08:00:00")
                    self.assertIsNone(self.funcionario.usuario_id)
                for rota, args in (("funcionario_novo", ()), ("funcionario_editar", (self.funcionario.pk,))):
                    self.abrir(rota, largura, *args)
                    self.foto(f"rh-{rota}-{largura}")
                    self.conferir_campos()

    def test_nps_separa_indicadores_secoes_e_acompanhamento(self):
        hoje = timezone.localdate()
        uh = UH.objects.create(numero="NPS-LAYOUT", tipo=TipoUH.objects.create(nome="Suíte fictícia", tarifa_base="200"))
        hospede = Pessoa.objects.create(nome="Hóspede fictícia para conferência da pesquisa")
        reserva = Reserva.objects.create(uh=uh, hospede=hospede, checkin=hoje-timedelta(days=3),
            checkout=hoje-timedelta(days=1), checkout_real=timezone.now()-timedelta(days=1),
            status=Reserva.Status.CHECKOUT, valor_diaria="200", criado_por=self.usuario)
        resposta = RespostaNPS.objects.create(reserva=reserva, hospede=hospede, nota=7,
            comentario="Atendimento atencioso. O quarto poderia estar mais silencioso à noite.", consentimento_versao="2026-10-22")
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                self.abrir("nps:painel", largura)
                self.page.get_by_text("Registrar acompanhamento", exact=True).click()
                self.page.locator(f"#tratativa-{resposta.pk}").fill("Contato fictício realizado com a hóspede.")
                self.foto(f"nps-espacamento-{largura}")
                espacos = self.page.locator(".nps-indicadores").evaluate("""indicadores => {
                    const secoes = [...indicadores.parentElement.querySelectorAll(':scope > section')];
                    return [secoes[0].getBoundingClientRect().top-indicadores.getBoundingClientRect().bottom,
                        secoes[1].getBoundingClientRect().top-secoes[0].getBoundingClientRect().bottom];
                }""")
                self.assertTrue(all(espaco >= 19 for espaco in espacos), espacos)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        self.page.get_by_role("button", name="Salvar acompanhamento", exact=True).click()
        expect(self.page.get_by_text("Ver acompanhamento", exact=True)).to_be_visible()
        resposta.refresh_from_db()
        self.assertEqual(resposta.tratativa, "Contato fictício realizado com a hóspede.")
