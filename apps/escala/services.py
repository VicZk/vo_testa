"""
Regras da Escala. Interface pública para as views (e futura integração:
Governança/Manutenção poderão atribuir tarefas a quem está de turno).
"""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Atribuicao, Ausencia, TrocaTurno


def inicio_da_semana(data=None):
    data = data or timezone.localdate()
    return data - timedelta(days=data.weekday())  # segunda-feira


def ausencia_no_dia(funcionario, data):
    return funcionario.ausencias.filter(inicio__lte=data, fim__gte=data).first()


def resumo_funcionario(funcionario, inicio, fim):
    """Dias/horas trabalhados, ausências e trocas do funcionário no período.
    Interface pública — o Histórico do funcionário (núcleo) consome daqui."""
    from datetime import datetime

    from django.db.models import Q

    atribs = (
        Atribuicao.objects
        .filter(funcionario=funcionario, data__range=(inicio, fim))
        .select_related("turno")
    )
    horas = 0.0
    for a in atribs:
        seg = (
            datetime.combine(inicio, a.turno.fim)
            - datetime.combine(inicio, a.turno.inicio)
        ).total_seconds()
        if seg <= 0:  # turno que vira a meia-noite
            seg += 86400
        horas += seg / 3600

    ausencias = []
    for au in Ausencia.objects.filter(
        funcionario=funcionario, inicio__lte=fim, fim__gte=inicio
    ).order_by("inicio"):
        di, df = max(au.inicio, inicio), min(au.fim, fim)
        ausencias.append({
            "tipo": au.get_tipo_display(), "dias": (df - di).days + 1,
            "inicio": au.inicio, "fim": au.fim,
        })

    trocas = TrocaTurno.objects.filter(
        Q(solicitante=funcionario) | Q(substituto=funcionario),
        criado_em__date__range=(inicio, fim),
    ).count()

    return {
        "dias_trabalhados": atribs.count(),
        "horas_trabalhadas": round(horas, 1),
        "ausencias": ausencias,
        "dias_ausente": sum(a["dias"] for a in ausencias),
        "trocas": trocas,
    }


@transaction.atomic
def atribuir(turno, funcionario, data, operador):
    from apps.nucleo.sistema import travar
    travar(funcionario)
    if not turno.ativo or not funcionario.pessoa.ativo:
        raise ValidationError("Escolha um turno e um funcionário ativos.")
    if data is None:
        raise ValidationError("Informe uma data válida para a escala.")
    if ausencia_no_dia(funcionario, data):
        raise ValidationError(
            f"{funcionario.pessoa.nome} está ausente em {data:%d/%m}. Remova a ausência antes de escalar."
        )
    try:
        return Atribuicao.objects.create(
            turno=turno, funcionario=funcionario, data=data, criado_por=operador
        )
    except IntegrityError:
        raise ValidationError("Esse funcionário já está nesse turno neste dia.")


def desatribuir(atribuicao):
    atribuicao.delete()


@transaction.atomic
def mover(atribuicao, novo_turno, nova_data, operador=None):
    """Move uma atribuição para outro turno/dia (arrasto na grade). Bloqueia
    ausência e duplicata (o mesmo funcionário no mesmo turno×dia)."""
    from apps.nucleo.sistema import travar
    travar(atribuicao.funcionario)
    travar(atribuicao)
    if not novo_turno.ativo or not atribuicao.funcionario.pessoa.ativo:
        raise ValidationError("Escolha um turno e um funcionário ativos.")
    if nova_data is None:
        raise ValidationError("Informe uma data válida para a escala.")
    if ausencia_no_dia(atribuicao.funcionario, nova_data):
        raise ValidationError(
            f"{atribuicao.funcionario.pessoa.nome} está ausente em {nova_data:%d/%m}."
        )
    duplicata = (
        Atribuicao.objects
        .filter(turno=novo_turno, funcionario=atribuicao.funcionario, data=nova_data)
        .exclude(pk=atribuicao.pk).exists()
    )
    if duplicata:
        raise ValidationError("Esse funcionário já está nesse turno neste dia.")
    atribuicao.turno = novo_turno
    atribuicao.data = nova_data
    atribuicao.save(update_fields=["turno", "data"])
    return atribuicao


