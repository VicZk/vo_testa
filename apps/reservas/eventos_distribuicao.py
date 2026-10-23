"""Transforma alterações persistidas em eventos públicos de distribuição."""
from django.db.models.signals import post_delete, post_save

from apps.nucleo.models import (
    UH,
    ConfiguracaoReservas,
    ConfiguracaoUH,
    ModuloContratado,
    PosicaoCama,
    Temporada,
    TipoUH,
)

from .models import Reserva, RestricaoVenda, Tarifa, TarifaTemporada, TarifaUnidade
from .signals import distribuicao_alterada


def avisar(sender, instance, raw=False, **kwargs):
    if sender is ModuloContratado and instance.codigo not in ("reservas", "manutencao"):
        return
    if not raw:
        distribuicao_alterada.send(sender=sender, origem=sender._meta.label_lower)


def conectar():
    for modelo in (Reserva, RestricaoVenda, Tarifa, TarifaTemporada, TarifaUnidade,
                   UH, TipoUH, ConfiguracaoReservas, ConfiguracaoUH, PosicaoCama, Temporada, ModuloContratado):
        for sinal in (post_save, post_delete):
            sinal.connect(avisar, sender=modelo, weak=False,
                dispatch_uid=f"reservas.distribuicao.{modelo._meta.label_lower}.{id(sinal)}")
