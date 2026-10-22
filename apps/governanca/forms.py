"""Formulários curtos para quem está trabalhando nos quartos."""
from django import forms


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
