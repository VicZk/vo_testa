"""Agenda de entregas e canais já utilizados no Marketing."""
import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import JSONField, Q, TextField
from django.db.models.functions import Cast, Lower
from django.urls import reverse

from apps.nucleo.periodos import MESES_PT

from .models import AprovacaoLP, Campanha, EtapaCampanha, PecaCampanha


def canais_disponiveis():
    canais = set(PecaCampanha.objects.exclude(canal="").values_list("canal", flat=True))
    for lista in Campanha.objects.values_list("canais", flat=True):
        canais.update(canal for canal in lista if isinstance(canal, str) and canal.strip())
    unicos = {}
    for canal in sorted(canais):
        unicos.setdefault(canal.lower(), canal)
    return sorted(unicos.values(), key=str.lower)


def filtros_canais(request):
    selecionado = request.GET.get("canal", "").strip()
    canais = canais_disponiveis()
    selecionado = next((canal for canal in canais if canal.lower() == selecionado.lower()), selecionado)
    if selecionado and selecionado not in canais:
        canais.append(selecionado)
    return selecionado, [{"valor": canal, "nome": canal or "Todos os canais",
                          "ativo": canal == selecionado} for canal in ["", *canais]]


def campanhas_no_canal(consulta, canal):
    if not canal:
        return consulta
    # Inclui o canal da campanha e o das entregas; ambos são dados do usuário.
    return consulta.annotate(_canais_normalizados=Cast(Lower(Cast("canais", TextField())), JSONField())).filter(
        Q(_canais_normalizados__contains=[canal.lower()]) | Q(pecas__canal__iexact=canal)).distinct()


def agenda_periodo(inicio, fim, *, canal="", semana=False):
    consulta = PecaCampanha.objects.select_related("campanha").filter(data__range=(inicio, fim))
    if canal:
        consulta = consulta.filter(canal__iexact=canal)
    por_dia = defaultdict(list)
    for entrega in consulta.order_by("data", "nome", "pk"):
        por_dia[entrega.data].append(entrega)
    datas = ([inicio + timedelta(days=i) for i in range(7)] if semana else sorted(por_dia))
    campanhas = campanhas_no_canal(Campanha.objects.filter(
        inicio__lte=fim, fim__gte=inicio).select_related("responsavel"), canal).order_by("inicio", "pk")
    return {"dias": [{"data": dia, "entregas": por_dia[dia]} for dia in datas],
            "campanhas": campanhas,
            "sem_data_url": reverse("marketing:entregas")}


# ── Cronograma: a grade do mês com tudo o que tem data ─────────────────────────
# Nada é cadastrado duas vezes: a entrega e a tarefa da campanha aparecem pela própria
# data, e a campanha pelo início e pelo fim. A ordem do dia segue esta lista.
TIPOS_CRONOGRAMA = (
    ("campanha", "Campanha"),
    ("entrega", "Entrega"),
    ("tarefa", "Tarefa de campanha"),
    ("lp", "Aprovação de LP"),
)
DIAS_SEMANA = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


def cronograma_mes(ano, mes, *, canal="", hoje):
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    inicio = primeiro - timedelta(days=primeiro.weekday())
    fim = ultimo + timedelta(days=6 - ultimo.weekday())
    itens = defaultdict(list)

    def por(dia, tipo, nome, url, detalhe, *, ficha="", feito=False, marca=""):
        itens[dia].append({"tipo": tipo, "nome": nome, "url": url, "ficha": ficha,
                           "detalhe": detalhe, "feito": feito, "marca": marca})

    campanhas = campanhas_no_canal(Campanha.objects.filter(
        Q(inicio__range=(inicio, fim)) | Q(fim__range=(inicio, fim))), canal)
    for c in campanhas.order_by("inicio", "pk"):
        url, ficha = reverse("marketing:detalhe", args=[c.pk]), reverse("marketing:ficha", args=[c.pk])
        for dia, marca in ((c.inicio, "Início"), (c.fim, "Fim")):
            if dia and inicio <= dia <= fim and (marca == "Início" or c.fim != c.inicio):
                por(dia, "campanha", c.nome, url, f"{marca} da campanha · {c.get_fase_display()}",
                    ficha=ficha, marca=marca)

    entregas = PecaCampanha.objects.select_related("campanha").filter(data__range=(inicio, fim))
    if canal:
        entregas = entregas.filter(canal__iexact=canal)
    for e in entregas.order_by("data", "nome", "pk"):
        partes = [e.get_tipo_display(), e.canal, e.get_status_display(),
                  e.campanha.nome if e.campanha_id else "Sem campanha"]
        por(e.data, "entrega", e.nome, reverse("marketing:editar_entrega", args=[e.pk]),
            " · ".join(p for p in partes if p), feito=e.status == PecaCampanha.Status.PRONTA)

    etapas = EtapaCampanha.objects.select_related("campanha", "dono").filter(prazo__range=(inicio, fim))
    lps = AprovacaoLP.objects.filter(prazo__range=(inicio, fim)).exclude(
        situacao=AprovacaoLP.Situacao.PUBLICADA)
    if canal:
        no_canal = campanhas_no_canal(Campanha.objects.all(), canal).values("pk")
        etapas, lps = etapas.filter(campanha__in=no_canal), lps.filter(campanha__in=no_canal)
    for t in etapas.order_by("prazo", "pk"):
        partes = [t.campanha.nome, t.dono.get_full_name() or t.dono.username if t.dono_id else ""]
        por(t.prazo, "tarefa", t.texto, reverse("marketing:detalhe", args=[t.campanha_id]),
            "Tarefa · " + " · ".join(p for p in partes if p),
            ficha=reverse("marketing:ficha", args=[t.campanha_id]), feito=t.feito)
    for a in lps.order_by("prazo", "pk"):
        por(a.prazo, "lp", a.nome, reverse("marketing:lp_detalhe", args=[a.pk]),
            f"Aprovação de LP · {a.get_situacao_display()}",
            feito=a.situacao == AprovacaoLP.Situacao.APROVADA)

    contagem = defaultdict(int)
    for dia, lista in itens.items():
        if dia.month == mes:
            for item in lista:
                contagem[item["tipo"]] += 1
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    return {
        "titulo": f"{MESES_PT[mes]} de {ano}",
        "dias_semana": DIAS_SEMANA,
        "dias": [{"data": d, "no_mes": d.month == mes, "hoje": d == hoje,
                  "semana": DIAS_SEMANA[d.weekday()], "itens": itens.get(d, [])} for d in dias],
        "legenda": [{"tipo": tipo, "nome": nome, "n": contagem[tipo]}
                    for tipo, nome in TIPOS_CRONOGRAMA],
        "total": sum(contagem.values()),
    }
