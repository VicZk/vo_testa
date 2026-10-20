from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    TrilhaAuditoria,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import LancamentoConta, Reserva, Tarifa

Usuario = get_user_model()

HOJE = timezone.localdate()


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class ReservasTestsBase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_superuser(
            username="recepcao", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(
            nome="Cabana Teste", tarifa_base=Decimal("300.00")
        )
        self.uh = UH.objects.create(numero="T1", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Maria Teste")
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        # Feriado automático desligado por padrão nos testes, para que as datas
        # relativas a HOJE não caiam em feriado nacional e flutuem. Os testes que
        # exercitam o automático ligam explicitamente.
        from apps.nucleo.models import ConfiguracaoReservas
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )

    def reserva(self, status=Reserva.Status.CONFIRMADA, dias=2, uh=None, offset=0):
        checkin = HOJE + timedelta(days=offset)
        return Reserva.objects.create(
            uh=uh or self.uh,
            hospede=self.hospede,
            checkin=checkin,
            checkout=checkin + timedelta(days=dias),
            status=status,
            valor_diaria=Decimal("300.00"),
            criado_por=self.usuario,
        )

    def abrir_caixa(self):
        return SessaoCaixa.objects.create(
            operador=self.usuario, modulo="reservas", fundo_troco=Decimal("0.00")
        )


class OverbookingTests(ReservasTestsBase):
    def test_constraint_impede_periodos_sobrepostos(self):
        self.reserva(dias=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.reserva(dias=2, offset=1)  # entra no meio da primeira

    def test_checkout_libera_a_noite_para_proxima_entrada(self):
        self.reserva(dias=2)  # ocupa [hoje, hoje+2)
        # Próxima reserva entra exatamente no dia do check-out: permitido.
        proxima = self.reserva(dias=2, offset=2)
        self.assertIsNotNone(proxima.pk)

    def test_cancelada_nao_segura_uh(self):
        r = self.reserva(dias=3)
        r.cancelar(self.usuario, "Hóspede desistiu")
        # Mesmo período, agora livre.
        nova = self.reserva(dias=3)
        self.assertIsNotNone(nova.pk)

    def test_orcamento_nao_segura_uh(self):
        self.reserva(status=Reserva.Status.ORCAMENTO, dias=3)
        nova = self.reserva(dias=3)
        self.assertIsNotNone(nova.pk)

    def test_disponibilidade_via_service(self):
        self.assertTrue(services.uh_disponivel(self.uh, HOJE, HOJE + timedelta(days=2)))
        self.reserva(dias=2)
        self.assertFalse(
            services.uh_disponivel(self.uh, HOJE, HOJE + timedelta(days=2))
        )
        self.assertNotIn(
            self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2))
        )


class RetencaoExpiracaoTests(ReservasTestsBase):
    def _pre(self, expira_em):
        r = self.reserva(status=Reserva.Status.PRE_RESERVA)
        r.expira_em = expira_em
        r.save(update_fields=["expira_em"])
        return r

    def test_prereserva_vencida_nao_bloqueia(self):
        self._pre(timezone.now() - timedelta(minutes=1))
        # o quarto já aparece livre, mesmo antes do job rodar
        self.assertIn(self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2)))

    def test_prereserva_valida_bloqueia(self):
        self._pre(timezone.now() + timedelta(minutes=20))
        self.assertNotIn(self.uh, services.uhs_disponiveis(HOJE, HOJE + timedelta(days=2)))

    def test_expirar_vencidas_cancela(self):
        r = self._pre(timezone.now() - timedelta(minutes=1))
        n = services.expirar_vencidas()
        r.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(r.status, Reserva.Status.CANCELADA)

    def test_confirmar_limpa_expira_em(self):
        r = self._pre(timezone.now() - timedelta(minutes=1))
        r.confirmar(self.usuario)
        r.refresh_from_db()
        self.assertIsNone(r.expira_em)
        self.assertEqual(services.expirar_vencidas(), 0)  # confirmada não expira


    def test_criar_reserva_site_grava_prazo(self):
        r = services.criar_reserva_site(
            tipo_uh=self.tipo, checkin=HOJE + timedelta(days=1),
            checkout=HOJE + timedelta(days=3), hospede=self.hospede,
            usuario=self.usuario,
        )
        self.assertIsNotNone(r.expira_em)
        self.assertGreater(r.expira_em, timezone.now())


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class SaidasVencidasTests(ReservasTestsBase):
    """Saídas atrasadas alimentam o painel; fechar é sempre do atendente."""

    def _hospedar_vencida(self, dias=2, offset=-5, uh=None):
        r = self.reserva(status=Reserva.Status.CONFIRMADA, dias=dias, offset=offset, uh=uh)
        r.fazer_checkin(self.usuario)
        return r

    def test_com_saldo_entra_em_com_saldo(self):
        r = self._hospedar_vencida()  # diárias em aberto
        res = services.saidas_vencidas()
        self.assertIn(r, res["com_saldo"])
        self.assertNotIn(r, res["quitadas"])
        self.assertEqual(res["total_aberto"], r.conta.saldo())

    def test_quitada_entra_em_quitadas(self):
        self.abrir_caixa()
        r = self._hospedar_vencida()
        services.receber_pagamento(r.conta, self.usuario, self.dinheiro, r.conta.saldo())
        res = services.saidas_vencidas()
        self.assertIn(r, res["quitadas"])
        self.assertNotIn(r, res["com_saldo"])

    def test_dentro_do_prazo_nao_aparece(self):
        r = self.reserva(status=Reserva.Status.CONFIRMADA, dias=3, offset=-1)
        r.fazer_checkin(self.usuario)  # saída amanhã, ainda não venceu
        res = services.saidas_vencidas()
        self.assertNotIn(r, res["com_saldo"])
        self.assertNotIn(r, res["quitadas"])

    def test_helper_nao_altera_status(self):
        r = self._hospedar_vencida()
        services.saidas_vencidas()
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)