@transaction.atomic
def adicionar_hora_extra(funcionario, data, inicio, fim, tipo, operador=None):
    """Lança uma hora extra planejada (banco/extra) num dia do colaborador."""
    from apps.nucleo.sistema import travar

    from .models import HoraExtra
    travar(funcionario)
    he = HoraExtra(funcionario=funcionario, data=data, inicio=inicio, fim=fim,
                   tipo=tipo or HoraExtra.Tipo.BANCO, criado_por=operador)
    he.full_clean()
    if he.total_minutos <= 0:
        raise ValidationError("Fim deve ser depois do início.")
    he.save()
    return he


def remover_hora_extra(hora_extra):
    hora_extra.delete()


def definir_compensacao_feriado(atribuicao, valor):
    """Marca, no dia de feriado trabalhado, se compensa com folga ou dobro."""
    from .models import Atribuicao
    if valor not in dict(Atribuicao.Compensacao.choices):
        raise ValidationError("Compensação inválida.")
    atribuicao.compensacao_feriado = valor
    atribuicao.save(update_fields=["compensacao_feriado"])
    return atribuicao


def feriados_no_periodo(inicio, fim):
    """Set de datas que são feriado no período (para marcar na grade/relatório)."""
    from .models import Feriado
    return set(Feriado.objects.filter(data__range=(inicio, fim)).values_list("data", flat=True))


def _fmt_min(m):
    return f"{m // 60}h{m % 60:02d}"


