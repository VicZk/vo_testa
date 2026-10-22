"""Regressões de operação entre módulos, incluindo concorrência real no PostgreSQL.

A barreira sincroniza a largada antes das transações. Nenhum teste espera que dois
operadores atravessem simultaneamente uma trava exclusiva. Saldos, número de
operações aceitas e efeitos financeiros são conferidos no banco ao final.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    ConfiguracaoReservas,
    FormaPagamento,
    Hospede,
    Inventario,
    ItemInventario,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    SessaoCaixa,
    TipoUH,
    Usuario,
    registrar_entrada,
    registrar_saida,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.reservas import services as booking
from apps.reservas.models import Reserva

D = Decimal


class FixtureMixin:
    def build_fixture(self):
        self.op = Usuario.objects.create_superuser(username="qa_operator", password=None)
        for code, _ in Modulo.choices:
            ModuloContratado.objects.update_or_create(
                codigo=code, defaults={"ativo": code != Modulo.FISCAL}
            )
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )
        self.kind = TipoUH.objects.create(nome="QA Standard", tarifa_base=D("300"), capacidade=4)
        self.room = UH.objects.create(numero="QA-01", tipo=self.kind)
        self.room2 = UH.objects.create(numero="QA-02", tipo=self.kind)
        self.guest = Pessoa.objects.create(
            nome="Hóspede fictício QA", email="guest@example.invalid"
        )
        Hospede.objects.create(pessoa=self.guest)
        self.cash, _ = FormaPagamento.objects.get_or_create(
            nome="QA Dinheiro", defaults={"tipo": "dinheiro"}
        )
        self.category = CategoriaProduto.objects.create(nome="QA Bebidas")
        self.shop = LocalEstoque.objects.create(nome="QA Loja", modulo="loja")
        self.kitchen = LocalEstoque.objects.create(nome="QA Restaurante", modulo="restaurante")
        self.product = Produto.objects.create(
            nome="QA Água", categoria=self.category, preco_venda=D("7")
        )
        registrar_entrada(self.product, self.shop, D("20"), D("2"), self.op)
        registrar_entrada(self.product, self.kitchen, D("20"), D("2"), self.op)
        for mod in ("reservas", "loja", "restaurante", "lavanderia", "nucleo"):
            SessaoCaixa.objects.create(operador=self.op, modulo=mod, fundo_troco=D("100"))
        self.today = timezone.localdate()

    def reservation(self, room=None, offset=0, nights=2, **extra):
        r = booking.criar_prereserva(
            uh=room or self.room,
            checkin=self.today + timedelta(days=offset),
            checkout=self.today + timedelta(days=offset + nights),
            hospede=self.guest,
            usuario=self.op,
            valor_diaria=D("300"),
            **extra,
        )
        booking.confirmar_reserva(r.pk, self.op)
        r.refresh_from_db()
        return r

    def stay(self, **kwargs):
        r = self.reservation(**kwargs)
        with mock.patch("django.utils.timezone.localdate", return_value=r.checkin):
            account = r.fazer_checkin(self.op)
        return (r, account)


@override_settings(
    FNRH_BLOQUEAR_CHECKIN=False,
    PRECO_TAXAS_ATIVAS=False,
    PAGAMENTOS_GATEWAY="simulado",
    FISCAL_GATEWAY="simulado",
)
class OperationalContracts(FixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def test_failed_housekeeping_keeps_room_unavailable(self):
        from apps.governanca import services as housekeeping

        r, account = self.stay()
        booking.receber_pagamento(account, self.op, self.cash, account.saldo())
        with mock.patch(
            "apps.governanca.services.abrir_faxina", side_effect=RuntimeError("QA injected failure")
        ):
            r.fazer_checkout(self.op)
        ready = housekeeping.uh_pronta_para_checkin(self.room)
        self.assertFalse(ready, "Checkout leaves the room ready when housekeeping fails")

    def test_new_guest_cannot_enter_before_previous_guest_leaves(self):
        old, _ = self.stay(offset=-2, nights=2)
        arriving = self.reservation(offset=0, nights=2)
        rejected = False
        try:
            arriving.fazer_checkin(self.op)
        except ValidationError:
            rejected = True
        occupied = Reserva.objects.filter(uh=self.room, status=Reserva.Status.HOSPEDADA).count()
        self.assertEqual(occupied, 1)
        self.assertTrue(
            rejected, "A second guest can check in while the previous stay is still open"
        )

    def test_early_arrival_does_not_overlap_current_physical_occupancy(self):
        self.stay(nights=1)
        early = self.reservation(offset=1, nights=2)
        with self.assertRaises(ValidationError):
            early.fazer_checkin(self.op)

    def test_stale_cancellation_cannot_undo_completed_checkin(self):
        r = self.reservation()
        stale = Reserva.objects.get(pk=r.pk)
        r.fazer_checkin(self.op)
        rejected = False
        try:
            stale.cancelar(self.op, "QA cancellation from another desk")
        except ValidationError:
            rejected = True
        r.refresh_from_db()
        self.assertTrue(rejected)
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)

    def test_stale_no_show_cannot_undo_completed_checkin(self):
        r = self.reservation()
        stale = Reserva.objects.get(pk=r.pk)
        r.fazer_checkin(self.op)
        try:
            stale.marcar_no_show(self.op)
        except ValidationError:
            pass
        r.refresh_from_db()
        self.assertEqual(r.status, Reserva.Status.HOSPEDADA)

    def test_restaurant_stale_remove_does_not_return_inventory_twice(self):
        from apps.restaurante import services as restaurant
        from apps.restaurante.models import ItemComanda

        order = restaurant.abrir_comanda(self.op, self.kitchen, rotulo="QA Mesa")
        item = restaurant.adicionar_item(order, self.product, 3, self.op)
        stale = ItemComanda.objects.get(pk=item.pk)
        restaurant.remover_item(item, self.op)
        try:
            restaurant.remover_item(stale, self.op)
        except ValidationError, ItemComanda.DoesNotExist:
            pass
        observed = saldo(self.product, self.kitchen)
        self.assertEqual(observed, D("20"))

    def test_old_cleaning_completion_does_not_collect_linen_twice(self):
        from apps.governanca import services as housekeeping
        from apps.governanca.models import TarefaGovernanca
        from apps.lavanderia import services as laundry
        from apps.lavanderia.models import ItemEnxoval, MovimentoEnxoval

        linen = ItemEnxoval.objects.create(nome="QA Toalha", por_faxina=2)
        laundry.adquirir(linen, 10, self.op)
        laundry.distribuir(linen, 10, self.op)
        task = housekeeping.abrir_faxina(self.room, usuario=self.op)
        stale = TarefaGovernanca.objects.get(pk=task.pk)
        housekeeping.concluir_tarefa(task, self.op)
        housekeeping.concluir_tarefa(stale, self.op)
        dirty = laundry.saldo_enxoval(linen, MovimentoEnxoval.Estado.SUJA)
        self.assertEqual(dirty, 2)

    def test_laundry_item_cannot_be_added_from_stale_order_after_delivery(self):
        from apps.lavanderia import services as laundry
        from apps.lavanderia.models import OrdemLavanderia, ServicoLavanderia

        service = ServicoLavanderia.objects.create(nome="QA Camisa", preco=D("12"))
        order = laundry.abrir_ordem(self.op, cliente=self.guest)
        laundry.adicionar_item(order, service, 1, self.op)
        stale = OrdemLavanderia.objects.get(pk=order.pk)
        laundry.entregar(order, self.op, "caixa", forma=self.cash)
        rejected = False
        try:
            laundry.adicionar_item(stale, service, 2, self.op)
        except ValidationError:
            rejected = True
        order.refresh_from_db()
        self.assertTrue(rejected)

    def test_laundry_stale_cancel_cannot_cancel_already_charged_delivery(self):
        from apps.lavanderia import services as laundry
        from apps.lavanderia.models import OrdemLavanderia, ServicoLavanderia

        service = ServicoLavanderia.objects.create(nome="QA Calça", preco=D("10"))
        order = laundry.abrir_ordem(self.op, cliente=self.guest)
        laundry.adicionar_item(order, service, 1, self.op)
        stale = OrdemLavanderia.objects.get(pk=order.pk)
        laundry.entregar(order, self.op, "caixa", forma=self.cash)
        try:
            laundry.cancelar_ordem(stale, self.op, "QA another tab")
        except ValidationError:
            pass
        order.refresh_from_db()
        self.assertEqual(order.status, OrdemLavanderia.Status.ENTREGUE)

    def test_preventive_maintenance_stale_completion_schedules_only_one_successor(self):
        from apps.manutencao import services as maintenance
        from apps.manutencao.models import OrdemServico

        order = maintenance.abrir_os(
            self.op,
            area="QA Piscina",
            titulo="QA preventiva",
            tipo=OrdemServico.Tipo.PREVENTIVA,
            recorrencia_meses=1,
        )
        stale = OrdemServico.objects.get(pk=order.pk)
        maintenance.concluir_os(order, self.op, resolucao="QA done")
        try:
            maintenance.concluir_os(stale, self.op, resolucao="QA repeated")
        except ValidationError:
            pass
        following = OrdemServico.objects.exclude(pk=order.pk).filter(titulo="QA preventiva").count()
        self.assertEqual(following, 1)

    def test_room_move_preserves_consumption_and_dirties_old_room(self):
        from apps.governanca import services as housekeeping

        r, account = self.stay()
        booking.lancar_na_conta(account, "consumo", "consumo", "QA água", D("7"), self.op)
        before = account.saldo()
        booking.trocar_quarto(r, self.room2, self.op, motivo="QA ar-condicionado")
        r.refresh_from_db()
        self.assertEqual(r.uh_id, self.room2.pk)
        self.assertEqual(account.saldo(), before)
        self.assertFalse(housekeeping.uh_pronta_para_checkin(self.room))

    def test_room_move_to_dirty_room_is_rejected(self):
        from apps.governanca import services as housekeeping
        from apps.governanca.models import StatusLimpeza

        r, _ = self.stay()
        housekeeping.definir_status(self.room2, StatusLimpeza.Situacao.SUJA, self.op)
        with self.assertRaises(ValidationError):
            booking.trocar_quarto(r, self.room2, self.op, motivo="QA replacement")

    def test_full_stay_with_multiple_departments_and_split_payment(self):
        from apps.governanca import services as housekeeping
        from apps.lavanderia import services as laundry
        from apps.lavanderia.models import ServicoLavanderia
        from apps.loja import services as shop
        from apps.pagamentos import services as payments
        from apps.pagamentos.models import Cobranca
        from apps.restaurante import services as restaurant

        r, account = self.stay()
        shop.finalizar_venda(
            self.op,
            self.shop,
            [{"produto_id": self.product.pk, "quantidade": 3}],
            "conta",
            conta_id=account.pk,
        )
        order = restaurant.abrir_comanda(self.op, self.kitchen, cliente=self.guest)
        restaurant.adicionar_item(order, self.product, 2, self.op)
        restaurant.fechar_comanda(order, self.op, "conta", conta_id=account.pk)
        service = ServicoLavanderia.objects.create(nome="QA Lavagem", preco=D("12"))
        wash = laundry.abrir_ordem(self.op, cliente=self.guest)
        laundry.adicionar_item(wash, service, 1, self.op)
        laundry.entregar(wash, self.op, "conta", conta_id=account.pk)
        self.assertEqual(account.saldo(), D("647"))
        booking.receber_pagamento(account, self.op, self.cash, D("100"))
        charge = payments.criar_cobranca(
            self.op,
            valor=D("180"),
            metodo="pix",
            descricao="QA parte online",
            finalidade=Cobranca.Finalidade.SALDO,
            reserva_id=r.pk,
        )
        payments.confirmar_pagamento(charge, self.op)
        self.assertEqual(account.saldo(), D("367"))
        booking.receber_pagamento(account, self.op, self.cash, account.saldo())
        r.fazer_checkout(self.op)
        account.refresh_from_db()
        self.assertFalse(account.aberta)
        self.assertFalse(housekeeping.uh_pronta_para_checkin(self.room))


@override_settings(
    FNRH_BLOQUEAR_CHECKIN=False,
    PRECO_TAXAS_ATIVAS=False,
    PAGAMENTOS_GATEWAY="simulado",
    FISCAL_GATEWAY="simulado",
)
class ExtendedContracts(FixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def test_payment_confirm_then_stale_cancel_preserves_paid_status(self):
        from apps.pagamentos import services as pay
        from apps.pagamentos.models import Cobranca

        r = self.reservation()
        c = pay.criar_cobranca(
            self.op, valor=D("180"), metodo="pix", descricao="QA", reserva_id=r.pk
        )
        stale = Cobranca.objects.get(pk=c.pk)
        pay.confirmar_pagamento(c, self.op)
        try:
            pay.cancelar(stale, self.op)
        except ValidationError:
            pass
        c.refresh_from_db()
        self.assertEqual(c.status, Cobranca.Status.PAGO)

    def make_lead(self, **extra):
        from apps.comercial import services as crm
        from apps.comercial.models import EtapaFunil

        step, _ = EtapaFunil.objects.get_or_create(nome="QA Leads")
        return crm.criar_oportunidade(
            usuario=self.op,
            pessoa=self.guest,
            titulo="QA family",
            etapa=step,
            disparar_crm=False,
            **extra,
        )

    def test_crm_conversion_preserves_adult_child_composition(self):
        from apps.comercial import services as crm

        lead = self.make_lead(adultos=2, criancas=2, hospedes=4, idades_criancas=[3, 8])
        r = crm.converter_em_reserva(
            lead,
            uh=self.room,
            checkin=self.today,
            checkout=self.today + timedelta(days=2),
            usuario=self.op,
            valor_diaria=D("300"),
        )
        self.assertEqual((r.adultos, r.criancas), (2, 2))

    def test_crm_stale_double_conversion_does_not_create_two_bookings(self):
        from apps.comercial import services as crm
        from apps.comercial.models import Oportunidade

        lead = self.make_lead()
        stale = Oportunidade.objects.get(pk=lead.pk)
        for obj in (lead, stale):
            try:
                crm.converter_em_reserva(
                    obj,
                    uh=self.room,
                    checkin=self.today,
                    checkout=self.today + timedelta(days=2),
                    usuario=self.op,
                    valor_diaria=D("300"),
                )
            except ValidationError:
                pass
        count = Reserva.objects.filter(hospede=self.guest).count()
        self.assertEqual(count, 1)

    def test_logbook_stale_reply_cannot_reopen_resolved_incident(self):
        from apps.nucleo import logbook_services as log
        from apps.nucleo.models import EntradaLogbook

        other = Usuario.objects.create_user(username="qa_other", password=None)
        item = log.registrar_ocorrencia(self.op, "QA leakage", True)
        stale = EntradaLogbook.objects.get(pk=item.pk)
        log.resolver(self.op, item, "QA fixed")
        try:
            log.comentar(other, stale, "QA reply from another shift")
        except ValidationError:
            pass
        item.refresh_from_db()
        self.assertEqual(item.status, EntradaLogbook.RESOLVIDA)


@override_settings(
    FNRH_BLOQUEAR_CHECKIN=False,
    PRECO_TAXAS_ATIVAS=False,
    PAGAMENTOS_GATEWAY="simulado",
    FISCAL_GATEWAY="simulado",
)
class RealConcurrency(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.build_fixture()

    def race(self, count, fn, prepare=lambda i: None):
        barrier = Barrier(count, timeout=20)

        def worker(i):
            close_old_connections()
            start = time.perf_counter()
            try:
                obj = prepare(i)
                barrier.wait()
                value = fn(i, obj)
                return {
                    "status": "ok",
                    "value": str(getattr(value, "pk", value)),
                    "seconds": time.perf_counter() - start,
                }
            except ValidationError as exc:
                return {"status": "rejected", "error": str(exc)}
            except Exception as exc:
                return {"status": "error", "type": type(exc).__name__, "error": str(exc)}
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as pool:
            rows = list(pool.map(worker, range(count)))
        self.assertFalse([r for r in rows if r["status"] == "error"], rows)
        return rows

    def test_16_requests_for_last_room_only_one_reservation(self):
        rows = self.race(
            16,
            lambda i, _: booking.criar_prereserva(
                uh=self.room,
                checkin=self.today,
                checkout=self.today + timedelta(days=2),
                hospede=self.guest,
                usuario=self.op,
                valor_diaria=D("300"),
            ),
        )
        self.assertEqual(sum(r["status"] == "ok" for r in rows), 1)
        self.assertEqual(Reserva.objects.count(), 1)

    def test_8_waiters_add_same_item_without_lost_quantity(self):
        from apps.restaurante import services as rest
        from apps.restaurante.models import Comanda

        order = rest.abrir_comanda(self.op, self.kitchen, rotulo="QA concurrency")
        self.race(
            8,
            lambda i, o: rest.adicionar_item(o, self.product, 1, self.op),
            lambda i: Comanda.objects.get(pk=order.pk),
        )
        self.assertEqual(order.itens.aggregate(q=Sum("quantidade"))["q"], D("8"))
        self.assertEqual(saldo(self.product, self.kitchen), D("12"))

    def test_two_waiters_remove_same_item_stock_returned_once(self):
        from apps.restaurante import services as rest
        from apps.restaurante.models import ItemComanda

        order = rest.abrir_comanda(self.op, self.kitchen, rotulo="QA concurrency")
        item = rest.adicionar_item(order, self.product, 3, self.op)
        self.race(
            2,
            lambda i, it: rest.remover_item(it, self.op),
            lambda i: ItemComanda.objects.get(pk=item.pk),
        )
        self.assertEqual(saldo(self.product, self.kitchen), D("20"))

    def test_laundry_double_delivery_bills_once(self):
        from apps.lavanderia import services as wash
        from apps.lavanderia.models import OrdemLavanderia, ServicoLavanderia
        from apps.nucleo.models import MovimentoCaixa

        service = ServicoLavanderia.objects.create(nome="QA Lavar", preco=D("12"))
        order = wash.abrir_ordem(self.op, cliente=self.guest)
        wash.adicionar_item(order, service, 1, self.op)
        rows = self.race(
            2,
            lambda i, o: wash.entregar(o, self.op, "caixa", forma=self.cash),
            lambda i: OrdemLavanderia.objects.get(pk=order.pk),
        )
        self.assertEqual(sum(r["status"] == "ok" for r in rows), 1)
        self.assertEqual(
            MovimentoCaixa.objects.filter(descricao=f"Lavanderia #{order.pk}").count(), 1
        )

    def test_laundry_8_additions_do_not_lose_items(self):
        from apps.lavanderia import services as wash
        from apps.lavanderia.models import OrdemLavanderia, ServicoLavanderia

        service = ServicoLavanderia.objects.create(nome="QA Lavar", preco=D("12"))
        order = wash.abrir_ordem(self.op, cliente=self.guest)
        wash.adicionar_item(order, service, 1, self.op)
        rows = self.race(
            8,
            lambda i, o: wash.adicionar_item(o, service, 1, self.op),
            lambda i: OrdemLavanderia.objects.get(pk=order.pk),
        )
        self.assertEqual(sum(row["status"] == "ok" for row in rows), 8)
        quantity = order.itens.aggregate(q=Sum("quantidade"))["q"]
        self.assertEqual(quantity, D("9"))

    def test_two_linen_distributions_cannot_overdraw_five_clean_items(self):
        from apps.lavanderia import services as wash
        from apps.lavanderia.models import ItemEnxoval, MovimentoEnxoval

        linen = ItemEnxoval.objects.create(nome="QA lençol")
        wash.adquirir(linen, 5, self.op)
        original = wash.saldo_enxoval
        rows = self.race(2, lambda i, _: wash.distribuir(linen, 4, self.op))
        self.assertEqual(sum(row["status"] == "ok" for row in rows), 1)
        clean = original(linen, MovimentoEnxoval.Estado.LIMPA)
        self.assertEqual(clean, 1)
        self.assertEqual(original(linen, MovimentoEnxoval.Estado.EM_USO), 4)

    def test_8_bank_settlements_emit_one_event(self):
        from apps.pagamentos import services as payment
        from apps.pagamentos.models import Cobranca, EventoPagamento

        charge = payment.criar_cobranca(
            self.op, valor=D("100"), metodo="pix", descricao="QA settlement"
        )
        payment.confirmar_pagamento(charge, self.op)
        self.race(
            8,
            lambda i, c: payment.registrar_liquidacao(
                c, valor_liquido=D("98"), taxa=D("2"), id_liquidacao="QA-unique"
            ),
            lambda i: Cobranca.objects.get(pk=charge.pk),
        )
        events = EventoPagamento.objects.filter(cobranca=charge, tipo="liquidada").count()
        self.assertEqual(events, 1)

    def test_same_bank_file_imported_simultaneously_does_not_duplicate_transactions(self):
        from apps.conciliacao import services as rec
        from apps.conciliacao.models import LancamentoExtrato

        content = "<OFX><BANKTRANLIST><STMTTRN><DTPOSTED>20261020<TRNAMT>100.00<FITID>QA-unique<NAME>QA</STMTTRN></BANKTRANLIST></OFX>"
        saved = LancamentoExtrato.save
        barrier = Barrier(2, timeout=15)

        def synchronized_save(item, *a, **kw):
            barrier.wait()
            return saved(item, *a, **kw)

        with mock.patch.object(LancamentoExtrato, "save", synchronized_save):
            self.race(
                2,
                lambda i, _: rec.importar_ofx(
                    conteudo=content, banco="QA", conta="QA", usuario=self.op
                ),
            )
        count = LancamentoExtrato.objects.filter(fitid="QA-unique").count()
        self.assertEqual(count, 1)

    def test_concurrent_marketing_approvals_cannot_exceed_monthly_budget(self):
        from apps.marketing import services as mkt
        from apps.marketing.models import Campanha

        mkt.definir_teto(self.today.strftime("%Y-%m"), "1000")
        campaigns = [
            Campanha.objects.create(
                nome=f"QA Marketing {i}",
                fase=Campanha.Fase.APROVACAO,
                verba_prevista=D("700"),
                inicio=self.today,
            )
            for i in range(2)
        ]
        original = mkt.posicao_verba
        rows = self.race(2, lambda i, _: mkt.avancar(campaigns[i], self.op))
        self.assertEqual(sum(row["status"] == "ok" for row in rows), 1)
        position = original(self.today.strftime("%Y-%m"))
        self.assertEqual(position["disponivel"], D("300"))


@override_settings(FNRH_BLOQUEAR_CHECKIN=False, PRECO_TAXAS_ATIVAS=False)
class PendingGuestConsumption(FixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def test_pending_portal_restaurant_order_prevents_final_checkout(self):
        from apps.portal import services as portal

        r, account = self.stay()
        order = portal.pedir_restaurante(booking.dados_estadia(r.pk), [(self.product.pk, 1)])
        booking.receber_pagamento(account, self.op, self.cash, account.saldo())
        rejected = False
        try:
            r.fazer_checkout(self.op)
        except ValidationError:
            rejected = True
        r.refresh_from_db()
        order.refresh_from_db()
        self.assertTrue(rejected, "Guest can leave with an open room order that was never billed")


@override_settings(FNRH_BLOQUEAR_CHECKIN=False, PRECO_TAXAS_ATIVAS=False)
class SharedResourceRaces(FixtureMixin, TransactionTestCase):
    race = RealConcurrency.race

    def setUp(self):
        self.build_fixture()

    def test_booking_and_maintenance_cannot_both_reserve_same_dates(self):
        from apps.manutencao import services as maintenance
        from apps.manutencao.models import OrdemServico

        def operation(i, _):
            if i == 0:
                return booking.criar_prereserva(
                    uh=self.room,
                    checkin=self.today,
                    checkout=self.today + timedelta(days=2),
                    hospede=self.guest,
                    usuario=self.op,
                    valor_diaria=D("300"),
                )
            return maintenance.abrir_os(
                self.op,
                uh=self.room,
                titulo="QA repair race",
                bloquear=True,
                bloqueio_inicio=self.today,
                bloqueio_fim=self.today + timedelta(days=2),
            )

        rows = self.race(2, operation)
        self.assertEqual(sum(row["status"] == "ok" for row in rows), 1)
        bookings = Reserva.objects.count()
        blocks = OrdemServico.objects.filter(bloqueia_uh=True).count()
        self.assertEqual(
            bookings + blocks, 1, "Room booked and blocked for repair on the same dates"
        )

    def test_last_crib_cannot_be_promised_to_two_rooms(self):
        from apps.reservas.models import BercoEstoque

        BercoEstoque.objects.update_or_create(pk=1, defaults={"quantidade": 1})

        def reserve(i, _):
            return booking.criar_prereserva(
                uh=self.room if i == 0 else self.room2,
                checkin=self.today,
                checkout=self.today + timedelta(days=2),
                hospede=self.guest,
                usuario=self.op,
                valor_diaria=D("300"),
                usa_berco=True,
            )

        rows = self.race(2, reserve)
        self.assertEqual(sum(row["status"] == "ok" for row in rows), 1)
        count = Reserva.objects.filter(usa_berco=True).count()
        self.assertEqual(count, 1, "One physical crib promised to two simultaneous stays")


@override_settings(
    FNRH_BLOQUEAR_CHECKIN=False,
    PRECO_TAXAS_ATIVAS=False,
    SECURE_SSL_REDIRECT=False,
    FNRH_GATEWAY="simulado",
)
class OpeningContracts(FixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def inventory(self):
        inv = Inventario.objects.create(local=self.shop, criado_por=self.op)
        ItemInventario.objects.create(
            inventario=inv,
            produto=self.product,
            saldo_sistema=D("20"),
            quantidade_contada=D("18"),
            contado=True,
        )
        return inv

    def test_count_cannot_erase_sales_made_after_physical_count(self):
        inv = self.inventory()
        registrar_saida(self.product, self.shop, D("3"), self.op)
        rejected = False
        try:
            inv.aplicar(self.op, somente_contados=True)
        except ValidationError:
            rejected = True
        actual = saldo(self.product, self.shop)
        self.assertTrue(rejected or actual == D("15"))

    def test_stale_count_cannot_be_applied_twice_after_new_sale(self):
        inv = self.inventory()
        stale = Inventario.objects.get(pk=inv.pk)
        inv.aplicar(self.op, somente_contados=True)
        registrar_saida(self.product, self.shop, D("1"), self.op)
        try:
            stale.aplicar(self.op, somente_contados=True)
        except ValidationError:
            pass
        self.assertEqual(saldo(self.product, self.shop), D("17"))
