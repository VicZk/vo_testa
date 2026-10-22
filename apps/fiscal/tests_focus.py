import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.nucleo.models import Pessoa

from . import services
from . import tests as testes_fiscais
from .focus import GatewayFocus
from .gateways import GatewaySimulado, get_gateway
from .models import DocumentoFiscal, EventoFiscal

FOCUS = dict(FISCAL_GATEWAY="focus", FISCAL_FOCUS_TOKEN="qa-token-nao-real",
    FISCAL_FOCUS_URL="https://homologacao.focusnfe.com.br", FISCAL_EMITENTE_CNPJ="26003246000100",
    FISCAL_MUNICIPIO_IBGE="4208004", FISCAL_DPS_SERIE="40001", FISCAL_DPS_NUMERO_INICIAL="1000",
    FISCAL_NFSE_COMPLEMENTOS="{}", FISCAL_WEBHOOK_TOKEN="qa-hook", FISCAL_REGIME="lucro_presumido")


@override_settings(**FOCUS)
class FocusTransporteTests(SimpleTestCase):
    def test_http_basic_token_payload_e_consulta_ausente(self):
        resposta = MagicMock()
        resposta.__enter__.return_value.read.return_value = b'{"status":"processando_autorizacao"}'
        gw = GatewayFocus()
        with patch("apps.fiscal.focus.request.urlopen", return_value=resposta) as abrir:
            dados = gw._req("POST", "/v2/nfsen?ref=qa-1", {"descricao_servico":"Hospedagem"})
        req = abrir.call_args.args[0]
        self.assertEqual(req.full_url, "https://homologacao.focusnfe.com.br/v2/nfsen?ref=qa-1")
        self.assertEqual(req.get_method(), "POST")
        self.assertTrue(req.get_header("Authorization").startswith("Basic "))
        self.assertEqual(json.loads(req.data), {"descricao_servico":"Hospedagem"})
        self.assertEqual(dados["status"], "processando_autorizacao")
        self.assertEqual(abrir.call_args.kwargs["timeout"], 20)

    def test_resposta_invalida_e_provedor_desconhecido_nao_simulam_autorizacao(self):
        for corpo in (b'[]', b'null', b'not-json'):
            resposta = MagicMock()
            resposta.__enter__.return_value.read.return_value = corpo
            with patch("apps.fiscal.focus.request.urlopen", return_value=resposta), self.assertRaises(ValidationError):
                GatewayFocus()._req("GET", "/v2/nfsen/qa")
        for nome in ("focuss", "governo", "indisponivel"):
            with self.assertRaises(ValidationError):
                get_gateway(nome)


