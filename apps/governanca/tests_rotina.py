from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, ModuloContratado, Pessoa, TipoUH
from apps.nucleo.modulos import Modulo
from apps.reservas.models import Reserva

from . import services
from .models import ConfiguracaoGovernanca, RotinaLimpezaDiaria, StatusLimpeza, TarefaGovernanca


class CenarioRotina:
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="rotina", password="teste")
        for codigo in (Modulo.GOVERNANCA, Modulo.RESERVAS):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.tipo = TipoUH.objects.create(nome="Quarto", tarifa_base=100)
        self.uh = UH.objects.create(numero="ROT-1", tipo=self.tipo)
        self.hoje = timezone.localdate()
        self.reserva = Reserva.objects.create(
            uh=self.uh, hospede=Pessoa.objects.create(nome="Teste de permanência"),
            checkin=self.hoje-timedelta(days=1), checkout=self.hoje+timedelta(days=2),
            checkin_real=timezone.now()-timedelta(days=1), status=Reserva.Status.HOSPEDADA,
            valor_diaria=100, criado_por=self.user)


class RotinaAutomaticaTests(CenarioRotina, TestCase):
    def test_respeita_horario_local_configuracao_e_reexecucao_apos_concluir(self):
        antes = timezone.make_aware(datetime.combine(self.hoje, time(5, 59)))
        depois = timezone.make_aware(datetime.combine(self.hoje, time(6)))
        self.assertEqual(services.executar_rotina_diaria(agora=antes)["geradas"], 0)
        self.assertEqual(services.executar_rotina_diaria(agora=depois)["geradas"], 1)
        tarefa = TarefaGovernanca.objects.get(uh=self.uh)
        services.concluir_tarefa(tarefa, self.user)
        services.inspecionar(self.uh, self.user)
        self.assertEqual(services.executar_rotina_diaria(agora=depois)["geradas"], 0)
        self.assertEqual(RotinaLimpezaDiaria.objects.count(), 1)
        self.assertEqual(TarefaGovernanca.objects.count(), 1)
        self.assertTrue(ConfiguracaoGovernanca.get().ultima_execucao)

    def test_desativada_nao_cria_servicos(self):
        config = ConfiguracaoGovernanca.get()
        config.ativa = False
        config.save()
        self.assertEqual(services.executar_rotina_diaria()["geradas"], 0)
        self.assertFalse(TarefaGovernanca.objects.exists())

    def test_chegada_real_hoje_nao_ganha_limpeza_da_permanencia(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(checkin_real=timezone.now())
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 0)

    def test_saida_hoje_e_quarto_bloqueado_nao_entram(self):
        Reserva.objects.filter(pk=self.reserva.pk).update(checkout=self.hoje)
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 0)
        Reserva.objects.filter(pk=self.reserva.pk).update(checkout=self.hoje+timedelta(days=2))
        UH.objects.filter(pk=self.uh.pk).update(status=UH.Status.BLOQUEADA)
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 0)

    def test_servico_concluido_hoje_antes_da_rotina_nao_e_duplicado(self):
        tarefa = services.abrir_faxina(self.uh)
        services.concluir_tarefa(tarefa, self.user)
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 0)
        self.assertEqual(RotinaLimpezaDiaria.objects.get().tarefa_id, tarefa.pk)

    def test_preferencia_bloqueia_inicio_e_expira(self):
        services.gerar_arrumacoes_do_dia()
        tarefa = TarefaGovernanca.objects.get()
        services.registrar_restricao(self.uh, self.user, tipo="nao_perturbe", ate=timezone.now()+timedelta(hours=2))
        with self.assertRaisesMessage(ValidationError, "Não perturbe"):
            services.iniciar_tarefa(tarefa, self.user)
        self.assertEqual(services.quarto(self.uh)["restricao"], "Não perturbe")
        StatusLimpeza.objects.filter(uh=self.uh).update(nao_perturbe_ate=timezone.now()-timedelta(minutes=1))
        services.iniciar_tarefa(tarefa, self.user)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.EM_ANDAMENTO)

    def test_dispensa_tem_validade_diaria_e_checkout_limpa_preferencia(self):
        status = services.registrar_restricao(self.uh, self.user, tipo="dispensa")
        self.assertEqual(status.restricao_ativa, "Limpeza dispensada hoje")
        with patch("django.utils.timezone.localdate", return_value=self.hoje+timedelta(days=1)):
            self.assertEqual(status.restricao_ativa, "")
        services.sujar_apos_ocupacao(self.uh)
        self.assertEqual(services.situacao_uh(self.uh).restricao_ativa, "")

    def test_fila_notifica_sem_expor_hospedes_e_configuracao_exige_gerencia(self):
        self.client.force_login(self.user)
        antes = self.client.get(reverse("governanca:atualizacoes")).json()
        services.gerar_arrumacoes_do_dia()
        resposta = self.client.get(reverse("governanca:atualizacoes"))
        self.assertEqual(resposta.json()["pendentes"], antes["pendentes"]+1)
        self.assertNotContains(resposta, self.reserva.hospede.nome)
        self.assertIn("no-store", resposta["Cache-Control"])
        equipe = get_user_model().objects.create_user(username="equipe")
        equipe.modulos.add(ModuloContratado.objects.get(codigo=Modulo.GOVERNANCA))
        self.client.force_login(equipe)
        self.assertEqual(self.client.get(reverse("governanca:configuracao")).status_code, 403)
        self.assertEqual(self.client.get(reverse("governanca:atualizacoes")).status_code, 200)
        equipe.modulos.clear()
        self.assertEqual(self.client.get(reverse("governanca:atualizacoes")).status_code, 403)

    def test_inspecao_nao_libera_quarto_com_servico_pendente(self):
        tarefa = services.abrir_faxina(self.uh)
        with self.assertRaises(ValidationError):
            services.inspecionar(self.uh, self.user)
        services.concluir_tarefa(tarefa, self.user)
        self.assertFalse(services.uh_pronta_para_checkin(self.uh))
        services.inspecionar(self.uh, self.user)
        self.assertTrue(services.uh_pronta_para_checkin(self.uh))

    def test_atribuicao_obsoleta_e_ids_invalidos_nao_corrompem_tarefa(self):
        tarefa = services.abrir_faxina(self.uh)
        antiga = TarefaGovernanca.objects.get(pk=tarefa.pk)
        services.concluir_tarefa(tarefa, self.user)
        with self.assertRaises(ValidationError):
            services.atribuir_tarefa(antiga, self.user.pk, self.user)
        tarefa.refresh_from_db()
        self.assertEqual(tarefa.status, TarefaGovernanca.Status.CONCLUIDA)
        self.client.force_login(self.user)
        for invalido in ("abc", "1e99", "-1", "9"*30):
            self.assertEqual(self.client.post(reverse("governanca:tarefa_acao", args=[tarefa.pk]), {"acao":"atribuir", "camareira":invalido}).status_code, 302)
            self.assertEqual(self.client.post(reverse("governanca:nova_tarefa"), {"uh":invalido}).status_code, 302)

    def test_preferencia_aparece_na_ficha_e_fila(self):
        tarefa = services.abrir_faxina(self.uh)
        services.atribuir_tarefa(tarefa, self.user.pk)
        services.registrar_restricao(self.uh, self.user, tipo="dispensa")
        self.client.force_login(self.user)
        ficha = self.client.get(reverse("governanca:quarto", args=[self.uh.pk]))
        self.assertContains(ficha, "Limpeza dispensada hoje")
        self.assertContains(ficha, "Salvar preferência")
        self.assertNotContains(ficha, '>Iniciar limpeza</button>')
        self.assertContains(self.client.get(reverse("governanca:minha_fila")), "Limpeza dispensada hoje")


class RotinaConcorrenteTests(CenarioRotina, TransactionTestCase):
    def test_duas_rotinas_geram_uma_tarefa_e_um_marcador(self):
        barreira = Barrier(2)
        def executar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return services.gerar_arrumacoes_do_dia()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: executar(), range(2)))
        self.assertEqual(sorted(resultados), [0, 1])
        self.assertEqual(TarefaGovernanca.objects.count(), 1)
        self.assertEqual(RotinaLimpezaDiaria.objects.count(), 1)
