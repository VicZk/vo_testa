from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import MovimentoCaixa, SessaoCaixa, TrilhaAuditoria, saldo
from apps.nucleo.models.financeiro import estornar_movimento
from apps.relatorios.services import rel_faturamento_modulos

from . import services
from .tests import RestauranteBase


class EstornoRestauranteTests(RestauranteBase):
    def setUp(self):
        super().setUp()
        self.sessao = self.abrir_caixa()
        self.c = self.comanda()
        self.item = services.adicionar_item(self.c, self.cerveja, 2, self.op)
        services.fechar_comanda(self.c, self.op, "caixa", forma=self.dinheiro, desconto=4)
        self.c.refresh_from_db()
        self.client.force_login(self.op)

    def test_estorno_parcial_altera_resumo_e_cupom_sem_mudar_consumo_ou_preparo(self):
        estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Devolução parcial", valor=5)
        resumo = self.c.financeiro
        self.assertEqual(resumo, {"recebido": Decimal("20"), "estornado": Decimal("5"), "liquido": Decimal("15"),
                                  "status": "estornado_parcial", "rotulo": "Pagamento parcialmente estornado"})
        self.c.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.c.status, "fechada")
        self.assertEqual(self.item.preparo, "aguardando")
        self.assertEqual(saldo(self.cerveja, self.local), 18)
        resposta = self.client.get(reverse("restaurante:cupom", args=[self.c.pk]))
        self.assertNotContains(resposta, "Pago com")
        self.assertContains(resposta, "Pagamento parcialmente estornado")
        self.assertEqual(resposta.context["cupom"]["liquido"], 15)

    def test_estorno_integral_acumulado_nao_exibe_pago_no_cupom(self):
        estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Primeira devolução", valor=5)
        estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Restante", valor=15)
        self.assertEqual(self.c.financeiro["status"], "estornado_total")
        self.assertEqual(self.c.financeiro["liquido"], 0)
        resposta = self.client.get(reverse("restaurante:cupom", args=[self.c.pk]))
        self.assertContains(resposta, "Pagamento estornado")
        self.assertNotContains(resposta, "Pago com")
        self.assertEqual(self.sessao.esperado_em_dinheiro(), 0)
        self.assertEqual(saldo(self.cerveja, self.local), 18)

    def test_periodo_separa_bruto_desconto_e_movimentos_sem_mudar_caixa_quarto(self):
        estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Devolução parcial", valor=5)
        hoje = timezone.localdate()
        resumo = services.faturamento_periodo(hoje, hoje)
        self.assertEqual(resumo, {"caixa": Decimal("20"), "quarto": Decimal("0"),
            "venda_bruta": Decimal("24"), "descontos": Decimal("4"), "venda_liquida": Decimal("20"),
            "recebimentos": Decimal("20"), "estornos": Decimal("5"), "recebido_liquido": Decimal("15")})

    def test_estorno_em_outro_dia_nao_reescreve_venda_ou_recebimento_antigos(self):
        agora = timezone.now()
        ontem = agora - timedelta(days=1)
        type(self.c).objects.filter(pk=self.c.pk).update(fechada_em=ontem)
        MovimentoCaixa.objects.filter(pk=self.c.movimento_caixa_id).update(criado_em=ontem)
        self.sessao.fechar(20, self.op)
        nova = SessaoCaixa.objects.create(operador=self.op, modulo="restaurante", fundo_troco=0)
        estorno = estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Devolução no dia seguinte")
        self.assertEqual(estorno.sessao_id, nova.pk)
        dia_venda, dia_estorno = timezone.localdate(ontem), timezone.localdate(agora)
        venda = services.faturamento_periodo(dia_venda, dia_venda)
        devolucao = services.faturamento_periodo(dia_estorno, dia_estorno)
        self.assertEqual((venda["caixa"], venda["recebimentos"], venda["estornos"], venda["recebido_liquido"]), (20, 20, 0, 20))
        self.assertEqual((devolucao["venda_bruta"], devolucao["recebimentos"], devolucao["estornos"], devolucao["recebido_liquido"]), (0, 0, 20, -20))
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.valor_contado, 20)
        self.assertEqual(saldo(self.cerveja, self.local), 18)

    def test_relatorio_html_e_csv_preservam_tabela_e_expoem_estornos_separados(self):
        estornar_movimento(self.c.movimento_caixa, self.sessao, self.op, "Devolução parcial", valor=5)
        hoje = timezone.localdate()
        resumo = rel_faturamento_modulos(hoje, hoje)
        self.assertEqual(next(linha for linha in resumo["linhas"] if linha[0] == "Restaurante"),
                         ["Restaurante", "R$ 20,00", "R$ 0,00", "R$ 20,00"])
        self.assertIn(("Recebido líquido", "R$ 15,00"), resumo["restaurante_financeiro"]["caixa"])
        url = reverse("relatorios:relatorio", args=["faturamento_modulos"])
        resposta = self.client.get(url)
        self.assertContains(resposta, "Caixa pela data de cada recebimento e estorno")
        self.assertContains(resposta, "Recebido líquido")
        csv = self.client.get(url, {"export": "csv"}).content.decode("utf-8-sig")
        self.assertIn("Restaurante: caixa pela data do movimento", csv)
        self.assertIn("Recebido líquido;R$ 15,00", csv)


class ComandaSemCobrancaTests(RestauranteBase):
    def test_desconto_integral_fecha_sem_caixa_forma_ou_movimento_e_preserva_consumo(self):
        c = self.comanda()
        item = services.adicionar_item(c, self.cerveja, 2, self.op)
        services.fechar_comanda(c, self.op, "caixa", desconto=24)
        c.refresh_from_db()
        self.assertEqual(c.status, "fechada")
        self.assertIsNone(c.forma_pagamento_id)
        self.assertIsNone(c.movimento_caixa_id)
        self.assertEqual(c.financeiro["status"], "sem_cobranca")
        self.assertEqual(c.financeiro["rotulo"], "Sem valor a receber")
        self.assertEqual(c.financeiro["recebido"], 0)
        self.assertFalse(MovimentoCaixa.objects.exists())
        self.assertFalse(SessaoCaixa.objects.exists())
        self.assertEqual(saldo(self.cerveja, self.local), 18)
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="comanda_sem_cobranca").exists())
        self.client.force_login(self.op)
        recibo = self.client.get(reverse("restaurante:cupom", args=[c.pk]))
        self.assertContains(recibo, "Sem valor a receber")
        self.assertNotContains(recibo, "Pago com")
        self.assertContains(self.client.get(reverse("restaurante:cozinha")), "Cerveja")
        services.alterar_preparo(item, "entregue", self.op, versao=1)
        hoje = timezone.localdate()
        valores = services.faturamento_periodo(hoje, hoje)
        self.assertEqual((valores["venda_bruta"], valores["descontos"], valores["venda_liquida"], valores["recebido_liquido"]), (24, 24, 0, 0))
        with self.assertRaisesMessage(ValidationError, "já foi fechada"):
            services.fechar_comanda(c, self.op, "caixa", desconto=24)

    def test_desconto_parcial_ainda_exige_pagamento_e_nao_fecha_sem_caixa(self):
        c = self.comanda()
        services.adicionar_item(c, self.cerveja, 1, self.op)
        with self.assertRaisesMessage(ValidationError, "forma de pagamento"):
            services.fechar_comanda(c, self.op, "caixa", desconto=11)
        c.refresh_from_db()
        self.assertEqual(c.status, "aberta")
        self.assertEqual(c.desconto, 0)
