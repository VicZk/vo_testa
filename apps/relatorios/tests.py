from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, TipoUH

from . import services

Usuario = get_user_model()


class RelatoriosServiceTests(TestCase):
    def setUp(self):
        from apps.reservas.models import Reserva
        self.op = Usuario.objects.create_superuser(username="ger", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede")
        hoje = timezone.localdate()
        self.r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje - timedelta(days=2),
            checkout=hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("200"), criado_por=self.op,
        )
        self.r.fazer_checkin(self.op)  # lança diárias na conta

    def _periodo(self):
        hoje = timezone.localdate()
        return hoje - timedelta(days=7), hoje

    def test_producao_soma_diarias(self):
        ini, fim = self._periodo()
        p = services.rel_producao(ini, fim)
        # três noites (hoje-2 a hoje+1) × 200 = 600 em serviço
        self.assertTrue(any("600" in v for _, v in p["kpis"]))

    def test_ocupacao_calcula_taxa(self):
        ini, fim = self._periodo()
        o = services.rel_ocupacao(ini, fim)
        rotulos = [r for r, _ in o["kpis"]]
        self.assertIn("Ocupação", rotulos)
        self.assertIn("Diária média (ADR)", rotulos)

    def test_reservas_conta_por_canal(self):
        ini, fim = self._periodo()
        r = services.rel_reservas(ini, fim)
        self.assertEqual(r["kpis"][0], ("Reservas criadas", "1"))

    def test_disponiveis_agrupa(self):
        grupos = services.disponiveis()
        self.assertIn("Consolidados", grupos)

    def test_periodo_por_mes_ano(self):
        from django.test import RequestFactory
        req = RequestFactory().get("/", {"mes": "3", "ano": "2026"})
        ini, fim, rotulo = services.periodo(req)
        self.assertEqual((ini.year, ini.month, ini.day), (2026, 3, 1))
        self.assertEqual((fim.year, fim.month, fim.day), (2026, 3, 31))
        self.assertEqual(rotulo, "Março/2026")

    def test_periodo_padrao_mes_corrente(self):
        from django.test import RequestFactory
        hoje = timezone.localdate()
        ini, fim, _ = services.periodo(RequestFactory().get("/"))
        self.assertEqual((ini.year, ini.month), (hoje.year, hoje.month))
        self.assertEqual(ini.day, 1)

    def test_faturamento_diarias_vao_para_o_quarto(self):
        ini, fim = self._periodo()
        f = services.rel_faturamento_modulos(ini, fim)
        kpis = dict(f["kpis"])
        # 3 diárias × 200 = 600, tudo "lançado no quarto" (recepção recebe).
        self.assertIn("600", kpis["Lançado nos quartos (recepção recebe)"])
        hosp = next(lin for lin in f["linhas"] if "Hospedagem" in lin[0])
        self.assertEqual(hosp[1], "R$ 0,00")   # nada no caixa do setor (formato pt-BR)
        self.assertIn("600", hosp[2])    # tudo no quarto

    def test_faturamento_loja_separa_caixa_e_quarto(self):
        from apps.loja.models import Venda
        from apps.nucleo.models import LocalEstoque
        local = LocalEstoque.objects.create(nome="Loja", modulo="loja")
        Venda.objects.create(local=local, destino=Venda.Destino.CAIXA,
                             total=Decimal("100.00"), criado_por=self.op)
        Venda.objects.create(local=local, destino=Venda.Destino.CONTA,
                             total=Decimal("50.00"), criado_por=self.op)
        ini, fim = self._periodo()
        f = services.rel_faturamento_modulos(ini, fim)
        loja = next(lin for lin in f["linhas"] if lin[0] == "Loja")
        self.assertIn("100", loja[1])  # no caixa do setor
        self.assertIn("50", loja[2])   # lançado no quarto
        self.assertIn("150", loja[3])  # total vendido


class RelatoriosViewTests(TestCase):
    def setUp(self):
        self.ger = Usuario.objects.create_superuser(username="ger", password="senha-forte-123")

    def test_index_ok(self):
        self.client.login(username="ger", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("relatorios:index")).status_code, 200)

    def test_relatorio_render(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["caixa"]))
        self.assertEqual(r.status_code, 200)

    def test_export_csv(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["caixa"]), {"export": "csv"})
        self.assertIn("text/csv", r["Content-Type"])  # agora com charset utf-8-sig (BOM)

    def test_relatorio_inexistente_404(self):
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("relatorios:relatorio", args=["nao-existe"]))
        self.assertEqual(r.status_code, 404)

    def test_sem_gerencia_403(self):
        Usuario.objects.create_user(username="op", password="senha-forte-123")
        self.client.login(username="op", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("relatorios:index")).status_code, 403)


