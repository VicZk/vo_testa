"""Spedy: NFS-e pelo Ambiente Nacional. Contratos consultados em 25/10/2026.

https://docs.spedy.com.br/api-reference/nfs-e/criar-nfs-e.md
https://docs.spedy.com.br/api-reference/nfs-e/obter-nfs-e.md
https://docs.spedy.com.br/api-reference/nfs-e/cancelar-nfs-e.md
https://docs.spedy.com.br/guides/ciclo-de-vida-da-nota.md
https://docs.spedy.com.br/webhooks/assinatura.md

A emissão é assíncrona: o POST só aceita a nota, e o fecho (autorizada/rejeitada) chega
pelo retorno assinado ou pela consulta. O `integrationId` é a nossa referência
(`gateway_id`): reenviar com ele atualiza a mesma nota, sem criar outra. O id do Spedy
volta na resposta e fica em `payload["spedy_id"]` para consultar e cancelar.
"""
import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal
from urllib import error, request
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.nucleo.validadores import decimal_valido

from .erros import CancelamentoPendente

BASE_PRODUCAO = "https://api.spedy.com.br"
BASE_SANDBOX = "https://sandbox-api.spedy.com.br"
# created, enqueued, received e inContingent ainda estão no provedor ou no fisco.
# removed (saiu antes do envio) e disabled (numeração inutilizada) não se corrigem com
# reenvio: ficam rejeitadas e pedem conciliação no painel do Spedy, como a denied.
ESTADOS = {"authorized": "autorizada", "canceled": "cancelada", "rejected": "rejeitada",
           "denied": "rejeitada", "removed": "rejeitada", "disabled": "rejeitada"}


def normalizar(dados, base):
    if not isinstance(dados, dict):
        raise ValidationError("O provedor fiscal retornou um formato inválido. Consulte antes de reenviar.")
    estado = str(dados.get("status", ""))
    status = ESTADOS.get(estado, "processando")
    spedy_id = str(dados.get("id") or "")[:64]
    autorizacao = dados.get("authorization") if isinstance(dados.get("authorization"), dict) else {}
    rps = dados.get("rps") if isinstance(dados.get("rps"), dict) else {}
    detalhe = dados.get("processingDetail") if isinstance(dados.get("processingDetail"), dict) else {}
    numero = str(dados.get("number") or "")
    chave = str(dados.get("accessKey") or dados.get("verificationCode") or "")
    if status == "autorizada" and not (numero or chave):
        raise ValidationError("O provedor não confirmou o número ou chave do documento.")
    # PDF e XML da nota emitida não pedem a chave da API.
    arquivo = (f"{base}/v1/service-invoices/{quote(spedy_id, safe='')}/"
               if spedy_id and status in ("autorizada", "cancelada") else "")
    return {"status": status, "numero": numero[:30], "chave": chave[:60],
        "serie": str(rps.get("series") or "")[:10],
        "protocolo": str(autorizacao.get("protocol") or "")[:60],
        "pdf_url": arquivo + "pdf" if arquivo else "", "xml_url": arquivo + "xml" if arquivo else "",
        "motivo_rejeicao": ("Documento rejeitado pelo provedor. Confira os detalhes no painel do Spedy." if status == "rejeitada" else ""),
        "payload": {"spedy_id": spedy_id} if spedy_id else {},
        "retorno": {"status": estado[:30], "codigo": str(detalhe.get("code") or "")[:60]}}


def assinatura_valida(corpo, cabecalhos, segredo, *, agora=None, tolerancia=300):
    """Assinatura do retorno (padrão Standard Webhooks): HMAC-SHA256 de
    `{webhook-id}.{webhook-timestamp}.{corpo cru}` com o segredo da conta (`whsec_…`)."""
    ident = cabecalhos.get("webhook-id", "")
    carimbo = cabecalhos.get("webhook-timestamp", "")
    assinaturas = cabecalhos.get("webhook-signature", "")
    if not ident or not carimbo.isdigit() or not assinaturas or not segredo:
        return False
    if abs((int(time.time()) if agora is None else agora) - int(carimbo)) > tolerancia:
        return False
    try:
        chave = base64.b64decode(segredo.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError):
        return False
    esperado = base64.b64encode(hmac.new(chave, f"{ident}.{carimbo}.".encode() + corpo, hashlib.sha256).digest()).decode()
    # Na troca do segredo, o Spedy manda mais de uma assinatura ("v1,<base64>" separadas por espaço).
    return any(versao == "v1" and hmac.compare_digest(valor, esperado)
               for versao, _, valor in (item.partition(",") for item in assinaturas.split()))


