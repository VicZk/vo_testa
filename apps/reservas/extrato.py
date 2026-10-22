"""Conferência do hóspede: totais derivados das mesmas linhas exibidas no papel."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.nucleo.sistema import travar

from .models import LancamentoConta

ZERO = Decimal("0.00")


def _credito(credito, adiantamento=False):
    if getattr(credito, "conta_receber_id", None):
        tipo = "Faturado"
        forma = f"A receber em {credito.conta_receber.vencimento:%d/%m/%Y}"
    elif credito.cobranca_id:
        tipo = "Adiantamento" if adiantamento else "Pagamento"
        forma = "Pagamento online"
    elif credito.movimento_caixa_id:
        tipo = "Adiantamento" if adiantamento else "Pagamento"
        forma = str(credito.movimento_caixa.forma_pagamento or "Dinheiro")
    else:
        tipo, forma = "Crédito", "Crédito registrado"
    if credito.eh_estorno:
        tipo = "Estorno de adiantamento" if adiantamento else "Estorno de pagamento"
    return {"data": credito.criado_em, "tipo": tipo, "forma": forma,
            "observacao": credito.observacao, "valor": credito.valor}


@transaction.atomic
def dados_extrato(conta):
    """Não recalcula tarifas e não inclui cobranças online ainda não pagas.

    A trava da conta serializa a conferência com lançamentos/fechamento. As somas
    usam as listas materializadas, sem consultar novamente os valores ao renderizar.
    """
    travar(conta)
    lancamentos = list(conta.lancamentos.order_by("competencia", "criado_em", "pk"))
    pagamentos = [_credito(p) for p in conta.pagamentos.select_related(
        "movimento_caixa__forma_pagamento", "conta_receber"
    ).order_by("criado_em", "pk")]
    if conta.reserva_id:
        pagamentos.extend(_credito(a, adiantamento=True) for a in
                          conta.reserva.adiantamentos.select_related("movimento_caixa__forma_pagamento"))
    pagamentos.sort(key=lambda p: p["data"])
    subtotal = sum((item.valor for item in lancamentos if item.tipo in LancamentoConta.TIPOS_DEBITO), ZERO)
    descontos = sum((item.valor for item in lancamentos if item.tipo == LancamentoConta.Tipo.DESCONTO), ZERO)
    creditos = sum((p["valor"] for p in pagamentos), ZERO)
    from .services import pendencias_consumo

    return {"conta": conta, "lancamentos": lancamentos, "pagamentos": pagamentos,
            "subtotal": subtotal, "descontos": descontos, "total": subtotal - descontos,
            "creditos": creditos, "saldo": subtotal - descontos - creditos,
            "saldo_absoluto": abs(subtotal - descontos - creditos),
            "pendencias": pendencias_consumo(conta), "emitido_em": timezone.now()}
