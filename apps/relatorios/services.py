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


def _n(v):
    """Contagem com separador de milhar ("1.234") — número não é dinheiro."""
    from apps.nucleo.templatetags.moeda import milhar
    return milhar(v or 0)


def _dec(v):
    """Decimal em pt-BR sem zeros à direita ("34,5", "12")."""
    from apps.nucleo.formatos import pct_br
    return pct_br(v or 0)


def _pc(v):
    """Percentual em pt-BR ("64,9%")."""
    return f"{_dec(v)}%"


def _parte(parte, total):
    """Quanto `parte` representa de `total`, em percentual."""
    if not total:
        return Decimal("0")
    return (Decimal(parte) / Decimal(total) * 100).quantize(Decimal("0.1"))


TRACO = "—"   # célula sem sentido naquela linha (não é zero)


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


# ─────────────── Receita vendida (olhando para a frente) ───────────────
#
# Produção e ocupação contam o que já aconteceu. Estes quatro contam a VENDA: o que
# está na carteira para datas que ainda vão chegar, o que entrou e saiu nos últimos
# dias, com quanta antecedência o mês vendeu e quanto custa cada canal. O cálculo é do
# dono do dado (`reservas.services`); aqui é só a apresentação.


def rel_carteira(inicio, fim):
    """Carteira (OTB) por data de estadia — dia a dia, por canal e por faturamento."""
    from apps.reservas.services import carteira
    c = carteira(inicio, fim)

    linhas = [[
        lin["rotulo"], _n(lin["firmes"]), _pc(lin["ocupacao"]),
        _rs(lin["receita_firme"]),
        _n(lin["provisorias"]) if lin["provisorias"] else TRACO,
        _rs(lin["receita_provisoria"]) if lin["provisorias"] else TRACO,
    ] for lin in c["linhas"]]
    linhas.append([
        "Total do período", _n(c["noites_firmes"]), _pc(c["ocupacao"]),
        _rs(c["receita_firme"]), _n(c["noites_provisorias"]),
        _rs(c["receita_provisoria"]),
    ])
    # Os cortes só olham o firme — pré-reserva ainda pode cair, e creditá-la a um canal
    # faria o canal parecer ter vendido o que não vendeu. A fatia de cada um vai no
    # rótulo, não na coluna de ocupação: o denominador é outro (noites vendidas, não
    # quartos disponíveis) e dois sentidos na mesma coluna confundem.
    for grupo, rotulo in (("por_canal", "Canal"), ("por_faturamento", "Faturamento")):
        for item in c[grupo]:
            if not item["noites"]:
                continue
            fatia = _pc(_parte(item["noites"], c["noites_firmes"]))
            linhas.append([f"{rotulo}: {item['rotulo']} · {fatia} das noites",
                           _n(item["noites"]), TRACO,
                           _rs(item["receita"]), TRACO, TRACO])

    du = c["day_use"]
    return {
        "kpis": [
            ("Quartos-noite vendidos", f"{_n(c['noites_firmes'])} de {_n(c['disponiveis'])}"),
            ("Ocupação vendida",
             f"{_pc(c['ocupacao'])} · {_pc(c['ocupacao_total'])} com a pré-reserva"),
            ("Receita de hospedagem", _rs(c["receita_firme"])),
            ("Diária média (ADR)", _rs(c["adr"])),
            ("Pré-reserva (pode cair)",
             f"{_n(c['noites_provisorias'])} noites · {_rs(c['receita_provisoria'])}"),
            ("Dia na Pousada (à parte)",
             f"{_n(du['reservas'])} reservas · {_rs(du['receita'])}"),
        ],
        "colunas": ["Data da estadia", "Quartos-noite", "Ocupação", "Receita",
                    "Pré-reserva (noites)", "Pré-reserva (R$)"],
        "linhas": linhas,
        "nota": (
            f"Carteira = o que segura quarto: confirmada, hospedada e saída (firme) + "
            f"pré-reserva dentro da retenção, mostrada à parte. Cancelada, no-show e "
            f"orçamento ficam fora. A noite entra no dia em que é dormida (estadia na "
            f"virada do mês conta em cada mês o que é dele). Ocupação sobre os "
            f"{c['quartos']} quartos de pernoite; o Dia na Pousada não é pernoite e "
            f"aparece só no indicador à parte. Pré-reserva não entra nos cortes por "
            f"canal e faturamento. É o que foi VENDIDO (preço da reserva); o fechamento "
            f"do mês que passou é o relatório de Produção."
        ),
    }


