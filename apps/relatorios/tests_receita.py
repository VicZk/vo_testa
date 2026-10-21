"""
Relatórios de receita vendida: carteira (OTB), pickup, ritmo e custo de canal.

Cada caso aqui é uma pergunta que o dono faz e que estes relatórios têm de responder
igual todo mês: o que conta na carteira, onde cai a noite da virada do mês, o que
entrou e saiu nos últimos dias, com quanta antecedência vendeu e quanto custou vender.
"""
import csv
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Agencia, ConfiguracaoReservas, Pessoa, TipoUH
from apps.reservas.models import Reserva

from . import services

Usuario = get_user_model()

NOVEMBRO = (date(2026, 11, 1), date(2026, 11, 30))
DEZEMBRO = (date(2026, 12, 1), date(2026, 12, 31))


def _linhas_de_dia(dados):
    """As linhas de data ("05/11 · qui"), sem o total nem os cortes por canal."""
    return [lin for lin in dados["linhas"] if re.match(r"\d\d/\d\d · ", lin[0])]


class BaseReceita(TestCase):
    """Dois quartos de pernoite + a vaga de day use que a migração já semeia (e que
    tem de ficar fora da ocupação)."""

    def setUp(self):
        self.op = Usuario.objects.create_superuser(
            username="ger", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("300"))
        self.q1 = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.q2 = UH.objects.create(numero="Quarto 02", tipo=self.tipo)
        self.day = UH.objects.filter(
            tipo__modalidade=TipoUH.Modalidade.DAY_USE, status=UH.Status.ATIVA).first()
        self.hospede = Pessoa.objects.create(nome="Hóspede de Teste")
        ConfiguracaoReservas.carregar()   # singleton pronto (percentuais no default)
        # A migração não semeia os 24 quartos: a ocupação dos testes é sobre os 2 acima.
        self.quartos_de_pernoite = (UH.objects.filter(status=UH.Status.ATIVA)
                                    .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
                                    .count())

    def reserva(self, *, checkin, checkout, status=Reserva.Status.CONFIRMADA,
                diaria="400", uh=None, canal=Reserva.Canal.BALCAO,
                vendida_em=None, faturamento=Reserva.Faturamento.PARTICULAR,
                titular=None, **extra):
        r = Reserva.objects.create(
            uh=uh or self.q1, hospede=self.hospede, checkin=checkin, checkout=checkout,
            status=status, canal=canal, faturamento=faturamento, titular=titular,
            valor_diaria=Decimal(diaria), criado_por=self.op, **extra,
        )
        if vendida_em:
            self.vender_em(r, vendida_em)
        return r

    def vender_em(self, reserva, dia):
        """Reescreve a data da venda (`criado_em` é auto_now_add)."""
        Reserva.objects.filter(pk=reserva.pk).update(criado_em=self.momento(dia))
        reserva.refresh_from_db()

    def sair_em(self, reserva, dia, *, motivo="Desistiu."):
        reserva.cancelar(self.op, motivo)
        Reserva.objects.filter(pk=reserva.pk).update(cancelada_em=self.momento(dia))
        reserva.refresh_from_db()

    @staticmethod
    def momento(dia):
        return timezone.make_aware(datetime.combine(dia, time(10, 0)))


