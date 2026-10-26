"""Acesso sem senha e troca de versão nas duas cópias de comparação da VPS.

Só entra pelo `settings_vps.py` desta pasta, que as cópias da VPS (versão anterior e
atualizada) usam. A produção e o desenvolvimento local nunca carregam este arquivo.

- Sem senha: a tela de entrada, aberta pelo navegador, entra direto como o usuário de
  `ACESSO_LIVRE_USUARIO`; sem a variável, nada muda. Uma tela do CRM pedida sem sessão
  já manda para a entrada com `next`, então se cai na própria tela. Depois de "Sair",
  a entrada volta a pedir senha por 15 min, para dar para testar outro usuário.
- Troca de versão: a tela que não existe do outro lado (404 numa navegação vinda do
  outro site) sobe um nível até achar uma que exista, com um aviso.
"""

import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url
from django.urls import NoReverseMatch, get_script_prefix, reverse
from django.utils.http import url_has_allowed_host_and_scheme

SAIU = "acesso_livre_saiu"
AVISOU = "acesso_livre_avisou"


def _url(nome):
    try:
        return reverse(nome)
    except NoReverseMatch:
        return None


def _navegacao(request):
    # Robô de linha de comando não manda Sec-Fetch-*: só o navegador ganha a sessão.
    return request.method == "GET" and request.headers.get("Sec-Fetch-Mode") == "navigate"


def _marcar(request, resposta, nome, segundos):
    resposta.set_cookie(nome, "1", max_age=segundos, path=get_script_prefix(),
                        secure=request.is_secure(), httponly=True, samesite="Lax")


class AcessoLivreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nome = os.environ.get("ACESSO_LIVRE_USUARIO", "")
        if nome and self._na_entrada(request):
            Usuario = get_user_model()
            usuario = Usuario._default_manager.filter(
                **{Usuario.USERNAME_FIELD: nome}, is_active=True).first()
            if usuario:
                login(request, usuario, backend=settings.AUTHENTICATION_BACKENDS[0])
                return self._seguir(request)
        resposta = self.get_response(request)
        if nome and request.path == _url("logout"):
            _marcar(request, resposta, SAIU, 15 * 60)
        return self._subir(request, resposta)

    def _na_entrada(self, request):
        return (_navegacao(request) and not request.COOKIES.get(SAIU)
                and request.path in {resolve_url(settings.LOGIN_URL), _url("admin:login")}
                and not request.user.is_authenticated)

    def _seguir(self, request):
        proximo = request.GET.get("next", "")
        if url_has_allowed_host_and_scheme(proximo, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
            return HttpResponseRedirect(proximo)
        if request.path == _url("admin:login"):
            return HttpResponseRedirect(reverse("admin:index"))
        return HttpResponseRedirect(resolve_url(settings.LOGIN_REDIRECT_URL))

    def _subir(self, request, resposta):
        partes = [p for p in request.path_info.split("/") if p]
        if (resposta.status_code != 404 or not _navegacao(request) or not partes
                or request.headers.get("Sec-Fetch-Site") != "cross-site"):
            if 200 <= resposta.status_code < 300 and request.COOKIES.get(AVISOU):
                resposta.delete_cookie(AVISOU, path=get_script_prefix(), samesite="Lax")
            return resposta
        # /crm/a/b/ -> /crm/a/; a query fica para trás (era da tela que não existe).
        # Montar pelos pedaços não deixa "//outro.site/x/" virar endereço de fora.
        pai = "/" + "".join(f"{p}/" for p in partes[:-1])
        url = get_script_prefix().rstrip("/") + pai
        if not url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
            return resposta
        destino = HttpResponseRedirect(url)
        # Um aviso só por troca, mesmo subindo vários níveis; o site público não mostra.
        if pai.startswith("/crm/") and not request.COOKIES.get(AVISOU):
            messages.info(request, "Esta tela não existe nesta versão. Abrimos a mais próxima.")
            _marcar(request, destino, AVISOU, 60)
        return destino
