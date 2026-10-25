import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Pessoa, TrilhaAuditoria
from apps.nucleo.modulos import Modulo

from . import services
from .erros import CancelamentoPendente
from .gateways import get_gateway
from .models import DocumentoFiscal, EventoFiscal
from .spedy import GatewaySpedy, assinatura_valida, normalizar

SEGREDO = "whsec_" + base64.b64encode(b"segredo-de-teste-nao-real-qa-0001").decode()
SPEDY = dict(FISCAL_GATEWAY="spedy", SPEDY_API_KEY="qa-chave-nao-real", SPEDY_SANDBOX=True,
    SPEDY_WEBHOOK_SECRET=SEGREDO, FISCAL_NFSE_CODIGO_SERVICO="090101", FISCAL_NFSE_LC116="9.01",
    FISCAL_NFSE_ISS_ALIQUOTA="4.0")
SID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
BASE = "https://sandbox-api.spedy.com.br"


def assinatura(corpo, segredo=SEGREDO, ident="msg_qa_1", carimbo=None):
    carimbo = str(int(time.time()) if carimbo is None else carimbo)
    chave = base64.b64decode(segredo.removeprefix("whsec_"))
    valor = base64.b64encode(hmac.new(chave, f"{ident}.{carimbo}.".encode() + corpo, hashlib.sha256).digest()).decode()
    return {"webhook-id": ident, "webhook-timestamp": carimbo, "webhook-signature": f"v1,{valor}"}


def nota(integration_id, status, **extras):
    return {"id": SID, "integrationId": integration_id, "status": status, **extras}


class SpedyAssinaturaTests(SimpleTestCase):
    def test_confere_id_carimbo_e_corpo_cru_com_o_segredo_da_conta(self):
        corpo = b'{"id":"msg_qa_1","event":"invoice.status_changed"}'
        cabecalhos = assinatura(corpo)
        self.assertTrue(assinatura_valida(corpo, cabecalhos, SEGREDO))
        self.assertFalse(assinatura_valida(corpo + b" ", cabecalhos, SEGREDO))
        self.assertFalse(assinatura_valida(corpo, {**cabecalhos, "webhook-id": "msg_qa_2"}, SEGREDO))
        outro = "whsec_" + base64.b64encode(b"outro-segredo-qa").decode()
        self.assertFalse(assinatura_valida(corpo, cabecalhos, outro))
        self.assertFalse(assinatura_valida(corpo, cabecalhos, ""))
        self.assertFalse(assinatura_valida(corpo, {}, SEGREDO))

    def test_carimbo_vencido_e_troca_de_segredo(self):
        corpo = b"{}"
        antigo = assinatura(corpo, carimbo=int(time.time()) - 301)
        self.assertFalse(assinatura_valida(corpo, antigo, SEGREDO))
        # Na troca, chegam as duas assinaturas; basta uma conferir.
        atual = assinatura(corpo)
        duas = {**atual, "webhook-signature": "v1,assinatura-do-segredo-anterior " + atual["webhook-signature"]}
        self.assertTrue(assinatura_valida(corpo, duas, SEGREDO))
        self.assertFalse(assinatura_valida(corpo, {**atual, "webhook-signature": atual["webhook-signature"].replace("v1,", "v2,")}, SEGREDO))