class TarifaTests(ReservasTestsBase):
    def test_tarifa_por_temporada_com_precedencia(self):
        Temporada.objects.create(
            nome="Alta verão", classificacao="alta",
            inicio=HOJE, fim=HOJE + timedelta(days=30),
        )
        Temporada.objects.create(
            nome="Feriadão", classificacao="feriado",
            inicio=HOJE, fim=HOJE + timedelta(days=2),
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="alta", valor=Decimal("400.00")
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="feriado", valor=Decimal("500.00")
        )
        # Feriado tem precedência sobre alta
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE), Decimal("500.00")
        )
        # Depois do feriado, vale a alta
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE + timedelta(days=5)),
            Decimal("400.00"),
        )

    def test_sem_temporada_usa_tarifa_base(self):
        self.assertEqual(
            services.tarifa_do_dia(self.tipo, HOJE), Decimal("300.00")
        )

    def test_preco_por_quarto_vence_o_tipo_na_temporada(self):
        from apps.reservas.models import TarifaUnidade
        Temporada.objects.create(
            nome="Alta", classificacao="alta", inicio=HOJE, fim=HOJE + timedelta(days=10)
        )
        Tarifa.objects.create(tipo_uh=self.tipo, classificacao="alta", valor=Decimal("400.00"))
        # sem preço do quarto → usa o do tipo na temporada
        self.assertEqual(services.tarifa_da_unidade(self.uh, HOJE), Decimal("400.00"))
        # com preço do quarto na temporada → vence
        TarifaUnidade.objects.create(uh=self.uh, classificacao="alta", valor=Decimal("450.00"))
        self.assertEqual(services.tarifa_da_unidade(self.uh, HOJE), Decimal("450.00"))
        # fora da temporada → cai na base do tipo
        self.assertEqual(
            services.tarifa_da_unidade(self.uh, HOJE + timedelta(days=60)), Decimal("300.00")
        )

    def test_diaria_media_do_periodo(self):
        Temporada.objects.create(
            nome="Feriadão", classificacao="feriado",
            inicio=HOJE, fim=HOJE,  # só a primeira noite
        )
        Tarifa.objects.create(
            tipo_uh=self.tipo, classificacao="feriado", valor=Decimal("500.00")
        )
        # 1 noite a 500 + 1 noite a 300 = média 400
        media = services.diaria_media(self.tipo, HOJE, HOJE + timedelta(days=2))
        self.assertEqual(media, Decimal("400.00"))

    def test_classificacao_por_dia_da_semana_e_feriado(self):
        import datetime
        seg = datetime.date(2026, 11, 9)   # segunda-feira comum (não feriado)
        sab = datetime.date(2026, 10, 31)  # sábado
        self.assertEqual((seg.weekday(), sab.weekday()), (0, 5))
        # Baixa nas noites de seg–qui; Alta nas de sex–dom (mesmo período).
        Temporada.objects.create(
            nome="Baixa", classificacao="baixa", dias_semana=[0, 1, 2, 3],
            inicio=datetime.date(2026, 1, 1), fim=datetime.date(2026, 12, 31),
        )
        Temporada.objects.create(
            nome="Alta", classificacao="alta", dias_semana=[4, 5, 6],
            inicio=datetime.date(2026, 1, 1), fim=datetime.date(2026, 12, 31),
        )
        # Feriado em data específica: sem dias marcados = vale o dia todo.
        Temporada.objects.create(
            nome="Feriados", classificacao="feriado", dias_semana=[],
            inicio=sab, fim=sab,
        )
        # Segunda/quinta comuns → baixa; sexta comum → alta.
        self.assertEqual(services.classificacao_do_dia(seg), "baixa")
        self.assertEqual(
            services.classificacao_do_dia(datetime.date(2026, 10, 29)), "baixa")
        self.assertEqual(
            services.classificacao_do_dia(datetime.date(2026, 10, 30)), "alta")
        # Sábado seria alta, mas é feriado → precedência do feriado.
        self.assertEqual(services.classificacao_do_dia(sab), "feriado")

    def test_feriado_automatico(self):
        import datetime
        from apps.nucleo.feriados import eh_feriado
        from apps.nucleo.models import ConfiguracaoReservas
        # Cálculo do calendário (nacional + Itá, móveis pela Páscoa).
        self.assertEqual(eh_feriado(datetime.date(2026, 12, 25)), "Natal")
        self.assertEqual(eh_feriado(datetime.date(2026, 12, 13)), "Aniversário de Itá")
        self.assertEqual(eh_feriado(datetime.date(2027, 2, 9)), "Carnaval")
        self.assertIsNone(eh_feriado(datetime.date(2026, 11, 9)))  # segunda comum
        # Ligado (sem NENHUMA temporada cadastrada): o feriado já classifica.
        cfg = ConfiguracaoReservas.carregar()
        cfg.feriados_automaticos = True
        cfg.save()
        self.assertEqual(
            services.classificacao_do_dia(datetime.date(2026, 12, 25)), "feriado")
        self.assertEqual(
            services.classificacao_do_dia(datetime.date(2026, 12, 13)), "feriado")
        # Desligado: deixa de classificar automaticamente.
        cfg.feriados_automaticos = False
        cfg.save()
        self.assertIsNone(
            services.classificacao_do_dia(datetime.date(2026, 12, 25)))

    def test_feriado_automatico_singleton_default_ligado(self):
        from apps.nucleo.models import ConfiguracaoReservas
        # setUp zera para False; aqui garantimos que o default do model é True.
        ConfiguracaoReservas.objects.all().delete()
        self.assertTrue(ConfiguracaoReservas.carregar().feriados_automaticos)
        self.assertEqual(ConfiguracaoReservas.objects.count(), 1)  # singleton

    def test_preco_unidade_noite_base_adicional_e_feriado_especifico(self):
        import datetime
        from apps.reservas.models import TarifaTemporada, TarifaUnidade
        seg = datetime.date(2026, 11, 9)  # segunda comum
        Temporada.objects.create(
            nome="Baixa", classificacao="baixa", dias_semana=[0, 1, 2, 3],
            inicio=datetime.date(2026, 1, 1), fim=datetime.date(2026, 12, 31),
        )
        TarifaUnidade.objects.create(
            uh=self.uh, classificacao="baixa",
            valor=Decimal("900.00"), pessoa_adicional=Decimal("400.00"),
        )
        # (base, adicional, meia) — meia vazia = metade do adicional.
        self.assertEqual(
            services.preco_unidade_noite(self.uh, seg),
            (Decimal("900.00"), Decimal("400.00"), Decimal("200.00")),
        )
        # Feriado específico (Natal) tem preço próprio e vence tudo na data dele;
        # meia explícita.
        natal = Temporada.objects.create(
            nome="Natal", classificacao="feriado", dias_semana=[],
            inicio=datetime.date(2026, 12, 25), fim=datetime.date(2026, 12, 25),
        )
        TarifaTemporada.objects.create(
            temporada=natal, uh=self.uh, valor=Decimal("2200.00"),
            pessoa_adicional=Decimal("800.00"), meia=Decimal("500.00"),
        )
        self.assertEqual(
            services.preco_unidade_noite(self.uh, datetime.date(2026, 12, 25)),
            (Decimal("2200.00"), Decimal("800.00"), Decimal("500.00")),
        )
        # adicional vazio na tarifa → cai no do tipo; meia = metade dele.
        self.tipo.pessoa_adicional = Decimal("150.00")
        self.tipo.save()
        TarifaUnidade.objects.filter(uh=self.uh, classificacao="baixa").update(
            pessoa_adicional=None)
        self.assertEqual(
            services.preco_unidade_noite(self.uh, seg),
            (Decimal("900.00"), Decimal("150.00"), Decimal("75.00")),
        )

    def test_cotacao_linear_por_numero_de_adultos(self):
        import datetime
        from apps.reservas import precos
        from apps.reservas.models import TarifaUnidade
        Temporada.objects.create(
            nome="Baixa", classificacao="baixa", dias_semana=[0, 1, 2, 3],
            inicio=datetime.date(2026, 1, 1), fim=datetime.date(2026, 12, 31),
        )
        TarifaUnidade.objects.create(
            uh=self.uh, classificacao="baixa",
            valor=Decimal("900.00"), pessoa_adicional=Decimal("400.00"),
        )
        ci, co = datetime.date(2026, 11, 9), datetime.date(2026, 11, 11)  # 2 noites seg/ter
        # 4 adultos: 900 + 2×400 = 1700/noite (igual à tabela de vendas).
        cot = precos.cotacao(uh=self.uh, checkin=ci, checkout=co, adultos=4,
                             cobra_iss=False, cobra_taxa_turismo=False)
        self.assertEqual(cot["media_noite"], Decimal("1700.00"))
        self.assertEqual(cot["hospedagem"], Decimal("3400.00"))
        # Hóspede sozinho = 70% da base de 2 pax (PRECO_SINGLE_FATOR).
        cot1 = precos.cotacao(uh=self.uh, checkin=ci, checkout=co, adultos=1,
                              cobra_iss=False, cobra_taxa_turismo=False)
        self.assertEqual(cot1["media_noite"], Decimal("630.00"))  # 900 × 0.70

    def test_meia_dayuse_e_nao_reembolsavel(self):
        import datetime
        from apps.nucleo.models import ConfiguracaoReservas
        from apps.nucleo.models.cadastros import TipoUH
        from apps.reservas import precos
        from apps.reservas.models import TarifaDayUse, TarifaUnidade
        Temporada.objects.create(
            nome="Baixa", classificacao="baixa", dias_semana=[0, 1, 2, 3],
            inicio=datetime.date(2026, 1, 1), fim=datetime.date(2026, 12, 31),
        )
        TarifaUnidade.objects.create(
            uh=self.uh, classificacao="baixa", valor=Decimal("900.00"),
            pessoa_adicional=Decimal("400.00"), meia=Decimal("150.00"),
        )
        ci, co = datetime.date(2026, 11, 9), datetime.date(2026, 11, 10)  # 1 noite baixa
        # 2 adultos + 1 criança 6-15 com meia explícita: 900 + 150 = 1050.
        cot = precos.cotacao(uh=self.uh, checkin=ci, checkout=co, adultos=2,
                             criancas_6_15=1, cobra_iss=False, cobra_taxa_turismo=False)
        self.assertEqual(cot["hospedagem"], Decimal("1050.00"))
        # Não-reembolsável −12%: 900 → 792; desconto 108.
        cotnr = precos.cotacao(uh=self.uh, checkin=ci, checkout=co, adultos=2,
                               cobra_iss=False, cobra_taxa_turismo=False,
                               nao_reembolsavel=True)
        self.assertEqual(cotnr["hospedagem"], Decimal("792.00"))
        self.assertEqual(cotnr["desconto_nao_reembolsavel"], Decimal("108.00"))
        # Day use por pessoa × temporada; criança ≤5 não paga, 6-15 = meia.
        dt = TipoUH.objects.create(
            nome="Dia", modalidade=TipoUH.Modalidade.DAY_USE, tarifa_base=Decimal("0.00"))
        TarifaDayUse.objects.create(
            classificacao="baixa", valor_adulto=Decimal("120.00"), valor_meia=Decimal("60.00"))
        cotd = precos.cotacao(tipo=dt, checkin=ci, checkout=ci, adultos=3,
                              criancas_6_15=2, criancas_0_5=1,
                              cobra_iss=False, cobra_taxa_turismo=False)
        self.assertEqual(cotd["hospedagem"], Decimal("480.00"))  # 3×120 + 2×60


