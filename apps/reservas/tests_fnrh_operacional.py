from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from . import fnrh_gateway, services
from .models import Reserva
from .tests import HOJE, ReservasTestsBase


class PayloadFNRHTests(SimpleTestCase):
    @override_settings(FNRH_API_URL="https://api.example.test", FNRH_API_USER="qa", FNRH_API_SENHA="qa", FNRH_CPF_SOLICITANTE="00000000000")
    def test_transporte_envia_horario_real_como_texto_e_identifica_solicitante(self):
        gw = fnrh_gateway.GatewaySerpro()
        resposta = mock.MagicMock()
        resposta.__enter__.return_value.read.return_value = b'{}'
        with mock.patch.object(fnrh_gateway.urlrequest, "urlopen", return_value=resposta) as abrir:
            gw._req("POST", "/reservas/qa/checkout", "2026-10-22T09:10:00-03:00", texto=True)
            pedido = abrir.call_args.args[0]
            self.assertEqual(pedido.data, b"2026-10-22T09:10:00-03:00")
            self.assertEqual(pedido.get_header("Content-type"), "text/plain; charset=utf-8")
            self.assertTrue(pedido.get_header("Authorization").startswith("Basic "))
            gw._req("GET", "/pessoas/documento/CPF/00000000000")
            self.assertEqual(abrir.call_args.args[0].get_header("Cpf_solicitante"), "00000000000")
        resposta.__enter__.return_value.read.return_value = b'[]'
        with mock.patch.object(fnrh_gateway.urlrequest, "urlopen", return_value=resposta), self.assertRaises(ValidationError):
            gw._req("GET", "/reservas")

    def ficha(self, **campos):
        return SimpleNamespace(**{**dict(nome="Pessoa fictícia", nacionalidade="Argentina", pais="Brasil",
            nascimento=None, documento_tipo="PASSAPORTE", documento_numero="QA", cpf="", sexo=""), **campos})

    def test_nacionalidade_e_residencia_separadas(self):
        pessoa = fnrh_gateway.payload_pessoa(self.ficha())
        self.assertEqual(pessoa["PaisNacionalidade_id"], "AR")
        self.assertEqual(pessoa["contato"]["PaisResidencia_id"], "BR")
        self.assertEqual(pessoa["documento_id"]["tipo_documento_id"], "PASSAPORTE")

    def test_codigo_desconhecido_nao_vira_brasil(self):
        with self.assertRaises(ValidationError):
            fnrh_gateway.payload_pessoa(self.ficha(pais="País inexistente"))

    @override_settings(FNRH_API_URL="https://api.example.test", FNRH_API_USER="qa", FNRH_API_SENHA="qa", FNRH_CPF_SOLICITANTE="00000000000")
    def test_gateway_usa_envelope_oficial_e_rejeita_id_ausente(self):
        gw = fnrh_gateway.GatewaySerpro()
        with mock.patch.object(gw, "_req", side_effect=[None, {}]) as req:
            with self.assertRaises(ValidationError):
                gw.criar_pessoa(self.ficha())
        self.assertIn("pessoa", req.call_args.args[2])

    @override_settings(FNRH_API_URL="https://api.example.test", FNRH_API_USER="qa", FNRH_API_SENHA="qa", FNRH_CPF_SOLICITANTE="00000000000")
    def test_estado_remoto_deve_ser_confirmado_e_reenvio_nao_repete_post(self):
        gw = fnrh_gateway.GatewaySerpro()
        with mock.patch.object(gw, "_req", return_value={"reserva": {"situacao_reserva_id": "CONCLUIDA"}}) as req:
            gw.checkout("qa")
            self.assertEqual(req.call_count, 1)
        with mock.patch.object(gw, "_req", side_effect=[{"reserva": {}}, {}, {"reserva": {}}]):
            with self.assertRaisesMessage(ValidationError, "não confirmou"):
                gw.checkout("qa")


