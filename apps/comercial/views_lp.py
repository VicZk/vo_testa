"""LP Fundador — servida direto do HTML oficial em LPs/LP_Fundador/ (fonte da verdade).

A raiz `/` serve a LP quando HOME_MODO='lp_fundador' (senão, o site normal). O formulário
posta JSON no endpoint do CRM e cai no funil (capturar_lead_site).
"""
import base64
import hashlib
import json
import logging
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import get_script_prefix, reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.ratelimit import janela_atual, somar

from . import services
from .forms_lead import ContatoLeadForm

logger = logging.getLogger(__name__)

_LP_PATH = Path(settings.BASE_DIR) / "LPs" / "LP_Fundador" / "LP_Fundador.html"
_LP_CACHE = {"html": None}

# O JS das LPs posta o lead em '/lp/<slug>/lead/'.
_LEAD_NO_JS = re.compile(r"""(["'`])/lp/""")


def _no_prefixo(html: str) -> str:
    """O HTML das LPs é feito fora do Django, com caminhos absolutos. Sob um prefixo
    (URL_PREFIX, ex.: /votesta) eles apontariam para a raiz do domínio — outro projeto.
    Sem prefixo (a produção), devolve o HTML como veio.

    Troca o caminho absoluto de atributo (href="/privacidade/", src="/static/…", o
    /lp/arquivo/<hash> do _desembutir) e de url(/…) no CSS; "//cdn…" e o que já vem
    com o prefixo (o aviso de cookies sai do {% url %}) ficam como estão."""
    prefixo = get_script_prefix().rstrip("/")
    if not prefixo:
        return html
    pula = r"(?!/|" + re.escape(prefixo.lstrip("/")) + r"/)"
    atributo = re.compile(r"""((?:href|src|action|poster|content)=["'])/""" + pula)
    url_css = re.compile(r"""(url\(\s*["']?)/""" + pula)
    html = atributo.sub(lambda m: m.group(1) + prefixo + "/", html)
    html = url_css.sub(lambda m: m.group(1) + prefixo + "/", html)
    return _LEAD_NO_JS.sub(lambda m: m.group(1) + prefixo + "/lp/", html)

# Anti-abuso do endpoint público de lead (não é auth — só corta spam/bot):
_RATE_MAX = 6            # nº de leads aceitos por IP
_RATE_JANELA = 600       # … a cada 10 min
_MIN_MS = 1500           # tempo mínimo de preenchimento (bot posta instantâneo)
_VISITA_COOKIE = "lpv_fundador"   # conta 1 visita por navegador (dedupe reload)
_VISITA_TTL = 6 * 3600


def _com_aviso_de_cookies(html: str) -> str:
    """Põe o aviso de cookies (o mesmo do site) no fim do <body> da LP autocontida.

    LGPD: as tags de medição das LPs (Google tag, Meta Pixel) vêm no HTML como
    `<script type="text/plain" data-consentimento>` — o navegador não executa — e o
    consentimento.js do aviso só as liga no "Aceitar". Antes, as três LPs carregavam
    GA4 e Pixel na hora, sem pergunta. Usa a ÚLTIMA ocorrência de </body>."""
    antes, fecho, depois = html.rpartition("</body>")
    if not fecho:
        return html
    return antes + render_to_string("componentes/consentimento.html") + fecho + depois


# O HTML das LPs vem pronto do design e é servido como está. Medido em 390px com
# toque emulado, o caminho de conversão já está certo — campos de 52 a 54px, as
# cápsulas de "quantas pessoas" com rótulo de 46px e o consentimento com rótulo de
# 292 a 350px de largura. O que ficou pequeno é secundário: a pergunta do FAQ
# (31 a 35px) e o "Inscrever outra pessoa" (31px). Só esses dois entram aqui, só
# no dedo, e só crescendo por dentro — os dois já centram o próprio texto, então
# ganham altura sem mexer no desenho. O que NÃO entra, de propósito, está no
# comentário do fim: mexer na marca da campanha é decisão do dono, não polimento.
_TOQUE_LP = """
<style>
@media (pointer: coarse) {
  summary { min-height: 44px; }
  .ticket-again { min-height: 44px; }
}
</style>
"""
# Fora daqui: a logo do topo (22 a 40px) e o "Entrar para a lista" (42px) — crescer
# qualquer um dos dois empurra o cabeçalho de uma campanha que já está no ar, e o
# ganho é pequeno. Os links "Privacidade" dentro da frase de consentimento ficam
# como estão: alvo dentro de texto corrido é isento pela WCAG 2.5.8.


