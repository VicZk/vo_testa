"""Números escritos para gente (pt-BR), para usar em texto montado no Python.

Nos templates, os filtros de `nucleo_extras` fazem o mesmo papel.
"""
from decimal import Decimal


def pct_br(valor) -> str:
    """Percentual sem zeros à direita e com vírgula: 10 → "10", 12.5 → "12,5", 4.00 → "4".

    `Decimal.normalize()` sozinho escreve 10 como "1E+1" — era o que o site mostrava na
    política de cancelamento ("retemos 1E+1% do valor total") e o que ficava gravado no
    motivo do cancelamento ("reter 1E+1%")."""
    return format(Decimal(valor).normalize(), "f").replace(".", ",")
