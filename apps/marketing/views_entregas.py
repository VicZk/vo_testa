"""Consulta e edição das entregas sem mudar a fase ou publicar a campanha."""
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_modulo

from . import services_agenda, services_entregas
from .forms_entregas import EntregaForm, FiltroEntregasForm
from .models import ItemChecklist, PecaCampanha


def _voltar(request, *, padrao=None, considerar_origem=False):
    destino = request.POST.get("voltar") or request.GET.get("voltar") or ""
    if not destino and considerar_origem:
        origem = request.headers.get("HX-Current-URL", "")
        if url_has_allowed_host_and_scheme(origem, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            partes = urlsplit(origem)
            destino = partes.path + ("?" + partes.query if partes.query else "")
    if destino.startswith("/") and not destino.startswith("//") and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return padrao or reverse("marketing:entregas")


def preparar_referencias(pecas, usuario):
    """Consulta em lote, sem carregar o model de LP ou expor links sem permissão."""
    paginas = {pagina["id"]: pagina for pagina in services_entregas.referencias_lps(
        usuario, [peca.pagina_captacao_id for peca in pecas if peca.pagina_captacao_id])}
    for peca in pecas:
        peca.lp_disponivel = peca.pagina_captacao_id in paginas
    return pecas


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def entregas(request):
    canal, canais = services_agenda.filtros_canais(request)
    form = FiltroEntregasForm(request.GET)
    dados = form.cleaned_data if form.is_valid() else {}
    consulta, resumo = services_entregas.consultar_entregas(
        busca=dados.get("q", ""), campanha=dados.get("campanha"),
        tipo=dados.get("tipo", ""), situacao=dados.get("situacao", ""), canal=canal,
        vinculo=dados.get("vinculo", ""))
    if form.errors:
        consulta = consulta.none()
    pagina = paginar(request, consulta, por_pagina=30)
    pagina.object_list = preparar_referencias(list(pagina.object_list), request.user)
    for item in resumo:
        filtros = request.GET.copy()
        filtros.pop("pagina", None)
        filtros["tipo"] = item["tipo"]
        for situacao in ("pendentes", "pronta"):
            filtros["situacao"] = situacao
            item["url_" + situacao] = reverse("marketing:entregas") + "?" + filtros.urlencode()
    return render(request, "marketing/entregas.html", {
        "filtros": form, "pagina": pagina, "resumo_tipos": resumo,
        "voltar_entrega": request.get_full_path(),
        "canal": canal, "canais": canais,
        "vinculos": [{"valor": valor, "nome": nome, "ativo": valor == dados.get("vinculo", "")}
                     for valor, nome in form.fields["vinculo"].choices],
        "atual": "marketing", "aba": "entregas",
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def alterar_estado(request, pk):
    entrega = get_object_or_404(PecaCampanha, pk=pk)
    try:
        services_entregas.alterar_estado(entrega, request.POST.get("status"), request.user,
                                       versao=request.POST.get("versao", ""))
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Situação da entrega atualizada.")
    return redirect(_voltar(request))


def _data_da_url(request):
    """`?data=AAAA-MM-DD` (o dia clicado no Cronograma); inválida, fica sem data."""
    from datetime import date
    try:
        return date.fromisoformat(request.GET.get("data", ""))
    except ValueError:
        return None


def _editar(request, peca=None):
    form = EntregaForm(
        request.POST if request.method == "POST" else None, usuario=request.user,
        peca=peca, campanha=request.GET.get("campanha"),
        initial={"tipo": request.GET.get("tipo", ""), "data": _data_da_url(request)})
    if request.method == "POST" and form.is_valid():
        try:
            services_entregas.salvar_entrega(dados=form.cleaned_data, usuario=request.user, peca=peca)
        except ValidationError as erro:
            if hasattr(erro, "message_dict"):
                for campo, erros in erro.message_dict.items():
                    form.add_error(campo if campo in form.fields else None, erros)
            else:
                form.add_error(None, erro)
        else:
            messages.success(request, "Entrega salva.")
            return redirect(_voltar(request))
    return render(request, "marketing/entrega_form.html", {
        "form": form, "peca": peca, "voltar": _voltar(request),
        "atual": "marketing", "aba": "entregas",
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_http_methods(["GET", "POST"])
def nova_entrega(request):
    return _editar(request)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_http_methods(["GET", "POST"])
def editar_entrega(request, pk):
    return _editar(request, get_object_or_404(PecaCampanha, pk=pk))


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def anexos_da_entrega(request):
    form = EntregaForm(usuario=request.user, campanha=request.GET.get("campanha"))
    return render(request, "marketing/_anexo_entrega.html", {"field": form["material_checklist"]})


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def abrir_material(request, pk):
    material = get_object_or_404(ItemChecklist, pk=pk)
    if not material.arquivo:
        raise Http404("Material não encontrado.")
    try:
        arquivo = material.arquivo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Material não encontrado.") from None
    resposta = FileResponse(arquivo, as_attachment=True, content_type="application/octet-stream",
                            filename=PurePosixPath(material.arquivo.name).name)
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Cache-Control"] = "private, no-store"
    return resposta


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def abrir_lp(request, pk):
    peca = get_object_or_404(PecaCampanha, pk=pk)
    if not peca.pagina_captacao_id:
        raise Http404("Nenhuma LP vinculada.")
    paginas = services_entregas.referencias_lps(request.user, [peca.pagina_captacao_id])
    if not paginas:
        raise PermissionDenied("Abrir esta LP exige acesso ao Comercial.")
    return redirect(paginas[0]["url"])