@override_settings(**SPEDY)
class SpedyTransporteTests(SimpleTestCase):
    def test_chave_no_cabecalho_base_do_sandbox_e_tempo_limite(self):
        resposta = MagicMock()
        resposta.__enter__.return_value.read.return_value = b'{"id":"x","status":"enqueued"}'
        with patch("apps.fiscal.spedy.request.urlopen", return_value=resposta) as abrir:
            dados = GatewaySpedy()._req("POST", "/v1/service-invoices", {"description": "Hospedagem"})
        req = abrir.call_args.args[0]
        self.assertEqual(req.full_url, BASE + "/v1/service-invoices")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("X-api-key"), "qa-chave-nao-real")
        self.assertEqual(json.loads(req.data), {"description": "Hospedagem"})
        self.assertEqual(dados["status"], "enqueued")
        self.assertEqual(abrir.call_args.kwargs["timeout"], 20)

    def test_sem_chave_nao_ha_gateway_e_producao_troca_a_base(self):
        with override_settings(SPEDY_API_KEY=""), self.assertRaises(ValidationError):
            get_gateway("spedy")
        with override_settings(SPEDY_SANDBOX=False):
            producao = GatewaySpedy()
        self.assertEqual(producao.base, "https://api.spedy.com.br")
        self.assertNotEqual(producao.ambiente, GatewaySpedy().ambiente)

    def test_situacoes_do_ciclo_de_vida(self):
        for estado, esperado in (("created", "processando"), ("enqueued", "processando"), ("received", "processando"),
                                 ("inContingent", "processando"), ("authorized", "autorizada"), ("rejected", "rejeitada"),
                                 ("denied", "rejeitada"), ("removed", "rejeitada"), ("canceled", "cancelada")):
            extras = {"number": 33005} if estado in ("authorized", "canceled") else {}
            self.assertEqual(normalizar(nota("vt-qa", estado, **extras), BASE)["status"], esperado, estado)
        autorizada = normalizar(nota("vt-qa", "authorized", number=33005, rps={"number": 7, "series": "1"},
                                     authorization={"protocol": "PRT-1"}, processingDetail={"code": None}), BASE)
        self.assertEqual((autorizada["numero"], autorizada["serie"], autorizada["protocolo"]), ("33005", "1", "PRT-1"))
        self.assertEqual(autorizada["pdf_url"], f"{BASE}/v1/service-invoices/{SID}/pdf")
        self.assertEqual(autorizada["xml_url"], f"{BASE}/v1/service-invoices/{SID}/xml")
        self.assertEqual(autorizada["payload"], {"spedy_id": SID})
        self.assertEqual(normalizar(nota("vt-qa", "enqueued"), BASE)["pdf_url"], "")
        with self.assertRaises(ValidationError):
            normalizar(nota("vt-qa", "authorized"), BASE)
        with self.assertRaises(ValidationError):
            normalizar([], BASE)


