"""Formulários curtos para quem está trabalhando nos quartos."""
from django import forms

from .models import ConfiguracaoGovernanca


class ConfiguracaoGovernancaForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoGovernanca
        fields = ["ativa", "horario", "distribuir"]
        widgets = {"horario": forms.TimeInput(format="%H:%M", attrs={"type": "time"})}


class RestricaoLimpezaForm(forms.Form):
    tipo = forms.ChoiceField(choices=[("nao_perturbe", "Não perturbe"),
        ("dispensa", "Limpeza dispensada hoje"), ("liberar", "Liberar atendimento")])
    ate = forms.DateTimeField(required=False, label="Não perturbe até",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    observacao = forms.CharField(required=False, max_length=200, label="Observação")


class ReportarProblemaForm(forms.Form):
    descricao = forms.CharField(
        label="O que precisa de conserto?", max_length=400,
        error_messages={
            "required": "Descreva o problema para abrir o chamado.",
            "max_length": "Use até 400 caracteres para descrever o problema.",
        },
        widget=forms.Textarea(attrs={
            "rows": 3, "autocomplete": "off",
            "placeholder": "Ex.: chuveiro pingando, lâmpada do banheiro queimada",
        }),
        help_text="Diga onde está o problema e o que você percebeu.",
    )
