"""Documentos de entrada e recebimentos; o saldo continua no motor de estoque."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Sum

from apps.nucleo.validadores import decimal_valido

from .estoque import ZERO, MovimentoEstoque, quantidade_valida


class HistoricoNotaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("O histórico da nota não pode ser alterado.")

    def delete(self):
        raise ValidationError("O histórico da nota não pode ser apagado.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("O histórico da nota não pode ser alterado.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Registre a nota e os recebimentos pelo serviço de estoque.")

    def _avancar_versao(self):
        if self.model is not NotaEntrada:
            raise ValidationError("A versão pertence à nota de entrada.")
        return super().update(versao_recebimento=models.F("versao_recebimento") + 1)


class HistoricoNota(models.Model):
    objects = HistoricoNotaQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("O histórico da nota não pode ser alterado.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O histórico da nota não pode ser apagado.")


class NotaEntrada(HistoricoNota):
    class Tipo(models.TextChoices):
        NFE = "nfe", "NF-e"
        NFCE = "nfce", "NFC-e"
        OUTRO = "outro", "Outro documento"

    fornecedor = models.ForeignKey("nucleo.Pessoa", on_delete=models.PROTECT, related_name="notas_entrada")
    fornecedor_nome = models.CharField(max_length=150, editable=False)
    # Este nome já é mascarado pela auditoria geral. Não copiar CPF/CNPJ para JSONs da trilha.
    documento_numero = models.CharField("identidade do fornecedor", max_length=40, editable=False)
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    numero = models.CharField("número", max_length=40)
    serie = models.CharField("série", max_length=20, blank=True)
    emissao = models.DateField("emissão")
    chave_acesso = models.CharField("chave de acesso", max_length=44, blank=True,
        validators=[RegexValidator(r"^[0-9]{44}$", "A chave de acesso deve ter 44 dígitos.")])
    observacao = models.CharField("observação", max_length=200, blank=True)
    chave = models.UUIDField(unique=True, editable=False)
    assinatura = models.CharField(max_length=64, editable=False)
    versao_recebimento = models.PositiveIntegerField(default=0, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="notas_entrada_criadas")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["documento_numero", "tipo", "numero", "serie"],
                                    name="nota_entrada_emitente_numero_unico"),
            models.UniqueConstraint(fields=["fornecedor", "tipo", "numero", "serie"],
                                    name="nota_entrada_fornecedor_numero_unico"),
            models.UniqueConstraint(fields=["chave_acesso"], condition=~models.Q(chave_acesso=""),
                                    name="nota_entrada_chave_acesso_unica"),
        ]

    def __str__(self):
        return self.referencia

    @property
    def referencia(self):
        serie = f" série {self.serie}" if self.serie else ""
        return f"{self.get_tipo_display()} {self.numero}{serie}"[:80]

    @property
    def identidade_fornecedor(self):
        return self.documento_numero

    @property
    def fornecedor_documento(self):
        return "" if self.documento_numero.startswith("pessoa:") else self.documento_numero

    @property
    def status(self):
        recebeu = getattr(self, "_tem_recebimentos", None)
        if recebeu is None:
            recebeu = self.recebimentos.exists()
        if not recebeu:
            return "pendente"
        pendente = getattr(self, "_tem_pendencias", None)
        if pendente is None:
            from apps.nucleo.notas_entrada import itens_da_nota
            pendente = itens_da_nota(self).filter(quantidade__gt=models.F("_quantidade_recebida")).exists()
        return "parcial" if pendente else "concluida"

    @property
    def status_label(self):
        return {"pendente": "Pendente", "parcial": "Parcial", "concluida": "Concluída"}[self.status]

    @property
    def valor_total(self):
        valor = getattr(self, "_valor_total", None)
        return valor if valor is not None else sum((i.valor_total for i in self.itens.all()), ZERO)

    @property
    def total_itens(self):
        total = getattr(self, "_total_itens", None)
        return total if total is not None else self.itens.count()


class ItemNotaEntrada(HistoricoNota):
    nota = models.ForeignKey(NotaEntrada, on_delete=models.PROTECT, related_name="itens")
    sequencia = models.PositiveSmallIntegerField()
    produto = models.ForeignKey("nucleo.Produto", on_delete=models.PROTECT, related_name="itens_notas_entrada")
    produto_nome = models.CharField(max_length=120, editable=False)
    embalagem = models.ForeignKey("nucleo.EmbalagemProduto", on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="itens_notas_entrada")
    embalagem_nome = models.CharField(max_length=80, blank=True, editable=False)
    unidade_base = models.CharField(max_length=4, editable=False)
    fator = models.DecimalField(max_digits=12, decimal_places=3, editable=False)
    quantidade = models.DecimalField("quantidade prevista", max_digits=12, decimal_places=3)
    custo_unidade_compra = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        ordering = ["sequencia", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["nota", "sequencia"], name="item_nota_entrada_sequencia_unica"),
            models.CheckConstraint(condition=models.Q(quantidade__gt=0), name="item_nota_entrada_quantidade_positiva"),
            models.CheckConstraint(condition=models.Q(fator__gt=0), name="item_nota_entrada_fator_positivo"),
            models.CheckConstraint(condition=models.Q(custo_unidade_compra__gte=0), name="item_nota_entrada_custo_positivo"),
        ]

    def __str__(self):
        return f"{self.sequencia}. {self.produto_nome}"

    def clean(self):
        self.quantidade = quantidade_valida(self.quantidade)
        self.fator = quantidade_valida(self.fator)
        quantidade_valida(self.quantidade * self.fator)
        self.custo_unidade_compra = decimal_valido(self.custo_unidade_compra, nome="Custo por unidade de compra",
                                                  maximo=Decimal("99999999.9999"), casas=4)
        decimal_valido((self.custo_unidade_compra / self.fator).quantize(Decimal("0.0001")),
                       nome="Custo na unidade base", maximo=Decimal("99999999.9999"), casas=4)
        if self.embalagem_id and self.embalagem.produto_id != self.produto_id:
            raise ValidationError("A embalagem deve pertencer ao produto do item.")

    @property
    def quantidade_base(self):
        return self.quantidade * self.fator

    @property
    def valor_total(self):
        return self.quantidade * self.custo_unidade_compra

    @property
    def quantidade_recebida(self):
        valor = getattr(self, "_quantidade_recebida", None)
        return valor if valor is not None else self.recebimentos.aggregate(total=Sum("quantidade"))["total"] or ZERO

    @property
    def quantidade_pendente(self):
        return self.quantidade - self.quantidade_recebida


class RecebimentoNotaEntrada(HistoricoNota):
    nota = models.ForeignKey(NotaEntrada, on_delete=models.PROTECT, related_name="recebimentos")
    chave = models.UUIDField(unique=True, editable=False)
    assinatura = models.CharField(max_length=64, editable=False)
    versao_conferida = models.PositiveIntegerField(editable=False)
    observacao = models.CharField(max_length=200, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="notas_entrada_recebidas")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-pk"]


class ItemRecebimentoNotaEntrada(HistoricoNota):
    recebimento = models.ForeignKey(RecebimentoNotaEntrada, on_delete=models.PROTECT, related_name="parcelas")
    item = models.ForeignKey(ItemNotaEntrada, on_delete=models.PROTECT, related_name="recebimentos")
    quantidade = models.DecimalField(max_digits=12, decimal_places=3)
    movimento = models.OneToOneField(MovimentoEstoque, on_delete=models.PROTECT, related_name="recebimento_nota")

    class Meta:
        ordering = ["pk"]
        constraints = [models.CheckConstraint(condition=models.Q(quantidade__gt=0),
                                             name="parcela_nota_entrada_quantidade_positiva")]

    def clean(self):
        self.quantidade = quantidade_valida(self.quantidade)
        if self.item_id and self.recebimento_id and self.item.nota_id != self.recebimento.nota_id:
            raise ValidationError("O item não pertence à nota deste recebimento.")
        if self.item_id and self.movimento_id:
            movimento = self.movimento
            if (movimento.produto_id != self.item.produto_id
                    or movimento.tipo != MovimentoEstoque.Tipo.ENTRADA_COMPRA
                    or movimento.quantidade != self.quantidade * self.item.fator
                    or movimento.fornecedor_id != self.item.nota.fornecedor_id):
                raise ValidationError("O movimento não corresponde ao recebimento deste item.")


class AnexoNotaEntrada(HistoricoNota):
    nota = models.ForeignKey(NotaEntrada, on_delete=models.PROTECT, related_name="documentos")
    nome = models.CharField(max_length=180)
    tipo = models.CharField(max_length=40)
    tamanho = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    conteudo = models.BinaryField()
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="documentos_notas_entrada")
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-enviado_em", "-pk"]
        constraints = [models.UniqueConstraint(fields=["nota", "sha256"], name="anexo_nota_entrada_hash_unico")]
