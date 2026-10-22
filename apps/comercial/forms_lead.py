"""Cadastro manual de interessado, com validação antes de criar o contato."""
import uuid
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.nucleo.forms import DataInput, PessoaForm
from apps.nucleo.models import Pessoa
from apps.nucleo.modulos import Modulo

from .models import Campanha, EtapaFunil, MotivoPerda, Oportunidade


class ValorEstimadoField(forms.DecimalField):
    def to_python(self, value):
        if value in self.empty_values:
            return Decimal("0.00")
        value = str(value).strip()
        if "," in value:
            value = value.replace(".", "").replace(",", ".")
        return super().to_python(value)


class ContatoLeadForm(PessoaForm):
    class Meta(PessoaForm.Meta):
        fields = ("nome", "telefone", "email")
        labels = {"nome": "Nome do contato", "telefone": "Telefone / WhatsApp", "email": "E-mail"}


class NovoLeadForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4,
                            error_messages={"required": "Reabra o cadastro para iniciar um novo atendimento."})
    tipo_contato = forms.ChoiceField(
        label="Quem está interessado?", choices=(("novo", "Novo contato"), ("cadastrado", "Já cadastrado")),
        initial="novo", widget=forms.RadioSelect,
    )
    pessoa = forms.ModelChoiceField(queryset=Pessoa.objects.none(), required=False,
                                   label="Buscar contato cadastrado")
    origem = forms.ChoiceField(label="Como chegou até nós?", choices=Oportunidade.Origem.choices,
                              initial=Oportunidade.Origem.WHATSAPP)
    campanha = forms.ModelChoiceField(queryset=Campanha.objects.none(), required=False,
                                     label="Campanha de origem", empty_label="Sem campanha identificada")
    tipo_interesse = forms.ChoiceField(label="Interesse", choices=Oportunidade.TipoInteresse.choices,
                                      initial=Oportunidade.TipoInteresse.HOSPEDAGEM)
    observacao = forms.CharField(label="O que a pessoa procura?", required=False,
                                widget=forms.Textarea(attrs={"rows": 2,
                                    "placeholder": "Ex.: fim de semana para um casal, em novembro"}))
    titulo = forms.CharField(label="Nome deste atendimento", required=False, max_length=120,
                            help_text="Opcional. Se ficar vazio, usamos o nome do contato.")
    checkin_previsto = forms.DateField(label="Chegada prevista", required=False, widget=DataInput())
    checkout_previsto = forms.DateField(label="Saída prevista", required=False, widget=DataInput())
    quartos = forms.IntegerField(label="Quartos previstos", min_value=1, max_value=32767, initial=1)
    hospedes = forms.IntegerField(label="Pessoas previstas", min_value=1, max_value=32767, initial=2,
                                 help_text="A composição de adultos e crianças pode ser detalhada no atendimento.")
    valor_estimado = ValorEstimadoField(
        label="Valor estimado (R$)", required=False, min_value=Decimal("0"),
        max_digits=10, decimal_places=2, localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00"}),
    )
    faturamento = forms.ChoiceField(label="Quem vai pagar?", initial="particular",
                                   choices=(("particular", "O próprio cliente"),
                                            ("agencia", "Uma agência"), ("empresa", "Uma empresa")))
    etapa = forms.ModelChoiceField(queryset=EtapaFunil.objects.none(), required=False,
                                  label="Etapa inicial", empty_label="Começar pela primeira etapa")
    responsavel = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False,
                                        label="Quem vai atender?", empty_label="Eu vou atender")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pessoa"].queryset = Pessoa.objects.filter(ativo=True)
        self.fields["campanha"].queryset = Campanha.objects.filter(ativa=True).order_by("nome")
        self.fields["etapa"].queryset = EtapaFunil.objects.filter(ativa=True, tipo=EtapaFunil.Tipo.ABERTA)
        self.fields["responsavel"].queryset = get_user_model().objects.filter(
            Q(is_superuser=True) | Q(modulos__codigo=Modulo.COMERCIAL, modulos__ativo=True),
            is_active=True,
        ).distinct().order_by("first_name", "username")

    def clean(self):
        data = super().clean()
        if data.get("tipo_contato") == "cadastrado" and not data.get("pessoa"):
            self.add_error("pessoa", "Busque e escolha o contato na lista.")
        if data.get("tipo_contato") == "novo":
            data["pessoa"] = None
        inicio, fim = data.get("checkin_previsto"), data.get("checkout_previsto")
        if inicio and fim:
            day_use = data.get("tipo_interesse") == Oportunidade.TipoInteresse.DAY_USE
            if fim < inicio or (fim == inicio and not day_use):
                self.add_error("checkout_previsto", "A saída precisa ser depois da chegada (no mesmo dia apenas para Dia na Pousada).")
        return data


class MoverLeadForm(forms.Form):
    etapa = forms.ModelChoiceField(queryset=EtapaFunil.objects.none(), label="Próxima etapa", empty_label=None)
    motivo = forms.ModelChoiceField(queryset=MotivoPerda.objects.filter(ativo=True),
                                   label="Motivo da perda", required=False)
    detalhe = forms.CharField(label="O que aconteceu?", required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["etapa"].queryset = EtapaFunil.objects.filter(ativa=True).exclude(tipo=EtapaFunil.Tipo.GANHO)

    def clean(self):
        data = super().clean()
        etapa = data.get("etapa")
        if etapa and etapa.tipo == EtapaFunil.Tipo.PERDIDO and not data.get("motivo"):
            self.add_error("motivo", "Escolha o motivo para registrar a perda.")
        return data
