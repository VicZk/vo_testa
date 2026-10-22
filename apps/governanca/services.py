"""Serviços da Governança — interface pública (o Mapa de quartos consome daqui)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.nucleo.models import registrar_auditoria

from .models import ConferenciaOcupacao, StatusLimpeza, TarefaGovernanca


def situacao_uh(uh) -> StatusLimpeza:
    return StatusLimpeza.objects.get_or_create(uh=uh)[0]


def uh_pronta_para_checkin(uh) -> bool:
    """Limpa ou inspecionada. Interface pública para Reservas (guard de entrada)."""
    return situacao_uh(uh).pronta


def status_por_uh() -> dict:
    """{uh_id: situacao} — usado pelo Mapa de quartos."""
    return {s.uh_id: s.situacao for s in StatusLimpeza.objects.all()}


def definir_status(uh, situacao, usuario=None):
    status = situacao_uh(uh)
    status.situacao = situacao
    status.atualizado_por = usuario
    status.save()
    return status


def abrir_faxina(uh, tipo=TarefaGovernanca.Tipo.FAXINA, usuario=None, origem="manual"):
    """Marca o quarto como sujo e cria a tarefa de faxina (evita duplicar pendente).

    Toque duplo e duas abas chegam aqui juntos («Começar limpeza» abre e já começa
    a faxina). A trava na situação do quarto põe um pedido atrás do outro e o
    segundo acha a tarefa do primeiro. Trava a linha da própria Governança, não a
    UH: o check-out chega aqui por sinal, dentro da transação de Reservas. E faxina
    que já começou não rebaixa o quarto para «A limpar» — ele ficava sujo com
    alguém limpando, e o botão da linha não o tirava mais de lá.
    """
    from django.db import transaction

    from apps.nucleo.sistema import travar

    with transaction.atomic():
        travar(situacao_uh(uh))
        tarefa = TarefaGovernanca.objects.filter(
            uh=uh, tipo=tipo,
            status__in=[TarefaGovernanca.Status.PENDENTE, TarefaGovernanca.Status.EM_ANDAMENTO],
        ).first()
        if tarefa and tarefa.status == TarefaGovernanca.Status.EM_ANDAMENTO:
            return tarefa
        definir_status(uh, StatusLimpeza.Situacao.SUJA, usuario)
        if tarefa:
            return tarefa
        return TarefaGovernanca.objects.create(uh=uh, tipo=tipo, origem=origem)


def gerar_arrumacoes_do_dia(usuario=None) -> int:
    """Uma arrumação para cada quarto ocupado em que o hóspede continua (rotina da
    manhã). Não duplica: quarto com arrumação pendente ou em andamento fica como está.
    Sem o módulo Reservas não há como saber quem está em casa — nada a fazer."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    if not modulo_ativo(Modulo.RESERVAS):
        return 0
    from apps.reservas.services import uhs_em_permanencia

    criadas = 0
    for uh in uhs_em_permanencia():
        ja_tem = TarefaGovernanca.objects.filter(
            uh=uh, tipo=TarefaGovernanca.Tipo.ARRUMACAO,
            status__in=[TarefaGovernanca.Status.PENDENTE, TarefaGovernanca.Status.EM_ANDAMENTO],
        ).exists()
        if not ja_tem:
            abrir_faxina(uh, tipo=TarefaGovernanca.Tipo.ARRUMACAO, usuario=usuario,
                         origem="arrumacao_diaria")
            criadas += 1
    return criadas


def iniciar_tarefa(tarefa, usuario=None):
    from django.db import transaction

    from apps.nucleo.sistema import travar

    with transaction.atomic():
        travar(tarefa)
        if tarefa.status == TarefaGovernanca.Status.EM_ANDAMENTO:
            # Já começou (toque duplo, outra aba). Se o quarto ficou «A limpar» com
            # a limpeza em andamento, acerta: é o que ele está.
            if situacao_uh(tarefa.uh).situacao == StatusLimpeza.Situacao.SUJA:
                definir_status(tarefa.uh, StatusLimpeza.Situacao.EM_LIMPEZA, usuario)
            return tarefa
        if tarefa.status != TarefaGovernanca.Status.PENDENTE:
            return tarefa  # concluída — idempotente
        tarefa.status = TarefaGovernanca.Status.EM_ANDAMENTO
        tarefa.iniciada_em = timezone.now()
        tarefa.save()
        definir_status(tarefa.uh, StatusLimpeza.Situacao.EM_LIMPEZA, usuario)
    return tarefa


def concluir_tarefa(tarefa, usuario=None):
    if tarefa.status == TarefaGovernanca.Status.CONCLUIDA:
        return tarefa  # idempotente — não re-dispara o sinal nem re-audita
    tarefa.status = TarefaGovernanca.Status.CONCLUIDA
    tarefa.concluida_em = timezone.now()
    tarefa.save()
    definir_status(tarefa.uh, StatusLimpeza.Situacao.LIMPA, usuario)
    registrar_auditoria(usuario, "faxina_concluida", tarefa, {"quarto": tarefa.uh.numero})
    # A Lavanderia (se ativa) recolhe o enxoval sujo do quarto — via sinal.
    from apps.nucleo.sinais import emitir

    from .signals import faxina_concluida

    emitir(faxina_concluida, sender=TarefaGovernanca, uh=tarefa.uh,
           tarefa=tarefa, usuario=usuario)
    return tarefa


def _faxina_a_julgar(uh):
    """A última faxina entregue neste quarto, se ainda não foi julgada — é ela que a
    supervisora aprova ou reprova. Inspecionar duas vezes não carimba a faxina da
    semana passada (nem conta duas no relatório); quarto que nunca passou pela fila
    ainda pode ser inspecionado, só não entra no relatório por camareira."""
    tarefa = (
        TarefaGovernanca.objects.filter(uh=uh, status=TarefaGovernanca.Status.CONCLUIDA)
        .order_by("-concluida_em", "-pk")
        .first()
    )
    if tarefa and (tarefa.inspecionada_em or tarefa.reprovada_em):
        return None
    return tarefa


def inspecionar(uh, usuario=None):
    """Supervisora aprovou: o quarto fica pronto e a faxina leva o carimbo de quem
    inspecionou (o relatório de inspecionados × reprovados sai daqui)."""
    tarefa = _faxina_a_julgar(uh)
    if tarefa:
        tarefa.inspecionada_em = timezone.now()
        tarefa.inspecionada_por = usuario
        tarefa.save(update_fields=["inspecionada_em", "inspecionada_por"])
    return definir_status(uh, StatusLimpeza.Situacao.INSPECIONADA, usuario)


def reprovar_inspecao(uh, usuario=None, motivo=""):
    """Supervisora reprovou: o quarto volta para a fila (nova faxina, origem
    "reprovada") e fica registrado quem reprovou, quando e por quê."""
    tarefa = _faxina_a_julgar(uh)
    if tarefa:
        tarefa.reprovada_em = timezone.now()
        tarefa.motivo_reprovacao = (motivo or "")[:200]
        tarefa.save(update_fields=["reprovada_em", "motivo_reprovacao"])
    nova = abrir_faxina(uh, usuario=usuario, origem="reprovada")
    # O motivo viaja com a faxina nova: quem for limpar lê na própria linha por que
    # o quarto voltou, em vez de descobrir no corredor.
    if motivo and not nova.observacoes:
        nova.observacoes = motivo[:200]
        nova.save(update_fields=["observacoes"])
    registrar_auditoria(usuario, "inspecao_reprovada", nova,
                        {"quarto": uh.numero, "motivo": motivo or ""})
    return nova


def tarefas_ativas():
    return (
        TarefaGovernanca.objects.exclude(status=TarefaGovernanca.Status.CONCLUIDA)
        .select_related("uh", "uh__tipo", "camareira")
    )


# Urgência: o que precisa de ação sobe. (a limpar → em limpeza → limpa → inspecionada)
_ORDEM_LIMPEZA = {
    StatusLimpeza.Situacao.SUJA: 0,
    StatusLimpeza.Situacao.EM_LIMPEZA: 1,
    StatusLimpeza.Situacao.LIMPA: 2,
    StatusLimpeza.Situacao.INSPECIONADA: 3,
}

