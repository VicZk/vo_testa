from django import template

from ..formatacao import frase, rotulo_acao, rotulo_alvo, rotulo_gravidade

register = template.Library()


@register.filter
def frase_auditoria(registro):
    """Frase legível de um registro da trilha (ver apps/auditoria/formatacao.py)."""
    return frase(registro)


register.filter("rotulo_acao", rotulo_acao)
register.filter("rotulo_alvo", rotulo_alvo)
register.filter("rotulo_gravidade", rotulo_gravidade)
