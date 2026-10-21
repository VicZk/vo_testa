import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from apps.nucleo.models import UH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_modulo

from . import services
from .models import ConferenciaOcupacao, StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


def _contexto_quadro(usuario=None):
    """Chips + lista de quartos — o trecho que o HTMX troca a cada ação."""
    dados = services.painel_limpeza()
    contagem = dados["contagem"]
    # "Só os meus": a camareira no corredor quer a fila DELA, não o andar inteiro.
    meus = 0
    minhas_por_situacao = dict.fromkeys(contagem, 0)
    for linha in dados["linhas"]:
        linha["minha"] = bool(
            usuario and linha["tarefa"] and linha["tarefa"].camareira_id == usuario.pk)
        if linha["minha"]:
            meus += 1
            minhas_por_situacao[linha["situacao"]] += 1
    # O ciclo já vem do services com rótulo e explicação; aqui entram só os números
    # (um por estado), que a tela usa no chip e no estado vazio.
    ciclo = [
        {**etapa, "n": contagem.get(etapa["cod"], 0),
         "minhas": minhas_por_situacao.get(etapa["cod"], 0)}
        for etapa in services.CICLO
    ]
    return {
        "linhas": dados["linhas"],
        "contagem": contagem,
        "ciclo": ciclo,
        "meus": meus,
        "divergencias": dados["divergencias"],
        "divergencias_graves": dados["divergencias_graves"],
        "a_conferir": dados["a_conferir"],
        "conferidos": dados["conferidos"],
        "sem_base": dados["sem_base"],
        "vistos": ConferenciaOcupacao.botoes_da_ronda(),
        "camareiras": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
    }


def _resposta_acao(request, aviso="", tipo="success"):
    """Resposta das ações do painel.

    Com HTMX devolve só o quadro (a linha E os contadores dos chips mudam juntos,
    sem recarregar a página) e manda o aviso em toast pelo HX-Trigger. Sem HTMX
    (ou sem JS) segue o caminho antigo: mensagem + redirect. `tipo="error"` fica
    na tela até alguém fechar — divergência da ronda não pode passar batida.
    """
    if not request.headers.get("HX-Request"):
        if aviso:
            {"error": messages.error, "warning": messages.warning}.get(
                tipo, messages.success)(request, aviso)
        return redirect("governanca:painel")
    resposta = render(request, "governanca/partials/quadro.html",
                      _contexto_quadro(request.user))
    if aviso:
        resposta["HX-Trigger"] = json.dumps({"aviso": {"texto": aviso, "tipo": tipo}})
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

    contexto = _contexto_quadro(request.user)
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
    tarefa = services.abrir_faxina(uh, tipo=tipo, usuario=request.user,
                                   origem="manual")
    # "Começar limpeza" num quarto sem faxina na fila: abrir e já começar é UM gesto
    # só para quem está com o pano na mão — dois botões seguidos ("abrir" e depois
    # "iniciar") era o que mais confundia quem pegava o sistema pela primeira vez.
    if request.POST.get("iniciar"):
        services.iniciar_tarefa(tarefa, request.user)
        return _resposta_acao(request, f"Limpeza do {uh.numero} começou.")
    return _resposta_acao(request, f"{uh.numero} entrou na fila de limpeza.")


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
    if situacao == "reprovada":
        # Supervisora devolveu o quarto: volta para a fila com motivo registrado.
        services.reprovar_inspecao(uh, request.user, request.POST.get("motivo", ""))
        aviso = f"{uh.numero} reprovado — voltou para a fila de limpeza."
    elif situacao == StatusLimpeza.Situacao.INSPECIONADA:
        services.inspecionar(uh, request.user)
        aviso = f"{uh.numero} inspecionado."
    elif situacao in StatusLimpeza.Situacao.values:
        services.definir_status(uh, situacao, request.user)
        aviso = f"{uh.numero}: {dict(StatusLimpeza.Situacao.choices)[situacao].lower()}."
    return _resposta_acao(request, aviso)


@requer_modulo(Modulo.GOVERNANCA)
def ronda(request, pk):
    """Conferência de ocupação: a camareira registra o que VIU no quarto. Um toque,
    sem recarregar a tela (HTMX) — e cada toque é uma linha nova no histórico."""
    if request.method != "POST":
        return redirect("governanca:painel")
    uh = get_object_or_404(UH, pk=pk)
    visto = request.POST.get("visto")
    if visto not in ConferenciaOcupacao.Visto.values:   # não confia no POST
        return _resposta_acao(request)
    conferencia = services.registrar_conferencia(
        uh, visto, usuario=request.user, observacao=request.POST.get("observacao", ""))
    if conferencia.divergente:
        rotulo, gravidade, o_que_fazer = services.explicar_divergencia(
            conferencia.divergencia)
        return _resposta_acao(
            request, f"{uh.numero}: {rotulo.lower()}. {o_que_fazer}",
            tipo="error" if gravidade == "alta" else "warning")
    return _resposta_acao(request, f"{uh.numero}: {ConferenciaOcupacao.CURTO[visto].lower()}.")


@requer_modulo(Modulo.GOVERNANCA)
def devolver(request, pk):
    """Formulário de «Devolver para limpar» (o motivo da reprovação).

    Só GET: quem grava é o `status_marcar` de sempre, com `situacao=reprovada` — a
    regra e o POST continuam os mesmos. Com HTMX abre no modal da casa (o antigo
    `<details>` aberto no meio da linha desalinhava os botões vizinhos); sem
    JavaScript, o mesmo formulário abre como página.
    """
    uh = get_object_or_404(UH, pk=pk)
    gabarito = ("governanca/partials/devolver_modal.html"
                if request.headers.get("HX-Request") else "governanca/devolver.html")
    return render(request, gabarito, {"uh": uh})


@requer_modulo(Modulo.GOVERNANCA)
def discrepancias(request):
    """Relatório de discrepância da governança: onde a ronda e o PMS não batem."""
    return render(request, "governanca/discrepancias.html", services.discrepancias())
