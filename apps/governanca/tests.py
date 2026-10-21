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
from .models import ConferenciaOcupacao, StatusLimpeza, TarefaGovernanca

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
    """A entrada do módulo (visão geral) e a lista seguem a mesma regra."""

    def test_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        for rota in ("governanca:painel", "governanca:quartos"):
            self.assertEqual(self.client.get(reverse(rota)).status_code, 403, rota)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.client.login(username="governanta", password="senha-forte-123")
        for rota in ("governanca:painel", "governanca:quartos"):
            self.assertEqual(self.client.get(reverse(rota)).status_code, 404, rota)


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
        # Já com o próximo passo da linha, no nome do que vai acontecer.
        self.assertIn("Terminei a limpeza", corpo)
        self.assertIn("HX-Trigger", r.headers)       # aviso vira toast
        self.assertIn("iniciada", r.headers["HX-Trigger"])

    def test_acao_sem_htmx_redireciona_como_antes(self):
        """Sem JS (ou com o form puro), o fluxo antigo tem de continuar de pé."""
        services.abrir_faxina(self.uh, usuario=self.user)
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        r = self.client.post(
            reverse("governanca:tarefa_acao", args=[tarefa.pk]), {"acao": "iniciar"}
        )
        self.assertRedirects(r, reverse("governanca:quartos"))
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")

    def test_atribuir_camareira_nao_dispara_sozinho(self):
        """O <select> não pode mais ter onchange=submit: quem confirma é o botão."""
        services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.get(reverse("governanca:quartos"))
        corpo = r.content.decode()
        self.assertNotIn("this.form.submit()", corpo)
        self.assertIn('name="camareira"', corpo)

    def test_filtro_sem_quarto_explica_em_vez_de_tabela_vazia(self):
        r = self.client.get(reverse("governanca:quartos"))
        # O único quarto está "limpa" por padrão; "a limpar" fica sem ninguém.
        self.assertContains(r, "Nenhum quarto")


class ArrumacaoDiariaTests(GovernancaBase):
    """De manhã, uma arrumação para cada quarto em que o hóspede continua."""

    def _hospedar(self, uh, sai_em_dias):
        from datetime import timedelta

        from django.utils import timezone

        from apps.nucleo.models import Pessoa
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=f"Hóspede {uh.numero}"),
            checkin=hoje - timedelta(days=1), checkout=hoje + timedelta(days=sai_em_dias),
            status=Reserva.Status.HOSPEDADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def test_gera_para_quem_fica_e_nao_para_quem_sai_hoje(self):
        fica = self.uh
        sai = UH.objects.create(numero="Quarto 02", tipo=self.tipo)
        self._hospedar(fica, sai_em_dias=2)
        self._hospedar(sai, sai_em_dias=0)
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 1)
        tarefa = TarefaGovernanca.objects.get()
        self.assertEqual((tarefa.uh, tarefa.tipo, tarefa.origem),
                         (fica, TarefaGovernanca.Tipo.ARRUMACAO, "arrumacao_diaria"))

    def test_rodar_de_novo_nao_duplica(self):
        self._hospedar(self.uh, sai_em_dias=3)
        services.gerar_arrumacoes_do_dia()
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 0)
        self.assertEqual(TarefaGovernanca.objects.count(), 1)

    def test_comando_da_rotina(self):
        from io import StringIO

        from django.core.management import call_command
        self._hospedar(self.uh, sai_em_dias=2)
        saida = StringIO()
        call_command("gerar_arrumacoes", stdout=saida)
        self.assertIn("1 arrumação", saida.getvalue())


class RondaBase(GovernancaBase):
    """Cenário da ronda: quartos físicos + um jeito curto de hospedar alguém."""

    def setUp(self):
        super().setUp()
        self.uh2 = UH.objects.create(numero="Quarto 02", tipo=self.tipo)
        self.hoje = timezone.localdate()

    def _hospedar(self, uh, *, sai_em_dias=2, nome="Hóspede"):
        from apps.reservas.models import Reserva
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=f"{nome} {uh.numero}"),
            checkin=self.hoje - timedelta(days=1),
            checkout=self.hoje + timedelta(days=sai_em_dias),
            status=Reserva.Status.HOSPEDADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def _achados(self, dia=None):
        return {a["uh"].pk: a for a in services.discrepancias(dia)["linhas"]}


