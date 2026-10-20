"""E-mails transacionais do site (confirmação de reserva)."""
import functools
import logging
import threading
from email.mime.image import MIMEImage
from pathlib import Path
from urllib.parse import quote_plus

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats, timezone

from apps.site.models import ConfiguracaoSite, Reserva

logger = logging.getLogger(__name__)

_EMAIL_IMG = Path(__file__).resolve().parent / "static" / "site" / "img" / "email"

# Horários padrão da pousada (exibidos no e-mail).
def _horarios():
    """Horários de entrada e saída da pousada (Tabela de Preços, no CRM)."""
    from apps.nucleo.models import ConfiguracaoReservas
    cfg = ConfiguracaoReservas.carregar()
    return cfg.hora_checkin.strftime("%H:%M"), cfg.hora_checkout.strftime("%H:%M")

# Razão social / CNPJ (rodapé legal do e-mail).
RAZAO_SOCIAL = "POUSADA VO TESTA LTDA"
CNPJ = "26.003.246/0001-00"


def url_recibo_reserva(reserva) -> str:
    """Link público da reserva (token opaco — não usa o código previsível)."""
    path = reverse("core:reserva_confirmada", args=[reserva.token])
    base = getattr(settings, "SITE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}{path}"


def _fmt_data_hora(data, hora: str) -> str:
    """Ex.: Qui., 12 de jul. · 14:00"""
    if not data:
        return "—"
    dia = formats.date_format(data, "D, d \\d\\e M.")
    return f"{dia} · {hora}"


def _ctx_confirmacao(reserva):
    config = ConfiguracaoSite.load()
    link = url_recibo_reserva(reserva)
    endereco = (config.endereco or "").strip()
    maps_q = quote_plus(endereco) if endereco else ""
    pago = reserva.status == "confirmada"
    hora_entrada, hora_saida = _horarios()
    return {
        "reserva": reserva,
        "config": config,
        "url_reserva": link,
        "metodo": reserva.get_metodo_pagamento_display(),
        "titulo": "Reserva Confirmada" if pago else "Reserva Registrada",
        "pago": pago,
        "chegada": _fmt_data_hora(reserva.data_checkin, hora_entrada),
        "partida": _fmt_data_hora(reserva.data_checkout, hora_saida),
        "endereco": endereco,
        "url_google_maps": (
            f"https://www.google.com/maps/search/?api=1&query={maps_q}" if maps_q else ""
        ),
        "url_apple_maps": f"https://maps.apple.com/?q={maps_q}" if maps_q else "",
        "url_whatsapp": (
            f"https://wa.me/{config.whatsapp}"
            f"?text={quote_plus(f'Olá! Sobre a reserva {reserva.codigo}')}"
            if config.whatsapp
            else ""
        ),
        "email_contato": config.email or "reservas@pousadavotesta.com.br",
        "instagram_url": config.instagram_url or "",
        "facebook_url": config.facebook_url or "",
        "razao_social": RAZAO_SOCIAL,
        "cnpj": CNPJ,
        "cid_hero": "email-hero",
        "cid_roda": "email-roda",
    }


@functools.lru_cache(maxsize=None)
def _bytes_da_imagem(path: Path) -> bytes | None:
    """Lê cada imagem do e-mail uma vez por processo (eram ~80 KB lidos a cada envio)."""
    return path.read_bytes() if path.is_file() else None


def _anexar_imagens(msg: EmailMultiAlternatives) -> None:
    """Anexa imagens inline (CID). Hero da prancheta já inclui o brasão."""
    arquivos = [
        ("email-hero", _EMAIL_IMG / "hero.jpg", "jpeg"),
        ("email-roda", _EMAIL_IMG / "roda.png", "png"),
    ]
    for cid, path, subtype in arquivos:
        conteudo = _bytes_da_imagem(path)
        if conteudo is None:
            continue
        img = MIMEImage(conteudo, _subtype=subtype)
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=path.name)
        msg.attach(img)


def enviar_confirmacao(reserva, *, fail_silently=True) -> bool:
    """Envia a confirmação da reserva ao hóspede. Por padrão não quebra o fluxo
    de reserva (fail_silently): se o e-mail falhar, a reserva já está registrada."""
    email = getattr(reserva.hospede, "email", "")
    if not email:
        return False
    ctx = _ctx_confirmacao(reserva)
    assunto = f"{ctx['titulo']} {reserva.codigo} — Pousada Vô Testa"
    msg = EmailMultiAlternatives(
        assunto,
        render_to_string("site/emails/confirmacao.txt", ctx),
        settings.DEFAULT_FROM_EMAIL,
        [email],
        reply_to=[ctx["email_contato"]],
    )
    msg.attach_alternative(
        render_to_string("site/emails/confirmacao.html", ctx), "text/html"
    )
    _anexar_imagens(msg)
    msg.send(fail_silently=fail_silently)
    return True


def registrar_confirmacao(reserva) -> bool:
    """Manda a confirmação e marca `confirmacao_enviada_em`. Nunca levanta: se falhar,
    a reserva fica sem a marca e o `reenviar_confirmacoes_site` tenta de novo."""
    try:
        if not enviar_confirmacao(reserva, fail_silently=False):
            return False
    except Exception:
        logger.exception(
            "Confirmação da reserva %s não saiu; o rotinas tenta de novo.", reserva.codigo)
        return False
    Reserva.objects.filter(pk=reserva.pk).update(confirmacao_enviada_em=timezone.now())
    return True


def _confirmacao_em_thread(reserva_id):
    from django.db import connections

    try:
        reserva = Reserva.objects.select_related("hospede").filter(pk=reserva_id).first()
        if reserva is not None:
            registrar_confirmacao(reserva)
    finally:
        connections.close_all()  # só as conexões desta thread


def disparar_confirmacao(reserva) -> None:
    """Confirmação ao hóspede depois que a reserva foi gravada.

    Em produção sai numa thread de fundo, para o SMTP (handshake TLS de até
    EMAIL_TIMEOUT s) não segurar a resposta do último passo da reserva. Se o processo
    cair antes do envio, a reserva fica sem `confirmacao_enviada_em` e o
    `reenviar_confirmacoes_site` (rotinas, a cada 10 min) manda depois. Nos testes, ou
    com EMAIL_ENVIO_ASSINCRONO=0, envia na hora."""
    if getattr(settings, "EMAIL_ENVIO_ASSINCRONO", True) and not getattr(settings, "TESTING", False):
        threading.Thread(target=_confirmacao_em_thread, args=(reserva.pk,), daemon=True).start()
    else:
        registrar_confirmacao(reserva)
