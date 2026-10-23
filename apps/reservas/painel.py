"""Dados de leitura para as chegadas e saídas do Painel."""

from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse

from apps.nucleo.models.cadastros import ConfiguracaoReservas

from .models import Adiantamento, ContaHospedagem


def preparar_fluxo_painel(chegadas, saidas):
    """Acrescenta saldo e destino da ação sem executar nenhuma etapa da estadia.

    As reservas devem trazer ``conta`` e ``grupo`` via select_related. O saldo de
    contas existentes usa a mesma regra do extrato, em lote. Antes de abrir a
    conta, a chegada avulsa mostra diárias e taxas previstas menos o sinal líquido.
    A diária de um grupo pertence ao folio-mãe e não ao consumo de cada quarto.
    """
    reservas = [*chegadas, *saidas]
    contas = [r.conta for r in reservas if getattr(r, "conta", None)]
    saldos = ContaHospedagem.saldos(contas)
    previstas = [
        r for r in chegadas if not r.grupo_id and not getattr(r, "conta", None)
    ]
    cfg = ConfiguracaoReservas.carregar() if previstas else None
    adiantamentos = {
        linha["reserva_id"]: linha["total"]
        for linha in Adiantamento.objects.filter(reserva_id__in=[r.pk for r in previstas])
        .order_by()
        .values("reserva_id")
        .annotate(total=Sum("valor"))
    }
    chegada_ids = {r.pk for r in chegadas}
    zero = Decimal("0.00")

    for reserva in reservas:
        chegada = reserva.pk in chegada_ids
        conta = getattr(reserva, "conta", None)
        grupo_url = (
            reverse("reservas:grupo_detalhe", args=[reserva.grupo_id])
            if reserva.grupo_id else ""
        )
        referencia = "Consumos do quarto" if reserva.grupo_id else "Conta da estadia"
        saldo = None

        if chegada and reserva.grupo_id:
            # O folio pode ter recebido sinal antes de lançar as diárias. Não
            # apresentar esse crédito como quitação ou excedente de cada quarto.
            estado, rotulo = "grupo", "Cobrança no grupo"
            referencia = "Diárias na conta do grupo"
        elif conta:
            saldo = saldos[conta.pk]
        elif chegada:
            saldo = reserva.total_previsto(cfg=cfg) - adiantamentos.get(reserva.pk, zero)
            referencia = "Previsto · diárias e taxas"
        else:
            # Uma saída sem folio é inconsistência a conferir, não saldo zero.
            estado, rotulo = "indisponivel", "Conferir conta"

        if saldo is not None:
            if saldo < zero:
                estado, rotulo = "credito", "Crédito"
            elif saldo > zero:
                estado, rotulo = "devedor", "Saldo devedor"
            else:
                estado = "sem_saldo"
                rotulo = (
                    "Sem saldo no quarto" if reserva.grupo_id
                    else "Sem saldo previsto" if chegada and not conta
                    else "Sem saldo"
                )

        reserva.painel_financeiro = {
            "estado": estado,
            "rotulo": rotulo,
            "saldo": saldo,
            "valor": abs(saldo) if saldo is not None else None,
            "referencia": referencia,
            "grupo_url": grupo_url,
        }
        reserva.painel_acao_url = (
            reverse("reservas:detalhe", args=[reserva.pk]) + "#acoes-estadia"
        )