class ConferenciaOcupacaoTests(RondaBase):
    """O registro da ronda: quem, quando, e histórico que não se sobrescreve."""

    def test_grava_quem_quando_e_o_que_viu(self):
        conf = services.registrar_conferencia(
            self.uh, ConferenciaOcupacao.Visto.VAGO, usuario=self.user)
        self.assertEqual((conf.uh, conf.visto, conf.registrado_por, conf.dia),
                         (self.uh, "vago", self.user, self.hoje))
        self.assertIsNotNone(conf.registrado_em)

    def test_segunda_conferencia_nao_sobrescreve_a_primeira(self):
        """A ronda da tarde não apaga a da manhã — e a tela mostra a mais recente."""
        primeira = services.registrar_conferencia(
            self.uh, ConferenciaOcupacao.Visto.OCUPADO, usuario=self.user)
        segunda = services.registrar_conferencia(
            self.uh, ConferenciaOcupacao.Visto.VAGO, usuario=self.user)
        self.assertEqual(ConferenciaOcupacao.objects.filter(uh=self.uh).count(), 2)
        primeira.refresh_from_db()
        self.assertEqual(primeira.visto, "ocupado")       # intacta
        self.assertEqual(services.conferencias_do_dia(self.hoje)[self.uh.pk].pk,
                         segunda.pk)

    def test_guarda_o_retrato_do_pms(self):
        """O veredito gravado é o do momento: amanhã a reserva não está mais
        hospedada e o relatório do mês continuaria certo."""
        r = self._hospedar(self.uh)
        conf = services.registrar_conferencia(
            self.uh, ConferenciaOcupacao.Visto.VAGO, usuario=self.user)
        self.assertTrue(conf.pms_ocupado)
        self.assertEqual(conf.reserva_id, r.pk)
        self.assertEqual(conf.divergencia, ConferenciaOcupacao.Divergencia.SKIP)

    def test_visto_invalido_recusado(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            services.registrar_conferencia(self.uh, "sei_la", usuario=self.user)

    def test_fica_na_trilha_de_auditoria_pelos_signals(self):
        """Nenhuma chamada explícita: o signal do núcleo audita qualquer escrita
        feita por um usuário real (aqui, pela view)."""
        self.client.login(username="governanta", password="senha-forte-123")
        self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                         {"visto": "vago"})
        trilha = TrilhaAuditoria.objects.filter(
            alvo="ConferenciaOcupacao", acao="criar").first()
        self.assertIsNotNone(trilha)
        self.assertEqual(trilha.usuario, self.user)


class DiscrepanciaTests(RondaBase):
    """Skip, sleeper e companhia — o cruzamento que ninguém fazia."""

    def test_skip_pms_ocupado_quarto_vago(self):
        self._hospedar(self.uh, sai_em_dias=2)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        achado = self._achados()[self.uh.pk]
        self.assertEqual(achado["tipo"], ConferenciaOcupacao.Divergencia.SKIP)
        self.assertEqual(achado["gravidade"], "alta")

    def test_saida_de_hoje_ainda_nao_lancada_nao_e_skip(self):
        """Hóspede que sai hoje e já foi embora: a recepção só não deu baixa. Pede
        ação (fechar a conta, liberar o quarto), mas não é hóspede fugindo."""
        self._hospedar(self.uh, sai_em_dias=0)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        achado = self._achados()[self.uh.pk]
        self.assertEqual(achado["tipo"],
                         ConferenciaOcupacao.Divergencia.SAIDA_NAO_LANCADA)
        self.assertEqual(achado["gravidade"], "media")

    def test_sleeper_pms_livre_quarto_com_gente(self):
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        achado = self._achados()[self.uh.pk]
        self.assertEqual(achado["tipo"], ConferenciaOcupacao.Divergencia.SLEEPER)
        self.assertEqual(achado["gravidade"], "alta")

    def test_sleeper_tambem_quando_viu_uso_sem_bagagem(self):
        services.registrar_conferencia(self.uh, "ocupado_sem_bagagem", usuario=self.user)
        self.assertEqual(self._achados()[self.uh.pk]["tipo"],
                         ConferenciaOcupacao.Divergencia.SLEEPER)

    def test_chegada_de_hoje_com_gente_dentro_e_sleeper_com_o_nome_do_hospede(self):
        """Check-in não lançado: o quarto tem hóspede e o PMS ainda o dá como livre."""
        from apps.reservas.models import Reserva
        Reserva.objects.create(
            uh=self.uh, hospede=Pessoa.objects.create(nome="Quem chegou"),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        achado = self._achados()[self.uh.pk]
        self.assertEqual(achado["tipo"], ConferenciaOcupacao.Divergencia.SLEEPER)
        self.assertIn("Quem chegou", achado["pms_diz"])

    def test_ocupado_confere_e_sai_da_lista(self):
        self._hospedar(self.uh)
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        d = services.discrepancias()
        self.assertNotIn(self.uh.pk, {a["uh"].pk for a in d["linhas"]})
        self.assertEqual(d["conferem"], 1)

    def test_sem_bagagem_no_meio_da_estadia_vira_aviso_leve(self):
        self._hospedar(self.uh, sai_em_dias=3)
        services.registrar_conferencia(self.uh, "ocupado_sem_bagagem", usuario=self.user)
        achado = self._achados()[self.uh.pk]
        self.assertEqual(achado["tipo"], ConferenciaOcupacao.Divergencia.SEM_BAGAGEM)
        self.assertEqual(achado["gravidade"], "baixa")

    def test_quarto_bloqueado_em_manutencao_nao_e_discrepancia(self):
        """Quarto em reparo tem técnico e material dentro — ver gente ali é normal."""
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        self.assertNotIn(self.uh.pk, self._achados())

    def test_bloqueio_por_datas_da_manutencao_tambem_isenta(self):
        """A Manutenção também bloqueia por período, sem mexer no status da UH."""
        from apps.manutencao.models import OrdemServico
        OrdemServico.objects.create(
            uh=self.uh, titulo="Troca do chuveiro", bloqueia_uh=True,
            bloqueio_inicio=self.hoje, bloqueio_fim=self.hoje,
            status=OrdemServico.Status.EM_ANDAMENTO, criado_por=self.user)
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        self.assertNotIn(self.uh.pk, self._achados())

    def test_nao_conferido_quando_nao_houve_ronda(self):
        d = services.discrepancias()
        achados = {a["uh"].pk: a for a in d["linhas"]}
        self.assertEqual(achados[self.uh.pk]["tipo"], "nao_conferido")
        self.assertEqual(achados[self.uh2.pk]["tipo"], "nao_conferido")
        self.assertEqual(d["resumo"]["nao_conferido"], 2)
        self.assertEqual(d["conferidos"], 0)
        # "Resolver" leva aonde a ronda se faz: a lista (a entrada virou a visão geral).
        self.assertEqual(achados[self.uh.pk]["url"], reverse("governanca:quartos"))

    def test_conferido_sai_do_nao_conferido(self):
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        d = services.discrepancias()
        self.assertEqual(d["resumo"]["nao_conferido"], 1)   # só o Quarto 02
        self.assertEqual(d["conferidos"], 1)

    def test_divergencia_resolvida_pela_recepcao_sai_da_tela(self):
        """A tela é de agora: feito o check-out, o skip de manhã não é mais problema
        (mas o registro da ronda continua no histórico, para o relatório)."""
        r = self._hospedar(self.uh, sai_em_dias=0)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        self.assertEqual(services.discrepancias()["divergencias"], 1)
        from apps.reservas.models import Reserva
        Reserva.objects.filter(pk=r.pk).update(status=Reserva.Status.CHECKOUT)
        self.assertEqual(services.discrepancias()["divergencias"], 0)
        self.assertEqual(
            ConferenciaOcupacao.objects.filter(
                divergencia=ConferenciaOcupacao.Divergencia.SAIDA_NAO_LANCADA).count(),
            1)

    def test_day_use_fica_fora_da_ronda(self):
        from apps.nucleo.models import TipoUH
        day = TipoUH.objects.create(nome="Dia na pousada", tarifa_base=Decimal("90"),
                                    modalidade=TipoUH.Modalidade.DAY_USE)
        UH.objects.create(numero="DAY-99", tipo=day)
        self.assertEqual(services.discrepancias()["quartos"], 2)   # Quarto 01 e 02

    def test_consultas_constantes(self):
        """24 quartos não podem virar 24 consultas: a tela faz o mesmo número de
        consultas com 2 quartos e com 10 (cada um com reserva e conferência)."""
        self._hospedar(self.uh)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        with self.assertNumQueries(8):
            services.discrepancias()
        for n in range(3, 11):
            uh = UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo)
            self._hospedar(uh)
            services.registrar_conferencia(uh, "vago", usuario=self.user)
        with self.assertNumQueries(8):
            services.discrepancias()