class CarteiraTests(BaseReceita):
    def test_conta_so_o_que_esta_na_carteira(self):
        """Firme e provisória entram (separadas); cancelada, no-show e orçamento não."""
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4))  # 2 noites
        self.reserva(checkin=date(2026, 11, 6), checkout=date(2026, 11, 7),
                     status=Reserva.Status.PRE_RESERVA, diaria="300")        # 1 noite
        fora = [
            self.reserva(checkin=date(2026, 11, 10), checkout=date(2026, 11, 12),
                         uh=self.q2),
            self.reserva(checkin=date(2026, 11, 15), checkout=date(2026, 11, 17),
                         uh=self.q2),
        ]
        fora[0].cancelar(self.op, "Desistiu.")
        fora[1].marcar_no_show(self.op)
        self.reserva(checkin=date(2026, 11, 20), checkout=date(2026, 11, 22),
                     uh=self.q2, status=Reserva.Status.ORCAMENTO)

        from apps.reservas.services import carteira
        c = carteira(*NOVEMBRO)
        self.assertEqual(c["noites_firmes"], 2)
        self.assertEqual(c["receita_firme"], Decimal("800.00"))
        self.assertEqual(c["noites_provisorias"], 1)
        self.assertEqual(c["receita_provisoria"], Decimal("300.00"))

    def test_pre_reserva_com_retencao_vencida_nao_esta_vendida(self):
        r = self.reserva(checkin=date(2026, 11, 5), checkout=date(2026, 11, 7),
                         status=Reserva.Status.PRE_RESERVA)
        Reserva.objects.filter(pk=r.pk).update(
            expira_em=timezone.now() - timedelta(hours=1))
        from apps.reservas.services import carteira
        self.assertEqual(carteira(*NOVEMBRO)["noites_provisorias"], 0)

    def test_virada_do_mes_divide_as_noites(self):
        """30/11 → 03/12 = 1 noite em novembro (a de 30/11) e 2 em dezembro."""
        self.reserva(checkin=date(2026, 11, 30), checkout=date(2026, 12, 3),
                     diaria="500")
        from apps.reservas.services import carteira
        nov, dez = carteira(*NOVEMBRO), carteira(*DEZEMBRO)
        self.assertEqual(nov["noites_firmes"], 1)
        self.assertEqual(nov["receita_firme"], Decimal("500.00"))
        self.assertEqual(dez["noites_firmes"], 2)
        self.assertEqual(dez["receita_firme"], Decimal("1000.00"))

    def test_noite_do_checkout_nao_e_noite(self):
        """Saída no dia 1º não vende nenhuma noite de dezembro."""
        self.reserva(checkin=date(2026, 11, 28), checkout=date(2026, 12, 1))
        from apps.reservas.services import carteira
        self.assertEqual(carteira(*DEZEMBRO)["noites_firmes"], 0)
        self.assertEqual(carteira(*NOVEMBRO)["noites_firmes"], 3)

    def test_ocupacao_so_dos_quartos_de_pernoite(self):
        """O day use não entra nem no numerador nem no denominador."""
        self.reserva(checkin=date(2026, 11, 1), checkout=date(2026, 11, 2))
        self.reserva(checkin=date(2026, 11, 1), checkout=date(2026, 11, 2),
                     uh=self.day, diaria="120")
        from apps.reservas.services import carteira
        c = carteira(date(2026, 11, 1), date(2026, 11, 1))
        self.assertEqual(self.quartos_de_pernoite, 2)   # as vagas DAY-0N ficam fora
        self.assertEqual(c["quartos"], 2)
        self.assertEqual(c["disponiveis"], 2)
        self.assertEqual(c["noites_firmes"], 1)
        self.assertEqual(c["ocupacao"], Decimal("50.0"))
        self.assertEqual(c["receita_firme"], Decimal("400.00"))
        # O dinheiro do day use não se perde: aparece no resumo à parte.
        self.assertEqual(c["day_use"]["reservas"], 1)
        self.assertEqual(c["day_use"]["receita"], Decimal("120.00"))

    def test_adr_e_a_media_da_noite_vendida(self):
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4),
                     diaria="400")
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 3),
                     uh=self.q2, diaria="700")
        from apps.reservas.services import carteira
        c = carteira(*NOVEMBRO)
        self.assertEqual(c["noites_firmes"], 3)
        self.assertEqual(c["adr"], Decimal("500.00"))   # 1500 / 3

    def test_corte_por_canal_e_faturamento_so_do_firme(self):
        agencia = Pessoa.objects.create(nome="Agência Demo",
                                        tipo=Pessoa.Tipo.JURIDICA)
        Agencia.objects.create(pessoa=agencia, comissao_padrao=Decimal("10"))
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4),
                     canal=Reserva.Canal.OTA,
                     faturamento=Reserva.Faturamento.AGENCIA, titular=agencia)
        self.reserva(checkin=date(2026, 11, 8), checkout=date(2026, 11, 9),
                     canal=Reserva.Canal.SITE, status=Reserva.Status.PRE_RESERVA)
        from apps.reservas.services import carteira
        c = carteira(*NOVEMBRO)
        por_canal = {lin["rotulo"]: lin["noites"] for lin in c["por_canal"]}
        self.assertEqual(por_canal[Reserva.Canal.OTA.label], 2)
        self.assertEqual(por_canal[Reserva.Canal.SITE.label], 0)   # pré-reserva fora
        por_fat = {lin["rotulo"]: lin["noites"] for lin in c["por_faturamento"]}
        self.assertEqual(por_fat[Reserva.Faturamento.AGENCIA.label], 2)

    def test_relatorio_mostra_o_dia_a_dia_e_o_total(self):
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4))
        dados = services.rel_carteira(*NOVEMBRO)
        self.assertEqual(len(dados["colunas"]), 6)
        self.assertEqual(len(dados["linhas"][0]), 6)
        dias = _linhas_de_dia(dados)
        self.assertEqual(len(dias), 30)                     # uma linha por dia
        self.assertEqual(dias[0][0], "01/11 · dom")
        self.assertEqual([dias[1][1], dias[2][1], dias[3][1]], ["1", "1", "0"])
        self.assertEqual(dias[1][2], "50%")                 # 1 de 2 quartos
        total = next(lin for lin in dados["linhas"] if lin[0] == "Total do período")
        self.assertEqual(total[1], "2")
        self.assertEqual(total[3], "R$ 800,00")
        self.assertIn("Carteira", dados["nota"])


