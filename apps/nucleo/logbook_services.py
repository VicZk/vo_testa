"""Regras do Logbook (recados do turno).

Interface pública para as views: registrar ocorrência, responder no tópico
(move para "em andamento" quando alguém que não é o autor entra na conversa) e
resolver (fecha registrando quem/quando/por quê). Fechar é permitido a qualquer
operador com a área Logbook — decisão do produto (agilidade de turno).
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ComentarioLogbook, EntradaLogbook
from .models.financeiro import registrar_auditoria
from .sistema import travar


def registrar_ocorrencia(usuario, texto, importante=False):
    texto = (texto or "").strip()
    if not texto:
        raise ValidationError("Escreva a ocorrência.")
    entrada = EntradaLogbook.objects.create(
        autor=usuario, texto=texto, importante=bool(importante)
    )
    return entrada


@transaction.atomic
def comentar(usuario, entrada, texto):
    """Adiciona uma resposta ao tópico. Se a ocorrência está aberta e quem
    responde não é o autor, passa para 'em andamento' (alguém pegou)."""
    travar(entrada)
    texto = (texto or "").strip()
    if not texto:
        raise ValidationError("Escreva uma resposta.")
    if entrada.status == EntradaLogbook.RESOLVIDA:
        raise ValidationError("Esta ocorrência já foi resolvida.")
    comentario = ComentarioLogbook.objects.create(
        entrada=entrada, autor=usuario, texto=texto
    )
    if entrada.status == EntradaLogbook.ABERTA and usuario_id(entrada.autor) != usuario_id(usuario):
        entrada.status = EntradaLogbook.EM_ANDAMENTO
        entrada.save(update_fields=["status"])
    return comentario


@transaction.atomic
def resolver(usuario, entrada, nota=""):
    travar(entrada)
    if entrada.status == EntradaLogbook.RESOLVIDA:
        return entrada
    entrada.marcar_resolvida(usuario, nota)
    entrada.save(update_fields=["status", "resolvida_por", "resolvida_em", "resolucao_nota"])
    registrar_auditoria(
        usuario, "resolver_ocorrencia", entrada,
        {"nota": entrada.resolucao_nota, "importante": entrada.importante},
    )
    return entrada


@transaction.atomic
def reabrir(usuario, entrada):
    travar(entrada)
    if entrada.status != EntradaLogbook.RESOLVIDA:
        return entrada
    entrada.reabrir()
    entrada.save(update_fields=["status", "resolvida_por", "resolvida_em", "resolucao_nota"])
    registrar_auditoria(usuario, "reabrir_ocorrencia", entrada, {})
    return entrada


def usuario_id(u):
    return getattr(u, "pk", None)
