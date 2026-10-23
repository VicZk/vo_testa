"""Formulários da Manutenção: campos válidos antes de qualquer mudança de estado."""

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.nucleo.models import UH, Pessoa, Usuario

from .models import OrdemServico
from .services import custo_valido, validar_programacao


class CustoOSField(forms.Field):
    widget = forms.TextInput

    def to_python(self, value):
        if value in self.empty_values:
            return Decimal("0.00")
        return custo_valido(value, nome=self.label or "Custo")


class NovaOSForm(forms.Form):
    uh = forms.ModelChoiceField(label="Quarto", queryset=UH.objects.none(), required=False)
    area = forms.CharField(label="Área comum", max_length=80, required=False)
    titulo = forms.CharField(label="Título", max_length=120)
    descricao = forms.CharField(label="Descrição", required=False)
    tipo = forms.ChoiceField(label="Tipo", choices=OrdemServico.Tipo.choices, required=False)
    prioridade = forms.ChoiceField(label="Prioridade", choices=OrdemServico.Prioridade.choices, required=False)
    responsavel = forms.ModelChoiceField(label="Responsável", queryset=Usuario.objects.none(), required=False)
    prestador = forms.ModelChoiceField(label="Prestador", queryset=Pessoa.objects.none(), required=False)
    previsto_para = forms.DateField(label="Previsto para", required=False, input_formats=["%Y-%m-%d"])
    bloquear = forms.BooleanField(label="Bloquear quarto", required=False)
    recorrencia_meses = forms.IntegerField(label="Recorrência", min_value=1, max_value=120, required=False)
    agendada_para = forms.DateField(label="Agendada para", required=False, input_formats=["%Y-%m-%d"])
    bloqueio_inicio = forms.DateField(label="Início do bloqueio", required=False, input_formats=["%Y-%m-%d"])
    bloqueio_fim = forms.DateField(label="Fim do bloqueio", required=False, input_formats=["%Y-%m-%d"])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["uh"].queryset = UH.objects.exclude(status=UH.Status.INATIVA)
        self.fields["responsavel"].queryset = Usuario.objects.filter(is_active=True)
        self.fields["prestador"].queryset = Pessoa.objects.filter(ativo=True).filter(
            Q(fornecedor__isnull=False) | Q(agencia__isnull=False))

    def clean_tipo(self):
        return self.cleaned_data["tipo"] or OrdemServico.Tipo.CORRETIVA

    def clean_prioridade(self):
        return self.cleaned_data["prioridade"] or OrdemServico.Prioridade.MEDIA

    def clean(self):
        dados = super().clean()
        if "uh" in dados and "area" in dados:
            if not dados["uh"] and not dados["area"]:
                raise ValidationError("Escolha um quarto ou informe a área comum.")
            if dados["uh"] and dados["area"]:
                raise ValidationError("Informe apenas um alvo: quarto OU área comum.")
            if dados.get("bloquear") and not dados["uh"]:
                self.add_error("bloquear", "Só é possível bloquear um quarto.")
        if all(campo in dados for campo in ("tipo", "recorrencia_meses", "agendada_para", "previsto_para")):
            try:
                validar_programacao(dados["tipo"], dados["recorrencia_meses"], dados["agendada_para"], dados["previsto_para"])
            except ValidationError as erro:
                self.add_error(None, erro)
        inicio, fim = dados.get("bloqueio_inicio"), dados.get("bloqueio_fim")
        if inicio and fim and fim < inicio:
            self.add_error("bloqueio_fim", "O fim do bloqueio não pode ser anterior ao início.")
        return dados


class ConcluirOSForm(forms.Form):
    resolucao = forms.CharField(label="Resolução", required=False)
    custo_maodeobra = CustoOSField(label="Mão de obra", required=False)
    custo_pecas = CustoOSField(label="Peças", required=False)
    nota_fiscal = forms.CharField(label="Número da nota / documento", max_length=60, required=False)
    garantia_ate = forms.DateField(label="Garantia até", required=False, input_formats=["%Y-%m-%d"])