class PickupTests(BaseReceita):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()

    def test_entrou_e_saiu_dentro_e_fora_da_janela(self):
        dentro = self.reserva(checkin=date(2026, 11, 3), checkout=date(2026, 11, 5),
                              vendida_em=self.hoje - timedelta(days=2))
        self.reserva(checkin=date(2026, 11, 10), checkout=date(2026, 11, 12),
                     uh=self.q2, vendida_em=self.hoje - timedelta(days=20))
        saiu = self.reserva(checkin=date(2026, 11, 20), checkout=date(2026, 11, 21),
                            diaria="300", vendida_em=self.hoje - timedelta(days=25))
        self.sair_em(saiu, self.hoje - timedelta(days=1))
        saiu_antes = self.reserva(checkin=date(2026, 11, 25),
                                  checkout=date(2026, 11, 27), uh=self.q2,
                                  vendida_em=self.hoje - timedelta(days=40))
        self.sair_em(saiu_antes, self.hoje - timedelta(days=15))

        from apps.reservas.services import pickup
        p = pickup(*NOVEMBRO, janela=7)
        self.assertEqual(p["entrou"]["reservas"], 1)
        self.assertEqual(p["entrou"]["noites"], 2)
        self.assertEqual(p["entrou"]["receita"], Decimal("800.00"))
        self.assertEqual(p["saiu"]["noites"], 1)
        self.assertEqual(p["saiu"]["receita"], Decimal("300.00"))
        self.assertEqual(p["liquido"]["noites"], 1)
        self.assertEqual(p["liquido"]["receita"], Decimal("500.00"))
        # A janela de 30 dias alcança as que a de 7 deixou de fora (a de 40 dias, não:
        # 30 dias corridos contando hoje = de hoje-29 até hoje).
        larga = pickup(*NOVEMBRO, janela=30)
        self.assertEqual(larga["entrou"]["reservas"], 3)
        self.assertEqual(larga["saiu"]["noites"], 3)        # 1 + 2 (a de 15 dias atrás)
        self.assertEqual(dentro.canal, Reserva.Canal.BALCAO)

    def test_so_as_estadias_do_periodo_escolhido(self):
        """Vendida na janela, mas para dezembro: não é pickup de novembro."""
        self.reserva(checkin=date(2026, 12, 5), checkout=date(2026, 12, 7),
                     vendida_em=self.hoje)
        from apps.reservas.services import pickup
        self.assertEqual(pickup(*NOVEMBRO, janela=7)["entrou"]["noites"], 0)
        self.assertEqual(pickup(*DEZEMBRO, janela=7)["entrou"]["noites"], 2)

    def test_cancelada_na_janela_conta_mesmo_tendo_entrado_na_janela(self):
        """Vendeu e caiu na mesma semana: entrou e saiu, líquido zero."""
        r = self.reserva(checkin=date(2026, 11, 8), checkout=date(2026, 11, 10),
                         vendida_em=self.hoje - timedelta(days=3))
        self.sair_em(r, self.hoje - timedelta(days=1))
        from apps.reservas.services import pickup
        p = pickup(*NOVEMBRO, janela=7)
        self.assertEqual(p["entrou"]["noites"], 2)
        self.assertEqual(p["saiu"]["noites"], 2)
        self.assertEqual(p["liquido"]["noites"], 0)
        self.assertEqual(p["liquido"]["receita"], Decimal("0.00"))

    def test_no_show_tambem_sai_da_carteira(self):
        r = self.reserva(checkin=date(2026, 11, 8), checkout=date(2026, 11, 9),
                         vendida_em=self.hoje - timedelta(days=20))
        r.marcar_no_show(self.op)
        self.assertIsNotNone(r.cancelada_em)
        from apps.reservas.services import pickup
        self.assertEqual(pickup(*NOVEMBRO, janela=7)["saiu"]["noites"], 1)

    def test_expiracao_da_retencao_grava_a_data_de_saida(self):
        r = self.reserva(checkin=date(2026, 11, 8), checkout=date(2026, 11, 9),
                         status=Reserva.Status.PRE_RESERVA)
        Reserva.objects.filter(pk=r.pk).update(
            expira_em=timezone.now() - timedelta(hours=1))
        from apps.reservas.services import expirar_vencidas
        self.assertEqual(expirar_vencidas(), 1)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CANCELADA)
        self.assertIsNotNone(r.cancelada_em)
        from apps.reservas.services import pickup
        self.assertEqual(pickup(*NOVEMBRO, janela=7)["saiu"]["noites"], 1)

    def test_relatorio_tem_a_janela_escolhida(self):
        dados = services.rel_pickup(*NOVEMBRO, janela=14)
        self.assertIn("Janela (últimos 14 dias)", dict(dados["kpis"]))
        self.assertEqual(len(_linhas_de_dia(dados)), 14)


