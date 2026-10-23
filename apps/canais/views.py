from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_gerencia, requer_modulo
from apps.nucleo.validadores import filtro_identificador

from . import services
from .forms import ConexaoForm, ConferenciaEnvioForm, MapeamentoForm, ResolucaoForm, ValidacaoForm
from .models import ConfiguracaoCanais, EnvioCanal, MapeamentoCanal, RevisaoCanal


def _conexao(request):
    pk = filtro_identificador(request.GET.get("conexao"))
    if pk:
        return get_object_or_404(ConfiguracaoCanais, pk=pk)
    return ConfiguracaoCanais.load()


def _painel(conexao):
    return redirect(reverse("canais:painel")+"?"+urlencode({"conexao": conexao.pk}))


def _formulario(request, template, contexto):
    form = contexto["form"]
    if request.method == "POST" and request.headers.get("X-Form-Preserve") == "1" and form.is_bound and form.errors:
        return JsonResponse({"errors": [erros_do_formulario(form)]}, status=422, headers={"Cache-Control": "no-store"})
    return render(request, template, contexto)


@requer_modulo(Modulo.CANAIS)
def painel(request):
    conexao = _conexao(request)
    revisoes = RevisaoCanal.objects.filter(reserva__configuracao=conexao).select_related("reserva")
    filtro = request.GET.get("estado", "pendentes")
    if filtro == "pendentes":
        revisoes = revisoes.filter(estado__in=services.PENDENTES)
    elif filtro == "ensaio":
        revisoes = revisoes.filter(estado=RevisaoCanal.Estado.ENSAIO)
    elif filtro != "todas":
        filtro = "todas"
    return render(request, "canais/painel.html", {
        "conexao": conexao, "conexoes": ConfiguracaoCanais.objects.all(), "situacao": services.situacao(conexao),
        "pagina": paginar(request, revisoes), "filtro": filtro,
        "pendentes": RevisaoCanal.objects.filter(reserva__configuracao=conexao, estado__in=services.PENDENTES).count(),
        "total_mapas": conexao.mapeamentos.count(), "ultimo_envio": conexao.envios.first(),
    })


