from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError


def ratear_desconto(total, bases):
    """Distribui centavos pelos maiores restos, sem valor negativo nem sobra."""
    soma = sum(bases, Decimal("0"))
    if total < 0 or total > soma or any(base < 0 for base in bases):
        raise ValidationError("O desconto não pode exceder a base fiscal.")
    if not soma:
        return [Decimal("0.00") for _ in bases]
    proporcoes = [total*base/soma for base in bases]
    parcelas = [valor.quantize(Decimal(".01"), rounding=ROUND_DOWN) for valor in proporcoes]
    centavos = int((total-sum(parcelas, Decimal("0")))*100)
    ordem = sorted(range(len(bases)), key=lambda i:(proporcoes[i]-parcelas[i], -i), reverse=True)
    for indice in ordem[:centavos]:
        parcelas[indice] += Decimal(".01")
    return parcelas
