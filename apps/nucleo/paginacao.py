"""Paginação das listas do CRM.

Antes cada lista cortava em 200 ou 300 itens e o resto sumia sem aviso (e a de Pessoas
carregava a base inteira de uma vez). Agora a view chama `paginar()` e o template inclui
`componentes/paginacao.html`, que mantém busca e filtros ao trocar de página.
"""
from django.core.paginator import Paginator

POR_PAGINA = 50


def paginar(request, consulta, por_pagina: int = POR_PAGINA):
    """Página pedida em `?pagina=N` (número inválido vira a primeira; além do fim, a
    última — é o `get_page`). Desempata a ordem pelo pk: ordenando só por data, dois itens
    do mesmo dia podiam trocar de lugar entre uma página e outra (um repetia, outro
    sumia)."""
    if hasattr(consulta, "query"):
        ordem = list(consulta.query.order_by)
        if not ordem and consulta.query.default_ordering:
            ordem = list(consulta.model._meta.ordering)
        nomes = {campo.lstrip("-") for campo in ordem if isinstance(campo, str)}
        if not nomes & {"pk", "id"}:
            consulta = consulta.order_by(*ordem, "pk")
    return Paginator(consulta, por_pagina).get_page(request.GET.get("pagina"))
