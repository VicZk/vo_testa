"""Cadastro documental e conferência de parcelas recebidas de uma nota."""

from decimal import Decimal

from django import forms
from django.forms import BaseFormSet, formset_factory

from apps.nucleo.documentos_privados import preparar_documento
from apps.nucleo.forms import rotular_selects_vazios
from apps.nucleo.models import EmbalagemProduto, LocalEstoque, LoteEstoque, Produto

from .forms import fornecedores


class ArquivosInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class DocumentosField(forms.FileField):
    def __init__(self, **kwargs):
        super().__init__(label="Anexos", required=False, widget=ArquivosInput(attrs={
            "accept": ".pdf,.jpg,.jpeg,.png,.xml",
        }), help_text="PDF, foto JPG/PNG ou XML. Até 10 arquivos de 10 MB por nota.", **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        arquivos = data if isinstance(data, (list, tuple)) else [data]
        if len(arquivos) > 10:
            raise forms.ValidationError("Anexe no máximo 10 arquivos por nota.")
        validar = super().clean
        return [preparar_documento(validar(arquivo, initial)) for arquivo in arquivos]


class NotaEntradaForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    fornecedor = forms.ModelChoiceField(label="Fornecedor", queryset=fornecedores())
    tipo = forms.ChoiceField(label="Tipo de documento", choices=(
        ("nfe", "Nota fiscal eletrônica (NF-e)"),
        ("nfce", "Nota fiscal de consumidor (NFC-e)"),
        ("outro", "Outro documento"),
    ), initial="nfe")
    numero = forms.CharField(label="Número da nota", max_length=40)
    serie = forms.CharField(label="Série", max_length=20, required=False)
    emissao = forms.DateField(label="Data de emissão", widget=forms.DateInput(
        attrs={"type": "date"}, format="%Y-%m-%d"))
    chave_acesso = forms.CharField(label="Chave de acesso", max_length=44, required=False,
                                  help_text="Opcional. Informe os 44 números, quando disponíveis.")
    observacao = forms.CharField(label="Observação", max_length=200, required=False,
                                 widget=forms.Textarea(attrs={"rows": 2}))
    documentos = DocumentosField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = fornecedores()


class ItemNotaForm(forms.Form):
    produto = forms.ModelChoiceField(label="Produto", queryset=Produto.objects.none())
    quantidade = forms.DecimalField(label="Quantidade prevista", max_digits=12,
                                    decimal_places=3, min_value=Decimal("0.001"))
    custo_unidade_compra = forms.DecimalField(label="Custo por unidade (R$)", max_digits=12,
                                             decimal_places=4, min_value=Decimal("0"))
    embalagem = forms.ModelChoiceField(label="Embalagem de compra", queryset=EmbalagemProduto.objects.none(),
                                       required=False, empty_label="Unidade do produto")
    fator_conferido = forms.DecimalField(widget=forms.HiddenInput, max_digits=12, decimal_places=3,
                                         min_value=Decimal("0.001"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, usa_ficha_tecnica=False)
        self.fields["produto"].label_from_instance = lambda produto: f"{produto.nome} ({produto.get_unidade_display()})"
        produto_id = self.data.get(self.add_prefix("produto")) if self.is_bound else self.initial.get("produto")
        try:
            produto_id = int(produto_id)
            if not 0 < produto_id <= 9223372036854775807:
                produto_id = None
        except (TypeError, ValueError, OverflowError):
            produto_id = None
        self.fields["embalagem"].queryset = EmbalagemProduto.objects.filter(
            ativo=True, produto_id=produto_id).select_related("produto")
        for nome in ("quantidade", "custo_unidade_compra"):
            self.fields[nome].widget.attrs["inputmode"] = "decimal"

    def clean(self):
        dados = super().clean()
        embalagem = dados.get("embalagem")
        if embalagem and not dados.get("fator_conferido"):
            self.add_error("embalagem", "Confira novamente a embalagem escolhida.")
        return dados


ItensNotaFormSet = formset_factory(ItemNotaForm, extra=0, min_num=1, validate_min=True,
                                   max_num=100, validate_max=True, absolute_max=100, can_delete=True)


class RecebimentoNotaForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    versao_conferida = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    observacao = forms.CharField(label="Observação da entrega", max_length=200, required=False,
                                 widget=forms.Textarea(attrs={"rows": 2}))


class ParcelaNotaForm(forms.Form):
    item = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    quantidade = forms.DecimalField(label="Receber agora", required=False, max_digits=12,
                                    decimal_places=3, min_value=Decimal("0.001"))
    local = forms.ModelChoiceField(label="Guardar em", queryset=LocalEstoque.objects.none(), required=False)
    lote = forms.ModelChoiceField(label="Lote recebido", queryset=LoteEstoque.objects.none(), required=False)

    def __init__(self, *args, itens, **kwargs):
        super().__init__(*args, **kwargs)
        self.itens = {str(item.pk): item for item in itens}
        item_id = self.data.get(self.add_prefix("item")) if self.is_bound else self.initial.get("item")
        self.item_nota = self.itens.get(str(item_id))
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)
        self.fields["quantidade"].widget.attrs["inputmode"] = "decimal"
        if self.item_nota:
            self.fields["lote"].queryset = LoteEstoque.objects.filter(
                produto_id=self.item_nota.produto_id).order_by("validade", "codigo")

    def clean_item(self):
        item = self.itens.get(str(self.cleaned_data["item"]))
        if item is None:
            raise forms.ValidationError("Este item não pertence à nota conferida.")
        return item

    def clean(self):
        dados = super().clean()
        item, quantidade = dados.get("item"), dados.get("quantidade")
        if quantidade is not None:
            if not dados.get("local"):
                self.add_error("local", "Escolha o local onde esta parcela será guardada.")
            if item and item.produto.controla_validade and not dados.get("lote"):
                self.add_error("lote", "Escolha o lote desta parcela e confira a validade.")
        return dados


class BaseParcelasNotaFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not any(form.cleaned_data.get("quantidade") is not None for form in self.forms):
            raise forms.ValidationError("Informe a quantidade recebida de pelo menos um item.")


ParcelasNotaFormSet = formset_factory(ParcelaNotaForm, formset=BaseParcelasNotaFormSet,
                                     extra=0, max_num=100, validate_max=True, absolute_max=100)


class AnexosNotaForm(forms.Form):
    documentos = DocumentosField()

    def clean_documentos(self):
        documentos = self.cleaned_data["documentos"]
        if not documentos:
            raise forms.ValidationError("Escolha pelo menos um arquivo para anexar.")
        return documentos


rotular_selects_vazios(globals())
