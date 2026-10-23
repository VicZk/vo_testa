from decimal import Decimal

from django import forms
from django.db.models import Q

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    LoteEstoque,
    Pessoa,
    Produto,
)

from .formato import para_campo

# Produto, local e fornecedor são escolhidos por combobox com busca
# (`estoque/partials/combo.html`), não por `<select>`: a lista de produtos
# cresce, e rolar 300 opções para achar "Água 500ml" não é escolher. O campo
# do form continua sendo um ModelChoiceField normal — quem envia o id é o
# `<input type="hidden">` do combo, e a validação do Django segue igual.
CAMPO_COMBO = forms.HiddenInput


class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = [
            "nome", "codigo_barras", "categoria", "icone_catalogo", "unidade", "natureza",
            "preco_venda", "estoque_minimo", "ativo",
            "controla_validade", "usa_ficha_tecnica",
        ]
        # custo_medio é calculado pelo motor — nunca editado à mão.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaProduto.objects.filter(ativo=True)
        self.fields["nome"].widget.attrs["placeholder"] = "Ex.: Água mineral 500 ml"
        self.fields["codigo_barras"].widget.attrs["placeholder"] = "Opcional"
        self.fields["estoque_minimo"].help_text = (
            "Abaixo disso o produto entra nos alertas do painel. Deixe 0 se não houver mínimo."
        )
        # O campo guarda 3 casas (existe meio quilo de café), mas abrir a ficha
        # com "24.000" escrito no campo não ajuda ninguém a editar.
        if self.instance and self.instance.pk:
            self.initial["estoque_minimo"] = para_campo(self.instance.estoque_minimo)