def rel_pickup(inicio, fim, janela=7):
    """Pickup: o que entrou e saiu da carteira do período nos últimos N dias."""
    from apps.reservas.services import pickup
    p = pickup(inicio, fim, janela=janela)

    def linha(rotulo, v):
        return [rotulo,
                _n(v["entrou_noites"]), _rs(v["entrou_receita"]),
                _n(v["saiu_noites"]), _rs(v["saiu_receita"]),
                _n(v["liquido_noites"]), _rs(v["liquido_receita"])]

    linhas = [linha(lin["rotulo"], lin) for lin in p["linhas"]]
    linhas.append(["Total da janela",
                   _n(p["entrou"]["noites"]), _rs(p["entrou"]["receita"]),
                   _n(p["saiu"]["noites"]), _rs(p["saiu"]["receita"]),
                   _n(p["liquido"]["noites"]), _rs(p["liquido"]["receita"])])
    linhas += [linha(f"Canal: {c['rotulo']}", c) for c in p["por_canal"]
               if c["entrou_noites"] or c["saiu_noites"]]

    return {
        "kpis": [
            (f"Janela (últimos {janela} dias)",
             f"{p['desde']:%d/%m} a {p['ate']:%d/%m}"),
            ("Entrou (quartos-noite)", _n(p["entrou"]["noites"])),
            ("Entrou (receita)", _rs(p["entrou"]["receita"])),
            ("Saiu (quartos-noite)", _n(p["saiu"]["noites"])),
            ("Saiu (receita)", _rs(p["saiu"]["receita"])),
            ("Pickup líquido",
             f"{_n(p['liquido']['noites'])} noites · {_rs(p['liquido']['receita'])}"),
        ],
        "colunas": ["Dia da venda", "Entrou (noites)", "Entrou (R$)",
                    "Saiu (noites)", "Saiu (R$)", "Líquido (noites)", "Líquido (R$)"],
        "linhas": linhas,
        "nota": (
            "Só o movimento das estadias do período escolhido: entrou = reserva vendida "
            "na janela (data da venda); saiu = reserva que deixou a carteira na janela "
            "(cancelamento, retenção expirada ou no-show). Pickup líquido negativo = o "
            "mês andou para trás. A data de saída passou a ser gravada nesta versão: "
            "cancelamento mais antigo não aparece na coluna 'Saiu'."
        ),
    }


def rel_ritmo(inicio, fim):
    """Ritmo de vendas: curva acumulada da carteira por antecedência da venda."""
    from apps.reservas.services import ritmo_de_vendas
    r = ritmo_de_vendas(inicio, fim)
    linhas = [[f["rotulo"], _n(f["noites"]), _pc(f["parte"]), _rs(f["receita"]),
               _n(f["acumulado_noites"]), _pc(f["parte_acumulada"]),
               _rs(f["acumulado_receita"])] for f in r["faixas"]]
    return {
        "kpis": [
            ("Quartos-noite na carteira", _n(r["noites"])),
            ("Receita na carteira", _rs(r["receita"])),
            ("Antecedência média", f"{_dec(r['antecedencia_media'])} dias"),
            ("Vendido com 30+ dias", _pc(r["parte_antecipada"])),
            ("Última hora (até 6 dias)", _pc(r["parte_ultima_hora"])),
        ],
        "colunas": ["Antecedência da venda", "Quartos-noite", "% do total", "Receita",
                    "Acumulado (noites)", "Acumulado (%)", "Receita acumulada"],
        "linhas": linhas,
        "nota": (
            "Antecedência = dias entre a venda e a data de CHEGADA da reserva (a decisão "
            "de compra é uma só, a da estadia). A curva acumula de cima para baixo: a "
            "linha '30 a 59 dias' já traz dentro dela o que foi vendido com 60+ e 90+. "
            "Comparada com a de um mês que já fechou, diz se este está adiantado ou "
            "atrasado. Carteira = firme + pré-reserva na retenção."
        ),
    }


