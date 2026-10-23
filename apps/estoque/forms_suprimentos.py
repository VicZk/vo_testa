from decimal import Decimal

from django import forms
from django.forms import formset_factory

from apps.nucleo.models import EmbalagemProduto, LocalEstoque, LoteEstoque, Produto

from .campos import DecimalBRField
from .forms import fornecedores


class EmbalagemForm(forms.ModelForm):
    class Meta:
        model = EmbalagemProduto
        fields = ["nome", "fator", "ativo"]
        field_classes = {"fator": DecimalBRField}


class LoteForm(forms.ModelForm):
    class Meta:
        model = LoteEstoque
        fields = ["produto", "codigo", "validade"]
        widgets = {"validade": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, controla_validade=True)


class CompraForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    fator_conferido = DecimalBRField(widget=forms.HiddenInput, max_digits=12, decimal_places=3,
                                         min_value=Decimal("0.001"), required=False)
    embalagem = forms.ModelChoiceField(label="Produto e embalagem", queryset=EmbalagemProduto.objects.none())
    local = forms.ModelChoiceField(label="Local de recebimento", queryset=LocalEstoque.objects.none())
    quantidade = DecimalBRField(label="Quantidade de embalagens", max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    custo_embalagem = DecimalBRField(label="Custo por embalagem (R$)", max_digits=12, decimal_places=4, min_value=0)
    lote = forms.ModelChoiceField(label="Lote recebido", queryset=LoteEstoque.objects.none(), required=False)
    fornecedor = forms.ModelChoiceField(label="Fornecedor", queryset=fornecedores())
    documento = forms.CharField(label="Nota fiscal ou documento da compra", max_length=80)
    observacao = forms.CharField(label="Observação", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["embalagem"].queryset = EmbalagemProduto.objects.filter(ativo=True, produto__ativo=True).select_related("produto")
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)
        self.fields["lote"].queryset = LoteEstoque.objects.select_related("produto")
        self.fields["fornecedor"].queryset = fornecedores()
        self.fields["quantidade"].help_text = "Ex.: 2 caixas com fator 12 entram como 24 unidades no estoque."
        self.fields["custo_embalagem"].help_text = "Inclua os custos de aquisição rateados nesta embalagem. O custo por unidade base será calculado."
        self.fields["lote"].help_text = "Obrigatório quando o produto controla validade. Cadastre o lote antes do recebimento."


class IdentificarForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    lote = forms.ModelChoiceField(label="Lote conferido", queryset=LoteEstoque.objects.none())
    local = forms.ModelChoiceField(label="Local", queryset=LocalEstoque.objects.none())
    quantidade = DecimalBRField(label="Quantidade na unidade base", max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    motivo = forms.CharField(label="Como o lote e a validade foram conferidos", max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lote"].queryset = LoteEstoque.objects.select_related("produto")
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)


class ContagemLoteForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    marca = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    quantidade = DecimalBRField(label="Quantidade contada deste lote", max_digits=12, decimal_places=3, min_value=0)
    motivo = forms.CharField(label="Motivo da contagem ou correção", max_length=200)


class CorrecaoLoteForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput)
    destino = forms.ModelChoiceField(label="Lote com a identificação correta", queryset=LoteEstoque.objects.none())
    local = forms.ModelChoiceField(label="Local", queryset=LocalEstoque.objects.none())
    quantidade = DecimalBRField(label="Quantidade a reidentificar", max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    motivo = forms.CharField(label="Motivo e evidência da conferência", max_length=200)

    def __init__(self, *args, lote, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destino"].queryset = LoteEstoque.objects.filter(produto=lote.produto).exclude(pk=lote.pk)
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)


class IngredienteForm(forms.Form):
    ingrediente = forms.ModelChoiceField(label="Ingrediente", queryset=Produto.objects.none())
    quantidade = DecimalBRField(label="Consumo na unidade base", max_digits=12, decimal_places=3, min_value=Decimal("0.001"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ingrediente"].queryset = Produto.objects.filter(ativo=True, usa_ficha_tecnica=False)
        self.fields["ingrediente"].label_from_instance = lambda produto: f"{produto.nome} ({produto.unidade})"


IngredientesFormSet = formset_factory(IngredienteForm, extra=3, can_delete=True, max_num=100, validate_max=True)


from apps.nucleo.forms import rotular_selects_vazios  # noqa: E402

rotular_selects_vazios(globals())