# ───────── O ciclo do quarto, em palavras de quem nunca trabalhou em hotel ─────────
#
# O model fala a língua da hotelaria ("Inspecionado"); a TELA fala a língua de quem
# está começando. Uma fonte de verdade só para o texto da Governança — a etiqueta do
# admin e dos outros módulos continua a do model.

CICLO = [
    {
        "cod": StatusLimpeza.Situacao.SUJA,
        "rotulo": "A limpar",
        "resumo": "O quarto precisa de limpeza.",
        "quem": "Camareira",
        "ajuda": "Entra aqui sozinho quando o hóspede faz check-out, quando a "
                 "supervisora devolve o quarto ou quando alguém pede limpeza.",
    },
    {
        "cod": StatusLimpeza.Situacao.EM_LIMPEZA,
        "rotulo": "Em limpeza",
        "resumo": "Alguém está limpando agora.",
        "quem": "Camareira",
        "ajuda": "A camareira tocou em «Começar limpeza». O relógio da faxina "
                 "começa a contar aqui.",
    },
    {
        "cod": StatusLimpeza.Situacao.LIMPA,
        "rotulo": "Limpo",
        "resumo": "A limpeza acabou e falta a supervisora conferir.",
        "quem": "Supervisora",
        "ajuda": "Quarto limpo ainda NÃO está liberado: a supervisora passa, "
                 "aprova ou devolve para limpar de novo.",
    },
    {
        "cod": StatusLimpeza.Situacao.INSPECIONADA,
        "rotulo": "Pronto",
        "resumo": "Conferido pela supervisora. Vago, pode receber hóspede; "
                  "ocupado, já está arrumado.",
        "quem": "—",
        "ajuda": "Na hotelaria chama-se «inspecionado». É o único estado em que o "
                 "quarto está liberado para a recepção entregar a chave — por isso "
                 "o quarto que já tem hóspede aparece como «Arrumado».",
    },
]
SITUACAO_SIMPLES = {e["cod"]: e["rotulo"] for e in CICLO}

# ───────────────── A outra metade da pergunta: quem está no quarto ─────────────────
#
# Hotelaria não pensa só em limpeza: pensa em OCUPAÇÃO × LIMPEZA. "Vago sujo" é
# faxina de saída; "ocupado sujo" é arrumação com as coisas do hóspede dentro;
# "vago pronto" é quarto vendável; e "chega hoje" muda a urgência de tudo. A tela
# falava só de limpeza — a supervisora tinha de abrir o mapa de reservas ao lado
# para saber se podia mandar alguém entrar.
#
# A ocupação vem de Reservas por service (`ocupacao_por_uh`), nunca por model.

OCUPACAO = {
    "vago": ("Vago", "Sem hóspede — o quarto está livre."),
    "ocupado": ("Ocupado", "Hóspede em casa, continua amanhã."),
    "sai_hoje": ("Sai hoje", "O hóspede vai embora hoje: o quarto suja na saída."),
    "chega_hoje": ("Chega hoje", "Chega hóspede: tem de estar pronto antes."),
    "bloqueado": ("Bloqueado", "Em manutenção — fora de operação."),
}


def ocupacao_do_quarto(info, *, bloqueado=False, sem_base=False) -> dict:
    """Quem está no quarto hoje, em palavras de gente. Função pura (nenhuma consulta).

    `info` = o dicionário do quarto em `reservas.ocupacao_por_uh` (None = o PMS
    considera o quarto vazio); `sem_base` = Reservas inativo, e aí a Governança
    não afirma nada sobre ocupação (degradação graciosa).

    Devolve `{cod, rotulo, ajuda, hospede, chegada}`. `chegada` viaja separado do
    código porque o caso mais apertado do dia é o back-to-back: **sai hoje E chega
    hoje** no mesmo quarto — a camareira tem uma janela entre as duas coisas.
    """
    if sem_base:
        return {"cod": "", "rotulo": "", "ajuda": "", "hospede": "", "chegada": False}
    chegada = bool(info and info["chegada"])
    if bloqueado:
        cod = "bloqueado"
    elif info and info["ocupado"]:
        cod = "sai_hoje" if info["saida_ate"] else "ocupado"
    elif chegada:
        cod = "chega_hoje"
    else:
        cod = "vago"
    rotulo, ajuda = OCUPACAO[cod]
    return {
        "cod": cod, "rotulo": rotulo, "ajuda": ajuda,
        "hospede": (info or {}).get("hospede", ""), "chegada": chegada,
    }

# Por que o quarto está sujo — a origem da faxina vira frase de gente.
_MOTIVO_DA_FAXINA = {
    "checkout": "O hóspede fez check-out.",
    "troca": "O hóspede trocou de quarto.",
    "manutencao": "O quarto saiu da manutenção.",
    "arrumacao_diaria": "O hóspede continua no quarto — é a arrumação do dia.",
    "reprovada": "A supervisora devolveu o quarto para limpar de novo.",
    "portal": "O próprio hóspede pediu limpeza pelo celular.",
    "manual": "Alguém marcou o quarto como sujo.",
}


def _quem(usuario) -> str:
    return (usuario.get_full_name() or usuario.username) if usuario else ""


def _tem_hospede(ocupacao) -> bool:
    return bool(ocupacao) and ocupacao.get("cod") in ("ocupado", "sai_hoje")


def rotulo_do_estado(situacao, ocupacao=None) -> str:
    """O nome do estado na TELA, lido junto com a ocupação.

    "Pronto" quer dizer «conferido, pode receber hóspede» — e não serve para um
    quarto que já tem um dentro. Com gente no quarto, limpo e conferido é
    **Arrumado**: é o serviço do dia feito, não uma unidade vendável. Sem essa
    distinção a casa cheia mostrava 21 blocos dizendo "pode receber hóspede".
    """
    if situacao == StatusLimpeza.Situacao.INSPECIONADA and _tem_hospede(ocupacao):
        return "Arrumado"
    return SITUACAO_SIMPLES.get(situacao, situacao)


def explicar_estado(situacao, tarefa, status, ocupacao=None, *, com_fila=True) -> str:
    """Uma frase curta dizendo POR QUE o quarto está neste estado e o que falta.

    É o que ensina o fluxo a quem pega o sistema pela primeira vez: a tela não diz
    só «Limpo», diz «Limpo às 11:05 por Maria — falta a supervisora conferir».

    `com_fila=False` corta o "Na fila de Maria": na fila da própria Maria, dizer o
    nome dela em cada cartão é ruído.
    """
    quando = f" às {timezone.localtime(status.atualizado_em):%H:%M}" if status.atualizado_em else ""
    quem = _quem(getattr(status, "atualizado_por", None))
    if ocupacao and ocupacao.get("cod") == "bloqueado":
        # Quarto em reparo não recebe hóspede nem entra em fila de ninguém, esteja
        # ele limpo ou sujo — a frase do estado dizia "pode receber hóspede".
        estado = SITUACAO_SIMPLES.get(situacao, situacao).lower()
        return (f"Em manutenção — fora de operação até o reparo terminar "
                f"(hoje está {estado}).")
    if situacao == StatusLimpeza.Situacao.SUJA:
        motivo = _MOTIVO_DA_FAXINA.get(tarefa.origem if tarefa else "", "")
        if tarefa and tarefa.origem == "reprovada" and tarefa.observacoes:
            motivo = f"Devolvido para limpar: {tarefa.observacoes.rstrip('.')}."
        if not com_fila:
            return motivo.strip()
        fila = (f" Na fila de {_quem(tarefa.camareira)}." if tarefa and tarefa.camareira
                else " Ninguém começou ainda.")
        return (motivo + fila).strip()
    if situacao == StatusLimpeza.Situacao.EM_LIMPEZA:
        if tarefa and tarefa.iniciada_em:
            inicio = f"{timezone.localtime(tarefa.iniciada_em):%H:%M}"
            return (f"{_quem(tarefa.camareira)} começou às {inicio}."
                    if tarefa.camareira else f"Limpeza começou às {inicio}.")
        return "Limpeza em andamento."
    if situacao == StatusLimpeza.Situacao.LIMPA:
        por = f" por {quem}" if quem else ""
        return f"Limpo{quando}{por}. Falta a supervisora conferir."
    sem_carimbo = not getattr(status, "atualizado_por_id", None)
    if _tem_hospede(ocupacao):
        # Com hóspede dentro, "pode receber hóspede" não quer dizer nada: o que
        # interessa é se a arrumação do dia saiu.
        if sem_carimbo:
            return "Sem arrumação registrada hoje."
        falta = ("O hóspede sai hoje — a faxina nasce no check-out."
                 if ocupacao["cod"] == "sai_hoje" else "O hóspede continua no quarto.")
        return f"Arrumado{quando}. {falta}"
    # "Pronto" sem ninguém no `atualizado_por` é o estado de nascimento do quarto
    # (banco novo, ou módulo ativado numa casa que já roda): ninguém inspecionou,
    # e a tela não inventa um carimbo que não existe.
    if sem_carimbo:
        return "Sem faxina registrada ainda. Disponível para a recepção."
    return f"Conferido e aprovado{quando}. Pode receber hóspede."


