import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.nucleo.models import UH
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo
from apps.nucleo.validadores import identificador_valido

from . import services
from .forms import ConfiguracaoGovernancaForm, ReportarProblemaForm, RestricaoLimpezaForm
from .models import ConferenciaOcupacao, ConfiguracaoGovernanca, StatusLimpeza, TarefaGovernanca

Usuario = get_user_model()


def _contexto_quadro(request, usuario=None):
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
    # Quem limpa: a Escala manda (as de turno hoje vêm primeiro, num grupo
    # próprio do <select>); sem o módulo, a lista de sempre.
    camareiras = services.camareiras_do_dia()
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
        "de_turno": camareiras["de_turno"],
        "camareiras": camareiras["outras"],
        "tem_escala": camareiras["tem_escala"],
        "sem_login": camareiras["sem_login"],
        # Quartos a limpar que ainda não têm quem limpe — o que o "Distribuir a
        # fila" vai dividir.
        # A oferta de desfazer o último gesto (consumida uma vez só).
        "desfazer": _desfazer_pendente(request),
        "sem_camareira": sum(
            1 for ln in dados["linhas"]
            if ln["tarefa"] and not ln["tarefa"].camareira_id and not ln["bloqueado"]
        ),
    }


def _contexto_fila(request, usuario):
    """A fila da camareira — o trecho que o HTMX troca a cada toque dela."""
    from apps.nucleo.models import modulo_ativo

    dados = services.minha_fila(usuario)
    dados["tem_manutencao"] = modulo_ativo(Modulo.MANUTENCAO)
    dados["desfazer"] = _desfazer_pendente(request)
    return dados


def _oferecer_desfazer(request, uh, texto):
    """Guarda, para a PRÓXIMA tela, a oferta de desfazer o que acabou de ser feito.

    Pela sessão porque a ação pode voltar por HTMX (o quadro) ou por redirect (a
    ficha do quarto manda de volta para a visão geral) — e nos dois casos a
    pessoa tem de ver a saída. Em vez de perguntar "tem certeza?" antes, a tela
    deixa o caminho de volta à mão depois: no toque, o erro é o toque errado, não
    a falta de convicção.
    """
    request.session["gov_desfazer"] = {
        "uh": uh.pk, "quarto": uh.numero, "texto": texto}


def _desfazer_pendente(request):
    """Consome a oferta de desfazer (uma vez só)."""
    return request.session.pop("gov_desfazer", None)


def _resposta_acao(request, aviso="", tipo="success"):
    """Resposta das ações da Governança.

    Com HTMX devolve só o trecho que mudou (o quadro da lista, ou a fila da
    camareira quando a ação partiu do celular dela — o `fila=1` do formulário) e
    manda o aviso em toast pelo HX-Trigger. Sem HTMX (ou sem JS) segue o caminho
    antigo: mensagem + redirect para a tela de onde a ação saiu. `tipo="error"`
    fica na tela até alguém fechar — divergência da ronda não pode passar batida.
    """
    da_fila = request.POST.get("fila") == "1"
    if not request.headers.get("HX-Request"):
        if aviso:
            {"error": messages.error, "warning": messages.warning}.get(
                tipo, messages.success)(request, aviso)
        # A ficha do quarto navega de verdade (ela abre sobre a parede de blocos,
        # e depois da ação a pessoa quer ver a parede atualizada).
        voltar = request.POST.get("voltar")
        if voltar in ("painel", "quartos"):
            return redirect(f"governanca:{voltar}")
        return redirect("governanca:minha_fila" if da_fila else "governanca:quartos")
    if da_fila:
        resposta = render(request, "governanca/partials/fila.html",
                          _contexto_fila(request, request.user))
    else:
        resposta = render(request, "governanca/partials/quadro.html",
                          _contexto_quadro(request, request.user))
    if aviso:
        resposta["HX-Trigger"] = json.dumps({"aviso": {"texto": aviso, "tipo": tipo}})
    resposta["X-Gov-Sucesso"] = "0" if tipo == "error" else "1"
    return resposta


