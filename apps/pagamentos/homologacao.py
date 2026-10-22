"""Exemplos ilustrativos de integração, sem escrita nem chamadas externas.

Este arquivo não comprova execução, aprovação ou homologação pelo provedor.
"""
from __future__ import annotations

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from .gateways import status_credenciais


def _centavos(valor) -> int:
    return int((Decimal(str(valor)) * 100).quantize(Decimal("1")))


def _customer_demo():
    return {
        "name": "Cliente Homologacao Vo Testa",
        "email": "exemplo@example.invalid",
        "documentType": 1,
        "document": "<Documento de teste fornecido pelo provedor>",
        "phone": {
            "countryCode": "55",
            "areaCode": "49",
            "number": "000000000",  # dado fictício
            "type": 5,
        },
    }


def payloads_api_hml(*, valor_pix="10.00", valor_cartao="10.00", valor_boleto="10.00"):
    """Exemplos de estrutura: completar com os dados orientados pelo provedor."""
    base = "https://payment-hml.safrapay.com.br"
    customer = _customer_demo()
    endereco_demo = {
        "street": "Rota do Sol", "number": "S/N", "neighborhood": "Centro",
        "city": "Itá", "state": "SC", "zipCode": "89760000",
        "complement": "", "country": "BR",
    }
    return {
        "ambiente": "hml",
        "gateway_base": base,
        "auth": {
            "metodo": "POST",
            "path": "/v2/merchant/auth",
            "header": "Authorization: <SAFRAPAY_TOKEN / Merchant Token mk_…>",
            "nota": "Use a credencial de homologação fornecida pelo provedor.",
        },
        "testes": [
            {
                "meio": "pix",
                "metodo": "POST",
                "path": "/v2/charge/pix",
                "body": {
                    "charge": {
                        "merchantChargeId": "VT-HML-PIX-DEMO",
                        "customer": customer,
                        "transactions": [{"amount": _centavos(valor_pix), "paymentType": 8}],  # 8 = Pix
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
            },
            {
                "meio": "cartao_credito_avista",
                "metodo": "POST",
                "path": "/v2/charge/authorization",
                "body": {
                    "remoteIp": "<IP do hóspede na página de pagamento>",
                    "charge": {
                        "merchantChargeId": "VT-HML-CARD-DEMO",
                        "sessionId": "<UUID do antifraude>",
                        "customer": {**customer, "address": endereco_demo},
                        "transactions": [{
                            "card": {
                                "cardholderName": "CLIENTE HOMOLOGACAO",
                                "cardNumber": "<Cartão de teste fornecido pelo provedor>",
                                "expirationMonth": 12,
                                "expirationYear": 2034,
                                "securityCode": "<Código de teste>",
                                "cardholderDocument": "<Documento de teste fornecido pelo provedor>",  # CPF do titular
                                "brand": 2,  # 2 = Mastercard
                                "billingAddress": endereco_demo,
                                "isPrivateLabel": False,
                            },
                            "paymentType": 2,
                            "amount": _centavos(valor_cartao),
                            "installmentNumber": 1,
                            "installmentType": 0,
                            "autoCapture": True,
                        }],
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
                "nota": "Substitua os exemplos pelos dados de teste e pelas orientações atuais do provedor.",
            },
            {
                "meio": "boleto",
                "metodo": "POST",
                "path": "/v2/charge/boleto",
                "body": {
                    "charge": {
                        "merchantChargeId": "VT-HML-BOL-DEMO",
                        # Boleto exige telefone + endereço (com country) do sacado.
                        "customer": {**customer, "address": endereco_demo},
                        "deadline": "<YYYY-MM-DD vencimento, ex.: now+3 dias>",
                        "transactions": [{
                            "amount": _centavos(valor_boleto),
                            "paymentType": 4,  # 4 = Boleto
                        }],
                        "metadata": [
                            {"key": "finalidade", "value": "sinal_reserva"},
                            {"key": "origem", "value": "evidencia_homologacao"},
                        ],
                        "source": 1,
                    }
                },
            },
        ],
        "webhook_esperado": {
            "url_crm": reverse("pagamentos:webhook"),
            "confirma_quando": "status paid/pago/captured → confirma pré-reserva (sinal)",
        },
        "credenciais_atuais": status_credenciais(),
        "gerado_em": timezone.now().isoformat(),
    }


def gerar_evidencias(operador, *, valor=Decimal("10.00")):
    """Compatibilidade da rota antiga: exporta somente exemplos, sem cobranças."""
    pacote = payloads_api_hml(valor_pix=str(valor), valor_cartao=str(valor), valor_boleto=str(valor))
    pacote["natureza"] = "Exemplos ilustrativos; nenhuma transação executada."
    pacote["comprova_homologacao"] = False
    pacote["instrucoes"] = [
        "Confirme as orientações atuais e os dados de teste com o provedor.",
        "Realize os ensaios no ambiente de homologação e confira o resultado no provedor.",
        "Registre os ensaios realizados em Configurações → Integrações.",
    ]
    return pacote