def _com_toque_no_celular(html: str) -> str:
    """Acrescenta ao fim do <head> da LP o mínimo de alvo de toque (ver _TOQUE_LP)."""
    antes, fecho, depois = html.rpartition("</head>")
    if not fecho:
        return html
    return antes + _TOQUE_LP + fecho + depois


# Fotos e fontes embutidas. O HTML chega do design autocontido, com as imagens e as
# fontes em base64 dentro do próprio arquivo: a Inauguração tem 2,1 MB, e as fontes e a
# foto do hero moram no <style> do <head> — o celular baixava 800 KB antes de pintar a
# primeira letra. Ao servir, cada `data:` de imagem ou fonte vira um endereço próprio,
# nomeado pelo hash do conteúdo (`/lp/arquivo/<hash>.<ext>`): o navegador baixa em
# paralelo, só o que a tela usa, uma vez só o que se repete, e guarda para a próxima
# visita. O arquivo em LPs/ continua autocontido (abre direto do disco).
_ARQUIVOS_LP: dict[str, tuple[str, bytes]] = {}
_EMBUTIDO = re.compile(r"data:(?P<mime>image/(?:png|jpeg|webp|gif|avif)|font/woff2?)"
                       r";base64,(?P<b64>[A-Za-z0-9+/=]+)")
_EXTENSAO = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
             "image/gif": "gif", "image/avif": "avif", "font/woff2": "woff2",
             "font/woff": "woff"}
_EMBUTIDO_MINIMO = 4096   # caracteres de base64 (3 KB): abaixo disso não vale um pedido


def _desembutir(html: str) -> str:
    def trocar(m):
        if len(m.group("b64")) < _EMBUTIDO_MINIMO:
            return m.group(0)
        dados = base64.b64decode(m.group("b64"))
        nome = f"{hashlib.sha256(dados).hexdigest()[:20]}.{_EXTENSAO[m.group('mime')]}"
        _ARQUIVOS_LP[nome] = (m.group("mime"), dados)
        return reverse("lp:arquivo", args=[nome])
    return _EMBUTIDO.sub(trocar, html)


def _lp_html() -> str:
    # Em produção lê uma vez (cache em memória); em DEBUG relê p/ editar ao vivo.
    if _LP_CACHE["html"] is None or settings.DEBUG:
        _LP_CACHE["html"] = _com_toque_no_celular(_com_aviso_de_cookies(
            _desembutir(_LP_PATH.read_text(encoding="utf-8"))))
    return _LP_CACHE["html"]


_BOTS = ("bot", "crawl", "spider", "facebookexternalhit", "whatsapp", "preview",
         "slurp", "bingpreview", "embedly", "quora", "pinterest", "telegrambot",
         "developers.google.com", "headless")


