"""
Seletor de período compartilhado (mês/ano + intervalo personalizado).

Usado por Relatórios e pela Trilha de auditoria — um único controle, mesmo
comportamento em toda parte. Padrão = mês corrente; `de`+`ate` sobrepõem com um
intervalo livre. `padrao="proximo_mes"` abre no mês que vem, para quem olha para a
frente (carteira, pickup, ritmo de vendas): o mês corrente já está quase todo vendido
e abrir nele esconderia justamente o que ainda dá para vender.
"""
import calendar
from datetime import date, datetime, timedelta

from django.utils import timezone

MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _data(txt):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _referencia(padrao=None):
    """O mês que o seletor abre quando o GET não traz mês/ano."""
    hoje = timezone.localdate()
    if padrao == "proximo_mes":
        return (hoje.replace(day=1) + timedelta(days=31)).replace(day=1)
    return hoje


def _mes_ano(request, padrao=None):
    """(mês, ano) escolhidos, com fallback no mês de referência."""
    ref = _referencia(padrao)
    try:
        mes = int(request.GET.get("mes") or ref.month)
        ano = int(request.GET.get("ano") or ref.year)
    except (TypeError, ValueError):
        mes, ano = ref.month, ref.year
    if not 1 <= mes <= 12:
        mes = ref.month
    if not 2 <= ano <= 9998:
        ano = ref.year
    return mes, ano


def periodo(request, padrao=None):
    """Período resolvido: MÊS/ANO (padrão) ou `de`+`ate`. Retorna (inicio, fim, rotulo)."""
    de, ate = _data(request.GET.get("de")), _data(request.GET.get("ate"))
    if de and ate and de <= ate and (ate - de).days <= 3660:
        return de, ate, "personalizado"
    mes, ano = _mes_ano(request, padrao)
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return inicio, fim, f"{MESES_PT[mes]}/{ano}"


def selecao_periodo(request, padrao=None):
    """Opções do seletor mês/ano para o template (últimos 5 anos + o corrente)."""
    hoje = timezone.localdate()
    mes_sel, ano_sel = _mes_ano(request, padrao)
    meses = [(i, MESES_PT[i]) for i in range(1, 13)]
    anos = list(range(hoje.year, hoje.year - 5, -1))
    if ano_sel not in anos:
        anos = sorted(set(anos + [ano_sel]), reverse=True)
    return {"meses": meses, "anos": anos, "mes_sel": mes_sel, "ano_sel": ano_sel}
