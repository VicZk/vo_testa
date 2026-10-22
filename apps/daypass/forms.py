import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.nucleo.forms import DataInput, ReaisInput
from apps.nucleo.models import FormaPagamento, LocalEstoque, Pessoa
from apps.reservas.services import hospedagens_para_daypass

from .models import TurnoDayPass


class TurnoForm(forms.ModelForm):
    data = forms.DateField(widget=DataInput())
    contar_hospedes = forms.TypedChoiceField(label="Hóspedes entram no limite de lotação?", choices=[("", "Selecione a regra"), ("sim", "Sim, hóspedes e visitantes usam o mesmo limite"), ("nao", "Não, este limite é exclusivo de visitantes")], coerce=lambda v: v == "sim")

    class Meta:
        model = TurnoDayPass
        fields = ["data", "nome", "inicio", "fim", "capacidade", "contar_hospedes", "preco_adulto", "preco_crianca", "preco_hospede", "ativo"]
        widgets = {"inicio": forms.TimeInput(attrs={"type": "time"}), "fim": forms.TimeInput(attrs={"type": "time"}), **{c: ReaisInput() for c in ("preco_adulto", "preco_crianca", "preco_hospede")}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial.update(data=self.instance.dia_id, contar_hospedes="sim" if self.instance.contar_hospedes else "nao")

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["fim"] <= dados["inicio"]:
            self.add_error("fim", "O fim deve ser posterior ao início, no mesmo dia.")
        if dados.get("data") and dados["data"] < timezone.localdate():
            self.add_error("data", "Use hoje ou uma data futura.")
        return dados


class VisitaForm(forms.Form):
    responsavel = forms.ModelChoiceField(label="Responsável pelo grupo", queryset=Pessoa.objects.none())
    hospedagem = forms.ModelChoiceField(label="Estadia vinculada (somente hóspedes)", queryset=hospedagens_para_daypass(), required=False)
    adultos = forms.CharField(label="Adultos, incluindo o responsável", widget=forms.Textarea(attrs={"rows": 3}), max_length=25000, help_text="Um nome completo por linha.")
    criancas = forms.CharField(label="Crianças acompanhadas", widget=forms.Textarea(attrs={"rows": 3}), max_length=25000, required=False, help_text="Um nome por linha. Todas as crianças ocupam vaga quando a regra do turno inclui o grupo.")
    chave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, turno, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsavel"].queryset = Pessoa.objects.filter(ativo=True)
        self.fields["hospedagem"].queryset = hospedagens_para_daypass(turno.dia_id)

    def _nomes(self, campo):
        nomes = [n.strip() for n in self.cleaned_data[campo].splitlines() if n.strip()]
        if len(nomes) > 200 or any(len(n) > 120 for n in nomes):
            raise ValidationError("Use até 200 nomes, com no máximo 120 caracteres cada.")
        return nomes

    def clean_adultos(self):
        return self._nomes("adultos")

    def clean_criancas(self):
        return self._nomes("criancas")


class PagamentoForm(forms.Form):
    forma = forms.ModelChoiceField(label="Forma de pagamento", queryset=FormaPagamento.objects.filter(ativo=True))
    valor = forms.DecimalField(label="Valor recebido (R$)", max_digits=10, decimal_places=2, min_value=Decimal("0.01"), widget=ReaisInput())
    chave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class ConsumoForm(forms.Form):
    local = forms.ModelChoiceField(label="Estoque de origem", queryset=LocalEstoque.objects.filter(ativo=True))
