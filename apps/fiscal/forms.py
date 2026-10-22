import json
import re

from django import forms
from django.conf import settings

from .models import ConfigFiscalProduto


class ConfigFiscalProdutoForm(forms.ModelForm):
    pis = forms.RegexField(r"^[0-9]{2}$", label="Situação tributária do PIS", max_length=2)
    cofins = forms.RegexField(r"^[0-9]{2}$", label="Situação tributária da COFINS", max_length=2)
    conferido = forms.BooleanField(label="Conferi estes códigos e parâmetros com o responsável fiscal.")

    class Meta:
        model = ConfigFiscalProduto
        fields = ["ncm", "cfop", "cst_csosn", "origem", "tributos"]
        widgets = {"tributos": forms.Textarea(attrs={"rows": 7, "spellcheck": "false"})}
        labels = {"tributos": "Parâmetros tributários complementares (JSON)"}
        help_texts = {"tributos": "Informe apenas os campos tributários adicionais definidos pelo contador para a Focus NFe. Use {} quando não houver complementos."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome in ("ncm", "cfop", "cst_csosn", "origem"):
            self.fields[nome].required = True
            self.fields[nome].widget.attrs["inputmode"] = "numeric"
        tributos = dict(self.instance.tributos) if isinstance(self.instance.tributos, dict) else {}
        self.fields["pis"].initial = tributos.pop("pis_situacao_tributaria", "")
        self.fields["cofins"].initial = tributos.pop("cofins_situacao_tributaria", "")
        self.initial["tributos"] = tributos

    def clean(self):
        dados = super().clean()
        for nome, regra in (("ncm", r"[0-9]{8}"), ("cfop", r"[0-9]{4}"),
                            ("cst_csosn", r"[0-9]{2,3}"), ("origem", r"[0-8]")):
            if nome in dados and not re.fullmatch(regra, dados[nome]):
                self.add_error(nome, "Confira o código com o responsável fiscal.")
        if settings.FISCAL_REGIME == "lucro_presumido" and len(dados.get("cst_csosn", "")) == 3:
            self.add_error("cst_csosn", "O regime configurado exige CST com dois dígitos.")
        tributos = dados.get("tributos")
        if tributos is None:
            tributos = {}
        try:
            valido = isinstance(tributos, dict) and len(json.dumps(tributos, allow_nan=False)) <= 20000
            valido = valido and all(isinstance(k, str) and k.startswith(("icms_", "pis_", "cofins_", "ibs_", "cbs_", "is_")) for k in tributos)
        except (ValueError, TypeError):
            valido = False
        if not valido:
            self.add_error("tributos", "Use um objeto JSON válido, de até 20 mil caracteres, somente com parâmetros tributários.")
        else:
            dados["tributos"] = {**tributos, "pis_situacao_tributaria": dados.get("pis", ""),
                                "cofins_situacao_tributaria": dados.get("cofins", "")}
        return dados
