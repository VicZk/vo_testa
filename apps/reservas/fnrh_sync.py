"""Sincronização com progresso durável e exclusão entre trabalhadores.

Cada confirmação remota é gravada antes da próxima chamada. Falhas não desfazem
identificadores já aceitos, e o gateway reconcilia a resposta perdida por consulta.
"""
import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import fnrh_gateway
from .models import Reserva

log = logging.getLogger(__name__)


def enviar(reserva):
    with transaction.atomic():
        atual = Reserva.objects.select_for_update().get(pk=reserva.pk)
        assinatura = hashlib.sha256(json.dumps(fnrh_gateway.payload_reserva(atual), sort_keys=True).encode()).hexdigest()
        ambiente_configurado = ("simulado" if settings.FNRH_GATEWAY == "simulado" else
            "serpro:" + hashlib.sha256(getattr(settings, "FNRH_API_URL", "").rstrip("/").encode()).hexdigest())
        if (settings.FNRH_GATEWAY in ("simulado", "serpro")
                and atual.fnrh_status == Reserva.SincFNRH.ENVIADA and atual.fnrh_etapa == atual.status
                and atual.fnrh_hash == assinatura and atual.fnrh_ambiente == ambiente_configurado):
            return True
        if atual.fnrh_em_processamento_ate and atual.fnrh_em_processamento_ate > timezone.now():
            return False
        lease = timezone.now() + timedelta(minutes=5)
        Reserva.objects.filter(pk=atual.pk).update(fnrh_em_processamento_ate=lease)

    def salvar(**campos):
        nonlocal lease
        novo_lease = timezone.now() + timedelta(minutes=5)
        mudou = Reserva.objects.filter(pk=atual.pk, fnrh_em_processamento_ate=lease).update(
            **campos, fnrh_em_processamento_ate=novo_lease)
        if not mudou:
            raise ValidationError("A sincronização foi retomada em outra sessão. Atualize a tela.")
        lease = novo_lease
        for campo, valor in campos.items():
            setattr(atual, campo, valor)

    try:
        gw = fnrh_gateway.get_gateway()
        if atual.fnrh_reserva_id and atual.fnrh_ambiente != gw.ambiente:
            if atual.fnrh_ambiente == "simulado":
                # IDs de demonstração jamais são enviados à API real.
                with transaction.atomic():
                    salvar(fnrh_reserva_id=None, fnrh_etapa="", fnrh_hash="", fnrh_ambiente=gw.ambiente)
                    atual.fichas_fnrh.update(fnrh_pessoa_id=None, fnrh_hospede_id=None)
            else:
                raise ValidationError("Os identificadores FNRH pertencem a outro ambiente ou têm origem legada. Confira a origem antes de sincronizar.")
        if not atual.fnrh_ambiente:
            salvar(fnrh_ambiente=gw.ambiente)
        encerrada = atual.status in (Reserva.Status.CANCELADA, Reserva.Status.NO_SHOW)
        if encerrada and not atual.fnrh_reserva_id:
            return True  # A reserva nunca foi enviada; não cria uma hospedagem cancelada.
        if not atual.fnrh_reserva_id:
            salvar(fnrh_reserva_id=gw.criar_reserva(atual))
        elif atual.fnrh_hash != assinatura and not encerrada:
            gw.atualizar_reserva(atual)
        if not atual.fnrh_etapa and atual.fnrh_status == Reserva.SincFNRH.ENVIADA:
            salvar(fnrh_etapa=Reserva.Status.HOSPEDADA)
        if not atual.fnrh_etapa and atual.status in (Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT):
            fichas = list(atual.fichas_fnrh.all())
            # O gateway simulado continua útil em ambientes de demonstração.
            if gw.nome == "serpro" and (len(fichas) != atual.total_hospedes or not all(f.completa for f in fichas)):
                raise ValidationError("Complete e confira todas as fichas antes de enviar à FNRH.")
            for ficha in fichas:
                if not ficha.completa:
                    continue
                if not ficha.fnrh_pessoa_id:
                    ficha.fnrh_pessoa_id = gw.criar_pessoa(ficha)
                    ficha.save(update_fields=["fnrh_pessoa_id"])
                    salvar()
                if not ficha.fnrh_hospede_id:
                    ficha.fnrh_hospede_id = gw.adicionar_hospede(atual.fnrh_reserva_id, ficha, ficha.fnrh_pessoa_id)
                    ficha.save(update_fields=["fnrh_hospede_id"])
                    salvar()
            gw.checkin(atual.fnrh_reserva_id, data_hora=atual.checkin_real)
            salvar(fnrh_etapa=Reserva.Status.HOSPEDADA)
        if atual.status == Reserva.Status.CHECKOUT and atual.fnrh_etapa != atual.status:
            gw.checkout(atual.fnrh_reserva_id, data_hora=atual.checkout_real)
        elif atual.status == Reserva.Status.CANCELADA and atual.fnrh_etapa != atual.status:
            gw.cancelar(atual.fnrh_reserva_id)
        elif atual.status == Reserva.Status.NO_SHOW and atual.fnrh_etapa != atual.status:
            gw.noshow(atual.fnrh_reserva_id)
        versao_atual = Reserva.objects.get(pk=atual.pk)
        assinatura_atual = hashlib.sha256(json.dumps(fnrh_gateway.payload_reserva(versao_atual), sort_keys=True).encode()).hexdigest()
        sincronizada = versao_atual.status == atual.status and assinatura_atual == assinatura
        salvar(fnrh_etapa=atual.status, fnrh_status=Reserva.SincFNRH.ENVIADA if sincronizada else Reserva.SincFNRH.PENDENTE,
               fnrh_hash=assinatura, fnrh_sincronizada_em=timezone.now(), fnrh_erro="")
        return sincronizada
    except Exception as erro:
        # Erros HTTP do gateway já vêm sem corpo, documento ou credencial.
        mensagem = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Falha de integração; confira a configuração e tente novamente."
        Reserva.objects.filter(pk=atual.pk, fnrh_em_processamento_ate=lease).update(
            fnrh_status=Reserva.SincFNRH.ERRO, fnrh_erro=mensagem[:500])
        log.warning("FNRH pendente: reserva=%s tipo=%s", atual.pk, type(erro).__name__)
        return False
    finally:
        Reserva.objects.filter(pk=atual.pk, fnrh_em_processamento_ate=lease).update(fnrh_em_processamento_ate=None)
        reserva.refresh_from_db()


def pendentes():
    ativos = Q(status__in=[Reserva.Status.HOSPEDADA, Reserva.Status.CHECKOUT])
    encerrados = Q(status__in=[Reserva.Status.CANCELADA, Reserva.Status.NO_SHOW], fnrh_reserva_id__isnull=False)
    return Reserva.objects.filter(ativos | encerrados).filter(
        fnrh_status__in=[Reserva.SincFNRH.PENDENTE, Reserva.SincFNRH.ERRO])
