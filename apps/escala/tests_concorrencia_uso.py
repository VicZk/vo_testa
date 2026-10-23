"""Solicitar e aprovar a mesma atribuição usam uma ordem consistente de locks."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.nucleo import sistema
from apps.nucleo.models import Funcionario, Pessoa, Usuario

from . import services
from .models import Atribuicao, TrocaTurno, Turno


class TrocaConcorrenteTests(TransactionTestCase):
    def test_solicitacao_e_aprovacao_concorrentes_nao_entram_em_deadlock(self):
        if connection.vendor != "postgresql":
            self.skipTest("O cenário verifica locks reais do PostgreSQL.")
        usuario = Usuario.objects.create_user(username="concorrencia-escala")
        funcionarios = [Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=f"Equipe QA {n}"))
                        for n in range(3)]
        turno = Turno.objects.create(nome="Concorrência QA", inicio=time(8), fim=time(16))
        atribuicao = services.atribuir(turno, funcionarios[0], timezone.localdate() + timedelta(days=7), usuario)
        primeira = services.solicitar_troca(atribuicao, funcionarios[1], "Pedido anterior")
        solicitacao_travou = threading.Event()
        decisao_aguarda_atribuicao = threading.Event()
        contexto = threading.local()
        travar_original = sistema.travar

        def travar_com_intercalacao(objeto):
            if isinstance(objeto, Atribuicao) and getattr(contexto, "papel", "") == "solicitar":
                resultado = travar_original(objeto)
                solicitacao_travou.set()
                # Quando a decisão já aguarda os funcionários, a solicitação pode
                # terminar normalmente ao fim deste intervalo. Antes da correção,
                # ela segurava só a atribuição e a decisão chegava até a outra ponta.
                decisao_aguarda_atribuicao.wait(2)
                return resultado
            if isinstance(objeto, Atribuicao) and getattr(contexto, "papel", "") == "decidir":
                decisao_aguarda_atribuicao.set()
            return travar_original(objeto)

        def executar(papel):
            close_old_connections()
            contexto.papel = papel
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                if papel == "solicitar":
                    services.solicitar_troca(Atribuicao.objects.get(pk=atribuicao.pk),
                                            Funcionario.objects.get(pk=funcionarios[2].pk), "Pedido concorrente")
                else:
                    services.decidir_troca(TrocaTurno.objects.get(pk=primeira.pk),
                                          Usuario.objects.get(pk=usuario.pk), True)
                return "ok"
            except Exception as erro:
                return f"{type(erro).__name__}: {erro}"
            finally:
                connection.close()

        with patch.object(sistema, "travar", side_effect=travar_com_intercalacao), ThreadPoolExecutor(max_workers=2) as pool:
            solicitar = pool.submit(executar, "solicitar")
            self.assertTrue(solicitacao_travou.wait(5), "A solicitação não alcançou a atribuição.")
            decidir = pool.submit(executar, "decidir")
            resultados = [solicitar.result(timeout=10), decidir.result(timeout=10)]
        self.assertEqual(resultados, ["ok", "ok"])
        atribuicao.refresh_from_db()
        primeira.refresh_from_db()
        self.assertEqual(atribuicao.funcionario_id, funcionarios[1].pk)
        self.assertEqual(primeira.status, TrocaTurno.Status.APROVADA)
        self.assertEqual(TrocaTurno.objects.filter(status=TrocaTurno.Status.PENDENTE).count(), 1)


class SolicitacaoEnvelhecidaTests(TestCase):
    def test_atribuicao_envelhecida_nao_gera_pedido_em_nome_do_novo_funcionario(self):
        usuario = Usuario.objects.create_user(username="solicitacao-escala")
        funcionarios = [Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=f"Equipe QA {n}"))
                        for n in range(3)]
        turno = Turno.objects.create(nome="Snapshot QA", inicio=time(8), fim=time(16))
        atribuicao = services.atribuir(turno, funcionarios[0], timezone.localdate() + timedelta(days=7), usuario)
        snapshot = Atribuicao.objects.get(pk=atribuicao.pk)
        primeira = services.solicitar_troca(atribuicao, funcionarios[1], "Pedido aprovado")
        services.decidir_troca(primeira, usuario, True)
        with self.assertRaisesMessage(ValidationError, "já mudou de funcionário"):
            services.solicitar_troca(snapshot, funcionarios[2], "Pedido com dados antigos")
        self.assertEqual(TrocaTurno.objects.count(), 1)
        atribuicao.refresh_from_db()
        self.assertEqual(atribuicao.funcionario_id, funcionarios[1].pk)
