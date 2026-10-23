import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from apps.nucleo.models import (
    LoteEstoque,
    MovimentoEstoque,
    Produto,
    Usuario,
    registrar_entrada,
    registrar_saida,
    saldo,
    saldo_vendavel,
    salvar_ficha,
)

from .tests_suprimentos import SuprimentosBase


class ConcorrenciaSuprimentosTests(TransactionTestCase):
    def setUp(self):
        SuprimentosBase.setUp(self)

    lote = SuprimentosBase.lote
    entrada = SuprimentosBase.entrada
    prato = SuprimentosBase.prato

    def _duas(self, operacao):
        barreira = threading.Barrier(2)

        def executar():
            close_old_connections()
            try:
                produto = Produto.objects.get(pk=self.produto.pk)
                usuario = Usuario.objects.get(pk=self.user.pk)
                lote = LoteEstoque.objects.get(pk=self.curto.pk)
                barreira.wait(timeout=10)
                try:
                    return operacao(produto, usuario, lote)
                except ValidationError:
                    return "recusado"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(executar), pool.submit(executar)
            return [a.result(timeout=20), b.result(timeout=20)]

    def test_ultima_unidade_do_lote_so_e_vendida_uma_vez(self):
        self.entrada(1)
        resultados = self._duas(lambda p, u, lote: registrar_saida(p, self.local, 1, u).pk)
        self.assertEqual(resultados.count("recusado"), 1)
        self.assertEqual(saldo(self.produto), 0)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 0)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida_venda").count(), 1)

    def test_recebimento_concorrente_com_mesma_chave_cria_um_movimento_e_um_lote(self):
        chave = uuid.uuid4()
        resultados = self._duas(lambda p, u, lote: registrar_entrada(p, self.local, 2, 5, u, lote=lote, chave=chave).pk)
        self.assertEqual(resultados[0], resultados[1])
        self.assertNotIn("recusado", resultados)
        self.assertEqual(saldo(self.produto), 2)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 2)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_ficha_editada_durante_pedido_recusa_composicao_antiga_sem_baixar(self):
        from apps.restaurante import services
        from apps.restaurante.models import Comanda

        self.entrada(2)
        prato = self.prato()
        comanda = services.abrir_comanda(self.user, self.local, rotulo="Disputa QA")
        preparado, continuar = threading.Event(), threading.Event()
        original = services._dados_item

        def aguardar(*args, **kwargs):
            resultado = original(*args, **kwargs)
            preparado.set()
            if not continuar.wait(timeout=10):
                raise AssertionError("A alteração da ficha não terminou.")
            return resultado

        def vender():
            close_old_connections()
            try:
                try:
                    return services.adicionar_item(Comanda.objects.get(pk=comanda.pk),
                        Produto.objects.get(pk=prato.pk), 1, Usuario.objects.get(pk=self.user.pk))
                except ValidationError as erro:
                    return " ".join(erro.messages)
            finally:
                connections.close_all()

        with patch.object(services, "_dados_item", side_effect=aguardar), ThreadPoolExecutor(max_workers=1) as pool:
            futuro = pool.submit(vender)
            try:
                self.assertTrue(preparado.wait(timeout=10))
                salvar_ficha(prato, [(self.produto, Decimal("0.500"))], self.user)
            finally:
                continuar.set()
            resultado = futuro.result(timeout=20)
        self.assertIn("ficha técnica mudou", resultado)
        self.assertEqual(saldo(self.produto), 2)
        self.assertFalse(comanda.itens.exists())