@override_settings(**SPEDY)
class SpedyCicloTests(TestCase):
    def setUp(self):
        self.op = get_user_model().objects.create_superuser(username="fiscal-spedy-qa", password="qa")
        self.tomador = Pessoa.objects.create(nome="Pessoa fictícia", documento="111.444.777-35", email="qa@example.com")
        self.gw = GatewaySpedy()

    def emitir(self, resposta, **extras):
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), \
                patch.object(self.gw, "_req", side_effect=resposta if isinstance(resposta, list) else [resposta]) as req:
            doc = services.emitir(self.op, natureza="servico", valor=Decimal("910.00"), descricao="Hospedagem fictícia",
                                  tomador=self.tomador, referencia="qa-estadia", payload={"codigo_servico": "090101"}, **extras)
        return doc, req

    def retorno(self, corpo, **cabecalhos):
        bruto = json.dumps(corpo).encode()
        assinado = {f"HTTP_{k.upper().replace('-', '_')}": v for k, v in assinatura(bruto).items()}
        return self.client.post(reverse("fiscal:webhook"), bruto, content_type="application/json", **{**assinado, **cabecalhos})

    def test_emissao_assincrona_fica_processando_com_o_id_do_spedy(self):
        doc, req = self.emitir({"id": SID, "status": "enqueued"})
        self.assertEqual(doc.status, "processando")
        self.assertEqual(doc.payload["spedy_id"], SID)
        self.assertEqual(req.call_count, 1)  # sem id do Spedy ainda, não há o que consultar
        metodo, caminho, corpo = req.call_args.args
        self.assertEqual((metodo, caminho), ("POST", "/v1/service-invoices"))
        self.assertEqual(corpo["integrationId"], doc.gateway_id)
        self.assertLessEqual(len(corpo["integrationId"]), 36)
        self.assertEqual((corpo["federalServiceCode"], corpo["nationalTaxationCode"]), ("9.01", "090101"))
        self.assertEqual(corpo["total"], {"invoiceAmount": 910.0, "issRate": 4.0})
        self.assertEqual(corpo["receiver"], {"name": "Pessoa fictícia", "federalTaxNumber": "11144477735", "email": "qa@example.com"})
        self.assertEqual(doc.payload_envio, corpo)

    def test_resposta_perdida_reenvia_com_o_mesmo_integration_id(self):
        with self.assertRaises(ValidationError):
            self.emitir(ValidationError("Tempo esgotado"))
        doc = DocumentoFiscal.objects.get()
        self.assertEqual(doc.status, "processando")
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), \
                patch.object(self.gw, "_req", return_value=nota(doc.gateway_id, "authorized", number=33005)) as req:
            atualizado = services.reenviar(doc)
        self.assertEqual(atualizado.status, "autorizada")
        self.assertEqual(atualizado.numero, "33005")
        self.assertEqual(DocumentoFiscal.objects.count(), 1)
        self.assertEqual(req.call_args.args[2]["integrationId"], doc.gateway_id)

    def test_retorno_assinado_autoriza_e_entrega_atrasada_nao_desfaz(self):
        doc, _ = self.emitir({"id": SID, "status": "enqueued"})
        autorizada = {"id": "msg_qa_1", "event": "invoice.status_changed",
                      "data": nota(doc.gateway_id, "authorized", number=33005, authorization={"protocol": "PRT-1"})}
        bruto = json.dumps(autorizada).encode()
        url = reverse("fiscal:webhook")
        self.assertEqual(self.client.post(url, bruto, content_type="application/json").status_code, 401)
        self.assertEqual(self.retorno(autorizada, HTTP_WEBHOOK_SIGNATURE="v1,falsa").status_code, 401)
        for _ in range(2):
            self.assertEqual(self.retorno(autorizada).status_code, 200)
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.numero, doc.protocolo), ("autorizada", "33005", "PRT-1"))
        self.assertTrue(doc.pdf_url.endswith(f"/v1/service-invoices/{SID}/pdf"))
        self.assertEqual(doc.eventos.filter(tipo="autorizada").count(), 1)
        self.assertEqual(self.retorno({**autorizada, "data": nota(doc.gateway_id, "enqueued")}).status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "autorizada")
        # O webhook vale para a conta toda: nota de outro sistema é recebida e ignorada.
        self.assertEqual(self.retorno({**autorizada, "data": nota("vt-outro-sistema", "authorized", number=1)}).json(),
                         {"ok": True, "ignorado": True})
        self.assertEqual(self.retorno({"id": "msg_qa_1", "data": []}).status_code, 400)
        with override_settings(SPEDY_WEBHOOK_SECRET=""):
            self.assertEqual(self.retorno(autorizada).status_code, 503)

    def test_cancelamento_assincrono_registra_quem_pediu_e_fecha_pelo_retorno(self):
        doc, _ = self.emitir({"id": SID, "status": "enqueued"})
        services.processar_retorno_spedy({"data": nota(doc.gateway_id, "authorized", number=33005)})
        doc.refresh_from_db()
        motivo = "Hóspede pediu nota em outro CPF"
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), \
                patch.object(self.gw, "_req", side_effect=[nota(doc.gateway_id, "authorized", number=33005),
                                                          nota(doc.gateway_id, "authorized", number=33005)]) as req:
            with self.assertRaises(CancelamentoPendente):
                services.cancelar(doc, self.op, motivo)
        self.assertEqual(req.call_args.args, ("DELETE", f"/v1/service-invoices/{SID}", {"reason": motivo}))
        doc.refresh_from_db()
        self.assertEqual(doc.status, "autorizada")
        trilha = TrilhaAuditoria.objects.get(acao="cancelamento_fiscal")
        self.assertEqual((trilha.usuario, trilha.detalhe["motivo"]), (self.op, motivo))
        self.assertEqual(self.retorno({"id": "msg_qa_2", "data": nota(doc.gateway_id, "canceled", number=33005)}).status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "cancelada")
        # Repetir o pedido depois do fecho não duplica a trilha.
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw):
            services.cancelar(doc, self.op, motivo)
        self.assertEqual(TrilhaAuditoria.objects.filter(acao="cancelamento_fiscal").count(), 1)
        self.assertEqual(EventoFiscal.objects.filter(documento=doc, tipo="cancelamento_log").count(), 1)

    def test_tela_de_cancelar_avisa_que_a_confirmacao_vem_depois(self):
        doc, _ = self.emitir({"id": SID, "status": "enqueued"})
        services.processar_retorno_spedy({"data": nota(doc.gateway_id, "authorized", number=33005)})
        ModuloContratado.objects.update_or_create(codigo=Modulo.FISCAL, defaults={"ativo": True})
        self.client.force_login(self.op)
        with patch.object(GatewaySpedy, "_req", side_effect=[nota(doc.gateway_id, "authorized", number=33005)] * 2):
            resposta = self.client.post(reverse("fiscal:cancelar", args=[doc.pk]),
                                        {"motivo": "Hóspede pediu nota em outro CPF"}, follow=True)
        avisos = [str(m) for m in resposta.context["messages"]]
        self.assertTrue(any("recebeu o pedido de cancelamento" in a for a in avisos), avisos)

    def test_rejeicao_de_cadastro_se_corrige_com_a_mesma_referencia_e_negada_nao(self):
        doc, _ = self.emitir({"id": SID, "status": "enqueued"})
        services.processar_retorno_spedy({"data": nota(doc.gateway_id, "rejected")})
        doc.refresh_from_db()
        self.assertEqual(doc.status, "rejeitada")
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), \
                patch.object(self.gw, "_req", side_effect=[nota(doc.gateway_id, "rejected"), nota(doc.gateway_id, "enqueued")]) as req:
            corrigido = services.corrigir(doc)
        self.assertEqual(corrigido.status, "processando")
        self.assertEqual(req.call_args.args[0:2], ("POST", "/v1/service-invoices"))
        self.assertEqual(req.call_args.args[2]["integrationId"], doc.gateway_id)
        services.processar_retorno_spedy({"data": nota(doc.gateway_id, "denied")})
        corrigido.refresh_from_db()
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), \
                patch.object(self.gw, "_req", return_value=nota(doc.gateway_id, "denied")), self.assertRaises(ValidationError):
            services.corrigir(corrigido)

    def test_nfce_e_tomador_sem_documento_param_antes_da_rede(self):
        sem_documento = Pessoa.objects.create(nome="Sem documento")
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), patch.object(self.gw, "_req") as req:
            with self.assertRaises(ValidationError):
                services.emitir(self.op, natureza="servico", valor=Decimal("50"), descricao="Hospedagem", tomador=sem_documento)
            with self.assertRaises(ValidationError):
                services.emitir(self.op, natureza="consumo", valor=Decimal("50"), descricao="Venda", tomador=self.tomador)
        req.assert_not_called()
        self.assertFalse(DocumentoFiscal.objects.exists())

    def test_painel_mostra_o_que_falta_configurar(self):
        self.assertEqual(services.configuracao()["pendencias"], [])
        self.assertIn("Spedy: ambiente de testes (sandbox)", services.configuracao()["mensagem"])
        with override_settings(SPEDY_WEBHOOK_SECRET="", SPEDY_API_KEY=""):
            pendencias = services.configuracao()["pendencias"]
        self.assertTrue(any("chave da API do Spedy" in p for p in pendencias), pendencias)
        self.assertTrue(any("segredo do webhook do Spedy" in p for p in pendencias), pendencias)
