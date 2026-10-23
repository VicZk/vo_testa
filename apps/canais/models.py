"""Configuração, recebimento durável e conferência da distribuição de quartos."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ConfiguracaoCanais(models.Model):
    class Ambiente(models.TextChoices):
        HOMOLOGACAO = "homologacao", "Homologação"
        PRODUCAO = "producao", "Produção"

    ativo = models.BooleanField("conexão habilitada", default=False)
    ambiente = models.CharField(max_length=12, choices=Ambiente.choices, default=Ambiente.HOMOLOGACAO)
    propriedade = models.UUIDField("identificador do estabelecimento", null=True, blank=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="+", verbose_name="responsável pela conferência")
    dias_publicados = models.PositiveSmallIntegerField("dias de disponibilidade", default=500,
        validators=[MinValueValidator(1), MaxValueValidator(500)])
    vendas_abertas = models.BooleanField("permitir vendas nas categorias mapeadas", default=False)
    importar_automaticamente = models.BooleanField("aplicar reservas compatíveis automaticamente", default=False)
    sincronizacao_solicitada = models.BooleanField(default=False, editable=False)
    versao_pendente = models.PositiveBigIntegerField(default=0, editable=False)
    versao_enviada = models.PositiveBigIntegerField(default=0, editable=False)
    falhas_consecutivas = models.PositiveSmallIntegerField(default=0, editable=False)
    proxima_tentativa = models.DateTimeField(null=True, blank=True, editable=False)
    ultima_execucao = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_recebimento = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_envio = models.DateTimeField(null=True, blank=True, editable=False)
    ultima_falha = models.CharField(max_length=500, blank=True, editable=False)
    assinatura_aceita = models.CharField(max_length=64, blank=True, editable=False)
    validacao_hash = models.CharField(max_length=64, blank=True, editable=False)
    validacao = models.CharField(max_length=2000, blank=True)
    validada_em = models.DateTimeField(null=True, blank=True, editable=False)
    validada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    em_processamento_ate = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["ambiente", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["ambiente", "propriedade"], name="canal_conexao_propriedade_unica"),
            models.UniqueConstraint(fields=["ativo"], condition=models.Q(ativo=True), name="canal_uma_conexao_ativa"),
        ]

    def __str__(self):
        return f"Channex · {self.get_ambiente_display()}"

    @classmethod
    def load(cls):
        return cls.objects.filter(ativo=True).first() or cls.objects.order_by("-pk").first() or cls.objects.create()


class MapeamentoCanal(models.Model):
    configuracao = models.ForeignKey(ConfiguracaoCanais, on_delete=models.PROTECT, related_name="mapeamentos")
    nome = models.CharField("nome da categoria", max_length=80)
    tipo_externo = models.UUIDField("identificador do tipo no provedor")
    tarifa_externa = models.UUIDField("identificador do plano de tarifa")
    limite_venda = models.PositiveSmallIntegerField("limite de unidades à venda", default=0,
        validators=[MaxValueValidator(10000)])
    margem_seguranca = models.PositiveSmallIntegerField("unidades reservadas para segurança", default=0,
        validators=[MaxValueValidator(10000)])
    ocupacao_tarifa = models.PositiveSmallIntegerField("adultos incluídos na tarifa enviada", default=2,
        validators=[MinValueValidator(1), MaxValueValidator(50)])
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["configuracao", "tipo_externo"], name="canal_tipo_unico_conexao"),
            models.UniqueConstraint(fields=["configuracao", "tarifa_externa"], name="canal_tarifa_unica_conexao"),
        ]

    def __str__(self):
        return self.nome


class UnidadeMapeada(models.Model):
    # Uma UH só pertence a um estoque externo: impede publicar a mesma vaga duas vezes.
    configuracao = models.ForeignKey(ConfiguracaoCanais, on_delete=models.PROTECT, related_name="unidades")
    uh = models.ForeignKey("nucleo.UH", on_delete=models.PROTECT, related_name="canais_mapeados")
    mapeamento = models.ForeignKey(MapeamentoCanal, on_delete=models.PROTECT, related_name="unidades")


    class Meta:
        constraints = [models.UniqueConstraint(fields=["configuracao", "uh"], name="canal_uh_unica_conexao")]

    def clean(self):
        if self.mapeamento_id and self.configuracao_id != self.mapeamento.configuracao_id:
            raise ValidationError("A unidade e a categoria precisam pertencer à mesma conexão.")


class ReservaCanal(models.Model):
    configuracao = models.ForeignKey(ConfiguracaoCanais, on_delete=models.PROTECT, related_name="reservas")
    ambiente = models.CharField(max_length=12, choices=ConfiguracaoCanais.Ambiente.choices)
    propriedade = models.UUIDField()
    identificador = models.UUIDField()
    canal = models.CharField(max_length=80, blank=True)
    codigo = models.CharField(max_length=100, blank=True)
    revisao_aplicada_em = models.DateTimeField(null=True, blank=True)
    ultima_revisao = models.ForeignKey("RevisaoCanal", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ambiente", "propriedade", "identificador"], name="canal_reserva_externa_unica")]

    def __str__(self):
        return f"{self.canal or 'Canal'} · {self.codigo or self.identificador}"


class RevisaoCanal(models.Model):
    class Estado(models.TextChoices):
        RECEBIDA = "recebida", "Recebida"
        PENDENTE = "pendente", "Conferência necessária"
        APLICADA = "aplicada", "Aplicada no PMS"
        ANTERIOR = "anterior", "Revisão anterior"
        CONFERIDA = "conferida", "Resolvida pela equipe"
        ENSAIO = "ensaio", "Recebida em homologação"

    reserva = models.ForeignKey(ReservaCanal, on_delete=models.PROTECT, related_name="revisoes")
    identificador = models.UUIDField(unique=True)
    alterada_em = models.DateTimeField()
    tipo = models.CharField(max_length=10)
    dados = models.JSONField(default=dict)
    vinculos_aplicados = models.JSONField(default=dict, editable=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.RECEBIDA)
    pendencia = models.CharField(max_length=500, blank=True)
    recebida_em = models.DateTimeField(auto_now_add=True)
    recebimento_confirmado_em = models.DateTimeField(null=True, blank=True)
    resolvida_em = models.DateTimeField(null=True, blank=True)
    resolvida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    resolucao = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-alterada_em", "-pk"]
        constraints = [models.UniqueConstraint(fields=["reserva", "identificador"], name="canal_revisao_unica")]


class QuartoReservaCanal(models.Model):
    externa = models.ForeignKey(ReservaCanal, on_delete=models.PROTECT, related_name="quartos")
    identificador = models.CharField(max_length=100)
    estado_aplicado = models.JSONField(default=dict)
    reserva = models.OneToOneField("reservas.Reserva", on_delete=models.PROTECT, related_name="origem_canal")
    mapeamento = models.ForeignKey(MapeamentoCanal, on_delete=models.PROTECT, related_name="reservas")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["externa", "identificador"], name="canal_quarto_externo_unico")]


class EnvioCanal(models.Model):
    class Estado(models.TextChoices):
        PENDENTE = "pendente", "Envio pendente"
        ACEITO = "aceito", "Aceito pelo provedor"
        FALHOU = "falhou", "Conferência necessária"

    configuracao = models.ForeignKey(ConfiguracaoCanais, on_delete=models.PROTECT, related_name="envios")
    criado_em = models.DateTimeField(auto_now_add=True)
    ambiente = models.CharField(max_length=12, choices=ConfiguracaoCanais.Ambiente.choices)
    propriedade = models.UUIDField()
    assinatura = models.CharField(max_length=64)
    dados = models.JSONField(default=dict)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDENTE)
    tarefas = models.JSONField(default=list)
    conferido_em = models.DateTimeField(null=True, blank=True)
    conferido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    conferencia = models.CharField(max_length=1000, blank=True)
    erro = models.CharField(max_length=500, blank=True)
    aceito_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-pk"]


class AvisoCanal(models.Model):
    """Notificação autenticada: só identidades; o conteúdo é obtido pelo feed."""
    configuracao = models.ForeignKey(ConfiguracaoCanais, on_delete=models.PROTECT, related_name="avisos")
    revisao = models.UUIDField()
    recebido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["configuracao", "revisao"], name="canal_aviso_revisao_unica")]
