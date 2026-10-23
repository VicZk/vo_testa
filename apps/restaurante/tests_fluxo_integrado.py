from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.daypass import services as daypass
from apps.daypass.models import TurnoDayPass
from apps.nucleo.models import (
    UH,
    Pessoa,
    Produto,
    SessaoCaixa,
    TipoUH,
    registrar_entrada,
    saldo,
    salvar_ficha,
)
from apps.nucleo.models.financeiro import estornar_movimento
from apps.reservas import services as reservas
from apps.reservas.models import Reserva

from . import services
from .models import GrupoOpcaoCardapio, OpcaoCardapio
from .tests import RestauranteBase


class FluxoRestauranteIntegradoTests(RestauranteBase):
    def setUp(self):
        super().setUp()
        self.carne = Produto.objects.create(nome="Carne", categoria=self.cerveja.categoria, unidade="kg")
        self.queijo = Produto.objects.create(nome="Queijo", categoria=self.cerveja.categoria, unidade="kg")
        registrar_entrada(self.carne, self.local, 5, 30, self.op)
        registrar_entrada(self.queijo, self.local, 1, 20, self.op)
        self.prato = Produto.objects.create(nome="Prato com carne", categoria=self.cerveja.categoria,
                                           preco_venda=28, usa_ficha_tecnica=True)
        salvar_ficha(self.prato, [(self.carne, Decimal("0.200"))], self.op)
        self.prato.refresh_from_db()
        ponto = GrupoOpcaoCardapio.objects.create(produto=self.prato, nome="Ponto", minimo=1)
        extra = GrupoOpcaoCardapio.objects.create(produto=self.prato, nome="Adicional")
        self.ponto = OpcaoCardapio.objects.create(grupo=ponto, nome="Ao ponto")
        self.extra = OpcaoCardapio.objects.create(grupo=extra, nome="Queijo", adicional=5,
            produto_estoque=self.queijo, quantidade_estoque=Decimal("0.030"))
        self.client.force_login(self.op)

    def pedir_prato(self, comanda, quantidade=2):
        return services.adicionar_item(comanda, self.prato, quantidade, self.op,
            observacoes="Molho à parte", opcoes=[self.ponto.pk, self.extra.pk], chave_pedido=uuid4())

    def test_ficha_personalizacao_edicao_cozinha_caixa_cupom_e_estorno(self):
        c = self.comanda()
        item = self.pedir_prato(c, 1)
        services.editar_item(item, self.op, versao=1, quantidade=2, observacoes="Molho à parte",
                             opcoes=[self.ponto.pk, self.extra.pk])
        item.refresh_from_db()
        self.assertEqual((item.preco_unitario, item.subtotal), (33, 66))
        self.assertEqual((saldo(self.carne, self.local), saldo(self.queijo, self.local)),
                         (Decimal("4.600"), Decimal("0.940")))
        cozinha = self.client.get(reverse("restaurante:cozinha"))
        self.assertContains(cozinha, "Ao ponto")
        self.assertContains(cozinha, "Molho à parte")
        for estado in ("preparando", "pronto"):
            services.alterar_preparo(item, estado, self.op, versao=item.versao)
            item.refresh_from_db()
        caixa = self.abrir_caixa()
        services.fechar_comanda(c, self.op, "caixa", forma=self.dinheiro, desconto=6)
        self.assertEqual(caixa.esperado_em_dinheiro(), 60)
        self.assertContains(self.client.get(reverse("restaurante:cozinha")), "Prato com carne")
        services.alterar_preparo(item, "entregue", self.op, versao=item.versao)
        self.assertNotContains(self.client.get(reverse("restaurante:cozinha")), "Prato com carne")
        recibo = self.client.get(reverse("restaurante:cupom", args=[c.pk]))
        self.assertEqual(recibo.context["cupom"]["total"], 60)
        self.assertContains(recibo, "Pago com")
        estornar_movimento(c.movimento_caixa, caixa, self.op, "Reembolso do atendimento")
        c.refresh_from_db()
        self.assertEqual((c.status, c.financeiro["status"]), ("fechada", "estornado_total"))
        self.assertEqual((saldo(self.carne, self.local), saldo(self.queijo, self.local)),
                         (Decimal("4.600"), Decimal("0.940")))

    def test_prato_vai_ao_quarto_com_detalhes_e_checkout_exige_resolver_comanda(self):
        hoje = timezone.localdate()
        tipo = TipoUH.objects.create(nome="Standard", tarifa_base=200)
        uh = UH.objects.create(numero="01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede do restaurante")
        estadia = Reserva.objects.create(uh=uh, hospede=hospede, checkin=hoje,
            checkout=hoje + timedelta(days=1), status="confirmada", valor_diaria=200, criado_por=self.op)
        conta = estadia.fazer_checkin(self.op)
        base = conta.total_lancamentos()
        c = services.abrir_comanda(self.op, self.local, conta_id=conta.pk)
        item = self.pedir_prato(c)
        with self.assertRaisesMessage(ValidationError, "consumo"):
            estadia.fazer_checkout(self.op)
        for estado in ("preparando", "pronto", "entregue"):
            services.alterar_preparo(item, estado, self.op, versao=item.versao)
            item.refresh_from_db()
        services.fechar_comanda(c, self.op, "conta", conta_id=conta.pk, desconto=6)
        lancamento = conta.lancamentos.get(tipo="consumo")
        self.assertEqual((lancamento.quantidade, lancamento.preco_unitario, lancamento.valor), (2, 33, 66))
        self.assertIn("Ao ponto", lancamento.observacoes)
        self.assertIn("Queijo", lancamento.observacoes)
        self.assertEqual(conta.total_lancamentos(), base + 60)
        self.assertEqual(reservas.pendencias_consumo(conta), [])
        self.assertIsNone(c.movimento_caixa_id)
        self.assertContains(self.client.get(reverse("restaurante:cupom", args=[c.pk])), "Lançado na conta")
        SessaoCaixa.objects.create(operador=self.op, modulo="reservas")
        reservas.receber_pagamento(conta, self.op, self.dinheiro, conta.saldo())
        estadia.fazer_checkout(self.op)
        self.assertEqual(saldo(self.carne, self.local), Decimal("4.600"))

    def test_daypass_consumo_pago_fecha_visita_sem_misturar_caixas_dos_ingressos(self):
        pessoa = Pessoa.objects.create(nome="Visitante da piscina")
        dia = timezone.localdate() + timedelta(days=1)
        turno = TurnoDayPass(dia_id=dia, nome="Piscina", inicio=time(9), fim=time(13),
            capacidade=3, contar_hospedes=True, preco_adulto=50, preco_crianca=25, preco_hospede=0, ativo=True)
        daypass.salvar_turno(turno, self.op)
        visita = daypass.reservar(turno=turno, responsavel=pessoa, adultos=[pessoa.nome],
                                 criancas=[], usuario=self.op, chave=uuid4())
        caixa_ingressos = SessaoCaixa.objects.create(operador=self.op, modulo="reservas")
        daypass.receber(visita, self.op, self.dinheiro, 50, uuid4())
        visitante = visita.visitantes.get()
        with patch("apps.daypass.services.timezone.localtime", return_value=timezone.make_aware(datetime.combine(dia, time(10)))):
            daypass.registrar_entrada(visitante, self.op)
        c = daypass.abrir_consumo(visita, self.op, self.local)
        self.assertEqual(daypass.abrir_consumo(visita, self.op, self.local).pk, c.pk)
        self.assertIsNone(c.conta_id)
        item = services.adicionar_item(c, self.cerveja, 2, self.op, chave_pedido=uuid4())
        services.alterar_preparo(item, "entregue", self.op, versao=1)
        daypass.registrar_saida(visitante, self.op)
        with self.assertRaisesMessage(ValidationError, "comandas abertas"):
            daypass.encerrar(visita, self.op)
        caixa_restaurante = self.abrir_caixa()
        services.fechar_comanda(c, self.op, "caixa", forma=self.dinheiro)
        daypass.encerrar(visita, self.op)
        visita.refresh_from_db()
        self.assertEqual(visita.status, "encerrada")
        self.assertEqual(caixa_ingressos.esperado_em_dinheiro(), 50)
        self.assertEqual(caixa_restaurante.esperado_em_dinheiro(), 24)
        self.assertEqual(saldo(self.cerveja, self.local), 18)
