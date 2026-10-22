"""Ciclo fiscal persistido, com referência estável e confirmação pelo provedor."""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.validadores import decimal_valido, identificador_valido

from .focus import normalizar
from .gateways import get_gateway
from .models import DocumentoFiscal, EventoFiscal


def ibs_cbs(valor):
    # Estimativa local pelas alíquotas configuradas; a nota autorizada é a referência fiscal.
    if not settings.FISCAL_IBS_CBS_ATIVO:
        return {}
    cbs = decimal_valido(settings.FISCAL_CBS_ALIQUOTA, maximo=Decimal("100"))
    ibs = decimal_valido(settings.FISCAL_IBS_ALIQUOTA, maximo=Decimal("100"))
    return {"cbs_aliquota": cbs, "cbs_valor": (valor*cbs/100).quantize(Decimal(".01")),
            "ibs_aliquota": ibs, "ibs_valor": (valor*ibs/100).quantize(Decimal(".01"))}


def _criar(operador, *, natureza, valor, descricao, tomador=None, referencia="", payload=None):
    valor = decimal_valido(valor, minimo=Decimal("0.01"))
    if natureza not in NaturezaFiscal.values:
        raise ValidationError("Natureza fiscal inválida.")
    if not isinstance(descricao, str) or not descricao.strip() or len(descricao) > 200:
        raise ValidationError("Descreva o documento em até 200 caracteres.")
    if not isinstance(referencia, str) or len(referencia) > 120:
        raise ValidationError("Referência fiscal inválida.")
    tipo = "nfse" if natureza == NaturezaFiscal.SERVICO else "nfce"
    existente = DocumentoFiscal.objects.filter(referencia=referencia, tipo=tipo).exclude(status="cancelada").first() if referencia else None
    if existente:
        if existente.valor != valor or existente.tomador_id != getattr(tomador, "pk", None):
            raise ValidationError("A origem mudou após a emissão. Concilie ou cancele a nota anterior antes de emitir novamente.")
        if payload and payload.get("codigo_servico") != existente.payload.get("codigo_servico"):
            raise ValidationError("A classificação mudou após a emissão. Concilie a nota anterior antes de emitir novamente.")
        return existente
    gw = get_gateway()
    try:
        with transaction.atomic():
            doc = DocumentoFiscal.objects.create(tipo=tipo, natureza=natureza,
                descricao=descricao.strip(), valor=valor, tomador=tomador, referencia=referencia,
                criado_por=operador, gateway=gw.nome, gateway_ambiente=gw.ambiente,
                gateway_id="vt-"+uuid.uuid4().hex, payload=payload or {}, **ibs_cbs(valor))
            # Validação antes de qualquer rede; um cadastro incompleto não vira sucesso fictício.
            doc.payload_envio = gw.montar_payload(doc)
            doc.save(update_fields=["payload_envio"])
            EventoFiscal.objects.create(documento=doc, tipo="emissao", detalhe={"gateway":gw.nome})
            return doc
    except IntegrityError:
        if not referencia:
            raise
        existente = DocumentoFiscal.objects.filter(referencia=referencia, tipo=tipo).exclude(status="cancelada").first()
        if not existente:
            raise
        if existente.valor != valor or existente.tomador_id != getattr(tomador, "pk", None):
            raise ValidationError("A origem mudou durante a emissão. Consulte o documento existente.")
        if payload and payload.get("codigo_servico") != existente.payload.get("codigo_servico"):
            raise ValidationError("A classificação mudou durante a emissão. Consulte o documento existente.")
        return existente


@transaction.atomic
def _reivindicar(doc_id, acao):
    doc = DocumentoFiscal.objects.select_for_update(of=("self",)).select_related("tomador").get(pk=doc_id)
    if doc.status == "cancelada" or (acao == "emitir" and doc.status == "autorizada"):
        return doc, None
    if acao == "cancelar" and doc.status != "autorizada":
        raise ValidationError("Só documentos autorizados podem ser cancelados.")
    if acao == "corrigir" and doc.status != "rejeitada":
        raise ValidationError("A correção exige rejeição confirmada pelo provedor.")
    if doc.envio_token and doc.envio_em and doc.envio_em > timezone.now()-timedelta(seconds=90):
        return doc, None
    token = uuid.uuid4()
    doc.envio_token, doc.envio_em = token, timezone.now()
    if acao == "emitir":
        doc.status = "processando"
    doc.save(update_fields=["envio_token", "envio_em", "status"])
    return doc, token


