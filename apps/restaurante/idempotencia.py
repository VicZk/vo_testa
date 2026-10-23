"""Identidade da intenção enviada, independente do preço e estoque atuais."""

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError

from apps.nucleo.validadores import decimal_valido, identificador_valido


def validar_chave_pedido(chave, *, obrigatoria=False):
    if chave in (None, ""):
        if obrigatoria:
            raise ValidationError("Abra o pedido novamente antes de enviar.")
        return None
    try:
        return chave if isinstance(chave, UUID) else UUID(str(chave))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("A identificação do pedido é inválida. Abra o pedido novamente.")


def identidade_item(produto_id, quantidade, observacoes="", opcoes=()):
    """Normaliza apenas a entrada: um retry não depende do catálogo ter mudado."""
    produto_id = identificador_valido(produto_id, nome="Produto")
    quantidade = decimal_valido(quantidade, nome="Quantidade", minimo=Decimal("0.001"),
                                maximo=Decimal("999999999.999"), casas=3)
    if not isinstance(observacoes, str) or len(observacoes.strip()) > 500:
        raise ValidationError("A observação deve ter no máximo 500 caracteres.")
    if not isinstance(opcoes, (list, tuple)) or len(opcoes) > 100:
        raise ValidationError("Confira as opções do pedido.")
    ids = [identificador_valido(pk, nome="Opção") for pk in opcoes]
    if len(set(ids)) != len(ids):
        raise ValidationError("A mesma opção não pode ser escolhida duas vezes.")
    return {"produto_id": produto_id, "quantidade": format(quantidade, ".3f"),
            "observacoes": observacoes.strip(), "opcoes": sorted(ids)}


def assinatura_pedido(origem, escopo_id, itens):
    # O carrinho é um conjunto de linhas; a ordem dos campos do POST não é intenção.
    linhas = sorted(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                    for item in itens)
    texto = json.dumps([1, origem, escopo_id, linhas], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
