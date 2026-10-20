"""Reenvia e-mails do Comercial que ficaram pendentes ou deram erro (backstop).

O 1:1, as boas-vindas e os alertas de lead saem numa thread de fundo; se o processo
reinicia no meio (deploy), o EnvioEmail fica "pendente" para sempre. Este comando pega,
entre os dos últimos 2 dias que ainda guardam o conteúdo:
- pendentes há mais de 10 minutos (a thread não terminou);
- com erro, enquanto tiverem menos de 3 tentativas.
E-mails de campanha ficam de fora: a campanha tem contadores próprios de enviados/erros.

Uso: manage.py reenviar_emails_pendentes (roda no grupo "frequentes" do `rotinas`)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.comercial.models import EnvioEmail
from apps.comercial.services import _processar_envio_email

LOTE = 100
MAX_TENTATIVAS = 3


class Command(BaseCommand):
    help = "Reenvia e-mails do Comercial pendentes há mais de 10 min ou com erro."

    def handle(self, *args, **options):
        agora = timezone.now()
        alvos = list(
            EnvioEmail.objects.filter(campanha__isnull=True, criado_em__gte=agora - timedelta(days=2))
            .exclude(corpo_html="", corpo_texto="")
            .filter(
                Q(status=EnvioEmail.Status.PENDENTE, criado_em__lte=agora - timedelta(minutes=10))
                | Q(status=EnvioEmail.Status.ERRO, tentativas__lt=MAX_TENTATIVAS)
            )
            .order_by("criado_em")[:LOTE]
        )
        for envio in alvos:
            _processar_envio_email(
                envio.pk, envio.email, envio.assunto, envio.corpo_html, envio.corpo_texto,
                envio.remetente or None, envio.reply_to or None, envio.autor_id,
                envio.oportunidade_id, envio.cabecalhos or None,
            )
        enviados = EnvioEmail.objects.filter(
            pk__in=[e.pk for e in alvos], status=EnvioEmail.Status.ENVIADO).count()
        self.stdout.write(self.style.SUCCESS(
            f"{enviados}/{len(alvos)} e-mail(s) do Comercial reenviado(s)."))
