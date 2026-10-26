"""`{% icone_peca nome escolha %}` — o ícone da peça, do serviço, do item de enxoval ou
do estado, inline e monocromático.

Mesma forma do `{% icone_canal %}` do Marketing: SVG inline `viewBox="0 0 24 24"`,
`aria-hidden="true"`, `focusable="false"`, cor por `currentColor` e classe `.ico-peca`
(nada de `<img>`, nada de sprite novo). O nome continua em texto ao lado — o ícone é
leitura de relance, não legenda.

Chaves, inferência pelo nome e procedência/licença dos traçados (Lucide ISC, Tabler MIT
e os próprios): `apps/lavanderia/icones.py`.

Uso:
    {% load pecas_lavanderia %}
    {% icone_peca servico.nome servico.icone %}      {# escolha manual vence a inferência #}
    {% icone_peca "Lençol casal" %}
    {% icone_peca item.nome classe="ico-peca--grande" %}

`ESCOLHAS_ICONES_LAV` (em `icones.py`) alimenta o `<select>` e a grade de desenhos da
tabela de preços, já agrupados por tipo.
"""
from decimal import Decimal

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..icones import icone_de, svg_de

register = template.Library()

__all__ = ["icone_peca", "ordens_em_producao", "passo_da_quantidade",
           "resumo_da_cesta"]


@register.simple_tag
def icone_peca(nome, escolha="", classe=""):
    classes = " ".join(parte for parte in ("ico-peca", classe) if parte)
    # O miolo sai da tabela fixa ICONES (icones.py): o nome só escolhe a chave.
    return format_html(
        '<svg class="{}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{}</svg>',
        classes, mark_safe(svg_de(icone_de(nome, escolha))),  # nosec B308, B703
    )


@register.simple_tag
def ordens_em_producao():
    """Quantas ordens estão em produção, para a contagem da aba «Ordens».

    A barra de seções é a mesma nas cinco telas do módulo; a contagem sai daqui
    para as cinco views não repetirem o mesmo `count()` no contexto.
    """
    from ..models import OrdemLavanderia

    return OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO).count()


@register.simple_tag
def resumo_da_cesta(ordem):
    """`{"n_pecas", "granel"}` do que está na ordem — o contador do painel e a aba «Cesta».

    Peça e quilo não se somam no mesmo número: «3 peças · 1,5 kg» diz a verdade,
    «4,5» não diz nada. Fica aqui, e não na view, porque o mesmo partial é
    devolvido por três rotas HTMX e também incluído na tela inteira.
    """
    from ..models import ServicoLavanderia

    pecas = 0
    granel = Decimal("0.000")
    for item in ordem.itens.all():
        if item.servico.unidade == ServicoLavanderia.Unidade.KG:
            granel += item.quantidade
        else:
            pecas += int(item.quantidade)
    return {"n_pecas": pecas, "granel": granel}


@register.simple_tag
def passo_da_quantidade(item, sinal):
    """A quantidade que o «−»/«+» da cesta vai GRAVAR (o service define, não soma).

    Peça anda de 1 em 1; serviço a granel, de meio quilo. Nunca abaixo de zero —
    e zero é justamente o que remove a linha. Devolve texto com ponto decimal,
    porque o valor viaja no `hx-vals` e não na tela (a vírgula é do operador).
    """
    from ..models import ServicoLavanderia

    passo = (Decimal("0.5") if item.servico.unidade == ServicoLavanderia.Unidade.KG
             else Decimal("1"))
    nova = item.quantidade + (passo if sinal == "+" else -passo)
    return f"{max(nova, Decimal('0')):f}"
