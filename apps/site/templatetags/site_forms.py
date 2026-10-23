"""Apresentação compartilhada pelos formulários públicos e seus widgets."""
from django import template

from apps.site.forms import _CAMPO

register = template.Library()


@register.simple_tag
def classe_campo_site():
    return _CAMPO
