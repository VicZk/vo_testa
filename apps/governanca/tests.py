import json
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
        self.assertTrue(all(ln["situacao"] == StatusLimpeza.Situacao.INSPECIONADA
                            for ln in dados["linhas"]))


class BancoNovoTests(TestCase):
    """Casa que acabou de entrar no sistema não tem fila de inspeção inventada.

    O padrão era "Limpo", que na nossa tela significa "limpeza feita, falta a
    supervisora conferir": num banco novo os 24 quartos entravam na fila da
    supervisora e a visão geral dizia "Faltam 23 quartos" sem ninguém ter sujado
    nada. Quarto sem registro de limpeza = disponível.
    """

    def setUp(self):
        self.user = Usuario.objects.create_superuser(
            username="nova", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        for n in range(1, 25):
            UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo)
        StatusLimpeza.objects.all().delete()   # é o que um banco novo tem: nada

    def test_casa_inteira_pronta_sem_nenhum_registro(self):
        dados = services.visao_geral()
        self.assertEqual(dados["total"], 24)
        self.assertEqual(dados["prontos"], 24)
        self.assertEqual(dados["falta_para_pronto"], 0)
        self.assertEqual(StatusLimpeza.objects.count(), 0)   # a tela não escreve

    def test_casa_vazia_nao_cobra_ronda_de_quarto_nenhum(self):
        """A ronda procura hóspede sem check-in e saída sem baixa: sem ninguém em
        casa não há nada para conferir (antes: "24 quartos sem ronda hoje")."""
        dados = services.visao_geral()
        self.assertEqual(dados["atencao"], [])
        self.assertEqual(dados["contagem"][StatusLimpeza.Situacao.LIMPA], 0)

    def test_a_tela_nao_finge_que_a_supervisora_conferiu(self):
        """"Pronto" sem ninguém no `atualizado_por` não vira carimbo de inspeção."""
        linha = services.painel_limpeza()["linhas"][0]
        self.assertEqual(linha["situacao_label"], "Pronto")
        self.assertIn("Sem faxina registrada ainda", linha["explicacao"])
        self.assertNotIn("Conferido", linha["explicacao"])

    def test_inspecao_de_verdade_diz_que_foi_conferida(self):
        uh = UH.objects.get(numero="Quarto 01")
        services.inspecionar(uh, self.user)
        linha = next(ln for ln in services.painel_limpeza()["linhas"]
                     if ln["uh"].pk == uh.pk)
        self.assertIn("Conferido e aprovado", linha["explicacao"])

    def test_checkout_tira_o_quarto_do_pronto(self):
        services.abrir_faxina(UH.objects.get(numero="Quarto 01"), usuario=self.user)
        dados = services.visao_geral()
        self.assertEqual(dados["prontos"], 23)
        self.assertEqual(dados["falta_para_pronto"], 1)


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
        self.assertContains(r, "não é possível comparar a ronda com as reservas")

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
        self.assertIn("Pronto para receber o hóspede", corpo)
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
        self.assertIn("Arrumação do dia, com o hóspede ainda no quarto.", self._painel())

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
        from django.test import RequestFactory

        from apps.governanca.views import _contexto_quadro

        # O contexto lê a sessão (a oferta de "Desfazer" do último gesto).
        pedido = RequestFactory().get(reverse("governanca:quartos"))
        pedido.session = self.client.session
        ctx = _contexto_quadro(pedido, self.maria)
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

    def test_uma_porta_por_quarto_abrindo_a_ficha_dele(self):
        """A porta resolve o quarto ali: no tablet, mandar "ir até a linha" era
        sair da parede de blocos e caçar numa lista de 24."""
        dados = services.visao_geral()
        self.assertEqual(len(dados["portas"]), 3)
        corpo = self.client.get(reverse("governanca:painel")).content.decode()
        ficha = reverse("governanca:quarto", args=[self.uh.pk])
        self.assertIn(f'href="{ficha}?voltar=painel"', corpo)
        self.assertIn(f'hx-get="{ficha}?voltar=painel"', corpo)

    def test_progresso_do_dia_conta_os_prontos(self):
        services.inspecionar(self.uh, self.user)
        for uh in (self.uh2, self.uh3):
            services.abrir_faxina(uh, usuario=self.user)
        dados = services.visao_geral()
        self.assertEqual((dados["prontos"], dados["total"]), (1, 3))
        self.assertEqual(dados["falta_para_pronto"], 2)
        self.assertContains(self.client.get(reverse("governanca:painel")), "de 3 prontos")

    def test_a_porta_ganha_a_cor_do_estado(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        services.inspecionar(self.uh2, self.user)
        services.definir_status(self.uh3, StatusLimpeza.Situacao.LIMPA, self.user)
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
        services.definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.user)
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
        """O prazo do dia aparece com a casa pronta e com a casa atrasada."""
        self.assertContains(self.client.get(reverse("governanca:painel")),
                            "O primeiro hóspede pode entrar")
        services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.get(reverse("governanca:painel"))
        self.assertContains(r, "O primeiro hóspede pode entrar")
        self.assertContains(r, "para a casa toda ficar pronta")

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
        self.assertContains(r, "não há como saber quem chega e quem sai hoje")


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


