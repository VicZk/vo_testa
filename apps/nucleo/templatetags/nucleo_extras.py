from django import template

from ..estrutura import capacidade as _capacidade
from ..estrutura import descricao_camas as _descricao_camas
from ..formatos import qtd_br as _qtd_br
from ..models import modulo_ativo as _modulo_ativo

register = template.Library()


@register.filter
def moeda_sem_quebra(valor):
    """Mantém o prefixo com o valor dentro de indicadores que também têm texto."""
    return str(valor).replace("R$ ", "R$\u00a0")


@register.filter
def quantidade_br(valor):
    """Quantidades de estoque sem zeros decimais desnecessários: 5.000 → 5."""
    return "" if valor is None or valor == "" else _qtd_br(valor)


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


@register.inclusion_tag("componentes/copiar.html")
def copiar(texto, rotulo="", recado="", telefone="", mostrar=True):
    """Botão «Copiar» (+ «Enviar pelo WhatsApp») para tudo que a equipe manda a alguém.

    Antes, link de pagamento, Pix copia-e-cola, endereço do portal e link da página
    de captação eram texto solto: a recepção selecionava com o mouse, copiava e
    colava no WhatsApp — com o risco clássico de levar meio código.

    Uso:
        {% copiar url rotulo="Link de pagamento"
                  recado="Olá! Segue o link…" telefone=hospede.telefone %}

    - `texto`    o que vai para a área de transferência (e para a mensagem);
    - `rotulo`   legenda discreta em cima do bloco (entra também no leitor de tela);
    - `recado`   frase cordial que abre a mensagem; vazio = sem botão de WhatsApp;
    - `telefone` do destinatário; sem ele (ou ilegível) o WhatsApp abre para
                 escolher o contato, em vez de não abrir;
    - `mostrar`  False esconde o `<code>` e deixa só os botões (linha apertada).
    """
    from ..compartilhar import link_whatsapp, mensagem_whatsapp, telefone_whatsapp

    texto = "" if texto is None else str(texto)
    destino = telefone_whatsapp(telefone)
    return {
        "texto": texto,
        "rotulo": rotulo,
        "mostrar": mostrar,
        "whatsapp": link_whatsapp(mensagem_whatsapp(recado, texto), telefone) if recado else "",
        "tem_destino": bool(destino),
    }


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


@register.filter
def eh_textarea(campo):
    """Campos de texto livre ocupam a largura da grade de formulário."""
    from django.forms import Textarea

    return isinstance(campo.field.widget, Textarea)
