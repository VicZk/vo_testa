from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


class GovernancaBase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(
            username="governanta", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)


class FluxoLimpezaTests(GovernancaBase):
    def test_abrir_faxina_deixa_sujo(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")
        self.assertEqual(tarefa.status, "pendente")

    def test_nao_duplica_faxina_pendente(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        services.abrir_faxina(self.uh, usuario=self.user)
        self.assertEqual(TarefaGovernanca.objects.filter(uh=self.uh).count(), 1)

    def test_iniciar_e_concluir(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(tarefa, self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")
        services.concluir_tarefa(tarefa, self.user)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, "concluida")
        self.assertEqual(services.situacao_uh(self.uh).situacao, "limpa")
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="faxina_concluida").exists()
        )

    def test_inspecionar(self):
        services.inspecionar(self.uh, self.user)
        self.assertTrue(services.situacao_uh(self.uh).pronta)


class SinalCheckoutTests(GovernancaBase):
    def test_checkout_gera_faxina(self):
        from apps.reservas import services as rs
        from apps.reservas.models import Reserva

        hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=hospede, checkin=hoje,
            checkout=hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("100"), criado_por=self.user,
        )
        conta = r.fazer_checkin(self.user)
        SessaoCaixa.objects.create(
            operador=self.user, modulo="reservas", fundo_troco=Decimal("0")
        )
        rs.receber_pagamento(
            conta, self.user, FormaPagamento.objects.get(tipo="dinheiro"),
            conta.saldo(),
        )
        r.fazer_checkout(self.user)
        self.assertTrue(
            TarefaGovernanca.objects.filter(uh=self.uh, status="pendente").exists()
        )
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")

    def test_uh_pronta_para_checkin(self):
        self.assertTrue(services.uh_pronta_para_checkin(self.uh))
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self.assertFalse(services.uh_pronta_para_checkin(self.uh))
        services.definir_status(self.uh, StatusLimpeza.Situacao.INSPECIONADA, self.user)
        self.assertTrue(services.uh_pronta_para_checkin(self.uh))


class MapaIntegracaoTests(GovernancaBase):
    def test_mapa_reflete_limpeza(self):
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self.client.login(username="governanta", password="senha-forte-123")
        r = self.client.get(reverse("reservas:mapa_quartos"))
        self.assertContains(r, "A limpar")


class PermissaoTests(GovernancaBase):
    def test_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.client.login(username="governanta", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 404)


class TarefaIdempotenteTests(GovernancaBase):
    """Médio: concluir_tarefa duas vezes re-disparava o sinal e re-auditava."""

    def test_concluir_duas_vezes_nao_redispara(self):
        t = TarefaGovernanca.objects.create(
            uh=self.uh, tipo=TarefaGovernanca.Tipo.FAXINA,
            status=TarefaGovernanca.Status.PENDENTE)
        from apps.governanca.signals import faxina_concluida
        recebidos = []
        def _h(sender, **kw):
            recebidos.append(1)
        faxina_concluida.connect(_h)
        try:
            services.concluir_tarefa(t, self.user)
            services.concluir_tarefa(t, self.user)  # 2ª vez — idempotente
        finally:
            faxina_concluida.disconnect(_h)
        self.assertEqual(len(recebidos), 1)


class PainelSemEscritaTests(TestCase):
    """Abrir o painel não grava StatusLimpeza (antes: get_or_create por quarto)."""

    def test_painel_nao_cria_status_e_mostra_padrao(self):
        from decimal import Decimal

        from apps.nucleo.models import UH, TipoUH

        from .models import StatusLimpeza
        from .services import painel_limpeza

        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200.00"), capacidade=2)
        for n in range(3):
            UH.objects.create(numero=f"P{n}", tipo=tipo)
        StatusLimpeza.objects.all().delete()
        dados = painel_limpeza()
        self.assertEqual(StatusLimpeza.objects.count(), 0)
        self.assertEqual(len(dados["linhas"]), 3)
        self.assertTrue(all(ln["situacao"] == StatusLimpeza.Situacao.LIMPA for ln in dados["linhas"]))


class PainelHtmxTests(GovernancaBase):
    """O painel troca só o quadro (linha + contadores dos chips) sem recarregar,
    e continua funcionando sem JavaScript."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def test_acao_com_htmx_devolve_so_o_quadro(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        r = self.client.post(
            reverse("governanca:tarefa_acao", args=[tarefa.pk]),
            {"acao": "iniciar"},
            headers={"hx-request": "true"},
        )
        self.assertEqual(r.status_code, 200)
        corpo = r.content.decode()
        self.assertIn("tabela-limpeza", corpo)       # veio o quadro
        self.assertNotIn("<html", corpo)             # e só o quadro
        self.assertIn("Marcar limpo", corpo)         # já com a ação nova da linha
        self.assertIn("HX-Trigger", r.headers)       # aviso vira toast
        self.assertIn("iniciada", r.headers["HX-Trigger"])

    def test_acao_sem_htmx_redireciona_como_antes(self):
        """Sem JS (ou com o form puro), o fluxo antigo tem de continuar de pé."""
        services.abrir_faxina(self.uh, usuario=self.user)
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        r = self.client.post(
            reverse("governanca:tarefa_acao", args=[tarefa.pk]), {"acao": "iniciar"}
        )
        self.assertRedirects(r, reverse("governanca:painel"))
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")

    def test_atribuir_camareira_nao_dispara_sozinho(self):
        """O <select> não pode mais ter onchange=submit: quem confirma é o botão."""
        services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.get(reverse("governanca:painel"))
        corpo = r.content.decode()
        self.assertNotIn("this.form.submit()", corpo)
        self.assertIn('name="camareira"', corpo)

    def test_filtro_sem_quarto_explica_em_vez_de_tabela_vazia(self):
        r = self.client.get(reverse("governanca:painel"))
        # O único quarto está "limpa" por padrão; "a limpar" fica sem ninguém.
        self.assertContains(r, "Nenhum quarto")
