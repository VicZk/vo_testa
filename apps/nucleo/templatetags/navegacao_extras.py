"""Uma chave de navegação por rota, compartilhada pelo HTML e pelo histórico."""
from django import template

from apps.nucleo.modulos import APRESENTACAO

register = template.Library()


@register.simple_tag
def navegacao_ativa(request):
    match = getattr(request, "resolver_match", None)
    if not match:
        return ""
    namespace, nome = match.namespace, match.url_name or ""
    if namespace == "comercial":
        if nome.startswith("pagina"):
            return "comercial_paginas"
        if nome.startswith("resposta"):
            return "comercial_respostas"
    if namespace:
        # Day pass usa o acesso de Reservas e suas abas, sem módulo paralelo.
        if namespace == "daypass":
            return "reservas"
        for codigo, apresentacao in APRESENTACAO.items():
            if apresentacao.get("url_name", "").partition(":")[0] == namespace:
                return codigo
        return namespace
    for prefixo, chave in (
        ("caixa_sess", "caixa_sessoes"), ("caixa_", "caixa"),
        ("funcionario", "funcionarios"), ("pessoa", "pessoas"),
        ("tipo_uh", "estrutura"), ("uh_", "estrutura"),
        ("temporada", "temporadas"), ("lancamento", "lancamentos"),
        ("conta_", "contas"), ("logbook", "logbook"),
        ("pendencias", "pendencias"),
    ):
        if nome.startswith(prefixo):
            return chave
    return nome