def _ip(request) -> str:
    """IP do cliente respeitando o proxy do Railway (X-Forwarded-For)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")) or "?"


def _contar_visita_lp(request):
    """+1 visita na Página de Captação 'fundador' (pula scrapers/preview de link)."""
    ua = (request.META.get("HTTP_USER_AGENT", "") or "").lower()
    if not ua or any(b in ua for b in _BOTS):
        return
    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug="fundador").first()
    if pagina:
        services.registrar_visita_pagina(pagina)


@never_cache
def servir_lp_fundador(request):
    """Renderiza a LP Fundador (HTML autocontido). Injeta o Google tag (env).

    `@never_cache`: sem isto, recarregar/voltar no histórico ou um proxy serviriam do
    cache e a visita nunca chegaria ao servidor — subcontando as métricas.
    Conta 1 visita por navegador (cookie `lpv_fundador`) — reload/back não infla.
    """
    html = _lp_html().replace("__GTAG_ID__", getattr(settings, "GOOGLE_TAG_ID", "") or "")
    resp = HttpResponse(_no_prefixo(html))
    if not request.COOKIES.get(_VISITA_COOKIE):
        try:
            _contar_visita_lp(request)
        except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
            pass
        resp.set_cookie(_VISITA_COOKIE, "1", max_age=_VISITA_TTL,
                        httponly=True, samesite="Lax",
                        secure=not settings.DEBUG)
    return resp


def privacidade(request):
    """Política de Privacidade (LGPD) — pública, linkada pela LP."""
    return render(request, "lp/privacidade.html")


def home_root(request):
    """Raiz `/`: LP Fundador quando ligada por env; senão o site público normal."""
    if getattr(settings, "HOME_MODO", "") == "lp_fundador":
        return servir_lp_fundador(request)
    from apps.site import views as site_views
    return site_views.home(request)


def _receber_lead_lp(request, *, slug, origem_padrao, mensagem):
    """Lead de uma LP (JSON) → funil. Igual para todas as LPs: anti-robô silencioso,
    limite por IP, validação do WhatsApp, captura com o consentimento que a pessoa
    marcou (sem o campo, não é consentimento) e o evento Lead na Conversions API
    (dedupe com o Pixel pelo event_id). Só confirma depois da gravação."""
    try:
        dados = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "erro": "json inválido"}, status=400)

    campos_texto = ("nome", "email", "whatsapp", "whats", "empresa", "origem",
                    "event_id", "fbp", "fbc")
    if not isinstance(dados, dict) or any(
        dados.get(campo) is not None and not isinstance(dados[campo], str)
        for campo in campos_texto
    ) or (dados.get("rastreio") is not None and not isinstance(dados["rastreio"], dict)):
        return JsonResponse({"ok": False, "erro": "dados inválidos"}, status=400)

    # Anti-bot silencioso: honeypot preenchido ou envio instantâneo → finge sucesso
    # (não revela a defesa) e descarta sem criar lead nem chamar a CAPI.
    if (dados.get("empresa") or "").strip():
        return JsonResponse({"ok": True})
    try:
        ms = float(dados.get("ms") or 0)
    except (TypeError, ValueError):
        ms = 0
    if 0 < ms < _MIN_MS:
        return JsonResponse({"ok": True})

    # Rate limit por IP (corta flood de leads/CAPI). Best-effort — cache pode faltar.
    ip = _ip(request)
    try:
        inicio, resta = janela_atual(_RATE_JANELA)
        if somar(f"lp_lead_rate:{ip}:{inicio}", resta) > _RATE_MAX:
            return JsonResponse({"ok": True})  # silencioso
    except Exception:  # noqa: BLE001 — sem cache, segue sem rate limit
        pass

    nome = (dados.get("nome") or "").strip()
    email = (dados.get("email") or "").strip()
    whats = (dados.get("whatsapp") or dados.get("whats") or "").strip()
    if not nome or not (email or whats):
        return JsonResponse({"ok": False, "erro": "dados incompletos"}, status=400)
    contato = ContatoLeadForm({"nome": nome, "email": email, "telefone": whats})
    if not contato.is_valid():
        erro = next(iter(contato.errors.values()))[0]
        return JsonResponse({"ok": False, "erro": erro}, status=400)
    nome, email = contato.cleaned_data["nome"], contato.cleaned_data["email"]
    if whats:
        from django.core.exceptions import ValidationError

        from apps.nucleo.validadores import validar_telefone_br
        try:
            whats = validar_telefone_br(whats)  # celular 11 dígitos; normaliza
        except ValidationError as e:
            return JsonResponse({"ok": False, "erro": e.messages[0]}, status=400)

    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug=slug).first()
    origem = dict(dados.get("rastreio") or {})
    origem.setdefault("origem_form", dados.get("origem") or origem_padrao)
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    try:
        with transaction.atomic():
            lead = services.capturar_lead_site(
                nome=nome, email=email, telefone=whats,
                tipo_interesse=(pagina.tipo_interesse if pagina else "hospedagem"),
                pagina=pagina, mensagem=mensagem,
                origem=origem, aceita_email=dados.get("consent") is True,
                ip=ip, user_agent=user_agent)
            if lead is None:
                raise RuntimeError("captação indisponível")
    except Exception as erro:  # noqa: BLE001 — erro visível, dados preservados na página
        logger.error("Falha na captação da LP %s (%s)", slug, type(erro).__name__)
        return JsonResponse({"ok": False, "erro": "Não conseguimos registrar agora. Tente novamente."},
                            status=503)

    # Conversions API (Meta) pelo servidor — dedupe com o Pixel via event_id.
    try:
        services.enviar_capi_lead(
            email=email, telefone=whats,
            event_id=(dados.get("event_id") or ""),
            fbp=(dados.get("fbp") or ""), fbc=(dados.get("fbc") or ""),
            event_source_url=request.META.get("HTTP_REFERER", ""),
            client_ip=ip, user_agent=user_agent)
    except Exception:  # noqa: BLE001
        pass
    return JsonResponse({"ok": True})


@csrf_exempt
@never_cache
@require_POST
def lp_fundador_lead(request):
    """Lead da LP Fundador (JSON) → funil."""
    return _receber_lead_lp(
        request, slug="fundador", origem_padrao="lp-fundador",
        mensagem="Lista de espera — LP Fundador")


# ─────────────────────────────────────────────────────────────────────────────
# LP Fundador II — nova campanha (13/09/2026), servida em paralelo à Fundador
# original, em /lp/fundador-2/. Código ADITIVO: não altera a LP que está no ar.
# ─────────────────────────────────────────────────────────────────────────────
_LP2_PATH = (Path(settings.BASE_DIR) / "LPs" / "LP_Fundador_II_13_09_2026"
             / "LP_Fundador_II_13_09_2026.html")
_LP2_CACHE = {"html": None}
_LP2_SLUG = "fundador-2"                 # casa com a PaginaCaptacao e o utm_campaign
_VISITA2_COOKIE = "lpv_fundador_2"       # conta 1 visita por navegador (dedupe reload)


def _lp2_html() -> str:
    if _LP2_CACHE["html"] is None or settings.DEBUG:
        _LP2_CACHE["html"] = _com_toque_no_celular(_com_aviso_de_cookies(
            _desembutir(_LP2_PATH.read_text(encoding="utf-8"))))
    return _LP2_CACHE["html"]


def _qtd_fundadores() -> int:
    """Nº real de leads na lista de fundadores — prova social viva.

    Conta as DUAS LPs (Fundador + Fundador II): a prova social é a lista inteira,
    não só a LP II (que herdou os leads da original). Marcadores robustos = slug da
    página de captação + `origem_form` (não depende de texto de observação).
    """
    from django.db.models import Q

    from .models import Oportunidade
    try:
        return Oportunidade.objects.filter(
            Q(pagina_captacao__slug__in=("fundador", _LP2_SLUG))
            | Q(origem_rastreio__origem_form__in=("lp-fundador", "lp-fundador-2"))
        ).distinct().count()
    except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
        return 0


def _contar_visita_pagina(request, slug: str):
    """+1 visita na Página de Captação `slug` (pula scrapers/preview de link)."""
    ua = (request.META.get("HTTP_USER_AGENT", "") or "").lower()
    if not ua or any(b in ua for b in _BOTS):
        return
    from .models import PaginaCaptacao
    pagina = PaginaCaptacao.objects.filter(slug=slug).first()
    if pagina:
        services.registrar_visita_pagina(pagina)


@never_cache
def servir_lp_fundador_2(request):
    """LP Fundador II (HTML autocontido) em /lp/fundador-2/. Injeta o Google tag."""
    html = _lp2_html().replace("__GTAG_ID__", getattr(settings, "GOOGLE_TAG_ID", "") or "")
    n = _qtd_fundadores()
    html = html.replace("__QTD_FUNDADORES__", str(n) if n else "56")  # fallback seguro
    resp = HttpResponse(_no_prefixo(html))
    if not request.COOKIES.get(_VISITA2_COOKIE):
        try:
            _contar_visita_pagina(request, _LP2_SLUG)
        except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
            pass
        resp.set_cookie(_VISITA2_COOKIE, "1", max_age=_VISITA_TTL,
                        httponly=True, samesite="Lax",
                        secure=not settings.DEBUG)
    return resp


@csrf_exempt
@never_cache
@require_POST
def lp_fundador_2_lead(request):
    """Lead da LP Fundador II (JSON) → funil, etiquetado na campanha fundador-2."""
    return _receber_lead_lp(
        request, slug=_LP2_SLUG, origem_padrao="lp-fundador-2",
        mensagem="Lista de espera — LP Fundador II")


# ─────────────────────────────────────────────────────────────────────────────
# LP Inauguração (sábado 31/10/2026) — HTML autocontido em
# /lp/inauguracao_31_10_2026/. Mesmo padrão da Fundador II: serve o HTML do disco e
# captura o RSVP no funil, etiquetado na campanha "inauguracao_31_10_2026".
# ─────────────────────────────────────────────────────────────────────────────
_LPINAUG_PATH = (Path(settings.BASE_DIR) / "LPs" / "LP_Inauguração_31_10_2026"
                 / "LP-Inauguracao-VoTesta.html")
_LPINAUG_CACHE = {"html": None}
_LPINAUG_SLUG = "inauguracao_31_10_2026"       # casa com a PaginaCaptacao / utm_campaign
_VISITA_INAUG_COOKIE = "lpv_inauguracao_31_10_2026"


def _lpinaug_html() -> str:
    if _LPINAUG_CACHE["html"] is None or settings.DEBUG:
        html = _LPINAUG_PATH.read_text(encoding="utf-8")
        # O HTML vem reusando o endpoint da Fundador II; aponta para a rota própria.
        html = html.replace("/lp/fundador-2/lead/", f"/lp/{_LPINAUG_SLUG}/lead/")
        # Canônico, og:url e a imagem de compartilhamento apontavam para
        # /lp/inauguracao/assets/…, que nunca existiu: o link no WhatsApp/Instagram saía
        # sem imagem e o Google recebia um canônico que dá 404. A imagem é a
        # `static/lp/og-inauguracao.jpg` (montada do próprio hero da LP).
        html = html.replace("/lp/inauguracao/assets/img/og-inauguracao-v2.jpg",
                            "/static/lp/og-inauguracao.jpg")
        html = html.replace("/lp/inauguracao/", f"/lp/{_LPINAUG_SLUG}/")
        _LPINAUG_CACHE["html"] = _com_toque_no_celular(_com_aviso_de_cookies(_desembutir(html)))
    return _LPINAUG_CACHE["html"]


@never_cache
def servir_lp_inauguracao(request):
    """LP Inauguração 31/10 (HTML autocontido) em /lp/inauguracao_31_10_2026/."""
    resp = HttpResponse(_no_prefixo(_lpinaug_html()))
    if not request.COOKIES.get(_VISITA_INAUG_COOKIE):
        try:
            _contar_visita_pagina(request, _LPINAUG_SLUG)
        except Exception:  # noqa: BLE001 — métrica nunca quebra a LP
            pass
        resp.set_cookie(_VISITA_INAUG_COOKIE, "1", max_age=_VISITA_TTL,
                        httponly=True, samesite="Lax", secure=not settings.DEBUG)
    return resp


@csrf_exempt
@never_cache
@require_POST
def lp_inauguracao_lead(request):
    """Lead (RSVP) da LP Inauguração (JSON) → funil, etiquetado 'inauguracao_31_10_2026'."""
    return _receber_lead_lp(
        request, slug=_LPINAUG_SLUG, origem_padrao="lp-inauguracao-31-10",
        mensagem="Inauguração 31/10 — confirmação de presença")


def arquivo_lp(request, nome):
    """Foto ou fonte que veio embutida numa LP (ver `_desembutir`). O nome é o hash do
    conteúdo — mudou a foto, muda o endereço —, então o navegador guarda para sempre."""
    if nome not in _ARQUIVOS_LP:      # outro worker serviu a LP: monta o mapa aqui também
        for carregar in (_lp_html, _lp2_html, _lpinaug_html):
            carregar()
    if nome not in _ARQUIVOS_LP:
        raise Http404
    mime, dados = _ARQUIVOS_LP[nome]
    resp = HttpResponse(dados, content_type=mime)
    patch_cache_control(resp, public=True, max_age=365 * 24 * 3600, immutable=True)
    return resp