def _min_turno(turno):
    from datetime import date, datetime
    d = datetime.combine(date.today(), turno.fim) - datetime.combine(date.today(), turno.inicio)
    m = int(d.total_seconds() // 60)
    return m + 1440 if m < 0 else m


def relatorio_colaborador(funcionario, inicio, fim):
    """Relatório mensal do colaborador: horas normais, extras (banco/extra),
    feriados trabalhados e ausências no período. Base = escala planejada
    (quando houver ponto, passa a usar o realizado)."""
    from .models import Atribuicao, Ausencia, HoraExtra

    atribs = list(
        Atribuicao.objects.filter(funcionario=funcionario, data__range=(inicio, fim))
        .select_related("turno")
    )
    feriados = feriados_no_periodo(inicio, fim)
    horas_normais = sum(_min_turno(a.turno) for a in atribs)

    fer_trab = []
    for a in atribs:
        if a.data in feriados:
            comp = a.compensacao_feriado or funcionario.compensacao_feriado or "folga"
            fer_trab.append({"data": a.data, "turno": a.turno.nome,
                             "compensacao": "Folga compensatória" if comp == "folga" else "Pagamento em dobro"})

    hx = list(HoraExtra.objects.filter(funcionario=funcionario, data__range=(inicio, fim)).order_by("data", "inicio"))
    banco = sum(h.total_minutos for h in hx if h.tipo == "banco")
    extra = sum(h.total_minutos for h in hx if h.tipo == "extra")

    ausencias = []
    aus_por_dia = {}
    for au in Ausencia.objects.filter(funcionario=funcionario, inicio__lte=fim, fim__gte=inicio).order_by("inicio"):
        di, df = max(au.inicio, inicio), min(au.fim, fim)
        ausencias.append({"tipo": au.get_tipo_display(), "dias": (df - di).days + 1,
                          "inicio": au.inicio, "fim": au.fim})
        d = di
        while d <= df:
            aus_por_dia[d] = au.get_tipo_display()
            d += timedelta(days=1)

    # Calendário: status por dia do período (herói do relatório).
    dias_atrib = {a.data for a in atribs}
    he_min_dia = {}
    for h in hx:
        he_min_dia[h.data] = he_min_dia.get(h.data, 0) + h.total_minutos
    dias = []
    d = inicio
    while d <= fim:
        aus = aus_por_dia.get(d, "")
        trabalhou = d in dias_atrib
        dias.append({
            "dia": d.day, "data": d, "domingo": d.weekday() == 6,
            "trabalhou": trabalhou and not aus,
            "feriado": trabalhou and d in feriados,
            "extra_txt": ("+" + _fmt_min(he_min_dia[d])) if d in he_min_dia else "",
            "ausencia": "" if trabalhou else aus,   # ausência só marca dia sem turno
        })
        d += timedelta(days=1)
    # semanas para a grade do calendário (blanks à frente + fecha em múltiplos de 7)
    celulas = [None] * inicio.weekday() + dias
    while len(celulas) % 7:
        celulas.append(None)
    semanas = [celulas[i:i + 7] for i in range(0, len(celulas), 7)]

    return {
        "dias_trabalhados": len(dias_atrib),
        "horas_normais_txt": _fmt_min(horas_normais),
        "banco_txt": _fmt_min(banco),
        "extra_txt": _fmt_min(extra),
        "hx_total_txt": _fmt_min(banco + extra),
        "horas_extras": hx,
        "feriados_trabalhados": fer_trab,
        "feriados_count": len(fer_trab),
        "ausencias": ausencias,
        "dias_ausente": sum(a["dias"] for a in ausencias),
        "dias": dias,
        "semanas": semanas,
        "primeiro_dow": inicio.weekday(),
    }


# ───────── Quem está trabalhando hoje — interface pública dos outros módulos ─────────
#
# A Governança escala a camareira do quarto; a Manutenção, o técnico da OS. Nenhum
# dos dois importa models daqui: perguntam quem está de turno e recebem gente.


def de_turno(dia=None, setor=None) -> list:
    """Os funcionários escalados para `dia` (só `setor`, se informado), sem quem
    está de folga/férias/atestado. Duas consultas, qualquer que seja a equipe."""
    dia = dia or timezone.localdate()
    ausentes = set(
        Ausencia.objects.filter(inicio__lte=dia, fim__gte=dia)
        .values_list("funcionario_id", flat=True)
    )
    qs = (Atribuicao.objects.filter(data=dia)
          .select_related("funcionario__pessoa", "funcionario__usuario", "turno")
          .order_by("turno__inicio", "funcionario__pessoa__nome"))
    if setor:
        qs = qs.filter(turno__setor=setor)
    vistos, equipe = set(), []
    for atrib in qs:
        func = atrib.funcionario
        if func.pk in vistos or func.pk in ausentes:
            continue
        vistos.add(func.pk)
        equipe.append(func)
    return equipe


def usuarios_de_turno(dia=None, setor=None) -> list:
    """Os LOGINS de quem está de turno — para o módulo que atribui trabalho a um
    usuário do sistema (a tarefa da Governança é de uma camareira com login).
    Funcionário sem login no CRM não entra: não haveria a quem atribuir."""
    return [f.usuario for f in de_turno(dia, setor)
            if f.usuario_id and f.usuario.is_active]


def ausencias_da_semana(inicio):
    """[(funcionario_id, 'YYYY-MM-DD')] das ausências que tocam a semana — o
    editor usa para acender de vermelho a célula inválida ao arrastar."""
    fim = inicio + timedelta(days=6)
    bloqueios = []
    for au in Ausencia.objects.filter(inicio__lte=fim, fim__gte=inicio):
        d = max(au.inicio, inicio)
        ate = min(au.fim, fim)
        while d <= ate:
            bloqueios.append({"func": au.funcionario_id, "data": d.strftime("%Y-%m-%d")})
            d += timedelta(days=1)
    return bloqueios


def grade_semana(inicio, setor=None):
    """Estrutura para a grade: por turno (linha) × 7 dias, com os funcionários."""
    from .models import Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)

    atribs = (
        Atribuicao.objects.filter(data__range=(dias[0], dias[-1]))
        .select_related("funcionario__pessoa", "turno")
    )
    mapa = {}
    for a in atribs:
        mapa.setdefault((a.turno_id, a.data), []).append(a)

    linhas = []
    for t in turnos:
        celulas = [{"data": d, "atribs": mapa.get((t.pk, d), [])} for d in dias]
        linhas.append({"turno": t, "celulas": celulas})
    return {"dias": dias, "linhas": linhas}


# ---------- Gerador automático de escala (regras encodadas) ----------

