"""Agenda de entregas e canais já utilizados no Marketing."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import JSONField, Q, TextField
from django.db.models.functions import Cast, Lower
from django.urls import reverse

from .models import Campanha, PecaCampanha


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