class TarifaUnidadeTests(ReservasTestsBase):
    """Tarifa por unidade (Passo 3): duplo cobra mais, override vence, mínimo real."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import PosicaoCama
        # self.uh (T1) é simples; cria um duplo do mesmo tipo (base 300 → 480).
        self.duplo = UH.objects.create(numero="T-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)

    def test_simples_fica_na_base_do_tipo(self):
        self.assertEqual(services.tarifa_da_unidade(self.uh, HOJE), Decimal("300.00"))

    def test_duplo_recebe_acrescimo_arredondado(self):
        # 300 × 1.6 = 480, arredondado à dezena.
        self.assertEqual(services.tarifa_da_unidade(self.duplo, HOJE), Decimal("480"))

    def test_override_vence_o_calculo(self):
        self.duplo.tarifa_override = Decimal("399.00")
        self.duplo.save()
        self.assertEqual(services.tarifa_da_unidade(self.duplo, HOJE), Decimal("399.00"))

    def test_tarifa_minima_do_tipo_e_o_menor_real(self):
        # Tipo tem o simples (300) e o duplo (480) → mínimo real = 300.
        self.assertEqual(services.tarifa_minima_do_tipo(self.tipo), Decimal("300.00"))

    def test_tarifa_minima_nunca_abaixo_de_qualquer_unidade(self):
        # Se todas as unidades são duplas, o "a partir de" não pode ser a base 300.
        self.uh.delete()  # sobra só o duplo
        self.assertEqual(services.tarifa_minima_do_tipo(self.tipo), Decimal("480"))


class CicloDeEstadosTests(ReservasTestsBase):
    def test_checkin_abre_conta_e_lanca_diarias_como_servico(self):
        r = self.reserva(dias=3)
        conta = r.fazer_checkin(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)
        self.assertEqual(conta.lancamentos.count(), 3)
        self.assertTrue(
            all(
                lanc.natureza == "servico" and lanc.tipo == "diaria"
                for lanc in conta.lancamentos.all()
            )
        )
        self.assertEqual(conta.total_lancamentos(), Decimal("900.00"))

    def test_checkout_exige_saldo_zero(self):
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        with self.assertRaises(ValidationError):
            r.fazer_checkout(self.usuario)  # 300 em aberto
        self.abrir_caixa()
        services.receber_pagamento(
            r.conta, self.usuario, self.dinheiro, Decimal("300.00")
        )
        # Saldo zerado é o único requisito de saída (sem trava de frigobar).
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)
        self.assertFalse(r.conta.aberta)

    def test_checkin_bloqueado_se_quarto_sujo(self):
        from apps.governanca.models import StatusLimpeza
        from apps.governanca.services import definir_status

        definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.usuario)
        r = self.reserva(dias=1)
        with self.assertRaises(ValidationError) as ctx:
            r.fazer_checkin(self.usuario)
        self.assertIn("limpo", str(ctx.exception).lower())
        definir_status(self.uh, StatusLimpeza.Situacao.LIMPA, self.usuario)
        conta = r.fazer_checkin(self.usuario)
        self.assertIsNotNone(conta)

    def test_checkin_sem_governanca_nao_bloqueia(self):
        from apps.governanca.models import StatusLimpeza
        from apps.governanca.services import definir_status

        definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.usuario)
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        r = self.reserva(dias=1)
        self.assertIsNotNone(r.fazer_checkin(self.usuario))

    def test_checkout_so_depende_do_saldo(self):
        # Não há consumo de frigobar: com a conta zerada, a saída é liberada.
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        self.abrir_caixa()
        services.receber_pagamento(
            r.conta, self.usuario, self.dinheiro, r.conta.saldo()
        )
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)

    def test_cancelamento_exige_motivo_e_audita(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            r.cancelar(self.usuario, "   ")
        r.cancelar(self.usuario, "Imprevisto do hóspede")
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="cancelamento_reserva").exists()
        )

    def test_hospedada_nao_pode_ser_cancelada(self):
        r = self.reserva(dias=1)
        r.fazer_checkin(self.usuario)
        with self.assertRaises(ValidationError):
            r.cancelar(self.usuario, "Tarde demais")

    def test_no_show_so_de_confirmada(self):
        r = self.reserva(status=Reserva.Status.PRE_RESERVA)
        with self.assertRaises(ValidationError):
            r.marcar_no_show(self.usuario)
        r.confirmar(self.usuario)
        r.marcar_no_show(self.usuario)
        self.assertEqual(r.status, Reserva.Status.NO_SHOW)


class ContaHospedagemTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        self.r = self.reserva(dias=2)
        self.conta = self.r.fazer_checkin(self.usuario)  # 600 em diárias (serviço)

    def test_lancamento_exige_natureza(self):
        with self.assertRaises(ValidationError):
            LancamentoConta(
                conta=self.conta, tipo="consumo", natureza="",
                descricao="Sem natureza", valor=Decimal("10.00"),
                criado_por=self.usuario,
            ).save()

    def test_subtotais_por_natureza(self):
        services.lancar_na_conta(
            self.conta, "consumo", "consumo", "Frigobar", Decimal("50.00"), self.usuario
        )
        services.lancar_na_conta(
            self.conta, "servico", "servico", "Lavanderia", Decimal("40.00"), self.usuario
        )
        services.lancar_na_conta(
            self.conta, "desconto", "servico", "Cortesia diária", Decimal("100.00"),
            self.usuario,
        )
        totais = self.conta.total_por_natureza()
        self.assertEqual(totais["Serviço"], Decimal("540.00"))  # 600+40−100
        self.assertEqual(totais["Consumo"], Decimal("50.00"))
        self.assertEqual(self.conta.total_lancamentos(), Decimal("590.00"))

    def test_lancamento_imutavel(self):
        lanc = self.conta.lancamentos.first()
        lanc.valor = Decimal("1.00")
        with self.assertRaises(ValidationError):
            lanc.save()
        with self.assertRaises(ValidationError):
            lanc.delete()

    def test_pagamento_passa_pelo_caixa_do_operador(self):
        # Sem caixa aberto: recusa.
        with self.assertRaises(ValidationError):
            services.receber_pagamento(
                self.conta, self.usuario, self.dinheiro, Decimal("100.00")
            )
        sessao = self.abrir_caixa()
        pagamento = services.receber_pagamento(
            self.conta, self.usuario, self.dinheiro, Decimal("100.00")
        )
        self.assertEqual(pagamento.movimento_caixa.sessao, sessao)
        self.assertEqual(sessao.esperado_em_dinheiro(), Decimal("100.00"))
        self.assertEqual(self.conta.saldo(), Decimal("500.00"))

    def test_adiantamento_vira_credito_na_conta(self):
        r2 = self.reserva(dias=2, offset=10)
        self.abrir_caixa()
        services.receber_adiantamento(
            r2, self.usuario, self.dinheiro, Decimal("200.00")
        )
        conta = r2.fazer_checkin(self.usuario)  # 600 de diárias
        self.assertEqual(conta.saldo(), Decimal("400.00"))

    def test_adiantamento_so_antes_do_checkin(self):
        self.abrir_caixa()
        with self.assertRaises(ValidationError):
            services.receber_adiantamento(
                self.r, self.usuario, self.dinheiro, Decimal("50.00")
            )


class PermissaoModuloTests(ReservasTestsBase):
    def test_view_exige_modulo_atribuido(self):
        Usuario.objects.create_user(username="sem-acesso", password="senha-forte-123")
        self.client.login(username="sem-acesso", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa"))
        self.assertEqual(resposta.status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa"))
        self.assertEqual(resposta.status_code, 404)

    def test_mapa_e_lista_carregam(self):
        self.reserva(dias=2)
        self.client.login(username="recepcao", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("reservas:mapa")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reservas:lista")).status_code, 200)

    def test_mapa_agrupa_por_ala(self):
        from apps.nucleo.models import UH
        from apps.nucleo.models.cadastros import TipoUH
        tp = TipoUH.objects.create(nome="Cabana", tarifa_base=Decimal("300.00"))
        UH.objects.create(numero="Quarto 01", tipo=tp)   # Embaixo da Recepção
        UH.objects.create(numero="Quarto 16", tipo=tp)   # Condado dos Hobbits
        self.client.login(username="recepcao", password="senha-forte-123")
        r = self.client.get(reverse("reservas:mapa"))
        titulos = [g["titulo"] for g in r.context["grupos"]]
        self.assertIn("Embaixo da Recepção", titulos)
        self.assertIn("Condado dos Hobbits", titulos)
        # Ordem oficial: Recepção antes do Condado.
        self.assertLess(titulos.index("Embaixo da Recepção"),
                        titulos.index("Condado dos Hobbits"))

    def test_diaria_manual_exige_gerencia(self):
        operadora = Usuario.objects.create_user(
            username="operadora", password="senha-forte-123"
        )
        operadora.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        self.client.login(username="operadora", password="senha-forte-123")
        resposta = self.client.post(
            reverse("reservas:nova"),
            {
                "hospede": self.hospede.pk,
                "uh": self.uh.pk,
                "checkin": HOJE.isoformat(),
                "checkout": (HOJE + timedelta(days=2)).isoformat(),
                "adultos": 2,
                "criancas": 0,
                "canal": "balcao",
                "faturamento": "particular",
                "valor_diaria": "100.00",  # abaixo da tarifa vigente (300)
                "observacoes": "",
            },
        )
        self.assertContains(resposta, "exige gerência")
        self.assertEqual(Reserva.objects.count(), 0)


class FaturamentoTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        from apps.nucleo.models import Agencia
        self.agencia_pessoa = Pessoa.objects.create(
            nome="Agência CVC", tipo=Pessoa.Tipo.JURIDICA
        )
        Agencia.objects.create(pessoa=self.agencia_pessoa)

    def test_particular_pagador_e_o_hospede(self):
        r = self.reserva()
        self.assertEqual(r.faturamento, Reserva.Faturamento.PARTICULAR)
        self.assertEqual(r.pagador, self.hospede)

    def test_faturamento_agencia_exige_titular(self):
        r = Reserva(
            uh=self.uh, hospede=self.hospede,
            checkin=HOJE, checkout=HOJE + timedelta(days=2),
            faturamento=Reserva.Faturamento.AGENCIA,
            valor_diaria=Decimal("300.00"), criado_por=self.usuario,
        )
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_faturamento_agencia_pagador_e_o_titular(self):
        r = self.reserva()
        r.faturamento = Reserva.Faturamento.AGENCIA
        r.titular = self.agencia_pessoa
        r.full_clean()
        r.save()
        self.assertEqual(r.pagador, self.agencia_pessoa)

    def test_particular_zera_titular(self):
        r = self.reserva()
        r.titular = self.agencia_pessoa
        r.faturamento = Reserva.Faturamento.PARTICULAR
        r.full_clean()  # clean() deve limpar o titular
        self.assertIsNone(r.titular)


class MapaQuartosTests(ReservasTestsBase):
    def test_situacoes_no_mapa(self):
        # ocupada (hospedada), bloqueada e livre
        r = self.reserva(dias=2)
        r.fazer_checkin(self.usuario)
        UH.objects.create(numero="B1", tipo=self.tipo, status=UH.Status.BLOQUEADA)
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("reservas:mapa_quartos"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Ocupada")
        self.assertContains(resposta, "Bloqueada")
        self.assertContains(resposta, self.hospede.nome[:18])

    def test_exige_modulo(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("reservas:mapa_quartos")).status_code, 403
        )


class TrocaQuartoTests(ReservasTestsBase):
    def test_troca_leva_a_conta(self):
        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)  # 600 em diárias
        outro = UH.objects.create(numero="T2", tipo=self.tipo)
        services.trocar_quarto(r, outro, self.usuario, "pedido do hóspede")
        r.refresh_from_db()
        self.assertEqual(r.uh, outro)
        self.assertEqual(r.conta.pk, conta.pk)  # mesma conta
        self.assertEqual(r.conta.total_lancamentos(), Decimal("600.00"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="troca_quarto").exists())

    def test_troca_bloqueada_por_overbooking(self):
        r = self.reserva(dias=3)
        outro = UH.objects.create(numero="T2", tipo=self.tipo)
        Reserva.objects.create(
            uh=outro, hospede=self.hospede, checkin=HOJE,
            checkout=HOJE + timedelta(days=3), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("300"), criado_por=self.usuario,
        )
        with self.assertRaises(ValidationError):
            services.trocar_quarto(r, outro, self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.uh, self.uh)

    def test_troca_exige_quarto_diferente(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            services.trocar_quarto(r, self.uh, self.usuario)


class RateioPagamentoTests(ReservasTestsBase):
    def test_dois_pagamentos_parciais_com_pagadores(self):
        # Rateio: a conta aceita vários pagamentos parciais até o saldo zerar.
        self.abrir_caixa()
        forma = FormaPagamento.objects.get(tipo="dinheiro")
        r = self.reserva(status=Reserva.Status.CONFIRMADA)  # 2 diárias × 300 = 600
        conta = r.fazer_checkin(self.usuario)
        services.receber_pagamento(conta, self.usuario, forma, Decimal("300"), observacao="Casal A")
        services.receber_pagamento(conta, self.usuario, forma, Decimal("300"), observacao="Casal B")
        self.assertEqual(conta.pagamentos.count(), 2)
        self.assertEqual(conta.saldo(), Decimal("0.00"))
        self.assertEqual(
            set(conta.pagamentos.values_list("observacao", flat=True)),
            {"Casal A", "Casal B"},
        )


class ColchaoExtraTests(ReservasTestsBase):
    """Colchão extra: quantidade, cotação itemizada e lançamento na conta (Passo 4)."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ConfiguracaoUH, PosicaoCama
        # Duplo com sofá e 2 colchões: incluído = 4 (fixa) + 1 (sofá) = 5.
        self.duplo = UH.objects.create(numero="T-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(
            uh=self.duplo, tem_sofa_cama=True, max_colchoes_extras=2,
            tarifa_colchao_extra=Decimal("80.00"),
        )

    def test_extras_para_dentro_da_capacidade_e_zero(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 5), 0)  # cabe nas camas incluídas

    def test_extras_para_limitado_ao_maximo(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 7), 2)   # 7-5=2
        self.assertEqual(extras_para(self.duplo, 12), 2)  # nunca acima do máximo

    def test_extras_para_nunca_negativo(self):
        from apps.nucleo.estrutura import extras_para
        self.assertEqual(extras_para(self.duplo, 1), 0)

    def test_checkin_nao_cobra_colchao(self):
        # Fase 6: o colchão virou só disponibilidade — não há mais linha de cobrança.
        r = self.reserva(uh=self.duplo, dias=2)
        r.adultos, r.criancas = 6, 1  # 7 pessoas (antes gerava colchão)
        r.save()
        conta = r.fazer_checkin(self.usuario)
        self.assertFalse(
            conta.lancamentos.filter(descricao__startswith="Colchão").exists()
        )
        # Só as diárias (taxas desligadas em teste via PRECO_TAXAS_ATIVAS).
        self.assertEqual(conta.total_lancamentos(), r.valor_diaria * 2)

    def test_colchoes_extras_service_para_governanca(self):
        r = self.reserva(uh=self.duplo, dias=1)
        r.adultos, r.criancas = 5, 2  # 7 → 2
        r.save()
        self.assertEqual(services.colchoes_extras(r), 2)