# Turno.setor é código; Funcionario.setor é texto livre — casamos por palavra-chave.
SETOR_KEYWORDS = {
    "recepcao": ["recep"],
    "governanca": ["govern", "camar", "limpeza", "arruma", "rouparia"],
    "cozinha": ["cozinh", "restaur", "garcom", "garçom", "bar"],
    "manutencao": ["manuten", "zelador"],
    "geral": [],
}

INTERJORNADA_MIN_H = 11   # CLT: 11h entre o fim de um turno e o início do próximo
MAX_DIAS_SEMANA = 6       # DSR: ao menos 1 folga a cada 6 dias


def descanso_minimo():
    from .models import ConfiguracaoEscala
    return ConfiguracaoEscala.atual().descanso_horas


def intervalo(data, inicio, fim):
    """Representa a saída noturna na data em que ela realmente acontece."""
    entrada = datetime.combine(data, inicio)
    saida = datetime.combine(data, fim)
    if saida <= entrada:
        saida += timedelta(days=1)
    return entrada, saida


def funcionarios_do_setor(setor_code):
    from django.db.models import Q

    from apps.nucleo.models import Funcionario

    kws = SETOR_KEYWORDS.get(setor_code, [])
    qs = Funcionario.objects.select_related("pessoa").order_by("pk")
    if not kws:
        return list(qs)
    q = Q()
    for kw in kws:
        q |= Q(setor__icontains=kw)
    return list(qs.filter(q))


def semana_idx(inicio):
    """Índice 0..3 no ciclo de 4 semanas (gira quem folga no domingo)."""
    return inicio.isocalendar().week % 4


def folga_domingo(funcionario, idx):
    """Regra de domingo por sexo, escalonada por funcionário (para não folgarem
    todos no mesmo domingo): ♀ folga 2 de 4, ♂ folga 1 de 4."""
    off = funcionario.pk or 0
    if funcionario.sexo == "M":
        return (idx + off) % 4 == 0            # 1 de 4 domingos de folga
    if funcionario.sexo == "F":
        return (idx + off) % 2 == 0            # 2 de 4 domingos de folga
    return False                               # sem sexo: sem regra especial


def _viola_interjornada(ultimo, dia, turno):
    """ultimo = (data, fim) do último turno alocado; bloqueia gap < 11h (ex.:
    tarde termina 22h e manhã começa 7h no dia seguinte = 9h)."""
    if not ultimo:
        return False
    gap = datetime.combine(dia, turno.inicio) - ultimo
    return gap.total_seconds() / 3600 < descanso_minimo()


@transaction.atomic
def gerar_semana(inicio, operador, setor=None, limpar=True):
    """Monta a semana automaticamente respeitando: cobertura mínima por turno,
    domingo por sexo, interjornada 11h, DSR (máx 6 dias) e ausências/férias.
    Devolve nº de atribuições criadas. O gestor ajusta depois; validar_semana
    aponta o que ficou descoberto."""
    from .models import Turno

    dias = [inicio + timedelta(days=n) for n in range(7)]
    idx = semana_idx(inicio)
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)
    turnos = list(turnos.order_by("inicio"))
    setores = sorted({t.setor for t in turnos})

    from apps.nucleo.models import Funcionario
    list(Funcionario.objects.select_for_update().order_by("pk"))
    if limpar:
        Atribuicao.objects.filter(
            data__range=(dias[0], dias[-1]), turno__setor__in=setores
        ).delete()

    criadas = 0
    for st in setores:
        funcs = funcionarios_do_setor(st)
        turnos_setor = [t for t in turnos if t.setor == st]
        dias_trab = {f.pk: 0 for f in funcs}
        ultimo = {f.pk: None for f in funcs}     # (data, fim) do último turno
        ocupado_no_dia = set()                   # (func_pk, data) — 1 turno/dia
        for dia in dias:
            eh_domingo = dia.weekday() == 6
            for t in turnos_setor:
                cands = [
                    f for f in funcs
                    if (f.pk, dia) not in ocupado_no_dia
                    and dias_trab[f.pk] < MAX_DIAS_SEMANA
                    and not ausencia_no_dia(f, dia)
                    and not _viola_interjornada(ultimo[f.pk], dia, t)
                    and not conflito_interjornada(f, t, dia)
                ]
                # Cobertura vem primeiro: quem "deveria folgar" no domingo (regra
                # por sexo) vai para o fim da fila e só entra se faltar gente.
                cands.sort(key=lambda f: (
                    1 if (eh_domingo and folga_domingo(f, idx)) else 0,
                    dias_trab[f.pk],
                ))
                for f in cands[: t.min_pessoas]:
                    Atribuicao.objects.create(
                        turno=t, funcionario=f, data=dia, criado_por=operador
                    )
                    dias_trab[f.pk] += 1
                    ultimo[f.pk] = intervalo(dia, t.inicio, t.fim)[1]
                    ocupado_no_dia.add((f.pk, dia))
                    criadas += 1
    return criadas


