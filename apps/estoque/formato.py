"""Como o estoque fala número na tela.

O saldo é `DecimalField(decimal_places=3)` porque existe meio quilo de café; mas
"55,000 unidade" não é como ninguém conta prateleira. Aqui o número perde os
zeros que não dizem nada e a unidade vira sigla: `55 un`, `4,5 kg`, `5 L`.

Mora fora do `templatetags` porque a tela de movimentação também precisa dele
em JSON (a prévia "saldo hoje → depois" é escrita em JavaScript).
"""
from decimal import Decimal, InvalidOperation

# Sigla por unidade do catálogo (`Produto.Unidade`). Litro em maiúscula é a
# forma recomendada do SI — "l" solto se confunde com o algarismo 1.
SIGLAS = {
    "un": "un", "kg": "kg", "g": "g", "l": "L",
    "ml": "ml", "cx": "cx", "pct": "pct", "dz": "dz",
}


def sigla(unidade: str) -> str:
    return SIGLAS.get(unidade, unidade)


def numero(valor) -> str:
    """Decimal → texto pt-BR sem zero à toa: 55.000 → '55' · 4.500 → '4,5'."""
    try:
        v = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return "0"
    negativo = v < 0
    v = abs(v).quantize(Decimal("0.001"))
    inteiro, _, decimais = f"{v:f}".partition(".")
    decimais = decimais.rstrip("0")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = ".".join(grupos) + (f",{decimais}" if decimais else "")
    return f"-{texto}" if negativo else texto


def quantidade(valor, unidade: str) -> str:
    """'55 un' — o número do jeito de gente, com a sigla da unidade."""
    return f"{numero(valor)} {sigla(unidade)}"


def com_sinal(valor, unidade: str) -> str:
    """'+12 un' / '−3 un' — movimento do kardex, onde o sinal é a informação.
    O menos é o sinal tipográfico (U+2212), que alinha com os algarismos."""
    texto = quantidade(valor, unidade)
    if texto.startswith("-"):
        return "−" + texto[1:]
    return f"+{texto}" if Decimal(str(valor or 0)) > 0 else texto
