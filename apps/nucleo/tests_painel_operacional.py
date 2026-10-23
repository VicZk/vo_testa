"""Painel da recepção: datas, valores, acesso e custo de leitura com dados fictícios."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaFinanceira,
    ConfiguracaoReservas,
    ContaPagarReceber,
    ModuloContratado,
    NaturezaFiscal,
    Pessoa,
    TipoUH,
)
from apps.nucleo.modulos import Modulo
from apps.reservas.models import (
    Adiantamento,
    ContaHospedagem,
    GrupoReserva,
    LancamentoConta,
    PagamentoConta,
    Reserva,
)
from apps.reservas.services import resumo_do_dia


@override_settings(FNRH_BLOQUEAR_CHECKIN=False, ECA_BLOQUEAR_CHECKIN=False)
class PainelOperacionalTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="recepcao-painel", password="senha-forte-123")
        modulo, _ = ModuloContratado.objects.update_or_create(
            codigo=Modulo.RESERVAS, defaults={"ativo": True})
        self.usuario.modulos.add(modulo)
        self.tipo = TipoUH.objects.create(
            nome="Cabana Painel", tarifa_base=Decimal("300.00"))
        self.hoje = timezone.localdate()
        self.cfg, _ = ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={
            "feriados_automaticos": False, "iss_aliquota": Decimal("0.00"),
            "taxa_turismo_diaria": Decimal("0.00"),
        })
        self.sequencia = 0

    def reserva(self, *, status=Reserva.Status.CONFIRMADA, offset=0, noites=2,
                tipo=None, **kwargs):
        self.sequencia += 1
        uh = UH.objects.create(numero=f"P{self.sequencia:02d}", tipo=tipo or self.tipo)
        hospede = Pessoa.objects.create(nome=f"Hóspede Painel {self.sequencia:02d}")
        checkin = self.hoje + timedelta(days=offset)
        return Reserva.objects.create(
            uh=uh, hospede=hospede, checkin=checkin,
            checkout=checkin + timedelta(days=noites), status=status,
            valor_diaria=Decimal("300.00"), criado_por=self.usuario, **kwargs)

    def saida(self, *, com_conta=True, **kwargs):
        reserva = self.reserva(status=Reserva.Status.HOSPEDADA, offset=-2, **kwargs)
        if com_conta:
            ContaHospedagem.objects.create(reserva=reserva)
        return reserva

    def lancar(self, conta, valor, tipo=LancamentoConta.Tipo.DIARIA):
        return LancamentoConta.objects.create(
            conta=conta, tipo=tipo, natureza=NaturezaFiscal.SERVICO,
            descricao="Lançamento fictício do teste", valor=Decimal(valor),
            criado_por=self.usuario)

    def grupo(self):
        titular = Pessoa.objects.create(nome="Titular Grupo Painel")
        grupo = GrupoReserva.objects.create(
            rotulo="Grupo Painel", titular=titular, checkin=self.hoje,
            checkout=self.hoje + timedelta(days=2), criado_por=self.usuario)
        ContaHospedagem.objects.create(grupo=grupo)
        return grupo

    def linha(self, reserva, secao="chegadas"):
        return next(r for r in resumo_do_dia()[secao] if r.pk == reserva.pk)

    def test_listas_usam_dia_local_status_operacional_e_excluem_day_use(self):
        chegada = self.reserva(status=Reserva.Status.PRE_RESERVA)
        confirmada = self.reserva()
        saida = self.saida()
        for status in (Reserva.Status.ORCAMENTO, Reserva.Status.CANCELADA,
                       Reserva.Status.NO_SHOW, Reserva.Status.CHECKOUT,
                       Reserva.Status.HOSPEDADA):
            self.reserva(status=status)
        self.reserva(offset=1)
        self.reserva(offset=-1)
        self.reserva(status=Reserva.Status.HOSPEDADA, offset=-3)
        self.reserva(status=Reserva.Status.HOSPEDADA, offset=-1)
        tipo_day = TipoUH.objects.create(
            nome="Day Use Painel", modalidade=TipoUH.Modalidade.DAY_USE,
            tarifa_base=Decimal("90.00"), preco_day_use=Decimal("90.00"))
        self.reserva(tipo=tipo_day)
        self.saida(tipo=tipo_day)

        with patch("apps.reservas.services.timezone.localdate", return_value=self.hoje):
            resumo = resumo_do_dia()
        self.assertEqual([r.pk for r in resumo["chegadas"]], [chegada.pk, confirmada.pk])
        self.assertEqual([r.pk for r in resumo["saidas"]], [saida.pk])
        self.assertEqual(resumo["chegadas_hoje"], 2)
        self.assertEqual(resumo["saidas_hoje"], 1)

    def test_oito_linhas_preservam_totais_de_todas_as_reservas(self):
        chegadas = [self.reserva() for _ in range(10)]
        saidas = [self.saida() for _ in range(10)]
        resumo = resumo_do_dia()
        self.assertEqual([r.pk for r in resumo["chegadas"]], [r.pk for r in chegadas[:8]])
        self.assertEqual([r.pk for r in resumo["saidas"]], [r.pk for r in saidas[:8]])
        self.assertEqual(resumo["chegadas_hoje"], 10)
        self.assertEqual(resumo["saidas_hoje"], 10)

    def test_chegada_deduz_adiantamentos_liquidos_sem_multiplicar_estornos(self):
        reserva = self.reserva()
        original = Adiantamento.objects.create(reserva=reserva, valor=Decimal("100.00"))
        Adiantamento.objects.create(
            reserva=reserva, valor=Decimal("-25.00"), estorno_de=original)
        Adiantamento.objects.create(reserva=reserva, valor=Decimal("50.00"))
        outra = self.reserva()
        Adiantamento.objects.create(reserva=outra, valor=Decimal("500.00"))
        financeiro = self.linha(reserva).painel_financeiro
        self.assertEqual(financeiro["saldo"], Decimal("475.00"))
        self.assertEqual(financeiro["valor"], Decimal("475.00"))
        self.assertEqual(financeiro["estado"], "devedor")

    @override_settings(PRECO_TAXAS_ATIVAS=True)
    def test_chegada_inclui_taxas_e_centavo_da_cotacao(self):
        self.cfg.iss_aliquota = Decimal("5.00")
        self.cfg.taxa_turismo_diaria = Decimal("2.00")
        self.cfg.save()
        reserva = self.reserva(noites=3, valor_hospedagem=Decimal("900.01"))
        self.assertEqual(reserva.total_previsto(self.cfg), Decimal("951.01"))
        self.assertEqual(self.linha(reserva).painel_financeiro["saldo"], Decimal("951.01"))

    def test_chegada_distingue_sem_saldo_e_credito(self):
        for pago, estado, saldo, valor in (
            ("600.00", "sem_saldo", "0.00", "0.00"),
            ("650.00", "credito", "-50.00", "50.00"),
        ):
            with self.subTest(pago=pago):
                reserva = self.reserva()
                Adiantamento.objects.create(reserva=reserva, valor=Decimal(pago))
                financeiro = self.linha(reserva).painel_financeiro
                self.assertEqual(financeiro["estado"], estado)
                self.assertEqual(financeiro["saldo"], Decimal(saldo))
                self.assertEqual(financeiro["valor"], Decimal(valor))
                self.assertNotIn("quitad", financeiro["rotulo"].lower())

    def test_chegada_com_conta_existente_mostra_ledger_em_vez_de_recalcular_diarias(self):
        reserva = self.reserva()
        conta = ContaHospedagem.objects.create(reserva=reserva)
        self.lancar(conta, "420.00")
        PagamentoConta.objects.create(conta=conta, valor=Decimal("120.00"))
        financeiro = self.linha(reserva).painel_financeiro
        self.assertEqual(financeiro["saldo"], Decimal("300.00"))
        self.assertEqual(financeiro["referencia"], "Conta da estadia")

    def test_saida_concilia_diarias_consumos_descontos_pagamentos_e_estornos(self):
        reserva = self.saida()
        self.lancar(reserva.conta, "600.00")
        self.lancar(reserva.conta, "35.00", LancamentoConta.Tipo.CONSUMO)
        self.lancar(reserva.conta, "10.00", LancamentoConta.Tipo.TAXA)
        self.lancar(reserva.conta, "20.00", LancamentoConta.Tipo.DESCONTO)
        pagamento = PagamentoConta.objects.create(conta=reserva.conta, valor=Decimal("350.00"))
        PagamentoConta.objects.create(
            conta=reserva.conta, valor=Decimal("-50.00"), estorno_de=pagamento)
        PagamentoConta.objects.create(conta=reserva.conta, valor=Decimal("50.00"))
        sinal = Adiantamento.objects.create(reserva=reserva, valor=Decimal("100.00"))
        Adiantamento.objects.create(
            reserva=reserva, valor=Decimal("-25.00"), estorno_de=sinal)
        self.lancar(self.saida().conta, "999.00")
        financeiro = self.linha(reserva, "saidas").painel_financeiro
        self.assertEqual(reserva.conta.saldo(), Decimal("200.00"))
        self.assertEqual(financeiro["saldo"], Decimal("200.00"))
        self.assertEqual(financeiro["estado"], "devedor")
        self.assertEqual(financeiro["referencia"], "Conta da estadia")

    def test_saida_nao_confunde_credito_conta_zerada_e_conta_ausente(self):
        zerada = self.saida()
        credito = self.saida()
        PagamentoConta.objects.create(conta=credito.conta, valor=Decimal("45.00"))
        sem_conta = self.saida(com_conta=False)
        linhas = {r.pk: r.painel_financeiro for r in resumo_do_dia()["saidas"]}
        self.assertEqual(linhas[zerada.pk]["estado"], "sem_saldo")
        self.assertEqual(linhas[credito.pk]["estado"], "credito")
        self.assertEqual(linhas[credito.pk]["saldo"], Decimal("-45.00"))
        self.assertEqual(linhas[credito.pk]["valor"], Decimal("45.00"))
        self.assertEqual(linhas[sem_conta.pk]["estado"], "indisponivel")
        self.assertIsNone(linhas[sem_conta.pk]["saldo"])

    def test_grupo_chegada_nao_atribui_pagamento_do_folio_a_um_quarto(self):
        grupo = self.grupo()
        reserva = self.reserva(grupo=grupo)
        PagamentoConta.objects.create(conta=grupo.folio, valor=Decimal("600.00"))
        financeiro = self.linha(reserva).painel_financeiro
        self.assertEqual(financeiro["estado"], "grupo")
        self.assertIsNone(financeiro["saldo"])
        self.assertIsNone(financeiro["valor"])
        self.assertEqual(financeiro["grupo_url"], reverse("reservas:grupo_detalhe", args=[grupo.pk]))

    def test_grupo_saida_mostra_consumo_do_quarto_e_link_da_conta_do_grupo(self):
        grupo = self.grupo()
        reserva = self.saida(grupo=grupo)
        self.lancar(grupo.folio, "1200.00")
        financeiro = self.linha(reserva, "saidas").painel_financeiro
        self.assertEqual(financeiro["estado"], "sem_saldo")
        self.assertEqual(financeiro["saldo"], Decimal("0.00"))
        self.assertEqual(financeiro["referencia"], "Consumos do quarto")
        self.assertEqual(financeiro["grupo_url"], reverse("reservas:grupo_detalhe", args=[grupo.pk]))
        self.assertEqual(grupo.folio.saldo(), Decimal("1200.00"))

    def test_saida_faturada_sem_saldo_nao_significa_titulo_recebido(self):
        empresa = Pessoa.objects.create(nome="Empresa Painel")
        reserva = self.saida(faturamento=Reserva.Faturamento.EMPRESA, titular=empresa)
        self.lancar(reserva.conta, "600.00")
        categoria = CategoriaFinanceira.objects.create(
            nome="Hospedagem Painel", tipo=CategoriaFinanceira.Tipo.RECEITA)
        titulo = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.RECEBER, pessoa=empresa, categoria=categoria,
            descricao="Hospedagem fictícia faturada", valor=Decimal("600.00"),
            vencimento=self.hoje + timedelta(days=15))
        PagamentoConta.objects.create(
            conta=reserva.conta, conta_receber=titulo, valor=Decimal("600.00"))
        financeiro = self.linha(reserva, "saidas").painel_financeiro
        self.assertEqual(financeiro["estado"], "sem_saldo")
        self.assertNotIn("quitad", financeiro["rotulo"].lower())
        titulo.refresh_from_db()
        self.assertEqual(titulo.status, ContaPagarReceber.Status.ABERTA)

    def test_recepcao_ve_saldo_operacional_sem_acesso_ao_financeiro_geral(self):
        reserva = self.reserva()
        self.assertFalse(self.usuario.pode_area("financeiro"))
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, reserva.hospede.nome)
        self.assertContains(resposta, 'data-financeiro-estado="devedor"')
        self.assertFalse(resposta.context["tem_financeiro"])

    def test_usuario_sem_reservas_nao_recebe_nomes_saldos_ou_acoes(self):
        reserva = self.reserva()
        self.usuario.modulos.clear()
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, reserva.hospede.nome)
        self.assertNotContains(resposta, "data-financeiro-estado")
        self.assertNotContains(resposta, "#acoes-estadia")

    def test_acoes_do_painel_abrem_detalhe_sem_mutar_a_estadia(self):
        chegada, saida = self.reserva(), self.saida()
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("dashboard"))
        for reserva, secao in ((chegada, "chegadas"), (saida, "saidas")):
            with self.subTest(secao=secao):
                linha = self.linha(reserva, secao)
                esperado = reverse("reservas:detalhe", args=[reserva.pk]) + "#acoes-estadia"
                self.assertEqual(linha.painel_acao_url, esperado)
                self.assertContains(resposta, f'href="{esperado}"')
                status = reserva.status
                detalhe = self.client.get(linha.painel_acao_url)
                self.assertEqual(detalhe.status_code, 200)
                self.assertContains(detalhe, 'id="acoes-estadia"')
                reserva.refresh_from_db()
                self.assertEqual(reserva.status, status)
        self.assertFalse(ContaHospedagem.objects.filter(reserva=chegada).exists())

    def test_sem_saldo_lancado_nao_libera_checkout_com_consumo_pendente(self):
        from apps.nucleo.models import CategoriaProduto, LocalEstoque, Produto
        from apps.restaurante.models import Comanda, ItemComanda

        reserva = self.saida()
        local = LocalEstoque.objects.create(nome="Restaurante Painel", modulo="restaurante")
        categoria = CategoriaProduto.objects.create(nome="Bebidas Painel")
        produto = Produto.objects.create(nome="Água Painel", categoria=categoria)
        comanda = Comanda.objects.create(
            local=local, conta=reserva.conta, cliente=reserva.hospede,
            criado_por=self.usuario)
        ItemComanda.objects.create(
            comanda=comanda, produto=produto, descricao="Água Painel",
            natureza=NaturezaFiscal.CONSUMO, quantidade=Decimal("1.000"),
            preco_unitario=Decimal("8.00"))
        linha = self.linha(reserva, "saidas")
        self.assertEqual(linha.painel_financeiro["estado"], "sem_saldo")
        self.client.force_login(self.usuario)
        detalhe = self.client.get(linha.painel_acao_url)
        self.assertContains(detalhe, "Consumos pendentes antes da saída")
        self.assertContains(detalhe, 'disabled title="Resolva os consumos pendentes antes da saída"')
        # A mesma trava vale no servidor se um cliente enviar o POST diretamente.
        self.client.post(reverse("reservas:checkout", args=[reserva.pk]))
        reserva.refresh_from_db()
        reserva.conta.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.HOSPEDADA)
        self.assertTrue(reserva.conta.aberta)

    def test_consultas_nao_crescem_por_linha_ou_por_grupo(self):
        def criar_par():
            self.reserva(grupo=self.grupo())
            self.saida(grupo=self.grupo())

        def medir():
            with CaptureQueriesContext(connection) as consultas:
                resumo = resumo_do_dia()
                # Inclui os campos que o template percorre, para detectar lazy N+1.
                for reserva in resumo["chegadas"] + resumo["saidas"]:
                    str(reserva.hospede.nome)
                    str(reserva.uh.numero)
                    str(reserva.uh.tipo.nome)
                    str(reserva.painel_financeiro)
                    str(reserva.painel_acao_url)
            return len(consultas)

        self.reserva()
        self.saida()
        criar_par()
        poucas = medir()
        for _ in range(6):
            criar_par()
        muitas = medir()
        self.assertLessEqual(muitas, poucas, (poucas, muitas))