class CategoriaProdutoForm(forms.ModelForm):
    class Meta:
        model = CategoriaProduto
        fields = ["nome", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nome"].widget.attrs["placeholder"] = "Ex.: Bebidas"


class LocalEstoqueForm(forms.ModelForm):
    class Meta:
        model = LocalEstoque
        fields = ["nome", "modulo", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.nucleo.models import centro_choices

        self.fields["modulo"] = forms.ChoiceField(
            label="Vínculo (centro)", choices=centro_choices(),
            help_text="Área responsável pelo depósito. O almoxarifado central pertence ao Núcleo.",
        )
        self.fields["nome"].widget.attrs["placeholder"] = "Ex.: Depósito da Loja"


class _ComChave(forms.Form):
    """Chave de idempotência do envio (o mesmo papel da `Venda.chave` do PDV).

    A tela gera um UUID ao abrir; se o mesmo formulário for enviado duas vezes
    (clique duplo, F5 depois de a conexão cair), o motor devolve o movimento já
    gravado em vez de somar — ou baixar — de novo. O ajuste fica de fora: ele é
    absoluto («o saldo correto é 18»), então o reenvio dá diferença zero.
    """

    chave = forms.UUIDField(widget=forms.HiddenInput, required=False)


class _ProdutoLocalBase(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)
        self.fields["lote"].queryset = LoteEstoque.objects.select_related("produto")
        produto_id = self.data.get("produto") or self.initial.get("produto")
        if produto_id and str(produto_id).isascii() and str(produto_id).isdigit() and len(str(produto_id)) <= 18:
            self.fields["lote"].queryset = self.fields["lote"].queryset.filter(produto_id=produto_id)

    produto = forms.ModelChoiceField(
        label="Produto", queryset=Produto.objects.none(), widget=CAMPO_COMBO
    )
    local = forms.ModelChoiceField(
        label="Local", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    quantidade = forms.DecimalField(
        label="Quantidade", min_value=Decimal("0.001"), max_digits=12, decimal_places=3
    )
    lote = forms.ModelChoiceField(label="Lote", queryset=LoteEstoque.objects.none(), required=False,
                                  help_text="Obrigatório para entrada de perecível. Na saída, deixe vazio para usar primeiro o lote que vence antes.")

    def clean_lote(self):
        lote = self.cleaned_data.get("lote")
        produto = self.cleaned_data.get("produto")
        if lote and produto and lote.produto_id != produto.pk:
            raise forms.ValidationError("Escolha um lote deste produto.")
        return lote


class EntradaForm(_ComChave, _ProdutoLocalBase):
    local = forms.ModelChoiceField(
        label="Entra em qual local", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    custo_unitario = forms.DecimalField(
        label="Custo unitário (R$)", min_value=Decimal("0"), max_digits=12, decimal_places=4,
        help_text="Valor pago por unidade, usado para calcular o custo médio.",
    )
    fornecedor = forms.ModelChoiceField(
        label="Fornecedor", queryset=Pessoa.objects.none(), required=False,
        widget=CAMPO_COMBO, help_text="Fornecedor da mercadoria (opcional).",
    )
    documento = forms.CharField(label="Documento (NF)", max_length=80, required=False)
    observacao = forms.CharField(label="Observação", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fornecedor"].queryset = fornecedores()


class SaidaForm(_ComChave, _ProdutoLocalBase):
    TIPOS = [
        ("saida_venda", "Venda"),
        ("consumo_interno", "Consumo interno"),
        ("perda", "Perda, quebra ou vencimento"),
    ]
    local = forms.ModelChoiceField(
        label="Sai de qual local", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    tipo = forms.ChoiceField(
        label="Motivo da saída", choices=TIPOS, widget=forms.RadioSelect,
        initial="consumo_interno",
    )
    observacao = forms.CharField(label="Observação", max_length=200, required=False)


class TransferenciaForm(_ComChave):
    produto = forms.ModelChoiceField(
        label="Produto", queryset=Produto.objects.none(), widget=CAMPO_COMBO
    )
    origem = forms.ModelChoiceField(
        label="Sai de", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    destino = forms.ModelChoiceField(
        label="Vai para", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    quantidade = forms.DecimalField(
        label="Quantidade", min_value=Decimal("0.001"), max_digits=12, decimal_places=3
    )
    observacao = forms.CharField(label="Observação", max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)
        locais = LocalEstoque.objects.filter(ativo=True)
        self.fields["origem"].queryset = locais
        self.fields["destino"].queryset = locais

    def clean(self):
        dados = super().clean()
        # O motor também barra (e é ele que vale, com a linha travada); aqui o
        # erro chega no campo certo, antes de a pessoa enviar.
        if dados.get("origem") and dados.get("origem") == dados.get("destino"):
            self.add_error("destino", "Escolha um local diferente da origem.")
        return dados


class AjusteForm(_ProdutoLocalBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("lote")

    local = forms.ModelChoiceField(
        label="Local conferido", queryset=LocalEstoque.objects.none(),
        widget=forms.RadioSelect, empty_label=None,
    )
    quantidade = forms.DecimalField(
        label="Saldo correto (contado na prateleira)",
        min_value=Decimal("0"), max_digits=12, decimal_places=3,
    )
    motivo = forms.CharField(
        label="Motivo do ajuste",
        max_length=200,
        help_text="Explique o motivo da diferença. A justificativa fica no histórico de auditoria.",
    )


class AbrirInventarioForm(forms.Form):
    local = forms.ModelChoiceField(label="Local", queryset=LocalEstoque.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["local"].queryset = LocalEstoque.objects.filter(ativo=True)


def fornecedores():
    """Quem pode vender para a pousada: fornecedores e empresas/agências.
    Mesmo recorte da Manutenção (prestador externo)."""
    return Pessoa.objects.filter(ativo=True).filter(
        Q(fornecedor__isnull=False) | Q(agencia__isnull=False)
    )


# Opção vazia dos selects com texto de gente ("Selecione…"), não com o traço
# default do Django. Ver `apps/nucleo/forms.py`.
from apps.nucleo.forms import rotular_selects_vazios  # noqa: E402

rotular_selects_vazios(globals())
