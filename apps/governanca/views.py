import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from apps.nucleo.models import UH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo

from . import services
from .models import StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


def _contexto_quadro():
    """Chips + lista de quartos — o trecho que o HTMX troca a cada ação."""
    dados = services.painel_limpeza()
    contagem = dados["contagem"]
    return {
        "linhas": dados["linhas"],
        "contagem": contagem,
        "camareiras": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        # Situações sem nenhum quarto: o filtro mostra um recado em vez de uma
        # tabela só com cabeçalho.
        "situacoes_vazias": [
            {"cod": cod, "label": label}
            for cod, label in StatusLimpeza.Situacao.choices
            if not contagem.get(cod)
        ],
    }


def _resposta_acao(request, aviso=""):
    """Resposta das ações do painel.

    Com HTMX devolve só o quadro (a linha E os contadores dos chips mudam juntos,
    sem recarregar a página) e manda o aviso em toast pelo HX-Trigger. Sem HTMX
    (ou sem JS) segue o caminho antigo: mensagem + redirect.
    """
    if not request.headers.get("HX-Request"):
        if aviso:
            messages.success(request, aviso)
        return redirect("governanca:painel")
    resposta = render(request, "governanca/partials/quadro.html", _contexto_quadro())
    if aviso:
        resposta["HX-Trigger"] = json.dumps({"aviso": {"texto": aviso, "tipo": "success"}})
    return resposta


@requer_modulo(Modulo.GOVERNANCA)
def painel(request):
    # Lista de montagem de camas das chegadas do dia (vem de Reservas, se ativo).
    from django.utils import timezone

    from apps.nucleo.models import modulo_ativo

    montagem = []
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import montagem_do_dia
        montagem = montagem_do_dia(timezone.localdate())

    contexto = _contexto_quadro()
    contexto.update({"tipos": TarefaGovernanca.Tipo.choices, "montagem": montagem})
    return render(request, "governanca/painel.html", contexto)


@requer_modulo(Modulo.GOVERNANCA)
def nova_tarefa(request):
    if request.method != "POST":
        return redirect("governanca:painel")
    uh = get_object_or_404(UH, pk=request.POST.get("uh"))
    tipo = request.POST.get("tipo") or TarefaGovernanca.Tipo.FAXINA
    if tipo not in TarefaGovernanca.Tipo.values:   # não confia no POST
        tipo = TarefaGovernanca.Tipo.FAXINA
    services.abrir_faxina(uh, tipo=tipo, usuario=request.user, origem="manual")
    return _resposta_acao(request, f"Faxina aberta para o {uh.numero}.")


@requer_modulo(Modulo.GOVERNANCA)
def tarefa_acao(request, pk):
    if request.method != "POST":
        return redirect("governanca:painel")
    tarefa = get_object_or_404(TarefaGovernanca, pk=pk)
    acao = request.POST.get("acao")
    aviso = ""
    if acao == "atribuir":
        tarefa.camareira = Usuario.objects.filter(
            pk=request.POST.get("camareira")
        ).first()
        tarefa.save()
        aviso = (
            f"{tarefa.uh.numero} com {tarefa.camareira.get_full_name() or tarefa.camareira.username}."
            if tarefa.camareira else f"{tarefa.uh.numero} sem camareira."
        )
    elif acao == "iniciar":
        services.iniciar_tarefa(tarefa, request.user)
        aviso = f"Faxina do {tarefa.uh.numero} iniciada."
    elif acao == "concluir":
        services.concluir_tarefa(tarefa, request.user)
        aviso = f"{tarefa.uh.numero} limpo. Boa!"
    return _resposta_acao(request, aviso)


@requer_modulo(Modulo.GOVERNANCA)
def status_marcar(request, pk):
    if request.method != "POST":
        return redirect("governanca:painel")
    uh = get_object_or_404(UH, pk=pk)
    situacao = request.POST.get("situacao")
    aviso = ""
    if situacao in StatusLimpeza.Situacao.values:
        services.definir_status(uh, situacao, request.user)
        aviso = f"{uh.numero}: {dict(StatusLimpeza.Situacao.choices)[situacao].lower()}."
    return _resposta_acao(request, aviso)
