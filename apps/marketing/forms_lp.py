"""Formulários da Aprovação de LPs."""
from django import forms
from django.utils.text import slugify

from .models import AprovacaoLP, Campanha, ComentarioLP
from .services_lp import LIMITE_TEXTO


def _arquivo():
    return forms.FileField(
        label="Arquivo da LP (.html)",
        widget=forms.FileInput(attrs={"accept": ".html,.htm,text/html"}),
        help_text="O HTML que o design entrega, com fotos e fontes dentro do arquivo.")


class NovaLPForm(forms.Form):
    nome = forms.CharField(label="Nome da LP", max_length=140)
    campanha = forms.ModelChoiceField(
        label="Campanha", queryset=Campanha.objects.order_by("nome", "id"), required=False,
        empty_label="Sem campanha")
    prazo = forms.DateField(
        label="Prazo da aprovação", required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        help_text="Aparece no Cronograma do Marketing.")
    arquivo = _arquivo()
    nota = forms.CharField(label="Recado para quem vai revisar", max_length=300, required=False)


class NovaVersaoForm(forms.Form):
    arquivo = _arquivo()
    nota = forms.CharField(label="O que mudou", max_length=300, required=False,
                           widget=forms.TextInput(attrs={"placeholder": "Ex.: troquei a foto do topo"}))


class ComentarioLPForm(forms.Form):
    nome = forms.CharField(label="Seu nome", max_length=80)
    texto = forms.CharField(label="Comentário", max_length=LIMITE_TEXTO, required=False,
                            widget=forms.Textarea(attrs={"rows": 3}))
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    tipo = forms.ChoiceField(choices=ComentarioLP.Tipo.choices)


class PublicarLPForm(forms.Form):
    slug = forms.SlugField(
        label="Endereço", max_length=60,
        help_text="A LP fica em /lp/<endereço>/. Só letras minúsculas, números e hífen.")

    def __init__(self, *args, aprovacao: AprovacaoLP, **kwargs):
        kwargs.setdefault("initial", {"slug": aprovacao.slug or slugify(aprovacao.nome)[:60]})
        super().__init__(*args, **kwargs)