class RitmoTests(BaseReceita):
    def test_acumula_pela_antecedencia_da_venda(self):
        """Cada venda cai na sua faixa e a curva soma de cima para baixo."""
        # 2 noites vendidas com 100 dias de antecedência
        self.reserva(checkin=date(2026, 11, 10), checkout=date(2026, 11, 12),
                     vendida_em=date(2026, 11, 10) - timedelta(days=100))
        # 1 noite com 40 dias
        self.reserva(checkin=date(2026, 11, 20), checkout=date(2026, 11, 21),
                     vendida_em=date(2026, 11, 20) - timedelta(days=40))
        # 3 noites com 10 dias
        self.reserva(checkin=date(2026, 11, 24), checkout=date(2026, 11, 27),
                     vendida_em=date(2026, 11, 24) - timedelta(days=10))

        from apps.reservas.services import ritmo_de_vendas
        r = ritmo_de_vendas(*NOVEMBRO)
        faixas = {f["rotulo"]: f for f in r["faixas"]}
        self.assertEqual(faixas["90+ dias antes"]["noites"], 2)
        self.assertEqual(faixas["30 a 59 dias"]["noites"], 1)
        self.assertEqual(faixas["7 a 13 dias"]["noites"], 3)
        self.assertEqual(faixas["60 a 89 dias"]["noites"], 0)
        # Acumulado: 2 → 2 → 3 → 3 → 6 → 6
        self.assertEqual([f["acumulado_noites"] for f in r["faixas"]],
                         [2, 2, 3, 3, 6, 6])
        self.assertEqual(r["noites"], 6)
        self.assertEqual(faixas["30 a 59 dias"]["parte_acumulada"], Decimal("50.0"))
        # Média ponderada por noite: (2×100 + 1×40 + 3×10) / 6 = 45
        self.assertEqual(r["antecedencia_media"], Decimal("45.0"))
        self.assertEqual(r["parte_antecipada"], Decimal("50.0"))

    def test_venda_lancada_depois_da_chegada_vale_zero_dias(self):
        self.reserva(checkin=date(2026, 11, 5), checkout=date(2026, 11, 6),
                     vendida_em=date(2026, 11, 9))
        from apps.reservas.services import ritmo_de_vendas
        r = ritmo_de_vendas(*NOVEMBRO)
        self.assertEqual(r["faixas"][-1]["noites"], 1)
        self.assertEqual(r["antecedencia_media"], Decimal("0.0"))

    def test_relatorio_lista_as_seis_faixas(self):
        dados = services.rel_ritmo(*NOVEMBRO)
        self.assertEqual(len(dados["linhas"]), 6)
        self.assertEqual(dados["linhas"][0][0], "90+ dias antes")


