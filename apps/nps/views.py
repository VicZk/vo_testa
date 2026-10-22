import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from apps.nucleo.areas import Area
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_area
from apps.nucleo.ratelimit import limite_excedido
from apps.portal.services import get_acesso
from apps.reservas.models import Reserva

from . import services
from .forms import RespostaForm
from .models import RespostaNPS


@never_cache
@requer_area(Area.NPS)
def painel(request):
    try:
        inicio, fim = services.periodo(request.GET)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        inicio, fim = services.periodo({})
    respostas = services.respostas_periodo(inicio, fim)
    pendentes = Reserva.objects.filter(status=Reserva.Status.CHECKOUT,
        checkout_real__gte=services.limite_resposta(), resposta_nps__isnull=True).select_related("hospede").order_by("-checkout_real")[:50]
    return render(request, "nps/painel.html", {"resumo": services.resumo(respostas),
        "pagina": paginar(request, respostas), "inicio": inicio, "fim": fim, "pendentes": pendentes})


@never_cache
@requer_area(Area.NPS)
@require_POST
def convite(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    if not services.elegivel(reserva):
        raise Http404()
    acesso = get_acesso(reserva.pk)
    link = request.build_absolute_uri(reverse("portal:nps", args=[acesso.token]))
    return render(request, "nps/convite.html", {"reserva": reserva, "link": link})


@requer_area(Area.NPS)
@require_POST
def tratar(request, resposta_id):
    get_object_or_404(RespostaNPS, pk=resposta_id)
    try:
        services.tratar(resposta_id, request.POST.get("tratativa", ""), request.user)
        messages.success(request, "Acompanhamento registrado.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("nps:painel")


def _reserva_publica(token):
    if not modulo_ativo(Modulo.APPSITE):
        raise Http404()
    reserva = services.reserva_por_token(token)
    if not reserva:
        raise Http404()
    return reserva


@never_cache
@require_http_methods(["GET", "POST"])
def pesquisa(request, token):
    reserva = _reserva_publica(token)
    form = RespostaForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if limite_excedido(request, "nps_resposta", limite=10, janela_seg=300, sufixo=str(token)):
            return HttpResponse("Muitas tentativas. Aguarde alguns minutos.", status=429)
        if form.is_valid():
            try:
                services.responder(reserva.pk, **form.cleaned_data)
                return redirect("portal:nps", token=token)
            except ValidationError as erro:
                form.add_error(None, erro)
                status = 409 if getattr(erro, "code", "") == "duplicada" else 400
        else:
            status = 400
    resposta = RespostaNPS.objects.filter(reserva=reserva).first()
    return render(request, "portal/nps.html", {"token": token, "reserva": reserva,
        "form": form, "resposta": resposta}, status=status)


def _serializar(resposta):
    return {"reserva_id": resposta.reserva_id, "nota": resposta.nota, "faixa": resposta.faixa,
        "comentario": resposta.comentario, "canal": resposta.canal, "criado_em": resposta.criado_em.isoformat()}


def _criar(dados, reserva_id, usuario=None):
    try:
        resposta, criada = services.responder(reserva_id, dados.get("nota"), dados.get("comentario", ""),
            dados.get("canal") or (RespostaNPS.Canal.EQUIPE if usuario else RespostaNPS.Canal.PORTAL), usuario,
            consentimento=dados.get("consentimento"))
    except ValidationError as erro:
        status = {"duplicada": 409, "indisponivel": 404}.get(getattr(erro, "code", ""), 400)
        return JsonResponse({"erro": " ".join(erro.messages)}, status=status)
    return JsonResponse(_serializar(resposta), status=201 if criada else 200)


@csrf_protect
def _criar_interna(request, dados):
    if not request.user.is_authenticated or not request.user.pode_area(Area.NPS):
        return JsonResponse({"erro": "Sem acesso à pesquisa."}, status=403)
    return _criar(dados, dados.get("reserva_id"), request.user)


@csrf_exempt
@never_cache
@require_http_methods(["POST"])
def api_criar_resposta(request):
    # Token opaco autentica o hóspede. Escritas por sessão passam pelo CSRF.
    try:
        if len(request.body) > 16384:
            raise ValueError()
        dados = json.loads(request.body)
        if not isinstance(dados, dict):
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"erro": "Envie um objeto JSON válido."}, status=400)
    if "token" not in dados:
        return _criar_interna(request, dados)
    if limite_excedido(request, "nps_api", limite=20, janela_seg=300):
        return JsonResponse({"erro": "Muitas tentativas."}, status=429)
    reserva = _reserva_publica(dados["token"])
    if dados.get("canal") == RespostaNPS.Canal.EQUIPE:
        return JsonResponse({"erro": "Canal de resposta inválido."}, status=400)
    return _criar(dados, reserva.pk)


@never_cache
@requer_area(Area.NPS)
@require_http_methods(["GET"])
def api_resposta_reserva(request, reserva_id: int):
    return JsonResponse(_serializar(get_object_or_404(RespostaNPS, reserva_id=reserva_id)))


@never_cache
@requer_area(Area.NPS)
@require_http_methods(["GET"])
def api_resumo(request):
    try:
        inicio, fim = services.periodo(request.GET)
    except ValidationError as erro:
        return JsonResponse({"erro": " ".join(erro.messages)}, status=400)
    return JsonResponse(services.resumo(services.respostas_periodo(inicio, fim)))
