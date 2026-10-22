"""Manda o Kit de contingência por e-mail — a folha do dia no celular de quem decide.

Se a internet da pousada cai, o CRM (que é todo em nuvem) fica fora do ar: a folha
impressa resolve na recepção, e esta cópia resolve para quem está fora dela — o
gerente abre o e-mail pelo 4G do celular e tem o mesmo retrato.

Destinos: `KIT_CONTINGENCIA_EMAILS` (variável de ambiente, vírgula). Vazia = não
envia nada, de propósito: ninguém recebe e-mail sem alguém ter pedido.

Uso: manage.py enviar_kit_contingencia [--para a@x.com,b@y.com]
Roda no grupo "diarias" do `rotinas` (03:15 de Brasília).
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.urls import reverse

from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.reservas import services


def destinatarios(extra: str = "") -> list:
    """Lista de e-mails configurada (o `--para` vence o settings, para teste manual)."""
    bruto = extra or ",".join(getattr(settings, "KIT_CONTINGENCIA_EMAILS", []) or [])
    return [e.strip() for e in bruto.split(",") if e.strip()]


class Command(BaseCommand):
    help = "Envia por e-mail a folha do Kit de contingência (KIT_CONTINGENCIA_EMAILS)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--para", default="",
            help="E-mails separados por vírgula; ignora KIT_CONTINGENCIA_EMAILS.")

    def handle(self, *args, **options):
        destinos = destinatarios(options["para"])
        if not destinos:
            self.stdout.write("KIT_CONTINGENCIA_EMAILS vazio — nada a enviar.")
            return
        if not modulo_ativo(Modulo.RESERVAS):
            self.stdout.write("Módulo Reservas inativo — nada a enviar.")
            return

        kit = services.kit_contingencia()
        base = getattr(settings, "SITE_PUBLIC_URL", "").rstrip("/")
        contexto = {
            "kit": kit,
            "gerado_por": "rotina automática",
            "url_kit": f"{base}{reverse('reservas:kit')}" if base else "",
        }
        assunto = (f"Kit de contingência {kit['hoje']:%d/%m/%Y} — "
                   f"{kit['totais']['quartos_ocupados']} quarto(s) ocupado(s), "
                   f"{len(kit['chegadas'])} chegada(s), {len(kit['saidas'])} saída(s)")
        msg = EmailMultiAlternatives(
            assunto,
            render_to_string("reservas/email/kit_contingencia.txt", contexto),
            settings.DEFAULT_FROM_EMAIL,
            destinos,
        )
        msg.attach_alternative(
            render_to_string("reservas/email/kit_contingencia.html", contexto), "text/html"
        )
        if settings.EMAIL_BACKEND in ("django.core.mail.backends.console.EmailBackend", "django.core.mail.backends.dummy.EmailBackend"):
            raise CommandError("O kit não foi enviado: configure o servidor de e-mail externo.")
        if msg.send() != 1:
            raise CommandError("O servidor não confirmou a aceitação do kit de contingência.")
        self.stdout.write(self.style.SUCCESS(
            f"Kit de contingência de {kit['hoje']:%d/%m/%Y} enviado para "
            f"{len(destinos)} endereço(s)."))
