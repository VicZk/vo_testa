"""
Relatórios do CRM (ESPECIFICACAO §4.6). Framework simples: cada relatório é uma
função que recebe (início, fim) e devolve `{kpis, colunas, linhas}`; uma view
genérica renderiza/exporta. **Read-only** e desacoplado — consome services dos
módulos e models do núcleo, nunca models internos de outros módulos.

Dois grupos: **Consolidados** (cruzam módulos) e **Por módulo** (individuais).
"""
from decimal import Decimal

from django.db.models import Sum

from apps.nucleo.modulos import Modulo

# Seletor de período compartilhado (mês/ano) — mesmo controle da Trilha de auditoria.
from apps.nucleo.periodos import periodo, selecao_periodo  # noqa: F401


def _rs(v):
    """Dinheiro em pt-BR pelo formatador único do sistema ("R$ 1.234,56")."""
    from apps.nucleo.templatetags.moeda import intcomma_brl
    return intcomma_brl(v or 0)


def _minutos(n):
    """Duração em minutos como texto curto ("48 min", "1 h 12 min"). None = sem medida
    — e aí a célula diz isso, em vez de mostrar um zero que mentiria."""
    if n is None:
        return "—"
    return f"{n // 60} h {n % 60:02d} min" if n >= 60 else f"{n} min"


# ───────────────────────── Consolidados (cruzados) ─────────────────────────

def _movimentos_por_forma(inicio, fim):
    from apps.nucleo.models import MovimentoCaixa
    return (
        MovimentoCaixa.objects
        .filter(criado_em__date__range=(inicio, fim),
                tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("forma_pagamento__nome")
        .annotate(total=Sum("valor")).order_by("-total")
    )


def rel_producao(inicio, fim):
    from apps.reservas.services import relatorio_producao
    p = relatorio_producao(inicio, fim)
    linhas = [[m["forma_pagamento__nome"] or "—", _rs(m["total"])]
              for m in _movimentos_por_forma(inicio, fim)]
    return {
        "kpis": [("Serviço", _rs(p["servico"])), ("Consumo", _rs(p["consumo"])),
                 ("Receita total", _rs(p["total"]))],
        "colunas": ["Recebido por forma de pagamento", "Valor"],
        "linhas": linhas,
    }


def rel_ocupacao(inicio, fim):
    from apps.reservas.services import relatorio_ocupacao
    o = relatorio_ocupacao(inicio, fim)
    linhas = [[tipo, str(n)] for tipo, n in sorted(o["por_tipo"].items())]
    return {
        "kpis": [("Ocupação", f"{o['taxa']}%"), ("Diária média (ADR)", _rs(o["adr"])),
                 ("RevPAR", _rs(o["revpar"])),
                 ("Diárias-quarto", f"{o['ocupadas']}/{o['disponiveis']}")],
        "colunas": ["Tipo de quarto", "Diárias-quarto ocupadas"],
        "linhas": linhas,
    }


def rel_caixa(inicio, fim):
    from apps.nucleo.models import MovimentoCaixa
    movs = MovimentoCaixa.objects.filter(criado_em__date__range=(inicio, fim))
    por_forma = list(
        movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("forma_pagamento__nome").annotate(total=Sum("valor")).order_by("-total")
    )
    recebido = sum((m["total"] for m in por_forma), Decimal("0"))
    por_operador = (
        movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        .values("sessao__operador__username").annotate(total=Sum("valor")).order_by("-total")
    )
    linhas = [[m["forma_pagamento__nome"] or "—", _rs(m["total"])] for m in por_forma]
    linhas += [[f"Operador: {m['sessao__operador__username']}", _rs(m["total"])]
               for m in por_operador]
    return {
        "kpis": [("Recebido no período", _rs(recebido)),
                 ("Nº de recebimentos", str(movs.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO).count()))],
        "colunas": ["Forma / operador", "Valor"],
        "linhas": linhas,
    }