def conflito_interjornada(funcionario, turno, data, ignora_pk=None):
    """A escala de `funcionario` no `turno`/`data` deixa <11h de descanso em
    relação ao dia anterior ou seguinte? (usado no drop, para pedir confirmação)."""
    if data is None:
        raise ValidationError("Informe uma data válida para a escala.")
    entrada, saida = intervalo(data, turno.inicio, turno.fim)
    viz = Atribuicao.objects.filter(
        funcionario=funcionario, data__range=(data - timedelta(days=2), data + timedelta(days=2))
    ).select_related("turno")
    if ignora_pk:
        viz = viz.exclude(pk=ignora_pk)
    for a in viz:
        inicio_a, fim_a = intervalo(a.data, a.turno.inicio, a.turno.fim)
        if entrada < fim_a and inicio_a < saida:
            return True
        gap = entrada - fim_a if fim_a <= entrada else inicio_a - saida
        if a.data != data and gap.total_seconds() / 3600 < descanso_minimo():
            return True
    return False


def analisar_semana(inicio, setor=None):
    """Análise completa da semana. Devolve:
      alertas    — lista para o painel ({nivel, texto})
      violacoes  — {atribuicao_id: [{nivel, texto}]} para o selo em cada chip
      bloqueios  — violações de nível legal (barram a publicação)."""
    from .models import Feriado, Turno
    descanso = descanso_minimo()

    dias = [inicio + timedelta(days=n) for n in range(7)]
    domingo = dias[6]
    turnos = Turno.objects.filter(ativo=True)
    if setor:
        turnos = turnos.filter(setor=setor)
    turnos = list(turnos)
    setores = sorted({t.setor for t in turnos})

    # Descanso acompanha a pessoa, inclusive quando trabalha em outro setor.
    funcionarios_alvo = Atribuicao.objects.filter(
        turno__in=turnos, data__range=(dias[0], dias[-1])).values_list("funcionario_id", flat=True)
    # Dois dias de borda cobrem jornadas que terminam depois da meia-noite.
    borda = list(
        Atribuicao.objects.filter(
            data__range=(dias[0] - timedelta(days=2), dias[-1] + timedelta(days=2)),
            funcionario_id__in=funcionarios_alvo,
        ).select_related("funcionario__pessoa", "turno")
    )
    turnos_ids = {t.pk for t in turnos}
    atribs = [a for a in borda if dias[0] <= a.data <= dias[-1] and a.turno_id in turnos_ids]

    violacoes, alertas, bloqueios = {}, [], []

    def marca(pk, nivel, texto):
        violacoes.setdefault(pk, []).append({"nivel": nivel, "texto": texto})

    # 1) Cobertura mínima por turno × dia
    por_slot = {}
    for a in atribs:
        por_slot.setdefault((a.turno_id, a.data), []).append(a)
    faltas = []
    for t in turnos:
        for d in dias:
            tem = len(por_slot.get((t.pk, d), []))
            if tem < t.min_pessoas:
                faltas.append(f"{t.get_setor_display()} {t.nome} {d:%d/%m} ({tem}/{t.min_pessoas})")
    if faltas:
        alertas.append({
            "nivel": "perigo",
            "texto": "Cobertura abaixo do mínimo: " + "; ".join(faltas) + ".",
            "rotulo": "Cobertura abaixo do mínimo",
            "itens": faltas,
        })
        bloqueios.append("cobertura abaixo do mínimo")
    else:
        alertas.append({"nivel": "ok", "texto": "Cobertura completa nos 7 dias (mínimo por turno atendido)."})

    # 2) Interjornada 11h + 3) DSR — por funcionário, considerando turno E hora extra.
    from .models import HoraExtra
    he_borda = list(HoraExtra.objects.filter(
        data__range=(dias[0] - timedelta(days=1), dias[-1] + timedelta(days=1))
    ).select_related("funcionario__pessoa"))

    spans, atribs_por_dia, nomes_func = {}, {}, {}
    for a in borda:
        spans.setdefault((a.funcionario_id, a.data), []).append(intervalo(a.data, a.turno.inicio, a.turno.fim))
        atribs_por_dia.setdefault((a.funcionario_id, a.data), []).append(a)
        nomes_func[a.funcionario_id] = a.funcionario.pessoa.nome
    for he in he_borda:
        spans.setdefault((he.funcionario_id, he.data), []).append(intervalo(he.data, he.inicio, he.fim))
        nomes_func[he.funcionario_id] = he.funcionario.pessoa.nome

    inter_nomes, dsr_nomes, sobrepostos = [], [], []
    for fid in {f for (f, _d) in spans}:
        nome = nomes_func.get(fid, "")
        for d in dias:
            hoje = spans.get((fid, d), [])
            ontem = spans.get((fid, d - timedelta(days=1)), [])
            juntos = sorted(ontem + hoje)
            fim_anterior = None
            for entrada, saida in juntos:
                if fim_anterior and entrada < fim_anterior and (entrada.date() == d or saida.date() >= d):
                    if nome not in sobrepostos:
                        sobrepostos.append(nome)
                    for a in atribs_por_dia.get((fid, d), []):
                        marca(a.pk, "perigo", "Horários sobrepostos")
                fim_anterior = max(fim_anterior, saida) if fim_anterior else saida
            if hoje and ontem:
                gap = min(s[0] for s in hoje) - max(s[1] for s in ontem)
                if gap.total_seconds() / 3600 < descanso:
                    if nome not in inter_nomes:
                        inter_nomes.append(nome)
                    for a in atribs_por_dia.get((fid, d), []):
                        marca(a.pk, "perigo", f"Interjornada <{descanso}h")
        dias_trab = {d for d in dias if spans.get((fid, d))}
        if len(dias_trab) >= 7:
            dsr_nomes.append(nome)
            for d in dias:
                for a in atribs_por_dia.get((fid, d), []):
                    marca(a.pk, "perigo", "Sem folga na semana (DSR)")
    if inter_nomes:
        alertas.append({"nivel": "perigo", "texto": f"Interjornada <{descanso}h: " + ", ".join(inter_nomes) + "."})
        bloqueios.append(f"interjornada <{descanso}h")
    if sobrepostos:
        alertas.append({"nivel": "perigo", "texto": "Horários sobrepostos: " + ", ".join(sobrepostos) + "."})
        bloqueios.append("horários sobrepostos")
    if dsr_nomes:
        alertas.append({"nivel": "perigo", "texto": "Sem folga na semana (DSR): " + ", ".join(dsr_nomes) + "."})
        bloqueios.append("DSR (sem folga)")
    if not inter_nomes and not dsr_nomes and not sobrepostos:
        alertas.append({"nivel": "ok", "texto": f"Descanso de {descanso}h respeitado, sem sobreposição e todos com folga."})

    # Total de horas extras da semana (prévia do relatório mensal)
    he_sem = [he for he in he_borda if dias[0] <= he.data <= dias[-1]]
    if he_sem:
        def _fmt(m):
            return f"{m // 60}h{m % 60:02d}"
        tot = sum(he.total_minutos for he in he_sem)
        banco = sum(he.total_minutos for he in he_sem if he.tipo == "banco")
        extra = sum(he.total_minutos for he in he_sem if he.tipo == "extra")
        alertas.append({"nivel": "info", "codigo": "horas_extras",
                        "he": {"total": _fmt(tot), "banco": _fmt(banco), "extra": _fmt(extra)},
                        "texto": f"Horas extras planejadas na semana: {_fmt(tot)} "
                                 f"(banco {_fmt(banco)} · extra {_fmt(extra)})."})

    # 4) Domingo — folga real + memória dos últimos 4 domingos (rodízio)
    idx = semana_idx(inicio)
    domingos = [domingo - timedelta(days=7 * k) for k in range(4)]
    dom_hist = Atribuicao.objects.filter(data__in=domingos, turno__in=turnos)
    trab_por_dom = {}
    for a in dom_hist:
        trab_por_dom.setdefault(a.funcionario_id, set()).add(a.data)
    trab_este = {a.funcionario_id: a for a in atribs if a.data == domingo}
    folgam, forcados, rodizio = [], [], []
    for st in setores:
        for f in funcionarios_do_setor(st):
            if not f.sexo:
                continue
            deveria = folga_domingo(f, idx)
            if f.pk not in trab_este:
                folgam.append(f"{f.pessoa.nome} ({'♀ 2/4' if f.sexo == 'F' else '♂ 1/4'})")
            elif deveria:
                forcados.append(f.pessoa.nome)
            qtd = len(trab_por_dom.get(f.pk, set()))
            limite = 4 if f.sexo == "M" else 3      # ♂: nunca folgou no mês; ♀: só 1 folga em 4
            if qtd >= limite and f.pk in trab_este:
                rodizio.append(f.pessoa.nome)
                marca(trab_este[f.pk].pk, "aviso", f"{qtd}º domingo (rodízio)")
    if folgam:
        alertas.append({"nivel": "info", "texto": f"Domingo {domingo:%d/%m}. Folga pela regra: " + "; ".join(folgam) + "."})
    if forcados:
        alertas.append({"nivel": "aviso",
                        "texto": f"Domingo {domingo:%d/%m}. Não foi possível dar a folga de domingo por falta de equipe: "
                                 f"{', '.join(forcados)}. Considere um coringa."})
    if rodizio:
        alertas.append({"nivel": "aviso",
                        "texto": "Rodízio de domingo quebrado (poucas folgas no mês): "
                                 + ", ".join(sorted(set(rodizio))) + "."})

    # 5) Feriado na semana
    for fe in Feriado.objects.filter(data__range=(dias[0], dias[-1])):
        alertas.append({"nivel": "info",
                        "texto": f'Feriado {fe.data:%d/%m} ({fe.nome}). Tratar como domingo; compensação (folga/dobro) por funcionário.'})

    return {"alertas": alertas, "violacoes": violacoes, "bloqueios": bloqueios}


