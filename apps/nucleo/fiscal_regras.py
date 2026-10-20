"""Regras fiscais que valem para todos os pontos de venda (Loja, Restaurante).

Venda de produto pede NFC-e, e a NFC-e depende da Inscrição Estadual. Enquanto a
pousada não tem IE (FISCAL_NFCE_HABILITADA=0), os PDVs mostram um aviso; com
FISCAL_BLOQUEAR_VENDA_SEM_NFCE=1 eles passam a recusar a venda.
"""
from django.conf import settings
from django.core.exceptions import ValidationError

AVISO_SEM_NFCE = (
    "Venda de produto sem NFC-e: a pousada ainda não tem Inscrição Estadual. Confirme "
    "com o contador como registrar estas vendas até a NFC-e ser liberada."
)


def nfce_disponivel() -> bool:
    return bool(getattr(settings, "FISCAL_NFCE_HABILITADA", False))


def conferir_venda_de_produto() -> None:
    """Levanta ValidationError se a venda de produto está bloqueada sem NFC-e."""
    if not nfce_disponivel() and getattr(settings, "FISCAL_BLOQUEAR_VENDA_SEM_NFCE", False):
        raise ValidationError(
            "Venda de produto bloqueada: a NFC-e ainda não está liberada (falta a "
            "Inscrição Estadual). Fale com a gerência.")
