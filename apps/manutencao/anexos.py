"""Anexos privados de manutenção; jamais enviados ao storage público de fotos."""
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.nucleo.documentos_privados import (
    LIMITE_BYTES as LIMITE_BYTES,
)
from apps.nucleo.documentos_privados import (
    TIPOS as TIPOS,
)
from apps.nucleo.documentos_privados import (
    preparar_documento as preparar_documento,
)
from apps.nucleo.models import registrar_auditoria

from .models import DocumentoOrdemServico, OrdemServico

LIMITE_DOCUMENTOS = 10


@transaction.atomic
def salvar_documento(ordem, usuario, documento):
    """Serializa o limite por OS; reenvios do mesmo arquivo são idempotentes."""
    if documento is None:
        return None
    OrdemServico.objects.select_for_update().only("pk").get(pk=ordem.pk)
    existente = ordem.documentos.filter(sha256=documento["sha256"]).defer("conteudo").first()
    if existente:
        return existente
    if ordem.documentos.count() >= LIMITE_DOCUMENTOS:
        raise ValidationError("Esta OS já tem 10 documentos anexados.")
    anexo = DocumentoOrdemServico.objects.create(ordem=ordem, enviado_por=usuario, **documento)
    registrar_auditoria(usuario, "documento_manutencao", ordem, {"documento_id": anexo.pk, "tamanho": anexo.tamanho})
    return anexo
