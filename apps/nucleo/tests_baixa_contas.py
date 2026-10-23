"""A baixa preserva integridade mesmo com uma tela antiga ou uma falha no banco."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import CategoriaFinanceira, ContaPagarReceber, LancamentoFinanceiro, Usuario


class _DadosBaixa:
    def setUp(self):
        super().setUp()
        self.op = Usuario.objects.create_user(username="baixa-conta", password="forte-123-abc")
        self.categoria = CategoriaFinanceira.objects.create(nome="Receita teste", tipo="receita")
        self.conta = ContaPagarReceber.objects.create(
            tipo="receber", categoria=self.categoria, descricao="Hospedagem fictícia",
            valor=Decimal("99.50"), vencimento=timezone.localdate())


class BaixaContasTests(_DadosBaixa, TestCase):
    def test_instancia_anterior_nao_baixa_conta_outra_vez(self):
        antiga = ContaPagarReceber.objects.get(pk=self.conta.pk)
        self.conta.baixar(self.op)
        with self.assertRaisesMessage(ValidationError, "Só contas abertas"):
            antiga.baixar(self.op)
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_descricao_no_limite_continua_permitindo_baixa(self):
        self.conta.descricao = "a" * 200
        self.conta.save(update_fields=["descricao"])
        lancamento = self.conta.baixar(self.op)
        self.assertEqual(lancamento.valor, Decimal("99.50"))
        self.assertLessEqual(len(lancamento.descricao), 200)
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.descricao, "a" * 200)

    def test_falha_ao_salvar_conta_nao_deixa_lancamento_solto(self):
        with patch.object(ContaPagarReceber, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaisesMessage(RuntimeError, "falha simulada"):
                self.conta.baixar(self.op)
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.status, "aberta")
        self.assertIsNone(self.conta.lancamento_id)
        self.assertFalse(LancamentoFinanceiro.objects.exists())


class BaixaContasConcorrenciaTests(_DadosBaixa, TransactionTestCase):
    def test_duas_telas_baixam_uma_vez(self):
        barreira = Barrier(2)

        def baixar():
            close_old_connections()
            try:
                conta = ContaPagarReceber.objects.get(pk=self.conta.pk)
                operador = Usuario.objects.get(pk=self.op.pk)
                barreira.wait(timeout=5)
                try:
                    conta.baixar(operador)
                    return "baixada"
                except ValidationError:
                    return "recusada"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: baixar(), range(2)))
        self.assertCountEqual(resultados, ["baixada", "recusada"])
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.status, "baixada")
