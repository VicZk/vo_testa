from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class RespostaNPS(models.Model):
    class Canal(models.TextChoices):
        PORTAL = "portal", "Portal do hóspede"
        EMAIL = "email", "E-mail"
        WHATSAPP = "whatsapp", "WhatsApp"
        EQUIPE = "equipe", "Recepção"

    reserva = models.OneToOneField("reservas.Reserva", on_delete=models.PROTECT, related_name="resposta_nps")
    hospede = models.ForeignKey("nucleo.Pessoa", on_delete=models.PROTECT, related_name="avaliacoes_nps")
    nota = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    comentario = models.TextField("comentário", max_length=2000, blank=True)
    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.PORTAL)
    criado_em = models.DateTimeField(auto_now_add=True)
    consentimento_versao = models.CharField("versão do consentimento", max_length=20)
    tratativa = models.TextField("acompanhamento", max_length=2000, blank=True)
    tratada_em = models.DateTimeField(null=True, blank=True)
    tratada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(nota__lte=10), name="nps_nota_entre_0_e_10")]

    @property
    def faixa(self):
        return "Promotor" if self.nota >= 9 else "Passivo" if self.nota >= 7 else "Detrator"

    def __str__(self):
        return f"Reserva #{self.reserva_id} · {self.nota}/10"
