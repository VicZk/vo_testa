"""Resposta progressiva dos formulários que historicamente usavam POST/redirect.

O navegador conserva os controles enquanto a validação falha. Não armazenamos
rascunhos em sessão, localStorage ou logs. Sem o cabeçalho, a view segue seu
contrato HTTP original; formulários Django com renderização própria são mantidos.
"""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.messages import ERROR, get_messages
from django.http import JsonResponse
from django.shortcuts import resolve_url


class RespostaFormularioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        preservar = request.method == "POST" and request.headers.get("X-Form-Preserve") == "1"
        if preservar:
            storage = get_messages(request)
            anteriores = {id(m) for m in storage}
            storage.used = False
        resposta = self.get_response(request)
        if not preservar:
            return resposta
        mensagens = list(storage)
        novas = [m for m in mensagens if id(m) not in anteriores]
        erros = [str(m) for m in novas if m.level >= ERROR]
        if erros and resposta.status_code < 400:
            # As mensagens são exibidas no formulário atual, uma única vez.
            resultado = JsonResponse({"errors": erros}, status=422)
            # Avisos anteriores e mensagens de outros níveis continuam disponíveis.
            for mensagem in mensagens:
                if id(mensagem) in anteriores or mensagem.level < ERROR:
                    storage.add(mensagem.level, mensagem.message, mensagem.extra_tags)
        else:
            storage.used = False
            if resposta.status_code in (301, 302, 303):
                if urlsplit(resposta["Location"]).path == urlsplit(resolve_url(settings.LOGIN_URL)).path:
                    resultado = JsonResponse({"errors": [
                        "Sua sessão expirou. Entre novamente em outra aba e volte para reenviar este formulário; seus dados continuam aqui."
                    ]}, status=401)
                else:
                    resultado = JsonResponse({"redirect": resposta["Location"]})
            else:
                return resposta
        resultado["Cache-Control"] = "no-store"
        return resultado


def erros_do_formulario(form):
    return " ".join(
        f"{form.fields[campo].label or campo}: {erro}" if campo in form.fields else str(erro)
        for campo, erros in form.errors.items() for erro in erros
    )