class CustoDistribuicaoTests(BaseReceita):
    def setUp(self):
        super().setUp()
        cfg = ConfiguracaoReservas.carregar()
        cfg.custo_canal_ota = Decimal("18.00")
        cfg.custo_canal_site = Decimal("2.50")
        cfg.save()

    def test_custo_por_canal_usa_os_percentuais_configurados(self):
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4),
                     canal=Reserva.Canal.OTA, diaria="500")          # 1000 bruto
        self.reserva(checkin=date(2026, 11, 6), checkout=date(2026, 11, 7),
                     canal=Reserva.Canal.SITE, diaria="400")         # 400 bruto
        self.reserva(checkin=date(2026, 11, 9), checkout=date(2026, 11, 10),
                     canal=Reserva.Canal.BALCAO, diaria="300")       # 300 bruto
        from apps.reservas.services import custo_distribuicao
        d = custo_distribuicao(*NOVEMBRO)
        linhas = {lin["rotulo"]: lin for lin in d["linhas"]}
        ota = linhas[Reserva.Canal.OTA.label]
        self.assertEqual(ota["receita"], Decimal("1000.00"))
        self.assertEqual(ota["custo"], Decimal("180.00"))
        self.assertEqual(ota["liquida"], Decimal("820.00"))
        self.assertEqual(linhas[Reserva.Canal.SITE.label]["custo"], Decimal("10.00"))
        self.assertEqual(linhas[Reserva.Canal.BALCAO.label]["custo"], Decimal("0.00"))
        self.assertEqual(d["bruta"], Decimal("1700.00"))
        self.assertEqual(d["custo"], Decimal("190.00"))
        self.assertEqual(d["liquida"], Decimal("1510.00"))

    def test_pre_reserva_nao_entra_no_custo(self):
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 3),
                     canal=Reserva.Canal.OTA, status=Reserva.Status.PRE_RESERVA)
        from apps.reservas.services import custo_distribuicao
        self.assertEqual(custo_distribuicao(*NOVEMBRO)["bruta"], Decimal("0.00"))

    def test_comissao_de_agencia_vem_do_cadastro_e_fica_a_parte(self):
        agencia = Pessoa.objects.create(nome="Agência Vale",
                                        tipo=Pessoa.Tipo.JURIDICA)
        Agencia.objects.create(pessoa=agencia, comissao_padrao=Decimal("12.00"))
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4),
                     canal=Reserva.Canal.BALCAO, diaria="500",
                     faturamento=Reserva.Faturamento.AGENCIA, titular=agencia)
        from apps.reservas.services import custo_distribuicao
        d = custo_distribuicao(*NOVEMBRO)
        self.assertEqual(len(d["comissoes"]), 1)
        self.assertEqual(d["comissoes"][0]["rotulo"], "Agência Vale")
        self.assertEqual(d["comissoes"][0]["comissao"], Decimal("120.00"))
        self.assertEqual(d["comissao_total"], Decimal("120.00"))
        # Estimativa informativa: NÃO entra no custo de canal nem na líquida.
        self.assertEqual(d["custo"], Decimal("0.00"))
        self.assertEqual(d["liquida"], Decimal("1000.00"))

    def test_particular_nao_gera_comissao(self):
        agencia = Pessoa.objects.create(nome="Agência Vale",
                                        tipo=Pessoa.Tipo.JURIDICA)
        Agencia.objects.create(pessoa=agencia, comissao_padrao=Decimal("12.00"))
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 3))
        from apps.reservas.services import custo_distribuicao
        self.assertEqual(custo_distribuicao(*NOVEMBRO)["comissoes"], [])

    def test_relatorio_avisa_que_e_estimativa(self):
        dados = services.rel_distribuicao(*NOVEMBRO)
        self.assertIn("Estimativa gerencial", dados["nota"])
        self.assertIn("Comissão de agência (estimativa)", dict(dados["kpis"]))