def validar_semana(inicio, setor=None):
    """Compat: só os alertas do painel (usa analisar_semana)."""
    return analisar_semana(inicio, setor)["alertas"]


@transaction.atomic
def publicar_semana(inicio, setor, operador, justificativa=""):
    """Publica a semana. Barra se houver violação legal em aberto, salvo se a
    gerência justificar (força). Registra na auditoria."""
    from apps.nucleo.models import Funcionario
    from apps.nucleo.models.financeiro import registrar_auditoria

    from .models import SemanaPublicada
    list(Funcionario.objects.select_for_update().order_by("pk"))
    bloqueios = analisar_semana(inicio, setor)["bloqueios"]
    if "horários sobrepostos" in bloqueios:
        raise ValidationError("Corrija os horários sobrepostos antes de publicar a escala.")
    if bloqueios and not (justificativa or "").strip():
        raise ValidationError(
            "Há violação legal em aberto (" + ", ".join(bloqueios) + "). "
            "Corrija ou justifique para publicar mesmo assim."
        )
    pub, _ = SemanaPublicada.objects.update_or_create(
        inicio=inicio, setor=setor or "",
        defaults={"publicado_por": operador, "forcado": bool(bloqueios),
                  "justificativa": justificativa.strip()[:240]},
    )
    registrar_auditoria(operador, "publicar_escala", pub,
                        {"forcado": bool(bloqueios), "bloqueios": bloqueios,
                         "justificativa": pub.justificativa})
    return pub