@requer_modulo(Modulo.GOVERNANCA)
def painel(request):
    """Visão geral: a casa inteira em blocos coloridos, o progresso do dia, as
    chegadas que dependem de quarto pronto e o que pede ação agora. É a porta de
    entrada do módulo — a lista operacional fica em `quartos`."""
    contexto = services.visao_geral()
    contexto["config_governanca"] = ConfiguracaoGovernanca.get()
    contexto["desfazer"] = _desfazer_pendente(request)
    return render(request, "governanca/visao.html", contexto)


@never_cache
@requer_modulo(Modulo.GOVERNANCA)
@requer_gerencia
def configuracao(request):
    config = ConfiguracaoGovernanca.get()
    form = ConfiguracaoGovernancaForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        from apps.nucleo.models import registrar_auditoria
        form.save()
        registrar_auditoria(request.user, "governanca_configuracao", config,
            {"ativa": config.ativa, "horario": str(config.horario), "distribuir": config.distribuir})
        messages.success(request, "Rotina da governança atualizada.")
        return redirect("governanca:configuracao")
    return render(request, "governanca/configuracao.html", {"form": form, "config": config})


@requer_modulo(Modulo.GOVERNANCA)
@require_POST
def restricao(request, pk):
    uh = get_object_or_404(UH, pk=pk)
    form = RestricaoLimpezaForm(request.POST)
    if form.is_valid():
        try:
            services.registrar_restricao(uh, request.user, **form.cleaned_data)
            messages.success(request, "Preferência de atendimento registrada.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        messages.error(request, "Confira o horário e a preferência de limpeza.")
    return redirect("governanca:quarto", pk=pk)


@never_cache
@requer_modulo(Modulo.GOVERNANCA)
def atualizacoes(request):
    from django.db.models import Count, Max, Q
    dados = TarefaGovernanca.objects.aggregate(
        ultima=Max("atualizada_em"), total=Count("pk"),
        pendentes=Count("pk", filter=Q(status=TarefaGovernanca.Status.PENDENTE)),
        em_andamento=Count("pk", filter=Q(status=TarefaGovernanca.Status.EM_ANDAMENTO)))
    dados["quartos_atualizados_em"] = StatusLimpeza.objects.aggregate(ultima=Max("atualizado_em"))["ultima"]
    return JsonResponse(dados)


@requer_modulo(Modulo.GOVERNANCA)
def quartos(request):
    """A lista operacional: uma linha por quarto, com o próximo passo de cada um."""
    # Lista de montagem de camas das chegadas do dia (vem de Reservas, se ativo).
    from django.utils import timezone

    from apps.nucleo.models import modulo_ativo

    montagem = []
    if modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import montagem_do_dia
        montagem = montagem_do_dia(timezone.localdate())

    contexto = _contexto_quadro(request, request.user)
    # A visão geral manda para cá já filtrado ("3 quartos esperando inspeção" abre a
    # lista nesses três); sem `?estado=`, vale a última escolha de quem está usando.
    estado = request.GET.get("estado")
    contexto.update({
        "tipos": TarefaGovernanca.Tipo.choices, "montagem": montagem,
        "filtro_inicial": estado if estado in StatusLimpeza.Situacao.values else "",
    })
    return render(request, "governanca/quartos.html", contexto)


@requer_modulo(Modulo.GOVERNANCA)
def quarto(request, pk):
    """A ficha de um quarto: como ele está, quem está dentro e o próximo passo.

    É o gesto do tablet: a supervisora toca na porta na parede de blocos e
    resolve o quarto ali, em vez de sair da visão geral e caçar a linha numa
    lista de 24. Com HTMX abre na gaveta da casa; sem JavaScript, como página.
    """
    uh = get_object_or_404(UH, pk=pk)
    linha = services.quarto(uh)
    if linha is None:   # day-use ou quarto inativo: não é da governança
        return redirect("governanca:quartos")
    gabarito = ("governanca/partials/quarto_sheet.html"
                if request.headers.get("HX-Request") else "governanca/quarto.html")
    # De onde a pessoa veio, para a ação devolvê-la ao mesmo lugar.
    voltar = request.GET.get("voltar", "")
    return render(request, gabarito, {
        "ln": linha, "uh": uh,
        "restricao_form": RestricaoLimpezaForm(),
        "voltar": voltar if voltar in ("painel", "quartos") else "",
    })


@requer_modulo(Modulo.GOVERNANCA)
def minha_fila(request):
    """A fila da camareira, feita para o celular dela: os quartos DELA, na ordem
    de atacar, com um botão grande por quarto. A lista de quartos continua sendo
    a mesa da supervisora."""
    return render(request, "governanca/fila.html", _contexto_fila(request, request.user))


@requer_modulo(Modulo.GOVERNANCA)
def reportar(request, pk):
    """"Reportar problema": a camareira acha o chuveiro pingando e abre a ordem de
    serviço dali mesmo, sem sair da fila.

    Quem cria a OS é a Manutenção, pelo service público dela — a Governança não
    importa models de lá, e sem o módulo ativo o botão nem aparece. A OS nasce
    SEM bloquear o quarto: quem decide tirar a unidade de operação é a Manutenção,
    não a camareira.
    """
    from apps.nucleo.models import modulo_ativo

    uh = get_object_or_404(UH, pk=pk)
    form = ReportarProblemaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        if not modulo_ativo(Modulo.MANUTENCAO):
            form.add_error(None, "O módulo Manutenção está desativado. Avise a recepção.")
        else:
            from apps.manutencao import services as manutencao

            manutencao.abrir_os(
                request.user, uh=uh,
                titulo=f"Problema no {uh.numero} (governança)",
                descricao=form.cleaned_data["descricao"],
            )
            resposta = _resposta_acao(request, f"Chamado aberto para o {uh.numero}. "
                                     "Ele já aparece na lista da manutenção.")
            if request.headers.get("HX-Request"):
                resposta["HX-Retarget"] = "#gov-fila"
                resposta["HX-Reswap"] = "innerHTML"
                resposta["X-Gov-Registrado"] = "1"
            return resposta
    gabarito = ("governanca/partials/reportar_modal.html"
                if request.headers.get("HX-Request") else "governanca/reportar.html")
    return render(request, gabarito, {"uh": uh, "form": form})


@requer_modulo(Modulo.GOVERNANCA)
def nova_tarefa(request):
    if request.method != "POST":
        return redirect("governanca:quartos")
    try:
        uh_id = identificador_valido(request.POST.get("uh"), nome="Quarto")
    except ValidationError as erro:
        return _resposta_acao(request, " ".join(erro.messages), tipo="error")
    uh = get_object_or_404(UH, pk=uh_id)
    tipo = request.POST.get("tipo") or TarefaGovernanca.Tipo.FAXINA
    if tipo not in TarefaGovernanca.Tipo.values:   # não confia no POST
        tipo = TarefaGovernanca.Tipo.FAXINA
    tarefa = services.abrir_faxina(uh, tipo=tipo, usuario=request.user,
                                   origem="manual")
    # "Começar limpeza" num quarto sem faxina na fila: abrir e já começar é UM gesto
    # só para quem está com o pano na mão — dois botões seguidos ("abrir" e depois
    # "iniciar") era o que mais confundia quem pegava o sistema pela primeira vez.
    if request.POST.get("iniciar"):
        try:
            services.iniciar_tarefa(tarefa, request.user)
        except ValidationError as erro:
            return _resposta_acao(request, " ".join(erro.messages), tipo="error")
        return _resposta_acao(request, f"Limpeza do {uh.numero} começou.")
    return _resposta_acao(request, f"{uh.numero} entrou na fila de limpeza.")


@requer_modulo(Modulo.GOVERNANCA)
def tarefa_acao(request, pk):
    if request.method != "POST":
        return redirect("governanca:quartos")
    tarefa = get_object_or_404(TarefaGovernanca, pk=pk)
    acao = request.POST.get("acao")
    aviso = ""
    if acao == "atribuir":
        try:
            services.atribuir_tarefa(tarefa, request.POST.get("camareira"), request.user)
        except ValidationError as erro:
            return _resposta_acao(request, " ".join(erro.messages), tipo="error")
        aviso = (
            f"{tarefa.uh.numero} com {tarefa.camareira.get_full_name() or tarefa.camareira.username}."
            if tarefa.camareira else f"{tarefa.uh.numero} sem camareira."
        )
    elif acao == "iniciar":
        try:
            services.iniciar_tarefa(tarefa, request.user)
        except ValidationError as erro:
            return _resposta_acao(request, " ".join(erro.messages), tipo="error")
        aviso = f"Faxina do {tarefa.uh.numero} iniciada."
    elif acao == "concluir":
        services.concluir_tarefa(tarefa, request.user)
        aviso = f"Limpeza do {tarefa.uh.numero} concluída. Aguardando inspeção."
    return _resposta_acao(request, aviso)


@requer_modulo(Modulo.GOVERNANCA)
def distribuir(request):
    """Divide os quartos a limpar sem camareira entre quem está de turno hoje.

    Um toque no lugar de abrir 12 `<select>`. Sem ninguém de turno na Escala não
    há em quem dividir — a tela diz isso em vez de espalhar faxina pela casa.
    """
    if request.method != "POST":
        return redirect("governanca:quartos")
    resultado = services.distribuir_fila(request.user)
    if resultado["motivo"] == "sem_login":
        nomes = ", ".join(resultado["sem_login"])
        return _resposta_acao(
            request,
            f'{nomes} está de turno hoje, mas sem acesso ao CRM. Ative o acesso na ficha do funcionário para distribuir os quartos.'
            if len(resultado["sem_login"]) == 1 else
            f'{nomes} estão de turno hoje, mas sem acesso ao CRM. Ative o acesso na ficha de cada funcionário para distribuir os quartos.',
            tipo="warning")
    if resultado["motivo"] == "sem_turno":
        return _resposta_acao(
            request,
            "Não há funcionários escalados hoje. Escolha quem limpa cada quarto.",
            tipo="warning")
    if not resultado["atribuidas"]:
        return _resposta_acao(request, "Todo quarto da fila já tem camareira.")
    n = resultado["atribuidas"]
    return _resposta_acao(
        request,
        f"{n} quarto{'s' if n > 1 else ''} divididos entre "
        f"{resultado['equipe']} de turno.")


@requer_modulo(Modulo.GOVERNANCA)
def status_marcar(request, pk):
    if request.method != "POST":
        return redirect("governanca:quartos")
    uh = get_object_or_404(UH, pk=pk)
    situacao = request.POST.get("situacao")
    aviso = ""
    if situacao == "reprovada":
        # Supervisora devolveu o quarto: volta para a fila com motivo registrado.
        try:
            services.reprovar_inspecao(uh, request.user, request.POST.get("motivo", ""))
        except ValidationError as erro:
            return _resposta_acao(request, " ".join(erro.messages), tipo="error")
        aviso = f"{uh.numero} reprovado. Voltou para a fila de limpeza."
    elif situacao == StatusLimpeza.Situacao.INSPECIONADA:
        try:
            services.inspecionar(uh, request.user)
        except ValidationError as erro:
            return _resposta_acao(request, " ".join(erro.messages), tipo="error")
        # Liberar o quarto para a recepção é o gesto mais caro da tela: em vez de
        # perguntar antes, a próxima tela traz o "Desfazer" à mão. E sem aviso em
        # cima: a barra já diz o que aconteceu — duas mensagens para o mesmo
        # gesto é ruído, e o aviso ainda passava por cima do título da página.
        _oferecer_desfazer(request, uh, services.frase_de_aprovacao(uh))
    elif situacao in StatusLimpeza.Situacao.values:
        services.definir_status(uh, situacao, request.user)
        aviso = f"{uh.numero}: {dict(StatusLimpeza.Situacao.choices)[situacao].lower()}."
    return _resposta_acao(request, aviso)


@requer_modulo(Modulo.GOVERNANCA)
def desfazer_aprovacao(request, pk):
    """Desfaz o «Aprovar limpeza»: o quarto volta a esperar a supervisora.

    Idempotente — o segundo toque (ou o botão de voltar do navegador) encontra o
    quarto já fora do aprovado e não faz nada.
    """
    if request.method != "POST":
        return redirect("governanca:quartos")
    uh = get_object_or_404(UH, pk=pk)
    services.desfazer_inspecao(uh, request.user)
    return _resposta_acao(request, f"{uh.numero} voltou para a conferência.")


@requer_modulo(Modulo.GOVERNANCA)
def ronda(request, pk):
    """Conferência de ocupação: a camareira registra o que VIU no quarto. Um toque,
    sem recarregar a tela (HTMX) — e cada toque é uma linha nova no histórico."""
    if request.method != "POST":
        return redirect("governanca:quartos")
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
