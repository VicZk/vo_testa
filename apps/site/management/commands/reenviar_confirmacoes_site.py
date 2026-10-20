"""Manda a confirmação das reservas do site que ficaram sem e-mail (backstop).

A confirmação sai numa thread de fundo logo depois da reserva; se o processo cair antes
(deploy, reinício) ou o SMTP falhar, a reserva fica sem `confirmacao_enviada_em`. Este
comando pega as de 10 min a 2 dias atrás, ainda ativas, e tenta de novo.

Uso: manage.py reenviar_confirmacoes_site (roda no grupo "frequentes" do `rotinas`)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.site.emails import registrar_confirmacao
from apps.site.models import Reserva

LOTE = 100


class Command(BaseCommand):
    help = "Reenvia a confirmação das reservas do site que ficaram sem e-mail."

    def handle(self, *args, **options):
        agora = timezone.now()
        pendentes = (
            Reserva.objects.filter(
                confirmacao_enviada_em__isnull=True,
                status__in=["aguardando", "confirmada"],
                criado_em__lte=agora - timedelta(minutes=10),
                criado_em__gte=agora - timedelta(days=2),
            )
            .exclude(hospede__email="")
            .select_related("hospede", "quarto")
            .order_by("criado_em")[:LOTE]
        )
        alvos = list(pendentes)
        enviados = sum(1 for reserva in alvos if registrar_confirmacao(reserva))
        self.stdout.write(self.style.SUCCESS(
            f"{enviados}/{len(alvos)} confirmação(ões) do site enviada(s)."))