@transaction.atomic
def _aplicar(doc_id, resultado, token=None, origem="consulta"):
    doc = DocumentoFiscal.objects.select_for_update().get(pk=doc_id)
    if token and doc.envio_token != token:
        return doc
    estado = resultado.get("status")
    if estado not in DocumentoFiscal.Status.values:
        raise ValidationError("O provedor não informou uma situação fiscal reconhecida.")
    anterior = doc.status
    permitido = anterior != "cancelada" and not (anterior == "autorizada" and estado not in ("autorizada", "cancelada"))
    if permitido:
        doc.status = estado
        for campo in ("numero", "serie", "chave", "protocolo", "xml_url", "pdf_url"):
            if resultado.get(campo):
                setattr(doc, campo, resultado[campo])
        doc.motivo_rejeicao = str(resultado.get("motivo_rejeicao") or "")[:255]
        doc.payload = {**doc.payload, **resultado.get("payload", {}), "retorno":resultado.get("retorno", {})}
        if estado == "autorizada" and not doc.autorizada_em:
            doc.autorizada_em = timezone.now()
        if anterior != estado:
            EventoFiscal.objects.create(documento=doc, tipo=estado, detalhe={"origem":origem})
    if token:
        doc.envio_token = None
        doc.envio_em = None
    doc.save()
    return doc


def _gateway_documento(doc):
    gw = get_gateway(doc.gateway)
    if doc.gateway_ambiente != gw.ambiente:
        raise ValidationError("O documento pertence a outro ambiente fiscal ou tem origem legada. Concilie a origem antes de enviar.")
    return gw


def _executar(doc_id, acao, motivo=""):
    doc, token = _reivindicar(doc_id, acao)
    if token is None:
        return doc
    try:
        gw = _gateway_documento(doc)
        if acao == "corrigir":
            resultado = gw.consultar(doc)
            if resultado and resultado.get("status") == "rejeitada":
                if resultado.get("retorno", {}).get("status") not in ("erro_autorizacao", "rejeitado", "rejeitada"):
                    raise ValidationError("Esta rejeição exige conciliação no provedor antes de uma nova emissão.")
                if doc.tipo == "nfce":
                    from .consumo import renovar_payload
                    doc.payload = {**doc.payload, "nfce": renovar_payload(doc)}
                doc.payload_envio = gw.montar_payload(doc)
                with transaction.atomic():
                    atual = DocumentoFiscal.objects.select_for_update().get(pk=doc.pk)
                    if atual.envio_token != token or atual.status != "rejeitada":
                        return atual
                    atual.payload, atual.payload_envio = doc.payload, doc.payload_envio
                    atual.save(update_fields=["payload", "payload_envio"])
                    EventoFiscal.objects.create(documento=atual, tipo="correcao")
                resultado = gw.submeter(doc)
        else:
            resultado = gw.cancelar(doc, motivo) if acao == "cancelar" else getattr(gw, acao)(doc)
        if resultado is None:
            raise ValidationError("O provedor ainda não encontrou a referência. Reenviar usa a mesma referência, sem criar outro documento.")
        if acao == "cancelar" and resultado.get("status") != "cancelada":
            raise ValidationError("O provedor não confirmou o cancelamento.")
        return _aplicar(doc.pk, resultado, token, acao)
    except ValidationError as erro:
        # Mantém o documento e a referência após falha de rede/validação externa.
        DocumentoFiscal.objects.filter(pk=doc.pk, envio_token=token).update(
            envio_token=None, envio_em=None, motivo_rejeicao=" ".join(erro.messages)[:255])
        raise


def emitir(operador, *, natureza, valor, descricao, tomador=None, referencia="", payload=None):
    doc = _criar(operador, natureza=natureza, valor=valor, descricao=descricao,
                 tomador=tomador, referencia=referencia, payload=payload)
    return _executar(doc.pk, "emitir")


def consultar(documento):
    return _executar(documento.pk, "consultar")


def reenviar(documento):
    return _executar(documento.pk, "emitir")


def corrigir(documento):
    return _executar(documento.pk, "corrigir")


