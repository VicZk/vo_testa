"""Aviso HMAC durável; o worker obtém a revisão pelo feed autenticado."""
import hashlib
import hmac
import json
import time
import uuid

from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.models import modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.sistema import usuario_de_sistema

from .models import AvisoCanal, ConfiguracaoCanais
from .services import segredo_webhook


@csrf_exempt
@require_POST
def receber(request, ambiente):
    if ambiente not in ConfiguracaoCanais.Ambiente.values or not modulo_ativo(Modulo.CANAIS):
        return HttpResponse(status=404)
    segredo = segredo_webhook(ambiente)
    if not segredo:
        return HttpResponse(status=503)
    bruto = request.read(16_385)
    if len(bruto) > 16_384:
        return HttpResponse(status=413)
    instante = request.headers.get("x-hmac-timestamp", "")
    assinaturas = request.headers.get("x-hmac-signature-256", "").split(",")
    if (not instante.isascii() or not instante.isdigit() or len(instante) > 12
            or abs(time.time()-int(instante)) > 300 or not 1 <= len(assinaturas) <= 2):
        return HttpResponse(status=401)
    esperado = hmac.new(segredo.encode(), instante.encode()+b"."+bruto, hashlib.sha256).hexdigest()
    if not any(len(a.strip()) == 64 and a.strip().isascii() and hmac.compare_digest(esperado, a.strip()) for a in assinaturas):
        return HttpResponse(status=401)
    try:
        dados = json.loads(bruto)
        if not isinstance(dados, dict):
            raise ValueError
        if dados.get("event") != "booking":
            return HttpResponse(status=204)
        propriedade = uuid.UUID(dados["property_id"])
        payload = dados["payload"]
        revisao = uuid.UUID(payload["revision_id"])
        if uuid.UUID(payload["property_id"]) != propriedade:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        return HttpResponse(status=400)
    with transaction.atomic():
        cfg = ConfiguracaoCanais.objects.filter(ativo=True, ambiente=ambiente, propriedade=propriedade).first()
        if not cfg:
            return HttpResponse(status=404)
        aviso, criado = AvisoCanal.objects.get_or_create(configuracao=cfg, revisao=revisao)
        if criado:
            ConfiguracaoCanais.objects.filter(pk=cfg.pk).update(versao_pendente=F("versao_pendente")+1)
            registrar_auditoria(usuario_de_sistema("_canais", "Integração de canais"), "aviso_canal_recebido", aviso,
                {"ambiente": ambiente})
    return HttpResponse(status=200)
