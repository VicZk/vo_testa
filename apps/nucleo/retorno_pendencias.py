"""Origem explícita da Central, restrita à sua própria URL e sem estado na sessão."""

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.urls import get_script_prefix, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .pendencias import ESTADOS, origens_permitidas, url_pendencias

PARAMETRO = "retorno_pendencias"


def _partes(url):
    if not isinstance(url, str) or len(url) > 4096 or "\\" in url or any(ord(c) < 32 for c in url):
        return None
    try:
        return urlsplit(url)
    except ValueError:
        return None


def validar_retorno(valor, usuario):
    """Aceita somente filtros conhecidos da Central, nunca uma URL de redirecionamento livre."""
    partes = _partes(valor)
    if not partes or partes.scheme or partes.netloc or partes.fragment or partes.path != reverse("pendencias"):
        return ""
    try:
        pares = parse_qsl(partes.query, keep_blank_values=True, max_num_fields=3)
    except ValueError:
        return ""
    filtros = dict(pares)
    if len(filtros) != len(pares) or set(filtros) - {"origem", "estado", "pagina"}:
        return ""
    origem, estado, pagina = (filtros.get(chave, "") for chave in ("origem", "estado", "pagina"))
    if origem and origem not in origens_permitidas(usuario):
        return ""
    if estado and estado not in ESTADOS:
        return ""
    if pagina and (not pagina.isascii() or not pagina.isdigit() or len(pagina) > 8 or int(pagina) < 1):
        return ""
    retorno = url_pendencias(origem, estado)
    if pagina:
        retorno += ("&" if "?" in retorno else "?") + urlencode({"pagina": int(pagina)})
    return retorno


def com_retorno(destino, retorno):
    """Acrescenta a origem a uma tela interna, preservando filtros e âncoras do destino."""
    partes = _partes(destino)
    if not retorno or not partes or partes.scheme or partes.netloc:
        return destino
    if not partes.path.startswith(reverse("dashboard")):
        return destino
    if partes.path.startswith(reverse("pendencias")) or partes.path in (reverse("login"), reverse("logout")):
        return destino
    try:
        parametros = [(k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True, max_num_fields=100)
                      if k != PARAMETRO]
    except ValueError:
        return destino
    parametros.append((PARAMETRO, retorno))
    return urlunsplit(partes._replace(query=urlencode(parametros)))


class RetornoPendenciasMiddleware:
    """Mantém o retorno depois de POST/redirect e de ações HTMX, apenas na requisição atual.

    Deve ficar depois de RespostaFormularioMiddleware: a resposta Location é
    ajustada antes de aquele middleware convertê-la no JSON do formulário.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.retorno_pendencias = ""
        prefixo = get_script_prefix().rstrip("/")
        raiz = reverse("dashboard").removeprefix(prefixo)
        if request.path_info.startswith(raiz) and request.user.is_authenticated:
            valor = request.GET.get(PARAMETRO, "")
            if not valor and request.method == "POST":
                valor = request.POST.get(PARAMETRO, "")
                # Formulários nativos e fetch legados ainda funcionam sem decorar
                # seus campos. O Referer só vale para POST do mesmo origin.
                if not valor:
                    referer = request.headers.get("Referer", "")
                    if url_has_allowed_host_and_scheme(referer, {request.get_host()}, require_https=request.is_secure()):
                        partes = _partes(referer)
                        try:
                            if partes and partes.scheme == request.scheme and partes.netloc == request.get_host():
                                valor = dict(parse_qsl(partes.query, max_num_fields=100)).get(PARAMETRO, "")
                        except ValueError:
                            pass
            request.retorno_pendencias = validar_retorno(valor, request.user) if valor else ""
        resposta = self.get_response(request)
        retorno = request.retorno_pendencias
        if retorno:
            for nome in ("Location", "HX-Redirect", "HX-Push-Url", "HX-Replace-Url"):
                if nome in resposta:
                    resposta[nome] = com_retorno(resposta[nome], retorno)
            if "HX-Location" in resposta:
                valor = resposta["HX-Location"]
                try:
                    dados = json.loads(valor)
                except (ValueError, TypeError):
                    resposta["HX-Location"] = com_retorno(valor, retorno)
                else:
                    if isinstance(dados, dict) and isinstance(dados.get("path"), str):
                        dados["path"] = com_retorno(dados["path"], retorno)
                        resposta["HX-Location"] = json.dumps(dados)
        return resposta
