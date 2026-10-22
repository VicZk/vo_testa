"""Contratos reais: identidade, valores, respostas perdidas e disputa entre cliques."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from apps.nucleo.models import Pessoa

from . import services, tests
from .gateways import GatewaySafrapay, ResultadoIncerto, _estado_cobranca, get_gateway
from .models import Cobranca, EventoPagamento

SAFRA = dict(PAGAMENTOS_GATEWAY="safrapay", SAFRAPAY_ENV="hml", SAFRAPAY_TOKEN="credencial-de-teste",
    SAFRAPAY_ID="estabelecimento-de-teste", SAFRAPAY_GATEWAY_URL="https://payment-hml.safrapay.com.br")


def origem_real(cb):
    cb.gateway, cb.gateway_ambiente = "safrapay", GatewaySafrapay().ambiente
    cb.save(update_fields=["gateway", "gateway_ambiente"])
    return cb


def corpo_pago(cb, *, valor=None, estado="Captured"):
    return {"success": True, "charge": {"id": cb.gateway_id or "ID-RECUPERADO",
        "merchantChargeId": cb.referencia_provedor, "chargeStatus": "Authorized",
        "transactions": [{"transactionStatus": estado, "amount": valor if valor is not None else int(cb.valor*100), "isCanceled": False}]}}


class ContratosSafrapayTests(tests.PagamentosBase):
    def test_retorno_nao_persiste_campos_sensiveis_soltos_ou_com_outra_caixa(self):
        from .gateways import _redigir_resposta
        dados = {"CardNumber":"PAN-NAO-PERSISTIR", "transactions":[{"securityCode":"CVV-NAO-PERSISTIR", "amount":2000}], "cardHolder":{"name":"Pessoa"}}
        filtrado = _redigir_resposta(dados)
        self.assertNotIn("PAN-NAO-PERSISTIR", str(filtrado))
        self.assertNotIn("CVV-NAO-PERSISTIR", str(filtrado))
        self.assertEqual(filtrado["transactions"][0]["amount"], 2000)

    def test_pix_manual_devolucao_exige_comprovante_e_nao_chama_gateway(self):
        cb = self.cobranca()
        cb.gateway, cb.gateway_ambiente = "pix_direto", "manual"
        cb.save(update_fields=["gateway", "gateway_ambiente"])
        services.confirmar_pagamento(cb, self.op)
        with patch("apps.pagamentos.services.get_gateway") as gateway:
            with self.assertRaises(ValidationError):
                services.estornar(cb, self.op)
            cb.refresh_from_db()
            self.assertEqual(cb.status, "pago")
            services.estornar(cb, self.op, devolucao_confirmada=True, referencia_devolucao="DEVOLUCAO-QA-001")
            with self.assertRaises(ValidationError):
                services.estornar(cb, self.op, devolucao_confirmada=True, referencia_devolucao="DEVOLUCAO-QA-001")
        gateway.assert_not_called()
        self.assertEqual(EventoPagamento.objects.filter(cobranca=cb, tipo="estornada").count(), 1)
        evento = cb.eventos.get(tipo="estornada")
        self.assertEqual(evento.origem, "operador")
        self.assertEqual(evento.detalhe["referencia_devolucao"], "DEVOLUCAO-QA-001")

    def test_pix_manual_tela_e_acesso_ao_modulo(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        cb = self.cobranca()
        cb.gateway, cb.gateway_ambiente = "pix_direto", "manual"
        cb.save(update_fields=["gateway", "gateway_ambiente"])
        services.confirmar_pagamento(cb, self.op)
        self.client.force_login(self.op)
        self.assertContains(self.client.get(reverse("pagamentos:detalhe", args=[cb.pk])), "Registrar devolução do Pix")
        ModuloContratado.objects.update_or_create(codigo=Modulo.PAGAMENTOS, defaults={"ativo":False})
        resposta = self.client.post(reverse("pagamentos:estornar", args=[cb.pk]), {"devolucao_confirmada":"1", "referencia_devolucao":"DEV-QA-002"})
        self.assertEqual(resposta.status_code, 404)
        cb.refresh_from_db()
        self.assertEqual(cb.status, "pago")

    def pagador(self):
        return Pessoa.objects.create(nome="Pessoa QA", email="qa@example.invalid", documento="11144477735",
            telefone="49999990000", endereco="Rua de Teste", numero="10", bairro="Bairro QA",
            cidade="Itá", uf="SC", cep="89760000")

    @override_settings(**SAFRA)
    def test_link_criado_sem_autorizar_cartao(self):
        with patch("apps.pagamentos.gateways.urlrequest.urlopen") as rede:
            cb = services.criar_cobranca(self.op, valor="20", metodo="link", descricao="Reserva")
        rede.assert_not_called()
        self.assertEqual(cb.gateway, "safrapay")
        self.assertEqual(cb.gateway_id, "")
        self.assertTrue(cb.payload["aguardando_cartao"])
        self.assertEqual(cb.gateway_ambiente, GatewaySafrapay().ambiente)

    @override_settings(**SAFRA)
    def test_pix_sem_pagador_nao_inventa_documento_nem_chama_api(self):
        with patch("apps.pagamentos.gateways.urlrequest.urlopen") as rede, self.assertRaises(ValidationError):
            services.criar_cobranca(self.op, valor="20", metodo="pix", descricao="Reserva")
        rede.assert_not_called()
        self.assertEqual(Cobranca.objects.get().status, "cancelado")

    def test_cnpj_e_endereco_real(self):
        cb = self.cobranca(pagador=self.pagador())
        cb.pagador.documento = "11222333000181"
        gw = GatewaySafrapay()
        self.assertEqual(gw._customer(cb)["documentType"], 2)
        self.assertEqual(gw._endereco(cb)["number"], "10")
        cb.pagador.bairro = ""
        with self.assertRaisesMessage(ValidationError, "bairro"):
            gw._endereco(cb)

    @override_settings(**SAFRA)
    def test_documento_invalido_do_titular_bloqueia_antes_da_api(self):
        cb = Cobranca.objects.create(valor="20", metodo="cartao", descricao="QA", pagador=self.pagador(), criado_por=self.op)
        with patch("apps.pagamentos.gateways.urlrequest.urlopen") as rede, self.assertRaises(ValidationError):
            GatewaySafrapay().autorizar_cartao(cb, {"cardNumber":"4111111111111111", "cardholderDocument":"123"})
        rede.assert_not_called()

    def test_authorized_so_e_pago_com_captura_integral(self):
        cb = self.cobranca()
        charge = corpo_pago(cb)["charge"]
        self.assertEqual(_estado_cobranca(charge, cb.valor), "Captured")
        charge["transactions"][0]["amount"] = 1
        self.assertEqual(_estado_cobranca(charge, cb.valor), "Pending")
        charge["transactions"][0]["isCanceled"] = True
        self.assertEqual(_estado_cobranca(charge, cb.valor), "Pending")
        charge["transactions"] = []
        self.assertEqual(_estado_cobranca(charge, cb.valor), "")

    @override_settings(**SAFRA)
    def test_retorno_pix_perdido_recupera_referencia_sem_novo_post(self):
        with patch.object(GatewaySafrapay, "criar_cobranca", side_effect=ResultadoIncerto("Sem resposta")):
            with self.assertRaises(ValidationError):
                services.criar_cobranca(self.op, valor="20", metodo="pix", descricao="Reserva")
        cb = Cobranca.objects.get()
        self.assertEqual(cb.status, "pendente")
        self.assertTrue(cb.conciliacao_pendente)
        self.assertFalse(cb.eventos.filter(tipo="cancelada").exists())
        with patch.object(GatewaySafrapay, "_access_token", return_value="TOKEN"), patch.object(
            GatewaySafrapay, "_http", return_value=(200, corpo_pago(cb))) as http:
            info = services.consultar_cobranca(cb)
        self.assertEqual(info["status_raw"], "Captured")
        self.assertEqual(http.call_args.args[:2], ("GET", f"/v2/charge?merchantChargeId=VT-{cb.pk}"))
        cb.refresh_from_db()
        self.assertEqual(cb.gateway_id, "ID-RECUPERADO")
        services.confirmar_pagamento(cb, self.op)
        self.assertEqual(cb.eventos.filter(tipo="paga").count(), 1)

    def test_troca_de_ambiente_nao_opera_cobranca_antiga(self):
        cb = self.cobranca()
        with override_settings(**SAFRA):
            origem_real(cb)
            with override_settings(SAFRAPAY_ENV="prod", SAFRAPAY_GATEWAY_URL="https://payment.safrapay.com.br"):
                with self.assertRaisesMessage(ValidationError, "outro provedor"):
                    get_gateway(cb)
        with self.assertRaises(ValidationError):
            get_gateway(cb)

    @override_settings(**SAFRA)
    def test_configuracao_invalida_nao_usa_outro_endpoint(self):
        with override_settings(SAFRAPAY_ENV="producao"):
            with self.assertRaises(ValidationError):
                GatewaySafrapay()._exigir_token()
        with override_settings(SAFRAPAY_GATEWAY_URL="http://payment-hml.safrapay.com.br"):
            with self.assertRaises(ValidationError):
                GatewaySafrapay()._exigir_token()

    @override_settings(**SAFRA)
    def test_cache_isola_token_e_estabelecimento(self):
        gw = GatewaySafrapay()
        with patch.object(gw, "_http", side_effect=[(200, {"accessToken":"A"}), (200, {"accessToken":"B"})]) as http:
            self.assertEqual(gw._access_token(), "A")
            self.assertEqual(gw._access_token(), "A")
            with override_settings(SAFRAPAY_TOKEN="credencial-rotacionada"):
                self.assertEqual(gw._access_token(), "B")
        self.assertEqual(http.call_count, 2)

    def test_estorno_sem_confirmacao_nao_apaga_pagamento(self):
        cb = self.cobranca()
        services.confirmar_pagamento(cb, self.op)
        with override_settings(**SAFRA):
            origem_real(cb)
            with patch.object(GatewaySafrapay, "_access_token", return_value="T"), patch.object(
                GatewaySafrapay, "_http", return_value=(200, {"canceled": False})), patch.object(
                GatewaySafrapay, "consultar_status", return_value={"status_raw": "Captured"}):
                with self.assertRaisesMessage(ValidationError, "não confirmado"):
                    services.estornar(cb, self.op)
        cb.refresh_from_db()
        self.assertEqual(cb.status, "pago")
        self.assertFalse(cb.eventos.filter(tipo="estornada").exists())

    def test_estorno_ja_confirmado_nao_repete_put(self):
        cb = self.cobranca()
        services.confirmar_pagamento(cb, self.op)
        with override_settings(**SAFRA):
            origem_real(cb)
            with patch.object(GatewaySafrapay, "consultar_status", return_value={"status_raw":"Canceled"}), patch.object(GatewaySafrapay, "_http") as http:
                services.estornar(cb, self.op)
        http.assert_not_called()
        cb.refresh_from_db()
        self.assertEqual(cb.status, "estornado")

    @override_settings(**SAFRA)
    def test_http_nao_aceita_lista_nem_success_false(self):
        for body in ([], {"success":False, "errors":[{"message":"PII-NAO-EXIBIR"}]}):
            resp = MagicMock(status=200)
            resp.read.return_value = json.dumps(body).encode()
            resp.__enter__.return_value = resp
            with patch("apps.pagamentos.gateways.urlrequest.urlopen", return_value=resp), self.assertRaises(ValidationError) as erro:
                GatewaySafrapay()._http("POST", "/v2/charge/pix")
            self.assertNotIn("PII-NAO-EXIBIR", str(erro.exception))

    def test_simulacao_producao_nao_quita_conta(self):
        cb = self.cobranca()
        with override_settings(DEBUG=False, TESTING=False):
            self.client.post(reverse("pagamentos:pagar_simular", args=[cb.token]))
            pagina = self.client.get(reverse("pagamentos:pagar", args=[cb.token]))
        cb.refresh_from_db()
        self.assertEqual(cb.status, "pendente")
        self.assertContains(pagina, "não recebe pagamentos")

    def test_resposta_cartao_incerta_impede_reenvio(self):
        cb = self.cobranca(metodo="cartao")
        gw = MagicMock()
        gw.autorizar_cartao.side_effect = ResultadoIncerto("Resposta perdida")
        with patch("apps.pagamentos.services.get_gateway", return_value=gw):
            self.assertFalse(services.autorizar_cartao_online(cb, {"cardNumber":"4111111111111111"})[0])
            self.assertFalse(services.autorizar_cartao_online(cb, {"cardNumber":"4111111111111111"})[0])
        self.assertEqual(gw.autorizar_cartao.call_count, 1)
        cb.refresh_from_db()
        self.assertTrue(cb.conciliacao_pendente)
        self.assertNotIn("4111111111111111", str(cb.payload))
        with self.assertRaises(ValidationError):
            services.cancelar(cb, self.op)


@override_settings(PAGAMENTOS_GATEWAY="simulado")
class CartaoConcorrenteTests(TransactionTestCase):
    def test_dois_cliques_so_autorizam_uma_vez(self):
        op = get_user_model().objects.create_user(username="cartao-concorrente")
        cb = services.criar_cobranca(op, valor=Decimal("20"), metodo="cartao", descricao="QA")
        iniciou, liberar = threading.Event(), threading.Event()
        chamadas = []

        class Gateway:
            def autorizar_cartao(self, cobranca, card, remote_ip=""):
                chamadas.append(cobranca.referencia_provedor)
                iniciou.set()
                if not liberar.wait(10):
                    raise AssertionError("A segunda requisição não concluiu.")
                return {"gateway_id":"SIM-UNICO", "status_raw":"Captured", "payload":{}}

        def executar():
            close_old_connections()
            try:
                return services.autorizar_cartao_online(Cobranca.objects.get(pk=cb.pk), {})
            finally:
                connections.close_all()

        with patch("apps.pagamentos.services.get_gateway", return_value=Gateway()), ThreadPoolExecutor(2) as pool:
            primeiro = pool.submit(executar)
            self.assertTrue(iniciou.wait(10))
            segundo = pool.submit(executar)
            try:
                self.assertFalse(segundo.result(timeout=10)[0])
            finally:
                liberar.set()
            self.assertTrue(primeiro.result(timeout=10)[0])
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(EventoPagamento.objects.filter(cobranca=cb, tipo="paga").count(), 1)
