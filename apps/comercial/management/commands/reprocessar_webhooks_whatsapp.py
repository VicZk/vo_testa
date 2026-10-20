"""Reprocessa webhooks do WhatsApp que falharam e apaga os processados antigos.

O webhook grava o corpo de cada evento da Meta antes de processar. Se o processamento
falhou (ou o processo caiu no meio), o registro fica sem `processado_em`; este comando
tenta de novo, na ordem de chegada, até 5 vezes. Os processados há mais de 30 dias são
apagados (a conversa já está em MensagemWhatsApp).

Uso: manage.py reprocessar_webhooks_whatsapp (grupo "frequentes" do `rotinas`)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comercial.models import WebhookWhatsApp
from apps.comercial.services import processar_registro_webhook

LOTE = 200
MAX_TENTATIVAS = 5
RETENCAO_DIAS = 30


class Command(BaseCommand):
    help = "Reprocessa webhooks do WhatsApp com falha e apaga os processados antigos."

    def handle(self, *args, **options):
        agora = timezone.now()
        # 2 min de folga: não disputa com um webhook que ainda está sendo processado.
        pendentes = list(
            WebhookWhatsApp.objects.filter(
                processado_em__isnull=True,
                tentativas__lt=MAX_TENTATIVAS,
                recebido_em__lte=agora - timedelta(minutes=2),
            ).order_by("recebido_em")[:LOTE]
        )
        ok = sum(1 for registro in pendentes if processar_registro_webhook(registro))
        apagados, _ = WebhookWhatsApp.objects.filter(
            processado_em__lt=agora - timedelta(days=RETENCAO_DIAS)).delete()
        self.stdout.write(self.style.SUCCESS(
            f"{ok}/{len(pendentes)} webhook(s) reprocessado(s); {apagados} antigo(s) apagado(s)."))