@override_settings(**FOCUS)
class FocusCicloTests(TestCase):
    def setUp(self):
        self.op = get_user_model().objects.create_superuser(username="fiscal-qa", password="qa")
        self.tomador = Pessoa.objects.create(nome="Pessoa fictícia", documento="11144477735")
        self.gw = GatewayFocus()

    def emitir(self, **extras):
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw):
            return services.emitir(self.op, natureza="servico", valor=Decimal("200"),
                descricao="Hospedagem fictícia", tomador=self.tomador, referencia="qa-estadia", **extras)

    def pendente(self):
        with patch.object(self.gw, "_req", side_effect=[None, {"status":"processando_autorizacao"}]) as req:
            doc = self.emitir(payload={"codigo_servico":"090101"})
        return doc, req

    def test_nfse_pendente_possui_referencia_e_parametros_antes_do_post(self):
        doc, req = self.pendente()
        self.assertEqual(doc.status, "processando")
        self.assertEqual(doc.gateway, "focus")
        self.assertTrue(doc.gateway_id.startswith("vt-"))
        self.assertIn(doc.gateway_id, req.call_args.args[1])
        payload = req.call_args.args[2]
        self.assertEqual(payload["codigo_tributacao_nacional_iss"], "090101")
        self.assertEqual(payload["valor_servico"], "200")
        self.assertEqual(payload["cpf_tomador"], "11144477735")
        self.assertEqual(payload["serie_dps"], 40001)
        self.assertEqual(doc.payload_envio, payload)
        self.assertIsNone(doc.envio_token)
        self.assertFalse(doc.eventos.filter(tipo="rejeitada").exists())

    def test_resposta_perdida_persiste_documento_e_reenvio_concilia_sem_novo_post(self):
        with patch.object(self.gw, "_req", side_effect=[None, ValidationError("Tempo esgotado")]):
            with self.assertRaises(ValidationError):
                self.emitir()
        doc = DocumentoFiscal.objects.get()
        referencia = doc.gateway_id
        self.assertEqual(doc.status, "processando")
        self.assertIsNone(doc.envio_token)
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), patch.object(self.gw, "_req", return_value={"status":"autorizado", "numero":"20"}) as req:
            atualizado = services.reenviar(doc)
        self.assertEqual(atualizado.status, "autorizada")
        self.assertEqual(atualizado.gateway_id, referencia)
        self.assertEqual(DocumentoFiscal.objects.count(), 1)
        self.assertEqual(req.call_count, 1)
        self.assertEqual(req.call_args.args[0], "GET")

    def test_webhook_autenticado_idempotente_e_fora_de_ordem(self):
        doc, _ = self.pendente()
        url = reverse("fiscal:webhook")
        payload = {"ref":doc.gateway_id,"status":"autorizado","numero":"20"}
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 401)
        for _ in range(2):
            self.assertEqual(self.client.post(url,payload,content_type="application/json",HTTP_AUTHORIZATION="qa-hook").status_code,200)
        doc.refresh_from_db()
        data = doc.autorizada_em
        self.assertEqual(doc.eventos.filter(tipo="autorizada").count(), 1)
        services.processar_retorno_focus({"ref":doc.gateway_id, "status":"erro_autorizacao"})
        services.processar_retorno_focus(payload)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "autorizada")
        self.assertEqual(doc.autorizada_em, data)
        services.processar_retorno_focus({"ref":doc.gateway_id,"status":"cancelado"})
        services.processar_retorno_focus(payload)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "cancelada")
        self.assertEqual(doc.eventos.filter(tipo="cancelada").count(), 1)

    def test_webhook_rejeita_json_nao_objeto_e_segredo_ausente_mesmo_simulado(self):
        url = reverse("fiscal:webhook")
        for corpo in ("[]","null","true","1","{",'"x"',"x"*66000):
            self.assertEqual(self.client.post(url, corpo, content_type="application/json", HTTP_AUTHORIZATION="qa-hook").status_code,400)
        with override_settings(FISCAL_GATEWAY="simulado", FISCAL_WEBHOOK_TOKEN=""):
            self.assertEqual(self.client.post(url, {}, content_type="application/json").status_code,503)

    def test_cancelamento_nao_confirmado_preserva_autorizada_e_reenvio_obsoleto_e_idempotente(self):
        doc, _ = self.pendente()
        services.processar_retorno_focus({"ref":doc.gateway_id,"status":"autorizado","numero":"20"})
        doc.refresh_from_db()
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), patch.object(self.gw,"_req",side_effect=[
            {"status":"autorizado","numero":"20"},{"status":"erro_cancelamento"},{"status":"autorizado","numero":"20"}]):
            with self.assertRaises(ValidationError):
                services.cancelar(doc,self.op,"Correção do tomador da nota")
        doc.refresh_from_db()
        self.assertEqual(doc.status,"autorizada")
        with patch("apps.fiscal.services.get_gateway", return_value=self.gw), patch.object(self.gw,"_req",side_effect=[
            {"status":"autorizado","numero":"20"},{"status":"cancelado"},{"status":"cancelado"}]) as req:
            services.cancelar(doc,self.op,"Correção do tomador da nota")
            services.cancelar(doc,self.op,"Repetição de clique na tela")
            self.assertEqual(req.call_count,3)
        self.assertEqual(DocumentoFiscal.objects.get().status,"cancelada")
        self.assertEqual(EventoFiscal.objects.filter(tipo="cancelamento_log").count(),1)

    def test_troca_de_ambiente_nao_envia_documento_para_outra_base(self):
        doc, _ = self.pendente()
        with override_settings(FISCAL_FOCUS_URL="https://api.focusnfe.com.br"), patch("apps.fiscal.focus.request.urlopen") as rede:
            with self.assertRaisesMessage(ValidationError,"outro ambiente"):
                services.consultar(doc)
            rede.assert_not_called()
        doc.refresh_from_db()
        self.assertIsNone(doc.envio_token)

    def test_troca_de_emitente_bloqueia_consulta_e_retorno(self):
        doc, _ = self.pendente()
        with override_settings(FISCAL_EMITENTE_CNPJ="11222333000181"), patch("apps.fiscal.focus.request.urlopen") as rede:
            with self.assertRaisesMessage(ValidationError, "outro ambiente"):
                services.consultar(doc)
            with self.assertRaisesMessage(ValidationError, "outro ambiente"):
                services.processar_retorno_focus({"ref":doc.gateway_id,"status":"autorizado","numero":"20"})
        rede.assert_not_called()

    def test_cadastro_incompleto_e_valores_invalidos_nao_criam_documento(self):
        self.tomador.documento=""
        self.tomador.save()
        with self.assertRaises(ValidationError), patch("apps.fiscal.focus.request.urlopen") as rede:
            self.emitir()
        rede.assert_not_called()
        self.assertFalse(DocumentoFiscal.objects.exists())
        for valor in ("NaN","Infinity","1e200","-1"):
            with self.assertRaises(ValidationError):
                services.emitir(self.op,natureza="servico",valor=valor,descricao="Teste")
        self.assertFalse(DocumentoFiscal.objects.exists())


@override_settings(FISCAL_GATEWAY="simulado")
class EmissaoConcorrenteTests(TransactionTestCase):
    def setUp(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(codigo=Modulo.RESERVAS, defaults={"ativo":True})
        testes_fiscais.NfseDaDiariaTests.setUp(self)

    def test_duas_emissoes_da_mesma_conta_criam_um_documento(self):
        barreira=Barrier(2)
        def executar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return services.emitir_nfse_da_conta(self.conta.pk,self.op).pk
            finally:
                connections.close_all()
        original=GatewaySimulado.emitir
        with patch.object(GatewaySimulado,"emitir",autospec=True,side_effect=original) as emitir:
            with ThreadPoolExecutor(max_workers=2) as executor:
                ids=list(executor.map(lambda _:executar(),range(2)))
            self.assertEqual(emitir.call_count,1)
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(DocumentoFiscal.objects.count(),1)
