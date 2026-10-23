from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.nucleo.models import (
    ModuloContratado,
    MovimentoEstoque,
    Produto,
    Usuario,
    registrar_entrada,
    saldo,
)

from . import services
from .forms import PedidoItemForm
from .models import GrupoOpcaoCardapio, ItemComanda, OpcaoCardapio
from .tests import RestauranteBase


class PedidoPersonalizadoTests(RestauranteBase):
    def setUp(self):
        super().setUp()
        self.grupo = GrupoOpcaoCardapio.objects.create(produto=self.cerveja, nome="Ponto da carne", minimo=1)
        self.ponto = OpcaoCardapio.objects.create(grupo=self.grupo, nome="Ao ponto")
        self.bem = OpcaoCardapio.objects.create(grupo=self.grupo, nome="Bem passada")
        self.extra = GrupoOpcaoCardapio.objects.create(produto=self.cerveja, nome="Adicionais", maximo=2)
        self.ingrediente = Produto.objects.create(nome="Queijo", categoria=self.cerveja.categoria)
        registrar_entrada(self.ingrediente, self.local, 10, 2, self.op)
        self.queijo = OpcaoCardapio.objects.create(grupo=self.extra, nome="Queijo extra", adicional=Decimal("5"),
            produto_estoque=self.ingrediente, quantidade_estoque=Decimal("0.100"))
        self.c = self.comanda()

    def pedido(self, *, quantidade=1, nota="Sem sal", escolhas=None):
        return services.adicionar_item(self.c, self.cerveja, quantidade, self.op, observacoes=nota,
                                       opcoes=escolhas if escolhas is not None else [self.ponto.pk, self.queijo.pk])

    def test_observacoes_ponto_adicional_precos_e_estoque_por_item(self):
        item = self.pedido(quantidade=2)
        self.assertEqual(item.preco_unitario, Decimal("17"))
        self.assertEqual(item.subtotal, Decimal("34"))
        self.assertEqual(saldo(self.cerveja, self.local), Decimal("18"))
        self.assertEqual(saldo(self.ingrediente, self.local), Decimal("9.8"))
        diferente = self.pedido(escolhas=[self.bem.pk])
        self.pedido()
        item.refresh_from_db()
        self.assertEqual(self.c.itens.count(), 2)
        self.assertEqual(item.quantidade, 3)
        self.assertEqual(diferente.resumo_opcoes, "Ponto da carne: Bem passada")
        self.client.force_login(self.op)
        for nome in ("comanda", "cupom"):
            resposta = self.client.get(reverse(f"restaurante:{nome}", args=[self.c.pk]))
            self.assertContains(resposta, "Ao ponto")
            self.assertContains(resposta, "Queijo extra")
            self.assertContains(resposta, "Sem sal")
        self.assertContains(self.client.get(reverse("restaurante:cozinha")), "Sem sal")

    def test_limites_opcoes_estranhas_e_numeros_invalidos_nao_baixam_estoque(self):
        for escolhas in ([], [self.ponto.pk, self.bem.pk], [self.ponto.pk, 999999],
                         [self.ponto.pk, self.ponto.pk], ["NaN"]):
            with self.subTest(escolhas=escolhas), self.assertRaises(ValidationError):
                self.pedido(escolhas=escolhas)
        for quantidade in ("NaN", "Infinity", "1e9999", "-1", "0", "0.0001"):
            with self.subTest(quantidade=quantidade), self.assertRaises(ValidationError):
                self.pedido(quantidade=quantidade)
        self.assertFalse(self.c.itens.exists())
        self.assertEqual(saldo(self.cerveja, self.local), 20)

    def test_edicao_preserva_preco_original_e_nao_aceita_versao_antiga(self):
        item = self.pedido()
        self.cerveja.preco_venda = Decimal("30")
        self.cerveja.save()
        self.queijo.adicional = Decimal("20")
        self.queijo.save()
        services.editar_item(item, self.op, versao=1, quantidade=2, observacoes="Molho à parte",
                             opcoes=[self.ponto.pk, self.queijo.pk])
        item.refresh_from_db()
        self.assertEqual(item.preco_unitario, Decimal("17"))
        self.assertEqual(item.quantidade, 2)
        self.assertEqual(saldo(self.ingrediente, self.local), Decimal("9.8"))
        with self.assertRaisesMessage(ValidationError, "Outro atendente"):
            services.editar_item(item, self.op, versao=1, quantidade=4, opcoes=[self.bem.pk])
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 2)
        self.assertEqual(item.observacoes, "Molho à parte")

    def test_edicao_sem_estoque_reverte_todas_as_movimentacoes(self):
        item = self.pedido()
        movimentos = MovimentoEstoque.objects.count()
        with self.assertRaises(ValidationError):
            services.editar_item(item, self.op, versao=1, quantidade=25, opcoes=[self.ponto.pk, self.queijo.pk])
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 1)
        self.assertEqual(item.versao, 1)
        self.assertEqual(MovimentoEstoque.objects.count(), movimentos)

    def test_preparo_bloqueia_edicao_e_cancelamento_registra_perda(self):
        item = self.pedido()
        services.alterar_preparo(item, "preparando", self.op, versao=1)
        item.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "cozinha já iniciou"):
            services.editar_item(item, self.op, versao=2, quantidade=2, opcoes=[self.bem.pk])
        atendente = Usuario.objects.create_user(username="atendente")
        with self.assertRaises(ValidationError):
            services.remover_item(item, atendente, "Desistência")
        with self.assertRaises(ValidationError):
            services.remover_item(item, self.op)
        services.remover_item(item, self.op, "Desistência após início")
        self.assertEqual(saldo(self.cerveja, self.local), 19)
        self.assertEqual(saldo(self.ingrediente, self.local), Decimal("9.9"))
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="perda").count(), 2)

    def test_dupla_remocao_nao_duplica_devolucao_nem_de_adicionais(self):
        item = self.pedido()
        antiga = ItemComanda.objects.get(pk=item.pk)
        services.remover_item(item, self.op)
        with self.assertRaises(ValidationError):
            services.remover_item(antiga, self.op)
        self.assertEqual(saldo(self.ingrediente, self.local), 10)
        self.assertEqual(saldo(self.cerveja, self.local), 20)

    def test_cozinha_mantem_pedido_pago_ate_entregar(self):
        self.abrir_caixa()
        item = self.pedido()
        services.fechar_comanda(self.c, self.op, "caixa", forma=self.dinheiro)
        self.client.force_login(self.op)
        self.assertContains(self.client.get(reverse("restaurante:cozinha")), "Queijo extra")
        for estado, versao in (("preparando", 1), ("pronto", 2), ("entregue", 3)):
            services.alterar_preparo(item, estado, self.op, versao=versao)
        self.assertNotContains(self.client.get(reverse("restaurante:cozinha")), "Queijo extra")
        with self.assertRaises(ValidationError):
            services.alterar_preparo(item, "preparando", self.op, versao=4)

    def test_modal_valida_e_exibe_erros_sem_perder_observacao(self):
        self.client.force_login(self.op)
        url = reverse("restaurante:pedir_item", args=[self.c.pk, self.cerveja.pk])
        resposta = self.client.post(url, {"quantidade": 1, "observacoes": "Sem sal"}, HTTP_HX_REQUEST="true")
        self.assertContains(resposta, "Este campo é obrigatório")
        self.assertContains(resposta, "Sem sal")
        self.assertFalse(self.c.itens.exists())
        resposta = self.client.post(url, {"quantidade": 1, "observacoes": "Sem sal",
                                         "chave_pedido": str(uuid4()),
                                         f"grupo_{self.grupo.pk}": self.ponto.pk}, HTTP_HX_REQUEST="true")
        self.assertEqual(resposta["HX-Retarget"], "#comanda-itens")
        self.assertEqual(self.c.itens.get().observacoes, "Sem sal")

    def test_formulario_restaura_escolhas_e_quantidade_ao_editar(self):
        item = self.pedido(quantidade=2)
        form = PedidoItemForm(produto=self.cerveja, item=item)
        self.assertEqual(form.initial[f"grupo_{self.grupo.pk}"], str(self.ponto.pk))
        self.assertEqual(form.initial[f"grupo_{self.extra.pk}"], [str(self.queijo.pk)])
        self.assertEqual(form.initial["quantidade"], 2)

    def test_configuracao_restrita_e_formulario_invalido_nao_grava_grupo(self):
        atendente = Usuario.objects.create_user(username="garcom-pedidos")
        atendente.modulos.add(ModuloContratado.objects.get(codigo="restaurante"))
        self.client.force_login(atendente)
        self.assertEqual(self.client.get(reverse("restaurante:cardapio_config")).status_code, 403)
        self.client.force_login(self.op)
        url = reverse("restaurante:cardapio_produto", args=[self.cerveja.pk])
        self.assertContains(self.client.get(url), "Ponto da carne")
        resposta = self.client.post(url, {"nome": "Inválido", "minimo": 3, "maximo": 1, "ordem": 0, "ativo": "on",
            "opcoes-TOTAL_FORMS": 0, "opcoes-INITIAL_FORMS": 0})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(GrupoOpcaoCardapio.objects.filter(nome="Inválido").exists())

    def test_http_invalidos_deixam_comanda_intacta(self):
        self.client.force_login(self.op)
        for rota, dados in (("add_item", {"produto_id": "NaN"}), ("fechar", {"desconto": "Infinity"}),
                            ("transferir", {"mesa": "1e9999"})):
            with self.subTest(rota=rota):
                self.assertLess(self.client.post(reverse(f"restaurante:{rota}", args=[self.c.pk]), dados).status_code, 500)
        self.assertFalse(self.c.itens.exists())
