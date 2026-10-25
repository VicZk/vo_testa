"""Camada Contábil × fluxos do fork: nada entra duas vezes na DRE, nada fica de fora."""
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.management.commands.rotinas import GRUPOS
from apps.nucleo.models.estoque import CategoriaProduto, LocalEstoque, MovimentoEstoque, Produto
from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    ContaRecorrente,
    LancamentoFinanceiro,
)
from apps.nucleo.modulos import Modulo

from . import relatorios
from .capturas import (
    capturar_descontos,
    capturar_receita,
    capturar_saidas_estoque,
    rotina_diaria,
)
from .models import FechamentoMensal

HOJE = timezone.localdate()


class LiquidacaoForaDaDRETests(TestCase):
    """Baixa de título com categoria gerida pelo sistema é dinheiro de algo já reconhecido."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("liq", password="x" * 10)

    def test_folha_paga_por_recorrencia_nao_soma_com_o_fechamento(self):
        folha = CategoriaFinanceira.objects.create(
            nome="Folha de pagamento", tipo=CategoriaFinanceira.Tipo.DESPESA, automatica=True)
        rec = ContaRecorrente.objects.create(
            categoria=folha, centro=Modulo.RESERVAS, descricao="Folha", valor=Decimal("9000"),
            dia_vencimento=5)
        titulo = rec.gerar(2026, 9)
        lanc = titulo.baixar(self.user, data=date(2026, 9, 5))
        lanc.refresh_from_db()
        titulo.refresh_from_db()
        self.assertEqual((lanc.conta_contabil, titulo.conta_contabil), ("2.1.01.01", "2.1.01.01"))
        fm = FechamentoMensal.objects.create(ano=2026, mes=9, folha=Decimal("9000"))
        fm.aplicar()
        dre = relatorios.dre(2026, 9)
        self.assertEqual(dre["lucro_bruto"], Decimal("-9000"))  # uma folha só, a do fechamento

    def test_compra_de_insumos_vai_ao_estoque_e_nao_ao_custo(self):
        insumos = CategoriaFinanceira.objects.create(
            nome="Insumos", tipo=CategoriaFinanceira.Tipo.DESPESA)
        titulo = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR, categoria=insumos, centro=Modulo.RESTAURANTE,
            descricao="Compra de bebidas", valor=Decimal("1200"), vencimento=date(2026, 9, 10))
        lanc = titulo.baixar(self.user, data=date(2026, 9, 10))
        lanc.refresh_from_db()
        self.assertEqual(lanc.conta_contabil, "1.1.03.01")
        self.assertEqual(relatorios.dre(2026, 9)["resultado"], Decimal("0.00"))

    def test_captura_sem_de_para_nao_vira_liquidacao(self):
        """Só a baixa manual liquida: a receita capturada fica na DRE mesmo sem regra."""
        with patch("apps.contabil.capturas._conta_classif", return_value=""), \
                patch("apps.reservas.services.diarias_periodo", return_value=Decimal("300")):
            capturar_receita(HOJE.year, HOJE.month)
        lanc = LancamentoFinanceiro.objects.get(referencia=f"receita:reservas:{HOJE:%Y-%m}")
        self.assertNotIn(lanc.conta_contabil, ("1.1.02.01", "2.1.01.01"))


class CapturasNovasTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("cap", password="x" * 10)

    def test_day_pass_entra_como_receita_propria(self):
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("1000")), \
                patch("apps.daypass.services.faturamento_periodo",
                      return_value={"ingressos": Decimal("150")}):
            capturar_receita(HOJE.year, HOJE.month)
        hosp = LancamentoFinanceiro.objects.get(referencia=f"receita:reservas:{HOJE:%Y-%m}")
        daypass = LancamentoFinanceiro.objects.get(referencia=f"receita:daypass:{HOJE:%Y-%m}")
        self.assertEqual((hosp.valor, daypass.valor), (Decimal("1000"), Decimal("150")))
        self.assertEqual(daypass.conta_contabil, "3.1.01.03")
        self.assertEqual(relatorios.dre(HOJE.year, HOJE.month)["receita_bruta"], Decimal("1150"))

    def test_desconto_da_conta_abate_a_receita_bruta(self):
        with patch("apps.reservas.services.diarias_periodo", return_value=Decimal("1000")), \
                patch("apps.daypass.services.faturamento_periodo",
                      return_value={"ingressos": Decimal("0")}):
            capturar_receita(HOJE.year, HOJE.month)
        with patch("apps.reservas.services.descontos_periodo", return_value=Decimal("80")):
            self.assertEqual(capturar_descontos(HOJE.year, HOJE.month), 1)
        dre = relatorios.dre(HOJE.year, HOJE.month)
        self.assertEqual((dre["receita_bruta"], dre["receita_liquida"]),
                         (Decimal("1000"), Decimal("920")))
        with patch("apps.reservas.services.descontos_periodo", return_value=Decimal("0")):
            capturar_descontos(HOJE.year, HOJE.month)  # recomputável: zerou, sai
        self.assertFalse(LancamentoFinanceiro.objects.filter(origem="desconto").exists())

    def test_consumo_interno_e_perda_do_estoque_viram_custo(self):
        produto = Produto.objects.create(
            nome="Sabonete", categoria=CategoriaProduto.objects.create(nome="Amenities"))
        local = LocalEstoque.objects.create(nome="Governança", modulo=Modulo.GOVERNANCA)
        for tipo, qtd in ((MovimentoEstoque.Tipo.CONSUMO_INTERNO, "-10"),
                          (MovimentoEstoque.Tipo.PERDA, "-2")):
            MovimentoEstoque.objects.create(
                produto=produto, local=local, tipo=tipo, quantidade=Decimal(qtd),
                custo_unitario=Decimal("1.50"), criado_por=self.user)
        agora = timezone.now()
        self.assertEqual(capturar_saidas_estoque(agora.year, agora.month), 2)
        consumo = LancamentoFinanceiro.objects.get(origem="consumo_estoque")
        perda = LancamentoFinanceiro.objects.get(origem="perda_estoque")
        self.assertEqual((consumo.valor, consumo.conta_contabil), (Decimal("15.00"), "4.2.01.02"))
        self.assertEqual((perda.valor, perda.conta_contabil), (Decimal("3.00"), "4.2.01.03"))


class OutrasReceitasTests(TestCase):
    def test_conta_a_receber_avulsa_tem_categoria_manual(self):
        from apps.nucleo.forms import ContaPagarReceberForm

        outras = CategoriaFinanceira.objects.get(nome="Outras receitas", tipo="receita")
        self.assertFalse(outras.automatica)
        self.assertIn(outras, ContaPagarReceberForm().fields["categoria"].queryset)


class RotinaDiariaTests(TestCase):
    def test_rotina_esta_no_grupo_diario_e_roda_idempotente(self):
        self.assertIn("rotina_contabil", GRUPOS["diarias"])
        cat = CategoriaFinanceira.objects.create(nome="Aluguel", tipo="despesa")
        ContaRecorrente.objects.create(categoria=cat, centro=Modulo.RESERVAS,
                                       descricao="Aluguel", valor=Decimal("5000"))
        saida = StringIO()
        call_command("rotina_contabil", stdout=saida)
        self.assertIn("títulos recorrentes novos: 1", saida.getvalue())
        self.assertEqual(rotina_diaria()["recorrentes_criadas"], 0)

    def test_comeco_do_mes_fecha_tambem_a_competencia_anterior(self):
        resultado = rotina_diaria(date(2026, 11, 3))
        self.assertEqual(sorted(resultado["capturas"]), ["2026-10", "2026-11"])

    @override_settings(CONTABIL_CRON_TOKEN="segredo123")
    def test_endpoint_so_aceita_o_token_no_cabecalho(self):
        url = reverse("contabil:cron_capturar")
        self.assertEqual(self.client.post(url + "?token=segredo123").status_code, 403)
        self.assertEqual(self.client.post(url, HTTP_X_CRON_TOKEN="segredo123").status_code, 200)
