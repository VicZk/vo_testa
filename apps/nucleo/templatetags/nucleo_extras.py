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


@register.simple_tag
def aviso_nfce():
    """Aviso de venda sem NFC-e (sem Inscrição Estadual) para o topo dos PDVs."""
    from django.utils.html import format_html

    from ..fiscal_regras import AVISO_SEM_NFCE, nfce_disponivel

    if nfce_disponivel():
        return ""
    return format_html('<p class="mensagem warning aviso-nfce" role="status">{}</p>',
                       AVISO_SEM_NFCE)


@register.filter
def rotulo(campo):
    """Rótulo do campo SEM o dois-pontos que o Django acrescenta.

    O `label_suffix` default do Django põe ":" em todo rótulo gerado — e nenhum
    rótulo escrito à mão no produto tem. O resultado era `Nome:` ao lado de
    `Papéis desta pessoa`, na mesma tela. Uso: `{{ campo|rotulo }}`.
    """
    return campo.label_tag(label_suffix="")


@register.filter
def eh_checkbox(campo):
    """True para caixas de marcar — elas pedem rótulo AO LADO, não em cima.

    Numa grade feita para campos de 42 px, um checkbox sozinho sob um rótulo
    deixa a linha torta e a caixinha solta no meio do nada.
    """
    from django.forms import CheckboxInput

    return isinstance(campo.field.widget, CheckboxInput)
