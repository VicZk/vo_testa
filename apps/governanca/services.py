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
    """Marca o quarto como sujo e cria a tarefa de faxina (evita duplicar pendente)."""
    definir_status(uh, StatusLimpeza.Situacao.SUJA, usuario)
    tarefa = (
        TarefaGovernanca.objects.filter(
            uh=uh, tipo=tipo, status__in=["pendente", "em_andamento"]
        ).first()
    )
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
    if tarefa.status != TarefaGovernanca.Status.PENDENTE:
        return tarefa  # já iniciada/concluída — idempotente
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
        "resumo": "Conferido pela supervisora — pode receber hóspede.",
        "quem": "—",
        "ajuda": "Na hotelaria chama-se «inspecionado». É o único estado em que o "
                 "quarto está liberado para a recepção entregar a chave.",
    },
]
SITUACAO_SIMPLES = {e["cod"]: e["rotulo"] for e in CICLO}

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


def explicar_estado(situacao, tarefa, status) -> str:
    """Uma frase curta dizendo POR QUE o quarto está neste estado e o que falta.

    É o que ensina o fluxo a quem pega o sistema pela primeira vez: a tela não diz
    só «Limpo», diz «Limpo às 11:05 por Maria — falta a supervisora conferir».
    """
    quando = f" às {timezone.localtime(status.atualizado_em):%H:%M}" if status.atualizado_em else ""
    quem = _quem(getattr(status, "atualizado_por", None))
    if situacao == StatusLimpeza.Situacao.SUJA:
        motivo = _MOTIVO_DA_FAXINA.get(tarefa.origem if tarefa else "", "")
        if tarefa and tarefa.origem == "reprovada" and tarefa.observacoes:
            motivo = f"Devolvido para limpar: {tarefa.observacoes.rstrip('.')}."
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
    # (limpo) sem gravar nada: abrir a tela não escreve no banco.
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
        linhas.append({
            "uh": uh,
            "situacao": status.situacao,
            # Rótulo da TELA (plain) + a frase que explica por que o quarto está
            # assim e o que falta — é o que ensina o fluxo a quem está começando.
            "situacao_label": SITUACAO_SIMPLES.get(status.situacao,
                                                   status.get_situacao_display()),
            "explicacao": explicar_estado(status.situacao, tarefa, status),
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
    return {"dia": dia, "sem_base": pms is None, "linhas": linhas}


def painel_limpeza(dia=None):
    """Tela única de Governança: uma linha por quarto FÍSICO (day-use fora), com o
    status de limpeza + a tarefa ativa (se houver), ordenada por urgência. Substitui
    as duas tabelas (fila de faxina + situação dos quartos) por uma só."""
    dados = _estado_dos_quartos(dia)
    linhas = dados["linhas"]
    contagem = {c: 0 for c, _ in StatusLimpeza.Situacao.choices}
    for ln in linhas:
        contagem[ln["situacao"]] += 1
    linhas.sort(key=lambda ln: (_ORDEM_LIMPEZA.get(ln["situacao"], 9), ln["uh"].numero))
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
        url = reverse("governanca:painel")        # a ação é fazer a ronda
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
