"""Focus NFe v2: NFS-e Nacional e NFC-e. Contratos consultados em 22/10/2026.

https://doc.focusnfe.com.br/reference/emitir_dps_nacional
https://doc.focusnfe.com.br/reference/emitir_nfce
"""
import base64
import hashlib
import json
import re
from decimal import Decimal
from urllib import error, request
from urllib.parse import quote, urlencode, urljoin, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.nucleo.validadores import decimal_valido


def normalizar(dados, base):
    if not isinstance(dados, dict):
        raise ValidationError("O provedor fiscal retornou um formato inválido. Consulte antes de reenviar.")
    estado = str(dados.get("status", "")).lower()
    status = {"autorizado": "autorizada", "autorizada": "autorizada",
              "cancelado": "cancelada", "cancelada": "cancelada"}.get(estado, "processando")
    if estado in ("erro_autorizacao", "rejeitado", "rejeitada", "denegado"):
        status = "rejeitada"
    numero = str(dados.get("numero") or dados.get("numero_nfse") or "")
    chave = str(dados.get("chave_nfse") or dados.get("chave_nfe") or dados.get("codigo_verificacao") or "")
    if status == "autorizada" and not (numero or chave):
        raise ValidationError("O provedor não confirmou o número ou chave do documento.")
    def link(valor):
        url = urljoin(base + "/", str(valor)) if valor else ""
        return url if urlsplit(url).scheme == "https" else ""
    return {"status": status, "numero": numero[:30], "chave": chave[:60],
        "serie": str(dados.get("serie") or "")[:10],
        "protocolo": str(dados.get("protocolo") or "")[:60],
        "pdf_url": link(dados.get("url_danfse") or dados.get("caminho_danfe") or dados.get("url")),
        "xml_url": link(dados.get("caminho_xml_nota_fiscal") or dados.get("url_xml")),
        "motivo_rejeicao": ("Documento rejeitado pelo provedor. Confira os detalhes no painel fiscal do provedor." if status == "rejeitada" else ""),
        "retorno": {"status": estado, "codigo": str(dados.get("codigo") or dados.get("status_sefaz") or "")[:60]}}