@override_settings(PRECO_TAXAS_ATIVAS=True, FNRH_BLOQUEAR_CHECKIN=False,
                   PRECO_ISS_ALIQUOTA="4.0", PRECO_TAXA_TURISMO_DIARIA="4.00")
class TaxasNoCheckinTests(ReservasTestsBase):
    """Fase 6 — ISS + taxa de turismo lançados no check-in (flag ligada em produção)."""

    def test_checkin_lanca_iss_e_turismo(self):
        r = self.reserva(dias=2)  # diária 300 × 2 = 600 de hospedagem
        conta = r.fazer_checkin(self.usuario)
        iss = conta.lancamentos.filter(descricao__startswith="ISS").first()
        tur = conta.lancamentos.filter(descricao__startswith="Taxa de turismo").first()
        self.assertIsNotNone(iss)
        self.assertEqual(iss.valor, Decimal("24.00"))    # 4% × 600
        self.assertEqual(tur.valor, Decimal("8.00"))     # R$4 × 2 noites
        self.assertEqual(conta.total_lancamentos(), Decimal("632.00"))

    def test_desmarcar_taxas_nao_lanca(self):
        r = self.reserva(dias=2)
        r.cobra_iss = False
        r.cobra_taxa_turismo = False
        r.save()
        conta = r.fazer_checkin(self.usuario)
        self.assertEqual(conta.total_lancamentos(), Decimal("600.00"))


