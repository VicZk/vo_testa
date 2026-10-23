import json
from decimal import Decimal
from unittest.mock import patch
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
    salvar_ficha,
)

from . import services
from .forms import PedidoItemForm
from .models import Comanda, GrupoOpcaoCardapio, InclusaoPedido, OpcaoCardapio
from .tests import RestauranteBase


class IdempotenciaAberturaTests(RestauranteBase):
    def setUp(self):
        super().setUp()
        self.chave = uuid4()
        self.client.force_login(self.op)

    def abrir(self, **dados):
        return services.abrir_comanda(self.op, self.local, **{
            "rotulo": "Guarda-sol 4", "chave_abertura": self.chave, **dados})

    def test_reenvio_http_retorna_mesma_comanda_e_nova_intencao_abre_outra(self):
        url = reverse("restaurante:abrir")
        dados = {"rotulo": "Guarda-sol 4", "chave_abertura": str(self.chave)}
        primeira, repetida = self.client.post(url, dados), self.client.post(url, dados)
        self.assertEqual(primeira.status_code, 302)
        self.assertEqual(primeira["Location"], repetida["Location"])
        self.assertEqual(Comanda.objects.count(), 1)
        nova = self.client.post(url, {**dados, "chave_abertura": str(uuid4())})
        self.assertNotEqual(nova["Location"], primeira["Location"])
        self.assertEqual(Comanda.objects.count(), 2)

    def test_chave_reutilizada_com_identificacao_ponto_ou_operador_diferentes_e_recusada(self):
        original = self.abrir()
        for dados in ({"rotulo": "Guarda-sol 5"}, {"mesa": self.mesa}):
            with self.subTest(dados=dados), self.assertRaisesMessage(ValidationError, "já foi usada"):
                self.abrir(**dados)
        outra_op = Usuario.objects.create_user(username="outro-garcom")
        with self.assertRaisesMessage(ValidationError, "já foi usada"):
            services.abrir_comanda(outra_op, self.local, rotulo=original.rotulo, chave_abertura=self.chave)
        self.assertEqual(Comanda.objects.count(), 1)
        resposta = self.client.post(reverse("restaurante:abrir"), {
            "rotulo": "Guarda-sol 5", "chave_abertura": str(self.chave)}, follow=True)
        self.assertContains(resposta, "já foi usada")
        self.assertEqual(Comanda.objects.get().rotulo, original.rotulo)

    def test_http_exige_chave_valida_e_limita_identificacao(self):
        for chave in ("", "invalida"):
            with self.subTest(chave=chave):
                self.client.post(reverse("restaurante:abrir"), {"rotulo": "Mesa", "chave_abertura": chave})
        resposta = self.client.post(reverse("restaurante:abrir"), {
            "rotulo": "X" * 61, "chave_abertura": str(self.chave)}, follow=True)
        self.assertContains(resposta, "no máximo 60 caracteres")
        self.assertFalse(Comanda.objects.exists())

    def test_pagina_gera_chave_por_abertura_e_a_inclui_no_formulario(self):
        primeira = self.client.get(reverse("restaurante:comandas"))
        segunda = self.client.get(reverse("restaurante:comandas"))
        self.assertContains(primeira, f'name="chave_abertura" value="{primeira.context["chave_abertura"]}"')
        self.assertNotEqual(primeira.context["chave_abertura"], segunda.context["chave_abertura"])

    def test_reenvio_normaliza_identificacao_e_nao_consulta_estadia_novamente(self):
        original = self.abrir(rotulo=" Guarda-sol 4 ")
        with patch("apps.reservas.services.conta_para_pedido") as resolver:
            self.assertEqual(self.abrir().pk, original.pk)
        resolver.assert_not_called()

    def test_reenvio_apos_cancelar_ou_fechar_nao_reabre_comanda(self):
        cancelada = self.abrir()
        services.cancelar_comanda(cancelada, self.op, "Teste de reenvio")
        self.assertEqual(self.abrir().status, "cancelada")
        self.chave = uuid4()
        fechada = self.abrir()
        services.adicionar_item(fechada, self.cerveja, 1, self.op)
        self.abrir_caixa()
        services.fechar_comanda(fechada, self.op, "caixa", forma=self.dinheiro)
        self.assertEqual(self.abrir().status, "fechada")
        self.assertEqual(Comanda.objects.count(), 2)
        self.assertEqual(saldo(self.cerveja, self.local), 19)

    def test_erro_nao_consume_chave_de_abertura(self):
        with self.assertRaises(ValidationError):
            self.abrir(rotulo="")
        self.assertFalse(Comanda.objects.exists())
        self.assertEqual(self.abrir().chave_abertura, self.chave)


