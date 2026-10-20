from django import template

from ..estrutura import capacidade as _capacidade
from ..estrutura import descricao_camas as _descricao_camas
from ..models import modulo_ativo as _modulo_ativo

register = template.Library()


@register.filter
def modulo_ativo(codigo):
    """Uso: {% if 'appsite'|modulo_ativo %} ... {% endif %}"""
    return _modulo_ativo(codigo)


@register.filter
def pode_area(user, codigo):
    """Uso: {% if user|pode_area:'equipe' %} ... {% endif %}"""
    return bool(user.is_authenticated and user.pode_area(codigo))


@register.filter
def pode_modulo(user, codigo):
    """Uso: {% if user|pode_modulo:'reservas' %} ... {% endif %}"""
    return bool(user.is_authenticated and user.pode_acessar(codigo))


@register.filter
def camas_uh(uh):
    """Frase de camas gerada da estrutura. Uso: {{ uh|camas_uh }}"""
    return _descricao_camas(uh)


@register.filter
def lotacao_uh(uh):
    """Lotação máxima da unidade (com crianças no sofá). Uso: {{ uh|lotacao_uh }}"""
    return _capacidade(uh)["maxima_criancas"]


@register.simple_tag
def campos_antirrobo():
    """Campos invisíveis do anti-robô (ver apps/nucleo/antirrobo.py): a armadilha e o
    carimbo de tempo. Vai logo depois do {% csrf_token %} de formulário público."""
    from django.utils.html import format_html

    from ..antirrobo import CAMPO_ARMADILHA, CAMPO_CARIMBO, carimbo

    return format_html(
        '<div aria-hidden="true" style="position:absolute;left:-10000px;top:auto;'
        'width:1px;height:1px;overflow:hidden">'
        '<label>Não preencha<input type="text" name="{}" tabindex="-1" autocomplete="off">'
        '</label></div><input type="hidden" name="{}" value="{}">',
        CAMPO_ARMADILHA, CAMPO_CARIMBO, carimbo(),
    )