def _estado_dos_quartos(dia=None) -> dict:
    """Uma passada pelos quartos FÍSICOS (day-use fora) com tudo que as duas telas da
    Governança precisam: limpeza, tarefa ativa, a última conferência da ronda e o
    veredito AO VIVO contra o PMS.

    Consultas fixas (quartos, status, tarefas, conferências, PMS, bloqueios) — 24
    quartos não viram 24 consultas.
    """
    from apps.nucleo.models import UH, TipoUH

    dia = dia or timezone.localdate()
    tarefas = {}
    for t in tarefas_ativas():
        tarefas.setdefault(t.uh_id, t)  # a mais recente por quarto (ordering do model)

    quartos = list(
        UH.objects.select_related("tipo")
        .exclude(status=UH.Status.INATIVA)
        .exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
    )
    # Todos os status numa consulta só (com quem mexeu por último — a frase da linha
    # diz "limpo por Maria"). Quarto ainda sem registro aparece com a situação padrão
    # («Pronto» — ver `StatusLimpeza`) sem gravar nada: abrir a tela não escreve no banco.
    existentes = {
        s.uh_id: s for s in
        StatusLimpeza.objects.filter(uh__in=quartos).select_related("atualizado_por")
    }
    conferencias = conferencias_do_dia(dia)
    pms = ocupacao_pms(dia)
    bloqueados = bloqueios_do_dia(dia)

    linhas = []
    for uh in quartos:
        status = existentes.get(uh.pk) or StatusLimpeza(uh=uh)
        conf = conferencias.get(uh.pk)
        info = (pms or {}).get(uh.pk)
        bloqueado = uh.status == UH.Status.BLOQUEADA or uh.pk in bloqueados
        divergencia = (
            classificar(conf.visto, info, bloqueado=bloqueado, sem_base=pms is None)
            if conf else ""
        )
        tarefa = tarefas.get(uh.pk)
        # A outra metade da pergunta: limpeza diz como o quarto está, ocupação diz
        # quem está dentro (e se alguém chega hoje). Sai do `pms` que já foi
        # consultado — nenhuma consulta nova por quarto. Vem ANTES do rótulo e da
        # frase porque as duas mudam de acordo com ela.
        ocupacao = ocupacao_do_quarto(info, bloqueado=bloqueado,
                                      sem_base=pms is None)
        linhas.append({
            "uh": uh,
            "situacao": status.situacao,
            "ocupacao": ocupacao,
            # Rótulo da TELA (plain) + a frase que explica por que o quarto está
            # assim e o que falta — é o que ensina o fluxo a quem está começando.
            "situacao_label": rotulo_do_estado(status.situacao, ocupacao),
            "explicacao": explicar_estado(status.situacao, tarefa, status, ocupacao),
            # O registro cru vai junto: quem quiser outra frase sobre o MESMO
            # estado (a fila da camareira monta a dela) não refaz a consulta.
            "status": status,
            "tarefa": tarefa,
            "atualizado_em": status.atualizado_em,
            "conferencia": conf,
            "pms": info,
            "bloqueado": bloqueado,
            "bloqueio_motivo": bloqueados.get(uh.pk, ""),
            # Ao vivo, não o veredito gravado: divergência que a recepção já resolveu
            # (lançou o check-out, fez o check-in) sai da tela sozinha.
            "divergencia": divergencia,
            "divergencia_rotulo": _ROTULO_DIVERGENCIA.get(divergencia, ""),
            "divergente": divergencia in ConferenciaOcupacao.DIVERGENTES,
        })
    # `pms` vai junto: quem já pagou a consulta não deve pagar de novo (a visão
    # geral precisa das chegadas de hoje, que vêm deste mesmo dicionário).
    return {"dia": dia, "sem_base": pms is None, "linhas": linhas, "pms": pms}


def painel_limpeza(dia=None):
    """Tela única de Governança: uma linha por quarto FÍSICO (day-use fora), com o
    status de limpeza + a tarefa ativa (se houver), ordenada por urgência. Substitui
    as duas tabelas (fila de faxina + situação dos quartos) por uma só."""
    dados = _estado_dos_quartos(dia)
    linhas = dados["linhas"]
    contagem = {c: 0 for c, _ in StatusLimpeza.Situacao.choices}
    for ln in linhas:
        contagem[ln["situacao"]] += 1
    # Mesma ordem do plano do dia: chegada sem quarto pronto → saída de hoje →
    # ocupado a arrumar → o resto; dentro de cada grupo, por urgência de limpeza.
    # A lista é a ferramenta de quem está trabalhando: ela já abre na ordem de
    # atacar, sem a camareira ter de cruzar com o mapa de reservas.
    linhas.sort(key=lambda ln: (_ORDEM_PLANO.get(prioridade_do_quarto(ln), 9),
                                _ORDEM_LIMPEZA.get(ln["situacao"], 9),
                                ln["uh"].numero))
    return {
        "linhas": linhas,
        "contagem": contagem,
        "dia": dados["dia"],
        "sem_base": dados["sem_base"],
        "divergencias": sum(1 for ln in linhas if ln["divergente"]),
        # Só "sem bagagem" no quadro não é motivo para a tela gritar em vermelho.
        "divergencias_graves": sum(
            1 for ln in linhas
            if ln["divergente"] and explicar_divergencia(ln["divergencia"])[1] != "baixa"
        ),
        "conferidos": sum(1 for ln in linhas if ln["conferencia"]),
        "a_conferir": sum(1 for ln in linhas
                          if not ln["conferencia"] and not ln["bloqueado"]),
    }


# ───────────────────── Visão geral da Governança (a tela de entrada) ─────────────────────
#
# A lista é a ferramenta de quem está trabalhando; a visão geral é a resposta para
# "como está a casa agora?". Mesma leitura do corredor do Mapa de quartos: a casa
# fala primeiro, em blocos coloridos, e cada bloco leva para a ação certa.

# Estado de limpeza → classe da porta no corredor. Classes próprias (e não as
# `sit-*` do mapa de reservas): lá a cor fala de ocupação, aqui de limpeza, e o
# verde/azul tem de bater com o `.selo` do mesmo estado na lista ao lado.
_COR_DA_PORTA = {
    StatusLimpeza.Situacao.SUJA: "limp-suja",
    StatusLimpeza.Situacao.EM_LIMPEZA: "limp-em_limpeza",
    StatusLimpeza.Situacao.LIMPA: "limp-limpa",
    StatusLimpeza.Situacao.INSPECIONADA: "limp-inspecionada",
}


