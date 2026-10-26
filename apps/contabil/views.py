import csv
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from apps.nucleo.export import celula, resposta_csv
from apps.nucleo.forms import ReaisInput
from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.periodos import MESES_PT, _mes_ano, selecao_periodo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo

from . import relatorios
from .forms import FechamentoMensalForm
from .models import ContaContabil, FechamentoMensal
from .services import plano_de_contas


def _periodo(request):
    mes, ano = _mes_ano(request)
    return ano, mes


# Abas do painel, na ordem da tela. `?aba=` abre direto numa delas (o JS mantém o
# parâmetro na URL ao trocar, para a troca de mês e o recarregar não voltarem à DRE).
ABAS = (
    ("dre", "DRE gerencial"), ("fluxo", "Fluxo de caixa"), ("plano", "Plano de contas"),
    ("depara", "A classificar"), ("fechar", "Fechar o mês"), ("export", "Exportar"),
)


def _porcento(valor: Decimal) -> str:
    return f"{valor:.1f}%".replace(".", ",")


def _fatia(valor: Decimal, base: Decimal) -> str:
    """Peso da linha na receita bruta (análise vertical); sem receita, "—"."""
    return _porcento(valor / base * 100) if base > 0 else "—"


def _variacao(atual: Decimal, anterior: Decimal) -> str | None:
    """"↑ 16,3%" sobre o mês anterior; sem base positiva para comparar, None."""
    if anterior <= 0:
        return None
    pct = (atual - anterior) / anterior * 100
    seta = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
    return f"{seta} {_porcento(abs(pct))}"


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def painel(request):
    ano, mes = _periodo(request)
    ano_ant, mes_ant = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    dados_dre = relatorios.dre(ano, mes)
    dre_ant = relatorios.dre(ano_ant, mes_ant)
    # As duas DREs saem da mesma lista de linhas, na mesma ordem.
    linhas_dre = [
        {"rotulo": rotulo, "estilo": estilo, "valor": valor, "anterior": anterior,
         "fatia": _fatia(valor, dados_dre["receita_bruta"])}
        for (_, rotulo, valor, estilo), (_, _, anterior, _) in zip(
            dados_dre["linhas"], dre_ant["linhas"], strict=True)
    ]
    variacao = {chave: _variacao(dados_dre[chave], dre_ant[chave])
                for chave in ("receita_liquida", "lucro_bruto", "despesas", "resultado")}
    fluxo = relatorios.fluxo_caixa(ano, mes)
    orf = relatorios.orfaos()
    totais = relatorios._totais_por_conta(ano, mes)
    contas = []
    for c in plano_de_contas():
        contas.append({"conta": c, "total": totais.get(c.classificacao, Decimal("0.00"))})
    servicos = totais.get("3.1.01.03", Decimal("0.00"))
    mercadorias = totais.get("3.1.01.01", Decimal("0.00"))
    natureza = {"servicos": servicos, "mercadorias": mercadorias,
                "servicos_fatia": _fatia(servicos, servicos + mercadorias),
                "mercadorias_fatia": _fatia(mercadorias, servicos + mercadorias)}
    aba = request.GET.get("aba")
    if aba not in dict(ABAS):
        # A única lista paginada é a dos lançamentos a classificar.
        aba = "depara" if "pagina" in request.GET else "dre"
    fechamento = FechamentoMensal.objects.filter(ano=ano, mes=mes).first()
    from apps.nucleo.models.cadastros import folha_base
    folha = folha_base()
    # Sem fechamento ainda, a folha nasce sugerida pelo cadastro (editável).
    form_fechamento = FechamentoMensalForm(
        instance=fechamento, initial=None if fechamento else {"folha": folha["total"]})

    # Receita futura contratada (reservas confirmadas ainda não hospedadas).
    from apps.nucleo.models import modulo_ativo
    futura ={"total": Decimal("0.00"), "qtd": 0, "por_mes": []}
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import receita_contratada_futura
        futura = receita_contratada_futura()
        for linha in futura["por_mes"]:
            linha["rotulo"] = f"{MESES_PT[linha['mes']]}/{linha['ano']}"

    donut = [float(servicos), float(mercadorias)]
    waterfall = {
        "labels": ["Rec. bruta", "(−) Deduções", "(−) Custos", "(−) Despesas", "Resultado"],
        "receita_bruta": float(dados_dre["receita_bruta"]),
        "receita_liquida": float(dados_dre["receita_liquida"]),
        "lucro_bruto": float(dados_dre["lucro_bruto"]),
        "resultado": float(dados_dre["resultado"]),
        "deducoes": float(dados_dre["receita_bruta"] - dados_dre["receita_liquida"]),
        "custos": float(dados_dre["receita_liquida"] - dados_dre["lucro_bruto"]),
        "despesas": float(dados_dre["lucro_bruto"] - dados_dre["resultado"]),
    }
    return render(request, "contabil/painel.html", {
        "ano": ano, "mes": mes, "dre": dados_dre, "fluxo": fluxo,
        "orfaos": orf, "contas": contas, "fechamento": fechamento,
        "donut": donut, "waterfall": waterfall, "folha_cadastro": folha,
        "folha_cadastro_campo": ReaisInput().format_value(folha["total"]),
        "form_fechamento": form_fechamento, "futura": futura,
        "abas": ABAS, "aba": aba, "linhas_dre": linhas_dre, "variacao": variacao,
        "natureza": natureza, "dias": relatorios.fluxo_diario(ano, mes),
        "titulos": fluxo["titulos"],
        "pagina_orfaos": paginar(request, orf["lancamentos"], por_pagina=50),
        "nome_mes": MESES_PT[mes], "nome_mes_ant": MESES_PT[mes_ant], "ano_ant": ano_ant,
        **selecao_periodo(request),
    })


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def fechar(request):
    if request.method != "POST":
        return redirect(reverse("contabil:painel"))

    hoje = timezone.localdate()

    def _int(campo, padrao):
        try:
            return int(request.POST.get(campo) or padrao)
        except (TypeError, ValueError):
            return padrao

    ano = _int("ano", hoje.year)
    mes = _int("mes", hoje.month)
    voltar = f"{reverse('contabil:painel')}?ano={ano}&mes={mes}&aba=fechar"
    if not (1 <= mes <= 12 and 2000 <= ano <= 2100):
        messages.error(request, "Mês ou ano inválido para o fechamento.")
        return redirect(reverse("contabil:painel"))

    with transaction.atomic():
        from apps.nucleo.sistema import travar

        fm, _ = FechamentoMensal.objects.get_or_create(ano=ano, mes=mes)
        fm = travar(fm)  # dois envios do mesmo mês: um espera o outro
        form = FechamentoMensalForm(request.POST, instance=fm)
        if not form.is_valid():
            # Nada é gravado: o formulário (data-preservar-erros) mostra o erro e
            # mantém o que foi digitado; sem JavaScript, volta com a mensagem.
            transaction.set_rollback(True)
            messages.error(request, erros_do_formulario(form))
            return redirect(voltar)
        fm = form.save(commit=False)
        fm.fechado_por = request.user
        fm.save()
        fm.aplicar()
    messages.success(request, f"Fechamento de {mes:02d}/{ano} aplicado à DRE.")
    return redirect(voltar)