class GatewayFocus:
    nome = "focus"

    def __init__(self):
        self.base = settings.FISCAL_FOCUS_URL.rstrip("/")
        if self.base not in ("https://api.focusnfe.com.br", "https://homologacao.focusnfe.com.br"):
            raise ValidationError("Configure a URL oficial de homologação ou produção da Focus NFe.")
        if not settings.FISCAL_FOCUS_TOKEN:
            raise ValidationError("Configure o token da Focus NFe para este ambiente.")
        emitente = re.sub(r"\D", "", settings.FISCAL_EMITENTE_CNPJ)
        self.ambiente = "focus:" + hashlib.sha256((self.base+"#"+emitente).encode()).hexdigest()
        self.auth = "Basic " + base64.b64encode((settings.FISCAL_FOCUS_TOKEN + ":").encode()).decode()

    def _req(self, metodo, caminho, corpo=None, *, ausente=False):
        pedido = request.Request(self.base+caminho, method=metodo,
            data=json.dumps(corpo, ensure_ascii=False, allow_nan=False).encode() if corpo is not None else None,
            headers={"Authorization": self.auth, "Content-Type": "application/json", "Accept": "application/json"})
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
        if doc.tipo not in ("nfse", "nfce"):
            raise ValidationError("Este provedor está preparado para NFS-e Nacional e NFC-e.")
        return "/v2/" + ("nfsen" if doc.tipo == "nfse" else "nfce")

    def montar_payload(self, doc):
        cnpj = re.sub(r"\D", "", settings.FISCAL_EMITENTE_CNPJ)
        if len(cnpj) != 14:
            raise ValidationError("Configure o CNPJ do emitente fiscal.")
        if doc.tipo == "nfce":
            if not settings.FISCAL_NFCE_HABILITADA:
                raise ValidationError("NFC-e desabilitada. Confirme inscrição estadual, CSC e habilitação antes de emitir.")
            dados = doc.payload.get("nfce")
            if not isinstance(dados, dict) or not dados.get("items") or not dados.get("formas_pagamento"):
                raise ValidationError("A NFC-e exige os itens com códigos fiscais e as formas de pagamento.")
            if not isinstance(dados["items"], list) or not isinstance(dados["formas_pagamento"], list):
                raise ValidationError("Itens e pagamentos devem ser listas.")
            try:
                json.dumps(dados, allow_nan=False)
            except (ValueError, TypeError):
                raise ValidationError("Os dados fiscais contêm valores inválidos.")
            total = sum((decimal_valido(i.get("valor_bruto"))-decimal_valido(i.get("valor_desconto", 0))
                         for i in dados["items"] if isinstance(i, dict)), Decimal("0"))
            pago = sum((decimal_valido(p.get("valor_pagamento")) for p in dados["formas_pagamento"] if isinstance(p, dict)), Decimal("0"))
            if total != doc.valor or pago != doc.valor or not all(isinstance(i,dict) for i in dados["items"]+dados["formas_pagamento"]):
                raise ValidationError("Itens e pagamentos fiscais devem fechar no valor do documento.")
            return {**dados, "cnpj_emitente": cnpj, "data_emissao": timezone.now().isoformat()}
        ibge = settings.FISCAL_MUNICIPIO_IBGE
        serie = str(settings.FISCAL_DPS_SERIE)
        inicial = str(settings.FISCAL_DPS_NUMERO_INICIAL)
        if not re.fullmatch(r"[0-9]{7}", ibge) or not serie.isdigit() or not 1 <= int(serie) <= 49999:
            raise ValidationError("Configure município IBGE e uma série DPS exclusiva deste sistema (1 a 49999).")
        if not inicial.isdigit() or not 1 <= int(inicial) < 10**14:
            raise ValidationError("Configure o número inicial da DPS.")
        if settings.FISCAL_REGIME != "lucro_presumido":
            raise ValidationError("O perfil NFS-e disponível exige Lucro Presumido. Revise o perfil fiscal com o contador.")
        pessoa = doc.tomador
        documento = re.sub(r"\D", "", pessoa.documento if pessoa else "")
        if not pessoa or len(documento) not in (11, 14):
            raise ValidationError("Informe nome e CPF/CNPJ válido do tomador no cadastro antes de emitir.")
        try:
            extras = json.loads(settings.FISCAL_NFSE_COMPLEMENTOS)
            if not isinstance(extras, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError("Os complementos fiscais da NFS-e devem ser um objeto JSON válido.")
        valor = decimal_valido(doc.valor, minimo=Decimal("0.01"))
        dados = {**extras, "data_emissao": doc.criado_em.isoformat(),
            "data_competencia": doc.payload.get("competencia") or timezone.localdate().isoformat(),
            "serie_dps": int(serie), "numero_dps": int(inicial)+doc.pk-1,
            "emitente_dps": "1", "cnpj_prestador": cnpj,
            "codigo_municipio_emissora": ibge, "codigo_municipio_prestacao": ibge,
            "codigo_opcao_simples_nacional": "1", "regime_especial_tributacao": "0",
            "codigo_tributacao_nacional_iss": doc.payload.get("codigo_servico") or settings.FISCAL_NFSE_CODIGO_SERVICO,
            "descricao_servico": doc.descricao, "valor_servico": str(valor),
            "tributacao_iss": "1", "tipo_retencao_iss": "1",
            "razao_social_tomador": pessoa.nome,
            ("cpf_tomador" if len(documento) == 11 else "cnpj_tomador"): documento}
        if pessoa.email:
            dados["email_tomador"] = pessoa.email
        return dados

    def consultar(self, doc):
        dados = self._req("GET", self._rota(doc)+"/"+quote(doc.gateway_id, safe=""), ausente=True)
        return normalizar(dados, self.base) if dados is not None else None

    def emitir(self, doc):
        # Referência persistida antes do envio: timeout não cria outra nota.
        atual = self.consultar(doc)
        if atual is not None:
            return atual
        return self.submeter(doc)

    def submeter(self, doc):
        dados = self._req("POST", self._rota(doc)+"?"+urlencode({"ref":doc.gateway_id}), doc.payload_envio)
        return normalizar(dados, self.base)

    def cancelar(self, doc, motivo):
        atual = self.consultar(doc)
        if atual and atual["status"] == "cancelada":
            return atual
        self._req("DELETE", self._rota(doc)+"/"+quote(doc.gateway_id, safe=""), {"justificativa":motivo})
        confirmado = self.consultar(doc)
        if not confirmado or confirmado["status"] != "cancelada":
            raise ValidationError("O cancelamento ainda não foi confirmado pelo provedor. Consulte novamente.")
        return confirmado