class GrupoReservaTests(ReservasTestsBase):
    """Reserva-mãe com filhas por quarto e folio híbrido (Passo 5)."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ConfiguracaoUH, PosicaoCama
        self.qa = UH.objects.create(numero="G-A", tipo=self.tipo)
        self.qb = UH.objects.create(numero="G-B", tipo=self.tipo)
        # Duplo com sofá + 2 colchões para testar o colchão no folio-mãe.
        self.duplo = UH.objects.create(numero="G-DUP", tipo=self.tipo)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=self.duplo, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(
            uh=self.duplo, tem_sofa_cama=True, max_colchoes_extras=2,
            tarifa_colchao_extra=Decimal("80.00"),
        )
        self.h2 = Pessoa.objects.create(nome="João Bloco")
        self.h3 = Pessoa.objects.create(nome="Ana Bloco")

    def _grupo(self, dias=2):
        return services.criar_grupo(
            rotulo="Grupo Teste", titular=self.hospede,
            checkin=HOJE, checkout=HOJE + timedelta(days=dias), usuario=self.usuario,
        )

    def test_criar_grupo_abre_folio(self):
        grupo = self._grupo()
        self.assertTrue(hasattr(grupo, "folio"))
        self.assertIsNone(grupo.folio.reserva_id)

    def test_contas_abertas_ignora_folio_de_grupo(self):
        """O folio-mãe é conta aberta SEM reserva; não pode aparecer em
        contas_abertas() — senão os PDVs quebram em c.reserva.uh (crash 500)."""
        grupo = self._grupo()
        pks = [c.pk for c in services.contas_abertas()]
        self.assertNotIn(grupo.folio.pk, pks)
        for c in services.contas_abertas():
            self.assertIsNotNone(c.reserva)  # c.reserva.uh nunca estoura

    def test_adicionar_quartos_e_antioverbooking(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        self.assertEqual(grupo.filhas.count(), 2)
        self.assertEqual(f1.grupo_id, grupo.pk)
        # O mesmo quarto no mesmo período é recusado.
        with self.assertRaises(ValidationError):
            services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h3, usuario=self.usuario)

    def test_grupo_quarto_preco_por_pessoa(self):
        # Fase 7/grupos: a diária do quarto do grupo vem pela motor (pessoa adicional).
        self.tipo.pessoa_adicional = Decimal("50.00")
        self.tipo.save(update_fields=["pessoa_adicional"])
        grupo = self._grupo()
        f = services.adicionar_quarto(
            grupo, uh=self.duplo, hospede=self.h2, usuario=self.usuario, adultos=3)
        # duplo base 480 (fator duplo) + (3−2)×50 = 530.
        self.assertEqual(f.valor_diaria, Decimal("530.00"))

    def test_grupo_quarto_respeita_trava_colchoes(self):
        from apps.reservas.models import ColchoesExtra
        pool = ColchoesExtra.atual()  # garante a linha
        pool.quantidade = 0
        pool.save()  # pool esgotado
        grupo = self._grupo()
        with self.assertRaises(ValidationError):
            # 7 pessoas no duplo exigem colchão extra — sem pool, bloqueia.
            services.adicionar_quarto(
                grupo, uh=self.duplo, hospede=self.h2, usuario=self.usuario, adultos=7)

    def test_diaria_no_folio_consumo_no_quarto(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        grupo.refresh_from_db()
        # 2 noites × 300 no folio-mãe; conta do quarto começa zerada.
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("600.00"))
        self.assertEqual(f1.conta.total_lancamentos(), Decimal("0.00"))
        # Consumo vai para a conta do quarto, não para o folio.
        from apps.nucleo.models import NaturezaFiscal
        services.lancar_na_conta(
            f1.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Frigobar", Decimal("50.00"), self.usuario,
        )
        self.assertEqual(f1.conta.total_lancamentos(), Decimal("50.00"))
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("600.00"))

    def test_diarias_vao_ao_folio_mae_sem_colchao(self):
        grupo = self._grupo()
        f = services.adicionar_quarto(
            grupo, uh=self.duplo, hospede=self.h2, usuario=self.usuario,
            adultos=6, criancas=1,  # 7 pessoas (antes gerava colchão)
        )
        services.confirmar_grupo(grupo.pk, self.usuario)
        f.refresh_from_db()
        f.fazer_checkin(self.usuario)
        # duplo: diária 480 × 2 = 960 no folio-mãe; colchão não cobra mais (Fase 6).
        self.assertEqual(grupo.folio.total_lancamentos(), Decimal("960.00"))
        self.assertFalse(
            grupo.folio.lancamentos.filter(descricao__startswith="Colchão").exists()
        )
        self.assertEqual(f.conta.total_lancamentos(), Decimal("0.00"))

    def test_checkout_quarto_com_folio_aberto(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        from apps.nucleo.models import NaturezaFiscal
        services.lancar_na_conta(
            f1.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Frigobar", Decimal("50.00"), self.usuario,
        )
        self.abrir_caixa()
        services.receber_pagamento(f1.conta, self.usuario, self.dinheiro, Decimal("50.00"))
        # Check-out do quarto passa mesmo com o folio-mãe (diárias) aberto.
        f1.fazer_checkout(self.usuario)
        f1.refresh_from_db()
        self.assertEqual(f1.status, Reserva.Status.CHECKOUT)
        self.assertTrue(grupo.folio.aberta)

    def test_confirmar_grupo_confirma_todas(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CONFIRMADA).count(), 2
        )
        grupo.refresh_from_db()
        self.assertIsNone(grupo.expira_em)

    def test_cancelar_grupo_cascata(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.cancelar_grupo(grupo, self.usuario, "Cliente desistiu")
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CANCELADA).count(), 2
        )

    def test_remover_do_grupo_encolhe(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        services.remover_do_grupo(f1, self.usuario, "Um quarto a menos")
        f1.refresh_from_db()
        self.assertEqual(f1.status, Reserva.Status.CANCELADA)
        self.assertEqual(grupo.filhas_ativas.count(), 1)

    def test_encerrar_grupo_exige_folio_zerado(self):
        grupo = self._grupo()
        f1 = services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.confirmar_grupo(grupo.pk, self.usuario)
        f1.refresh_from_db()
        f1.fazer_checkin(self.usuario)
        f1.fazer_checkout(self.usuario)  # sem consumo, conta do quarto zerada
        # Folio tem as diárias em aberto → encerrar recusa.
        with self.assertRaises(ValidationError):
            services.encerrar_grupo(grupo, self.usuario)
        # Recebe o folio e encerra.
        self.abrir_caixa()
        services.receber_folio_grupo(
            grupo, self.usuario, self.dinheiro, grupo.folio.saldo()
        )
        services.encerrar_grupo(grupo, self.usuario)
        grupo.refresh_from_db()
        self.assertIsNotNone(grupo.encerrado_em)
        self.assertFalse(grupo.folio.aberta)

    def test_expirar_grupos_vencidos(self):
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        grupo.expira_em = timezone.now() - timedelta(minutes=1)
        grupo.save()
        self.assertEqual(services.expirar_grupos_vencidos(), 1)
        self.assertEqual(grupo.filhas_ativas.count(), 0)

    @override_settings(PAGAMENTOS_GATEWAY="simulado")
    def test_sinal_unico_confirma_grupo_via_pagamentos(self):
        from apps.pagamentos.models import Cobranca
        from apps.pagamentos.services import confirmar_pagamento, criar_cobranca
        grupo = self._grupo()
        services.adicionar_quarto(grupo, uh=self.qa, hospede=self.h2, usuario=self.usuario)
        services.adicionar_quarto(grupo, uh=self.qb, hospede=self.h3, usuario=self.usuario)
        cobranca = criar_cobranca(
            self.usuario, valor=Decimal("500.00"), metodo=Cobranca.Metodo.PIX,
            descricao="Sinal do grupo", finalidade=Cobranca.Finalidade.SINAL,
            pagador=self.hospede, grupo_id=grupo.pk,
        )
        confirmar_pagamento(cobranca, self.usuario, origem="teste")
        self.assertEqual(
            grupo.filhas.filter(status=Reserva.Status.CONFIRMADA).count(), 2
        )


@override_settings(FNRH_BLOQUEAR_CHECKIN=True)
class FNRHTests(ReservasTestsBase):
    """Ficha Nacional de Registro de Hóspedes: preparo, prefill e trava de check-in."""

    def setUp(self):
        super().setUp()
        self.hospede.documento = "111.222.333-44"
        self.hospede.cidade = "Itá"
        self.hospede.uf = "SC"
        self.hospede.save()

    def _preencher_todas(self, r):
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Acompanhante"
            f.nascimento = HOJE - timedelta(days=365 * 30)
            f.documento_numero = "123456"
            f.cidade = "Itá"
            f.motivo_viagem = "LAZER_FERIAS"
            f.save()

    def test_garantir_cria_titular_pre_preenchido_e_slots(self):
        r = self.reserva()  # adultos=2 → total_hospedes=2
        services.garantir_fichas_fnrh(r)
        self.assertEqual(r.fichas_fnrh.count(), 2)
        titular = r.fichas_fnrh.get(titular=True)
        self.assertEqual(titular.nome, self.hospede.nome)
        self.assertEqual(titular.cidade, "Itá")  # veio do cadastro
        # Idempotente: chamar de novo não duplica.
        services.garantir_fichas_fnrh(r)
        self.assertEqual(r.fichas_fnrh.count(), 2)

    def test_checkin_bloqueado_sem_fnrh(self):
        r = self.reserva()
        with self.assertRaises(ValidationError):
            r.fazer_checkin(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CONFIRMADA)

    def test_checkin_liberado_com_fnrh_completa(self):
        r = self.reserva()
        self._preencher_todas(r)
        self.assertTrue(r.fnrh_pronta)
        conta = r.fazer_checkin(self.usuario)
        self.assertIsNotNone(conta)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)

    def test_falta_ficha_de_acompanhante_ainda_bloqueia(self):
        r = self.reserva()  # 2 hóspedes
        services.garantir_fichas_fnrh(r)
        # Preenche só o titular; acompanhante fica pendente.
        titular = r.fichas_fnrh.get(titular=True)
        titular.nascimento = HOJE - timedelta(days=365 * 30)
        titular.documento_numero = "999"
        titular.motivo_viagem = "LAZER_FERIAS"
        titular.save()
        self.assertFalse(r.fnrh_pronta)
        with self.assertRaises(ValidationError):
            r.fazer_checkin(self.usuario)

    def test_um_unico_titular_por_reserva(self):
        from apps.reservas.models import FichaFNRH
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FichaFNRH.objects.create(reserva=r, titular=True, nome="Duplo")


class BOHTests(ReservasTestsBase):
    """Boletim de Ocupação Hoteleira — agregação da FNRH + ocupação e export CSV."""

    def _hospeda_com_fnrh(self, uf="SC", motivo="LAZER_FERIAS", transporte="AUTOMOVEL"):
        r = self.reserva()  # checkin=HOJE, adultos=2
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Y"
            f.nascimento = HOJE - timedelta(days=365 * 25)
            f.documento_numero = "555"
            f.cidade = "Itá"
            f.uf = uf
            f.pais = "Brasil"
            f.motivo_viagem = motivo
            f.meio_transporte = transporte
            f.save()
        r.fazer_checkin(self.usuario)  # base tem a trava desligada
        return r

    def test_agrega_procedencia_motivo_transporte(self):
        self._hospeda_com_fnrh()
        boh = services.boh_mensal(HOJE.year, HOJE.month)
        self.assertEqual(boh["total_hospedes"], 2)
        self.assertEqual(boh["total_chegadas"], 1)
        self.assertIn(("SC", 2), boh["nacional"])
        self.assertEqual(dict(boh["motivo"]).get("Turismo / lazer / férias"), 2)
        self.assertEqual(dict(boh["transporte"]).get("Automóvel"), 2)
        self.assertGreater(boh["uh_noites_ocupadas"], 0)

    def test_estrangeiro_vai_para_internacional(self):
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome, f.nascimento = "Tourist", HOJE - timedelta(days=365 * 40)
            f.documento_numero, f.cidade = "P123", "Buenos Aires"
            f.pais, f.motivo_viagem = "Argentina", "LAZER_FERIAS"
            f.save()
        r.fazer_checkin(self.usuario)
        boh = services.boh_mensal(HOJE.year, HOJE.month)
        self.assertIn(("Argentina", 2), boh["internacional"])

    def test_export_csv(self):
        self._hospeda_com_fnrh()
        self.client.login(username="recepcao", password="senha-forte-123")
        resp = self.client.get(
            reverse("reservas:boh") + f"?ano={HOJE.year}&mes={HOJE.month}&formato=csv"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        corpo = resp.content.decode("utf-8")
        self.assertIn("Boletim de Ocupação Hoteleira", corpo)
        self.assertIn("Motivo da viagem", corpo)


class EnvioFNRHTests(ReservasTestsBase):
    """Push à FNRH Digital via gateway simulado (estratégia B)."""

    def _hospeda_completa(self):
        r = self.reserva()
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome = f.nome or "Hóspede Z"
            f.nascimento = HOJE - timedelta(days=365 * 28)
            f.documento_numero = "321"
            f.cidade, f.uf, f.pais = "Itá", "SC", "Brasil"
            f.motivo_viagem, f.meio_transporte = "LAZER_FERIAS", "AUTOMOVEL"
            f.save()
        r.fazer_checkin(self.usuario)
        return r

    def test_checkin_marca_pendente(self):
        r = self._hospeda_completa()
        self.assertEqual(r.fnrh_status, Reserva.SincFNRH.PENDENTE)

    def test_envio_simulado_marca_enviada_com_ids(self):
        r = self._hospeda_completa()
        self.assertTrue(services.enviar_fnrh(r))
        r.refresh_from_db()
        self.assertEqual(r.fnrh_status, Reserva.SincFNRH.ENVIADA)
        self.assertIsNotNone(r.fnrh_reserva_id)
        for f in r.fichas_fnrh.all():
            self.assertIsNotNone(f.fnrh_pessoa_id)
            self.assertIsNotNone(f.fnrh_hospede_id)

    def test_envio_idempotente(self):
        r = self._hospeda_completa()
        services.enviar_fnrh(r)
        r.refresh_from_db()
        rid = r.fnrh_reserva_id
        self.assertTrue(services.enviar_fnrh(r))  # 2ª vez não refaz
        r.refresh_from_db()
        self.assertEqual(r.fnrh_reserva_id, rid)

    def test_pendentes_qs_e_reenvio(self):
        r = self._hospeda_completa()
        self.assertIn(r, services.fnrh_pendentes_qs())
        services.enviar_fnrh(r)
        self.assertNotIn(r, services.fnrh_pendentes_qs())

    def test_depara_dominios(self):
        from apps.reservas import fnrh_gateway
        r = self._hospeda_completa()
        ficha = r.fichas_fnrh.first()
        p = fnrh_gateway.payload_hospede(ficha, pessoa_id="x")
        self.assertEqual(p["fnrh"]["motivo_viagem_id"], "LAZER_FERIAS")
        self.assertEqual(p["fnrh"]["meio_transporte_id"], "AUTOMOVEL")
        self.assertEqual(fnrh_gateway.payload_reserva(r)["origem_reserva_id"], "MEIOHOSPEDAGEM")


class SinaisIsoladosTests(ReservasTestsBase):
    """Um módulo ouvinte que falha não desfaz a operação de quem emitiu o sinal
    (apps/nucleo/sinais.py): o check-out conclui e a falha vai para o log."""

    def _hospedada_com_conta_paga(self):
        r = self.reserva(status=Reserva.Status.CONFIRMADA)
        conta = r.fazer_checkin(self.usuario)
        self.abrir_caixa()
        services.receber_pagamento(conta, self.usuario, self.dinheiro, conta.saldo())
        r.refresh_from_db()
        return r

    def test_erro_de_banco_na_governanca_nao_derruba_checkout(self):
        from unittest import mock

        from django.db import connection

        def quebra_o_banco(*args, **kwargs):
            with connection.cursor() as cur:
                cur.execute("SELECT 1/0")  # DataError: aborta a transação

        r = self._hospedada_com_conta_paga()
        with mock.patch("apps.governanca.services.abrir_faxina", side_effect=quebra_o_banco), \
                self.assertLogs("apps.nucleo.sinais", level="ERROR"):
            r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)
        self.assertFalse(r.conta.aberta)
        # A transação segue utilizável depois do erro contido no savepoint.
        self.assertTrue(Reserva.objects.filter(pk=r.pk).exists())

    def test_excecao_no_comercial_nao_derruba_checkout(self):
        from unittest import mock

        r = self._hospedada_com_conta_paga()
        with mock.patch("apps.comercial.services.anotar_reserva_encerrada",
                        side_effect=RuntimeError("bug no funil")), \
                self.assertLogs("apps.nucleo.sinais", level="ERROR"):
            r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)


class CheckinCheckoutAtomicosTests(ReservasTestsBase):
    """Check-in/check-out atômicos e com trava; consumo nunca entra em conta fechada."""

    def test_falha_no_meio_do_checkin_nao_deixa_reserva_pela_metade(self):
        from unittest import mock

        from .models import ContaHospedagem

        r = self.reserva(status=Reserva.Status.CONFIRMADA)
        with mock.patch.object(ContaHospedagem, "lancar_taxas",
                               side_effect=ValidationError("falha nas taxas")):
            with self.assertRaises(ValidationError):
                r.fazer_checkin(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CONFIRMADA)
        self.assertFalse(ContaHospedagem.objects.filter(reserva=r).exists())
        self.assertFalse(LancamentoConta.objects.filter(conta__reserva=r).exists())

    def test_checkin_em_dobro_com_instancia_antiga_e_recusado(self):
        r1 = self.reserva(status=Reserva.Status.CONFIRMADA)
        r2 = Reserva.objects.get(pk=r1.pk)  # segunda aba/recepção, ainda "confirmada"
        r1.fazer_checkin(self.usuario)
        with self.assertRaises(ValidationError):
            r2.fazer_checkin(self.usuario)
        self.assertEqual(LancamentoConta.objects.filter(conta__reserva=r1).count(), 2)

    def test_consumo_nao_entra_em_conta_que_acabou_de_fechar(self):
        from .models import ContaHospedagem

        r = self.reserva(status=Reserva.Status.CONFIRMADA)
        conta_antiga = r.fazer_checkin(self.usuario)  # instância que o PDV tem em mãos
        ContaHospedagem.objects.filter(pk=conta_antiga.pk).update(
            status=ContaHospedagem.Status.FECHADA)  # outra recepção fechou a conta
        with self.assertRaises(ValidationError):
            services.lancar_na_conta(
                conta_antiga, "consumo", "consumo", "Cerveja", Decimal("12.00"), self.usuario)
        self.assertFalse(LancamentoConta.objects.filter(descricao="Cerveja").exists())


class CheckoutArredondamentoTests(ReservasTestsBase):
    """Check-out não trava por centavos de arredondamento da diária média."""

    def _hospedada(self, diaria, noites):
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=HOJE,
            checkout=HOJE + timedelta(days=noites), status=Reserva.Status.CONFIRMADA,
            valor_diaria=diaria, criado_por=self.usuario,
        )
        conta = r.fazer_checkin(self.usuario)
        self.abrir_caixa()
        return r, conta

    def test_residuo_de_centavos_e_quitado_e_auditado(self):
        # 5 noites a 250 + 2 a 400 = 2.050,00 cotado; média 292,86 × 7 = 2.050,02 lançado.
        r, conta = self._hospedada(Decimal("292.86"), 7)
        self.assertEqual(conta.saldo(), Decimal("2050.02"))
        services.receber_pagamento(conta, self.usuario, self.dinheiro, Decimal("2050.00"))
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)
        ajuste = LancamentoConta.objects.get(conta=conta, tipo=LancamentoConta.Tipo.DESCONTO)
        self.assertEqual(ajuste.valor, Decimal("0.02"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="ajuste_arredondamento").exists())

    def test_saldo_acima_da_tolerancia_continua_bloqueando(self):
        r, conta = self._hospedada(Decimal("300.00"), 2)
        services.receber_pagamento(conta, self.usuario, self.dinheiro, Decimal("599.50"))
        with self.assertRaises(ValidationError):
            r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)
        self.assertFalse(
            LancamentoConta.objects.filter(conta=conta, tipo=LancamentoConta.Tipo.DESCONTO).exists())


class DayUseUmDiaTests(ReservasTestsBase):
    """Unidade de day use só aceita um dia (saída = dia seguinte à entrada)."""

    def setUp(self):
        super().setUp()
        self.day = UH.objects.filter(tipo__modalidade=TipoUH.Modalidade.DAY_USE,
                                     status=UH.Status.ATIVA).first()

    def test_prereserva_de_varios_dias_em_day_use_e_recusada(self):
        with self.assertRaises(ValidationError):
            services.criar_prereserva(
                uh=self.day, checkin=HOJE + timedelta(days=5),
                checkout=HOJE + timedelta(days=8), hospede=self.hospede, usuario=self.usuario)
        self.assertFalse(Reserva.objects.filter(uh=self.day).exists())

    def test_formulario_valida_pelo_clean_do_model(self):
        r = Reserva(uh=self.day, hospede=self.hospede, checkin=HOJE,
                    checkout=HOJE + timedelta(days=6), adultos=2,
                    valor_diaria=Decimal("100.00"), criado_por=self.usuario)
        with self.assertRaises(ValidationError):
            r.full_clean()
        r.checkout = HOJE + timedelta(days=1)
        r.full_clean()  # um dia: válido

    def test_transferir_day_use_para_varios_dias_e_recusado(self):
        r = Reserva.objects.create(
            uh=self.day, hospede=self.hospede, checkin=HOJE + timedelta(days=3),
            checkout=HOJE + timedelta(days=4), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("100.00"), criado_por=self.usuario)
        with self.assertRaises(ValidationError):
            services.transferir_datas(
                r, HOJE + timedelta(days=10), HOJE + timedelta(days=12), self.usuario)


class PrecosEmLoteTests(TestCase):
    """`precos_em_lote()` memoriza sem mudar preço, e só dentro do bloco."""

    def setUp(self):
        from datetime import date

        from apps.nucleo.models import UH, Temporada, TipoUH

        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200.00"), capacidade=2)
        self.uh = UH.objects.create(numero="L1", tipo=self.tipo)
        self.dia = date.today() + timedelta(days=15)
        Temporada.objects.create(nome="Alta", classificacao="alta",
                                 inicio=self.dia, fim=self.dia + timedelta(days=5))
        Tarifa.objects.create(tipo_uh=self.tipo, classificacao="alta", valor=Decimal("260.00"))

    def test_mesmo_preco_dentro_e_fora_do_lote(self):
        co = self.dia + timedelta(days=4)
        fora = services.diaria_media_unidade(self.uh, self.dia, co)
        with services.precos_em_lote():
            dentro = services.diaria_media_unidade(self.uh, self.dia, co)
        self.assertEqual(fora, dentro)

    def test_memoria_nao_vaza_para_fora_do_bloco(self):
        if services.classificacao_do_dia(self.dia) != "alta":
            self.skipTest("o dia caiu num feriado automático")
        with services.precos_em_lote():
            self.assertEqual(services.tarifa_do_dia(self.tipo, self.dia), Decimal("260.00"))
        Tarifa.objects.filter(tipo_uh=self.tipo).update(valor=Decimal("280.00"))
        self.assertEqual(services.tarifa_do_dia(self.tipo, self.dia), Decimal("280.00"))

    def test_dentro_do_lote_cada_consulta_acontece_uma_vez(self):
        co = self.dia + timedelta(days=4)
        with services.precos_em_lote():
            services.diaria_media_unidade(self.uh, self.dia, co)
            with self.assertNumQueries(0):
                services.diaria_media_unidade(self.uh, self.dia, co)


class SaldosEmLoteTests(ReservasTestsBase):
    """`ContaHospedagem.saldos()` dá o mesmo que `saldo()` de cada conta, em 4 consultas."""

    def test_saldos_em_lote_iguais_ao_saldo_de_cada_conta(self):
        from apps.nucleo.models import NaturezaFiscal

        from .models import ContaHospedagem

        uh2 = UH.objects.create(numero="T2", tipo=self.tipo)
        uh3 = UH.objects.create(numero="T3", tipo=self.tipo)
        self.abrir_caixa()
        # Conta 1: diárias + consumo + desconto + pagamento parcial.
        r1 = self.reserva(dias=3)
        c1 = r1.fazer_checkin(self.usuario)
        services.lancar_na_conta(c1, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
                                 "Cerveja", Decimal("18.50"), self.usuario)
        LancamentoConta.objects.create(conta=c1, tipo=LancamentoConta.Tipo.DESCONTO,
                                       natureza=NaturezaFiscal.SERVICO, descricao="Cortesia",
                                       valor=Decimal("25.00"), criado_por=self.usuario)
        services.receber_pagamento(c1, self.usuario, self.dinheiro, Decimal("100.00"))
        # Conta 2: com adiantamento antes do check-in.
        r2 = self.reserva(dias=2, uh=uh2)
        services.receber_adiantamento(r2, self.usuario, self.dinheiro, Decimal("150.00"))
        c2 = r2.fazer_checkin(self.usuario)
        # Conta 3: só diárias.
        c3 = self.reserva(dias=1, uh=uh3).fazer_checkin(self.usuario)

        contas = [c1, c2, c3]
        with self.assertNumQueries(4):
            em_lote = ContaHospedagem.saldos(contas)
        self.assertEqual(em_lote, {c.pk: c.saldo() for c in contas})
        self.assertEqual(em_lote[c2.pk], Decimal("450.00"))  # 600 − 150


class MapaSemConsultaPorQuartoTests(ReservasTestsBase):
    """O mapa de quartos (dashboard) não consulta o banco por quarto ocupado."""

    def _ocupar(self, n):
        for _ in range(n):
            uh = UH.objects.create(numero=f"M{UH.objects.count():02d}", tipo=self.tipo)
            Reserva.objects.create(
                uh=uh, hospede=self.hospede, checkin=HOJE, checkout=HOJE + timedelta(days=2),
                status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("300.00"),
                criado_por=self.usuario,
            ).fazer_checkin(self.usuario)

    def _consultas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        services.mapa_quartos_hoje()  # aquece o que só roda uma vez
        with CaptureQueriesContext(connection) as ctx:
            dados = services.mapa_quartos_hoje()
        return len(ctx.captured_queries), dados

    def test_consultas_nao_crescem_com_os_quartos_ocupados(self):
        self._ocupar(2)
        com_2, _ = self._consultas()
        self._ocupar(4)
        com_6, dados = self._consultas()
        self.assertEqual(com_2, com_6)
        ocupados = [q for q in dados["quartos"] if q["situacao"] == "ocupada"]
        self.assertEqual(len(ocupados), 6)
        self.assertTrue(all(q["saldo"] == Decimal("600.00") for q in ocupados))


class PagamentoOnlineNaContaTests(ReservasTestsBase):
    """O que é pago pelo gateway vira crédito na reserva; estornos desfazem o crédito."""

    def _cobranca_paga(self, *, reserva=None, grupo=None, valor="300.00", finalidade=None):
        from apps.pagamentos.models import Cobranca
        from apps.pagamentos.services import confirmar_pagamento, criar_cobranca

        c = criar_cobranca(
            self.usuario, valor=Decimal(valor), metodo="pix", descricao="Teste",
            finalidade=finalidade or Cobranca.Finalidade.SINAL,
            reserva_id=reserva.pk if reserva else None,
            grupo_id=grupo.pk if grupo else None,
        )
        return confirmar_pagamento(c, self.usuario)

    def test_sinal_online_antes_do_checkin_vira_adiantamento_uma_vez_so(self):
        from apps.pagamentos.services import confirmar_pagamento

        from .models import Adiantamento

        r = self.reserva(dias=2, status=Reserva.Status.PRE_RESERVA)
        c = self._cobranca_paga(reserva=r)
        confirmar_pagamento(c, self.usuario)  # o webhook pode chegar duas vezes
        credito = Adiantamento.objects.get(reserva=r)
        self.assertEqual(credito.valor, Decimal("300.00"))
        self.assertEqual(credito.cobranca_id, c.pk)
        self.assertIsNone(credito.movimento_caixa)
        conta = r.fazer_checkin(self.usuario)  # 600 de diárias
        self.assertEqual(conta.saldo(), Decimal("300.00"))

    def test_saldo_pago_online_libera_o_checkout(self):
        from apps.pagamentos.models import Cobranca

        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)
        self._cobranca_paga(reserva=r, valor="600.00",
                            finalidade=Cobranca.Finalidade.SALDO)
        conta.refresh_from_db()
        self.assertEqual(conta.saldo(), Decimal("0.00"))
        r.fazer_checkout(self.usuario)
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CHECKOUT)

    def test_pagamento_online_do_grupo_cai_no_folio(self):
        hoje = timezone.localdate()
        grupo = services.criar_grupo(rotulo="Casamento", titular=self.hospede, checkin=hoje,
                                     checkout=hoje + timedelta(days=2), usuario=self.usuario)
        self._cobranca_paga(grupo=grupo, valor="500.00")
        self.assertEqual(grupo.folio.total_pago(), Decimal("500.00"))

    def test_estorno_no_gateway_volta_a_cobrar(self):
        from apps.pagamentos.services import estornar

        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)
        c = self._cobranca_paga(reserva=r, valor="200.00")
        self.assertEqual(conta.saldo(), Decimal("400.00"))
        estornar(c, self.usuario)
        self.assertEqual(conta.saldo(), Decimal("600.00"))

    def test_estorno_no_caixa_desfaz_o_pagamento_da_conta(self):
        from apps.nucleo.models import estornar_movimento

        from .models import PagamentoConta

        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)
        sessao = self.abrir_caixa()
        pagamento = services.receber_pagamento(conta, self.usuario, self.dinheiro, Decimal("600.00"))
        self.assertEqual(conta.saldo(), Decimal("0.00"))
        estornar_movimento(pagamento.movimento_caixa, sessao, self.usuario, "Devolução",
                           valor=Decimal("150.00"))
        self.assertEqual(conta.saldo(), Decimal("150.00"))
        estorno = PagamentoConta.objects.get(estorno_de=pagamento)
        self.assertEqual(estorno.valor, Decimal("-150.00"))

    def test_estorno_no_caixa_de_conta_fechada_e_recusado_sem_mexer_em_nada(self):
        from apps.nucleo.models import MovimentoCaixa, estornar_movimento

        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)
        sessao = self.abrir_caixa()
        pagamento = services.receber_pagamento(conta, self.usuario, self.dinheiro, Decimal("600.00"))
        r.fazer_checkout(self.usuario)
        with self.assertRaisesMessage(ValidationError, "já fechada"):
            estornar_movimento(pagamento.movimento_caixa, sessao, self.usuario, "Devolução")
        self.assertFalse(MovimentoCaixa.objects.filter(tipo=MovimentoCaixa.Tipo.ESTORNO).exists())
        self.assertEqual(conta.saldo(), Decimal("0.00"))

    def test_estorno_no_caixa_de_adiantamento_desfaz_o_credito(self):
        from apps.nucleo.models import estornar_movimento

        r = self.reserva(dias=2, offset=5)
        sessao = self.abrir_caixa()
        adiantamento = services.receber_adiantamento(r, self.usuario, self.dinheiro,
                                                     Decimal("200.00"))
        estornar_movimento(adiantamento.movimento_caixa, sessao, self.usuario, "Desistiu")
        conta = r.fazer_checkin(self.usuario)
        self.assertEqual(conta.saldo(), Decimal("600.00"))

    def test_sinal_estornado_volta_a_contar_como_sem_sinal(self):
        from apps.nucleo.models import estornar_movimento

        r = self.reserva(dias=2, offset=1)
        sessao = self.abrir_caixa()
        adiantamento = services.receber_adiantamento(r, self.usuario, self.dinheiro,
                                                     Decimal("200.00"))

        def sem_sinal():
            return [a for a in services.pendencias_auditoria() if a["tipo"] == "sem_sinal"]

        self.assertEqual(sem_sinal(), [])
        estornar_movimento(adiantamento.movimento_caixa, sessao, self.usuario, "Desistiu")
        self.assertEqual(len(sem_sinal()), 1)


class DevolucaoAoHospedeTests(ReservasTestsBase):
    """Adiantamento não passa do total; crédito a mais e cancelamento voltam pelo caixa."""

    def test_adiantamento_nao_passa_do_total_da_estadia(self):
        r = self.reserva(dias=2, offset=5)  # 600 (taxas desligadas nos testes)
        self.abrir_caixa()
        with self.assertRaisesMessage(ValidationError, "acima do que falta pagar"):
            services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("600.01"))
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("400.00"))
        with self.assertRaisesMessage(ValidationError, "R$ 200.00"):
            services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("250.00"))
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("200.00"))

    def test_adiantamento_em_quarto_de_grupo_vai_para_o_sinal_do_grupo(self):
        inicio = HOJE + timedelta(days=5)
        grupo = services.criar_grupo(rotulo="Família", titular=self.hospede, checkin=inicio,
                                     checkout=inicio + timedelta(days=2), usuario=self.usuario)
        filha = services.adicionar_quarto(grupo, uh=self.uh, hospede=self.hospede,
                                          usuario=self.usuario)
        self.abrir_caixa()
        with self.assertRaisesMessage(ValidationError, "grupo"):
            services.receber_adiantamento(filha, self.usuario, self.dinheiro, Decimal("100.00"))

    def test_credito_a_mais_na_conta_trava_a_saida_ate_devolver(self):
        from apps.nucleo.models import MovimentoCaixa, NaturezaFiscal

        r = self.reserva(dias=2)
        conta = r.fazer_checkin(self.usuario)
        sessao = self.abrir_caixa()
        services.receber_pagamento(conta, self.usuario, self.dinheiro, Decimal("600.00"))
        LancamentoConta.objects.create(conta=conta, tipo=LancamentoConta.Tipo.DESCONTO,
                                       natureza=NaturezaFiscal.SERVICO, descricao="Cortesia",
                                       valor=Decimal("100.00"), criado_por=self.usuario)
        with self.assertRaisesMessage(ValidationError, "R$ 100.00 de crédito"):
            r.fazer_checkout(self.usuario)
        self.assertEqual(services.situacao_devolucao(r)["sugerido"], Decimal("100.00"))
        services.devolver_ao_hospede(r, Decimal("100.00"), self.usuario, "Cortesia")
        self.assertEqual(conta.saldo(), Decimal("0.00"))
        estorno = MovimentoCaixa.objects.get(tipo=MovimentoCaixa.Tipo.ESTORNO)
        self.assertEqual((estorno.sessao, estorno.valor), (sessao, Decimal("100.00")))
        r.fazer_checkout(self.usuario)
        self.assertIsNone(services.situacao_devolucao(r))

    def test_cancelamento_grava_a_retencao_e_sugere_devolver_o_resto(self):
        r = self.reserva(dias=2, offset=30)  # 600; retenção de 10% = 60
        self.abrir_caixa()
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("300.00"))
        # Confirmada há 10 dias: fora da janela de arrependimento.
        Reserva.objects.filter(pk=r.pk).update(confirmada_em=timezone.now() - timedelta(days=10))
        self.client.force_login(self.usuario)
        self.client.post(reverse("reservas:cancelar", args=[r.pk]), {"motivo": "Desistiu"})
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.CANCELADA)
        self.assertEqual(r.valor_retido, Decimal("60.00"))
        self.assertEqual(services.situacao_devolucao(r)["sugerido"], Decimal("240.00"))
        pendentes = [a for a in services.pendencias_auditoria() if a["tipo"] == "devolucao_pendente"]
        self.assertEqual(len(pendentes), 1)
        detalhe = self.client.get(reverse("reservas:detalhe", args=[r.pk]))
        self.assertContains(detalhe, "Devolver ao hóspede")
        self.assertContains(detalhe, 'value="240,00"')  # no formato da máscara de reais

        resposta = self.client.post(reverse("reservas:devolver", args=[r.pk]),
                                    {"valor": "240.00", "motivo": "Política: fora do prazo"})
        self.assertRedirects(resposta, reverse("reservas:detalhe", args=[r.pk]),
                             fetch_redirect_response=False)
        from .cancelamento import total_pago
        self.assertEqual(total_pago(r), Decimal("60.00"))
        self.assertEqual(services.situacao_devolucao(r)["sugerido"], Decimal("0.00"))
        self.assertFalse([a for a in services.pendencias_auditoria()
                          if a["tipo"] == "devolucao_pendente"])

    def test_devolucao_do_que_entrou_online_e_recusada_sem_mexer_em_nada(self):
        from .cancelamento import total_pago

        r = self.reserva(dias=2, offset=30)
        services.registrar_pagamento_online(cobranca_id=4242, valor=Decimal("300.00"),
                                            descricao="Pix online", reserva_id=r.pk)
        self.abrir_caixa()
        r.cancelar(self.usuario, "Desistiu")
        situacao = services.situacao_devolucao(r)
        self.assertEqual((situacao["online"], situacao["no_caixa"]),
                         (Decimal("300.00"), Decimal("0.00")))
        with self.assertRaisesMessage(ValidationError, "pago online"):
            services.devolver_ao_hospede(r, Decimal("300.00"), self.usuario, "Desistiu")
        self.assertEqual(total_pago(r), Decimal("300.00"))

    def test_devolver_acima_do_limite_e_recusado(self):
        r = self.reserva(dias=2, offset=5)
        self.abrir_caixa()
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("300.00"))
        # Ativa e sem nada pago a mais: não há o que devolver.
        with self.assertRaisesMessage(ValidationError, "R$ 0.00"):
            services.devolver_ao_hospede(r, Decimal("10.00"), self.usuario, "Teste")

    def test_devolver_exige_gerencia(self):
        r = self.reserva(dias=2, offset=30)
        self.abrir_caixa()
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("300.00"))
        r.cancelar(self.usuario, "Desistiu")
        operadora = Usuario.objects.create_user(username="op-dev", password="senha-forte-123")
        operadora.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        self.client.login(username="op-dev", password="senha-forte-123")
        self.client.post(reverse("reservas:devolver", args=[r.pk]),
                         {"valor": "300.00", "motivo": "Tentativa"})
        from .cancelamento import total_pago
        self.assertEqual(total_pago(r), Decimal("300.00"))


class ModalNovaReservaTests(ReservasTestsBase):
    """O modal é a tela mais usada do balcão: rótulo ligado ao campo, foco no
    hóspede e o que raramente se mexe recolhido em "Mais opções"."""

    def setUp(self):
        super().setUp()
        self.client.login(username="recepcao", password="senha-forte-123")

    def html(self):
        """O modal só é servido para o HTMX (sem o header vem a página inteira)."""
        r = self.client.get(reverse("reservas:nova"), headers={"hx-request": "true"})
        return r.content.decode()

    def test_rotulo_do_hospede_aponta_para_o_campo_visivel(self):
        """O label_tag do Django aponta `for="id_hospede"`; o combobox não tinha
        esse id em nenhum elemento — clicar no rótulo não focava nada."""
        html = self.html()
        self.assertIn('for="id_hospede"', html)
        self.assertIn('id="id_hospede"', html)
        self.assertIn('for="id_titular"', html)
        self.assertIn('id="id_titular"', html)

    def test_combobox_anuncia_como_combobox(self):
        html = self.html()
        self.assertIn('role="combobox"', html)
        self.assertIn('role="listbox"', html)
        self.assertIn('role="option"', html)
        self.assertIn("aria-activedescendant", html)

    def test_foco_nasce_no_hospede(self):
        self.assertIn("autofocus", self.html())

    def test_mais_opcoes_recolhe_sem_perder_campo(self):
        html = self.html()
        self.assertIn("Mais opções", html)
        # Nenhum campo saiu do formulário — só mudou de lugar.
        for campo in ("casais", "solteiros", "usa_sofa_cama", "usa_berco",
                      "cobra_iss", "cobra_taxa_turismo", "nao_reembolsavel",
                      "observacoes"):
            self.assertIn(f'name="{campo}"', html, campo)

    def test_ctrl_enter_envia(self):
        self.assertIn("keydown.ctrl.enter", self.html())


class MapaSemRecarregarNoErroTests(ReservasTestsBase):
    """Arrastar e errar não pode recarregar a página: o toast explicando o
    motivo era apagado junto, e parecia que a troca tinha dado certo."""

    def setUp(self):
        super().setUp()
        self.client.login(username="recepcao", password="senha-forte-123")

    def test_mapa_recarrega_preservando_a_rolagem_so_no_sucesso(self):
        html = self.client.get(reverse("reservas:mapa")).content.decode()
        self.assertIn("recarregarNoLugar(['.mapa-rolagem'])", html)
        self.assertNotIn("setTimeout(() => location.reload()", html)
        self.assertIn("a reserva não foi movida", html)

    def test_mapa_de_quartos_tambem(self):
        html = self.client.get(reverse("reservas:mapa_quartos")).content.decode()
        self.assertIn("recarregarNoLugar()", html)
        self.assertNotIn("setTimeout(() => location.reload()", html)
        self.assertIn("o quarto não foi trocado", html)

    def test_mapa_sem_quarto_explica(self):
        UH.objects.all().delete()
        html = self.client.get(reverse("reservas:mapa")).content.decode()
        self.assertIn("Nenhum quarto cadastrado", html)


@override_settings(PRECO_TAXAS_ATIVAS=True)
class TaxasForaDaBaseDaNfseTests(ReservasTestsBase):
    """ISS e taxa de turismo entram na conta, mas não na base da NFS-e."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ConfiguracaoReservas
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={
            "iss_aliquota": Decimal("4.00"), "taxa_turismo_diaria": Decimal("5.00"),
        })

    def test_checkin_lanca_taxas_com_tipo_proprio_e_a_nfse_usa_so_a_hospedagem(self):
        r = self.reserva(dias=2)  # 600 de diárias
        conta = r.fazer_checkin(self.usuario)
        taxas = conta.lancamentos.filter(tipo=LancamentoConta.Tipo.TAXA)
        self.assertEqual(sorted(t.valor for t in taxas), [Decimal("10.00"), Decimal("24.00")])
        self.assertEqual(conta.saldo(), Decimal("634.00"))  # o hóspede paga tudo
        resumo = services.resumo_fiscal_conta(conta.pk)
        self.assertEqual(resumo["servico"], Decimal("600.00"))  # base da NFS-e
        self.assertEqual(resumo["taxas"], Decimal("34.00"))

    def test_taxa_nao_pode_ser_lancada_a_mao(self):
        from .forms import LancamentoContaForm

        tipos = [c[0] for c in LancamentoContaForm().fields["tipo"].choices]
        self.assertNotIn(LancamentoConta.Tipo.TAXA, tipos)
        self.assertNotIn(LancamentoConta.Tipo.DIARIA, tipos)

    def test_migracao_marca_as_taxas_antigas(self):
        import importlib

        from django.apps import apps as registro

        conta = self.reserva(dias=1).fazer_checkin(self.usuario)
        LancamentoConta.objects.filter(conta=conta, tipo=LancamentoConta.Tipo.TAXA).update(
            tipo=LancamentoConta.Tipo.SERVICO)  # como as contas antigas estavam
        migracao = importlib.import_module("apps.reservas.migrations.0024_lancamento_tipo_taxa")
        migracao.marcar_taxas(registro, None)
        self.assertEqual(conta.lancamentos.filter(tipo=LancamentoConta.Tipo.TAXA).count(), 2)
        self.assertEqual(conta.lancamentos.filter(tipo=LancamentoConta.Tipo.DIARIA).count(), 1)