def _hora_do_checkin():
    """Horário em que o primeiro hóspede pode entrar (configuração de Reservas), ou
    None se o módulo não estiver ativo. É o prazo real da governança no dia."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    if not modulo_ativo(Modulo.RESERVAS):
        return None
    from apps.reservas.services import configuracao_reservas

    return configuracao_reservas().hora_checkin


# ─────────────────────── O plano do dia (a ordem de atacar) ───────────────────────
#
# A supervisora chega às 7h e a pergunta é uma só: por onde começar. A tela dava a
# casa em estados de limpeza e deixava a conta com ela — qual quarto tem hóspede
# chegando, qual vai sujar hoje, qual só precisa da arrumação. A ordem é sempre a
# mesma, e é esta:
#
#   1. chegada de hoje com o quarto ainda não pronto  — tem hóspede na porta;
#   2. saída de hoje                                   — vai sujar, planeje a tarde;
#   3. ocupado pedindo arrumação                       — o serviço do dia;
#   4. o resto                                         — o que sobra, por urgência.
#
# Quarto bloqueado pela Manutenção nunca entra nos três primeiros: não é trabalho
# da governança enquanto o técnico não devolve.

PLANO = [
    {
        "cod": "chegada", "nivel": "alerta",
        "rotulo": "Chegadas de hoje",
        "resumo": "O quarto tem de estar pronto antes de o hóspede chegar.",
    },
    {
        "cod": "saida", "nivel": "aviso",
        "rotulo": "Saídas de hoje",
        "resumo": "Vão sujar: a faxina nasce quando a recepção lança o check-out.",
    },
    {
        "cod": "arrumacao", "nivel": "aviso",
        "rotulo": "Ocupados a arrumar",
        "resumo": "Hóspede em casa — arrumação do dia, com as coisas dele dentro.",
    },
    {
        "cod": "resto", "nivel": "info",
        "rotulo": "O resto da casa",
        "resumo": "Sem hóspede chegando nem saindo hoje: ainda pedem limpeza ou a "
                  "conferência da supervisora.",
    },
]
_ORDEM_PLANO = {etapa["cod"]: i for i, etapa in enumerate(PLANO)}


def prioridade_do_quarto(linha) -> str:
    """Em que grupo do plano do dia este quarto cai. Primeiro que casar vence."""
    ocup = linha.get("ocupacao") or {}
    if linha["bloqueado"]:
        return "resto"
    if ocup.get("chegada"):
        return "chegada"
    if ocup.get("cod") == "sai_hoje":
        return "saida"
    # Ocupado "a arrumar" é ocupado com a LIMPEZA pendente. Ocupado e já limpo só
    # espera a supervisora: aparecia na fila da camareira dizendo "Limpo".
    if ocup.get("cod") == "ocupado" and linha["situacao"] in (
            StatusLimpeza.Situacao.SUJA, StatusLimpeza.Situacao.EM_LIMPEZA):
        return "arrumacao"
    return "resto"


def _falta_fazer(linha) -> bool:
    """O quarto ainda pede alguém? (bloqueado não é trabalho da governança)."""
    return not linha["bloqueado"] and linha["situacao"] != StatusLimpeza.Situacao.INSPECIONADA


def _tempo_ate(hora, dia) -> tuple:
    """("faltam 3h20", atrasado) até o horário de entrada — a resposta de "dá
    tempo?" sem conta nenhuma na cabeça de quem está lendo."""
    if not hora or dia != timezone.localdate():
        return "", False
    from datetime import datetime

    agora = timezone.localtime()
    alvo = timezone.make_aware(datetime.combine(dia, hora), agora.tzinfo)
    minutos = int((alvo - agora).total_seconds() // 60)
    if minutos <= 0:
        return "", True
    if minutos < 60:
        return f"faltam {minutos} min", False
    return f"faltam {minutos // 60}h{minutos % 60:02d}", False


def _quarto_no_plano(linha) -> dict:
    """O que cada quarto mostra na lista do plano."""
    tarefa = linha["tarefa"]
    return {
        "uh": linha["uh"],
        "situacao": linha["situacao"],
        "rotulo": linha["situacao_label"],
        "ocupacao": linha["ocupacao"]["rotulo"],
        "hospede": linha["ocupacao"]["hospede"],
        "pronto": linha["situacao"] == StatusLimpeza.Situacao.INSPECIONADA,
        "camareira": _quem(tarefa.camareira) if tarefa else "",
        "falta": _falta_fazer(linha),
    }


def _montar_plano(linhas, hora_checkin, dia) -> dict:
    """O plano do dia a partir das linhas que a tela já tem (nenhuma consulta nova)."""
    grupos = {etapa["cod"]: [] for etapa in PLANO}
    tranquilos = 0
    for linha in sorted(linhas, key=lambda ln: (_ORDEM_LIMPEZA.get(ln["situacao"], 9),
                                                ln["uh"].numero)):
        cod = prioridade_do_quarto(linha)
        # No "resto" só entra quarto que ainda pede alguém; o que está pronto é
        # contado numa linha só — 15 quartos sem nada a fazer não são um plano.
        if cod == "resto" and not _falta_fazer(linha):
            tranquilos += 1
            continue
        grupos[cod].append(_quarto_no_plano(linha))
    # Dentro das chegadas, quem ainda não está pronto vem primeiro.
    grupos["chegada"].sort(key=lambda q: (q["pronto"], q["uh"].numero))
    a_entregar = sum(1 for q in grupos["chegada"] if not q["pronto"])
    falta_tempo, atrasado = _tempo_ate(hora_checkin, dia)
    return {
        "grupos": [{**etapa, "quartos": grupos[etapa["cod"]]}
                   for etapa in PLANO if grupos[etapa["cod"]]],
        "a_entregar": a_entregar,
        "tranquilos": tranquilos,
        "hora_checkin": hora_checkin,
        "falta_tempo": falta_tempo,
        "atrasado": atrasado,
        "a_fazer": sum(1 for ln in linhas if _falta_fazer(ln)),
    }


def plano_do_dia(dia=None) -> dict:
    """Interface pública do plano do dia (a visão geral monta o seu das mesmas
    linhas, sem pagar as consultas duas vezes)."""
    dados = _estado_dos_quartos(dia)
    return _montar_plano(dados["linhas"], _hora_do_checkin(), dados["dia"])


# ─────────────── Quem limpa: a Escala manda, a lista de todos degrada ───────────────
#
# Escolher a camareira num `<select>` com a casa inteira dentro (recepção, cozinha,
# gerência) era adivinhação: quem está de folga aparecia na mesma lista de quem
# está no corredor agora. A Escala sabe quem trabalha hoje — e é o único módulo
# que sabe. Sem ela ativa, a tela não quebra: mostra todo mundo, como antes.


def camareiras_do_dia(dia=None) -> dict:
    """`{"de_turno", "outras", "tem_escala", "sem_login"}` — quem limpa.

    `de_turno` vem da Escala (setor Governança) por interface pública; `outras`
    é o resto dos usuários ativos, que continua disponível para o caso de alguém
    cobrir fora da escala. Sem o módulo Escala, `de_turno` vem vazio e a tela cai
    na lista de sempre.

    `sem_login` são as pessoas escaladas hoje que **não têm login no CRM**: a
    tarefa é de um usuário, então não há a quem atribuir. Vale a pena nomear —
    "ninguém de turno hoje" seria mentira, e a correção é ligar o login na ficha
    do funcionário, não mexer na escala.
    """
    from django.contrib.auth import get_user_model

    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    dia = dia or timezone.localdate()
    de_turno, sem_login = [], []
    if modulo_ativo(Modulo.ESCALA):
        from apps.escala.services import de_turno as escalados

        for func in escalados(dia, setor="governanca"):
            if func.usuario_id and func.usuario.is_active:
                de_turno.append(func.usuario)
            else:
                sem_login.append(func.pessoa.nome)
    ids = {u.pk for u in de_turno}
    outras = [
        u for u in get_user_model().objects.filter(is_active=True)
        .order_by("first_name", "username")
        if u.pk not in ids
    ]
    return {"de_turno": de_turno, "outras": outras, "tem_escala": bool(de_turno),
            "sem_login": sem_login}


def distribuir_fila(operador, dia=None) -> dict:
    """Divide os quartos a limpar SEM camareira entre quem está de turno hoje.

    Equilibrada: cada quarto vai para quem tem menos na mão naquele momento
    (contando o que ela já tinha antes de a tela abrir), e os mais urgentes saem
    primeiro — na mesma ordem do plano do dia. Rodar de novo não embaralha nada:
    quarto que já tem camareira não é tocado.

    Sem ninguém de turno não há em quem dividir: devolve `motivo="sem_turno"` e a
    tela explica, em vez de espalhar faxina para a casa inteira.
    """
    from django.db import transaction
    from django.db.models import Count

    dia = dia or timezone.localdate()
    quem = camareiras_do_dia(dia)
    equipe = quem["de_turno"]
    if not equipe:
        # Escalada sem login no CRM não é "ninguém de turno": a correção é outra.
        motivo = "sem_login" if quem["sem_login"] else "sem_turno"
        return {"atribuidas": 0, "equipe": 0, "motivo": motivo,
                "sem_login": quem["sem_login"]}

    dados = _estado_dos_quartos(dia)
    pendentes = [
        ln for ln in dados["linhas"]
        if not ln["bloqueado"] and ln["tarefa"] and not ln["tarefa"].camareira_id
    ]
    pendentes.sort(key=lambda ln: (_ORDEM_PLANO.get(prioridade_do_quarto(ln), 9),
                                   _ORDEM_LIMPEZA.get(ln["situacao"], 9),
                                   ln["uh"].numero))
    # O que cada uma já tem na mão (numa consulta) — distribuir "do zero" jogaria
    # quatro quartos em cima de quem já está com seis.
    carga = dict.fromkeys([u.pk for u in equipe], 0)
    for linha in (
        TarefaGovernanca.objects
        .filter(camareira__in=equipe)
        .exclude(status=TarefaGovernanca.Status.CONCLUIDA)
        .values("camareira").annotate(n=Count("pk")).order_by()
    ):
        carga[linha["camareira"]] = linha["n"]

    atribuidas, primeira = [], None
    with transaction.atomic():
        for ln in pendentes:
            alvo = min(equipe, key=lambda u: (carga[u.pk], u.pk))
            tarefa = ln["tarefa"]
            tarefa.camareira = alvo
            tarefa.save(update_fields=["camareira"])
            carga[alvo.pk] += 1
            atribuidas.append((ln["uh"].numero, _quem(alvo)))
            primeira = primeira or tarefa
        if atribuidas:
            # Cada tarefa já entra na trilha pelos signals do núcleo; esta linha é
            # a narrativa do gesto — quem mandou dividir, quantos e entre quem.
            registrar_auditoria(
                operador, "fila_distribuida", primeira,
                {"quartos": len(atribuidas), "equipe": len(equipe),
                 "entre": ", ".join(sorted({nome for _, nome in atribuidas}))},
            )
    return {"atribuidas": len(atribuidas), "equipe": len(equipe),
            "motivo": "", "detalhe": atribuidas}


# ───────────────── A fila da camareira (o celular dela, no corredor) ─────────────────
#
# A lista de quartos é a mesa da supervisora: cinco colunas, três botões de ronda,
# um `<select>` por linha. No corredor, de celular, a camareira quer outra coisa —
# os quartos DELA, na ordem de atacar, com UM botão grande por quarto.


def minha_fila(usuario, dia=None) -> dict:
    """Os quartos desta camareira hoje, na ordem do plano do dia.

    Quarto bloqueado pela Manutenção não entra: enquanto o técnico não devolve, a
    faxina não acontece, e ocupar a primeira linha da fila com ele é mandar a
    camareira bater numa porta fechada. Concluídas de hoje ficam no fim, como
    recibo do que ela já entregou.
    """
    dados = _estado_dos_quartos(dia)
    fila, feitas = [], []
    for linha in dados["linhas"]:
        tarefa = linha["tarefa"]
        if not tarefa or tarefa.camareira_id != usuario.pk or linha["bloqueado"]:
            continue
        fila.append({
            **_quarto_no_plano(linha),
            "tarefa": tarefa,
            # Sem o "Na fila de Maria": na fila da própria Maria isso é ruído.
            "explicacao": explicar_estado(linha["situacao"], tarefa, linha["status"],
                                          linha["ocupacao"], com_fila=False),
            "fazendo": tarefa.status == TarefaGovernanca.Status.EM_ANDAMENTO,
            "tipo": tarefa.get_tipo_display(),
            "observacoes": tarefa.observacoes,
            "grupo": prioridade_do_quarto(linha),
        })
    fila.sort(key=lambda q: (_ORDEM_PLANO.get(q["grupo"], 9),
                             not q["fazendo"],          # o que já começou, no alto
                             _ORDEM_LIMPEZA.get(q["situacao"], 9),
                             q["uh"].numero))
    feitas = list(
        TarefaGovernanca.objects
        .filter(camareira=usuario, status=TarefaGovernanca.Status.CONCLUIDA,
                concluida_em__date=dados["dia"])
        .select_related("uh").order_by("-concluida_em")
    )
    return {
        "dia": dados["dia"],
        "fila": fila,
        "fazendo": next((q for q in fila if q["fazendo"]), None),
        "feitas": feitas,
        "hora_checkin": _hora_do_checkin(),
    }


def carga_das_camareiras(dia=None) -> list:
    """Quanto cada camareira tem na mão hoje: na fila, limpando agora e já entregue.
    Duas consultas, não uma por pessoa."""
    from django.db.models import Count, Q

    dia = dia or timezone.localdate()
    ativas = (
        TarefaGovernanca.objects
        .exclude(status=TarefaGovernanca.Status.CONCLUIDA)
        .values("camareira", "camareira__first_name", "camareira__username")
        .annotate(
            pendentes=Count("pk", filter=Q(status=TarefaGovernanca.Status.PENDENTE)),
            fazendo=Count("pk", filter=Q(status=TarefaGovernanca.Status.EM_ANDAMENTO)),
        ).order_by()
    )
    feitas = (
        TarefaGovernanca.objects
        .filter(status=TarefaGovernanca.Status.CONCLUIDA, concluida_em__date=dia)
        .values("camareira").annotate(n=Count("pk")).order_by()
    )
    por_pessoa = {}
    for linha in ativas:
        por_pessoa[linha["camareira"]] = {
            "nome": (linha["camareira__first_name"] or linha["camareira__username"]
                     or "Sem camareira"),
            "pendentes": linha["pendentes"], "fazendo": linha["fazendo"], "feitas": 0,
        }
    for linha in feitas:
        reg = por_pessoa.setdefault(
            linha["camareira"], {"nome": "", "pendentes": 0, "fazendo": 0, "feitas": 0})
        reg["feitas"] = linha["n"]
    # O nome de quem só tem faxina concluída hoje não vem na primeira consulta.
    faltam = [pk for pk, reg in por_pessoa.items() if pk and not reg["nome"]]
    if faltam:
        from django.contrib.auth import get_user_model
        for u in get_user_model().objects.filter(pk__in=faltam):
            por_pessoa[u.pk]["nome"] = u.get_full_name() or u.username
    for pk, reg in por_pessoa.items():
        if not reg["nome"]:
            reg["nome"] = "Sem camareira"
        reg["na_mao"] = reg["pendentes"] + reg["fazendo"]
        reg["total"] = reg["na_mao"] + reg["feitas"]
        reg["camareira_id"] = pk
    linhas = sorted(por_pessoa.values(), key=lambda r: (-r["na_mao"], -r["feitas"]))
    teto = max([r["total"] for r in linhas] or [1]) or 1
    for reg in linhas:          # largura da barra em % — a comparação é visual
        reg["barra_feitas"] = round(100 * reg["feitas"] / teto)
        reg["barra_fazendo"] = round(100 * reg["fazendo"] / teto)
        reg["barra_pendentes"] = round(100 * reg["pendentes"] / teto)
    return linhas


def visao_geral(dia=None) -> dict:
    """A tela de entrada da Governança: a casa inteira em blocos, o progresso do dia,
    as chegadas que dependem de quarto pronto e o que pede ação agora.

    Consome o mesmo `_estado_dos_quartos` da lista — um retrato só, sem dois números
    diferentes para a mesma coisa na mesma tela.
    """
    from django.urls import reverse

    dados = _estado_dos_quartos(dia)
    linhas = dados["linhas"]
    dia = dados["dia"]
    contagem = {c: 0 for c, _ in StatusLimpeza.Situacao.choices}
    for ln in linhas:
        contagem[ln["situacao"]] += 1

    total = len(linhas)
    prontos = contagem[StatusLimpeza.Situacao.INSPECIONADA]
    pms = dados["pms"] or {}

    portas, chegadas, divergentes = [], [], []
    ocupacao_resumo = dict.fromkeys(OCUPACAO, 0)
    for ln in sorted(linhas, key=lambda x: x["uh"].numero):
        info = pms.get(ln["uh"].pk)
        ocup = ln["ocupacao"]
        chegada = ocup["chegada"]
        pronto = ln["situacao"] == StatusLimpeza.Situacao.INSPECIONADA
        if ocup["cod"]:
            ocupacao_resumo[ocup["cod"]] += 1
        portas.append({
            "uh": ln["uh"],
            "cor": "limp-bloqueada" if ln["bloqueado"] else _COR_DA_PORTA.get(ln["situacao"], ""),
            "situacao": ln["situacao"],
            "rotulo": ln["situacao_label"],
            "explicacao": ln["explicacao"],
            "camareira": (_quem(ln["tarefa"].camareira) if ln["tarefa"] else ""),
            # Ocupação na própria porta: "Sai hoje · Ana Lima" responde o que a
            # supervisora ia buscar no mapa de reservas.
            "ocupacao": ocup["rotulo"],
            "ocupacao_cod": ocup["cod"],
            "hospede": ocup["hospede"],
            "chegada": chegada,
            "bloqueado": ln["bloqueado"],
            "tipo": ln["uh"].tipo.nome,
            "divergente": ln["divergente"],
            "divergencia_rotulo": ln["divergencia_rotulo"],
        })
        if chegada:
            chegadas.append({
                "uh": ln["uh"], "hospede": info["hospede"],
                "situacao": ln["situacao"], "rotulo": ln["situacao_label"],
                "pronto": pronto, "reserva_id": info["reserva_id"],
            })
        if ln["divergente"]:
            divergentes.append(ln)

    chegadas.sort(key=lambda c: (c["pronto"], c["uh"].numero))
    chegadas_atrasadas = [c for c in chegadas if not c["pronto"]]
    hora_checkin = _hora_do_checkin()
    plano = _montar_plano(linhas, hora_checkin, dia)

    # ── O que pede ação agora (mesma linguagem do bloco da Visão geral do CRM) ──
    url_quartos = reverse("governanca:quartos")
    # Níveis no vocabulário da casa (os mesmos da Visão geral do CRM):
    # `alerta` = vermelho (dinheiro/hóspede na porta), `aviso` = âmbar (precisa de
    # alguém hoje), `info` = azul (bom saber).
    def s(n):   # plural como na Visão geral do CRM: "1 quarto", "2 quartos"
        return "s" if n > 1 else ""

    atencao = []
    if chegadas_atrasadas:
        n = len(chegadas_atrasadas)
        quartos = ", ".join(c["uh"].numero.replace("Quarto ", "") for c in chegadas_atrasadas[:6])
        # A lista abre no estado em que esses quartos estão — "a limpar" escondia
        # o quarto que já está limpo e só espera a inspeção.
        estados = {c["situacao"] for c in chegadas_atrasadas}
        atencao.append({
            "nivel": "alerta",
            "rotulo": f"{n} chegada{s(n)} sem quarto pronto",
            "detalhe": f"Quarto{s(n)} {quartos} — hóspede chega hoje.",
            "url": f"{url_quartos}?estado={estados.pop()}" if len(estados) == 1 else url_quartos,
        })
    esperando = contagem[StatusLimpeza.Situacao.LIMPA]
    if esperando:
        atencao.append({
            "nivel": "aviso",
            "rotulo": f"{esperando} quarto{s(esperando)} esperando inspeção",
            "detalhe": "Limpos, mas ainda não liberados para a recepção.",
            "url": f"{url_quartos}?estado={StatusLimpeza.Situacao.LIMPA}",
        })
    if divergentes:
        n = len(divergentes)
        atencao.append({
            "nivel": "alerta",
            "rotulo": f"{n} divergência{s(n)} na ronda",
            "detalhe": "O que a camareira viu não bate com o sistema.",
            "url": reverse("governanca:discrepancias"),
        })
    sem_camareira = sum(
        1 for ln in linhas
        if ln["situacao"] == StatusLimpeza.Situacao.SUJA
        and (not ln["tarefa"] or not ln["tarefa"].camareira_id)
    )
    if sem_camareira:
        atencao.append({
            "nivel": "aviso",
            "rotulo": f"{sem_camareira} quarto{s(sem_camareira)} a limpar sem camareira",
            "detalhe": "Ninguém na fila: escolha quem limpa.",
            "url": f"{url_quartos}?estado={StatusLimpeza.Situacao.SUJA}",
        })
    # Só os quartos que o PMS diz OCUPADOS: a ronda existe para achar o hóspede que
    # saiu sem baixa e o que entrou sem check-in. Contando a casa inteira, um banco
    # novo (e toda manhã antes da ronda) abria com "24 quartos sem ronda hoje" — a
    # mesma regra que a varredura da Auditoria já aplica.
    a_conferir = sum(
        1 for ln in linhas
        if not ln["conferencia"] and not ln["bloqueado"]
        and (pms.get(ln["uh"].pk) or {}).get("ocupado")
    )
    if a_conferir and not dados["sem_base"]:
        atencao.append({
            "nivel": "info",
            "rotulo": f"{a_conferir} quarto{s(a_conferir)} ocupado{s(a_conferir)} "
                      "sem ronda hoje",
            "detalhe": "Ninguém registrou o que viu dentro.",
            "url": url_quartos,
        })

    ciclo = [
        {**etapa, "n": contagem.get(etapa["cod"], 0),
         "pct": round(100 * contagem.get(etapa["cod"], 0) / total) if total else 0}
        for etapa in CICLO
    ]
    # A casa pela OCUPAÇÃO, do mais urgente para o resto — a faixa que fica ao lado
    # da legenda de limpeza. Só os estados que existem hoje entram.
    ocupacao = [
        {"cod": cod, "rotulo": OCUPACAO[cod][0], "ajuda": OCUPACAO[cod][1],
         "n": ocupacao_resumo[cod]}
        for cod in ("chega_hoje", "sai_hoje", "ocupado", "vago", "bloqueado")
        if ocupacao_resumo[cod]
    ]
    return {
        "dia": dia,
        "ciclo": ciclo,
        "contagem": contagem,
        "ocupacao": ocupacao,
        "portas": portas,
        "total": total,
        "prontos": prontos,
        "pct_prontos": round(100 * prontos / total) if total else 0,
        "falta_para_pronto": total - prontos,
        "hora_checkin": hora_checkin,
        # A ordem de atacar o dia, montada das mesmas linhas (zero consulta nova).
        "plano": plano,
        "chegadas": chegadas,
        "chegadas_atrasadas": len(chegadas_atrasadas),
        "carga": carga_das_camareiras(dia),
        "atencao": atencao,
        "sem_base": dados["sem_base"],
        "divergencias": len(divergentes),
    }


# ───────────── Conferência de ocupação e discrepância (skip × sleeper) ─────────────
#
# A governança é a única que entra em todos os quartos todo dia. Sem registrar o que
# viu, o PMS fica sozinho com a sua versão: hóspede que vai embora sem passar na
# recepção segue "hospedado" (diária correndo, conta aberta, quarto invendável) e
# hóspede que entrou sem o check-in lançado dorme de graça. É assim que pousada perde
# diária e descobre no fim do mês. O cruzamento é esta tela.


def ocupacao_pms(dia=None):
    """O que Reservas diz de cada quarto no dia, ou **None** quando o módulo não está
    ativo — aí não há base de comparação e a discrepância se explica em vez de
    quebrar (degradação graciosa)."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    if not modulo_ativo(Modulo.RESERVAS):
        return None
    from apps.reservas.services import ocupacao_por_uh

    return ocupacao_por_uh(dia or timezone.localdate())


def bloqueios_do_dia(dia=None) -> dict:
    """{uh_id: motivo} dos quartos que a Manutenção bloqueou no dia. Quarto em reparo
    tem técnico e material dentro: ver gente ali não é sleeper."""
    from apps.nucleo.models import modulo_ativo
    from apps.nucleo.modulos import Modulo

    if not modulo_ativo(Modulo.MANUTENCAO):
        return {}
    from apps.manutencao.services import bloqueios

    dia = dia or timezone.localdate()
    return {b["uh_id"]: b["motivo"] for b in bloqueios(dia, dia)}


def conferencias_do_dia(dia=None) -> dict:
    """{uh_id: última conferência daquele quarto no dia} — uma consulta. O histórico
    fica todo no banco; a tela mostra a ronda mais recente."""
    dia = dia or timezone.localdate()
    ultimas = {}
    for c in (
        ConferenciaOcupacao.objects.filter(dia=dia)
        .select_related("registrado_por")
        .order_by("registrado_em", "pk")      # crescente: a última sobrescreve
    ):
        ultimas[c.uh_id] = c
    return ultimas


def classificar(visto, pms, *, bloqueado=False, sem_base=False) -> str:
    """Veredito de uma conferência: o que foi visto × o que o PMS diz. Função pura
    (nenhuma consulta) — é ela que grava o retrato na ronda e a que a tela de hoje
    roda de novo ao vivo.

    `pms` = o dicionário do quarto em `reservas.ocupacao_por_uh` (None = o PMS
    considera o quarto vazio).
    """
    Div = ConferenciaOcupacao.Divergencia
    if sem_base:
        return Div.SEM_BASE
    if bloqueado:
        return Div.OK          # quarto fora da ronda: manutenção manda nele
    ocupado_visto = visto != ConferenciaOcupacao.Visto.VAGO
    if pms and pms["ocupado"]:
        if not ocupado_visto:
            # Saída que já era = recepção não lançou o check-out. Saída no futuro =
            # o hóspede sumiu com a conta aberta.
            return Div.SAIDA_NAO_LANCADA if pms["saida_ate"] else Div.SKIP
        if visto == ConferenciaOcupacao.Visto.SEM_BAGAGEM and not pms["saida_ate"]:
            # Cama usada e nenhuma mala no meio da estadia: pode já ter ido embora.
            return Div.SEM_BAGAGEM
        return Div.OK
    return Div.SLEEPER if ocupado_visto else Div.OK


# Rótulo curto (cabe na cápsula da linha), gravidade e o que fazer.
_DIVERGENCIAS = {
    ConferenciaOcupacao.Divergencia.SKIP: (
        "Saiu sem baixa", "alta",
        "Conferir na recepção: se foi embora, cobrar a conta e lançar a saída.",
    ),
    ConferenciaOcupacao.Divergencia.SAIDA_NAO_LANCADA: (
        "Saída não lançada", "media",
        "Fechar a conta e lançar o check-out — o quarto está invendável até isso.",
    ),
    ConferenciaOcupacao.Divergencia.SLEEPER: (
        "Hóspede não lançado", "alta",
        "Descobrir quem está no quarto: check-in não lançado ou estadia esticada.",
    ),
    ConferenciaOcupacao.Divergencia.SEM_BAGAGEM: (
        "Sem bagagem", "baixa",
        "Quarto em uso e sem mala no meio da estadia — confirmar se o hóspede ficou.",
    ),
    # Frase curta de propósito: esta linha se repete uma vez por quarto sem ronda, e
    # o porquê já está no alto da tela.
    "nao_conferido": ("Não conferido", "baixa", "Passar no quarto e registrar."),
}
_ROTULO_DIVERGENCIA = {cod: rotulo for cod, (rotulo, _, _) in _DIVERGENCIAS.items()}


def explicar_divergencia(cod) -> tuple:
    """(rótulo curto, gravidade, o que fazer) de uma divergência — o texto que a tela
    e o aviso da ronda mostram. Código que não é divergência devolve vazio."""
    return _DIVERGENCIAS.get(cod, ("", "", ""))


def registrar_conferencia(uh, visto, usuario=None, dia=None, observacao=""):
    """Grava o que a camareira viu no quarto. Linha nova a cada toque (histórico), com
    o retrato do PMS e o veredito do momento. A trilha de auditoria vem dos signals
    do núcleo — quem registrou e quando também ficam no próprio registro."""
    if visto not in ConferenciaOcupacao.Visto.values:
        raise ValidationError("Situação de ocupação inválida.")
    dia = dia or timezone.localdate()
    pms = ocupacao_pms(dia)
    info = (pms or {}).get(uh.pk)
    from apps.nucleo.models import UH

    bloqueado = uh.status == UH.Status.BLOQUEADA or uh.pk in bloqueios_do_dia(dia)
    return ConferenciaOcupacao.objects.create(
        uh=uh, dia=dia, visto=visto,
        pms_ocupado=None if pms is None else bool(info and info["ocupado"]),
        reserva_id=(info or {}).get("reserva_id"),
        divergencia=classificar(visto, info, bloqueado=bloqueado, sem_base=pms is None),
        observacao=(observacao or "")[:200],
        registrado_por=usuario,
    )


def _acao_da_divergencia(cod, uh, pms, conferencia):
    """Uma linha do relatório de discrepância: o que o PMS diz, o que foi visto, a
    gravidade e para onde ir resolver."""
    from django.urls import reverse

    rotulo, gravidade, o_que_fazer = _DIVERGENCIAS[cod]
    hospede = pms["hospede"] if pms else ""
    if pms and pms["ocupado"]:
        pms_diz = f"Ocupado — {hospede} (saída {pms['checkout']:%d/%m})"
    elif pms and pms["chegada"]:
        pms_diz = f"Livre — chegada hoje de {hospede}"
    else:
        pms_diz = "Livre"
    if cod == "nao_conferido":
        visto = "—"
        url = reverse("governanca:quartos")       # a ação é fazer a ronda (na lista)
    else:
        visto = conferencia.get_visto_display()
        url = (reverse("reservas:detalhe", args=[pms["reserva_id"]]) if pms
               # Sleeper não tem reserva para abrir: o caminho é o mapa de quartos.
               else reverse("reservas:mapa_quartos"))
    return {
        "uh": uh, "tipo": cod, "rotulo": rotulo, "gravidade": gravidade,
        "o_que_fazer": o_que_fazer, "pms_diz": pms_diz, "visto": visto,
        "conferencia": conferencia, "pms": pms, "url": url,
    }


def discrepancias(dia=None) -> dict:
    """Relatório de discrepância da governança: onde a ronda e o PMS não batem.

    Confronto AO VIVO (não o veredito gravado na ronda): o que a recepção já
    resolveu sai da lista. `sem_base` = Reservas inativo, nada a comparar.
    """
    dados = _estado_dos_quartos(dia)
    gravidade_ordem = {"alta": 0, "media": 1, "baixa": 2}
    linhas, resumo = [], {cod: 0 for cod in _DIVERGENCIAS}
    conferidos = ok = 0
    for ln in dados["linhas"]:
        if ln["divergente"]:
            resumo[ln["divergencia"]] += 1
            linhas.append(_acao_da_divergencia(
                ln["divergencia"], ln["uh"], ln["pms"], ln["conferencia"]))
        elif ln["conferencia"]:
            ok += 1
        elif not ln["bloqueado"] and not dados["sem_base"]:
            resumo["nao_conferido"] += 1
            linhas.append(_acao_da_divergencia(
                "nao_conferido", ln["uh"], ln["pms"], None))
        if ln["conferencia"]:
            conferidos += 1
    linhas.sort(key=lambda a: (gravidade_ordem.get(a["gravidade"], 9), a["uh"].numero))
    return {
        "dia": dados["dia"], "sem_base": dados["sem_base"], "linhas": linhas,
        "resumo": resumo, "conferidos": conferidos, "conferem": ok,
        "quartos": len(dados["linhas"]),
        "divergencias": sum(resumo[c] for c in ConferenciaOcupacao.DIVERGENTES),
    }


def pendencias_auditoria():
    """Divergências da ronda de HOJE para a varredura da Auditoria (read-only).

    Sem Reservas ativo não há base de comparação — nada a apontar. "Não conferido"
    entra em UMA linha agregada e só pelos quartos que o PMS diz ocupados: antes da
    ronda nenhum quarto foi conferido, e 24 linhas todas as manhãs viram ruído.
    """
    d = discrepancias()
    if d["sem_base"]:
        return []
    achados = [
        {
            "area": "Governança", "tipo": a["tipo"], "gravidade": a["gravidade"],
            "descricao": (f"{a['uh'].numero} — {a['rotulo'].lower()}: PMS diz "
                          f"\"{a['pms_diz']}\" e a ronda viu \"{a['visto']}\". "
                          f"{a['o_que_fazer']}"),
            "url": a["url"],
        }
        for a in d["linhas"] if a["tipo"] != "nao_conferido"
    ]
    ocupados_sem_ronda = [a for a in d["linhas"]
                          if a["tipo"] == "nao_conferido" and a["pms"]
                          and a["pms"]["ocupado"]]
    if ocupados_sem_ronda:
        from django.urls import reverse

        quartos = ", ".join(a["uh"].numero for a in ocupados_sem_ronda)
        achados.append({
            "area": "Governança", "tipo": "ronda_incompleta", "gravidade": "baixa",
            "descricao": f"{len(ocupados_sem_ronda)} quarto(s) ocupado(s) sem "
                         f"conferência de ocupação hoje: {quartos}.",
            "url": reverse("governanca:discrepancias"),
        })
    return achados


# ───────────────────────────── Relatórios da Governança ─────────────────────────────
#
# Dados crus (números, não texto formatado) — quem monta a tabela e escreve "R$" é o
# módulo Relatórios, como faz com os outros setores.


def _nome(usuario) -> str:
    if not usuario:
        return "— sem camareira —"
    return usuario.get_full_name() or usuario.username


def relatorio_faxinas(inicio, fim) -> dict:
    """Faxinas CONCLUÍDAS no período, por camareira e por tipo, com o tempo médio
    entre iniciar e concluir. Tarefa sem `iniciada_em` (concluída direto, sem passar
    por "em limpeza") entra na contagem e fica fora da média — a média é de quem
    cronometrou, não uma estimativa."""
    from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F

    qs = TarefaGovernanca.objects.filter(
        status=TarefaGovernanca.Status.CONCLUIDA,
        concluida_em__date__range=(inicio, fim),
    )
    tipos = list(TarefaGovernanca.Tipo.choices)
    por_camareira = {}
    for linha in (qs.values("camareira", "tipo")
                  .annotate(n=Count("pk")).order_by()):
        reg = por_camareira.setdefault(
            linha["camareira"], {"n": 0, "tipos": dict.fromkeys(dict(tipos), 0)})
        reg["n"] += linha["n"]
        reg["tipos"][linha["tipo"]] = linha["n"]

    duracao = ExpressionWrapper(F("concluida_em") - F("iniciada_em"),
                                output_field=DurationField())
    cronometradas = qs.filter(iniciada_em__isnull=False)
    for linha in (cronometradas.values("camareira")
                  .annotate(media=Avg(duracao)).order_by()):
        reg = por_camareira.get(linha["camareira"])
        if reg is not None:
            reg["minutos"] = round(linha["media"].total_seconds() / 60)

    media_geral = cronometradas.aggregate(m=Avg(duracao))["m"]
    usuarios = {u.pk: u for u in _usuarios_das_tarefas(por_camareira)}
    linhas = [
        {"camareira": _nome(usuarios.get(pk)), "n": reg["n"],
         "tipos": reg["tipos"], "minutos": reg.get("minutos")}
        for pk, reg in por_camareira.items()
    ]
    linhas.sort(key=lambda ln: (-ln["n"], ln["camareira"]))
    return {
        "tipos": tipos, "linhas": linhas,
        "total": sum(ln["n"] for ln in linhas),
        "minutos_medios": (round(media_geral.total_seconds() / 60)
                           if media_geral else None),
        "cronometradas": cronometradas.count(),
    }


def _usuarios_das_tarefas(por_camareira):
    """Os usuários citados nas agregações, numa consulta (as `values()` só trazem o id)."""
    from django.contrib.auth import get_user_model

    ids = [pk for pk in por_camareira if pk]
    return get_user_model().objects.filter(pk__in=ids) if ids else []


def relatorio_inspecoes(inicio, fim) -> dict:
    """Faxinas inspecionadas × reprovadas no período, por camareira — qualidade da
    entrega. A reprovação é a supervisora devolvendo o quarto para a fila."""
    from django.db.models import Count

    inspecionadas = TarefaGovernanca.objects.filter(
        inspecionada_em__date__range=(inicio, fim))
    reprovadas = TarefaGovernanca.objects.filter(
        reprovada_em__date__range=(inicio, fim))
    por = {}
    for qs, chave in ((inspecionadas, "inspecionadas"), (reprovadas, "reprovadas")):
        for linha in qs.values("camareira").annotate(n=Count("pk")).order_by():
            reg = por.setdefault(linha["camareira"],
                                 {"inspecionadas": 0, "reprovadas": 0})
            reg[chave] = linha["n"]
    usuarios = {u.pk: u for u in _usuarios_das_tarefas(por)}
    linhas = []
    for pk, reg in por.items():
        total = reg["inspecionadas"] + reg["reprovadas"]
        linhas.append({
            "camareira": _nome(usuarios.get(pk)),
            "inspecionadas": reg["inspecionadas"], "reprovadas": reg["reprovadas"],
            # % de retrabalho sobre o que foi julgado (aprovado + reprovado).
            "retrabalho": round(100 * reg["reprovadas"] / total, 1) if total else 0,
        })
    linhas.sort(key=lambda ln: (-ln["reprovadas"], -ln["inspecionadas"], ln["camareira"]))
    motivos = list(
        reprovadas.exclude(motivo_reprovacao="")
        .values("motivo_reprovacao").annotate(n=Count("pk")).order_by("-n")[:10]
    )
    total_i = inspecionadas.count()
    total_r = reprovadas.count()
    julgadas = total_i + total_r
    return {
        "linhas": linhas, "inspecionadas": total_i, "reprovadas": total_r,
        "retrabalho": round(100 * total_r / julgadas, 1) if julgadas else 0,
        "motivos": [(m["motivo_reprovacao"], m["n"]) for m in motivos],
        # Faxinas entregues e ainda sem veredito da supervisora, no período.
        "sem_inspecao": TarefaGovernanca.objects.filter(
            status=TarefaGovernanca.Status.CONCLUIDA,
            concluida_em__date__range=(inicio, fim),
            inspecionada_em__isnull=True, reprovada_em__isnull=True,
        ).count(),
    }


def relatorio_discrepancias(inicio, fim) -> dict:
    """Discrepâncias por dia no período — o veredito GRAVADO em cada ronda (retrato do
    momento), não um recálculo: a reserva de ontem não está mais hospedada hoje, e o
    histórico tem de continuar contando o que de fato foi encontrado."""
    from django.db.models import Count

    por_dia = {}
    for linha in (
        ConferenciaOcupacao.objects.filter(dia__range=(inicio, fim))
        .values("dia", "divergencia").annotate(n=Count("pk")).order_by("dia")
    ):
        reg = por_dia.setdefault(
            linha["dia"],
            {"dia": linha["dia"], "conferencias": 0,
             **{cod: 0 for cod in ConferenciaOcupacao.DIVERGENTES}},
        )
        reg["conferencias"] += linha["n"]
        if linha["divergencia"] in ConferenciaOcupacao.DIVERGENTES:
            reg[linha["divergencia"]] = linha["n"]
    linhas = sorted(por_dia.values(), key=lambda r: r["dia"])
    for reg in linhas:
        reg["divergencias"] = sum(reg[c] for c in ConferenciaOcupacao.DIVERGENTES)
    return {
        "linhas": linhas,
        "conferencias": sum(r["conferencias"] for r in linhas),
        "divergencias": sum(r["divergencias"] for r in linhas),
        "dias_com_divergencia": sum(1 for r in linhas if r["divergencias"]),
        "por_tipo": {
            cod: sum(r[cod] for r in linhas) for cod in ConferenciaOcupacao.DIVERGENTES
        },
    }