@transaction.atomic
def registrar_ausencia(funcionario, tipo, inicio, fim, operador, observacao=""):
    from apps.nucleo.sistema import travar
    travar(funcionario)
    ausencia = Ausencia(
        funcionario=funcionario, tipo=tipo, inicio=inicio, fim=fim,
        observacao=observacao, criado_por=operador,
    )
    ausencia.full_clean()
    if fim < inicio:
        raise ValidationError("A data final não pode ser antes da inicial.")
    ausencia.save()
    return ausencia


def minha_escala(usuario, inicio, fim):
    func = getattr(usuario, "funcionario", None)
    if not func:
        return []
    return (
        Atribuicao.objects.filter(funcionario=func, data__range=(inicio, fim))
        .select_related("turno").order_by("data", "turno__inicio")
    )


@transaction.atomic
def solicitar_troca(atribuicao, substituto, motivo=""):
    from apps.nucleo.models import Funcionario
    from apps.nucleo.sistema import travar

    solicitante_id = atribuicao.funcionario_id
    # A aprovação também começa pelos funcionários. A inserção da troca confere
    # essas FKs no commit; travar só a atribuição antes delas criava um deadlock.
    list(Funcionario.objects.select_for_update().filter(
        pk__in=[solicitante_id, substituto.pk]).order_by("pk"))
    travar(atribuicao)
    if atribuicao.funcionario_id != solicitante_id:
        raise ValidationError("Este turno já mudou de funcionário. Atualize a escala e solicite uma nova troca.")
    if substituto == atribuicao.funcionario:
        raise ValidationError("Escolha um substituto diferente.")
    if ausencia_no_dia(substituto, atribuicao.data):
        raise ValidationError("O substituto está ausente nesse dia.")
    if not substituto.pessoa.ativo:
        raise ValidationError("Escolha um substituto ativo.")
    existente = TrocaTurno.objects.filter(atribuicao=atribuicao,
        solicitante=atribuicao.funcionario, substituto=substituto, status=TrocaTurno.Status.PENDENTE).first()
    if existente:
        return existente
    troca = TrocaTurno(
        atribuicao=atribuicao, solicitante=atribuicao.funcionario,
        substituto=substituto, motivo=motivo,
    )
    troca.full_clean()
    troca.save()
    return troca