class OcupacaoNoQuadroTests(RondaBase):
    """Ocupação × limpeza: a tela diz COMO está o quarto e QUEM está dentro.

    Antes falava só de limpeza, e a supervisora abria o mapa de reservas ao lado
    para saber se podia mandar alguém entrar. "Vago sujo" é faxina de saída;
    "ocupado sujo" é arrumação com as coisas do hóspede dentro.
    """

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def _linha(self, uh, dia=None):
        return next(ln for ln in services.painel_limpeza(dia)["linhas"]
                    if ln["uh"].pk == uh.pk)

    def _chegada_hoje(self, uh, nome="Quem chega"):
        from apps.reservas.models import Reserva
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=nome),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def test_quarto_sem_ninguem_e_vago(self):
        self.assertEqual(self._linha(self.uh)["ocupacao"]["cod"], "vago")

    def test_hospede_que_continua_e_ocupado_com_o_nome(self):
        self._hospedar(self.uh, sai_em_dias=3, nome="Ana")
        ocup = self._linha(self.uh)["ocupacao"]
        self.assertEqual((ocup["cod"], ocup["rotulo"]), ("ocupado", "Ocupado"))
        self.assertIn("Ana", ocup["hospede"])

    def test_hospede_que_vai_embora_hoje_e_sai_hoje(self):
        self._hospedar(self.uh, sai_em_dias=0)
        ocup = self._linha(self.uh)["ocupacao"]
        self.assertEqual((ocup["cod"], ocup["rotulo"]), ("sai_hoje", "Sai hoje"))

    def test_quem_chega_hoje_e_chega_hoje(self):
        self._chegada_hoje(self.uh)
        ocup = self._linha(self.uh)["ocupacao"]
        self.assertEqual((ocup["cod"], ocup["rotulo"]), ("chega_hoje", "Chega hoje"))
        self.assertTrue(ocup["chegada"])

    def test_back_to_back_sai_hoje_e_ainda_marca_a_chegada(self):
        """O caso mais apertado do dia: o hóspede sai e outro chega no mesmo quarto."""
        self._hospedar(self.uh, sai_em_dias=0)
        self._chegada_hoje(self.uh, nome="Quem chega depois")
        ocup = self._linha(self.uh)["ocupacao"]
        self.assertEqual(ocup["cod"], "sai_hoje")
        self.assertTrue(ocup["chegada"])
        self.assertContains(self.client.get(reverse("governanca:quartos")),
                            "Chega outro")

    def test_quarto_bloqueado_e_bloqueado_nao_vago(self):
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        self.assertEqual(self._linha(self.uh)["ocupacao"]["cod"], "bloqueado")

    def test_a_lista_mostra_quem_esta_no_quarto(self):
        self._hospedar(self.uh, nome="Ana Lima")
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("gov-ocupacao", corpo)
        self.assertIn("Ocupado", corpo)
        self.assertIn("Ana Lima", corpo)

    def test_o_tipo_do_quarto_sai_da_linha_e_vai_para_a_ficha(self):
        """Dado secundário: ocupava a linha de baixo e não muda o que fazer agora.
        Não vira dica de hover — num tablet isso seria sumir."""
        self._hospedar(self.uh)
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertNotIn(f"- {self.uh.tipo.nome}", corpo)
        self.assertNotIn(f'<small class="ajuda">{self.uh.tipo.nome}</small>', corpo)
        self.assertContains(
            self.client.get(reverse("governanca:quarto", args=[self.uh.pk])),
            self.uh.tipo.nome)

    def test_a_visao_geral_resume_a_casa_por_ocupacao(self):
        self._hospedar(self.uh, sai_em_dias=0)                # sai hoje
        self._hospedar(self.uh2, sai_em_dias=3)               # ocupado
        resumo = {o["cod"]: o["n"] for o in services.visao_geral()["ocupacao"]}
        self.assertEqual(resumo.get("sai_hoje"), 1)
        self.assertEqual(resumo.get("ocupado"), 1)
        self.assertNotIn("chega_hoje", resumo)                # zero não vira linha
        r = self.client.get(reverse("governanca:painel"))
        self.assertContains(r, "A casa hoje")
        self.assertContains(r, "corredor-ocupacao")

    def test_ocupacao_na_porta_da_visao_geral(self):
        self._hospedar(self.uh, nome="Ana Lima")
        porta = next(p for p in services.visao_geral()["portas"]
                     if p["uh"].pk == self.uh.pk)
        self.assertEqual(porta["ocupacao"], "Ocupado")
        self.assertIn("Ana Lima", porta["hospede"])

    def test_consultas_constantes_com_a_ocupacao(self):
        """A ocupação sai do mesmo retrato do PMS — nenhuma consulta nova."""
        self._hospedar(self.uh)
        services.visao_geral()          # aquece o singleton de configuração
        with self.assertNumQueries(12):
            services.visao_geral()
        for n in range(3, 11):
            self._hospedar(UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo))
        with self.assertNumQueries(12):
            services.visao_geral()


class OcupacaoSemReservasTests(RondaBase):
    """Sem o módulo Reservas a Governança não afirma nada sobre ocupação."""

    def setUp(self):
        super().setUp()
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        self.client.login(username="governanta", password="senha-forte-123")

    def test_a_linha_nao_inventa_ocupacao(self):
        ocup = services.painel_limpeza()["linhas"][0]["ocupacao"]
        self.assertEqual(ocup["cod"], "")
        self.assertEqual(ocup["rotulo"], "")

    def test_a_visao_geral_abre_sem_o_resumo_de_ocupacao(self):
        dados = services.visao_geral()
        self.assertEqual(dados["ocupacao"], [])
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 200)

    def test_a_lista_volta_a_mostrar_o_tipo_do_quarto(self):
        """Sem ocupação para contar, a linha não fica muda: mostra o tipo."""
        self.assertContains(self.client.get(reverse("governanca:quartos")),
                            f'<small class="ajuda">{self.uh.tipo.nome}</small>')