class ConsultasConstantesTests(BaseReceita):
    """O custo do relatório é do tamanho do período, não do número de reservas."""

    def povoar(self, quantas, *, etiqueta):
        """Cada reserva no seu próprio quarto (um lote não colide com o outro)."""
        hoje = timezone.localdate()
        for i in range(quantas):
            uh = UH.objects.create(numero=f"{etiqueta}-{i:02d}", tipo=self.tipo)
            dia = date(2026, 11, 2) + timedelta(days=i % 20)
            r = self.reserva(checkin=dia, checkout=dia + timedelta(days=3), uh=uh,
                             canal=Reserva.Canal.OTA if i % 3 else Reserva.Canal.SITE)
            self.vender_em(r, hoje - timedelta(days=i % 7))

    def _consultas(self, funcao):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            funcao()
        return len(ctx)

    def test_mesmo_numero_de_consultas_com_10_e_com_20_reservas(self):
        alvos = {
            "carteira": lambda: services.rel_carteira(*NOVEMBRO),
            "pickup": lambda: services.rel_pickup(*NOVEMBRO, janela=30),
            "ritmo": lambda: services.rel_ritmo(*NOVEMBRO),
            "distribuicao": lambda: services.rel_distribuicao(*NOVEMBRO),
        }
        self.povoar(10, etiqueta="LOTE-A")
        antes = {nome: self._consultas(f) for nome, f in alvos.items()}
        self.povoar(10, etiqueta="LOTE-B")
        depois = {nome: self._consultas(f) for nome, f in alvos.items()}
        self.assertEqual(antes, depois)
        # E o teto é baixo: nenhum relatório passa de 3 consultas.
        for nome, n in depois.items():
            self.assertLessEqual(n, 3, f"{nome} fez {n} consultas")

    def test_periodo_maior_nao_multiplica_consultas(self):
        self.povoar(10, etiqueta="LOTE-A")
        mes = self._consultas(lambda: services.rel_carteira(*NOVEMBRO))
        ano = self._consultas(
            lambda: services.rel_carteira(date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(mes, ano)


class RegistroEViewTests(BaseReceita):
    def setUp(self):
        super().setUp()
        self.client.login(username="ger", password="senha-forte-123")
        self.reserva(checkin=date(2026, 11, 2), checkout=date(2026, 11, 4))

    def test_os_quatro_estao_no_registro_dos_consolidados(self):
        chaves = {r["chave"] for r in services.disponiveis()["Consolidados"]}
        self.assertTrue({"carteira", "pickup", "ritmo", "distribuicao"} <= chaves)

    def test_sem_o_modulo_reservas_saem_do_registro_e_dao_404(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        chaves = {r["chave"] for grupo in services.disponiveis().values() for r in grupo}
        self.assertFalse({"carteira", "pickup", "ritmo"} & chaves)
        for chave in ("carteira", "pickup", "ritmo", "distribuicao"):
            resp = self.client.get(reverse("relatorios:relatorio", args=[chave]))
            self.assertEqual(resp.status_code, 404, chave)

    def test_cada_tela_abre(self):
        for chave in ("carteira", "pickup", "ritmo", "distribuicao"):
            resp = self.client.get(reverse("relatorios:relatorio", args=[chave]),
                                   {"mes": 11, "ano": 2026})
            self.assertEqual(resp.status_code, 200, chave)
            self.assertContains(resp, services.RELATORIOS[chave]["nome"])
            # A nota explica o relatório na própria tela (e no CSV e na impressão).
            self.assertContains(resp, resp.context["dados"]["nota"][:40])
            # Coluna de número nasce alinhada: `.num` no <th> (regra da casa).
            self.assertContains(resp, '<th class="num">')

    def test_carteira_abre_no_proximo_mes(self):
        hoje = timezone.localdate()
        esperado = (hoje.replace(day=1) + timedelta(days=31)).replace(day=1)
        resp = self.client.get(reverse("relatorios:relatorio", args=["carteira"]))
        self.assertEqual(resp.context["inicio"], esperado)
        # Os de trás continuam abrindo no mês corrente.
        resp = self.client.get(reverse("relatorios:relatorio", args=["ocupacao"]))
        self.assertEqual(resp.context["inicio"], hoje.replace(day=1))

    def test_janela_do_pickup_vem_do_endereco_e_e_validada(self):
        resp = self.client.get(reverse("relatorios:relatorio", args=["pickup"]),
                               {"janela": 30})
        self.assertEqual(resp.context["controles"][0]["valor"], 30)
        resp = self.client.get(reverse("relatorios:relatorio", args=["pickup"]),
                               {"janela": "999"})
        self.assertEqual(resp.context["controles"][0]["valor"], 7)   # volta ao padrão

    def test_csv_sai_com_as_mesmas_linhas_da_tela(self):
        for chave in ("carteira", "pickup", "ritmo", "distribuicao"):
            resp = self.client.get(reverse("relatorios:relatorio", args=[chave]),
                                   {"mes": 11, "ano": 2026, "export": "csv"})
            self.assertIn("text/csv", resp["Content-Type"], chave)
            texto = resp.content.decode("utf-8-sig")
            # Um BOM só, no começo do arquivo: nenhuma linha carrega marca invisível.
            self.assertNotIn("﻿", texto, chave)
            linhas = list(csv.reader(texto.splitlines(), delimiter=";"))
            extras = {nome: services.CONTROLES[nome]["padrao"]
                      for nome in services.RELATORIOS[chave].get("controles", ())}
            dados = services.RELATORIOS[chave]["builder"](*NOVEMBRO, **extras)
            # Cabeçalho da tabela e todas as linhas, na mesma ordem.
            inicio = linhas.index(dados["colunas"])
            do_csv = linhas[inicio + 1:inicio + 1 + len(dados["linhas"])]
            self.assertEqual(do_csv, dados["linhas"], chave)
            self.assertIn(dados["nota"], texto)

    def test_csv_do_pickup_leva_a_janela_escolhida(self):
        resp = self.client.get(reverse("relatorios:relatorio", args=["pickup"]),
                               {"mes": 11, "ano": 2026, "janela": 30, "export": "csv"})
        self.assertIn("últimos 30 dias", resp.content.decode("utf-8-sig"))
