"""Acesso às áreas comuns por pessoa e turno, independente das unidades de hospedagem."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, Sum


class DiaDayPass(models.Model):
    data = models.DateField(primary_key=True)


class TurnoDayPass(models.Model):
    dia = models.ForeignKey(DiaDayPass, on_delete=models.PROTECT, related_name="turnos")
    nome = models.CharField("nome do turno", max_length=60)
    inicio = models.TimeField("início")
    fim = models.TimeField("fim")
    capacidade = models.PositiveIntegerField("lotação máxima", validators=[MinValueValidator(1), MaxValueValidator(10000)])
    contar_hospedes = models.BooleanField("hóspedes entram no limite de lotação")
    preco_adulto = models.DecimalField("ingresso de adulto (R$)", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    preco_crianca = models.DecimalField("ingresso de criança (R$)", max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    preco_hospede = models.DecimalField("ingresso por hóspede (R$)", max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)], help_text="Informe zero se incluso na hospedagem. Vazio impede cadastrar hóspedes neste turno.")
    ativo = models.BooleanField("aceitar novas reservas", default=False)

    class Meta:
        ordering = ["dia_id", "inicio", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(fim__gt=models.F("inicio")), name="daypass_horario_valido"),
            models.CheckConstraint(condition=Q(capacidade__gte=1, capacidade__lte=10000), name="daypass_lotacao_valida"),
        ]

    def __str__(self):
        return f"{self.dia_id:%d/%m/%Y} · {self.nome}"


class VisitaDayPass(models.Model):
    class Status(models.TextChoices):
        RESERVADA = "reservada", "Reservada"
        EM_VISITA = "em_visita", "Em visita"
        ENCERRADA = "encerrada", "Encerrada"
        CANCELADA = "cancelada", "Cancelada"

    turno = models.ForeignKey(TurnoDayPass, on_delete=models.PROTECT, related_name="visitas")
    responsavel = models.ForeignKey("nucleo.Pessoa", on_delete=models.PROTECT, related_name="visitas_daypass")
    hospedagem = models.ForeignKey("reservas.Reserva", on_delete=models.PROTECT, null=True, blank=True, related_name="visitas_daypass")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RESERVADA)
    vagas = models.PositiveIntegerField(editable=False)
    valor_ingressos = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    chave = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    motivo_cancelamento = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        constraints = [models.UniqueConstraint(fields=["turno", "hospedagem"], condition=Q(hospedagem__isnull=False) & ~Q(status="cancelada"), name="daypass_hospedagem_unica")]

    def __str__(self):
        return f"Day pass #{self.pk} · {self.responsavel}"

    def total_pago(self):
        from apps.nucleo.models import MovimentoCaixa
        recebido = self.pagamentos.aggregate(total=Sum("movimento__valor"))["total"] or Decimal("0")
        estornos = MovimentoCaixa.objects.filter(movimento_origem__in=self.pagamentos.values("movimento_id")).aggregate(total=Sum("valor"))["total"] or Decimal("0")
        return recebido - estornos

    def saldo(self):
        return self.valor_ingressos - self.total_pago()


class VisitanteDayPass(models.Model):
    visita = models.ForeignKey(VisitaDayPass, on_delete=models.PROTECT, related_name="visitantes")
    nome = models.CharField(max_length=120)
    crianca = models.BooleanField(default=False)
    entrou_em = models.DateTimeField(null=True, blank=True)
    saiu_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]


class PagamentoDayPass(models.Model):
    visita = models.ForeignKey(VisitaDayPass, on_delete=models.PROTECT, related_name="pagamentos")
    movimento = models.OneToOneField("nucleo.MovimentoCaixa", on_delete=models.PROTECT, related_name="pagamento_daypass")
    chave = models.UUIDField(unique=True, editable=False)
