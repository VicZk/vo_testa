from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_gerencia, requer_modulo

from . import services
from .forms import ConsumoForm, PagamentoForm, TurnoForm, VisitaForm
from .models import TurnoDayPass, VisitaDayPass, VisitanteDayPass


@requer_modulo(Modulo.RESERVAS)
def painel(request):
    from datetime import date
    try:
        dia = date.fromisoformat(request.GET.get("data", ""))
    except (ValueError, TypeError):
        dia = timezone.localdate()
    turnos = list(TurnoDayPass.objects.filter(dia_id=dia))
    for turno in turnos:
        turno.ocupacao = services.ocupacao(turno)
    visitas = paginar(request, VisitaDayPass.objects.filter(turno__dia_id=dia).select_related("turno", "responsavel").prefetch_related("visitantes"))
    return render(request, "daypass/painel.html", {"dia": dia, "turnos": turnos, "visitas": visitas})


@requer_modulo(Modulo.RESERVAS)
@requer_gerencia
def turno(request, pk=None):
    obj = get_object_or_404(TurnoDayPass, pk=pk) if pk else TurnoDayPass()
    form = TurnoForm(request.POST if request.method == "POST" else None, instance=obj, initial={"data": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.dia_id = form.cleaned_data["data"]
        try:
            services.salvar_turno(obj, request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Turno salvo. Confira a lotação e os valores antes de cadastrar visitantes.")
            return redirect("daypass:painel")
    return render(request, "daypass/turno.html", {"form": form, "turno": obj})


@requer_modulo(Modulo.RESERVAS)
def nova_visita(request, turno_pk):
    obj = get_object_or_404(TurnoDayPass, pk=turno_pk)
    form = VisitaForm(request.POST if request.method == "POST" else None, turno=obj)
    if request.method == "POST" and form.is_valid():
        try:
            visita = services.reservar(turno=obj, usuario=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("daypass:visita", pk=visita.pk)
    return render(request, "daypass/nova_visita.html", {"form": form, "turno": obj, "ocupacao": services.ocupacao(obj)})


@requer_modulo(Modulo.RESERVAS)
def visita(request, pk):
    obj = get_object_or_404(VisitaDayPass.objects.select_related("turno", "responsavel", "hospedagem"), pk=pk)
    saldo = obj.saldo()
    return render(request, "daypass/visita.html", {"visita": obj, "saldo": saldo, "pago": obj.total_pago(), "pagamento_form": PagamentoForm(initial={"valor": saldo}), "consumo_form": ConsumoForm()})


@requer_modulo(Modulo.RESERVAS)
@require_POST
def acao(request, pk, acao):
    obj = get_object_or_404(VisitaDayPass.objects.select_related("turno"), pk=pk)
    try:
        if acao == "receber":
            form = PagamentoForm(request.POST)
            if not form.is_valid():
                raise ValidationError(erros_do_formulario(form))
            services.receber(obj, request.user, **form.cleaned_data)
        elif acao == "consumo":
            form = ConsumoForm(request.POST)
            if not form.is_valid():
                raise ValidationError("Escolha um estoque válido para a comanda.")
            comanda = services.abrir_consumo(obj, request.user, form.cleaned_data["local"])
            return redirect("restaurante:comanda", pk=comanda.pk)
        elif acao == "encerrar":
            services.encerrar(obj, request.user)
        elif acao == "cancelar":
            services.cancelar(obj, request.user, request.POST.get("motivo", ""))
        else:
            raise ValidationError("Ação indisponível.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Operação registrada.")
    return redirect("daypass:visita", pk=obj.pk)


@requer_modulo(Modulo.RESERVAS)
@require_POST
def acesso(request, pk, visitante_pk, acao):
    visitante = get_object_or_404(VisitanteDayPass.objects.select_related("visita__turno"), pk=visitante_pk, visita_id=pk)
    try:
        if acao == "entrada":
            services.registrar_entrada(visitante, request.user)
        elif acao == "saida":
            services.registrar_saida(visitante, request.user)
        else:
            raise ValidationError("Ação indisponível.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("daypass:visita", pk=pk)


def publico(request):
    from apps.nucleo.models import modulo_ativo
    turnos = list(TurnoDayPass.objects.filter(ativo=True, dia_id__gte=timezone.localdate()).order_by("dia_id", "inicio")[:30]) if modulo_ativo(Modulo.RESERVAS) else []
    for turno in turnos:
        turno.ocupacao = services.ocupacao(turno)
    return render(request, "daypass/publico.html", {"turnos": turnos})