@override_settings(FNRH_GATEWAY="simulado")
class CicloFNRHTests(ReservasTestsBase):
    def hospedagem(self):
        r = self.reserva(status=Reserva.Status.CONFIRMADA)
        services.garantir_fichas_fnrh(r)
        for f in r.fichas_fnrh.all():
            f.nome, f.nascimento = f.nome or "QA Pessoa", HOJE - timedelta(days=365*30)
            f.documento_numero, f.cidade, f.motivo_viagem = "QA", "Itá", "LAZER_FERIAS"
            f.save()
        r.fazer_checkin(self.usuario)
        return r

    def test_entrada_saida_repetida_e_fila(self):
        r = self.hospedagem()
        gw = fnrh_gateway.GatewaySimulado()
        with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw), mock.patch.object(gw, "checkout") as saida:
            self.assertTrue(services.enviar_fnrh(r))
            self.abrir_caixa()
            services.receber_pagamento(r.conta, self.usuario, self.dinheiro, r.conta.saldo())
            r.fazer_checkout(self.usuario)
            self.assertIn(r, services.fnrh_pendentes_qs())
            self.assertTrue(services.enviar_fnrh(r))
            self.assertTrue(services.enviar_fnrh(r))
            saida.assert_called_once()

    def test_falha_parcial_preserva_reserva_e_pessoa(self):
        r = self.hospedagem()
        gw = fnrh_gateway.GatewaySimulado()
        with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw):
            with mock.patch.object(gw, "adicionar_hospede", side_effect=ValidationError("Falha controlada")):
                self.assertFalse(services.enviar_fnrh(r))
            rid = r.fnrh_reserva_id
            pid = r.fichas_fnrh.first().fnrh_pessoa_id
            self.assertTrue(rid)
            self.assertTrue(pid)
            self.assertTrue(services.enviar_fnrh(r))
            self.assertEqual(r.fnrh_reserva_id, rid)
            self.assertEqual(r.fichas_fnrh.first().fnrh_pessoa_id, pid)

    def test_alteracao_durante_envio_fica_pendente(self):
        r = self.hospedagem()
        gw = fnrh_gateway.GatewaySimulado()
        def alterar(*args, **kwargs):
            Reserva.objects.filter(pk=r.pk).update(checkout=r.checkout + timedelta(days=1))
        with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw), mock.patch.object(gw, "checkin", side_effect=alterar):
            self.assertFalse(services.enviar_fnrh(r))
        self.assertEqual(r.fnrh_status, Reserva.SincFNRH.PENDENTE)

    def test_troca_de_simulador_descarta_ids_sinteticos_antes_de_integrar(self):
        r = self.hospedagem()
        self.assertTrue(services.enviar_fnrh(r))
        anterior = r.fnrh_reserva_id
        gw = fnrh_gateway.GatewaySimulado()
        gw.ambiente = "serpro:ambiente-teste"
        with override_settings(FNRH_GATEWAY="serpro"), mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw):
            self.assertTrue(services.enviar_fnrh(r))
        self.assertNotEqual(r.fnrh_reserva_id, anterior)
        self.assertEqual(r.fnrh_ambiente, gw.ambiente)

    def test_ids_de_outro_ambiente_nao_sao_enviados_ou_apagados(self):
        r = self.hospedagem()
        self.assertTrue(services.enviar_fnrh(r))
        anterior = r.fnrh_reserva_id
        Reserva.objects.filter(pk=r.pk).update(fnrh_ambiente="serpro:outro-ambiente", fnrh_status=Reserva.SincFNRH.PENDENTE)
        gw = fnrh_gateway.GatewaySimulado()
        with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw), mock.patch.object(gw, "criar_reserva") as criar:
            self.assertFalse(services.enviar_fnrh(r))
            criar.assert_not_called()
        self.assertEqual(r.fnrh_reserva_id, anterior)
        self.assertIn("outro ambiente", r.fnrh_erro)

    def test_saida_usa_horario_efetivo_mesmo_quando_reenviada_depois(self):
        r = self.hospedagem()
        services.enviar_fnrh(r)
        saida = r.checkin_real + timedelta(hours=2)
        Reserva.objects.filter(pk=r.pk).update(status=Reserva.Status.CHECKOUT,
            checkout_real=saida, fnrh_status=Reserva.SincFNRH.PENDENTE)
        r.refresh_from_db()
        gw = fnrh_gateway.GatewaySimulado()
        with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw), mock.patch.object(gw, "checkout") as chamada:
            self.assertTrue(services.enviar_fnrh(r))
            chamada.assert_called_once_with(r.fnrh_reserva_id, data_hora=saida)

    def test_cancelamento_e_no_show_enviam_uma_vez(self):
        for estado, metodo in ((Reserva.Status.CANCELADA, "cancelar"), (Reserva.Status.NO_SHOW, "noshow")):
            with self.subTest(estado=estado):
                r = self.hospedagem()
                services.enviar_fnrh(r)
                Reserva.objects.filter(pk=r.pk).update(status=estado, fnrh_status=Reserva.SincFNRH.PENDENTE)
                r.refresh_from_db()
                gw = fnrh_gateway.GatewaySimulado()
                with mock.patch("apps.reservas.fnrh_gateway.get_gateway", return_value=gw), mock.patch.object(gw, metodo) as chamada:
                    self.assertTrue(services.enviar_fnrh(r))
                    self.assertTrue(services.enviar_fnrh(r))
                    chamada.assert_called_once()
