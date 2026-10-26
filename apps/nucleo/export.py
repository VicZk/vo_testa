"""Exportação CSV segura (compartilhada pelo projeto).

Neutraliza CSV/formula-injection: uma célula que começa com =, +, -, @ (ou tab/CR)
é executável ao abrir no Excel/Sheets. Prefixamos com aspa simples para virar texto.
Padrão pt-BR: delimitador `;` + BOM (utf-8-sig) para o Excel abrir com acentos.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

_GATILHOS = ("=", "+", "-", "@", "\t", "\r")
# Número negativo já formatado ("-12", "-1.234,56", "-R$ 50,50", "-3,5%"): só dígito,
# ponto, vírgula e o "R$ " do formatador; não tem como virar fórmula.
_NEGATIVO = re.compile(r"-(R\$ )?\d[\d.]*(,\d+)?%?")


def sanitizar_celula(v):
    """Devolve a célula neutralizada contra formula-injection."""
    s = "" if v is None else str(v)
    if s[:1] in _GATILHOS and not _NEGATIVO.fullmatch(s):
        return "'" + s
    return s


def celula(v):
    """Valor pronto para a célula do CSV pt-BR.

    Número sai com vírgula e sem separador de milhar ("1234,56"), que o Excel pt-BR lê
    como número; "1234.56" ficava como texto, e "5.7" pode virar data. Data sai em
    dd/mm/aaaa, data e hora no fuso da casa, None vazio e booleano como Sim/Não. Texto
    passa por `sanitizar_celula`.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        v = Decimal(str(v))
    if isinstance(v, Decimal):
        return format(abs(v) if not v else v, "f").replace(".", ",")
    if isinstance(v, datetime):
        if timezone.is_aware(v):
            v = timezone.localtime(v)
        return v.strftime("%d/%m/%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return sanitizar_celula(v)


def resposta_csv(filename: str) -> HttpResponse:
    """HttpResponse pronta para CSV pt-BR (utf-8 + um BOM no começo do arquivo).

    O charset é `utf-8`, não `utf-8-sig`: o `HttpResponse.write` codifica CADA chamada
    com o charset declarado, e o codec `utf-8-sig` escreve um BOM por chamada — ou seja,
    uma marca invisível no começo de TODA linha do CSV (o `csv.writer` escreve linha por
    linha). O BOM que o Excel pt-BR precisa é só o primeiro, escrito à mão aqui — mesmo
    jeito dos outros dois exports da casa (BOH e conciliação).
    """
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")  # BOM p/ Excel pt-BR
    return resp
