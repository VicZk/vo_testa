import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    LocalEstoque,
    ModuloContratado,
    MovimentoEstoque,
    Pessoa,
    Produto,
    TipoUH,
    Usuario,
    registrar_entrada,
    saldo,
)
from apps.portal import services as portal
from apps.portal.models import SolicitacaoPortal
from apps.reservas.models import Reserva

from . import services
from .models import Comanda, InclusaoPedido


@skipUnless(connection.vendor == "postgresql", "Concorrência validada com travas reais do PostgreSQL.")
@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class ConcorrenciaPedidosTests(TransactionTestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="concorrencia-pedidos", password="senha-forte-123")
        self.cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        self.produto = Produto.objects.create(nome="Água", categoria=self.cat, preco_venda=6)
        registrar_entrada(self.produto, self.local, 20, 2, self.op)
        self.comanda = services.abrir_comanda(self.op, self.local, rotulo="Mesa de teste")
        self.chave = uuid4()
        for codigo in ("restaurante", "reservas", "estoque"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})

    def _duas(self, operacao):
        barreira = threading.Barrier(2)

        def executar(indice):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                try:
                    return operacao(indice)
                except ValidationError as erro:
                    return " ".join(erro.messages)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, indice) for indice in range(2)]
            return [futuro.result(timeout=25) for futuro in futuros]

    def _incluir(self, *, chave=None, quantidade=1, comanda_id=None, produto_id=None):
        return services.adicionar_item(
            Comanda.objects.get(pk=comanda_id or self.comanda.pk),
            Produto.objects.get(pk=produto_id or self.produto.pk), quantidade,
            Usuario.objects.get(pk=self.op.pk), chave_pedido=chave or self.chave,
        ).pk

    def _abrir_simultaneamente(self, *, diferentes=False):
        # Força ambas as transações além da consulta inicial para exercitar a UNIQUE.
        pronta_para_criar = threading.Barrier(2)

        def sem_estadia(**kwargs):
            pronta_para_criar.wait(timeout=10)
            return None

        with patch("apps.reservas.services.conta_para_pedido", side_effect=sem_estadia):
            return self._duas(lambda indice: services.abrir_comanda(
                Usuario.objects.get(pk=self.op.pk), LocalEstoque.objects.get(pk=self.local.pk),
                rotulo=f"Mesa {indice if diferentes else 1}", chave_abertura=self.chave).pk)

    def test_abertura_concorrente_com_mesma_chave_cria_uma_comanda(self):
        resultados = self._abrir_simultaneamente()
        self.assertIsInstance(resultados[0], int)
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(Comanda.objects.filter(chave_abertura=self.chave).count(), 1)
        self.assertEqual(Comanda.objects.count(), 2)  # Inclui a comanda do setUp.

    def test_abertura_concorrente_com_dados_diferentes_recusa_uma_intencao(self):
        resultados = self._abrir_simultaneamente(diferentes=True)
        self.assertEqual(sum(isinstance(resultado, int) for resultado in resultados), 1)
        self.assertTrue(any("já foi usada" in str(resultado) for resultado in resultados))
        self.assertEqual(Comanda.objects.filter(chave_abertura=self.chave).count(), 1)
        self.assertEqual(Comanda.objects.count(), 2)

    def test_mesma_chave_e_conteudo_concorrentes_produzem_uma_inclusao(self):
        resultados = self._duas(lambda _: self._incluir())
        self.assertIsInstance(resultados[0], int)
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(self.comanda.itens.get().quantidade, 1)
        self.assertEqual(saldo(self.produto, self.local), 19)
        self.assertEqual(InclusaoPedido.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida_venda").count(), 1)

    def test_mesma_chave_com_conteudo_diferente_recusa_uma_operacao(self):
        resultados = self._duas(lambda indice: self._incluir(quantidade=indice + 1))
        self.assertEqual(sum(isinstance(resultado, int) for resultado in resultados), 1)
        self.assertTrue(any("já foi usada" in str(resultado) for resultado in resultados))
        item = self.comanda.itens.get()
        self.assertIn(item.quantidade, (1, 2))
        self.assertEqual(saldo(self.produto, self.local), Decimal("20") - item.quantidade)
        self.assertEqual(InclusaoPedido.objects.count(), 1)

    def test_chaves_distintas_preservam_dois_pedidos_iguais(self):
        chaves = [uuid4(), uuid4()]
        resultados = self._duas(lambda indice: self._incluir(chave=chaves[indice]))
        self.assertTrue(all(isinstance(resultado, int) for resultado in resultados))
        self.assertEqual(self.comanda.itens.get().quantidade, 2)
        self.assertEqual(saldo(self.produto, self.local), 18)
        self.assertEqual(InclusaoPedido.objects.count(), 2)

    def test_chave_disputada_por_comandas_distintas_reverte_estoque_da_perdedora(self):
        outra = services.abrir_comanda(self.op, self.local, rotulo="Outra mesa")
        outro_produto = Produto.objects.create(nome="Suco", categoria=self.cat, preco_venda=8)
        registrar_entrada(outro_produto, self.local, 20, 3, self.op)
        comandas = [self.comanda.pk, outra.pk]
        produtos = [self.produto.pk, outro_produto.pk]
        baixas_prontas = threading.Barrier(2)
        registrar = services._registrar_baixas

        def aguardar_inclusao(*args, **kwargs):
            movimentos = registrar(*args, **kwargs)
            baixas_prontas.wait(timeout=10)
            return movimentos

        with patch.object(services, "_registrar_baixas", side_effect=aguardar_inclusao):
            resultados = self._duas(lambda indice: self._incluir(
                comanda_id=comandas[indice], produto_id=produtos[indice]))
        self.assertEqual(sum(isinstance(resultado, int) for resultado in resultados), 1)
        self.assertTrue(any("já foi usada" in str(resultado) for resultado in resultados))
        self.assertEqual(InclusaoPedido.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida_venda").count(), 1)
        self.assertEqual(saldo(self.produto, self.local) + saldo(outro_produto, self.local), 39)

    def _estadia(self):
        tipo = TipoUH.objects.create(nome="Standard", tarifa_base=200)
        uh = UH.objects.create(numero="01", tipo=tipo)
        pessoa = Pessoa.objects.create(nome="Hóspede fictício")
        hoje = timezone.localdate()
        reserva = Reserva.objects.create(uh=uh, hospede=pessoa, checkin=hoje,
            checkout=hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=200, criado_por=self.op)
        reserva.fazer_checkin(self.op)
        return portal.resolver(portal.get_acesso(reserva.pk).token)

    def test_portal_mesmo_carrinho_concorrente_abre_uma_comanda(self):
        estadia = self._estadia()
        resultados = self._duas(lambda _: portal.pedir_restaurante(
            estadia, [(self.produto.pk, 2)], chave_pedido=self.chave).pk)
        self.assertIsInstance(resultados[0], int)
        self.assertEqual(resultados[0], resultados[1])
        self.assertEqual(Comanda.objects.filter(conta__reserva_id=estadia["reserva_id"]).count(), 1)
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
        self.assertEqual(saldo(self.produto, self.local), 18)

    def test_portal_mesma_chave_com_carrinhos_distintos_recusa_um(self):
        estadia = self._estadia()
        resultados = self._duas(lambda indice: portal.pedir_restaurante(
            estadia, [(self.produto.pk, indice + 1)], chave_pedido=self.chave).pk)
        self.assertEqual(sum(isinstance(resultado, int) for resultado in resultados), 1)
        self.assertTrue(any("já foi usada" in str(resultado) for resultado in resultados))
        comanda = Comanda.objects.get(conta__reserva_id=estadia["reserva_id"])
        self.assertEqual(saldo(self.produto, self.local), 20 - comanda.itens.get().quantidade)
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