@requer_modulo(Modulo.CANAIS)
@requer_gerencia
def conexao(request, pk=None):
    obj = get_object_or_404(ConfiguracaoCanais, pk=pk) if pk else ConfiguracaoCanais()
    form = ConexaoForm(request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            services.salvar_configuracao(obj, form.cleaned_data, request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Conexão salva. Confira as categorias e a validação antes de abrir vendas.")
            return _painel(obj)
    return _formulario(request, "canais/formulario.html", {"form": form, "titulo": "Editar conexão" if obj.pk else "Nova conexão",
        "descricao": "As credenciais ficam no servidor. Homologação e produção usam conexões e credenciais separadas.", "botao": "Salvar conexão", "conexao": obj})


@requer_modulo(Modulo.CANAIS)
def categorias(request, pk):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=pk)
    mapas = cfg.mapeamentos.annotate(total_unidades=Count("unidades")).order_by("nome", "pk")
    return render(request, "canais/categorias.html", {"conexao": cfg, "pagina": paginar(request, mapas)})


@requer_modulo(Modulo.CANAIS)
@requer_gerencia
def mapeamento(request, conexao_pk, pk=None):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=conexao_pk)
    obj = get_object_or_404(MapeamentoCanal, pk=pk, configuracao=cfg) if pk else MapeamentoCanal(configuracao=cfg)
    form = MapeamentoForm(request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        dados = dict(form.cleaned_data)
        unidades = dados.pop("unidades")
        try:
            services.salvar_mapeamento(cfg, obj, dados, unidades, request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Categoria salva. Confira a disponibilidade e registre a validação atualizada.")
            return _painel(cfg)
    return _formulario(request, "canais/formulario.html", {"form": form, "titulo": "Mapear categoria",
        "descricao": "Uma unidade física pertence a uma só categoria nesta conexão. O limite e a margem reduzem a quantidade publicada.", "botao": "Salvar categoria", "conexao": cfg})


@requer_modulo(Modulo.CANAIS)
@requer_gerencia
def validacao(request, pk):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=pk)
    form = ValidacaoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            services.registrar_validacao(cfg, form.cleaned_data["evidencia"], request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Validação registrada para a configuração atual.")
            return _painel(cfg)
    return _formulario(request, "canais/formulario.html", {"form": form, "titulo": "Registrar validação",
        "descricao": "Este registro acompanha a conferência feita com o provedor. Mudanças nas credenciais ou no mapeamento exigem nova validação.", "botao": "Registrar validação", "conexao": cfg})


@requer_modulo(Modulo.CANAIS)
@requer_gerencia
@require_POST
def solicitar(request, pk):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=pk)
    try:
        services.solicitar_sincronizacao(cfg, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Atualização solicitada. A rotina agendada processará o pedido.")
    return _painel(cfg)


@requer_modulo(Modulo.CANAIS)
def disponibilidade(request, pk):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=pk)
    previa = services.previa_envio(cfg)
    return render(request, "canais/disponibilidade.html", {"conexao": cfg, "previa": previa, "pagina": paginar(request, previa["linhas"])})


def _detalhe_revisao(request, obj, form=None, erro=""):
    dados = {**obj.dados, "quartos": [{**q, "entrada": parse_date(q["checkin"]), "saida": parse_date(q["checkout"])} for q in obj.dados["quartos"]]}
    return _formulario(request, "canais/revisao.html", {"revisao": obj, "dados": dados, "form": form if form is not None else ResolucaoForm(),
        "erro": erro, "pode_resolver": obj.estado in services.PENDENTES,
        "vinculos": obj.vinculos_aplicados.values()})


@requer_modulo(Modulo.CANAIS)
def revisao(request, pk):
    return _detalhe_revisao(request, get_object_or_404(RevisaoCanal.objects.select_related("reserva__configuracao"), pk=pk))


@requer_modulo(Modulo.CANAIS)
@requer_modulo(Modulo.RESERVAS)
@require_POST
def aplicar(request, pk):
    obj = get_object_or_404(RevisaoCanal.objects.select_related("reserva__configuracao"), pk=pk)
    try:
        services.aplicar_revisao(obj, request.user, manual=True)
    except ValidationError as exc:
        return _detalhe_revisao(request, obj, erro=" ".join(exc.messages))
    messages.success(request, "Revisão conferida e aplicada no PMS.")
    return redirect("canais:revisao", pk=obj.pk)


@requer_modulo(Modulo.CANAIS)
@requer_modulo(Modulo.RESERVAS)
@require_POST
def resolver(request, pk):
    obj = get_object_or_404(RevisaoCanal.objects.select_related("reserva__configuracao"), pk=pk)
    form = ResolucaoForm(request.POST)
    if form.is_valid():
        try:
            services.resolver_manualmente(obj, form.cleaned_data["reservas"], form.cleaned_data["motivo"], request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Conferência registrada com os vínculos do PMS.")
            return redirect("canais:revisao", pk=obj.pk)
    return _detalhe_revisao(request, obj, form=form)


@requer_modulo(Modulo.CANAIS)
def envios(request, pk):
    cfg = get_object_or_404(ConfiguracaoCanais, pk=pk)
    return render(request, "canais/envios.html", {"conexao": cfg, "pagina": paginar(request, cfg.envios.all())})


@requer_modulo(Modulo.CANAIS)
@requer_gerencia
def envio(request, pk):
    obj = get_object_or_404(EnvioCanal, pk=pk)
    form = ConferenciaEnvioForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            services.conferir_envio(obj, form.cleaned_data["evidencia"], request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Conferência do envio registrada.")
            return redirect("canais:envios", pk=obj.configuracao_id)
    return _formulario(request, "canais/formulario.html", {"form": form, "titulo": "Conferir envio nos canais",
        "descricao": f"Envio de {obj.criado_em:%d/%m/%Y %H:%M} · {obj.get_estado_display()}. O aceite do provedor ainda exige conferir o resultado nos canais.",
        "botao": "Registrar conferência", "envio": obj, "conexao": obj.configuracao})
