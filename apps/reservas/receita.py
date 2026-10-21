"""
Receita vendida: carteira (OTB), pickup, ritmo de vendas e custo de distribuição.

Produção e ocupação olham para TRÁS — o que já foi lançado na conta. Estes quatro
olham a VENDA: quanto já está vendido para datas que ainda vão chegar ("quanto temos
no Réveillon?"), o que entrou e saiu de reserva nos últimos dias, com quanta
antecedência o mês está vendendo e quanto custa vender por cada canal.

Três decisões valem para tudo aqui:

* **Uma régua só para a receita.** O valor de cada noite é o que o check-in vai lançar
  (`Reserva.valores_das_diarias()`), não o lançamento da conta: assim pré-reserva e
  confirmada — que ainda não lançaram nada — entram pela mesma conta da hospedada, e a
  noite da virada do mês cai no mês certo (estadia 30/11→03/12 = 1 noite em novembro,
  2 em dezembro). Consumo (frigobar, restaurante) não é receita de venda de quarto e
  fica fora: para ele há o relatório de Produção. O preço de cada noite é o da reserva,
  não o da conta — numa estadia estendida (`estender_estadia` cota as noites a mais pela
  tarifa do dia) as noites extras entram aqui pela diária acordada. É venda, não
  faturamento: o número fechado do mês que passou continua sendo o de Produção.
* **Carteira é o que segura quarto.** Confirmada, hospedada e saída são *firmes*;
  pré-reserva dentro da retenção é *provisória* (aparece separada, pode cair).
  Orçamento nunca segurou quarto, cancelada e no-show saíram — fora das duas.
* **Day use à parte**, como em `relatorio_ocupacao`: não é pernoite, não entra na
  ocupação nem no ADR (as 8 unidades inflariam a disponibilidade).

Só leitura — a interface pública é `services.py`, que o Relatórios consome.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.nucleo.models import UH, TipoUH

from .models import Reserva

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

# Estados na carteira.
FIRMES = (Reserva.Status.CONFIRMADA, Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT)
PROVISORIAS = (Reserva.Status.PRE_RESERVA,)
NA_CARTEIRA = FIRMES + PROVISORIAS
# Saíram da carteira (o pickup conta como baixa).
BAIXAS = (Reserva.Status.CANCELADA, Reserva.Status.NO_SHOW)
# Tudo que um dia entrou na carteira: o orçamento não, nunca segurou quarto.
ENTRARAM = NA_CARTEIRA + BAIXAS

_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Antecedência da venda (dias entre a venda e a CHEGADA), do mais antecipado ao de
# última hora — a curva acumula nesta ordem.
FAIXAS_ANTECEDENCIA = [
    (90, None, "90+ dias antes"),
    (60, 89, "60 a 89 dias"),
    (30, 59, "30 a 59 dias"),
    (14, 29, "14 a 29 dias"),
    (7, 13, "7 a 13 dias"),
    (0, 6, "0 a 6 dias (última hora)"),
]


# ───────────────────────────── peças comuns ─────────────────────────────

def _so_pernoite(qs):
    """Reservas de pernoite (sem Dia na Pousada)."""
    return qs.exclude(uh__tipo__modalidade=TipoUH.Modalidade.DAY_USE)


def _sem_retencao_vencida(qs):
    """Pré-reserva com a retenção vencida não está vendida — o quarto já voltou a
    aparecer livre (mesma regra de `reservas_ativas_qs`), mesmo antes do cron passar."""
    return qs.exclude(status=Reserva.Status.PRE_RESERVA, expira_em__lt=timezone.now())


def _pernoites(inicio, fim, statuses):
    """Reservas de pernoite com ao menos uma noite dentro de [inicio, fim].

    `checkout__gt=inicio` porque a noite do check-out não é noite: saída no dia 1º não
    vende nenhuma noite de um período que começa no dia 1º.
    """
    return _so_pernoite(Reserva.objects.filter(
        status__in=statuses, checkin__lte=fim, checkout__gt=inicio,
    ))


def noites_vendidas(reserva, inicio, fim) -> list:
    """`[(noite, valor)]` das noites da reserva que caem em [inicio, fim].

    Sem consulta: `valores_das_diarias()` é a lista que o check-in lança, uma por
    noite, já com os centavos do arredondamento na última.
    """
    dentro = []
    for n, valor in enumerate(reserva.valores_das_diarias()):
        noite = reserva.checkin + timedelta(days=n)
        if inicio <= noite <= fim:
            dentro.append((noite, valor))
    return dentro


def _quartos_de_pernoite() -> int:
    """Quartos ativos que vendem pernoite — o 100% da ocupação (hoje, 24)."""
    return (UH.objects.filter(status=UH.Status.ATIVA)
            .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE).count())


def _rotulo_do_dia(dia) -> str:
    return f"{dia:%d/%m} · {_SEMANA[dia.weekday()]}"


def _pct(parte, total) -> Decimal:
    if not total:
        return Decimal("0.0")
    return (Decimal(parte) / Decimal(total) * 100).quantize(Decimal("0.1"))


def _media(valor, divisor) -> Decimal:
    if not divisor:
        return ZERO
    return (valor / Decimal(divisor)).quantize(CENTAVO)


def _por_chave(chaves):
    """Acumuladores zerados por canal/faturamento — a ordem é a dos choices."""
    return {k: {"noites": 0, "receita": ZERO} for k in chaves}


def _canais():
    return _por_chave([c for c, _ in Reserva.Canal.choices])


def _faturamentos():
    return _por_chave([f for f, _ in Reserva.Faturamento.choices])


def _lista(acumulado, labels) -> list:
    """Dicionário de acumuladores → linhas com rótulo, na ordem dos choices."""
    return [{"rotulo": labels[k], "noites": v["noites"], "receita": v["receita"]}
            for k, v in acumulado.items()]


# ───────────────────────── 1. Carteira (OTB) ─────────────────────────

def carteira(inicio, fim) -> dict:
    """O que já está vendido para as estadias de [inicio, fim] — dia a dia.

    Quartos-noite, ocupação, ADR e receita de hospedagem, separando firme de
    pré-reserva, mais os cortes por canal e por faturamento. Day use vai num resumo
    à parte (não é pernoite).
    """
    quartos = _quartos_de_pernoite()
    dias = (fim - inicio).days + 1
    por_dia = {inicio + timedelta(days=i): {
        "firmes": 0, "provisorias": 0, "receita_firme": ZERO, "receita_provisoria": ZERO,
    } for i in range(dias)}
    canais, faturamentos = _canais(), _faturamentos()

    noites_firmes = noites_provisorias = 0
    receita_firme = receita_provisoria = ZERO

    for r in _sem_retencao_vencida(_pernoites(inicio, fim, NA_CARTEIRA)):
        firme = r.status in FIRMES
        for noite, valor in noites_vendidas(r, inicio, fim):
            dia = por_dia[noite]
            if firme:
                dia["firmes"] += 1
                dia["receita_firme"] += valor
                noites_firmes += 1
                receita_firme += valor
                # Os cortes por canal/faturamento só olham o firme: misturar a
                # pré-reserva faria o canal parecer ter vendido o que ainda pode cair.
                canais[r.canal]["noites"] += 1
                canais[r.canal]["receita"] += valor
                faturamentos[r.faturamento]["noites"] += 1
                faturamentos[r.faturamento]["receita"] += valor
            else:
                dia["provisorias"] += 1
                dia["receita_provisoria"] += valor
                noites_provisorias += 1
                receita_provisoria += valor

    linhas = [{
        "dia": dia, "rotulo": _rotulo_do_dia(dia),
        "ocupacao": _pct(v["firmes"], quartos),
        "ocupacao_total": _pct(v["firmes"] + v["provisorias"], quartos),
        **v,
    } for dia, v in sorted(por_dia.items())]

    disponiveis = quartos * dias
    return {
        "quartos": quartos, "dias": dias, "disponiveis": disponiveis,
        "linhas": linhas,
        "noites_firmes": noites_firmes, "noites_provisorias": noites_provisorias,
        "receita_firme": receita_firme, "receita_provisoria": receita_provisoria,
        "ocupacao": _pct(noites_firmes, disponiveis),
        "ocupacao_total": _pct(noites_firmes + noites_provisorias, disponiveis),
        "adr": _media(receita_firme, noites_firmes),
        "por_canal": _lista(canais, dict(Reserva.Canal.choices)),
        "por_faturamento": _lista(faturamentos, dict(Reserva.Faturamento.choices)),
        "day_use": _carteira_day_use(inicio, fim),
    }


def _carteira_day_use(inicio, fim) -> dict:
    """Dia na Pousada vendido no período — fora da ocupação, mas é dinheiro vendido."""
    reservas = _sem_retencao_vencida(Reserva.objects.filter(
        status__in=NA_CARTEIRA, checkin__gte=inicio, checkin__lte=fim,
        uh__tipo__modalidade=TipoUH.Modalidade.DAY_USE,
    ))
    quantas = pessoas = 0
    receita = ZERO
    for r in reservas:
        quantas += 1
        pessoas += r.total_hospedes
        receita += r.hospedagem_prevista()
    return {"reservas": quantas, "pessoas": pessoas, "receita": receita}


# ───────────────────────────── 2. Pickup ─────────────────────────────

def pickup(inicio, fim, *, janela=7, hoje=None) -> dict:
    """O que entrou e saiu da carteira de [inicio, fim] nos últimos `janela` dias.

    Entrou = reserva **vendida** na janela (data de criação) com noites no período.
    Saiu = reserva que **saiu** da carteira na janela (`cancelada_em`: cancelamento,
    expiração da retenção ou no-show) com noites no período. Pickup líquido = a
    diferença — é ele que diz se o mês está andando ou andando para trás.

    A janela conta dias corridos incluindo hoje: 7 dias = de (hoje − 6) até hoje.
    """
    hoje = hoje or timezone.localdate()
    desde = hoje - timedelta(days=janela - 1)
    por_dia = {desde + timedelta(days=i): {
        "entrou_noites": 0, "entrou_receita": ZERO,
        "saiu_noites": 0, "saiu_receita": ZERO,
    } for i in range((hoje - desde).days + 1)}
    canais = {k: {"entrou_noites": 0, "entrou_receita": ZERO,
                  "saiu_noites": 0, "saiu_receita": ZERO}
              for k, _ in Reserva.Canal.choices}

    def somar(reserva, quando, prefixo):
        noites = noites_vendidas(reserva, inicio, fim)
        valor = sum((v for _, v in noites), ZERO)
        destino = por_dia.get(quando)
        if destino is not None:
            destino[f"{prefixo}_noites"] += len(noites)
            destino[f"{prefixo}_receita"] += valor
        canais[reserva.canal][f"{prefixo}_noites"] += len(noites)
        canais[reserva.canal][f"{prefixo}_receita"] += valor
        return len(noites), valor

    entrou = {"reservas": 0, "noites": 0, "receita": ZERO}
    for r in _pernoites(inicio, fim, ENTRARAM).filter(
            criado_em__date__gte=desde, criado_em__date__lte=hoje):
        noites, valor = somar(r, timezone.localdate(r.criado_em), "entrou")
        entrou["reservas"] += 1
        entrou["noites"] += noites
        entrou["receita"] += valor

    saiu = {"reservas": 0, "noites": 0, "receita": ZERO}
    for r in _pernoites(inicio, fim, BAIXAS).filter(
            cancelada_em__date__gte=desde, cancelada_em__date__lte=hoje):
        noites, valor = somar(r, timezone.localdate(r.cancelada_em), "saiu")
        saiu["reservas"] += 1
        saiu["noites"] += noites
        saiu["receita"] += valor

    def com_liquido(d):
        return {**d,
                "liquido_noites": d["entrou_noites"] - d["saiu_noites"],
                "liquido_receita": d["entrou_receita"] - d["saiu_receita"]}

    labels = dict(Reserva.Canal.choices)
    return {
        "janela": janela, "desde": desde, "ate": hoje,
        "entrou": entrou, "saiu": saiu,
        "liquido": {"noites": entrou["noites"] - saiu["noites"],
                    "receita": entrou["receita"] - saiu["receita"]},
        "linhas": [{"dia": dia, "rotulo": _rotulo_do_dia(dia), **com_liquido(v)}
                   for dia, v in sorted(por_dia.items(), reverse=True)],
        "por_canal": [{"rotulo": labels[k], **com_liquido(v)} for k, v in canais.items()],
    }


# ─────────────────────── 3. Ritmo de vendas (pace) ───────────────────────

def ritmo_de_vendas(inicio, fim) -> dict:
    """Curva de vendas da carteira de [inicio, fim] por antecedência.

    Antecedência = dias entre a venda e a **chegada** da reserva (não entre a venda e
    cada noite: a decisão de compra é uma só, a da estadia). A curva acumula dos mais
    antecipados para os de última hora — comparada com a de um mês que já fechou, diz
    se este está adiantado ou atrasado.
    """
    faixas = [{"rotulo": rotulo, "de": de, "ate": ate, "noites": 0, "receita": ZERO}
              for de, ate, rotulo in FAIXAS_ANTECEDENCIA]
    noites_total = 0
    receita_total = ZERO
    soma_antecedencia = 0

    for r in _sem_retencao_vencida(_pernoites(inicio, fim, NA_CARTEIRA)):
        noites = noites_vendidas(r, inicio, fim)
        if not noites:
            continue
        valor = sum((v for _, v in noites), ZERO)
        # Venda lançada depois da chegada (entrada retroativa, walk-in digitado no dia
        # seguinte) conta como 0 dias de antecedência, nunca negativa.
        dias = max(0, (r.checkin - timezone.localdate(r.criado_em)).days)
        for faixa in faixas:
            if dias >= faixa["de"] and (faixa["ate"] is None or dias <= faixa["ate"]):
                faixa["noites"] += len(noites)
                faixa["receita"] += valor
                break
        noites_total += len(noites)
        receita_total += valor
        soma_antecedencia += dias * len(noites)

    acumulado_noites = 0
    acumulado_receita = ZERO
    for faixa in faixas:
        acumulado_noites += faixa["noites"]
        acumulado_receita += faixa["receita"]
        faixa["acumulado_noites"] = acumulado_noites
        faixa["acumulado_receita"] = acumulado_receita
        faixa["parte"] = _pct(faixa["noites"], noites_total)
        faixa["parte_acumulada"] = _pct(acumulado_noites, noites_total)

    antecipadas = sum(f["noites"] for f in faixas if f["de"] >= 30)
    return {
        "faixas": faixas, "noites": noites_total, "receita": receita_total,
        "antecedencia_media": (Decimal(soma_antecedencia) / noites_total).quantize(
            Decimal("0.1")) if noites_total else Decimal("0.0"),
        "parte_antecipada": _pct(antecipadas, noites_total),
        "parte_ultima_hora": _pct(faixas[-1]["noites"], noites_total),
    }


# ──────────────── 4. Custo de distribuição por canal ────────────────

def custo_distribuicao(inicio, fim) -> dict:
    """Receita bruta, custo de venda estimado e receita líquida por canal.

    Base = reservas **firmes** com noites no período: pré-reserva ainda pode cair, e
    custo de canal sobre venda que não aconteceu enganaria a conta. Os percentuais são
    parâmetro da casa (`ConfiguracaoReservas`, editável na Tabela de preços) — comissão
    de OTA, taxa do gateway no site, zero no que vem direto.

    A comissão de agência/empresa é **estimativa informativa**, calculada pela
    `comissao_padrao` do cadastro e mostrada à parte: a regra contábil dela (quando
    nasce, se é desconto na diária ou despesa) ainda é decisão do dono, então nada é
    lançado no Financeiro nem somado ao custo de canal.
    """
    from apps.nucleo.models import ConfiguracaoReservas

    percentuais = ConfiguracaoReservas.carregar().custo_por_canal()
    canais = _canais()
    agencias: dict = {}

    reservas = (_pernoites(inicio, fim, FIRMES)
                .select_related("titular__agencia"))
    for r in reservas:
        noites = noites_vendidas(r, inicio, fim)
        if not noites:
            continue
        valor = sum((v for _, v in noites), ZERO)
        canais[r.canal]["noites"] += len(noites)
        canais[r.canal]["receita"] += valor
        agencia = getattr(r.titular, "agencia", None) if r.titular_id else None
        if r.faturamento != Reserva.Faturamento.PARTICULAR and agencia:
            linha = agencias.setdefault(
                r.titular_id,
                {"rotulo": r.titular.nome, "pct": agencia.comissao_padrao,
                 "noites": 0, "receita": ZERO},
            )
            linha["noites"] += len(noites)
            linha["receita"] += valor

    labels = dict(Reserva.Canal.choices)
    linhas, bruta, custo = [], ZERO, ZERO
    for canal, v in canais.items():
        pct = percentuais.get(canal, ZERO)
        custo_canal = (v["receita"] * pct / 100).quantize(CENTAVO)
        linhas.append({
            "rotulo": labels[canal], "noites": v["noites"], "receita": v["receita"],
            "pct": pct, "custo": custo_canal, "liquida": v["receita"] - custo_canal,
        })
        bruta += v["receita"]
        custo += custo_canal

    comissoes = []
    comissao_total = ZERO
    for linha in sorted(agencias.values(), key=lambda a: -a["receita"]):
        estimada = (linha["receita"] * linha["pct"] / 100).quantize(CENTAVO)
        comissoes.append({**linha, "comissao": estimada})
        comissao_total += estimada

    return {
        "linhas": linhas, "bruta": bruta, "custo": custo, "liquida": bruta - custo,
        "custo_medio": _pct(custo, bruta) if bruta else Decimal("0.0"),
        "comissoes": comissoes, "comissao_total": comissao_total,
    }
