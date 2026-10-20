"""Marca como "expirada" os recibos do site aguardando pagamento cujo prazo passou.

Era `expirar_reservas`, mesmo nome do comando de Reservas; o Django resolve nomes iguais
pelo primeiro app do INSTALLED_APPS, então este nunca rodava. A pré-reserva do CRM é
expirada pelo `expirar_reservas` (Reservas); este só acerta o recibo do canal site.

Uso: manage.py expirar_recibos_site (roda no grupo "frequentes" do `rotinas`)
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.site.models import Reserva


class Command(BaseCommand):
    help = 'Marca como "expirada" os recibos do site aguardando pagamento cujo prazo já passou.'

    def handle(self, *args, **options):
        agora = timezone.now()
        vencidas = Reserva.objects.filter(
            status='aguardando',
            expira_em__isnull=False,
            expira_em__lt=agora,
        )
        total = vencidas.update(status='expirada')
        self.stdout.write(self.style.SUCCESS(f'{total} recibo(s) do site expirado(s).'))