class DispensarTaxasExigeGerenciaTests(ReservasTestsBase):
    def _post(self, usuario, **extra):
        self.client.force_login(usuario)
        dados = {
            "hospede": self.hospede.pk, "uh": self.uh.pk,
            "checkin": (HOJE + timedelta(days=20)).isoformat(),
            "checkout": (HOJE + timedelta(days=22)).isoformat(),
            "adultos": 2, "criancas": 0, "canal": "balcao", "faturamento": "particular",
            "observacoes": "", "cobra_iss": "on", "cobra_taxa_turismo": "on",
        }
        dados.update(extra)
        dados = {k: v for k, v in dados.items() if v is not None}
        return self.client.post(reverse("reservas:nova"), dados)

    def test_operador_nao_dispensa_iss_nem_taxa(self):
        operadora = Usuario.objects.create_user(username="op-taxa", password="senha-forte-123")
        operadora.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        resposta = self._post(operadora, cobra_taxa_turismo=None)
        self.assertContains(resposta, "Dispensar a taxa de turismo exige gerência")
        self.assertEqual(Reserva.objects.count(), 0)
        self._post(operadora)  # com as duas marcadas, passa
        self.assertEqual(Reserva.objects.count(), 1)

    def test_gerencia_dispensa(self):
        self._post(self.usuario, cobra_iss=None)
        reserva = Reserva.objects.get()
        self.assertFalse(reserva.cobra_iss)