class BlocoDoQuartoTests(RondaBase):
    """O bloco da visão geral é lido de longe: número e ESTADO na frente.

    O estado saía num rótulo de 9 px em maiúsculas, o maior texto do bloco era o
    tipo do quarto e a metade de baixo ficava vazia.
    """

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def _corpo(self):
        return self.client.get(reverse("governanca:painel")).content.decode()

    def test_o_estado_tem_marcacao_propria_no_bloco(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        corpo = self._corpo()
        self.assertIn('class="porta-estado"', corpo)
        self.assertIn("A limpar", corpo)

    def test_o_tipo_do_quarto_sai_do_bloco_e_vai_para_a_ficha(self):
        """Dado secundário. Na dica ele seria invisível no tablet — foi para a
        ficha do quarto, que abre com um toque na porta."""
        corpo = self._corpo()
        self.assertNotIn('class="porta-nome"', corpo)       # era o maior texto
        self.assertNotIn(f"- {self.tipo.nome}", corpo)      # não é só no hover
        ficha = self.client.get(reverse("governanca:quarto", args=[self.uh.pk]))
        self.assertContains(ficha, self.tipo.nome)

    def test_quem_esta_no_quarto_aparece_no_bloco(self):
        self._hospedar(self.uh, nome="Ana Lima")
        corpo = self._corpo()
        self.assertIn('class="porta-ocupacao"', corpo)
        self.assertIn("Ana Lima", corpo)

    def test_a_camareira_aparece_no_rodape_do_bloco(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        maria = Usuario.objects.create_user(
            username="maria", password="senha-forte-123", first_name="Maria")
        tarefa.camareira = maria
        tarefa.save(update_fields=["camareira"])
        corpo = self._corpo()
        self.assertIn('class="porta-quem"', corpo)
        self.assertIn("Maria", corpo)

    def test_bloco_sem_camareira_e_sem_divergencia_nao_tem_rodape_vazio(self):
        """O rodapé é uma faixa com fio em cima: sem conteúdo, era metade do bloco
        em branco."""
        self.assertNotIn('class="porta-rodape"', self._corpo())

    def test_quarto_bloqueado_diz_bloqueado_no_bloco(self):
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        porta = next(p for p in services.visao_geral()["portas"]
                     if p["uh"].pk == self.uh.pk)
        self.assertEqual(porta["ocupacao"], "Bloqueado")
        self.assertEqual(porta["cor"], "limp-bloqueada")


class QuartoOcupadoNaoDizProntoTests(RondaBase):
    """"Pronto" quer dizer «pode receber hóspede» — e o quarto já tem um.

    Com a casa cheia a tela mostrava 21 blocos anunciando "pode receber hóspede"
    sobre quartos ocupados. Com gente dentro, limpo e conferido é ARRUMADO: o
    serviço do dia saiu, não é uma unidade vendável.
    """

    def _linha(self, uh):
        return next(ln for ln in services.painel_limpeza()["linhas"]
                    if ln["uh"].pk == uh.pk)

    def test_quarto_vago_e_conferido_continua_pronto(self):
        services.inspecionar(self.uh, self.user)
        linha = self._linha(self.uh)
        self.assertEqual(linha["situacao_label"], "Pronto")
        self.assertIn("Pode receber hóspede", linha["explicacao"])

    def test_quarto_ocupado_e_conferido_diz_arrumado(self):
        self._hospedar(self.uh, sai_em_dias=3)
        services.inspecionar(self.uh, self.user)
        linha = self._linha(self.uh)
        self.assertEqual(linha["situacao_label"], "Arrumado")
        self.assertIn("O hóspede continua no quarto", linha["explicacao"])
        self.assertNotIn("Pode receber hóspede", linha["explicacao"])

    def test_quem_sai_hoje_lembra_que_a_faxina_vem_no_checkout(self):
        self._hospedar(self.uh, sai_em_dias=0)
        services.inspecionar(self.uh, self.user)
        self.assertIn("sai hoje", self._linha(self.uh)["explicacao"])

    def test_ocupado_sem_nenhum_registro_nao_finge_arrumacao(self):
        self._hospedar(self.uh, sai_em_dias=3)
        StatusLimpeza.objects.filter(uh=self.uh).delete()
        linha = self._linha(self.uh)
        self.assertEqual(linha["situacao_label"], "Arrumado")
        self.assertEqual(linha["explicacao"], "Sem arrumação registrada hoje.")

    def test_o_estado_do_banco_nao_muda_so_o_rotulo_da_tela(self):
        """A palavra é da tela: o model, o filtro e o Mapa seguem em
        `inspecionada`."""
        self._hospedar(self.uh, sai_em_dias=3)
        services.inspecionar(self.uh, self.user)
        self.assertEqual(self._linha(self.uh)["situacao"],
                         StatusLimpeza.Situacao.INSPECIONADA)
        self.assertEqual(services.status_por_uh()[self.uh.pk], "inspecionada")

    def test_quarto_sujo_ocupado_segue_a_limpar(self):
        self._hospedar(self.uh, sai_em_dias=3)
        services.abrir_faxina(self.uh, tipo=TarefaGovernanca.Tipo.ARRUMACAO,
                              usuario=self.user, origem="arrumacao_diaria")
        self.assertEqual(self._linha(self.uh)["situacao_label"], "A limpar")


class PlanoDoDiaTests(RondaBase):
    """A ordem de atacar o dia, que a supervisora fazia de cabeça.

    1. chegada de hoje com o quarto ainda não pronto; 2. saída de hoje (vai
    sujar); 3. ocupado pedindo arrumação; 4. o resto.
    """

    def setUp(self):
        super().setUp()
        self.uh3 = UH.objects.create(numero="Quarto 03", tipo=self.tipo)
        self.uh4 = UH.objects.create(numero="Quarto 04", tipo=self.tipo)
        self.client.login(username="governanta", password="senha-forte-123")

    def _chegada_hoje(self, uh, nome="Quem chega"):
        from apps.reservas.models import Reserva
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=nome),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def _grupos(self, plano=None):
        plano = plano or services.plano_do_dia()
        return {g["cod"]: [q["uh"].numero for q in g["quartos"]]
                for g in plano["grupos"]}

    def test_ocupado_ja_limpo_nao_entra_na_fila_de_arrumar(self):
        """Limpo e ocupado só espera a supervisora — aparecia em "a arrumar"
        dizendo "Limpo"."""
        self._hospedar(self.uh, sai_em_dias=3)
        services.definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.user)
        grupos = self._grupos()
        self.assertNotIn("Quarto 01", grupos.get("arrumacao", []))
        self.assertIn("Quarto 01", grupos["resto"])

    def test_a_ordem_dos_grupos_e_sempre_a_mesma(self):
        self._chegada_hoje(self.uh)
        services.abrir_faxina(self.uh, usuario=self.user)
        self._hospedar(self.uh2, sai_em_dias=0)                 # sai hoje
        self._hospedar(self.uh3, sai_em_dias=3)                 # ocupado
        services.abrir_faxina(self.uh3, usuario=self.user)      # a arrumar
        services.abrir_faxina(self.uh4, usuario=self.user)      # vago sujo
        plano = services.plano_do_dia()
        self.assertEqual([g["cod"] for g in plano["grupos"]],
                         ["chegada", "saida", "arrumacao", "resto"])
        grupos = self._grupos(plano)
        self.assertEqual(grupos["chegada"], ["Quarto 01"])
        self.assertEqual(grupos["saida"], ["Quarto 02"])
        self.assertEqual(grupos["arrumacao"], ["Quarto 03"])
        self.assertEqual(grupos["resto"], ["Quarto 04"])

    def test_chegada_vem_antes_mesmo_com_o_quarto_pronto(self):
        """O grupo das chegadas lista todas, com as não prontas na frente."""
        self._chegada_hoje(self.uh, nome="Pronta")
        services.inspecionar(self.uh, self.user)
        self._chegada_hoje(self.uh2, nome="Atrasada")
        services.abrir_faxina(self.uh2, usuario=self.user)
        chegada = next(g for g in services.plano_do_dia()["grupos"]
                       if g["cod"] == "chegada")
        self.assertEqual([q["uh"].numero for q in chegada["quartos"]],
                         ["Quarto 02", "Quarto 01"])
        self.assertFalse(chegada["quartos"][0]["pronto"])

    def test_back_to_back_entra_nas_chegadas_e_nao_nas_saidas(self):
        """Sai um e entra outro: quem manda na urgência é quem está chegando."""
        self._hospedar(self.uh, sai_em_dias=0)
        self._chegada_hoje(self.uh, nome="O próximo")
        grupos = self._grupos()
        self.assertIn("Quarto 01", grupos["chegada"])
        self.assertNotIn("Quarto 01", grupos.get("saida", []))

    def test_quarto_sem_nada_pendente_nao_vira_linha_do_plano(self):
        """15 quartos prontos listados como "o resto" não são um plano."""
        services.abrir_faxina(self.uh, usuario=self.user)
        plano = services.plano_do_dia()
        self.assertEqual(self._grupos(plano)["resto"], ["Quarto 01"])
        self.assertEqual(plano["tranquilos"], 3)

    def test_quarto_bloqueado_nao_entra_no_trabalho_do_dia(self):
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        services.definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.user)
        self._chegada_hoje(self.uh2)
        services.abrir_faxina(self.uh2, usuario=self.user)
        grupos = self._grupos()
        self.assertNotIn("Quarto 01", grupos.get("chegada", []))
        self.assertNotIn("Quarto 01", grupos.get("arrumacao", []))
        self.assertNotIn("Quarto 01", grupos.get("resto", []))

    def test_da_tempo_responde_com_quantos_e_quanto_falta(self):
        self._chegada_hoje(self.uh)
        services.abrir_faxina(self.uh, usuario=self.user)
        plano = services.plano_do_dia()
        self.assertEqual(plano["a_entregar"], 1)
        self.assertIsNotNone(plano["hora_checkin"])
        # Ou sobra tempo ("faltam 3h20"), ou o horário já passou — nunca os dois.
        self.assertNotEqual(bool(plano["falta_tempo"]), plano["atrasado"])
        self.assertContains(self.client.get(reverse("governanca:painel")),
                            "quarto para entregar")

    def test_a_tela_mostra_o_plano_com_os_grupos(self):
        self._chegada_hoje(self.uh)
        services.abrir_faxina(self.uh, usuario=self.user)
        self._hospedar(self.uh2, sai_em_dias=0)
        r = self.client.get(reverse("governanca:painel"))
        self.assertContains(r, "Plano do dia")
        self.assertContains(r, "Chegadas de hoje")
        self.assertContains(r, "Saídas de hoje")
        self.assertContains(r, "não pedem nada agora")

    def test_a_lista_abre_na_ordem_do_plano(self):
        """A camareira não precisa cruzar a lista com o mapa de reservas."""
        services.abrir_faxina(self.uh4, usuario=self.user)      # vago sujo
        self._chegada_hoje(self.uh3)
        services.abrir_faxina(self.uh3, usuario=self.user)      # chegada atrasada
        numeros = [ln["uh"].numero for ln in services.painel_limpeza()["linhas"]]
        self.assertLess(numeros.index("Quarto 03"), numeros.index("Quarto 04"))

    def test_sem_reservas_o_plano_vira_so_a_fila_de_limpeza(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        services.abrir_faxina(self.uh, usuario=self.user)
        plano = services.plano_do_dia()
        self.assertEqual([g["cod"] for g in plano["grupos"]], ["resto"])
        self.assertEqual(plano["a_entregar"], 0)
        self.assertEqual((plano["falta_tempo"], plano["atrasado"]), ("", False))
        self.assertEqual(self.client.get(reverse("governanca:painel")).status_code, 200)

    def test_o_plano_nao_custa_consulta_nenhuma_a_mais(self):
        self._hospedar(self.uh)
        services.visao_geral()          # aquece o singleton de configuração
        with self.assertNumQueries(12):
            services.visao_geral()


class QuemLimpaVemDaEscalaTests(GovernancaBase):
    """Escolher a camareira numa lista com a casa inteira dentro era adivinhação.

    A Escala é o único módulo que sabe quem trabalha hoje. Sem ela, a tela não
    quebra: mostra todo mundo, como antes.
    """

    def setUp(self):
        super().setUp()
        from datetime import time

        from apps.escala.models import Turno
        from apps.escala.services import atribuir
        from apps.nucleo.models import Funcionario

        self.hoje = timezone.localdate()
        self.turno = Turno.objects.create(nome="Manhã", setor="governanca",
                                          inicio=time(7, 0), fim=time(15, 0))
        self.maria = self._camareira("Maria", "maria")
        self.joana = self._camareira("Joana", "joana")
        self.recepcao = Usuario.objects.create_user(
            username="recepcao", password="senha-forte-123", first_name="Recepção")
        for func in Funcionario.objects.filter(usuario__in=[self.maria, self.joana]):
            atribuir(self.turno, func, self.hoje, self.user)
        self.client.login(username="governanta", password="senha-forte-123")

    def _camareira(self, nome, username):
        from apps.nucleo.models import Funcionario, Pessoa

        usuario = Usuario.objects.create_user(
            username=username, password="senha-forte-123", first_name=nome)
        Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=nome),
                                   cargo="Camareira", usuario=usuario)
        return usuario

    def test_de_turno_hoje_vem_separado_das_outras(self):
        quem = services.camareiras_do_dia()
        self.assertEqual({u.pk for u in quem["de_turno"]},
                         {self.maria.pk, self.joana.pk})
        self.assertIn(self.recepcao.pk, {u.pk for u in quem["outras"]})
        self.assertTrue(quem["tem_escala"])

    def test_o_seletor_poe_as_de_turno_no_alto(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("De turno hoje", corpo)
        self.assertIn("Fora da escala de hoje", corpo)
        self.assertLess(corpo.index("De turno hoje"), corpo.index("Fora da escala"))

    def test_sem_o_modulo_escala_a_lista_e_a_de_sempre(self):
        ModuloContratado.objects.filter(codigo=Modulo.ESCALA).update(ativo=False)
        quem = services.camareiras_do_dia()
        self.assertEqual(quem["de_turno"], [])
        self.assertFalse(quem["tem_escala"])
        self.assertIn(self.maria.pk, {u.pk for u in quem["outras"]})
        services.abrir_faxina(self.uh, usuario=self.user)
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertNotIn("De turno hoje", corpo)
        self.assertIn("Maria", corpo)


class DistribuirAFilaTests(QuemLimpaVemDaEscalaTests):
    """Um toque no lugar de abrir um <select> por quarto — e equilibrado."""

    def setUp(self):
        super().setUp()
        self.quartos = [self.uh] + [
            UH.objects.create(numero=f"Quarto {n:02d}", tipo=self.tipo)
            for n in range(2, 6)
        ]

    def _fila(self):
        for uh in self.quartos:
            services.abrir_faxina(uh, usuario=self.user)

    def _por_camareira(self):
        from collections import Counter
        return Counter(
            t.camareira_id for t in TarefaGovernanca.objects.exclude(
                status=TarefaGovernanca.Status.CONCLUIDA)
        )

    def test_divide_os_quartos_entre_quem_esta_de_turno(self):
        self._fila()
        resultado = services.distribuir_fila(self.user)
        self.assertEqual((resultado["atribuidas"], resultado["equipe"]), (5, 2))
        carga = self._por_camareira()
        self.assertIsNone(carga.get(None))
        self.assertEqual(sorted(carga.values()), [2, 3])     # equilibrado

    def test_quem_ja_tem_quarto_recebe_menos(self):
        """Distribuir "do zero" jogava quatro em cima de quem já estava com seis."""
        self._fila()
        for tarefa in TarefaGovernanca.objects.all()[:3]:
            tarefa.camareira = self.maria
            tarefa.save(update_fields=["camareira"])
        services.distribuir_fila(self.user)
        carga = self._por_camareira()
        self.assertEqual(carga[self.maria.pk], 3)   # não ganhou mais nenhum
        self.assertEqual(carga[self.joana.pk], 2)

    def test_o_mais_urgente_sai_primeiro(self):
        """A ordem é a do plano do dia: chegada de hoje antes do resto."""
        from apps.reservas.models import Reserva

        Reserva.objects.create(
            uh=self.quartos[4], hospede=Pessoa.objects.create(nome="Chega hoje"),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)
        self._fila()
        resultado = services.distribuir_fila(self.user)
        self.assertEqual(resultado["detalhe"][0][0], self.quartos[4].numero)

    def test_quarto_que_ja_tem_camareira_nao_e_mexido(self):
        self._fila()
        tarefa = TarefaGovernanca.objects.first()
        tarefa.camareira = self.recepcao     # alguém de fora cobrindo
        tarefa.save(update_fields=["camareira"])
        services.distribuir_fila(self.user)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.camareira_id, self.recepcao.pk)

    def test_rodar_de_novo_nao_embaralha(self):
        self._fila()
        services.distribuir_fila(self.user)
        antes = {t.pk: t.camareira_id for t in TarefaGovernanca.objects.all()}
        resultado = services.distribuir_fila(self.user)
        self.assertEqual(resultado["atribuidas"], 0)
        self.assertEqual({t.pk: t.camareira_id for t in TarefaGovernanca.objects.all()},
                         antes)

    def test_quarto_bloqueado_fica_fora_da_divisao(self):
        self._fila()
        bloqueado = self.quartos[0]
        bloqueado.status = UH.Status.BLOQUEADA
        bloqueado.save(update_fields=["status"])
        services.distribuir_fila(self.user)
        tarefa = TarefaGovernanca.objects.get(uh=bloqueado)
        self.assertIsNone(tarefa.camareira_id)

    def test_sem_ninguem_de_turno_a_tela_explica_em_vez_de_espalhar(self):
        from apps.escala.models import Atribuicao

        Atribuicao.objects.all().delete()
        self._fila()
        resultado = services.distribuir_fila(self.user)
        self.assertEqual((resultado["atribuidas"], resultado["motivo"]),
                         (0, "sem_turno"))
        r = self.client.post(reverse("governanca:distribuir"), HTTP_HX_REQUEST="true")
        aviso = json.loads(r["HX-Trigger"])["aviso"]
        self.assertIn("Não há funcionários escalados hoje", aviso["texto"])
        self.assertEqual(aviso["tipo"], "warning")

    def test_o_botao_so_aparece_com_quarto_sem_camareira(self):
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertNotIn("Distribuir a fila", corpo)
        self._fila()
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("Distribuir a fila", corpo)
        self.assertIn("de turno hoje, equilibrando a carga", corpo)

    def test_pela_view_com_htmx_devolve_o_quadro_e_avisa(self):
        self._fila()
        r = self.client.post(reverse("governanca:distribuir"), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "governanca/partials/quadro.html")
        self.assertIn("divididos entre", r["HX-Trigger"])

    def test_get_nao_distribui(self):
        self._fila()
        self.client.get(reverse("governanca:distribuir"))
        self.assertEqual(self._por_camareira()[None], 5)

    def test_a_divisao_fica_na_trilha_com_quem_mandou(self):
        self._fila()
        services.distribuir_fila(self.user)
        trilha = TrilhaAuditoria.objects.filter(acao="fila_distribuida").first()
        self.assertIsNotNone(trilha)
        self.assertEqual(trilha.usuario_id, self.user.pk)
        self.assertEqual(trilha.detalhe["quartos"], 5)


