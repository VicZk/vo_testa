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