class DiscrepanciaSemReservasTests(RondaBase):
    """Sem o módulo Reservas não há base de comparação — e nada quebra."""

    def setUp(self):
        super().setUp()
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)

    def test_discrepancia_explica_em_vez_de_quebrar(self):
        conf = services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        self.assertIsNone(conf.pms_ocupado)
        self.assertEqual(conf.divergencia, ConferenciaOcupacao.Divergencia.SEM_BASE)
        d = services.discrepancias()
        self.assertTrue(d["sem_base"])
        self.assertEqual(d["linhas"], [])
        self.assertEqual(d["divergencias"], 0)

    def test_painel_e_tela_de_discrepancia_abrem(self):
        self.client.login(username="governanta", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("governanca:quartos")).status_code, 200)
        r = self.client.get(reverse("governanca:discrepancias"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "não há com o que comparar")

    def test_varredura_da_auditoria_nao_aponta_nada(self):
        services.registrar_conferencia(self.uh, "ocupado", usuario=self.user)
        self.assertEqual(services.pendencias_auditoria(), [])


class VarreduraAuditoriaTests(RondaBase):
    """A divergência do dia aparece na varredura de pendências da Auditoria."""

    def test_skip_entra_na_varredura(self):
        from apps.auditoria.services import varrer
        self._hospedar(self.uh, sai_em_dias=2)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        achados = [a for a in varrer() if a["area"] == "Governança"]
        skip = next(a for a in achados if a["tipo"] == "skip")
        self.assertEqual(skip["gravidade"], "alta")
        self.assertIn(self.uh.numero, skip["descricao"])
        self.assertTrue(skip["url"])

    def test_ronda_incompleta_agrega_numa_linha_e_so_conta_ocupados(self):
        """Antes da ronda nenhum quarto foi conferido: 24 linhas todas as manhãs
        viram ruído. Vai uma linha, e só pelos quartos com hóspede dentro."""
        self._hospedar(self.uh)
        achados = services.pendencias_auditoria()
        linhas = [a for a in achados if a["tipo"] == "ronda_incompleta"]
        self.assertEqual(len(linhas), 1)
        self.assertIn(self.uh.numero, linhas[0]["descricao"])
        self.assertNotIn(self.uh2.numero, linhas[0]["descricao"])  # quarto livre

    def test_quarto_livre_sem_ronda_nao_vira_pendencia(self):
        self.assertEqual(services.pendencias_auditoria(), [])


class RondaViewTests(RondaBase):
    """O toque da camareira: HTMX troca só o quadro e o aviso vem no cabeçalho."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def test_htmx_devolve_so_o_quadro(self):
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "vago"}, headers={"hx-request": "true"})
        self.assertEqual(r.status_code, 200)
        corpo = r.content.decode()
        self.assertIn("tabela-limpeza", corpo)
        self.assertNotIn("<html", corpo)
        self.assertIn("HX-Trigger", r.headers)

    def test_sem_htmx_redireciona(self):
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "ocupado"})
        self.assertRedirects(r, reverse("governanca:quartos"))
        self.assertEqual(ConferenciaOcupacao.objects.count(), 1)

    def test_divergencia_avisa_na_hora_e_nao_desaparece(self):
        """Skip é dinheiro na mesa: o toast fica até alguém fechar (tipo "error")."""
        self._hospedar(self.uh, sai_em_dias=2)
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "vago"}, headers={"hx-request": "true"})
        self.assertIn("error", r.headers["HX-Trigger"])
        self.assertIn("saiu sem baixa", r.headers["HX-Trigger"].lower())
        self.assertIn("aviso-divergencia", r.content.decode())

    def test_achado_leve_avisa_sem_alarmar(self):
        """"Ocupado sem bagagem" é observação, não emergência: o bloco não vai em
        vermelho (o dono já reclamou de tela que grita por tudo)."""
        self._hospedar(self.uh, sai_em_dias=3)
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "ocupado_sem_bagagem"},
                             headers={"hx-request": "true"})
        self.assertIn("aviso-divergencia leve", r.content.decode())
        self.assertIn("warning", r.headers["HX-Trigger"])

    def test_achado_grave_pinta_o_aviso_de_vermelho(self):
        self._hospedar(self.uh, sai_em_dias=3)
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "vago"}, headers={"hx-request": "true"})
        corpo = r.content.decode()
        self.assertIn("aviso-divergencia", corpo)
        self.assertNotIn("aviso-divergencia leve", corpo)

    def test_visto_invalido_nao_grava_nem_quebra(self):
        r = self.client.post(reverse("governanca:ronda", args=[self.uh.pk]),
                             {"visto": "qualquer"}, headers={"hx-request": "true"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ConferenciaOcupacao.objects.count(), 0)

    def test_get_nao_grava(self):
        r = self.client.get(reverse("governanca:ronda", args=[self.uh.pk]))
        self.assertRedirects(r, reverse("governanca:quartos"))
        self.assertEqual(ConferenciaOcupacao.objects.count(), 0)

    def test_painel_mostra_os_tres_botoes_da_ronda(self):
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        for rotulo in ("Vago", "Com mala", "Sem mala"):
            self.assertIn(rotulo, corpo)

    def test_tela_de_discrepancias_lista_o_achado_com_o_que_fazer(self):
        self._hospedar(self.uh, sai_em_dias=2)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        r = self.client.get(reverse("governanca:discrepancias"))
        self.assertContains(r, "Saiu sem baixa")
        self.assertContains(r, "lançar a saída")
        self.assertContains(r, self.uh.numero)

    def test_discrepancias_exige_o_modulo(self):
        Usuario.objects.create_user(username="sem2", password="senha-forte-123")
        self.client.logout()
        self.client.login(username="sem2", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("governanca:discrepancias")).status_code, 403)

    def test_discrepancias_404_com_modulo_inativo(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.assertEqual(
            self.client.get(reverse("governanca:discrepancias")).status_code, 404)


class InspecaoTests(GovernancaBase):
    """Inspeção carimba a faxina entregue; reprovar devolve o quarto para a fila."""

    def _faxina_entregue(self, camareira=None):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        tarefa.camareira = camareira or self.user
        tarefa.save(update_fields=["camareira"])
        services.iniciar_tarefa(tarefa, self.user)
        services.concluir_tarefa(tarefa, self.user)
        tarefa.refresh_from_db()
        return tarefa

    def test_inspecionar_carimba_a_faxina(self):
        tarefa = self._faxina_entregue()
        services.inspecionar(self.uh, self.user)
        tarefa.refresh_from_db()
        self.assertIsNotNone(tarefa.inspecionada_em)
        self.assertEqual(tarefa.inspecionada_por, self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "inspecionada")

    def test_inspecionar_duas_vezes_nao_conta_duas(self):
        tarefa = self._faxina_entregue()
        services.inspecionar(self.uh, self.user)
        primeiro = TarefaGovernanca.objects.get(pk=tarefa.pk).inspecionada_em
        services.inspecionar(self.uh, self.user)
        self.assertEqual(TarefaGovernanca.objects.get(pk=tarefa.pk).inspecionada_em,
                         primeiro)

    def test_reprovar_devolve_para_a_fila_com_motivo(self):
        tarefa = self._faxina_entregue()
        nova = services.reprovar_inspecao(self.uh, self.user, "Banheiro")
        tarefa.refresh_from_db()
        self.assertIsNotNone(tarefa.reprovada_em)
        self.assertEqual(tarefa.motivo_reprovacao, "Banheiro")
        self.assertEqual((nova.status, nova.origem), ("pendente", "reprovada"))
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="inspecao_reprovada").exists())

    def test_quarto_sem_faxina_ainda_pode_ser_inspecionado(self):
        services.inspecionar(self.uh, self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "inspecionada")

    def test_quarto_limpo_oferece_aprovar_e_devolver(self):
        """Quarto limpo tem UMA ação principal ("Aprovar limpeza") e uma saída
        secundária ("Devolver para limpar"), que leva ao formulário do motivo."""
        self._faxina_entregue()
        self.client.login(username="governanta", password="senha-forte-123")
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("Aprovar limpeza", corpo)
        self.assertIn("Devolver para limpar", corpo)
        self.assertIn(reverse("governanca:devolver", args=[self.uh.pk]), corpo)

    def test_reprovar_pela_view(self):
        self._faxina_entregue()
        self.client.login(username="governanta", password="senha-forte-123")
        r = self.client.post(reverse("governanca:status_marcar", args=[self.uh.pk]),
                             {"situacao": "reprovada", "motivo": "Pó no armário"},
                             headers={"hx-request": "true"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            TarefaGovernanca.objects.filter(origem="reprovada").count(), 1)


class RelatoriosGovernancaTests(RondaBase):
    """Os números que a gerência olha no fim do mês."""

    def setUp(self):
        super().setUp()
        self.maria = Usuario.objects.create_user(
            username="maria", password="senha-forte-123", first_name="Maria")
        self.periodo = (self.hoje - timedelta(days=7), self.hoje)

    def _faxina(self, uh, camareira, *, minutos=30,
                tipo=TarefaGovernanca.Tipo.FAXINA):
        agora = timezone.now()
        return TarefaGovernanca.objects.create(
            uh=uh, tipo=tipo, camareira=camareira,
            status=TarefaGovernanca.Status.CONCLUIDA,
            iniciada_em=agora - timedelta(minutes=minutos), concluida_em=agora)

    def test_faxinas_por_camareira_com_tipo_e_tempo_medio(self):
        self._faxina(self.uh, self.maria, minutos=20)
        self._faxina(self.uh2, self.maria, minutos=40,
                     tipo=TarefaGovernanca.Tipo.ARRUMACAO)
        self._faxina(self.uh, self.user, minutos=60)
        rel = services.relatorio_faxinas(*self.periodo)
        self.assertEqual(rel["total"], 3)
        self.assertEqual(rel["minutos_medios"], 40)        # (20+40+60)/3
        linha = next(ln for ln in rel["linhas"] if ln["camareira"] == "Maria")
        self.assertEqual(linha["n"], 2)
        self.assertEqual(linha["minutos"], 30)             # (20+40)/2
        self.assertEqual(linha["tipos"][TarefaGovernanca.Tipo.ARRUMACAO], 1)

    def test_faxina_sem_horario_conta_mas_fica_fora_da_media(self):
        TarefaGovernanca.objects.create(
            uh=self.uh, camareira=self.maria,
            status=TarefaGovernanca.Status.CONCLUIDA, concluida_em=timezone.now())
        rel = services.relatorio_faxinas(*self.periodo)
        self.assertEqual(rel["total"], 1)
        self.assertEqual(rel["cronometradas"], 0)
        self.assertIsNone(rel["minutos_medios"])

    def test_faxina_fora_do_periodo_nao_entra(self):
        antiga = self._faxina(self.uh, self.maria)
        TarefaGovernanca.objects.filter(pk=antiga.pk).update(
            concluida_em=timezone.now() - timedelta(days=40))
        self.assertEqual(services.relatorio_faxinas(*self.periodo)["total"], 0)

    def test_inspecoes_contam_aprovadas_reprovadas_e_retrabalho(self):
        aprovada = self._faxina(self.uh, self.maria)
        reprovada = self._faxina(self.uh2, self.maria)
        TarefaGovernanca.objects.filter(pk=aprovada.pk).update(
            inspecionada_em=timezone.now(), inspecionada_por=self.user)
        TarefaGovernanca.objects.filter(pk=reprovada.pk).update(
            reprovada_em=timezone.now(), motivo_reprovacao="Banheiro")
        rel = services.relatorio_inspecoes(*self.periodo)
        self.assertEqual((rel["inspecionadas"], rel["reprovadas"]), (1, 1))
        self.assertEqual(rel["retrabalho"], 50.0)
        self.assertEqual(rel["motivos"], [("Banheiro", 1)])
        self.assertEqual(rel["linhas"][0]["camareira"], "Maria")

    def test_discrepancias_por_dia_usam_o_veredito_gravado(self):
        self._hospedar(self.uh, sai_em_dias=2)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        services.registrar_conferencia(self.uh2, "ocupado", usuario=self.user)
        rel = services.relatorio_discrepancias(*self.periodo)
        self.assertEqual(rel["conferencias"], 2)
        self.assertEqual(rel["divergencias"], 2)
        self.assertEqual(rel["dias_com_divergencia"], 1)
        self.assertEqual(rel["por_tipo"][ConferenciaOcupacao.Divergencia.SKIP], 1)
        self.assertEqual(rel["por_tipo"][ConferenciaOcupacao.Divergencia.SLEEPER], 1)
        self.assertEqual(rel["linhas"][0]["dia"], self.hoje)

    def test_historico_nao_muda_quando_a_reserva_muda_de_estado(self):
        """O relatório conta o que foi ENCONTRADO na ronda; a reserva segue a vida."""
        r = self._hospedar(self.uh, sai_em_dias=2)
        services.registrar_conferencia(self.uh, "vago", usuario=self.user)
        from apps.reservas.models import Reserva
        Reserva.objects.filter(pk=r.pk).update(status=Reserva.Status.CHECKOUT)
        rel = services.relatorio_discrepancias(*self.periodo)
        self.assertEqual(rel["por_tipo"][ConferenciaOcupacao.Divergencia.SKIP], 1)


class FluxoDidaticoTests(GovernancaBase):
    """A tela tem de se explicar sozinha para quem nunca trabalhou em hotel: o
    ciclo à vista, UMA ação principal por quarto com o nome do que acontece, e uma
    frase dizendo por que o quarto está naquele estado."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def _painel(self):
        return self.client.get(reverse("governanca:quartos")).content.decode()

    def test_o_ciclo_aparece_na_tela_na_ordem_certa(self):
        corpo = self._painel()
        posicoes = [corpo.index(e["rotulo"]) for e in services.CICLO]
        self.assertEqual(posicoes, sorted(posicoes), "o ciclo saiu fora de ordem")
        self.assertIn("Como funciona a limpeza dos quartos", corpo)

    def test_glossario_explica_os_termos_de_hotelaria(self):
        corpo = self._painel()
        for termo in ("Ronda", "Inspeção", "Faxina completa", "Skip", "Sleeper"):
            self.assertIn(termo, corpo, termo)

    def test_quarto_sujo_tem_uma_acao_e_ela_diz_o_que_acontece(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        corpo = self._painel()
        self.assertIn("Começar limpeza", corpo)
        self.assertNotIn("Iniciar limpeza", corpo)     # jargão antigo saiu
        self.assertEqual(corpo.count("botao-primario"), 1)   # uma só ação principal

    def test_quarto_em_limpeza_pede_terminei(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(tarefa, self.user)
        corpo = self._painel()
        self.assertIn("Terminei a limpeza", corpo)
        self.assertNotIn("Marcar limpo", corpo)

    def test_quarto_pronto_nao_tem_acao_principal(self):
        services.inspecionar(self.uh, self.user)
        corpo = self._painel()
        self.assertIn("Nada a fazer", corpo)
        self.assertIn("Pedir nova limpeza", corpo)
        self.assertNotIn("botao-primario", corpo)

    def test_cada_estado_vem_com_a_frase_que_o_explica(self):
        services.abrir_faxina(self.uh, usuario=self.user, origem="checkout")
        self.assertIn("O hóspede fez check-out.", self._painel())
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        services.iniciar_tarefa(tarefa, self.user)
        self.assertIn("começou às", self._painel())
        services.concluir_tarefa(tarefa, self.user)
        self.assertIn("Falta a supervisora conferir.", self._painel())
        services.inspecionar(self.uh, self.user)
        self.assertIn("Pode receber hóspede.", self._painel())

    def test_arrumacao_do_dia_se_explica_diferente_do_checkout(self):
        services.abrir_faxina(self.uh, usuario=self.user, origem="arrumacao_diaria")
        self.assertIn("O hóspede continua no quarto", self._painel())

    def test_estado_usa_a_palavra_simples_e_nao_o_termo_do_model(self):
        """O model diz "Inspecionado"; a tela diz "Pronto" (o termo de hotelaria
        fica explicado no «Como funciona»)."""
        services.inspecionar(self.uh, self.user)
        dados = services.painel_limpeza()
        linha = next(ln for ln in dados["linhas"] if ln["uh"] == self.uh)
        self.assertEqual(linha["situacao_label"], "Pronto")


class ComecarLimpezaNumToqueTests(GovernancaBase):
    """Quarto sujo sem faxina na fila: abrir e começar era dois botões seguidos —
    o passo que mais confundia quem pegava o sistema pela primeira vez."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)

    def test_um_toque_abre_a_faxina_e_ja_comeca(self):
        r = self.client.post(reverse("governanca:nova_tarefa"),
                             {"uh": self.uh.pk, "tipo": "faxina_completa", "iniciar": "1"},
                             headers={"hx-request": "true"})
        self.assertEqual(r.status_code, 200)
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.EM_ANDAMENTO)
        self.assertIsNotNone(tarefa.iniciada_em)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")

    def test_sem_a_marca_iniciar_so_entra_na_fila(self):
        """O caminho antigo continua valendo (o POST não mudou)."""
        self.client.post(reverse("governanca:nova_tarefa"),
                         {"uh": self.uh.pk, "tipo": "faxina_completa"})
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.PENDENTE)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "suja")

    def test_toque_duplo_nao_devolve_o_quarto_para_a_limpar(self):
        """O segundo POST achava a faxina já em andamento, mas antes marcava o quarto
        como sujo: ficava «A limpar» com alguém limpando, e o botão da linha
        («Começar limpeza» → iniciar) não o tirava mais de lá."""
        for _ in range(2):
            self.client.post(reverse("governanca:nova_tarefa"),
                             {"uh": self.uh.pk, "tipo": "faxina_completa", "iniciar": "1"},
                             headers={"hx-request": "true"})
        self.assertEqual(TarefaGovernanca.objects.filter(uh=self.uh).count(), 1)
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")

    def test_quarto_preso_em_a_limpar_se_acerta_no_botao_da_linha(self):
        """Quem já ficou preso (faxina em andamento, quarto «A limpar») sai pelo
        próprio botão principal da linha."""
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(tarefa, self.user)
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                         {"acao": "iniciar"}, headers={"hx-request": "true"})
        self.assertEqual(services.situacao_uh(self.uh).situacao, "em_limpeza")


class DevolverParaLimparTests(GovernancaBase):
    """A reprovação virou um formulário próprio (modal da casa), e o motivo chega
    até quem vai limpar de novo."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(tarefa, self.user)
        services.concluir_tarefa(tarefa, self.user)

    def test_htmx_devolve_so_o_modal(self):
        r = self.client.get(reverse("governanca:devolver", args=[self.uh.pk]),
                            headers={"hx-request": "true"})
        corpo = r.content.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("modal-form", corpo)
        self.assertNotIn("<html", corpo)
        self.assertIn(reverse("governanca:status_marcar", args=[self.uh.pk]), corpo)

    def test_sem_javascript_abre_como_pagina(self):
        r = self.client.get(reverse("governanca:devolver", args=[self.uh.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<html")
        self.assertContains(r, "Devolver o")

    def test_motivo_chega_na_faxina_nova(self):
        self.client.post(reverse("governanca:status_marcar", args=[self.uh.pk]),
                         {"situacao": "reprovada", "motivo": "Banheiro"})
        nova = TarefaGovernanca.objects.get(origem="reprovada")
        self.assertEqual(nova.observacoes, "Banheiro")
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("Devolvido para limpar: Banheiro", corpo)

    def test_exige_o_modulo(self):
        Usuario.objects.create_user(username="sem3", password="senha-forte-123")
        self.client.logout()
        self.client.login(username="sem3", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("governanca:devolver", args=[self.uh.pk])).status_code,
            403)


class FilaDaCamareiraTests(GovernancaBase):
    """No corredor, a camareira quer a fila DELA — não o andar inteiro."""

    def setUp(self):
        super().setUp()
        self.maria = Usuario.objects.create_user(
            username="maria", password="senha-forte-123", first_name="Maria")
        self.maria.modulos.set(
            ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA))
        self.uh2 = UH.objects.create(numero="Quarto 02", tipo=self.tipo)

    def test_chip_so_aparece_para_quem_tem_quarto_na_fila(self):
        """O filtro é "chip-meus"; o texto "Só os meus" também aparece no «Como
        funciona», então a asserção olha o controle, não a palavra."""
        self.client.login(username="maria", password="senha-forte-123")
        self.assertNotIn("chip-meus",
                         self.client.get(reverse("governanca:quartos")).content.decode())
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        tarefa.camareira = self.maria
        tarefa.save(update_fields=["camareira"])
        self.assertIn("chip-meus",
                      self.client.get(reverse("governanca:quartos")).content.decode())

    def test_so_os_quartos_dela_sao_marcados_como_dela(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        tarefa.camareira = self.maria
        tarefa.save(update_fields=["camareira"])
        services.abrir_faxina(self.uh2, usuario=self.user)   # de ninguém
        from apps.governanca.views import _contexto_quadro
        ctx = _contexto_quadro(self.maria)
        minhas = {ln["uh"].numero: ln["minha"] for ln in ctx["linhas"]}
        self.assertTrue(minhas["Quarto 01"])
        self.assertFalse(minhas["Quarto 02"])
        self.assertEqual(ctx["meus"], 1)

    def test_a_fila_aparece_na_frase_do_quarto(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        tarefa.camareira = self.maria
        tarefa.save(update_fields=["camareira"])
        self.client.login(username="governanta", password="senha-forte-123")
        self.assertIn("Na fila de Maria.",
                      self.client.get(reverse("governanca:quartos")).content.decode())


class VisaoGeralTests(GovernancaBase):
    """A entrada da Governança é gráfica: a casa em blocos, o progresso do dia e o
    que pede ação — tudo clicável para o lugar certo."""

    def setUp(self):
        super().setUp()
        self.uh2 = UH.objects.create(numero="Quarto 02", tipo=self.tipo)
        self.uh3 = UH.objects.create(numero="Quarto 03", tipo=self.tipo)
        self.client.login(username="governanta", password="senha-forte-123")

    def test_entrada_do_modulo_e_a_visao_geral(self):
        r = self.client.get(reverse("governanca:painel"))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "governanca/visao.html")
        self.assertContains(r, "Como está a casa")
        self.assertContains(r, "corredor-gov")       # a casa em blocos

    def test_uma_porta_por_quarto_levando_para_a_linha_dele(self):
        dados = services.visao_geral()
        self.assertEqual(len(dados["portas"]), 3)
        corpo = self.client.get(reverse("governanca:painel")).content.decode()
        self.assertIn(f"#quarto-{self.uh.pk}", corpo)

    def test_progresso_do_dia_conta_os_prontos(self):
        services.inspecionar(self.uh, self.user)
        dados = services.visao_geral()
        self.assertEqual((dados["prontos"], dados["total"]), (1, 3))
        self.assertEqual(dados["falta_para_pronto"], 2)
        self.assertContains(self.client.get(reverse("governanca:painel")), "de 3 prontos")

    def test_a_porta_ganha_a_cor_do_estado(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        services.inspecionar(self.uh2, self.user)
        cores = {p["uh"].numero: p["cor"] for p in services.visao_geral()["portas"]}
        self.assertEqual(cores["Quarto 01"], "limp-suja")
        self.assertEqual(cores["Quarto 02"], "limp-inspecionada")   # pronto
        self.assertEqual(cores["Quarto 03"], "limp-limpa")          # falta inspeção

    def test_quarto_bloqueado_aparece_como_manutencao(self):
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        porta = next(p for p in services.visao_geral()["portas"] if p["uh"] == self.uh)
        self.assertEqual(porta["cor"], "limp-bloqueada")
        self.assertTrue(porta["bloqueado"])

    def test_atencao_aponta_inspecao_esperando_e_leva_a_lista_filtrada(self):
        dados = services.visao_geral()
        item = next(a for a in dados["atencao"] if "esperando inspeção" in a["rotulo"])
        self.assertEqual(item["nivel"], "aviso")
        self.assertIn(reverse("governanca:quartos"), item["url"])
        self.assertIn("estado=limpa", item["url"])

    def test_atencao_cobra_camareira_para_o_que_esta_sujo(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        achados = {a["rotulo"] for a in services.visao_geral()["atencao"]}
        self.assertTrue(any("sem camareira" in a for a in achados), achados)

    def test_sem_nada_pendente_a_tela_diz_isso(self):
        for uh in (self.uh, self.uh2, self.uh3):
            services.inspecionar(uh, self.user)
            services.registrar_conferencia(uh, "vago", usuario=self.user)
        dados = services.visao_geral()
        self.assertEqual(dados["atencao"], [])
        self.assertContains(self.client.get(reverse("governanca:painel")),
                            "Nada pendente na governança agora")

    def test_carga_por_camareira_soma_fila_andamento_e_entregue(self):
        maria = Usuario.objects.create_user(
            username="maria2", password="senha-forte-123", first_name="Maria")
        t1 = services.abrir_faxina(self.uh, usuario=self.user)
        t1.camareira = maria
        t1.save(update_fields=["camareira"])
        t2 = services.abrir_faxina(self.uh2, usuario=self.user)
        t2.camareira = maria
        t2.save(update_fields=["camareira"])
        services.iniciar_tarefa(t2, maria)
        t3 = services.abrir_faxina(self.uh3, usuario=self.user)
        t3.camareira = maria
        t3.save(update_fields=["camareira"])
        services.iniciar_tarefa(t3, maria)
        services.concluir_tarefa(t3, maria)
        carga = {c["nome"]: c for c in services.carga_das_camareiras()}
        self.assertEqual(
            (carga["Maria"]["pendentes"], carga["Maria"]["fazendo"], carga["Maria"]["feitas"]),
            (1, 1, 1))
        self.assertEqual(carga["Maria"]["na_mao"], 2)
        self.assertEqual(carga["Maria"]["barra_pendentes"], 33)   # 1 de 3

    def test_faxina_sem_camareira_aparece_como_sem_camareira(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        nomes = [c["nome"] for c in services.carga_das_camareiras()]
        self.assertIn("Sem camareira", nomes)

    def test_consultas_constantes(self):
        """A visão geral não pode virar uma consulta por quarto."""
        services.abrir_faxina(self.uh, usuario=self.user)
        services.visao_geral()   # aquece o singleton de configuração (ele nasce aqui)
        with self.assertNumQueries(12):
            services.visao_geral()
        for n in range(4, 12):
            UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo)
        with self.assertNumQueries(12):   # 3 quartos ou 11: o mesmo número
            services.visao_geral()

class VisaoGeralComReservasTests(RondaBase):
    """As chegadas de hoje são o prazo real da governança."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def _chegada_hoje(self, uh, nome="Quem chega"):
        from apps.reservas.models import Reserva
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=nome),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def test_chegada_com_quarto_sujo_vira_o_alerta_mais_grave(self):
        self._chegada_hoje(self.uh)
        services.abrir_faxina(self.uh, usuario=self.user)
        dados = services.visao_geral()
        self.assertEqual(dados["chegadas_atrasadas"], 1)
        item = dados["atencao"][0]
        self.assertEqual(item["nivel"], "alerta")     # o mais grave da tela
        self.assertIn("sem quarto pronto", item["rotulo"])

    def test_chegada_com_quarto_pronto_nao_alarma(self):
        self._chegada_hoje(self.uh)
        services.inspecionar(self.uh, self.user)
        dados = services.visao_geral()
        self.assertEqual(dados["chegadas_atrasadas"], 0)
        self.assertFalse(any("sem quarto pronto" in a["rotulo"] for a in dados["atencao"]))
        self.assertEqual(dados["chegadas"][0]["hospede"], "Quem chega")

    def test_a_tela_mostra_o_horario_de_entrada_do_hospede(self):
        self.assertContains(self.client.get(reverse("governanca:painel")),
                            "o primeiro hóspede pode entrar")

    def test_o_bloco_de_chegadas_lista_quarto_e_hospede(self):
        self._chegada_hoje(self.uh, nome="Ana Chegando")
        r = self.client.get(reverse("governanca:painel"))
        self.assertContains(r, "gov-chegadas")
        self.assertContains(r, "Ana Chegando")
        self.assertContains(r, self.uh.numero)

    def test_sem_reservas_a_visao_nao_quebra(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        dados = services.visao_geral()
        self.assertTrue(dados["sem_base"])
        self.assertEqual(dados["chegadas"], [])
        self.assertIsNone(dados["hora_checkin"])
        r = self.client.get(reverse("governanca:painel"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "não há como saber quem chega hoje")


class ListaFiltradaPelaVisaoTests(GovernancaBase):
    """Clicar em "3 esperando inspeção" abre a lista nesses três."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def test_estado_da_url_vira_o_filtro_inicial(self):
        r = self.client.get(reverse("governanca:quartos"), {"estado": "limpa"})
        self.assertEqual(r.context["filtro_inicial"], "limpa")
        self.assertContains(r, "'limpa' || (function ()")

    def test_estado_invalido_e_ignorado(self):
        r = self.client.get(reverse("governanca:quartos"), {"estado": "sei_la"})
        self.assertEqual(r.context["filtro_inicial"], "")

    def test_cada_linha_tem_ancora_para_a_porta_da_visao(self):
        self.assertContains(self.client.get(reverse("governanca:quartos")),
                            f'id="quarto-{self.uh.pk}"')
