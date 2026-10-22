"""
Gateway fiscal plugável. Escolha via `FISCAL_GATEWAY` no settings.

- `simulado` (default): sandbox — autoriza na hora com número/chave fake. Serve para
  testar o fluxo do módulo sem credencial nenhuma.
- `focus`: Focus NFe v2, NFS-e Nacional e NFC-e. Exige cadastro, credenciais e ensaio.
  Integração direta com governo e outros provedores não estão disponíveis.

Interface: criar_documento(doc) -> dict; cancelar(doc, motivo) -> dict.
O dict de emissão pode conter: gateway, gateway_id, numero, serie, chave, protocolo,
xml_url, pdf_url, status ('autorizada'|'rejeitada'), motivo_rejeicao, payload.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .focus import GatewayFocus


class GatewayFiscalBase:
    nome = "base"

    def emitir(self, documento) -> dict:
        raise NotImplementedError

    def cancelar(self, documento, motivo) -> dict:
        raise NotImplementedError


class GatewaySimulado(GatewayFiscalBase):
    """Sandbox: autoriza imediatamente com dados fake (para testes/demonstração)."""
    nome = "simulado"
    ambiente = "simulado"

    def montar_payload(self, documento):
        return {"sandbox": True}

    def emitir(self, documento) -> dict:
        gid = documento.gateway_id or f"SIM-{uuid.uuid4().hex[:12].upper()}"
        chave = "".join(filter(str.isdigit, uuid.uuid4().hex))[:44].ljust(44, "0")
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "status": "autorizada",
            "numero": str(abs(hash(gid)) % 100000),
            "serie": "1",
            "chave": chave,
            "protocolo": gid,
            "xml_url": "",
            "pdf_url": "",
            "payload": {"sandbox": True, "emitido_em": timezone.now().isoformat()},
        }

    def cancelar(self, documento, motivo) -> dict:
        return {"status": "cancelada"}

    def consultar(self, documento):
        return {"status": documento.status}


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "focus": GatewayFocus,
}


def get_gateway(nome=None):
    nome = nome or getattr(settings, "FISCAL_GATEWAY", "simulado")
    if nome not in _GATEWAYS:
        raise ValidationError("Provedor fiscal indisponível. Configure Focus NFe ou use o emissor externo conciliado; simulação exige seleção explícita.")
    return _GATEWAYS[nome]()
