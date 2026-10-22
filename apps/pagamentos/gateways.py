"""
Abstração de gateway de pagamento.

- **simulado**: sandbox local (fim-a-fim sem provedor).
- **safrapay**: API e-commerce SafraPay (docs em developers.safrapay.com.br).
  Exige `SAFRAPAY_TOKEN` no .env. Sem token → ValidationError clara (não cai no simulado).
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from decimal import Decimal
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

# S-M5: blocos com PII do pagador que NÃO devem ser persistidos em Cobranca.payload
# (a reconciliação só precisa de id/status/valor/qrCode).
_CHAVES_PII = {"customer", "card", "cardholder", "document", "buyer", "payer", "holder",
               "billingaddress", "address", "cardnumber", "securitycode", "cvv", "cvc",
               "cardholdername", "cardholderdocument", "cpf", "cnpj", "email", "phone",
               "name", "nome", "telefone", "token", "accesstoken", "access_token"}


def _redigir_resposta(data):
    """Remove recursivamente blocos de PII da resposta do provedor antes de salvar."""
    if isinstance(data, dict):
        return {k: ("[redigido]" if str(k).casefold() in _CHAVES_PII else _redigir_resposta(v))
                for k, v in data.items()}
    if isinstance(data, list):
        return [_redigir_resposta(i) for i in data]
    return data


class ResultadoIncerto(ValidationError):
    """O provedor pode ter processado a operação; consultar antes de repetir."""


def _estado_cobranca(charge, valor):
    """SafraPay usa Authorized na cobrança com transação já Captured.

    Só confirma o valor integral de transações capturadas/pagas e não canceladas.
    Números de enum de chargeStatus e transactionStatus não são intercambiáveis.
    """
    txs = charge.get("transactions")
    if not isinstance(txs, list) or not txs or not all(isinstance(t, dict) for t in txs):
        return ""
    if str(charge.get("chargeStatus", "")).lower() in {"canceled", "cancelled"}:
        return "Canceled"
    pago = 0
    for tx in txs:
        if status_pago(tx.get("transactionStatus")) is True and tx.get("isCanceled") is not True:
            quantia = tx.get("amount")
            if type(quantia) is not int or quantia < 0:
                return ""
            pago += quantia
    if pago == int(valor * 100):
        return "Captured"
    if all(status_negado(t.get("transactionStatus")) for t in txs):
        return "Denied"
    return "Pending"


class GatewaySimulado:
    """Sandbox: gera identificadores/códigos fake e aceita estorno sempre."""
    nome = "simulado"
    ambiente = "simulado"

    def criar_cobranca(self, cobranca) -> dict:
        gid = f"SIM-{uuid.uuid4().hex[:16].upper()}"
        dados = {
            "gateway": self.nome,
            "gateway_id": gid,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {"sandbox": True, "metodo": cobranca.metodo},
        }
        if cobranca.metodo == cobranca.Metodo.PIX:
            dados["pix_copia_cola"] = (
                f"00020126VOTESTA{gid}5204000053039865802BR6009SAOPAULO62070503***6304SIM"
            )
        elif cobranca.metodo in (cobranca.Metodo.CARTAO, cobranca.Metodo.LINK):
            dados["payload"]["checkout_url"] = reverse("pagamentos:pagar", args=[cobranca.token])
            dados["payload"]["instrucao"] = "Sandbox: use «Já paguei» para simular o cartão."
        elif cobranca.metodo == cobranca.Metodo.BOLETO:
            dados["payload"]["linha_digitavel"] = (
                f"23793.38128 60000.000003 00000.000400 1 {gid[-8:]}"
            )
            dados["payload"]["instrucao"] = "Boleto de teste. Use «Já paguei» para simular o pagamento."
        return dados

    def autorizar_cartao(self, cobranca, card: dict, remote_ip: str = "") -> dict:
        """Sandbox: 'aprova' o cartão digitado sem tocar em rede."""
        gid = cobranca.gateway_id or f"SIM-{uuid.uuid4().hex[:16].upper()}"
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "status_raw": "captured",  # sandbox aprova
            "payload": {**(cobranca.payload or {}), "sandbox": True, "cartao_ok": True},
        }

    def estornar(self, cobranca) -> dict:
        return {"estornado": True, "gateway_id": cobranca.gateway_id}


class GatewaySafrapay:
    """
    Provider SafraPay (homologação/produção via SAFRAPAY_ENV).

    Fluxo: Merchant Token → POST /v2/merchant/auth → Bearer accessToken →
    POST /v2/charge/pix (ou outros). Token vazio no portal = conta sem API liberada.
    """
    nome = "safrapay"

    @property
    def ambiente(self):
        cred = self._credenciais()
        estabelecimento = hashlib.sha256(cred["merchant_id"].encode()).hexdigest()[:16]
        return f"{cred['base']}#{estabelecimento}"

    def _credenciais(self):
        token = (getattr(settings, "SAFRAPAY_TOKEN", "") or "").strip()
        merchant_id = (getattr(settings, "SAFRAPAY_ID", "") or "").strip()
        codigo = (getattr(settings, "SAFRAPAY_CODIGO_ATIVACAO", "") or "").strip()
        base = (getattr(settings, "SAFRAPAY_GATEWAY_URL", "") or "").rstrip("/")
        return {
            "token": token,
            "merchant_id": merchant_id,
            "codigo_ativacao": codigo,
            "base": base,
        }

    def _exigir_token(self):
        cred = self._credenciais()
        if not cred["token"]:
            raise ValidationError(
                "Safrapay: Token ausente no .env (SAFRAPAY_TOKEN). "
                "No portal Developers o campo Token precisa estar preenchido — "
                "solicite liberação da API e-commerce à SafraPay."
            )
        if not cred["base"]:
            raise ValidationError("Safrapay: SAFRAPAY_GATEWAY_URL não configurada.")
        esperado = {"hml": "https://payment-hml.safrapay.com.br", "prod": "https://payment.safrapay.com.br"}
        if cred["base"] != esperado.get(settings.SAFRAPAY_ENV):
            raise ValidationError("Safrapay: o endereço oficial deve corresponder ao ambiente hml ou prod.")
        return cred

    def _http(self, method, path, *, headers=None, body=None, timeout=None):
        # Timeout curto (SAFRAPAY_TIMEOUT, padrão 10 s): uma Safrapay lenta não segura o
        # worker, e o gunicorn (timeout 60 s) não mata o processo no meio da cobrança.
        timeout = timeout or getattr(settings, "SAFRAPAY_TIMEOUT", 10)
        cred = self._exigir_token()
        altera_cobranca = path in ("/v2/charge/pix", "/v2/charge/boleto", "/v2/charge/authorization") or path.startswith("/v2/charge/cancelation/")
        erro_incerto = ResultadoIncerto if altera_cobranca else ValidationError
        url = f"{cred['base']}{path}"
        data = None
        hdrs = {"Accept": "application/json", "User-Agent": "CRM-Vo-Testa/1.0"}
        if headers:
            hdrs.update(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        req = urlrequest.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urlerror.HTTPError as exc:
            logger.warning("Safrapay: requisição %s recusada, HTTP %s", method, exc.code)
            classe = erro_incerto if exc.code >= 500 or exc.code in (408, 409, 429) else ValidationError
            raise classe(f"Safrapay recusou a requisição (HTTP {exc.code}). Confira a operação no provedor.") from exc
        except urlerror.URLError as exc:
            raise erro_incerto("Safrapay indisponível. Consulte a cobrança antes de tentar novamente.") from exc
        except OSError as exc:
            # Tempo esgotado ou conexão caída durante a leitura não viram URLError.
            logger.warning("Safrapay: requisição %s sem resposta", method)
            raise erro_incerto("Safrapay não respondeu a tempo. Consulte a cobrança antes de tentar novamente.") from exc
        try:
            corpo = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            logger.warning("Safrapay: resposta sem JSON válido")
            raise erro_incerto("Safrapay devolveu uma resposta inválida.") from exc
        if not isinstance(corpo, dict):
            raise erro_incerto("Safrapay devolveu uma resposta inválida.")
        if corpo.get("success") is False:
            raise ValidationError("Safrapay não aceitou a operação. Confira o cadastro e o resultado no provedor.")
        return status, corpo

    def _access_token(self) -> str:
        cred = self._exigir_token()
        chave = "safrapay_token:" + hashlib.sha256((self.ambiente + cred["token"]).encode()).hexdigest()
        cached = cache.get(chave)
        if cached:
            return cached
        # Autenticação: Merchant Token cru no header Authorization → accessToken.
        # (Testado 200 em HML; o esquema bcrypt+CNPJ da doc não é o usado.)
        _status, data = self._http(
            "POST", "/v2/merchant/auth",
            headers={"Authorization": cred["token"]},
        )
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise ValidationError(
                "Safrapay: autenticação sem accessToken na resposta. "
                "Confira o Merchant Token no portal HML."
            )
        # JWT típico ~ hours; cache conservador 50 min
        cache.set(chave, token, timeout=50 * 60)
        return token

    def _centavos(self, valor) -> int:
        return int((Decimal(str(valor)) * 100).quantize(Decimal("1")))

    def _documento(self, cobranca) -> str:
        pagador = cobranca.pagador
        doc = "".join(
            c for c in (getattr(pagador, "documento", "") or "") if c.isdigit()
        )
        from apps.nucleo.validadores import validar_documento
        validar_documento(doc)
        if len(doc) not in (11, 14):
            raise ValidationError("Complete o CPF ou CNPJ válido do pagador antes da cobrança.")
        return doc

    def _telefone(self, cobranca) -> dict:
        """Telefone efetivamente informado pelo pagador."""
        phone = "".join(c for c in (getattr(cobranca.pagador, "telefone", "") or "") if c.isdigit())
        if phone.startswith("55") and len(phone) in (12, 13):
            phone = phone[2:]
        if len(phone) not in (10, 11):
            raise ValidationError("Complete o telefone brasileiro do pagador, com DDD.")
        return {
            "countryCode": "55",
            "areaCode": phone[-11:-9] if len(phone) >= 11 else phone[:2],
            "number": phone[-9:] if len(phone) >= 11 else phone[2:],
            "type": 5,
        }

    def _customer(self, cobranca, *, exigir_contato=False) -> dict:
        pagador = cobranca.pagador
        if not pagador or not pagador.nome.strip() or not pagador.email:
            raise ValidationError("Complete nome, documento e e-mail do pagador antes da cobrança.")
        doc = self._documento(cobranca)
        from django.core.validators import validate_email
        validate_email(pagador.email)
        customer = {
            "name": pagador.nome[:120],
            "email": pagador.email,
            "documentType": 1 if len(doc) == 11 else 2,
            "document": doc,
        }
        phone = "".join(c for c in (getattr(pagador, "telefone", "") or "") if c.isdigit())
        if len(phone) >= 10 or exigir_contato:
            customer["phone"] = self._telefone(cobranca)
        return customer

    def _endereco(self, cobranca) -> dict:
        """Endereço cadastrado, sem substituir dados faltantes pelos da pousada."""
        pagador = cobranca.pagador
        cep = "".join(c for c in (getattr(pagador, "cep", "") or "") if c.isdigit())
        campos = ("endereco", "numero", "bairro", "cidade", "uf")
        if not pagador or any(not getattr(pagador, c, "").strip() for c in campos) or len(cep) != 8:
            raise ValidationError("Complete endereço, número (ou S/N), bairro, cidade, UF e CEP do pagador.")
        return {
            "street": pagador.endereco[:120], "number": pagador.numero,
            "neighborhood": pagador.bairro, "city": pagador.cidade[:60],
            "state": pagador.uf.upper(), "zipCode": cep, "complement": pagador.complemento,
            "country": "BR",
        }

    def _endereco_cartao(self, cobranca, card):
        endereco = card.get("billingAddress") or self._endereco(cobranca)
        campos = ("street", "number", "neighborhood", "city", "state", "zipCode")
        if not isinstance(endereco, dict) or any(not isinstance(endereco.get(c), str) or not endereco[c].strip() for c in campos):
            raise ValidationError("Preencha o endereço de cobrança completo do titular do cartão.")
        cep = "".join(c for c in endereco["zipCode"] if c.isdigit())
        uf = endereco["state"].strip().upper()
        if len(cep) != 8 or uf not in "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split():
            raise ValidationError("Confira a UF e o CEP do endereço de cobrança.")
        return {**{c:endereco[c].strip()[:120] for c in campos}, "state":uf, "zipCode":cep,
            "complement":str(endereco.get("complement", ""))[:100], "country":"BR"}

    def _metadata(self, cobranca) -> list:
        return [
            {"key": "finalidade", "value": cobranca.finalidade},
            {"key": "cobranca_id", "value": str(cobranca.pk or "")},
            {"key": "reserva_id", "value": str(cobranca.reserva_id or "")},
        ]

    def _parse_charge(self, data, *, merchant_charge_id) -> tuple[str, dict]:
        charge = data.get("charge") or data
        if not isinstance(charge, dict):
            raise ResultadoIncerto("Safrapay: resposta de cobrança inválida.")
        gid = str(charge.get("id") or data.get("id") or "")
        if not gid:
            raise ResultadoIncerto("Safrapay: cobrança sem id na resposta.")
        if charge.get("merchantChargeId") not in (None, merchant_charge_id):
            raise ResultadoIncerto("Safrapay: a referência retornada pertence a outra cobrança.")
        return gid, charge

    def criar_cobranca(self, cobranca) -> dict:
        self._exigir_token()
        if cobranca.metodo == cobranca.Metodo.PIX:
            return self._criar_pix(cobranca)
        if cobranca.metodo in (cobranca.Metodo.CARTAO, cobranca.Metodo.LINK):
            # O link só abre o formulário. A emissão não autoriza cartão algum.
            return {
                "gateway": self.nome,
                "gateway_id": "",
                "expira_em": timezone.now() + timezone.timedelta(hours=24),
                "payload": {
                    "aguardando_cartao": True,
                    "checkout_url": reverse("pagamentos:pagar", args=[cobranca.token]),
                },
            }
        if cobranca.metodo == cobranca.Metodo.BOLETO:
            return self._criar_boleto(cobranca)
        raise ValidationError(f"Safrapay: método '{cobranca.metodo}' não suportado.")

    def autorizar_cartao(self, cobranca, card: dict, remote_ip: str = "") -> dict:
        """Autoriza o crédito à vista com o cartão digitado pelo hóspede na página
        pública. `card` = {cardholderName, cardNumber, expirationMonth,
        expirationYear, securityCode[, cardholderDocument]}. `remote_ip` = IP do
        hóspede (o antifraude usa)."""
        payload = dict(cobranca.payload or {})
        payload["card"] = card
        if remote_ip:
            payload["remote_ip"] = remote_ip
        original = cobranca.payload
        cobranca.payload = payload
        try:
            return self._criar_cartao(cobranca)
        finally:
            cobranca.payload = original

    def _criar_pix(self, cobranca) -> dict:
        merchant_charge_id = cobranca.referencia_provedor
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "customer": self._customer(cobranca),
                "transactions": [
                    {"amount": self._centavos(cobranca.valor), "paymentType": 8},  # 8 = Pix
                ],
                "metadata": self._metadata(cobranca),
                "source": 1,
            }
        }
        access = self._access_token()
        _status, data = self._http(
            "POST", "/v2/charge/pix",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        pix = charge.get("qrCode") or data.get("qrCode") or ""
        if not pix:
            for tx in charge.get("transactions") or []:
                pix = tx.get("qrCode") or tx.get("emv") or pix
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "pix_copia_cola": pix,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {"safrapay": _redigir_resposta(data), "merchantChargeId": merchant_charge_id},
        }

    def _criar_cartao(self, cobranca) -> dict:
        """Autoriza apenas o cartão informado e a sessão real do SDK antifraude."""
        merchant_charge_id = cobranca.referencia_provedor
        payload = cobranca.payload or {}
        card = dict(payload.get("card") or {})
        if not card:
            raise ValidationError("Informe os dados do cartão para autorizar o pagamento.")
        endereco = self._endereco_cartao(cobranca, card)
        from apps.nucleo.validadores import validar_documento
        card["cardholderDocument"] = validar_documento(card.get("cardholderDocument") or self._documento(cobranca))
        card.setdefault("billingAddress", endereco)
        card.setdefault("isPrivateLabel", False)
        customer = self._customer(cobranca, exigir_contato=True)  # força telefone
        customer["address"] = endereco
        sessao = str(payload.get("session_id") or "")
        if settings.SAFRAPAY_ENV == "prod" and not sessao:
            raise ValidationError("A sessão de segurança do pagamento não foi iniciada. Recarregue a página.")
        access = self._access_token()
        _, bin_info = self._http("GET", "/v2/Card/Bin?bin=" + quote(str(card.get("cardNumber", ""))[:8]),
            headers={"Authorization": f"Bearer {access}"})
        bandeira = bin_info.get("cardBrand")
        if not isinstance(bandeira, (str, int)) or str(bandeira).lower() in ("", "0", "undefined"):
            raise ValidationError("A operadora não identificou a bandeira deste cartão.")
        card["brand"] = bandeira
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "sessionId": sessao or str(uuid.uuid4()),
                "customer": customer,
                "transactions": [{
                    "card": card,
                    "paymentType": 2,
                    "amount": self._centavos(cobranca.valor),
                    "installmentNumber": max(1, int(cobranca.parcelas or 1)),
                    "installmentType": 0,
                    "autoCapture": True,
                }],
                "metadata": self._metadata(cobranca),
                "source": 1,
            }
        }
        if payload.get("remote_ip"):
            body["remoteIp"] = payload["remote_ip"]  # topo, irmão de charge (ver exemplo antifraude)
        _status, data = self._http(
            "POST", "/v2/charge/authorization",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        status_raw = _estado_cobranca(charge, cobranca.valor)
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "status_raw": status_raw,
            "expira_em": timezone.now() + timezone.timedelta(hours=24),
            "payload": {
                "safrapay": _redigir_resposta(data),
                "merchantChargeId": merchant_charge_id,
                "checkout_url": reverse("pagamentos:pagar", args=[cobranca.token]),
            },
        }

    def _criar_boleto(self, cobranca) -> dict:
        merchant_charge_id = cobranca.referencia_provedor
        # Boleto exige vencimento, telefone, e endereço do sacado.
        vencimento = (timezone.now() + timezone.timedelta(days=3)).date().isoformat()
        customer = self._customer(cobranca, exigir_contato=True)
        customer["address"] = self._endereco(cobranca)
        access = self._access_token()
        body = {
            "charge": {
                "merchantChargeId": merchant_charge_id,
                "customer": customer,
                "deadline": vencimento,
                "transactions": [{
                    "amount": self._centavos(cobranca.valor),
                    "paymentType": 4,  # 4 = Boleto
                }],
                "metadata": self._metadata(cobranca),
                "source": 1,
            }
        }
        _status, data = self._http(
            "POST", "/v2/charge/boleto",
            headers={"Authorization": f"Bearer {access}"},
            body=body,
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=merchant_charge_id)
        # Safrapay real: digitalLine (linha digitável), barcode, bankSlipUrl (PDF).
        linha = barcode = url_pdf = ""
        for tx in charge.get("transactions") or []:
            linha = linha or tx.get("digitalLine") or tx.get("digitableLine") or tx.get("linhaDigitavel") or ""
            barcode = barcode or tx.get("barcode") or ""
            url_pdf = url_pdf or tx.get("bankSlipUrl") or tx.get("boletoUrl") or ""
        linha = linha or charge.get("digitalLine") or charge.get("digitableLine") or ""
        return {
            "gateway": self.nome,
            "gateway_id": gid,
            "expira_em": timezone.now() + timezone.timedelta(days=3),
            "payload": {
                "safrapay": _redigir_resposta(data),
                "merchantChargeId": merchant_charge_id,
                "linha_digitavel": linha,
                "barcode": barcode,
                "boleto_url": url_pdf,
            },
        }

    def consultar_status(self, cobranca) -> dict:
        """Consulta o status real da cobrança (GET /v2/charge/{id}).

        Devolve o status bruto do Safrapay (chargeStatus ou transactionStatus da
        1ª transação) — usado p/ confirmar pagamento sem depender do webhook
        (útil em localhost, onde o webhook do gateway não chega)."""
        access = self._access_token()
        caminho = (f"/v2/charge/{quote(cobranca.gateway_id, safe='')}" if cobranca.gateway_id
            else f"/v2/charge?merchantChargeId={quote(cobranca.referencia_provedor)}")
        _status, data = self._http(
            "GET", caminho,
            headers={"Authorization": f"Bearer {access}"},
        )
        gid, charge = self._parse_charge(data, merchant_charge_id=cobranca.referencia_provedor)
        if cobranca.gateway_id and gid != cobranca.gateway_id:
            raise ResultadoIncerto("Safrapay: o identificador retornado pertence a outra cobrança.")
        if not cobranca.gateway_id and charge.get("merchantChargeId") != cobranca.referencia_provedor:
            raise ResultadoIncerto("Safrapay: referência não confirmada pelo provedor.")
        return {"status_raw": _estado_cobranca(charge, cobranca.valor), "gateway_id": gid,
            "charge": _redigir_resposta(charge), "raw": _redigir_resposta(data)}

    def estornar(self, cobranca) -> dict:
        anterior = self.consultar_status(cobranca)
        if anterior["status_raw"] == "Canceled":
            return {"estornado": True, "gateway_id": cobranca.gateway_id}
        access = self._access_token()
        if not cobranca.gateway_id:
            raise ValidationError("Cobrança sem id no gateway para estornar.")
        _status, data = self._http(
            "PUT", f"/v2/charge/cancelation/{cobranca.gateway_id}",
            headers={"Authorization": f"Bearer {access}"},
            body={},
        )
        confirmado = self.consultar_status(cobranca)
        if confirmado["status_raw"] != "Canceled":
            raise ResultadoIncerto("Estorno ainda não confirmado pela Safrapay. Consulte o provedor antes de repetir.")
        return {"estornado": True, "gateway_id": cobranca.gateway_id}


def status_credenciais() -> dict:
    """Checklist das chaves Safrapay para a tela do CRM."""
    gateway = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado")
    env = getattr(settings, "SAFRAPAY_ENV", "hml")
    sid = bool((getattr(settings, "SAFRAPAY_ID", "") or "").strip())
    codigo = bool((getattr(settings, "SAFRAPAY_CODIGO_ATIVACAO", "") or "").strip())
    token = bool((getattr(settings, "SAFRAPAY_TOKEN", "") or "").strip())
    avisos = []
    if gateway == "safrapay" and not token:
        avisos.append(
            "Gateway apontado para safrapay, mas SAFRAPAY_TOKEN está vazio. "
            "Aguarde liberação no portal Developers → Keys."
        )
    if not sid:
        avisos.append("SAFRAPAY_ID ainda não preenchido no .env.")
    if not codigo:
        avisos.append("SAFRAPAY_CODIGO_ATIVACAO ainda não preenchido no .env.")
    if not token:
        avisos.append(
            "Token vazio é o esperado agora: a SafraPay só envia o Token "
            "depois das evidências de teste (Pix, cartão, boleto)."
        )
        avisos.append(
            "ID e Código de Ativação NÃO autenticam a API (teste HML → 401). "
            "Use o sandbox do CRM (simulado) para gerar o pacote de evidências."
        )
    pronto = gateway == "safrapay" and token and sid
    return {
        "gateway": gateway,
        "env": env,
        "gateway_url": getattr(settings, "SAFRAPAY_GATEWAY_URL", ""),
        "id_ok": sid,
        "codigo_ativacao_ok": codigo,
        "token_ok": token,
        "pronto_para_api": pronto,
        "avisos": avisos,
        "processo_homologacao": [
            "Integração no CRM já cobre Pix, cartão e boleto (provider Safrapay + sandbox).",
            "Gere o pacote de evidências nesta tela (3 cobranças sandbox + JSON no formato HML).",
            "Anexe prints + JSON no formulário de integração da SafraPay.",
            "Faça os testes que eles pedirem (ex.: cartão do titular deles) quando liberarem acesso HML.",
            "Só então o Token aparece em Developers → Keys.",
            "Cole SAFRAPAY_TOKEN, PAGAMENTOS_GATEWAY=safrapay, webhook /crm/pagamentos/webhook/.",
        ],
        "proximos_passos": [
            "Manter PAGAMENTOS_GATEWAY=simulado até o Token existir.",
            "Clicar em «Gerar evidências (Pix + cartão + boleto)» e baixar o JSON.",
            "Enviar evidências no formulário Safrapay / e-mail de integração.",
            "Quando o Token chegar: colar no .env e ligar o gateway safrapay em HML.",
        ],
    }


_GATEWAYS = {
    "simulado": GatewaySimulado,
    "safrapay": GatewaySafrapay,
}


def get_gateway(cobranca=None):
    nome = getattr(settings, "PAGAMENTOS_GATEWAY", "simulado")
    cls = _GATEWAYS.get(nome)
    if cls is None:
        raise ValidationError(
            f"Gateway de pagamento desconhecido: {nome!r}. "
            f"Use um de: {', '.join(sorted(_GATEWAYS))}."
        )
    gw = cls()
    if cobranca and (cobranca.gateway != gw.nome or cobranca.gateway_ambiente != gw.ambiente):
        raise ValidationError("A cobrança pertence a outro provedor, estabelecimento ou ambiente. Concilie a origem antes de operar.")
    return gw


# Mapa de status do provedor (SafraPay/Aditum) — compartilhado por webhook, consulta e
# autorização de cartão. Conservador: só "pago" em estados inequívocos (Captured/Paid);
# negado/cancelado/desconhecido NÃO confirma (fail-safe). Sandbox sem status → None.
#   1=PreAuthorized · 2=Captured · 3=Denied · 4=Pending · 5=Canceled · 8=Paid
_STATUS_PAGO = {"paid", "pago", "captured", "consolidated", "2", "8"}
_STATUS_PENDENTE = {
    "pending", "pendente", "ordered", "created",
    "preauthorized", "pre_authorized", "authorized",
    "pendingpayment", "pending_payment", "1", "4",
}
_STATUS_NEGADO = {
    "denied", "notauthorized", "not_authorized", "refused", "declined",
    "canceled", "cancelled", "cancelado", "3", "5",
}


def status_pago(status_raw):
    """True = pago, False = pendente/negado, None = desconhecido (fail-safe: não confirma)."""
    if status_raw is None or status_raw == "":
        return None
    st = str(status_raw).lower()
    if st in _STATUS_PAGO:
        return True
    if st in _STATUS_PENDENTE or st in _STATUS_NEGADO:
        return False
    return None


def status_negado(status_raw):
    """True quando o provedor recusou/cancelou explicitamente (para mensagem ao cliente)."""
    return str(status_raw or "").lower() in _STATUS_NEGADO
