"""E-mail simulado sem rede, SMTP e Amazon SES com confirmação de aceitação."""
from __future__ import annotations

import uuid
from email.utils import parseaddr
from smtplib import SMTPException

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection


def mensagem(*, para, assunto, html, texto, remetente, reply_to=None, headers=None):
    msg = EmailMultiAlternatives(subject=assunto, body=texto or "", from_email=remetente,
        to=[para], reply_to=[reply_to] if reply_to else None, headers=headers or {})
    if html:
        msg.attach_alternative(html, "text/html")
    return msg


class GatewaySimulado:
    nome = "simulado"

    def enviar(self, **dados):
        if not (settings.DEBUG or settings.TESTING):
            raise ValidationError("O envio externo de e-mail ainda não está configurado nesta instalação.")
        # Nunca usa a conexão SMTP global, mesmo que existam credenciais no ambiente.
        msg = mensagem(**dados)
        msg.connection = get_connection("django.core.mail.backends.locmem.EmailBackend")
        msg.send(fail_silently=False)
        return {"ok": True, "message_id": f"SIM-{uuid.uuid4().hex[:16].upper()}", "status": "simulado"}


class GatewaySmtp:
    nome = "smtp"

    def enviar(self, **dados):
        if not getattr(settings, "EMAIL_HOST", ""):
            raise ValidationError("Configure o servidor SMTP antes de enviar e-mails.")
        usuario = settings.EMAIL_COMERCIAL_HOST_USER or settings.EMAIL_HOST_USER
        senha = settings.EMAIL_COMERCIAL_HOST_PASSWORD if settings.EMAIL_COMERCIAL_HOST_USER else settings.EMAIL_HOST_PASSWORD
        if usuario and not senha:
            raise ValidationError("Configure a senha de aplicativo do remetente SMTP.")
        if not settings.EMAIL_COMERCIAL_HOST_USER:
            dados["remetente"] = settings.DEFAULT_FROM_EMAIL
        msg = mensagem(**dados)
        msg.connection = get_connection("django.core.mail.backends.smtp.EmailBackend",
            username=usuario, password=senha, timeout=settings.EMAIL_TIMEOUT)
        try:
            aceitos = msg.send(fail_silently=False)
        except (SMTPException, OSError):
            raise ValidationError("O servidor SMTP não confirmou o envio. Confira a conexão e o remetente configurados.")
        if aceitos != 1:
            raise ValidationError("O servidor SMTP não aceitou a mensagem.")
        return {"ok": True, "message_id": f"SMTP-{uuid.uuid4().hex}", "status": "enviado"}


class GatewaySes:
    nome = "ses"

    def enviar(self, **dados):
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
        if not all((settings.EMAIL_SES_REGION, settings.EMAIL_SES_ACCESS_KEY_ID, settings.EMAIL_SES_SECRET_ACCESS_KEY)):
            raise ValidationError("Configure região e credenciais do Amazon SES, com remetente verificado.")
        msg = mensagem(**dados)
        try:
            cliente = boto3.client("ses", region_name=settings.EMAIL_SES_REGION,
                aws_access_key_id=settings.EMAIL_SES_ACCESS_KEY_ID,
                aws_secret_access_key=settings.EMAIL_SES_SECRET_ACCESS_KEY,
                config=Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 0}))
            resultado = cliente.send_raw_email(Source=parseaddr(msg.from_email)[1], Destinations=msg.to,
                RawMessage={"Data": msg.message().as_bytes()})
        except (BotoCoreError, ClientError):
            raise ValidationError("O Amazon SES não confirmou a aceitação. Confira a identidade do remetente e a situação da conta no provedor.")
        identificador = resultado.get("MessageId") if isinstance(resultado, dict) else None
        if not isinstance(identificador, str) or not identificador:
            raise ValidationError("O Amazon SES não informou o identificador da mensagem.")
        return {"ok": True, "message_id": identificador, "status": "enviado"}


_GATEWAYS = {"simulado": GatewaySimulado, "smtp": GatewaySmtp, "ses": GatewaySes}


def get_email_gateway():
    nome = settings.EMAIL_GATEWAY
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError("Provedor de e-mail desconhecido. Configure simulado, smtp ou ses.")
    return cls()
