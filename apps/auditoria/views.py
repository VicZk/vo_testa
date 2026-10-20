import csv

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.nucleo.audit import redigir_sensiveis
from apps.nucleo.models import TrilhaAuditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.periodos import periodo, selecao_periodo
from apps.nucleo.permissoes import eh_gerente, pode_ver_salario, requer_modulo

from . import services

Usuario = get_user_model()


@never_cache
@requer_modulo(Modulo.AUDITORIA)
def painel(request):
    achados = services.varrer()
    return render(request, "auditoria/painel.html", {
        "achados": achados,
        "resumo": services.resumo(achados),
    })


def _trilha_filtrada(request):
    """Filtra a trilha por ação, usuário e período (mês/ano ou intervalo)."""
    inicio, fim, rotulo = periodo(request)
    qs = TrilhaAuditoria.objects.select_related("usuario").filter(
        criado_em__date__range=(inicio, fim)
    )
    acao = request.GET.get("acao")
    usuario = request.GET.get("usuario")
    if acao:
        qs = qs.filter(acao=acao)
    if usuario:
        qs = qs.filter(usuario_id=usuario)
    return qs, rotulo


@requer_modulo(Modulo.AUDITORIA)
def trilha(request):
    qs, rotulo = _trilha_filtrada(request)
    # Salário é sensível: quem não tem a área Remuneração vê o valor redigido na
    # trilha (a mudança continua registrada — só o número é mascarado).
    ocultar_sensivel = not pode_ver_salario(request.user)
    if request.GET.get("export") == "csv":
        # Exportar é tirar a trilha inteira do sistema: só a gerência.
        if not eh_gerente(request.user):
            raise PermissionDenied("Exportar a trilha exige gerência.")
        import json as _json

        from apps.nucleo.export import resposta_csv, sanitizar_celula
        resp = resposta_csv("trilha_auditoria.csv")
        from .formatacao import frase
        w = csv.writer(resp, delimiter=";")
        w.writerow(["quando", "usuario", "descricao", "acao", "alvo", "alvo_id", "detalhe"])
        for t in qs[:5000]:
            if ocultar_sensivel:
                t.detalhe = redigir_sensiveis(t.detalhe)
            w.writerow([sanitizar_celula(x) for x in (
                t.criado_em.strftime("%d/%m/%Y %H:%M"),
                t.usuario or "—", frase(t), t.acao, t.alvo, t.alvo_id,
                _json.dumps(t.detalhe, ensure_ascii=False),
            )])
        return resp
    pagina = paginar(request, qs, 100)
    registros = list(pagina.object_list)
    if ocultar_sensivel:
        for t in registros:
            t.detalhe = redigir_sensiveis(t.detalhe)
    return render(request, "auditoria/trilha.html", {
        "registros": registros,
        "pagina": pagina,
        "rotulo": rotulo,
        "acoes": TrilhaAuditoria.objects.order_by("acao").values_list("acao", flat=True).distinct(),
        "usuarios": Usuario.objects.filter(auditorias__isnull=False).distinct(),
        "f": request.GET,
        **selecao_periodo(request),
    })


@never_cache
@requer_modulo(Modulo.AUDITORIA)
def fechamentos(request):
    """Fechamentos do dia gravados pela rotina da madrugada (auditoria noturna): o
    retrato de cada dia, que não muda depois. Só leitura; CSV para a gerência."""
    from decimal import Decimal

    from apps.nucleo.models import modulo_ativo

    inicio, fim, rotulo = periodo(request)
    lista = []
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import fechamentos as fechamentos_do_periodo

        lista = list(fechamentos_do_periodo(inicio, fim))
    soma = {campo: sum((getattr(f, campo) for f in lista), Decimal("0"))
            for campo in ("receita_diarias", "receita_servico", "receita_consumo")}
    ocupados = sum(f.quartos_ocupados for f in lista)
    disponiveis = sum(f.quartos_disponiveis for f in lista)
    totais = {
        **soma,
        "ocupados": ocupados,
        "taxa": (Decimal(ocupados) * 100 / disponiveis).quantize(Decimal("0.1"))
        if disponiveis else Decimal("0.0"),
        "adr": (soma["receita_diarias"] / ocupados).quantize(Decimal("0.01"))
        if ocupados else Decimal("0.00"),
    }
    if request.GET.get("export") == "csv":
        if not eh_gerente(request.user):
            raise PermissionDenied("Exportar os fechamentos exige gerência.")
        from apps.nucleo.export import resposta_csv

        resp = resposta_csv("fechamentos_do_dia.csv")
        w = csv.writer(resp, delimiter=";")
        w.writerow(["dia", "quartos_disponiveis", "quartos_ocupados", "ocupacao_pct",
                    "chegadas", "saidas", "no_shows", "diarias", "adr", "servico",
                    "consumo", "saldo_em_aberto", "fechado_em"])
        for f in lista:
            w.writerow([f.data.strftime("%d/%m/%Y"), f.quartos_disponiveis,
                        f.quartos_ocupados, f.taxa_ocupacao, f.chegadas, f.saidas,
                        f.no_shows, f.receita_diarias, f.adr, f.receita_servico,
                        f.receita_consumo, f.saldo_em_aberto,
                        timezone.localtime(f.criado_em).strftime("%d/%m/%Y %H:%M")])
        return resp
    return render(request, "auditoria/fechamentos.html", {
        "fechamentos": lista,
        "totais": totais,
        "rotulo": rotulo,
        "f": request.GET,
        **selecao_periodo(request),
    })
