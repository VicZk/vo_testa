from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    LoteEstoque,
    Produto,
    registrar_entrada,
    saldo,
    salvar_ficha,
)
from apps.restaurante import services as restaurante
from apps.restaurante.models import Comanda

from . import services
from .models import SolicitacaoPortal
from .tests import PortalBase


class PedidoRestaurantePortalTests(PortalBase):
    def setUp(self):
        super().setUp()
        self.cat = CategoriaProduto.objects.create(nome="Cardápio")
        self.local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        self.agua = Produto.objects.create(nome="Água", categoria=self.cat, preco_venda=Decimal("6"))
        registrar_entrada(self.agua, self.local, 10, 2, self.op)
        self.chave = uuid4()

    def pedir(self, pedidos=None, **kwargs):
        return services.pedir_restaurante(self.estadia, pedidos or [(self.agua.pk, 2)],
                                          **{"chave_pedido": self.chave, **kwargs})

    def test_cardapio_considera_ficha_e_validade_dos_ingredientes(self):
        leite = Produto.objects.create(nome="Leite", categoria=self.cat, unidade="l", controla_validade=True)
        lote = LoteEstoque.objects.create(produto=leite, codigo="LEITE", validade=timezone.localdate() + timedelta(days=1), criado_por=self.op)
        registrar_entrada(leite, self.local, 2, 5, self.op, lote=lote)
        cafe = Produto.objects.create(nome="Café com leite", categoria=self.cat, preco_venda=12, usa_ficha_tecnica=True)
        salvar_ficha(cafe, [(leite, Decimal("0.200"))], self.op)
        self.assertIn(cafe.pk, [item["id"] for item in services.cardapio()])
        c = self.pedir([(cafe.pk, 1)])
        self.assertEqual(c.total(), 12)
        self.assertEqual(saldo(leite, self.local), Decimal("1.800"))
        with patch("django.utils.timezone.localdate", return_value=lote.validade + timedelta(days=1)):
            self.assertNotIn(cafe.pk, [item["id"] for item in services.cardapio()])
        self.assertEqual(saldo(leite, self.local), Decimal("1.800"))

    def test_cardapio_oculta_produto_com_saldo_apenas_vencido(self):
        suco = Produto.objects.create(nome="Suco", categoria=self.cat, preco_venda=8, controla_validade=True)
        lote = LoteEstoque.objects.create(produto=suco, codigo="SUCO", validade=timezone.localdate() + timedelta(days=1), criado_por=self.op)
        registrar_entrada(suco, self.local, 3, 3, self.op, lote=lote)
        with patch("django.utils.timezone.localdate", return_value=lote.validade + timedelta(days=1)):
            self.assertNotIn(suco.pk, [item["id"] for item in services.cardapio()])
        self.assertEqual(saldo(suco, self.local), 3)

    def test_retry_nao_cria_comanda_solicitacao_ou_baixa_duplicada(self):
        original = self.pedir()
        Produto.objects.filter(pk=self.agua.pk).update(ativo=False, preco_venda=10)
        self.assertEqual(self.pedir().pk, original.pk)
        self.assertEqual(Comanda.objects.count(), 1)
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
        self.assertEqual(saldo(self.agua, self.local), 8)
        self.assertEqual(original.total(), 12)

    def test_chave_com_conteudo_diferente_recusa_e_nova_chave_cria_outro_pedido(self):
        original = self.pedir()
        with self.assertRaisesMessage(ValidationError, "já foi usada"):
            self.pedir([(self.agua.pk, 3)])
        nova = self.pedir(chave_pedido=uuid4())
        self.assertNotEqual(nova.pk, original.pk)
        self.assertEqual(saldo(self.agua, self.local), 6)

    def test_mesmo_carrinho_em_outra_ordem_e_mesmo_pedido(self):
        outro = Produto.objects.create(nome="Refrigerante", categoria=self.cat, preco_venda=8)
        registrar_entrada(outro, self.local, 5, 3, self.op)
        original = self.pedir([(self.agua.pk, 1), (outro.pk, 2)])
        self.assertEqual(self.pedir([(outro.pk, 2), (self.agua.pk, 1)]).pk, original.pk)
        self.assertEqual(saldo(outro, self.local), 3)

    def test_remover_ou_cancelar_nao_libera_chave_antiga(self):
        original = self.pedir()
        restaurante.remover_item(original.itens.get(), self.op)
        self.assertEqual(self.pedir().pk, original.pk)
        self.assertFalse(original.itens.exists())
        self.assertEqual(saldo(self.agua, self.local), 10)
        restaurante.cancelar_comanda(original, self.op, "Teste de retransmissão")
        self.assertEqual(self.pedir().pk, original.pk)
        self.assertEqual(saldo(self.agua, self.local), 10)

    def test_pedido_sem_estoque_reverte_chave_comanda_e_solicitacao(self):
        with self.assertRaises(ValidationError):
            self.pedir([(self.agua.pk, 11)])
        self.assertFalse(Comanda.objects.exists())
        self.assertFalse(SolicitacaoPortal.objects.exists())
        registrar_entrada(self.agua, self.local, 1, 2, self.op)
        self.pedir([(self.agua.pk, 11)])
        self.assertEqual(saldo(self.agua, self.local), 0)

    def test_http_exige_chave_preserva_erro_e_retry_nao_duplica(self):
        token = services.get_acesso(self.reserva.pk).token
        url = reverse("portal:pedir", args=[token])
        dados = {f"qtd_{self.agua.pk}": "2"}
        for chave in ("", "invalida"):
            resposta = self.client.post(url, {**dados, "chave_pedido": chave})
            self.assertEqual(resposta.status_code, 200)
        self.assertFalse(Comanda.objects.exists())
        erro = self.client.post(url, {f"qtd_{self.agua.pk}": "21", "chave_pedido": str(self.chave)})
        self.assertEqual(erro.context["chave_pedido"], str(self.chave))
        for _ in range(2):
            self.assertEqual(self.client.post(url, {**dados, "chave_pedido": str(self.chave)}).status_code, 302)
        self.assertEqual(Comanda.objects.count(), 1)
        self.assertEqual(saldo(self.agua, self.local), 8)

    def _cardapio_com_101_produtos(self):
        extras = Produto.objects.bulk_create([
            Produto(nome=f"Produto do cardápio QA {i:03}", categoria=self.cat, preco_venda=6)
            for i in range(100)
        ])
        for produto in extras:
            registrar_entrada(produto, self.local, 2, 2, self.op)
        return [self.agua, *extras]

    def test_formulario_com_101_produtos_aceita_um_escolhido_e_100_zeros(self):
        produtos = self._cardapio_com_101_produtos()
        token = services.get_acesso(self.reserva.pk).token
        pagina = self.client.get(reverse("portal:home", args=[token]))
        self.assertEqual(len(pagina.context["cardapio"]), 101)
        dados = {f"qtd_{produto.pk}": "0" for produto in produtos}
        dados.update({f"qtd_{self.agua.pk}": "1", "chave_pedido": str(pagina.context["chave_pedido"])})
        resposta = self.client.post(reverse("portal:pedir", args=[token]), dados)
        self.assertEqual(resposta.status_code, 302)
        comanda = Comanda.objects.get()
        item = comanda.itens.get()
        self.assertEqual((item.produto_id, item.quantidade), (self.agua.pk, 1))
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
        self.assertEqual(saldo(self.agua, self.local), 9)
        self.assertEqual(saldo(produtos[-1], self.local), 2)

    def test_formulario_com_101_produtos_escolhidos_recusa_sem_consumir_estoque(self):
        produtos = self._cardapio_com_101_produtos()
        token = services.get_acesso(self.reserva.pk).token
        dados = {f"qtd_{produto.pk}": "1" for produto in produtos}
        dados["chave_pedido"] = str(self.chave)
        resposta = self.client.post(reverse("portal:pedir", args=[token]), dados)
        self.assertContains(resposta, "Até 100 itens por pedido")
        self.assertFalse(Comanda.objects.exists())
        self.assertFalse(SolicitacaoPortal.objects.exists())
        self.assertEqual(saldo(self.agua, self.local), 10)
        self.assertTrue(all(saldo(produto, self.local) == 2 for produto in produtos[1:]))
