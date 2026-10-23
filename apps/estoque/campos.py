"""Campos decimais em português sem reduzir a precisão de quantidade e custo."""
from decimal import Decimal, InvalidOperation

from django import forms


class DecimalBRInput(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__({"inputmode": "decimal", **(attrs or {})})

    def format_value(self, value):
        if value in (None, ""):
            return None
        # Strings são o texto submetido pelo usuário: preserve inclusive erros
        # e notação científica, sem expandir um expoente antes da validação.
        if isinstance(value, str):
            return value
        try:
            numero = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not numero.is_finite():
            return str(value)
        return format(numero, "f").replace(".", ",")


class DecimalBRField(forms.DecimalField):
    widget = DecimalBRInput

    def to_python(self, value):
        # O ponto decimal continua aceito para reenvios anteriores e clientes
        # HTTP. Só removemos separadores de milhar quando há vírgula explícita.
        if isinstance(value, str) and "," in value:
            value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)
