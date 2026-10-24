"""Formulários de entregas com referências a recursos já existentes."""
from pathlib import PurePosixPath

from django import forms
from django.core.validators import URLValidator
from django.urls import reverse

from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo

from . import services_entregas
from .models import Campanha, ItemChecklist, PecaCampanha


class FiltroEntregasForm(forms.Form):
    vinculo = forms.ChoiceField(label="Vínculo", required=False, choices=[
        ("", "Todas"), ("sem", "Sem campanha"), ("com", "Por campanha")], widget=forms.HiddenInput)
    q = forms.CharField(label="Buscar entrega", max_length=140, required=False,
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Material ou campanha"}))
    tipo = forms.ChoiceField(label="Tipo", required=False,
                             choices=[("", "Todos os tipos"), *PecaCampanha.Tipo.choices])
    situacao = forms.ChoiceField(label="Situação", required=False, choices=[
        ("", "Todas as situações"), ("pendentes", "Pendentes"), *PecaCampanha.Status.choices])
    campanha = forms.ModelChoiceField(label="Campanha", required=False,
                                      queryset=Campanha.objects.order_by("nome", "id"),
                                      empty_label="Todas as campanhas")

    def clean(self):
        dados = super().clean()
        if dados.get("campanha"):
            dados["vinculo"] = "com"
        return dados


class EntregaForm(forms.Form):
    versao = forms.IntegerField(widget=forms.HiddenInput, min_value=1, initial=1)
    campanha = forms.ModelChoiceField(
        label="Campanha", queryset=Campanha.objects.order_by("nome", "id"), required=False,
        empty_label="Sem campanha (avulsa)",
        help_text="Opcional. Deixe sem campanha para produzir um material avulso.")
    nome = forms.CharField(label="Nome da entrega", max_length=140)
    tipo = forms.ChoiceField(label="Tipo", choices=PecaCampanha.Tipo.choices)
    canal = forms.CharField(label="Canal", max_length=40, required=False,
                            help_text="Onde será usada: Instagram, Meta Ads, recepção…")
    data = forms.DateField(label="Prazo", required=False,
                           widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    status = forms.ChoiceField(label="Situação da produção", choices=PecaCampanha.Status.choices,
                               initial=PecaCampanha.Status.A_FAZER,
                               help_text="Pronta indica produção concluída; não confirma publicação ou distribuição.")
    url_material = forms.URLField(label="Link do material", max_length=2048, required=False,
                                   validators=[URLValidator(schemes=["http", "https"])],
                                   help_text="Link do projeto, arte ou publicação existente.")
    material_checklist = forms.ModelChoiceField(
        label="Anexo já salvo na campanha", queryset=ItemChecklist.objects.none(), required=False,
        empty_label="Sem anexo vinculado")
    pagina_captacao = forms.TypedChoiceField(label="LP existente", required=False, coerce=int,
                                             empty_value=None, choices=[("", "Sem LP vinculada")])

    def __init__(self, *args, usuario, peca=None, campanha=None, **kwargs):
        self.peca = peca
        initial = dict(kwargs.pop("initial", {}))
        if peca:
            initial.update({nome: getattr(peca, nome) for nome in (
                "nome", "tipo", "canal", "data", "status", "url_material")})
            initial.update(campanha=peca.campanha_id, versao=peca.versao, material_checklist=peca.material_checklist_id,
                           pagina_captacao=peca.pagina_captacao_id)
            campanha = peca.campanha_id
        elif campanha:
            initial["campanha"] = campanha
        super().__init__(*args, initial=initial, **kwargs)
        if peca and peca.campanha_id:
            self.fields["campanha"].disabled = True
            self.fields["campanha"].help_text = "Esta entrega já está vinculada; o vínculo é preservado."
        elif peca:
            self.fields["campanha"].help_text = "Avulsa. Escolha uma campanha apenas se quiser vinculá-la; o vínculo será preservado."
        if not peca or not peca.campanha_id:
            self.fields["campanha"].widget.attrs.update({
                "hx-get": reverse("marketing:anexos_da_entrega"), "hx-trigger": "change",
                "hx-target": "#entrega-anexo", "hx-include": "this", "hx-swap": "innerHTML"})
        if not peca or peca.tipo != PecaCampanha.Tipo.NAO_CLASSIFICADO:
            self.fields["tipo"].choices = [("", "Selecione o tipo"), *(
                escolha for escolha in PecaCampanha.Tipo.choices
                if escolha[0] != PecaCampanha.Tipo.NAO_CLASSIFICADO)]
        escolhido = campanha if peca and peca.campanha_id else (self.data.get("campanha") if self.is_bound else campanha)
        try:
            campanha_id = int(escolhido)
        except (TypeError, ValueError):
            campanha_id = None
        anexos = ItemChecklist.objects.filter(campanha_id=campanha_id).exclude(arquivo="").exclude(arquivo__isnull=True)
        self.fields["material_checklist"].queryset = anexos
        self.fields["material_checklist"].label_from_instance = lambda item: PurePosixPath(item.arquivo.name).name
        paginas = services_entregas.referencias_lps(usuario)
        self.fields["pagina_captacao"].choices = [("", "Sem LP vinculada"), *(
            (pagina["id"], pagina["nome"]) for pagina in paginas)]
        if not (usuario.pode_acessar(Modulo.COMERCIAL) and modulo_ativo(Modulo.COMERCIAL)):
            if peca and peca.pagina_captacao_id:
                self.fields["pagina_captacao"].choices.append((peca.pagina_captacao_id, "LP vinculada"))
            self.fields["pagina_captacao"].disabled = True
            self.fields["pagina_captacao"].help_text = "Escolher e abrir LPs exige acesso ao Comercial."
        elif not paginas:
            self.fields["pagina_captacao"].help_text = "Cadastre a página no Comercial para vinculá-la aqui."
        for campo in self.fields.values():
            campo.widget.attrs["class"] = "fx-sel" if isinstance(campo.widget, forms.Select) else "fx-in"

    def clean(self):
        dados = super().clean()
        anexo = dados.get("material_checklist")
        campanha = dados.get("campanha")
        if anexo and (not campanha or anexo.campanha_id != campanha.pk):
            self.add_error("material_checklist", "Escolha um anexo desta campanha.")
        if dados.get("pagina_captacao") and dados.get("tipo") != PecaCampanha.Tipo.LP:
            self.add_error("pagina_captacao", "Escolha o tipo Landing page para vincular uma LP.")
        return dados