class MinhaFilaTests(RondaBase):
    """A fila da camareira, no celular dela: os quartos DELA, na ordem de atacar,
    um botão grande por quarto."""

    def setUp(self):
        super().setUp()
        self.uh3 = UH.objects.create(numero="Quarto 03", tipo=self.tipo)
        self.maria = self._camareira("Maria", "maria")
        self.joana = self._camareira("Joana", "joana")
        self.client.login(username="maria", password="senha-forte-123")

    def _camareira(self, nome, username):
        """Camareira de verdade: login com o módulo Governança, não superusuária."""
        usuario = Usuario.objects.create_user(
            username=username, password="senha-forte-123", first_name=nome)
        usuario.modulos.set(ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA))
        return usuario

    def _para(self, uh, camareira, **kw):
        tarefa = services.abrir_faxina(uh, usuario=self.user, **kw)
        tarefa.camareira = camareira
        tarefa.save(update_fields=["camareira"])
        return tarefa

    def _chegada_hoje(self, uh, nome="Quem chega"):
        from apps.reservas.models import Reserva
        return Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=nome),
            checkin=self.hoje, checkout=self.hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def test_so_os_quartos_dela(self):
        self._para(self.uh, self.maria)
        self._para(self.uh2, self.joana)
        fila = services.minha_fila(self.maria)["fila"]
        self.assertEqual([q["uh"].numero for q in fila], ["Quarto 01"])

    def test_a_ordem_e_a_do_plano_do_dia(self):
        """Chegada de hoje antes do quarto que ninguém espera."""
        self._para(self.uh2, self.maria)            # vago sujo
        self._chegada_hoje(self.uh3)
        self._para(self.uh3, self.maria)            # chegada hoje
        fila = services.minha_fila(self.maria)["fila"]
        self.assertEqual([q["uh"].numero for q in fila], ["Quarto 03", "Quarto 02"])

    def test_o_que_ela_ja_comecou_fica_no_alto(self):
        self._para(self.uh, self.maria)
        comecada = self._para(self.uh2, self.maria)
        services.iniciar_tarefa(comecada, self.maria)
        dados = services.minha_fila(self.maria)
        self.assertEqual(dados["fila"][0]["uh"].numero, "Quarto 02")
        self.assertTrue(dados["fila"][0]["fazendo"])
        self.assertEqual(dados["fazendo"]["uh"].numero, "Quarto 02")

    def test_quarto_bloqueado_nao_entra_na_fila(self):
        """Enquanto o técnico não devolve, a faxina não acontece — mandar a
        camareira bater numa porta fechada é pior que não mostrar."""
        self._para(self.uh, self.maria)
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        self.assertEqual(services.minha_fila(self.maria)["fila"], [])

    def test_o_que_ela_entregou_hoje_aparece_como_recibo(self):
        tarefa = self._para(self.uh, self.maria)
        services.concluir_tarefa(tarefa, self.maria)
        dados = services.minha_fila(self.maria)
        self.assertEqual(dados["fila"], [])
        self.assertEqual([t.uh.numero for t in dados["feitas"]], ["Quarto 01"])

    def test_a_tela_abre_com_um_botao_por_quarto(self):
        self._para(self.uh, self.maria)
        r = self.client.get(reverse("governanca:minha_fila"))
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "governanca/fila.html")
        corpo = r.content.decode()
        self.assertIn("Começar", corpo)
        self.assertNotIn("Terminei", corpo)

    def test_comecar_e_terminar_pela_fila_sem_sair_dela(self):
        tarefa = self._para(self.uh, self.maria)
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "iniciar", "fila": "1"}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(r, "governanca/partials/fila.html")
        self.assertIn("Terminei", r.content.decode())
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "concluir", "fila": "1"}, HTTP_HX_REQUEST="true")
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.CONCLUIDA)
        self.assertIn("Já entreguei hoje", r.content.decode())

    def test_sem_javascript_volta_para_a_fila_e_nao_para_a_lista(self):
        tarefa = self._para(self.uh, self.maria)
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "iniciar", "fila": "1"})
        self.assertRedirects(r, reverse("governanca:minha_fila"))

    def test_a_acao_da_supervisora_continua_voltando_para_a_lista(self):
        tarefa = self._para(self.uh, self.maria)
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "iniciar"})
        self.assertRedirects(r, reverse("governanca:quartos"))

    def test_fila_vazia_explica_de_onde_vem_quarto(self):
        corpo = self.client.get(reverse("governanca:minha_fila")).content.decode()
        self.assertIn("Nenhum quarto na sua fila agora", corpo)

    def test_o_motivo_da_devolucao_viaja_para_a_fila(self):
        services.definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.user)
        services.reprovar_inspecao(self.uh, self.user, "pó no armário")
        tarefa = TarefaGovernanca.objects.filter(uh=self.uh, origem="reprovada").first()
        tarefa.camareira = self.maria
        tarefa.save(update_fields=["camareira"])
        self.assertContains(self.client.get(reverse("governanca:minha_fila")),
                            "pó no armário")

    def test_a_fila_dela_nao_repete_o_nome_dela(self):
        """"Na fila de Maria Aparecida" em cada cartão da fila da Maria é ruído."""
        self._para(self.uh, self.maria, origem="checkout")
        fila = services.minha_fila(self.maria)["fila"]
        self.assertIn("O hóspede fez check-out", fila[0]["explicacao"])
        self.assertNotIn("Na fila de", fila[0]["explicacao"])
        # Na lista da supervisora, que mostra a casa toda, o nome continua.
        linha = next(ln for ln in services.painel_limpeza()["linhas"]
                     if ln["uh"].pk == self.uh.pk)
        self.assertIn("Na fila de Maria", linha["explicacao"])

    def test_exige_o_modulo(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.assertEqual(
            self.client.get(reverse("governanca:minha_fila")).status_code, 404)


class ReportarProblemaTests(RondaBase):
    """A camareira acha o chuveiro pingando e abre a OS dali mesmo."""

    def setUp(self):
        super().setUp()
        self.maria = Usuario.objects.create_user(
            username="maria", password="senha-forte-123", first_name="Maria")
        self.maria.modulos.set(ModuloContratado.objects.filter(
            codigo__in=[Modulo.GOVERNANCA, Modulo.MANUTENCAO]))
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        tarefa.camareira = self.maria
        tarefa.save(update_fields=["camareira"])
        self.client.login(username="maria", password="senha-forte-123")

    def _ordens(self):
        from apps.manutencao.models import OrdemServico
        return OrdemServico.objects.all()

    def test_abre_ordem_de_servico_na_manutencao(self):
        r = self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                             {"descricao": "chuveiro pingando", "fila": "1"},
                             HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(r, "governanca/partials/fila.html")
        ordem = self._ordens().get()
        self.assertEqual(ordem.uh_id, self.uh.pk)
        self.assertIn("chuveiro pingando", ordem.descricao)
        self.assertEqual(ordem.criado_por_id, self.maria.pk)
        self.assertEqual(r["HX-Retarget"], "#gov-fila")
        self.assertEqual(r["X-Gov-Registrado"], "1")

    def test_a_os_nao_tira_o_quarto_de_operacao(self):
        """Quem decide bloquear a unidade é a Manutenção, não a camareira."""
        self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                         {"descricao": "lâmpada queimada", "fila": "1"})
        self.uh.refresh_from_db()
        self.assertFalse(self._ordens().get().bloqueia_uh)
        self.assertEqual(self.uh.status, UH.Status.ATIVA)

    def test_sem_descricao_nao_abre_chamado(self):
        r = self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                             {"descricao": "  ", "fila": "1"}, HTTP_HX_REQUEST="true")
        self.assertEqual(self._ordens().count(), 0)
        self.assertTemplateUsed(r, "governanca/partials/reportar_modal.html")
        self.assertContains(r, "Descreva o problema")
        self.assertNotIn("X-Gov-Registrado", r)

    def test_descricao_longa_volta_preenchida_e_sem_abrir_chamado(self):
        texto = "Descrição do defeito " * 25
        r = self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                             {"descricao": texto, "fila": "1"}, HTTP_HX_REQUEST="true")
        self.assertEqual(self._ordens().count(), 0)
        self.assertContains(r, "Use até 400 caracteres")
        self.assertEqual(r.context["form"].data["descricao"], texto)

    def test_erro_sem_javascript_permanece_na_pagina_de_relato(self):
        r = self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                             {"descricao": " ", "fila": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "governanca/reportar.html")
        self.assertContains(r, "Descreva o problema")

    def test_painel_nao_diz_fila_vazia_quando_ha_trabalho_distribuido(self):
        r = self.client.get(reverse("governanca:painel"))
        self.assertContains(r, "A limpeza já está distribuída")
        self.assertNotContains(r, "Nada pendente na governança agora")

    def test_com_htmx_abre_o_modal_da_casa_e_sem_js_a_pagina(self):
        r = self.client.get(reverse("governanca:reportar", args=[self.uh.pk]),
                            HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(r, "governanca/partials/reportar_modal.html")
        r = self.client.get(reverse("governanca:reportar", args=[self.uh.pk]))
        self.assertTemplateUsed(r, "governanca/reportar.html")

    def test_sem_o_modulo_manutencao_o_botao_some_e_o_post_explica(self):
        ModuloContratado.objects.filter(codigo=Modulo.MANUTENCAO).update(ativo=False)
        corpo = self.client.get(reverse("governanca:minha_fila")).content.decode()
        self.assertNotIn("Reportar problema", corpo)
        r = self.client.post(reverse("governanca:reportar", args=[self.uh.pk]),
                             {"descricao": "torneira", "fila": "1"},
                             HTTP_HX_REQUEST="true")
        self.assertEqual(self._ordens().count(), 0)
        self.assertContains(r, "Manutenção está desativado")
        self.assertContains(r, "torneira")
        self.assertNotIn("X-Gov-Registrado", r)

    def test_com_o_modulo_ativo_o_botao_aparece_na_fila(self):
        self.assertContains(self.client.get(reverse("governanca:minha_fila")),
                            "Reportar problema")


class QuartoBloqueadoTests(RondaBase):
    """Quarto em reparo não recebe hóspede nem entra na fila de ninguém."""

    def setUp(self):
        super().setUp()
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        self.client.login(username="governanta", password="senha-forte-123")

    def _linha(self):
        return next(ln for ln in services.painel_limpeza()["linhas"]
                    if ln["uh"].pk == self.uh.pk)

    def test_a_frase_fala_do_reparo_e_nao_de_receber_hospede(self):
        services.inspecionar(self.uh, self.user)
        explicacao = self._linha()["explicacao"]
        self.assertIn("Em manutenção", explicacao)
        self.assertNotIn("Pode receber hóspede", explicacao)

    def test_a_frase_diz_tambem_como_esta_a_limpeza(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        self.assertIn("a limpar", self._linha()["explicacao"])

    def test_a_linha_nao_oferece_proximo_passo_de_limpeza(self):
        services.inspecionar(self.uh, self.user)
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        linha = corpo[corpo.index(f'id="quarto-{self.uh.pk}"'):]
        linha = linha[:linha.index("</tr>")]
        self.assertIn("Em manutenção (fora de operação)", linha)
        self.assertNotIn("pronto para o hóspede", linha)
        self.assertNotIn("Pedir nova limpeza", linha)


class EscaladaSemLoginTests(GovernancaBase):
    """Escalada hoje mas sem login no CRM: a tarefa é de um usuário, então não há
    a quem atribuir — e "ninguém de turno hoje" seria mentira."""

    def setUp(self):
        super().setUp()
        from datetime import time

        from apps.escala.models import Turno
        from apps.escala.services import atribuir
        from apps.nucleo.models import Funcionario, Pessoa

        self.hoje = timezone.localdate()
        turno = Turno.objects.create(nome="Diurno", setor="governanca",
                                     inicio=time(7, 0), fim=time(15, 0))
        self.sem_login = Funcionario.objects.create(
            pessoa=Pessoa.objects.create(nome="Rita Camareira"), cargo="Camareira")
        atribuir(turno, self.sem_login, self.hoje, self.user)
        services.abrir_faxina(self.uh, usuario=self.user)
        self.client.login(username="governanta", password="senha-forte-123")

    def test_a_escala_sabe_quem_e_mas_nao_ha_login(self):
        quem = services.camareiras_do_dia()
        self.assertEqual(quem["de_turno"], [])
        self.assertEqual(quem["sem_login"], ["Rita Camareira"])

    def test_distribuir_nomeia_a_causa_certa(self):
        resultado = services.distribuir_fila(self.user)
        self.assertEqual(resultado["motivo"], "sem_login")
        r = self.client.post(reverse("governanca:distribuir"), HTTP_HX_REQUEST="true")
        texto = json.loads(r["HX-Trigger"])["aviso"]["texto"]
        self.assertIn("Rita Camareira", texto)
        self.assertIn("sem acesso ao CRM", texto)
        self.assertNotIn("Ninguém de turno", texto)

    def test_a_tela_diz_o_que_fazer(self):
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn("Rita Camareira", corpo)
        self.assertIn("Ative o acesso na ficha do funcionário", corpo)
        self.assertNotIn("Distribuir a fila", corpo)

    def test_com_o_login_ligado_passa_a_distribuir(self):
        self.sem_login.usuario = Usuario.objects.create_user(
            username="rita", password="senha-forte-123", first_name="Rita")
        self.sem_login.save(update_fields=["usuario"])
        self.assertEqual(services.distribuir_fila(self.user)["atribuidas"], 1)


class FichaDoQuartoTests(RondaBase):
    """Um toque na porta resolve o quarto ali.

    No tablet, "ir até a linha daquele quarto" queria dizer sair da parede de
    blocos e caçar numa lista de 24 — e tudo o que a porta sabia (tipo, motivo,
    hóspede) só existia na dica de hover, que no toque não existe.
    """

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def _ficha(self, uh=None, htmx=False, **kw):
        extra = {"HTTP_HX_REQUEST": "true"} if htmx else {}
        return self.client.get(
            reverse("governanca:quarto", args=[(uh or self.uh).pk]), kw, **extra)

    def test_a_ficha_traz_o_que_so_existia_na_dica(self):
        self._hospedar(self.uh, nome="Ana Lima")
        services.abrir_faxina(self.uh, usuario=self.user, origem="checkout")
        r = self._ficha()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.uh.numero)
        self.assertContains(r, "A limpar")
        self.assertContains(r, self.tipo.nome)            # tipo do quarto
        self.assertContains(r, "Ana Lima")                # quem está no quarto
        self.assertContains(r, "O hóspede fez check-out")  # o porquê

    def test_a_ficha_traz_o_proximo_passo_do_quarto(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        self.assertContains(self._ficha(), "Começar limpeza")
        services.definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.user)
        r = self._ficha()
        self.assertContains(r, "Aprovar limpeza")
        self.assertContains(r, "Devolver para limpar")

    def test_com_htmx_abre_a_gaveta_e_sem_js_a_pagina(self):
        r = self._ficha(htmx=True)
        self.assertTemplateUsed(r, "governanca/partials/quarto_sheet.html")
        self.assertTemplateUsed(r, "governanca/partials/quarto_ficha.html")
        self.assertTemplateUsed(self._ficha(), "governanca/quarto.html")

    def test_a_acao_da_ficha_navega_e_volta_para_onde_a_pessoa_estava(self):
        """Ela veio da parede de blocos e quer vê-la atualizada depois de agir."""
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "iniciar", "voltar": "painel"})
        self.assertRedirects(r, reverse("governanca:painel"))
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.EM_ANDAMENTO)

    def test_voltar_so_aceita_tela_da_governanca(self):
        tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]),
                             {"acao": "iniciar", "voltar": "http://exemplo.invalido/"})
        self.assertRedirects(r, reverse("governanca:quartos"))

    def test_o_formulario_da_ficha_nao_usa_htmx(self):
        """Ela navega de verdade: a gaveta sai e a parede de blocos se refaz."""
        services.abrir_faxina(self.uh, usuario=self.user)
        corpo = self._ficha(voltar="painel").content.decode()
        inicio = corpo.index('name="acao"')
        trecho = corpo[max(0, inicio - 400):inicio]
        self.assertNotIn("hx-post", trecho)
        self.assertIn('name="voltar" value="painel"', corpo)

    def test_day_use_nao_tem_ficha_na_governanca(self):
        from apps.nucleo.models import TipoUH
        day = TipoUH.objects.create(nome="Dia na pousada", tarifa_base=Decimal("90"),
                                    modalidade=TipoUH.Modalidade.DAY_USE)
        uh = UH.objects.create(numero="DAY-77", tipo=day)
        self.assertRedirects(self._ficha(uh), reverse("governanca:quartos"))

    def test_a_linha_da_lista_abre_a_ficha(self):
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertIn(reverse("governanca:quarto", args=[self.uh.pk]), corpo)

    def test_exige_o_modulo(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.assertEqual(self._ficha().status_code, 404)

    def test_quarto_bloqueado_diz_que_nao_ha_passo(self):
        self.uh.status = UH.Status.BLOQUEADA
        self.uh.save(update_fields=["status"])
        r = self._ficha()
        self.assertContains(r, "Em manutenção (fora de operação)")
        self.assertNotContains(r, "Começar limpeza")


class SemHoverTests(RondaBase):
    """Nada que só exista no hover: no tablet ele não existe."""

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")

    def test_os_chips_do_ciclo_nao_dependem_de_title(self):
        """O que o `title` dizia está por extenso no «Como funciona» da tela."""
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertNotIn('title="O quarto precisa de limpeza', corpo)
        self.assertIn("Entra aqui sozinho quando o hóspede faz check-out", corpo)

    def test_os_botoes_da_ronda_dizem_o_longo_por_aria_label(self):
        corpo = self.client.get(reverse("governanca:quartos")).content.decode()
        self.assertNotIn('title="Ocupado (com bagagem)"', corpo)
        self.assertIn("Ocupado (com bagagem)", corpo)     # aria-label

    def test_a_porta_anuncia_estado_e_ocupacao_sem_hover(self):
        self._hospedar(self.uh, nome="Ana Lima")
        corpo = self.client.get(reverse("governanca:painel")).content.decode()
        self.assertIn(f'aria-label="{self.uh.numero}:', corpo)
        self.assertIn("Ana Lima", corpo)                  # visível no bloco


class DesfazerAprovacaoTests(GovernancaBase):
    """No toque, o erro é o toque errado — não a falta de convicção.

    Em vez de parar a supervisora com "tem certeza?" antes de cada aprovação, a
    tela deixa o caminho de volta à mão depois.
    """

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")
        self.tarefa = services.abrir_faxina(self.uh, usuario=self.user)
        services.iniciar_tarefa(self.tarefa, self.user)
        services.concluir_tarefa(self.tarefa, self.user)

    def _aprovar(self, **extra):
        return self.client.post(
            reverse("governanca:status_marcar", args=[self.uh.pk]),
            {"situacao": StatusLimpeza.Situacao.INSPECIONADA}, **extra)

    def test_aprovar_oferece_o_caminho_de_volta(self):
        self._aprovar()
        oferta = self.client.session.get("gov_desfazer")
        self.assertEqual(oferta["uh"], self.uh.pk)
        self.assertEqual(oferta["quarto"], self.uh.numero)
        self.assertIn("liberado para a recepção", oferta["texto"])

    def test_o_quarto_ocupado_nao_e_liberado_para_a_recepcao(self):
        """Aprovar um quarto com hóspede dentro é conferir a arrumação do dia."""
        from apps.reservas.models import Reserva
        Reserva.objects.create(
            uh=self.uh, hospede=Pessoa.objects.create(nome="Quem está lá"),
            checkin=timezone.localdate() - timedelta(days=1),
            checkout=timezone.localdate() + timedelta(days=2),
            status=Reserva.Status.HOSPEDADA, valor_diaria=Decimal("200"),
            criado_por=self.user)
        self._aprovar()
        texto = self.client.session.get("gov_desfazer")["texto"]
        self.assertIn("Arrumação do dia", texto)
        self.assertNotIn("recepção", texto)

    def test_a_oferta_aparece_na_tela_e_some_depois(self):
        self._aprovar()
        r = self.client.get(reverse("governanca:quartos"))
        self.assertContains(r, "gov-desfazer")
        self.assertContains(r, "Desfazer")
        # Uma vez só: recarregar a tela não deixa a oferta pendurada.
        self.assertNotContains(self.client.get(reverse("governanca:quartos")),
                               "gov-desfazer")

    def test_a_visao_geral_tambem_mostra_a_oferta(self):
        """A ficha do quarto devolve a pessoa para a parede de blocos."""
        self._aprovar()
        self.assertContains(self.client.get(reverse("governanca:painel")),
                            "gov-desfazer")

    def test_desfazer_devolve_o_quarto_para_a_conferencia(self):
        self._aprovar()
        self.client.post(reverse("governanca:desfazer_aprovacao", args=[self.uh.pk]))
        self.assertEqual(services.situacao_uh(self.uh).situacao,
                         StatusLimpeza.Situacao.LIMPA)
        self.tarefa.refresh_from_db()
        self.assertIsNone(self.tarefa.inspecionada_em)
        self.assertEqual(self.tarefa.status, TarefaGovernanca.Status.CONCLUIDA)

    def test_desfazer_nao_apaga_a_faxina_da_camareira(self):
        """O veredito volta atrás; a entrega dela continua valendo."""
        self._aprovar()
        services.desfazer_inspecao(self.uh, self.user)
        relatorio = services.relatorio_faxinas(timezone.localdate(),
                                               timezone.localdate())
        self.assertEqual(relatorio["total"], 1)

    def test_o_quarto_pode_ser_aprovado_de_novo(self):
        self._aprovar()
        services.desfazer_inspecao(self.uh, self.user)
        services.inspecionar(self.uh, self.user)
        self.tarefa.refresh_from_db()
        self.assertIsNotNone(self.tarefa.inspecionada_em)
        self.assertEqual(services.situacao_uh(self.uh).situacao,
                         StatusLimpeza.Situacao.INSPECIONADA)

    def test_desfazer_duas_vezes_nao_quebra(self):
        self._aprovar()
        services.desfazer_inspecao(self.uh, self.user)
        services.desfazer_inspecao(self.uh, self.user)   # idempotente
        self.assertEqual(services.situacao_uh(self.uh).situacao,
                         StatusLimpeza.Situacao.LIMPA)

    def test_desfazer_quarto_que_nunca_foi_aprovado_nao_mexe_em_nada(self):
        services.abrir_faxina(self.uh, usuario=self.user)   # volta para sujo
        services.desfazer_inspecao(self.uh, self.user)
        self.assertEqual(services.situacao_uh(self.uh).situacao,
                         StatusLimpeza.Situacao.SUJA)

    def test_fica_na_trilha(self):
        self._aprovar()
        services.desfazer_inspecao(self.uh, self.user)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="inspecao_desfeita").exists())

    def test_com_htmx_devolve_o_quadro(self):
        self._aprovar(HTTP_HX_REQUEST="true")
        r = self.client.post(reverse("governanca:desfazer_aprovacao", args=[self.uh.pk]),
                             HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(r, "governanca/partials/quadro.html")
        self.assertIn("voltou para a conferência",
                      json.loads(r["HX-Trigger"])["aviso"]["texto"])

    def test_get_nao_desfaz(self):
        self._aprovar()
        self.client.get(reverse("governanca:desfazer_aprovacao", args=[self.uh.pk]))
        self.assertEqual(services.situacao_uh(self.uh).situacao,
                         StatusLimpeza.Situacao.INSPECIONADA)

    def test_exige_o_modulo(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.assertEqual(
            self.client.post(reverse("governanca:desfazer_aprovacao",
                                     args=[self.uh.pk])).status_code, 404)


class AvisoDeCheckinSujoTests(GovernancaBase):
    """Check-in barrado pela limpeza leva ao QUARTO, não à casa inteira.

    Quem está com o hóspede na frente não tem de caçar a linha dele numa lista
    de 24 — menos ainda no tablet.
    """

    def setUp(self):
        super().setUp()
        self.client.login(username="governanta", password="senha-forte-123")
        from apps.reservas.models import Reserva
        self.reserva = Reserva.objects.create(
            uh=self.uh, hospede=Pessoa.objects.create(nome="Quem chega"),
            checkin=timezone.localdate(),
            checkout=timezone.localdate() + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.user)

    def _detalhe(self):
        return self.client.get(reverse("reservas:detalhe", args=[self.reserva.pk]))

    def test_quarto_sujo_barra_o_checkin_e_aponta_para_a_ficha_dele(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        aviso = self._detalhe().context["aviso_checkin"]
        self.assertIn(self.uh.numero, aviso["texto"])
        self.assertEqual(aviso["url"],
                         reverse("governanca:quarto", args=[self.uh.pk]))
        self.assertNotEqual(aviso["url"], reverse("governanca:painel"))

    def test_o_link_abre_o_quarto_com_o_proximo_passo(self):
        """O caminho inteiro: o aviso leva a uma tela que resolve a limpeza."""
        services.abrir_faxina(self.uh, usuario=self.user)
        r = self.client.get(self._detalhe().context["aviso_checkin"]["url"])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.uh.numero)
        self.assertContains(r, "Começar limpeza")

    def test_quarto_pronto_nao_barra_nada(self):
        services.inspecionar(self.uh, self.user)
        self.assertIsNone(self._detalhe().context["aviso_checkin"])

    def test_sem_o_modulo_governanca_o_aviso_nao_existe(self):
        services.abrir_faxina(self.uh, usuario=self.user)
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.assertIsNone(self._detalhe().context["aviso_checkin"])
