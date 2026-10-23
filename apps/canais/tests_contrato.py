"""Contrato de transporte e seleção de dados, sem conexão com o provedor."""
import copy
import json
import uuid
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from .gateways import Channex, ErroCanal
from .normalizacao import normalizar


def revisao_exemplo(propriedade=None):
    propriedade = str(propriedade or uuid.uuid4())
    identificador = str(uuid.uuid4())
    return {"id": identificador, "type": "booking_revision", "attributes": {
        "id": identificador, "property_id": propriedade, "booking_id": str(uuid.uuid4()),
        "inserted_at": "2027-01-01T12:00:00Z", "status": "new", "currency": "BRL",
        "amount": "600.00", "payment_collect": "property", "ota_name": "OTA de teste",
        "ota_reservation_code": "QA-123", "customer": {
            "name": "Hóspede", "surname": "Fictício QA", "mail": "qa@example.invalid"},
        "rooms": [{"room_type_id": str(uuid.uuid4()), "rate_plan_id": str(uuid.uuid4()),
            "ota_unique_id": "quarto-qa", "checkin_date": "2027-02-01", "checkout_date": "2027-02-03",
            "amount": "600.00", "occupancy": {"adults": 2, "children": 0, "infants": 0},
            "days": {"2027-02-01": "300.00", "2027-02-02": "300.00"}}],
    }}


class NormalizacaoTests(SimpleTestCase):
    def test_guarda_apenas_dados_da_estadia_e_descarta_garantia_e_notas(self):
        bruto = revisao_exemplo()
        # Um identificador legítimo pode conter os mesmos dígitos do CVV.
        bruto["attributes"]["booking_id"] = "9994fb6f-6008-4d3e-baff-e6305ebc2caa"
        bruto["attributes"].update({
            "guarantee": {"card_number": "DADO_QUE_NAO_PODE_SER_GUARDADO", "cvv": "999"},
            "notes": "SEGREDO EM TEXTO LIVRE", "card_number": "OUTRO DADO",
        })
        resultado = normalizar(bruto, bruto["attributes"]["property_id"])
        self.assertEqual(resultado["valor"], "600.00")
        self.assertEqual(resultado["cliente"]["nome"], "Hóspede Fictício QA")
        for valor in ("DADO_QUE", "SEGREDO", "OUTRO DADO", "guarantee", "card_number", "cvv"):
            self.assertNotIn(valor, repr(resultado))
        self.assertNotIn('"999"', json.dumps(resultado))

    def test_recusa_estrutura_identidade_datas_e_quantidades_malformadas(self):
        base = revisao_exemplo()
        propriedade = base["attributes"]["property_id"]
        alteracoes = [
            ("property_id", str(uuid.uuid4())), ("id", str(uuid.uuid4())),
            ("status", "paid"), ("inserted_at", None), ("amount", "NaN"),
            ("amount", "1e100000"), ("amount", True), ("amount", 0.1),
            ("customer", []), ("rooms", []), ("rooms", [None]),
        ]
        for chave, valor in alteracoes:
            with self.subTest(campo=chave, valor=repr(valor)[:50]):
                bruto = copy.deepcopy(base)
                bruto["attributes"][chave] = valor
                with self.assertRaises(ValidationError):
                    normalizar(bruto, propriedade)
        for campo, valor in (("checkin_date", "inválida"), ("checkout_date", "2027-01-01"),
                             ("occupancy", {"adults": True}), ("days", {"2028-01-01": "1"})):
            with self.subTest(quarto=campo):
                bruto = copy.deepcopy(base)
                bruto["attributes"]["rooms"][0][campo] = valor
                with self.assertRaises(ValidationError):
                    normalizar(bruto, propriedade)


@override_settings(CHANNEX_API_KEY="chave-ficticia-qa", CHANNEX_API_KEY_HML="chave-ficticia-qa")
class TransporteTests(SimpleTestCase):
    def setUp(self):
        self.propriedade = str(uuid.uuid4())
        self.abrir = Mock()
        self.resposta = MagicMock(status=200)
        self.resposta.__enter__.return_value = self.resposta
        self.resposta.read.return_value = b"{}"
        self.abrir.return_value = self.resposta
        self.gateway = Channex("homologacao", self.propriedade, abrir=self.abrir)

    def test_feed_identifica_propriedade_sem_redirecionar_e_le_decimal(self):
        self.resposta.read.return_value = json.dumps({"data": [revisao_exemplo(self.propriedade)]}).encode()
        self.assertEqual(len(self.gateway.revisoes()), 1)
        req = self.abrir.call_args.args[0]
        self.assertEqual(req.method, "GET")
        self.assertTrue(req.full_url.startswith("https://staging.channex.io/api/v1/booking_revisions/feed?"))
        self.assertEqual(parse_qs(urlparse(req.full_url).query)["filter[property_id]"], [self.propriedade])
        self.assertEqual(req.get_header("User-api-key"), "chave-ficticia-qa")
        self.assertEqual(self.abrir.call_args.kwargs["timeout"], 25)

    def test_aceite_parcial_ou_sem_tarefa_nunca_confirma_envio(self):
        tarefa = {"id": str(uuid.uuid4()), "type": "task"}
        respostas = [None, [], {"meta": None}, {"meta": {"message": "Success"}, "data": []},
            {"meta": {"message": "Success", "warnings": ["campo inválido"]}, "data": [tarefa]},
            {"meta": {"message": "Success"}, "data": [{"type": "task", "id": "inválido"}]}]
        for resposta in respostas:
            with self.subTest(resposta=resposta):
                self.resposta.read.return_value = json.dumps(resposta).encode()
                with self.assertRaises(ErroCanal):
                    self.gateway.disponibilidade([{"property_id": self.propriedade}])
        self.resposta.read.return_value = json.dumps({"meta": {"message": "Success"}, "data": [tarefa]}).encode()
        valores = [{"property_id": self.propriedade, "rate": "300.00"}]
        self.assertEqual(self.gateway.tarifas(valores), [tarefa["id"]])
        self.assertEqual(json.loads(self.abrir.call_args.args[0].data)["values"][0]["rate"], "300.00")

    def test_falha_nao_expoe_corpo_recebido_nem_credenciais(self):
        for status in (301, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.abrir.side_effect = HTTPError("https://staging.channex.io/", status, "chave-ficticia-qa e dados pessoais", {}, None)
                with self.assertRaises(ErroCanal) as erro:
                    self.gateway.revisoes()
                self.assertNotIn("chave-ficticia", str(erro.exception))
                self.assertNotIn("dados pessoais", str(erro.exception))
        self.abrir.side_effect = TimeoutError("chave-ficticia-qa")
        with self.assertRaises(ErroCanal) as erro:
            self.gateway.revisoes()
        self.assertNotIn("chave-ficticia", str(erro.exception))

    def test_ack_precisa_confirmacao_explicita(self):
        self.resposta.read.return_value = b'{"meta":{"message":"Failed"}}'
        with self.assertRaises(ErroCanal):
            self.gateway.confirmar_recebimento(uuid.uuid4())
        self.resposta.read.return_value = b'{"meta":{"message":"Success"}}'
        self.gateway.confirmar_recebimento(uuid.uuid4())

    @override_settings(CHANNEX_API_KEY="", CHANNEX_API_KEY_HML="")
    def test_sem_chave_nao_faz_requisicao(self):
        with self.assertRaises(ErroCanal):
            self.gateway.revisoes()
        self.abrir.assert_not_called()
