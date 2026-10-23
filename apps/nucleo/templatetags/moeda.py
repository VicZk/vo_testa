"""Filtro de moeda único do sistema (pt-BR).

Fonte única de formatação de dinheiro para templates e e-mails — por isso mora
no núcleo, não em Pagamentos. `{{ valor|intcomma_brl }}` → "R$ 1.600,00".

Regra de ouro: um só formatador. Não criar um segundo em outro app — dois
formatadores no mesmo sistema sempre divergem em algum caso.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def intcomma_brl(valor, casas=2):
    """Moeda com duas casas; custos unitários podem pedir quatro com `:4`."""
    casas = 4 if casas in (4, "4") else 2
    zero = "R$ 0," + "0" * casas
    if valor is None or valor == "":
        return zero
    try:
        v = Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return zero

    inteiro, _, centavos = f"{abs(v):.{casas}f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = f"R$ {'.'.join(grupos)},{centavos}"
    return f"-{texto}" if v < 0 else texto


@register.filter
def milhar(valor):
    """1234567 → '1.234.567' (contagens, como o total de uma lista; dinheiro é
    `intcomma_brl`). O que não for número volta como veio."""
    try:
        return f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return valor
