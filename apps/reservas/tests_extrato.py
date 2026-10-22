from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    ModuloContratado,
    Produto,
    registrar_entrada,
)

from . import services
from .extrato import dados_extrato
from .models import LancamentoConta
from .tests import ReservasTestsBase


@override_settings(PRECO_TAXAS_ATIVAS=False)
class ExtratoHospedagemTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        for codigo in ("reservas", "restaurante", "lavanderia", "loja"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.estadia = self.reserva()
        services.registrar_pagamento_online(
            cobranca_id=801, valor=50, descricao="Sinal confirmado", reserva_id=self.estadia.pk
        )
        self.conta = self.estadia.fazer_checkin(self.usuario)
        self.abrir_caixa()
        self.client.force_login(self.usuario)

    def test_totais_conferem_com_linhas_creditos_estornos_e_formulario_de_recebimento(self):
        services.lancar_na_conta(self.conta, "consumo", "consumo", "Dois sucos", 25,
                                self.usuario, quantidade=2, preco_unitario=Decimal("12.50"))
        services.lancar_na_conta(self.conta, "desconto", "consumo", "Desconto acordado", 5, self.usuario)
        services.receber_pagamento(self.conta, self.usuario, self.dinheiro, 100)
        for _ in range(2):
            services.registrar_pagamento_online(
                cobranca_id=802, valor=190, descricao="Pix confirmado", reserva_id=self.estadia.pk
            )
        services.estornar_pagamento_online(cobranca_id=802, motivo="Estorno autorizado")
        dados = dados_extrato(self.conta)
        self.assertEqual(dados["subtotal"], Decimal("625"))
        self.assertEqual(dados["descontos"], Decimal("5"))
        self.assertEqual(dados["creditos"], Decimal("150"))
        self.assertEqual(dados["saldo"], Decimal("470"))
        self.assertEqual(dados["saldo"], self.conta.saldo())
        tela = self.client.get(reverse("reservas:detalhe", args=[self.estadia.pk]))
        self.assertEqual(tela.context["fin_total"], dados["total"])
        self.assertEqual(tela.context["fin_saldo"], dados["saldo"])
        self.assertEqual(tela.context["form_recebimento"].initial["valor"], dados["saldo"])

    def test_restaurante_guarda_quantidade_e_preco_original_no_extrato(self):
        from apps.restaurante import services as restaurante

        categoria = CategoriaProduto.objects.create(nome="Bebidas")
        produto = Produto.objects.create(nome="Suco", categoria=categoria, preco_venda=12)
        local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        registrar_entrada(produto, local, 10, 4, self.usuario)
        comanda = restaurante.abrir_comanda(self.usuario, local, conta_id=self.conta.pk)
        restaurante.adicionar_item(comanda, produto, 2, self.usuario)
        self.assertEqual(len(dados_extrato(self.conta)["pendencias"]), 1)
        with self.assertRaises(ValidationError):
            self.estadia.fazer_checkout(self.usuario)
        restaurante.fechar_comanda(comanda, self.usuario, "conta", conta_id=self.conta.pk)
        Produto.objects.filter(pk=produto.pk).update(preco_venda=99)
        item = self.conta.lancamentos.get(tipo="consumo")
        self.assertEqual((item.quantidade, item.preco_unitario, item.valor), (Decimal("2"), Decimal("12"), Decimal("24")))
        self.assertEqual(dados_extrato(self.conta)["pendencias"], [])

    def test_extrato_disponivel_antes_e_depois_da_saida_sem_mutar_a_conta(self):
        url = reverse("reservas:extrato", args=[self.estadia.pk])
        antes = list(self.conta.lancamentos.values_list("pk", "valor"))
        resposta = self.client.get(url)
        self.assertContains(resposta, "Conferência da hospedagem")
        self.assertContains(resposta, "Saldo a pagar")
        self.assertIn("no-store", resposta["Cache-Control"])
        self.assertEqual(antes, list(self.conta.lancamentos.values_list("pk", "valor")))
        services.receber_pagamento(self.conta, self.usuario, self.dinheiro, self.conta.saldo())
        self.estadia.fazer_checkout(self.usuario)
        resposta = self.client.get(url)
        self.assertContains(resposta, "Extrato de encerramento")
        self.assertEqual(resposta.context["extrato"]["saldo"], Decimal("0"))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_quantidade_preco_e_valor_nao_podem_divergir(self):
        with self.assertRaisesMessage(ValidationError, "não confere"):
            services.lancar_na_conta(self.conta, "consumo", "consumo", "Suco", 20,
                                    self.usuario, quantidade=2, preco_unitario=12)
        with self.assertRaisesMessage(ValidationError, "informados juntos"):
            services.lancar_na_conta(self.conta, "consumo", "consumo", "Suco", 20,
                                    self.usuario, quantidade=2)
        self.assertFalse(LancamentoConta.objects.filter(conta=self.conta, tipo="consumo").exists())
