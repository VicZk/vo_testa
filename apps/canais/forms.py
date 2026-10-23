from django import forms
from django.core.exceptions import ValidationError

from apps.nucleo.models import UH, TipoUH, Usuario

from .models import ConfiguracaoCanais, MapeamentoCanal


class ConexaoForm(forms.ModelForm):
    class Meta:
        model = ConfiguracaoCanais
        fields = ["ambiente", "propriedade", "responsavel", "dias_publicados", "ativo", "vendas_abertas", "importar_automaticamente"]
        help_texts = {
            "propriedade": "Identificador fornecido pela Channex para este estabelecimento e ambiente.",
            "ativo": "Habilita o recebimento de reservas e as atualizações agendadas.",
            "vendas_abertas": "Só abre após mapear as categorias e registrar a validação. Pendências de reservas fecham a oferta.",
            "importar_automaticamente": "Reservas compatíveis entram no PMS. Alterações que exigem decisão ficam na fila de conferência.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsavel"].queryset = Usuario.objects.filter(is_active=True).order_by("first_name", "username")


class MapeamentoForm(forms.ModelForm):
    unidades = forms.ModelMultipleChoiceField(label="Unidades físicas desta categoria", queryset=UH.objects.none(),
        help_text="Selecione somente unidades com a mesma tarifa e capacidade para a ocupação publicada.")

    class Meta:
        model = MapeamentoCanal
        fields = ["nome", "tipo_externo", "tarifa_externa", "ocupacao_tarifa", "limite_venda", "margem_seguranca", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unidades"].queryset = UH.objects.filter(status=UH.Status.ATIVA, tipo__modalidade=TipoUH.Modalidade.HOSPEDAGEM).select_related("tipo").order_by("numero")
        if self.instance.pk:
            self.initial["unidades"] = list(self.instance.unidades.values_list("uh_id", flat=True))


class ValidacaoForm(forms.Form):
    evidencia = forms.CharField(label="Resultado da validação com o provedor", min_length=20, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Registre data, responsável e resultados de disponibilidade, preço, restrições, nova reserva, alteração e cancelamento. Não inclua credenciais ou dados de cartão.")


class ConferenciaEnvioForm(forms.Form):
    evidencia = forms.CharField(label="Conferência no canal de venda", min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Confira datas, categorias, quantidades e preços no canal. Anote onde, quando e o que foi verificado.")


class ResolucaoForm(forms.Form):
    reservas = forms.CharField(label="Números das reservas no PMS", max_length=1000, required=False,
        help_text="Uma reserva por quarto recebido, na ordem apresentada. Separe os números por vírgula.")
    motivo = forms.CharField(label="Conferência realizada", min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Descreva os ajustes e a conferência de valores, recebimentos e serviços.")

    def clean_reservas(self):
        texto = self.cleaned_data["reservas"].strip()
        if not texto:
            return []
        partes = [p.strip() for p in texto.split(",")]
        if len(partes) > 50 or any(not p.isascii() or not p.isdigit() or not 0 < int(p) < 2**63 for p in partes):
            raise ValidationError("Informe até 50 números de reserva válidos, separados por vírgula.")
        valores = list(map(int, partes))
        if len(set(valores)) != len(valores):
            raise ValidationError("Cada quarto deve corresponder a uma reserva diferente.")
        return valores