def rel_distribuicao(inicio, fim):
    """Custo de distribuição: bruta × custo de venda × líquida, por canal."""
    from apps.reservas.services import custo_distribuicao
    d = custo_distribuicao(inicio, fim)
    linhas = [[lin["rotulo"], _n(lin["noites"]), _rs(lin["receita"]), _pc(lin["pct"]),
               _rs(lin["custo"]), _rs(lin["liquida"])] for lin in d["linhas"]]
    linhas.append(["Total", _n(sum(lin["noites"] for lin in d["linhas"])),
                   _rs(d["bruta"]), _pc(d["custo_medio"]),
                   _rs(d["custo"]), _rs(d["liquida"])])
    # Abaixo do total de propósito: a comissão é outra conta, não soma com a de canal.
    linhas += [[f"Comissão estimada: {c['rotulo']}", _n(c["noites"]), _rs(c["receita"]),
                _pc(c["pct"]), _rs(c["comissao"]), TRACO] for c in d["comissoes"]]
    return {
        "kpis": [
            ("Receita bruta (firme)", _rs(d["bruta"])),
            ("Custo de venda estimado", _rs(d["custo"])),
            ("Receita líquida", _rs(d["liquida"])),
            ("Custo médio", _pc(d["custo_medio"])),
            ("Comissão de agência (estimativa)", _rs(d["comissao_total"])),
        ],
        "colunas": ["Canal", "Quartos-noite", "Receita bruta", "Custo %",
                    "Custo estimado", "Receita líquida"],
        "linhas": linhas,
        "nota": (
            "Estimativa gerencial, não lançamento: os percentuais por canal são "
            "parâmetro da casa (Cadastros → Tabela de preços → Custo de vender por "
            "canal). Base = reservas firmes com noites no período (pré-reserva pode "
            "cair). As linhas de agência/empresa usam a comissão do cadastro da agência "
            "e ficam FORA do total de custo — como a comissão entra na contabilidade "
            "ainda é decisão da pousada, então nada é lançado no Financeiro."
        ),
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
# `periodo` = "proximo_mes" abre no mês que vem (relatório que olha para a frente).
# `controles` = controle próprio além do período (ver CONTROLES).
RELATORIOS = {
    "producao": {"nome": "Produção / Receita", "grupo": "Consolidados",
                 "builder": rel_producao, "modulo": Modulo.RESERVAS},
    "ocupacao": {"nome": "Ocupação & Diárias (ADR/RevPAR)", "grupo": "Consolidados",
                 "builder": rel_ocupacao, "modulo": Modulo.RESERVAS},
    "carteira": {"nome": "Carteira de reservas (OTB)", "grupo": "Consolidados",
                 "builder": rel_carteira, "modulo": Modulo.RESERVAS,
                 "periodo": "proximo_mes"},
    "pickup": {"nome": "Pickup — entrou × saiu", "grupo": "Consolidados",
               "builder": rel_pickup, "modulo": Modulo.RESERVAS,
               "periodo": "proximo_mes", "controles": ["janela"]},
    "ritmo": {"nome": "Ritmo de vendas (antecedência)", "grupo": "Consolidados",
              "builder": rel_ritmo, "modulo": Modulo.RESERVAS,
              "periodo": "proximo_mes"},
    "distribuicao": {"nome": "Custo de distribuição por canal", "grupo": "Consolidados",
                     "builder": rel_distribuicao, "modulo": Modulo.RESERVAS},
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


# ───────────────── Controles próprios de um relatório ─────────────────
#
# Alguns relatórios têm um botão a mais que o período (a janela do pickup). O registro
# só declara o nome; a view lê do GET, valida contra as escolhas e passa por kwarg ao
# builder — o template desenha o seletor e o CSV/impressão levam a escolha junto.

CONTROLES = {
    "janela": {
        "rotulo": "Entrou nos últimos",
        "escolhas": [(7, "7 dias"), (14, "14 dias"), (30, "30 dias")],
        "padrao": 7,
    },
}


def controles(request, chave) -> list:
    """`[{nome, rotulo, escolhas, valor}]` do relatório, com a escolha já resolvida."""
    resolvidos = []
    for nome in RELATORIOS[chave].get("controles", ()):
        spec = CONTROLES[nome]
        validas = [v for v, _ in spec["escolhas"]]
        try:
            valor = type(spec["padrao"])(request.GET.get(nome))
        except (TypeError, ValueError):
            valor = spec["padrao"]
        resolvidos.append({
            "nome": nome, "rotulo": spec["rotulo"], "escolhas": spec["escolhas"],
            "valor": valor if valor in validas else spec["padrao"],
        })
    return resolvidos
