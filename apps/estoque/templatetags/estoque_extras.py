"""Filtros das telas de Estoque — quantidade legível (ver `apps/estoque/formato.py`)."""
from django import template

from ..formato import com_sinal, numero, quantidade, sigla

register = template.Library()


@register.filter
def qtd(valor, unidade=""):
    """`{{ linha.saldo|qtd:linha.produto.unidade }}` → '55 un'."""
    return quantidade(valor, unidade)


@register.filter
def qtd_sinal(valor, unidade=""):
    """Movimento do kardex: '+12 un' / '−3 un'."""
    return com_sinal(valor, unidade)


@register.filter
def num(valor):
    """Só o número, sem unidade: '1.250' · '4,5'."""
    return numero(valor)


@register.filter
def unidade_sigla(unidade):
    return sigla(unidade)
