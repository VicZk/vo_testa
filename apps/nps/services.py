from datetime import date, timedelta
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.nucleo.models import registrar_auditoria
from apps.nucleo.validadores import identificador_valido
from apps.portal.models import AcessoPortal
from apps.reservas.models import Reserva

from .models import RespostaNPS


def limite_resposta():
    return timezone.now() - timedelta(days=getattr(settings, "NPS_JANELA_DIAS", 90))


def elegivel(reserva):
    return (reserva.status == Reserva.Status.CHECKOUT and reserva.checkout_real is not None
            and limite_resposta() <= reserva.checkout_real <= timezone.now())


def reserva_por_token(token):
    try:
        token = UUID(str(token))
    except (ValueError, TypeError, AttributeError):
        return None
    acesso = AcessoPortal.objects.filter(token=token).first()
    if acesso is None:
        return None
    reserva = Reserva.objects.select_related("hospede").filter(pk=acesso.reserva_id).first()
    return reserva if reserva and elegivel(reserva) else None


@transaction.atomic
def responder(reserva_id, nota, comentario="", canal=RespostaNPS.Canal.PORTAL, usuario=None, consentimento=False):
    if consentimento is not True:
        raise ValidationError("É necessário autorizar o uso da avaliação antes do envio.")
    reserva_id = identificador_valido(reserva_id, nome="Reserva")
    if isinstance(nota, bool) or str(nota) not in {str(i) for i in range(11)}:
        raise ValidationError("Escolha uma nota inteira de 0 a 10.")
    if not isinstance(comentario, str) or len(comentario) > 2000:
        raise ValidationError("O comentário deve ter até 2.000 caracteres.")
    if canal not in RespostaNPS.Canal.values:
        raise ValidationError("Canal de resposta inválido.")
    reserva = Reserva.objects.select_for_update().filter(pk=reserva_id).first()
    if not reserva or not elegivel(reserva):
        raise ValidationError("A avaliação está disponível após o check-out, por 90 dias.", code="indisponivel")
    nota, comentario = int(nota), comentario.strip()
    anterior = RespostaNPS.objects.filter(reserva=reserva).first()
    if anterior:
        if anterior.nota == nota and anterior.comentario == comentario:
            return anterior, False
        raise ValidationError("Esta estadia já foi avaliada. A resposta original foi preservada.", code="duplicada")
    resposta = RespostaNPS.objects.create(reserva=reserva, hospede=reserva.hospede,
        nota=nota, comentario=comentario, canal=canal, consentimento_versao="2026-10-22")
    registrar_auditoria(usuario, "nps_resposta", resposta, {"reserva_id": reserva.pk, "nota": nota, "canal": canal})
    return resposta, True


def periodo(params):
    hoje = timezone.localdate()
    try:
        inicio = date.fromisoformat(params.get("de") or (hoje - timedelta(days=89)).isoformat())
        fim = date.fromisoformat(params.get("ate") or hoje.isoformat())
    except (ValueError, TypeError):
        raise ValidationError("Informe datas válidas para o período.")
    if fim < inicio or (fim - inicio).days > 3660:
        raise ValidationError("Escolha um período de até 10 anos, com início anterior ao fim.")
    return inicio, fim


def respostas_periodo(inicio, fim):
    return RespostaNPS.objects.select_related("hospede", "reserva", "tratada_por").filter(
        criado_em__date__gte=inicio, criado_em__date__lte=fim)


def resumo(respostas):
    dados = respostas.aggregate(total=Count("pk"), promotores=Count("pk", filter=Q(nota__gte=9)),
        passivos=Count("pk", filter=Q(nota__gte=7, nota__lte=8)), detratores=Count("pk", filter=Q(nota__lte=6)))
    dados["score"] = round(100 * (dados["promotores"] - dados["detratores"]) / dados["total"], 1) if dados["total"] else None
    return dados


@transaction.atomic
def tratar(resposta_id, texto, usuario):
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 2000:
        raise ValidationError("Descreva o acompanhamento em até 2.000 caracteres.")
    resposta = RespostaNPS.objects.select_for_update().get(pk=resposta_id)
    resposta.tratativa = texto.strip()
    resposta.tratada_em = timezone.now()
    resposta.tratada_por = usuario
    resposta.save(update_fields=["tratativa", "tratada_em", "tratada_por"])
    registrar_auditoria(usuario, "nps_acompanhamento", resposta, {"reserva_id": resposta.reserva_id})
    return resposta
