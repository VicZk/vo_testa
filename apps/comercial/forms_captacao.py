"""Contato público: validar antes de gravar e devolver os campos após um erro."""
from django import forms
from django.utils import timezone

from apps.nucleo.forms import DataInput

from .forms_lead import ContatoLeadForm
from .models import Oportunidade


class CaptacaoPublicaForm(ContatoLeadForm):
    checkin = forms.DateField(label="Entrada", required=False, widget=DataInput())
    checkout = forms.DateField(label="Saída", required=False, widget=DataInput())
    pessoas = forms.IntegerField(
        label="Quantas pessoas?", required=False, min_value=1, max_value=8, initial=2,
        widget=forms.Select(choices=[(n, f"{n} pessoa" + ("s" if n > 1 else "")) for n in range(1, 9)]),
    )
    consent = forms.BooleanField(required=False)

    def __init__(self, *args, tipo_interesse="hospedagem", **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        self.tipo_interesse = tipo_interesse
        self.fields["nome"].label = "Seu nome"
        self.fields["telefone"].label = "WhatsApp (com DDD)"
        self.fields["telefone"].required = True
        self.fields["telefone"].widget = forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"})
        self.fields["nome"].widget.attrs["autocomplete"] = "name"
        self.fields["email"].label = "E-mail (opcional)"
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        for nome in ("checkin", "checkout"):
            self.fields[nome].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean_pessoas(self):
        return self.cleaned_data.get("pessoas") or 2

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("checkin"), dados.get("checkout")
        if fim and not inicio:
            self.add_error("checkin", "Informe também a data de entrada.")
        if inicio and fim:
            day_use = self.tipo_interesse == Oportunidade.TipoInteresse.DAY_USE
            if fim < inicio or (fim == inicio and not day_use):
                self.add_error("checkout", "A saída precisa ser depois da entrada.")
        return dados