def rel_faturamento_modulos(inicio, fim):
    """
    Faturamento por setor, separando ONDE o dinheiro é recebido:
      - "no caixa do setor" = venda paga na hora, entra na gaveta do próprio setor;
      - "lançado no quarto" = foi pro folio; quem recebe é a RECEPÇÃO (caixa Reservas).
    É faturamento por COMPETÊNCIA (o que foi vendido no período, por timestamp de cada
    setor) — uma visão gerencial, não a batida exata da gaveta da recepção (essa se faz
    pelo caixa/conciliação). A coluna "lançado no quarto" aproxima o que a recepção
    coleta de outros setores (+ diárias), mas não é igualdade contábil ao centavo.
    """
    from apps.nucleo.models import modulo_ativo

    linhas = []
    tot_caixa = tot_quarto = Decimal("0")

    def add(setor, no_caixa, no_quarto):
        nonlocal tot_caixa, tot_quarto
        linhas.append([setor, _rs(no_caixa), _rs(no_quarto), _rs(no_caixa + no_quarto)])
        tot_caixa += no_caixa
        tot_quarto += no_quarto

    # Consome o service público de cada módulo (desacoplado — sem importar models
    # internos de outros apps, como o resto do Relatórios).
    # Hospedagem — as diárias são sempre folio (recebidas pela recepção).
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import diarias_periodo
        add("Hospedagem (diárias)", Decimal("0"), diarias_periodo(inicio, fim))

    if modulo_ativo(Modulo.LOJA):
        from apps.loja.services import faturamento_periodo as loja_fat
        f = loja_fat(inicio, fim)
        add("Loja", f["caixa"], f["quarto"])

    if modulo_ativo(Modulo.RESTAURANTE):
        from apps.restaurante.services import faturamento_periodo as rest_fat
        f = rest_fat(inicio, fim)
        add("Restaurante", f["caixa"], f["quarto"])

    if modulo_ativo(Modulo.LAVANDERIA):
        from apps.lavanderia.services import faturamento_periodo as lav_fat
        f = lav_fat(inicio, fim)
        add("Lavanderia", f["caixa"], f["quarto"])

    return {
        "kpis": [
            ("Faturamento total", _rs(tot_caixa + tot_quarto)),
            ("Recebido na gaveta do setor", _rs(tot_caixa)),
            ("Lançado nos quartos (recepção recebe)", _rs(tot_quarto)),
        ],
        "colunas": ["Setor", "No caixa do setor", "Lançado no quarto", "Total vendido"],
        "linhas": linhas,
    }


# ───────────────────────── Por módulo (individuais) ─────────────────────────

def rel_estoque_consumo(inicio, fim):
    """Curva de consumo (ABC) — saídas por produto no período."""
    from apps.nucleo.models import MovimentoEstoque
    saidas = (
        MovimentoEstoque.objects
        .filter(criado_em__date__range=(inicio, fim), quantidade__lt=0)
        .values("produto__nome").annotate(qtd=Sum("quantidade")).order_by("qtd")
    )
    linhas = [[s["produto__nome"], f"{-s['qtd']:.0f}"] for s in saidas]
    total = sum((-s["qtd"] for s in saidas), Decimal("0"))
    return {
        "kpis": [("Itens consumidos (qtd)", f"{total:.0f}"),
                 ("Produtos movimentados", str(len(linhas)))],
        "colunas": ["Produto", "Qtd. consumida"],
        "linhas": linhas,
    }


def rel_comercial(inicio, fim):
    """Funil de vendas — oportunidades criadas, conversão e funil em aberto por etapa."""
    from apps.comercial.services import relatorio_funil
    f = relatorio_funil(inicio, fim)
    linhas = [[e["etapa__nome"], str(e["n"]), _rs(e["valor"])] for e in f["por_etapa"]]
    return {
        "kpis": [("Oportunidades criadas", str(f["total"])),
                 ("Ganhas", str(f["ganhas"])), ("Perdidas", str(f["perdidas"])),
                 ("Taxa de conversão", f"{f['conversao']}%"),
                 ("Valor ganho", _rs(f["valor_ganho"]))],
        "colunas": ["Etapa (em aberto)", "Qtd.", "Valor no funil"],
        "linhas": linhas,
    }


def rel_governanca_faxinas(inicio, fim):
    """Produtividade da governança: quem entregou quantas faxinas, de que tipo, e
    quanto tempo levou entre iniciar e concluir."""
    from apps.governanca.services import relatorio_faxinas
    g = relatorio_faxinas(inicio, fim)
    colunas = ["Camareira", "Concluídas"] + [label for _, label in g["tipos"]] + ["Tempo médio"]
    linhas = [
        [ln["camareira"], str(ln["n"])]
        + [str(ln["tipos"].get(cod, 0)) for cod, _ in g["tipos"]]
        + [_minutos(ln["minutos"])]
        for ln in g["linhas"]
    ]
    return {
        "kpis": [("Faxinas concluídas", str(g["total"])),
                 ("Tempo médio", _minutos(g["minutos_medios"])),
                 ("Com tempo medido", str(g["cronometradas"])),
                 ("Camareiras", str(len(g["linhas"])))],
        "colunas": colunas,
        "linhas": linhas,
    }


def rel_governanca_inspecao(inicio, fim):
    """Qualidade da entrega: faxinas aprovadas na inspeção × devolvidas para refazer."""
    from apps.governanca.services import relatorio_inspecoes
    g = relatorio_inspecoes(inicio, fim)
    linhas = [[ln["camareira"], str(ln["inspecionadas"]), str(ln["reprovadas"]),
               f"{ln['retrabalho']}%".replace(".", ",")]
              for ln in g["linhas"]]
    linhas += [[f"Motivo: {motivo}", "", str(n), ""] for motivo, n in g["motivos"]]
    return {
        "kpis": [("Aprovadas na inspeção", str(g["inspecionadas"])),
                 ("Reprovadas (refazer)", str(g["reprovadas"])),
                 ("Retrabalho", f"{g['retrabalho']}%".replace(".", ",")),
                 ("Entregues sem inspeção", str(g["sem_inspecao"]))],
        "colunas": ["Camareira", "Aprovadas", "Reprovadas", "Retrabalho"],
        "linhas": linhas,
    }


