"""Content-Security-Policy (Fase 4 — defesa em profundidade de XSS).

Começa em REPORT-ONLY (`CSP_REPORT_ONLY=True`): o navegador NÃO bloqueia nada, só
reporta violações no console — dá pra observar o que a política pegaria antes de impor.
Quando estiver limpo, virar `CSP_REPORT_ONLY=False` para passar a bloquear.

A política permite o que o app realmente usa (HTMX/Alpine via unpkg, GTM, Google Fonts,
imagens de qualquer https p/ fotos de quarto e tour 360º). `'unsafe-inline'` em script/style
é necessário hoje (muitos inline + Alpine `x-...`); o passo seguinte do hardening é migrar
para nonce e remover o unsafe-inline.
"""
import json
import logging
import re

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("csp")

_POLITICA = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net "
    "https://cdnjs.cloudflare.com https://www.googletagmanager.com https://connect.facebook.net",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' https://www.google-analytics.com https://graph.facebook.com",
    "frame-src 'self' https:",          # tour 360º (Kuula/Matterport/Street View) + GTM
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'self'",           # anti-clickjacking (complementa X-Frame-Options)
    "form-action 'self'",
    # O navegador manda cada violação para cá (também em report-only): é o que diz se
    # dá para trocar para bloqueio sem quebrar tela.
    "report-uri /csp/relatorio/",
])

# Tokens na URL (portal do hóspede, link de pagamento) não vão para o log.
_TOKEN = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")


def _limpa(url) -> str:
    texto = str(url or "")[:300].split("?")[0].split("#")[0]
    return _TOKEN.sub("<token>", texto)


@csrf_exempt  # o navegador envia sem cookie nem token de formulário
@require_POST
def relatorio_csp(request):
    """Recebe as violações de CSP e registra uma linha por violação no log ("csp"):
    diretiva, o que foi barrado e em que página. Corpo limitado e IP com limite de
    envio; tokens das URLs mascarados."""
    from .ratelimit import limite_excedido

    if limite_excedido(request, "csp", limite=60, janela_seg=300):
        return HttpResponse(status=204)
    corpo = request.body[:20_000]
    try:
        dados = json.loads(corpo or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    # Formato antigo ({"csp-report": {...}}) e Reporting API ([{"body": {...}}]).
    itens = dados if isinstance(dados, list) else [dados]
    for item in itens[:20]:
        if not isinstance(item, dict):
            continue
        rel = item.get("csp-report") or item.get("body") or item
        if not isinstance(rel, dict):
            continue
        logger.warning(
            "CSP: %s barrou %s em %s",
            rel.get("violated-directive") or rel.get("effectiveDirective") or "?",
            _limpa(rel.get("blocked-uri") or rel.get("blockedURL")),
            _limpa(rel.get("document-uri") or rel.get("documentURL")),
        )
    return HttpResponse(status=204)


class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resposta = self.get_response(request)
        report_only = getattr(settings, "CSP_REPORT_ONLY", True)
        header = ("Content-Security-Policy-Report-Only" if report_only
                  else "Content-Security-Policy")
        resposta.setdefault(header, _POLITICA)
        return resposta


class MFAObrigatorioMiddleware:
    """Fase 4: superusuário sem MFA ativo é levado a ativar antes de usar o CRM."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.urls import reverse

        from .mfa import mfa_obrigatorio

        if getattr(settings, "TESTING", False) or not getattr(settings, "MFA_OBRIGATORIO", True):
            return self.get_response(request)
        user = getattr(request, "user", None)
        if (user and user.is_authenticated and mfa_obrigatorio(user) and not user.mfa_ativo):
            livres = {reverse("mfa_ativar"), reverse("login"), reverse("logout"),
                      reverse("senha_esqueci")}
            if (request.path not in livres
                    and not request.path.startswith(("/static/", "/media/"))):
                messages.warning(request, "Ative o MFA para continuar — é obrigatório na sua conta.")
                return redirect("mfa_ativar")
        return self.get_response(request)
