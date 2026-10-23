from decimal import Decimal
from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.nucleo.templatetags.moeda import intcomma_brl

from .models import GrupoOpcaoCardapio, OpcaoCardapio


class PedidoItemForm(forms.Form):
    quantidade = forms.DecimalField(label="Quantidade", min_value=Decimal("0.001"),
                                    max_value=Decimal("999999999.999"), max_digits=12,
                                    decimal_places=3, initial=1)
    observacoes = forms.CharField(label="Observações para a cozinha", required=False, max_length=500,
                                  widget=forms.Textarea(attrs={"rows": 3,
                                      "placeholder": "Ex.: batata sem sal, molho à parte…"}))
    versao = forms.IntegerField(required=False, widget=forms.HiddenInput)
    chave_pedido = forms.UUIDField(initial=uuid4, widget=forms.HiddenInput)

    def __init__(self, *args, produto, item=None, **kwargs):
        initial = kwargs.setdefault("initial", {})
        if item:
            initial.update(quantidade=item.quantidade, observacoes=item.observacoes, versao=item.versao)
        super().__init__(*args, **kwargs)
        if item:
            self.fields.pop("chave_pedido")
        self.grupos = list(produto.grupos_opcoes.filter(ativo=True).prefetch_related("opcoes"))
        selecionadas = {str(opcao["id"]) for opcao in item.opcoes} if item else set()
        for grupo in self.grupos:
            nome = f"grupo_{grupo.pk}"
            escolhas = [(str(op.pk), f"{op.nome}" + (f" (+ {intcomma_brl(op.adicional)})" if op.adicional else ""))
                        for op in grupo.opcoes.all() if op.ativo]
            comuns = {"label": grupo.nome, "required": grupo.minimo > 0,
                      "help_text": ("Escolha 1 opção." if grupo.minimo == grupo.maximo == 1
                                    else f"Escolha de {grupo.minimo} a {grupo.maximo} opções.")}
            if grupo.maximo == 1:
                self.fields[nome] = forms.ChoiceField(
                    choices=escolhas if grupo.minimo else [("", "Sem adicional"), *escolhas],
                    widget=forms.RadioSelect, **comuns)
                self.initial[nome] = next((pk for pk, _ in escolhas if pk in selecionadas), "")
            else:
                self.fields[nome] = forms.MultipleChoiceField(choices=escolhas,
                                                            widget=forms.CheckboxSelectMultiple, **comuns)
                self.initial[nome] = [pk for pk, _ in escolhas if pk in selecionadas]
        self.order_fields(["quantidade", *[f"grupo_{grupo.pk}" for grupo in self.grupos],
                           "observacoes", "versao", "chave_pedido"])

    def clean(self):
        dados = super().clean()
        opcoes = []
        for grupo in self.grupos:
            nome = f"grupo_{grupo.pk}"
            valores = dados.get(nome) or []
            if isinstance(valores, str):
                valores = [valores]
            if not grupo.minimo <= len(valores) <= grupo.maximo and nome not in self.errors:
                self.add_error(nome, f"Escolha entre {grupo.minimo} e {grupo.maximo} opções.")
            opcoes.extend(valores)
        dados["opcoes"] = opcoes
        return dados


class GrupoOpcaoForm(forms.ModelForm):
    class Meta:
        model = GrupoOpcaoCardapio
        fields = ["nome", "minimo", "maximo", "ordem", "ativo"]
        widgets = {"nome": forms.TextInput(attrs={"placeholder": "Ex.: Ponto da carne ou Acompanhamentos"})}


class OpcoesFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        ativas = [form.cleaned_data for form in self.forms
                  if form.cleaned_data.get("nome") and form.cleaned_data.get("ativo")]
        if self.instance.ativo and len(ativas) < self.instance.minimo:
            raise ValidationError("Cadastre opções ativas suficientes para o mínimo de escolhas.")
        nomes = [dados["nome"].strip().casefold() for dados in ativas]
        if len(nomes) != len(set(nomes)):
            raise ValidationError("Use nomes diferentes nas opções deste grupo.")


OpcoesForm = inlineformset_factory(GrupoOpcaoCardapio, OpcaoCardapio, formset=OpcoesFormSet,
    fields=["nome", "adicional", "produto_estoque", "quantidade_estoque", "ordem", "ativo"],
    extra=3, can_delete=False, max_num=50, validate_max=True)