def cancelar(documento, operador, motivo):
    if not isinstance(motivo, str) or not 15 <= len(motivo.strip()) <= 255:
        raise ValidationError("Descreva o motivo do cancelamento em 15 a 255 caracteres.")
    doc = _executar(documento.pk, "cancelar", motivo.strip())
    if doc.status == "cancelada" and not doc.eventos.filter(tipo="cancelamento_log").exists():
        with transaction.atomic():
            DocumentoFiscal.objects.select_for_update().get(pk=doc.pk)
            if not doc.eventos.filter(tipo="cancelamento_log").exists():
                registrar_auditoria(operador, "cancelamento_fiscal", doc, {"motivo":motivo.strip()})
                EventoFiscal.objects.create(documento=doc, tipo="cancelamento_log")
    return doc


def emitir_nfse_da_conta(conta_id, operador, codigo_servico=None):
    if not modulo_ativo(Modulo.RESERVAS):
        raise ValidationError("Módulo Reservas inativo.")
    conta_id = identificador_valido(conta_id, nome="Conta")
    from apps.reservas.models import ContaHospedagem
    from apps.reservas.services import resumo_fiscal_conta

    from .servicos import grupo_para_emitir, referencia
    with transaction.atomic():
        conta = ContaHospedagem.objects.select_for_update().filter(pk=conta_id).first()
        if not conta:
            raise ValidationError("Conta não encontrada.")
        resumo = resumo_fiscal_conta(conta_id)
        if not resumo:
            raise ValidationError("Conta sem titular para emissão fiscal.")
        codigo = codigo_servico or settings.FISCAL_NFSE_CODIGO_SERVICO
        grupo = grupo_para_emitir(conta, codigo)
        descricao = "Hospedagem" if codigo == settings.FISCAL_NFSE_CODIGO_SERVICO else f"Serviço {codigo}"
        doc = _criar(operador, natureza=NaturezaFiscal.SERVICO, valor=grupo["valor"],
            descricao=f"{descricao}: {resumo['uh']}", tomador=resumo["hospede"], referencia=referencia(conta_id,codigo),
            payload={"codigo_servico":codigo,"lancamentos":grupo["linhas"],"desconto_rateado":str(grupo["desconto"]),
                "iss_aliquota":settings.FISCAL_NFSE_ISS_ALIQUOTA, "regime":settings.FISCAL_REGIME})
    # Nunca mantém lock da conta durante chamada de rede.
    return _executar(doc.pk, "emitir")


def processar_retorno_focus(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("ref"), str) or len(payload["ref"]) > 80:
        raise ValidationError("Retorno fiscal inválido.")
    doc = DocumentoFiscal.objects.filter(gateway="focus", gateway_id=payload["ref"]).first()
    if doc is None:
        return None
    gw = _gateway_documento(doc)
    resultado = normalizar(payload, gw.base)
    return _aplicar(doc.pk, resultado, origem="webhook")


def configuracao():
    nome = settings.FISCAL_GATEWAY
    if nome == "simulado":
        return {"mensagem":"Modo de teste. Documentos simulados não têm validade fiscal.", "pendencias":[]}
    pendencias = []
    try:
        get_gateway()
    except ValidationError as erro:
        pendencias.extend(erro.messages)
    for chave, rotulo in (("FISCAL_EMITENTE_CNPJ", "CNPJ do emitente"),
                         ("FISCAL_MUNICIPIO_IBGE", "Código IBGE do município"),
                         ("FISCAL_DPS_SERIE", "Série DPS exclusiva"),
                         ("FISCAL_WEBHOOK_TOKEN", "Autenticação do retorno fiscal")):
        if not getattr(settings, chave, ""):
            pendencias.append(rotulo+": configuração pendente.")
    ambiente = "homologação" if "homologacao" in settings.FISCAL_FOCUS_URL else "produção"
    return {"mensagem":f"Focus NFe: ambiente de {ambiente}. A validade depende da autorização do documento pelo fisco. Confirme o cadastro e os parâmetros com o responsável fiscal.",
            "pendencias":pendencias}


def pendencias_auditoria():
    """Documentos fiscais rejeitados para a Auditoria (read-only)."""
    from django.urls import reverse
    achados = []
    for d in DocumentoFiscal.objects.filter(status=DocumentoFiscal.Status.REJEITADA):
        achados.append({
            "area": "Fiscal", "tipo": "nota_rejeitada", "gravidade": "alta",
            "descricao": f"{d.get_tipo_display()} #{d.pk} rejeitada: {d.motivo_rejeicao or 'sem motivo'}.",
            "url": reverse("fiscal:detalhe", args=[d.pk]),
        })
    return achados
