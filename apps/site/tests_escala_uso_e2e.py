"""Fluxos reais da escala: correção de entradas, ausências e decisão de troca."""

import os
import unittest
from datetime import time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.escala import services
from apps.escala.models import Atribuicao, Ausencia, TrocaTurno, Turno
from apps.nucleo.models import Funcionario, ModuloContratado, Pessoa, Usuario

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class EscalaUsoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        ModuloContratado.objects.update_or_create(codigo="escala", defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="escala-navegador", password="senha-qa")
        nomes = ("Ana Carolina de Albuquerque e Silva", "Bruno Henrique Fernandes de Oliveira",
                 "Camila Aparecida dos Santos e Costa")
        self.funcionarios = [Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=nome),
                                                       cargo="Atendimento", setor="recepcao") for nome in nomes]
        self.turno = Turno.objects.create(nome="Recepção e atendimento da manhã", setor="recepcao",
                                         inicio=time(8), fim=time(16))
        self.dia = services.inicio_da_semana(timezone.localdate()) + timedelta(days=7)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def abrir_formulario(self, resumo):
        """O formulário de cadastro mora num <details> acima da lista: ele nasce
        fechado quando já existem registros, para a tabela ficar com a largura toda."""
        bloco = self.page.locator(f'details:has(> summary:text-is("{resumo}"))')
        expect(bloco).to_have_count(1)
        if not bloco.evaluate("bloco => bloco.open"):
            bloco.locator("summary").click()
        self.assertTrue(bloco.evaluate("bloco => bloco.open"))

    def enviar(self, nome):
        with self.page.expect_navigation():
            self.page.get_by_role("button", name=nome, exact=True).click()

    def erro(self, nome, mensagem):
        with self.page.expect_response(lambda resposta: resposta.request.method == "POST") as resposta:
            self.page.get_by_role("button", name=nome, exact=True).click()
        self.assertEqual(resposta.value.status, 422)
        expect(self.page.locator("[data-erros-envio]")).to_contain_text(mensagem)

    def fotos(self, estado, botoes=False):
        p = self.page
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        for largura in (320, 390, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("() => document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            if botoes:
                for botao in p.locator("#trocas-pendentes button").all():
                    caixa = botao.bounding_box()
                    self.assertGreaterEqual(caixa["height"], 43.5)
                    self.assertGreaterEqual(caixa["width"], 43.5)
            if destino:
                pasta = Path(destino)
                pasta.mkdir(parents=True, exist_ok=True)
                p.evaluate("window.scrollTo(0, 0)")
                p.screenshot(path=str(pasta / f"escala-{estado}-{largura}.png"), full_page=True,
                             animations="disabled")
        p.set_viewport_size({"width": 390, "height": 844})

    def test_turno_de_duracao_zero_preserva_dados_e_permite_corrigir(self):
        p = self.page
        p.goto(self.url(reverse("escala:turnos")))
        self.abrir_formulario("Novo turno")
        p.get_by_label("Nome", exact=True).fill("Turno noturno de recepção")
        p.get_by_label("Setor", exact=True).select_option("recepcao")
        p.get_by_label("Início", exact=True).fill("22:00")
        p.get_by_label("Fim", exact=True).fill("22:00")
        self.erro("Salvar turno", "início e fim")
        expect(p.get_by_label("Nome", exact=True)).to_have_value("Turno noturno de recepção")
        expect(p.get_by_label("Setor", exact=True)).to_have_value("recepcao")
        expect(p.get_by_label("Início", exact=True)).to_have_value("22:00")
        expect(p.get_by_label("Fim", exact=True)).to_have_value("22:00")
        self.assertEqual(Turno.objects.count(), 1)
        p.get_by_label("Fim", exact=True).fill("06:00")
        self.enviar("Salvar turno")
        turno = Turno.objects.get(nome="Turno noturno de recepção")
        self.assertEqual((turno.inicio, turno.fim), (time(22), time(6)))
        expect(p.locator(".tabela tbody")).to_contain_text("22:00–06:00")
        self.fotos("turnos")

    def test_ausencia_bloqueia_escala_e_troca_aprovada_altera_so_a_atribuicao_escolhida(self):
        p = self.page
        func, substituto, controle = self.funcionarios
        observacao = "Ausência planejada para compromisso pessoal; registro fictício de conferência."
        p.goto(self.url(reverse("escala:ausencias")))
        self.abrir_formulario("Nova ausência")
        p.get_by_label("Funcionário", exact=True).select_option(str(func.pk))
        p.get_by_label("Tipo", exact=True).select_option("folga")
        p.get_by_label("Início", exact=True).fill(self.dia.isoformat())
        p.get_by_label("Fim", exact=True).fill((self.dia - timedelta(days=1)).isoformat())
        p.locator("#ausencia-observacao").fill(observacao)
        self.erro("Registrar ausência", "data final")
        expect(p.get_by_label("Funcionário", exact=True)).to_have_value(str(func.pk))
        expect(p.get_by_label("Início", exact=True)).to_have_value(self.dia.isoformat())
        expect(p.locator("#ausencia-observacao")).to_have_value(observacao)
        self.assertEqual(Ausencia.objects.count(), 0)
        p.get_by_label("Fim", exact=True).fill(self.dia.isoformat())
        self.enviar("Registrar ausência")
        self.assertEqual(Ausencia.objects.get().funcionario, func)
        self.fotos("ausencias")

        p.goto(self.url(reverse("escala:grade")) + f"?inicio={self.dia.isoformat()}")
        formulario = p.locator(".escala-escalar form")
        formulario.get_by_label("Funcionário", exact=True).select_option(str(func.pk))
        formulario.get_by_label("Turno", exact=True).select_option(str(self.turno.pk))
        formulario.locator('[name="data"]').fill(self.dia.isoformat())
        self.erro("Escalar", "está ausente")
        self.assertEqual(Atribuicao.objects.count(), 0)
        expect(formulario.get_by_label("Funcionário", exact=True)).to_have_value(str(func.pk))
        expect(formulario.get_by_label("Turno", exact=True)).to_have_value(str(self.turno.pk))
        dia_livre = self.dia + timedelta(days=1)
        formulario.locator('[name="data"]').fill(dia_livre.isoformat())
        self.enviar("Escalar")
        atribuicao = Atribuicao.objects.get()
        outra = services.atribuir(self.turno, controle, dia_livre, self.usuario)
        self.assertEqual(atribuicao.funcionario, func)

        p.get_by_role("navigation", name="Seções da Escala").get_by_role("link", name="Trocas", exact=True).click()
        expect(p.get_by_role("heading", name="Trocas de turno", exact=True)).to_be_visible()
        self.abrir_formulario("Solicitar troca")
        p.get_by_label("Turno a ceder", exact=True).select_option(str(atribuicao.pk))
        p.get_by_label("Substituto", exact=True).select_option(str(func.pk))
        motivo = "Substituição combinada entre os funcionários para conferência do fluxo."
        p.locator("#troca-motivo").fill(motivo)
        self.erro("Solicitar troca", "substituto diferente")
        expect(p.get_by_label("Turno a ceder", exact=True)).to_have_value(str(atribuicao.pk))
        expect(p.locator("#troca-motivo")).to_have_value(motivo)
        self.assertEqual(TrocaTurno.objects.count(), 0)
        p.get_by_label("Substituto", exact=True).select_option(str(substituto.pk))
        self.enviar("Solicitar troca")
        troca = TrocaTurno.objects.get()
        self.assertEqual(troca.status, TrocaTurno.Status.PENDENTE)
        self.fotos("troca-pendente", botoes=True)
        with p.expect_navigation():
            p.get_by_role("button", name="Aprovar troca de", exact=False).click()
        troca.refresh_from_db()
        atribuicao.refresh_from_db()
        outra.refresh_from_db()
        self.assertEqual(troca.status, TrocaTurno.Status.APROVADA)
        self.assertEqual(troca.decidido_por, self.usuario)
        self.assertEqual(atribuicao.funcionario, substituto)
        self.assertEqual((atribuicao.data, atribuicao.turno_id), (dia_livre, self.turno.pk))
        self.assertEqual(outra.funcionario, controle)
        self.assertEqual(Atribuicao.objects.count(), 2)
        expect(p.locator("#trocas-decididas")).to_contain_text("Aprovada")
        expect(p.locator("#trocas-pendentes")).to_contain_text("Nenhuma troca pendente")
        self.fotos("troca-aprovada")