@csrf_exempt
def cron_capturar(request):
    """
    Cron financeiro (a DRE se atualiza sozinha). Sem login: autenticado por token
    compartilhado (`CONTABIL_CRON_TOKEN`), para um agendador externo (GitHub Action /
    Railway cron / pinger) chamar. Idempotente — pode rodar quantas vezes quiser.
    Faz: (1) capturas automáticas do mês corrente (+ mês anterior nos primeiros dias,
    p/ fechar a competência que virou); (2) geração das contas recorrentes do mês
    corrente (contas fixas; não retroage).
    """
    token = getattr(settings, "CONTABIL_CRON_TOKEN", "")
    if not token:
        raise Http404("Cron de capturas desativado (sem CONTABIL_CRON_TOKEN).")
    # Só pelo cabeçalho: parâmetro de URL fica gravado em log de proxy e de acesso.
    if not constant_time_compare(request.headers.get("X-Cron-Token", ""), token):
        return HttpResponseForbidden("token inválido")

    from .capturas import rotina_diaria

    return JsonResponse({"ok": True, **rotina_diaria()})


EXPORTS = {"resumo", "lancamentos", "plano"}
# `LancamentoFinanceiro.origem` em palavras (o código fica no banco).
ORIGENS = {
    "manual": "Manual", "receita": "Receita da competência", "desconto": "Desconto na conta",
    "taxa_cartao": "Taxa de cartão", "comissao_ota": "Comissão de canal (OTA)", "cmv": "CMV",
    "consumo_estoque": "Consumo interno", "perda_estoque": "Perda de estoque",
    "fechamento": "Fechamento do mês",
}


@never_cache
@requer_modulo(Modulo.CONTABIL)
@requer_gerencia
def export(request, tipo):
    if tipo not in EXPORTS:
        raise Http404("Export indisponível.")
    ano, mes = _periodo(request)
    resp = resposta_csv(f"contabil_{tipo}_{ano:04d}-{mes:02d}.csv")
    w = csv.writer(resp, delimiter=";")

    if tipo == "plano":
        w.writerow(["Código do contador", "Classificação", "Nome", "Grupo", "Tipo"])
        for c in plano_de_contas():
            w.writerow([celula(x) for x in (
                c.codigo_contador, c.classificacao, c.nome,
                c.get_grupo_display(), c.get_tipo_display())])
    elif tipo == "resumo":
        totais = relatorios._totais_por_conta(ano, mes)
        w.writerow(["Código do contador", "Classificação", "Nome", "Saldo do mês (R$)"])
        for c in plano_de_contas().filter(tipo=ContaContabil.Tipo.ANALITICA):
            w.writerow([celula(x) for x in (
                c.codigo_contador, c.classificacao, c.nome,
                totais.get(c.classificacao, Decimal("0.00")))])
    else:  # lancamentos
        from apps.nucleo.models.financeiro import LancamentoFinanceiro, centro_choices
        ini, fim = relatorios.periodo(ano, mes)
        centros = dict(centro_choices())
        w.writerow(["Data", "Histórico", "Tipo", "Valor (R$)", "Conta contábil", "Centro",
                    "Origem"])
        for lanc in LancamentoFinanceiro.objects.filter(data__range=(ini, fim)).order_by("data"):
            w.writerow([celula(x) for x in (
                lanc.data, lanc.descricao, lanc.get_tipo_display(), lanc.valor,
                lanc.conta_contabil, centros.get(lanc.centro, lanc.centro),
                ORIGENS.get(lanc.origem, lanc.origem))])
    return resp