class RelatoriosGovernancaTests(TestCase):
    """Os três relatórios da Governança entram no registro como os outros: grupo
    "Por módulo", presos ao módulo, com CSV e a mesma regra de acesso."""

    CHAVES = ["governanca_faxinas", "governanca_inspecao", "governanca_discrepancias"]

    def setUp(self):
        self.ger = Usuario.objects.create_superuser(
            username="ger", password="senha-forte-123")
        self.client.login(username="ger", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)

    def test_estao_no_registro_amarrados_ao_modulo(self):
        from apps.nucleo.modulos import Modulo
        for chave in self.CHAVES:
            r = services.RELATORIOS[chave]
            self.assertEqual(r["grupo"], "Por módulo", chave)
            self.assertEqual(r["modulo"], Modulo.GOVERNANCA, chave)
        nomes = [r["nome"] for r in services.disponiveis()["Por módulo"]]
        self.assertTrue(any("Governança" in n for n in nomes))

    def test_somem_do_indice_com_o_modulo_inativo(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        chaves = {r["chave"] for grupo in services.disponiveis().values() for r in grupo}
        self.assertTrue(set(self.CHAVES).isdisjoint(chaves))
        for chave in self.CHAVES:
            self.assertEqual(
                self.client.get(reverse("relatorios:relatorio", args=[chave])).status_code,
                404, chave)

    def test_renderizam_e_exportam_csv(self):
        from apps.governanca import services as gov
        gov.registrar_conferencia(self.uh, "vago", usuario=self.ger)
        for chave in self.CHAVES:
            url = reverse("relatorios:relatorio", args=[chave])
            self.assertEqual(self.client.get(url).status_code, 200, chave)
            csv_resp = self.client.get(url, {"export": "csv"})
            self.assertIn("text/csv", csv_resp["Content-Type"], chave)

    def test_sem_gerencia_403(self):
        Usuario.objects.create_user(username="op", password="senha-forte-123")
        self.client.logout()
        self.client.login(username="op", password="senha-forte-123")
        for chave in self.CHAVES:
            self.assertEqual(
                self.client.get(reverse("relatorios:relatorio", args=[chave])).status_code,
                403, chave)

    def test_faxinas_mostram_tempo_medio_legivel(self):
        from apps.governanca.models import TarefaGovernanca
        agora = timezone.now()
        TarefaGovernanca.objects.create(
            uh=self.uh, camareira=self.ger, status=TarefaGovernanca.Status.CONCLUIDA,
            iniciada_em=agora - timedelta(minutes=75), concluida_em=agora)
        hoje = timezone.localdate()
        dados = services.rel_governanca_faxinas(hoje - timedelta(days=1), hoje)
        self.assertEqual(dict(dados["kpis"])["Tempo médio"], "1 h 15 min")
        self.assertEqual(dados["linhas"][0][-1], "1 h 15 min")

    def test_sem_medida_de_tempo_a_celula_diz_isso(self):
        """Zero minutos mentiria: faxina sem horário aparece como "—"."""
        hoje = timezone.localdate()
        dados = services.rel_governanca_faxinas(hoje - timedelta(days=1), hoje)
        self.assertEqual(dict(dados["kpis"])["Tempo médio"], "—")

    def test_discrepancias_tem_uma_coluna_por_tipo_de_achado(self):
        from apps.governanca.models import ConferenciaOcupacao
        hoje = timezone.localdate()
        ConferenciaOcupacao.objects.create(
            uh=self.uh, dia=hoje, visto="ocupado", pms_ocupado=False,
            divergencia=ConferenciaOcupacao.Divergencia.SLEEPER)
        dados = services.rel_governanca_discrepancias(hoje - timedelta(days=1), hoje)
        self.assertEqual(dados["colunas"][:3], ["Dia", "Conferências", "Divergências"])
        self.assertEqual(dict(dados["kpis"])["Divergências no período"], "1")
        self.assertIn("Hóspede sem check-in (sleeper)", dados["colunas"])
        self.assertEqual(dados["linhas"][0][:3], [f"{hoje:%d/%m/%Y}", "1", "1"])