@transaction.atomic
def decidir_troca(troca, operador, aprovar):
    from apps.nucleo.models import Funcionario
    from apps.nucleo.sistema import travar

    # As mesmas âncoras de atribuir/mover/ausência, em ordem fixa, impedem duas
    # aprovações de aplicar decisões incompatíveis sobre a mesma atribuição.
    list(Funcionario.objects.select_for_update().filter(
        pk__in=[troca.solicitante_id, troca.substituto_id]).order_by("pk"))
    atrib = troca.atribuicao
    travar(atrib)
    travar(troca)
    if troca.status != TrocaTurno.Status.PENDENTE:
        raise ValidationError("Esta troca já foi decidida.")
    troca.decidido_por = operador
    troca.decidido_em = timezone.now()
    if aprovar:
        troca.status = TrocaTurno.Status.APROVADA
        if atrib.funcionario_id != troca.solicitante_id:
            raise ValidationError("Este turno já mudou de funcionário. Atualize a escala e solicite uma nova troca.")
        if not troca.substituto.pessoa.ativo:
            raise ValidationError("O substituto está inativo. Escolha outro funcionário.")
        # Revalida na aprovação: a solicitação pode ter envelhecido (o substituto ficou
        # ausente ou já foi escalado nesse turno/dia) — evita IntegrityError/estado ruim.
        if ausencia_no_dia(troca.substituto, atrib.data):
            raise ValidationError("O substituto está ausente nesse dia.")
        if (Atribuicao.objects
                .filter(turno=atrib.turno, data=atrib.data, funcionario=troca.substituto)
                .exclude(pk=atrib.pk).exists()):
            raise ValidationError("O substituto já está escalado nesse turno/dia.")
        atrib.funcionario = troca.substituto
        try:
            atrib.save(update_fields=["funcionario"])
        except IntegrityError:
            raise ValidationError("Conflito ao reatribuir o turno.")
    else:
        troca.status = TrocaTurno.Status.RECUSADA
    troca.save(update_fields=["status", "decidido_por", "decidido_em"])
    return troca
