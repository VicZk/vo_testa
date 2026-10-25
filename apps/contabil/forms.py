"""Fechamento mensal: valores em R$ pela máscara da casa (`ReaisField`/`ReaisInput`).

Antes o campo era texto cru e a view trocava a vírgula por ponto: "12.500,00" virava
"12.500.00", que não é número, e o valor entrava como zero sem aviso.
"""
from decimal import Decimal

from django import forms

from apps.nucleo.forms import ReaisField

from .models import FechamentoMensal

CAMPOS_VALOR = ("folha", "encargos", "pro_labore", "das")


def _valor(rotulo):
    return ReaisField(label=rotulo, required=False, min_value=Decimal("0"),
                      max_digits=12, decimal_places=2)


class FechamentoMensalForm(forms.ModelForm):
    folha = _valor("Folha")
    encargos = _valor("Encargos FGTS/INSS")
    pro_labore = _valor("Pró-labore")
    das = _valor("DAS / Simples")

    class Meta:
        model = FechamentoMensal
        fields = [*CAMPOS_VALOR, "observacao"]

    def clean(self):
        dados = super().clean()
        for campo in CAMPOS_VALOR:
            if dados.get(campo) is None and campo not in self.errors:
                dados[campo] = Decimal("0.00")  # vazio = nada a lançar (valor 0 apaga)
        return dados