class GatewaySpedy:
    nome = "spedy"

    def __init__(self):
        if not settings.SPEDY_API_KEY:
            raise ValidationError("Configure a chave da API do Spedy para este ambiente.")
        self.base = BASE_SANDBOX if settings.SPEDY_SANDBOX else BASE_PRODUCAO
        emitente = re.sub(r"\D", "", settings.EMPRESA_CNPJ)
        self.ambiente = "spedy:" + hashlib.sha256((self.base+"#"+emitente).encode()).hexdigest()

    def _req(self, metodo, caminho, corpo=None, *, ausente=False):
        pedido = request.Request(self.base+caminho, method=metodo,
            data=json.dumps(corpo, ensure_ascii=False, allow_nan=False).encode() if corpo is not None else None,
            headers={"X-Api-Key": settings.SPEDY_API_KEY, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with request.urlopen(pedido, timeout=20) as resposta:
                dados = json.loads(resposta.read(1024*1024).decode())
                if not isinstance(dados, dict):
                    raise ValueError()
                return dados
        except error.HTTPError as exc:
            if ausente and exc.code == 404:
                return None
            # Corpos de erro podem conter CPF/endereço e nunca entram em logs ou telas.
            raise ValidationError(f"O provedor fiscal recusou a solicitação (HTTP {exc.code}). Consulte o documento e o cadastro no provedor antes de reenviar.")
        except (error.URLError, TimeoutError, OSError):
            raise ValidationError("Não foi possível confirmar a operação fiscal. Consulte o documento antes de reenviar.")
        except (ValueError, UnicodeDecodeError):
            raise ValidationError("Resposta fiscal inválida. A operação não foi confirmada.")

    def _rota(self, doc):
        if doc.tipo != "nfse":
            raise ValidationError("Pelo Spedy, o sistema emite só a NFS-e por enquanto. A NFC-e aguarda a inscrição estadual.")
        return "/v1/service-invoices"

    def _nota(self, doc):
        sid = str(doc.payload.get("spedy_id") or "")
        return self._rota(doc)+"/"+quote(sid, safe="") if sid else ""

    def montar_payload(self, doc):
        self._rota(doc)
        if len(doc.gateway_id) > 36:
            raise ValidationError("A referência fiscal passou do tamanho aceito pelo Spedy.")
        codigo = str(doc.payload.get("codigo_servico") or settings.FISCAL_NFSE_CODIGO_SERVICO)
        if not re.fullmatch(r"[0-9]{6}", codigo):
            raise ValidationError("Classifique o serviço com o código de tributação nacional (6 dígitos).")
        pessoa = doc.tomador
        documento = re.sub(r"\D", "", pessoa.documento if pessoa else "")
        if not pessoa or len(documento) not in (11, 14):
            raise ValidationError("Informe nome e CPF/CNPJ válido do tomador no cadastro antes de emitir.")
        valor = decimal_valido(doc.valor, minimo=Decimal("0.01"))
        iss = decimal_valido(doc.payload.get("iss_aliquota") or settings.FISCAL_NFSE_ISS_ALIQUOTA, maximo=Decimal("100"))
        # O código nacional tem item, subitem e desdobro (090101); a LC 116 usa o item (9.01).
        item = settings.FISCAL_NFSE_LC116 if codigo == settings.FISCAL_NFSE_CODIGO_SERVICO else f"{int(codigo[:2])}.{codigo[2:4]}"
        recebedor = {"name": pessoa.nome, "federalTaxNumber": documento}
        if pessoa.email:
            recebedor["email"] = pessoa.email
        # O JSON só tem número binário: valor e alíquota saem do Decimal já validado.
        return {"integrationId": doc.gateway_id, "effectiveDate": doc.criado_em.isoformat(),
            "description": doc.descricao, "federalServiceCode": item, "nationalTaxationCode": codigo,
            "total": {"invoiceAmount": float(valor), "issRate": float(iss)}, "receiver": recebedor}

    def consultar(self, doc):
        nota = self._nota(doc)
        if not nota:
            return None
        dados = self._req("GET", nota, ausente=True)
        return normalizar(dados, self.base) if dados is not None else None

    def emitir(self, doc):
        # Sem o id do Spedy (primeiro envio ou resposta perdida), o reenvio com o mesmo
        # integrationId atualiza a nota que já existir em vez de criar outra.
        atual = self.consultar(doc)
        if atual is not None:
            return atual
        return self.submeter(doc)

    def submeter(self, doc):
        return normalizar(self._req("POST", self._rota(doc), doc.payload_envio), self.base)

    def cancelar(self, doc, motivo):
        nota = self._nota(doc)
        if not nota:
            raise ValidationError("O Spedy ainda não devolveu a identificação desta nota. Consulte o documento antes de cancelar.")
        atual = self.consultar(doc)
        if atual and atual["status"] == "cancelada":
            return atual
        resultado = normalizar(self._req("DELETE", nota, {"reason": motivo}), self.base)
        if resultado["status"] != "cancelada":
            raise CancelamentoPendente("O Spedy recebeu o pedido de cancelamento. A confirmação chega pelo retorno do provedor; consulte o documento em alguns minutos.")
        return resultado
