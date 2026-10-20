"""Webhook público do WhatsApp Cloud API (Meta) — fora do /crm, sem login.

- GET: handshake de verificação (hub.challenge) usando WHATSAPP_VERIFY_TOKEN.
- POST: eventos (mensagens recebidas + status de entrega). O corpo é gravado num
  WebhookWhatsApp ANTES de processar: se o processamento falhar, o registro guarda o erro
  e o `reprocessar_webhooks_whatsapp` (rotinas) tenta de novo — nada se perde e a resposta
  200 é honesta. Se nem a gravação der certo, devolve 500 e a Meta reentrega.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import services

logger = logging.getLogger(__name__)


def _assinatura_valida(request) -> bool:
    """Confere a assinatura X-Hub-Signature-256 (HMAC do corpo com o App Secret).

    S-M6: falha FECHADA. Só dispensa a assinatura no sandbox local (DEBUG) sem secret;
    com o gateway real ligado (ou em produção) o secret é obrigatório — sem ele, recusa.
    """
    segredo = getattr(settings, "WHATSAPP_APP_SECRET", "")
    if not segredo:
        gateway_real = getattr(settings, "WHATSAPP_GATEWAY", "simulado") != "simulado"
        # Dispensa só no sandbox local/testes com gateway simulado; produção = recusa.
        return (settings.DEBUG or getattr(settings, "TESTING", False)) and not gateway_real
    cabecalho = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    if not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(
        segredo.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecalho[len("sha256="):], esperado)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        # Verificação do webhook (Meta chama uma vez ao configurar).
        modo = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        desafio = request.GET.get("hub.challenge", "")
        esperado = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
        if modo == "subscribe" and esperado and hmac.compare_digest(token or "", esperado):
            return HttpResponse(desafio, content_type="text/plain")
        return HttpResponseForbidden("token inválido")

    # POST: eventos
    if not _assinatura_valida(request):
        return HttpResponseForbidden("assinatura inválida")
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        logger.warning("Webhook do WhatsApp com corpo que não é JSON; ignorado.")
        return JsonResponse({"ok": True})
    services.registrar_e_processar_webhook_whatsapp(payload)
    return JsonResponse({"ok": True})