def rel_governanca_discrepancias(inicio, fim):
    """Discrepância da ronda por dia: onde a conferência da camareira não bateu com o
    sistema. Skip = hóspede foi embora sem baixa (conta aberta); sleeper = tem gente
    num quarto que o sistema dá como livre (check-in não lançado)."""
    from apps.governanca.models import ConferenciaOcupacao
    from apps.governanca.services import relatorio_discrepancias
    g = relatorio_discrepancias(inicio, fim)
    rotulos = dict(ConferenciaOcupacao.Divergencia.choices)
    tipos = list(ConferenciaOcupacao.DIVERGENTES)
    linhas = [
        [f"{d['dia']:%d/%m/%Y}", str(d["conferencias"]), str(d["divergencias"])]
        + [str(d[cod]) for cod in tipos]
        for d in g["linhas"]
    ]
    return {
        "kpis": [("Divergências no período", str(g["divergencias"])),
                 ("Conferências registradas", str(g["conferencias"])),
                 ("Dias com divergência", str(g["dias_com_divergencia"]))]
                + [(rotulos[cod], str(g["por_tipo"][cod])) for cod in tipos],
        "colunas": ["Dia", "Conferências", "Divergências"] + [rotulos[c] for c in tipos],
        "linhas": linhas,
    }


def rel_reservas(inicio, fim):
    from apps.reservas.models import Reserva
    from apps.reservas.services import relatorio_reservas
    r = relatorio_reservas(inicio, fim)
    canais = dict(Reserva.Canal.choices)
    status = dict(Reserva.Status.choices)
    linhas = [["Canal: " + canais.get(k, k), str(v)] for k, v in r["por_canal"].items()]
    linhas += [["Status: " + status.get(k, k), str(v)] for k, v in r["por_status"].items()]
    return {
        "kpis": [("Reservas criadas", str(r["total"]))],
        "colunas": ["Categoria", "Quantidade"],
        "linhas": linhas,
    }


# Registro central. grupo = "Consolidados" | "Por módulo". `modulo` = exige ativo.
RELATORIOS = {
    "producao": {"nome": "Produção / Receita", "grupo": "Consolidados",
                 "builder": rel_producao, "modulo": Modulo.RESERVAS},
    "ocupacao": {"nome": "Ocupação & Diárias (ADR/RevPAR)", "grupo": "Consolidados",
                 "builder": rel_ocupacao, "modulo": Modulo.RESERVAS},
    "caixa": {"nome": "Caixa / Financeiro", "grupo": "Consolidados",
              "builder": rel_caixa, "modulo": None},
    "faturamento_modulos": {"nome": "Faturamento por setor (caixa × quarto)",
                            "grupo": "Consolidados",
                            "builder": rel_faturamento_modulos, "modulo": None},
    "estoque": {"nome": "Estoque — consumo (curva ABC)", "grupo": "Por módulo",
                "builder": rel_estoque_consumo, "modulo": Modulo.ESTOQUE},
    "reservas": {"nome": "Reservas — canal e status", "grupo": "Por módulo",
                 "builder": rel_reservas, "modulo": Modulo.RESERVAS},
    "governanca_faxinas": {"nome": "Governança — faxinas por camareira",
                           "grupo": "Por módulo",
                           "builder": rel_governanca_faxinas,
                           "modulo": Modulo.GOVERNANCA},
    "governanca_inspecao": {"nome": "Governança — inspeção e retrabalho",
                            "grupo": "Por módulo",
                            "builder": rel_governanca_inspecao,
                            "modulo": Modulo.GOVERNANCA},
    "governanca_discrepancias": {"nome": "Governança — discrepâncias da ronda",
                                 "grupo": "Por módulo",
                                 "builder": rel_governanca_discrepancias,
                                 "modulo": Modulo.GOVERNANCA},
    "comercial": {"nome": "Comercial — funil e conversão", "grupo": "Por módulo",
                  "builder": rel_comercial, "modulo": Modulo.COMERCIAL},
}


def disponiveis():
    """Relatórios cujo módulo está ativo (ou sem dependência), agrupados."""
    from apps.nucleo.models import modulo_ativo
    grupos = {}
    for chave, r in RELATORIOS.items():
        if r["modulo"] and not modulo_ativo(r["modulo"]):
            continue
        grupos.setdefault(r["grupo"], []).append({"chave": chave, "nome": r["nome"]})
    return grupos