class DiariasSomamACotacaoTests(ReservasTestsBase):
    """A diária acordada é a média arredondada; as noites lançadas somam o total cotado."""

    def test_ultima_noite_absorve_o_arredondamento(self):
        r = self.reserva(dias=3)
        r.valor_diaria, r.valor_hospedagem = Decimal("333.67"), Decimal("1001.00")
        r.save(update_fields=["valor_diaria", "valor_hospedagem"])
        conta = r.fazer_checkin(self.usuario)
        diarias = list(conta.lancamentos.filter(tipo=LancamentoConta.Tipo.DIARIA)
                       .values_list("valor", flat=True))
        self.assertEqual(diarias, [Decimal("333.67"), Decimal("333.67"), Decimal("333.66")])
        self.assertEqual(conta.saldo(), Decimal("1001.00"))
        self.assertEqual(r.total_previsto(), Decimal("1001.00"))

    def test_total_que_nao_combina_com_a_diaria_e_ignorado(self):
        # Diária mudada à mão depois: o total antigo não pode virar uma noite estranha.
        r = self.reserva(dias=3)
        r.valor_hospedagem = Decimal("750.00")
        self.assertEqual(r.valores_das_diarias(), [Decimal("300.00")] * 3)

    def test_sem_total_exato_todas_as_noites_valem_a_diaria(self):
        r = self.reserva(dias=2)
        self.assertIsNone(r.valor_hospedagem)
        self.assertEqual(r.hospedagem_prevista(), Decimal("600.00"))

    def test_prereserva_guarda_o_total_da_cotacao(self):
        from . import precos

        inicio = HOJE + timedelta(days=40)
        r = services.criar_prereserva(uh=self.uh, checkin=inicio,
                                      checkout=inicio + timedelta(days=3),
                                      hospede=self.hospede, usuario=self.usuario)
        cot = precos.cotacao(uh=self.uh, checkin=inicio, checkout=inicio + timedelta(days=3))
        self.assertEqual(r.valor_hospedagem, cot["hospedagem"])
        self.assertEqual(r.hospedagem_prevista(), cot["hospedagem"])
