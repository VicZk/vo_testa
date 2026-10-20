"""Dados de contato da pousada para telas que não são do site.

O link público de pagamento e o portal do hóspede precisam dizer "fale com a
pousada" (WhatsApp/telefone), mas as views deles não passam a Configuração do
Site. Esta tag busca o registro único — uma consulta, só onde é usada.
"""

from django import template

register = template.Library()


@register.simple_tag
def contato_pousada():
    """Registro único de ConfiguracaoSite (telefone, whatsapp, email, endereço)."""
    from apps.site.models import ConfiguracaoSite

    return ConfiguracaoSite.load()


@register.simple_tag
def encarregado_lgpd():
    """Encarregado pelo tratamento de dados (LGPD, art. 41): nome e e-mail publicados
    na política de privacidade (configurações LGPD_ENCARREGADO_*)."""
    from django.conf import settings

    return {
        "nome": settings.LGPD_ENCARREGADO_NOME,
        "email": settings.LGPD_ENCARREGADO_EMAIL,
    }
