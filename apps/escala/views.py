import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.nucleo.models import Funcionario
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo

from . import services
from .models import Atribuicao, Ausencia, HoraExtra, TrocaTurno, Turno


def _data(txt, default=None):
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _hora(txt):
    try:
        return datetime.strptime(txt, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _funcionarios(setor=None):
    qs = Funcionario.objects.filter(pessoa__ativo=True).select_related("pessoa").order_by("pessoa__nome")
    return qs


def _selecionado(modelo, valor, rotulo):
    try:
        chave = int(valor)
        if not 0 < chave <= 9223372036854775807:
            raise ValueError()
        return modelo.objects.get(pk=chave)
    except (TypeError, ValueError, modelo.DoesNotExist) as erro:
        raise ValidationError(f"Selecione {rotulo} da lista. Atualize a página se o cadastro mudou.") from erro


def _contexto_grade(inicio, setor):
    """Contexto compartilhado pela grade (página cheia e refresh do editor)."""
    from .models import SemanaPublicada

    grade = services.grade_semana(inicio, setor)
    analise = services.analisar_semana(inicio, setor)
    viol = analise["violacoes"]
    fim = inicio + timedelta(days=6)
    hx = HoraExtra.objects.filter(data__range=(inicio, fim)).select_related("funcionario")
    hx_por = {}
    for he in hx:
        hx_por.setdefault((he.funcionario_id, he.data), []).append(he)
    feriados = services.feriados_no_periodo(inicio, fim)
    for linha in grade["linhas"]:                       # selo de violação + horas extras + feriado por chip
        for cel in linha["celulas"]:
            cel["eh_feriado"] = cel["data"] in feriados
            for a in cel["atribs"]:
                a.violacoes = viol.get(a.pk, [])
                a.horas_extras = hx_por.get((a.funcionario_id, a.data), [])
                a.eh_feriado = a.data in feriados
                a.compensacao_efetiva = (
                    a.compensacao_feriado or a.funcionario.compensacao_feriado or "folga"
                )
    pub = SemanaPublicada.objects.filter(inicio=inicio, setor=setor or "").first()
    return {
        "grade": grade,
        "inicio": inicio,
        "setor": setor,
        "hoje": timezone.localdate(),
        "validacao": analise["alertas"],
        "bloqueios": analise["bloqueios"],
        "publicacao": pub,
    }


@requer_modulo(Modulo.ESCALA)
def escala(request):
    inicio = services.inicio_da_semana(_data(request.GET.get("inicio")))
    setor = request.GET.get("setor") or None
    ctx = _contexto_grade(inicio, setor)
    ctx.update({
        "anterior": inicio - timedelta(days=7),
        "proximo": inicio + timedelta(days=7),
        "setores": Turno.Setor.choices,
        "funcionarios": _funcionarios(setor),
        "turnos": Turno.objects.filter(ativo=True),
        "ausencias_json": json.dumps(services.ausencias_da_semana(inicio)),
    })
    return render(request, "escala/grade.html", ctx)


@requer_modulo(Modulo.ESCALA)
@require_POST
def escala_editar(request):
    """Add/mover/remover por arrasto. Devolve o partial da grade (validação +
    tabela) já atualizado; erro de regra volta como JSON 400 (vira toast)."""
    inicio = services.inicio_da_semana(_data(request.POST.get("inicio")))
    setor = request.POST.get("setor") or None
    acao = request.POST.get("acao")
    forcar = request.POST.get("forcar") == "1"
    data = _data(request.POST.get("data"))
    try:
        if acao in ("add", "mover"):
            turno = _selecionado(Turno, request.POST.get("turno"), "um turno")
            if acao == "add":
                func = _selecionado(Funcionario, request.POST.get("funcionario"), "um funcionário")
                atrib = None
            else:
                atrib = _selecionado(Atribuicao, request.POST.get("atribuicao"), "uma atribuição")
                func = atrib.funcionario
            # Interjornada <11h é risco legal: barra o drop e pede confirmação.
            if not forcar and services.conflito_interjornada(
                func, turno, data, ignora_pk=atrib.pk if atrib else None
            ):
                return JsonResponse(
                    {"confirmar": f"{func.pessoa.nome} teria horários sobrepostos ou menos de "
                                  f"{services.descanso_minimo()}h de descanso. Incluir para revisão?"}, status=409,
                )
            if acao == "add":
                services.atribuir(turno, func, data, request.user)
            else:
                services.mover(atrib, turno, data, request.user)
            if forcar:
                from apps.nucleo.models.financeiro import registrar_auditoria
                registrar_auditoria(request.user, "escala_forcar_interjornada",
                                    func, {"turno": str(turno), "data": str(data)})
        elif acao == "remover":
            atrib = _selecionado(Atribuicao, request.POST.get("atribuicao"), "uma atribuição")
            services.desatribuir(atrib)
        elif acao == "he_add":
            func = _selecionado(Funcionario, request.POST.get("funcionario"), "um funcionário")
            services.adicionar_hora_extra(
                func, data, _hora(request.POST.get("he_inicio")), _hora(request.POST.get("he_fim")),
                request.POST.get("tipo"), request.user,
            )
        elif acao == "he_remover":
            he = _selecionado(HoraExtra, request.POST.get("hora_extra"), "uma hora extra")
            services.remover_hora_extra(he)
        elif acao == "feriado_comp":
            atrib = _selecionado(Atribuicao, request.POST.get("atribuicao"), "uma atribuição")
            services.definir_compensacao_feriado(atrib, request.POST.get("valor"))
        else:
            raise ValidationError("Ação de edição desconhecida. Atualize a escala e tente novamente.")
    except ValidationError as erro:
        return JsonResponse({"erro": " ".join(erro.messages)}, status=400)
    return render(request, "escala/partials/grade_conteudo.html", _contexto_grade(inicio, setor))


@requer_modulo(Modulo.ESCALA)
@requer_gerencia
def relatorio_colaborador(request):
    """Relatório mensal do colaborador (filtros: colaborador + mês/ano)."""
    import csv

    from django.http import HttpResponse

    from apps.nucleo import periodos

    inicio, fim, rotulo = periodos.periodo(request)
    funcs = Funcionario.objects.select_related("pessoa").order_by("pessoa__nome")
    fid = request.GET.get("funcionario")
    try:
        func = _selecionado(Funcionario, fid, "um funcionário") if fid else funcs.first()
    except ValidationError as erro:
        func = None
        messages.error(request, " ".join(erro.messages))
    dados = services.relatorio_colaborador(func, inicio, fim) if func else None

    if request.GET.get("export") == "csv" and dados:
        from django.utils.text import slugify

        from apps.nucleo.export import sanitizar_celula  # S-M2: anti CSV formula-injection
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp.write("﻿")
        nome_arq = slugify(func.pessoa.nome) or "colaborador"
        resp["Content-Disposition"] = f'attachment; filename="relatorio_{nome_arq}_{inicio}.csv"'
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Colaborador", sanitizar_celula(func.pessoa.nome)])
        w.writerow(["Período", rotulo])
        w.writerow(["Dias trabalhados", dados["dias_trabalhados"]])
        w.writerow(["Horas normais", dados["horas_normais_txt"]])
        w.writerow(["Hora extra (banco)", dados["banco_txt"]])
        w.writerow(["Hora extra (extra)", dados["extra_txt"]])
        w.writerow(["Dias ausente", dados["dias_ausente"]])
        w.writerow([])
        w.writerow(["Feriado", "Turno", "Compensação"])
        for fe in dados["feriados_trabalhados"]:
            w.writerow([fe["data"].strftime("%d/%m/%Y"),
                        sanitizar_celula(fe["turno"]), sanitizar_celula(fe["compensacao"])])
        return resp

    iniciais = ""
    if func:
        iniciais = "".join(p[0] for p in func.pessoa.nome.split()[:2]).upper()
    return render(request, "escala/relatorio_colaborador.html", {
        "funcionarios": funcs, "func": func, "dados": dados, "iniciais": iniciais,
        "inicio": inicio, "fim": fim, "rotulo": rotulo,
        **periodos.selecao_periodo(request),
    })


@requer_modulo(Modulo.ESCALA)
@requer_gerencia
@require_POST
def publicar(request):
    inicio = None
    setor = request.POST.get("setor") or None
    try:
        data = _data(request.POST.get("inicio"))
        if data is None:
            raise ValidationError("Informe uma semana válida antes de publicar.")
        inicio = services.inicio_da_semana(data)
        services.publicar_semana(inicio, setor, request.user,
                                 request.POST.get("justificativa", ""))
        messages.success(request, "Escala da semana publicada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    if inicio is None:
        return redirect("escala:grade")
    destino = f"{reverse('escala:grade')}?inicio={inicio:%Y-%m-%d}"
    if setor:
        destino += f"&setor={setor}"
    return redirect(destino)


@requer_modulo(Modulo.ESCALA)
@requer_gerencia
def gerar_semana(request):
    """Gera a escala da semana automaticamente (gestão) e mostra o resultado."""
    inicio = None
    setor = request.POST.get("setor") or None
    if request.method == "POST":
        try:
            data = _data(request.POST.get("semana"))
            if data is None:
                raise ValidationError("Informe uma semana válida antes de gerar a escala.")
            inicio = services.inicio_da_semana(data)
            n = services.gerar_semana(inicio, request.user, setor)
            messages.success(request, f"Escala gerada: {n} atribuições. Ajuste o que precisar.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    if inicio is None:
        return redirect("escala:grade")
    destino = f"{reverse('escala:grade')}?inicio={inicio:%Y-%m-%d}"
    if setor:
        destino += f"&setor={setor}"
    return redirect(destino)


@requer_modulo(Modulo.ESCALA)
def atribuir(request):
    if request.method == "POST":
        try:
            turno = _selecionado(Turno, request.POST.get("turno"), "um turno")
            func = _selecionado(Funcionario, request.POST.get("funcionario"), "um funcionário")
            data = _data(request.POST.get("data"))
            services.atribuir(turno, func, data, request.user)
            messages.success(request, f"{func.pessoa.nome} escalado(a).")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    semana = request.POST.get("semana")
    return redirect(f"{reverse('escala:grade')}?inicio={semana}" if semana else "escala:grade")


@requer_modulo(Modulo.ESCALA)
def remover_atribuicao(request, pk):
    atrib = get_object_or_404(Atribuicao, pk=pk)
    if request.method == "POST":
        services.desatribuir(atrib)
        messages.success(request, "Atribuição removida.")
    # "voltar" vem como query string (?inicio=…); redirect() reverte nome de rota,
    # então prefixa a URL base da grade para não dar NoReverseMatch.
    voltar = request.POST.get("voltar", "")
    destino = reverse("escala:grade") + voltar if voltar.startswith("?") else reverse("escala:grade")
    return redirect(destino)


@requer_modulo(Modulo.ESCALA)
def minha_escala(request):
    hoje = timezone.localdate()
    fim = hoje + timedelta(days=30)
    atribs = services.minha_escala(request.user, hoje, fim)
    return render(request, "escala/minha.html", {
        "atribs": atribs,
        "tem_funcionario": getattr(request.user, "funcionario", None) is not None,
    })


@requer_modulo(Modulo.ESCALA)
def turnos(request):
    from .models import ConfiguracaoEscala
    config = ConfiguracaoEscala.atual()
    if request.method == "POST":
        if not eh_gerente(request.user):
            raise PermissionDenied
        if request.POST.get("acao") == "descanso":
            from apps.nucleo.models import registrar_auditoria
            from apps.nucleo.validadores import decimal_valido
            try:
                horas = int(decimal_valido(request.POST.get("descanso_horas"), nome="Descanso", minimo=1, maximo=48, casas=0))
                anterior = config.descanso_horas
                config.descanso_horas = horas
                config.full_clean()
                config.save(update_fields=["descanso_horas"])
                registrar_auditoria(request.user, "configurar_descanso_escala", config,
                                    {"anterior": anterior, "horas": horas})
                messages.success(request, "Parâmetro de descanso atualizado.")
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
            return redirect("escala:turnos")
        nome = request.POST.get("nome", "").strip()
        inicio = _hora(request.POST.get("inicio"))
        fim = _hora(request.POST.get("fim"))
        if nome and len(nome) <= 40 and inicio and fim and inicio != fim and request.POST.get("setor", "geral") in Turno.Setor.values:
            Turno.objects.create(
                nome=nome, setor=request.POST.get("setor") or "geral",
                inicio=inicio, fim=fim,
            )
            messages.success(request, "Turno cadastrado.")
        else:
            messages.error(request, "Preencha nome, início e fim.")
        return redirect("escala:turnos")
    return render(request, "escala/turnos.html", {
        "turnos": Turno.objects.all(),
        "setores": Turno.Setor.choices,
        "config": config, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.ESCALA)
def ausencias(request):
    if request.method == "POST":
        try:
            func = _selecionado(Funcionario, request.POST.get("funcionario"), "um funcionário")
            services.registrar_ausencia(
                func, request.POST.get("tipo") or "folga",
                _data(request.POST.get("inicio")), _data(request.POST.get("fim")),
                request.user, request.POST.get("observacao", ""),
            )
            messages.success(request, "Ausência registrada.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        return redirect("escala:ausencias")
    pagina = paginar(request, Ausencia.objects.select_related("funcionario__pessoa"))
    return render(request, "escala/ausencias.html", {
        "ausencias": pagina,
        "pagina": pagina,
        "funcionarios": _funcionarios(),
        "tipos": Ausencia.Tipo.choices,
    })


@requer_modulo(Modulo.ESCALA)
def trocas(request):
    if request.method == "POST":
        try:
            atrib = _selecionado(Atribuicao, request.POST.get("atribuicao"), "uma atribuição")
            substituto = _selecionado(Funcionario, request.POST.get("substituto"), "um substituto")
            services.solicitar_troca(atrib, substituto, request.POST.get("motivo", ""))
            messages.success(request, "Troca solicitada. Aguarde a aprovação.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        return redirect("escala:trocas")
    hoje = timezone.localdate()
    return render(request, "escala/trocas.html", {
        "pendentes": TrocaTurno.objects.filter(status="pendente").select_related(
            "atribuicao__turno", "solicitante__pessoa", "substituto__pessoa"),
        "recentes": TrocaTurno.objects.exclude(status="pendente").select_related(
            "solicitante__pessoa", "substituto__pessoa")[:20],
        "atribuicoes": Atribuicao.objects.filter(data__gte=hoje).select_related(
            "turno", "funcionario__pessoa").order_by("data")[:60],
        "funcionarios": _funcionarios(),
        "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.ESCALA)
@requer_gerencia
def decidir_troca(request, pk):
    troca = get_object_or_404(TrocaTurno, pk=pk)
    if request.method == "POST":
        try:
            acao = request.POST.get("acao")
            if acao not in ("aprovar", "recusar"):
                raise ValidationError("Escolha aprovar ou recusar esta troca.")
            services.decidir_troca(troca, request.user, acao == "aprovar")
            messages.success(request, "Troca decidida.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("escala:trocas")