class IdempotenciaPedidoTests(RestauranteBase):
    def setUp(self):
        super().setUp()
        self.c = self.comanda()
        self.chave = uuid4()
        self.client.force_login(self.op)

    def incluir(self, **kwargs):
        dados = {"chave_pedido": self.chave, **kwargs}
        return services.adicionar_item(self.c, self.cerveja, dados.pop("quantidade", 1), self.op, **dados)

    def test_reenvio_retorna_mesmo_item_sem_baixar_ou_cobrar_duas_vezes(self):
        original = self.incluir(quantidade="1.000", observacoes=" Sem sal ")
        self.cerveja.preco_venda = Decimal("30")
        self.cerveja.save()
        repetido = self.incluir(quantidade=1, observacoes="Sem sal")
        self.assertEqual(repetido.pk, original.pk)
        self.assertEqual(self.c.total(), Decimal("12"))
        self.assertEqual(saldo(self.cerveja, self.local), 19)
        self.assertEqual(InclusaoPedido.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida_venda").count(), 1)

    def test_chave_com_quantidade_observacao_ou_comanda_diferente_e_recusada(self):
        self.incluir()
        for dados in ({"quantidade": 2}, {"observacoes": "Outra observação"}):
            with self.subTest(dados=dados), self.assertRaisesMessage(ValidationError, "já foi usada"):
                self.incluir(**dados)
        outra = self.comanda()
        with self.assertRaisesMessage(ValidationError, "já foi usada"):
            services.adicionar_item(outra, self.cerveja, 1, self.op, chave_pedido=self.chave)
        self.assertFalse(outra.itens.exists())
        self.assertEqual(saldo(self.cerveja, self.local), 19)

    def test_intencoes_distintas_iguais_somam_e_chave_removida_nao_ressuscita_item(self):
        item = self.incluir()
        self.incluir(chave_pedido=uuid4())
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 2)
        services.remover_item(item, self.op)
        self.assertEqual(saldo(self.cerveja, self.local), 20)
        self.assertEqual(InclusaoPedido.objects.filter(item__isnull=True).count(), 2)
        with self.assertRaisesMessage(ValidationError, "já foi removido"):
            self.incluir()
        self.assertFalse(self.c.itens.exists())
        self.assertEqual(self.incluir(chave_pedido=uuid4()).quantidade, 1)

    def test_falha_de_estoque_nao_consume_chave_e_retry_pode_concluir(self):
        with self.assertRaises(ValidationError):
            self.incluir(quantidade=21)
        self.assertFalse(InclusaoPedido.objects.exists())
        registrar_entrada(self.cerveja, self.local, 1, 4, self.op)
        self.incluir(quantidade=21)
        self.assertEqual(saldo(self.cerveja, self.local), 0)
        self.assertEqual(InclusaoPedido.objects.count(), 1)

    def test_retry_apos_fechamento_ou_cancelamento_nao_reabre_ou_baixa(self):
        item = self.incluir()
        services.cancelar_comanda(self.c, self.op, "Cancelamento para teste")
        self.assertEqual(self.incluir().pk, item.pk)
        self.assertEqual(self.c.status, "cancelada")
        self.assertEqual(saldo(self.cerveja, self.local), 20)
        self.c = self.comanda()
        self.chave = uuid4()
        item = self.incluir()
        self.abrir_caixa()
        services.fechar_comanda(self.c, self.op, "caixa", forma=self.dinheiro)
        self.assertEqual(self.incluir().pk, item.pk)
        self.assertEqual(self.c.status, "fechada")
        self.assertEqual(saldo(self.cerveja, self.local), 19)

    def test_modal_reenvia_opcoes_mesmo_apos_desativacao_do_catalogo(self):
        grupo = GrupoOpcaoCardapio.objects.create(produto=self.cerveja, nome="Escolha", minimo=1)
        opcao = OpcaoCardapio.objects.create(grupo=grupo, nome="Primeira")
        url = reverse("restaurante:pedir_item", args=[self.c.pk, self.cerveja.pk])
        dados = {"chave_pedido": str(self.chave), "quantidade": "1", f"grupo_{grupo.pk}": str(opcao.pk)}
        primeiro = self.client.post(url, dados, HTTP_HX_REQUEST="true")
        self.assertEqual(primeiro["HX-Retarget"], "#comanda-itens")
        Produto.objects.filter(pk=self.cerveja.pk).update(ativo=False)
        OpcaoCardapio.objects.filter(pk=opcao.pk).update(ativo=False)
        repetido = self.client.post(url, dados, HTTP_HX_REQUEST="true")
        self.assertEqual(repetido["HX-Retarget"], "#comanda-itens")
        self.assertEqual(self.c.itens.get().quantidade, 1)
        self.assertEqual(saldo(self.cerveja, self.local), 19)
        conflito = self.client.post(url, {**dados, "quantidade": 2}, HTTP_HX_REQUEST="true")
        self.assertContains(conflito, "já foi usada")
        self.assertNotIn("pedidoSalvo", json.loads(conflito["HX-Trigger-After-Swap"]))

    def test_rotas_http_recusam_chave_ausente_invalida_e_form_preserva_chave(self):
        url = reverse("restaurante:pedir_item", args=[self.c.pk, self.cerveja.pk])
        for chave in ("", "invalida"):
            for rota, dados in ((url, {"quantidade": 1}),
                                (reverse("restaurante:add_item", args=[self.c.pk]), {"produto_id": self.cerveja.pk})):
                with self.subTest(chave=chave, rota=rota):
                    self.assertEqual(self.client.post(rota, {**dados, "chave_pedido": chave}).status_code, 200)
        self.assertFalse(self.c.itens.exists())
        resposta = self.client.post(url, {"quantidade": 0, "chave_pedido": str(self.chave)})
        self.assertEqual(resposta.context["form"]["chave_pedido"].value(), str(self.chave))
        a, b = PedidoItemForm(produto=self.cerveja), PedidoItemForm(produto=self.cerveja)
        self.assertNotEqual(a["chave_pedido"].value(), b["chave_pedido"].value())

    def test_catalogo_htmx_atualiza_todos_os_pratos_que_compartilham_ingrediente(self):
        prato = Produto.objects.create(nome="Prato", categoria=self.cerveja.categoria,
                                       preco_venda=20, usa_ficha_tecnica=True)
        salvar_ficha(prato, [(self.cerveja, 2)], self.op)
        url = reverse("restaurante:pedir_item", args=[self.c.pk, self.cerveja.pk])
        resposta = self.client.post(url, {"quantidade": 2, "chave_pedido": str(self.chave)}, HTTP_HX_REQUEST="true")
        eventos = json.loads(resposta["HX-Trigger-After-Swap"])
        self.assertTrue(eventos["pedidoSalvo"])
        self.assertEqual(eventos["restauranteEstoque"]["comanda"], self.c.pk)
        self.assertEqual(Decimal(eventos["restauranteEstoque"]["saldos"][str(prato.pk)]), 9)
        item = self.c.itens.get()
        remover = self.client.post(reverse("restaurante:remover_item", args=[self.c.pk, item.pk]), HTTP_HX_REQUEST="true")
        eventos = json.loads(remover["HX-Trigger-After-Swap"])
        self.assertNotIn("pedidoSalvo", eventos)
        self.assertEqual(Decimal(eventos["restauranteEstoque"]["saldos"][str(prato.pk)]), 10)


class CancelamentoPermissaoTests(RestauranteBase):
    def test_staff_sem_modulo_nao_cancela_nem_devolve_estoque(self):
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 1, self.op)
        staff = Usuario.objects.create_user(username="staff-sem-restaurante", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(reverse("restaurante:cancelar", args=[c.pk]), {"motivo": "Teste"}).status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.status, "aberta")
        self.assertEqual(saldo(self.cerveja, self.local), 19)

    def test_modulo_desativado_nao_permite_cancelamento_nem_com_superusuario(self):
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 1, self.op)
        ModuloContratado.objects.filter(codigo="restaurante").update(ativo=False)
        self.client.force_login(self.op)
        self.assertEqual(self.client.post(reverse("restaurante:cancelar", args=[c.pk]), {"motivo": "Teste"}).status_code, 404)
        c.refresh_from_db()
        self.assertEqual(c.status, "aberta")
        self.assertEqual(saldo(self.cerveja, self.local), 19)
