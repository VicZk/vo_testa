"""Dados de campanha: validação visível, sem salvar valores inválidos em silêncio."""
import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from . import services
from .models import Campanha

SECOES = {
    "dados": ("nome", "objetivo", "publico", "inicio", "fim", "verba_prevista"),
    "objetivo": ("etapa_funil", "objetivo_tipo", "meta_valor", "realizado_valor"),
    "retro": ("retro_funcionou", "retro_nao", "retro_diferente"),
}


class NumeroBrasileiro(forms.DecimalField):
    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            return super().to_python(services.parse_moeda(value))
        except (ValueError, ValidationError):
            raise ValidationError("Digite um número válido, como 150 ou 1.500,50.") from None


class DadosCampanhaForm(forms.ModelForm):
    verba_prevista = NumeroBrasileiro(
        label="Investimento previsto (R$)", min_value=Decimal("0"),
        max_digits=10, decimal_places=2,
    )
    meta_valor = NumeroBrasileiro(
        label="Meta a atingir", min_value=Decimal("0"), required=False,
        max_digits=12, decimal_places=2,
    )
    realizado_valor = NumeroBrasileiro(
        label="Resultado alcançado", min_value=Decimal("0"), required=False,
        max_digits=12, decimal_places=2,
    )
    canais = forms.CharField(required=False)

    class Meta:
        model = Campanha
        fields = (*SECOES["dados"], *SECOES["objetivo"], *SECOES["retro"], "canais")
        labels = {
            "nome": "Nome da campanha", "objetivo": "O que queremos conseguir?",
            "publico": "Para quem é a campanha?", "inicio": "Data de início",
            "fim": "Data de término", "etapa_funil": "Momento do cliente",
            "objetivo_tipo": "Resultado que vamos medir",
            "retro_funcionou": "O que funcionou?", "retro_nao": "O que não funcionou?",
            "retro_diferente": "O que mudar na próxima campanha?",
        }
        widgets = {
            "inicio": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "fim": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            **{name: forms.Textarea(attrs={"rows": 2}) for name in (
                "objetivo", "retro_funcionou", "retro_nao", "retro_diferente")},
        }

    def __init__(self, *args, campos=None, **kwargs):
        super().__init__(*args, **kwargs)
        if campos is not None:
            self.fields = {key: field for key, field in self.fields.items() if key in campos}
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "fx-sel" if isinstance(field.widget, forms.Select) else "fx-in"
            if isinstance(field, NumeroBrasileiro):
                field.widget = forms.TextInput(attrs={"class": "fx-in num", "inputmode": "decimal"})
                field.localize = True
                field.widget.is_localized = True
            if name in ("inicio", "verba_prevista") and self.instance.aprovada_em:
                field.disabled = True
                field.help_text = "Definido na aprovação da campanha."

    def clean_canais(self):
        return [value.strip() for value in self.cleaned_data["canais"].split(",") if value.strip()]

    def clean(self):
        data = super().clean()
        inicio = data.get("inicio", self.instance.inicio)
        fim = data.get("fim", self.instance.fim)
        if inicio and fim and fim < inicio:
            field = "fim" if "fim" in self.fields else None
            self.add_error(field, "O término precisa ser no mesmo dia ou depois do início.")
        return data


class NovaCampanhaForm(forms.ModelForm):
    chave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    class Meta:
        model = Campanha
        fields = ("nome", "objetivo")
        labels = {"nome": "Nome da campanha", "objetivo": "O que queremos conseguir?"}
        widgets = {
            "nome": forms.TextInput(attrs={"autofocus": True, "placeholder": "Ex.: Férias em família"}),
            "objetivo": forms.Textarea(attrs={"rows": 3, "placeholder": "Ex.: Reservar as cabanas nos dias de menor ocupação"}),
        }
