"""A página só confirma uma inscrição efetivamente registrada no CRM."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import Pessoa


class FalhaCaptacaoLPTests(TestCase):
    rotas = ("lp:fundador_lead", "lp:fundador_2_lead", "lp:inauguracao_lead")
    dados = {"nome": "Contato fictício QA", "email": "qa@example.invalid", "ms": 4000}

    def setUp(self):
        cache.clear()

    def enviar(self, rota, dados=None):
        cache.clear()
        return self.client.post(reverse(rota), self.dados if dados is None else dados,
                                content_type="application/json")

    def test_falha_de_gravacao_nao_confirma_nem_envia_conversao(self):
        def falhar(**kwargs):
            Pessoa.objects.create(nome="Contato parcial QA")
            raise RuntimeError("falha simulada")

        for rota in self.rotas:
            with self.subTest(rota=rota), patch(
                "apps.comercial.services.capturar_lead_site", side_effect=falhar
            ), patch("apps.comercial.services.enviar_capi_lead") as capi:
                resposta = self.enviar(rota)
                self.assertEqual(resposta.status_code, 503)
                self.assertFalse(resposta.json()["ok"])
                self.assertFalse(Pessoa.objects.filter(nome="Contato parcial QA").exists())
                capi.assert_not_called()

    def test_captacao_indisponivel_nao_confirma(self):
        for rota in self.rotas:
            with self.subTest(rota=rota), patch(
                "apps.comercial.services.capturar_lead_site", return_value=None
            ), patch("apps.comercial.services.enviar_capi_lead") as capi:
                self.assertEqual(self.enviar(rota).status_code, 503)
                capi.assert_not_called()

    def test_json_ou_contato_invalido_nao_chega_ao_servico(self):
        invalidos = [[], 1, {**self.dados, "nome": []},
                     {**self.dados, "email": "sem-arroba"},
                     {**self.dados, "nome": "A" * 300},
                     {**self.dados, "rastreio": "invalido"}]
        for dados in invalidos:
            with self.subTest(dados=dados), patch(
                "apps.comercial.services.capturar_lead_site"
            ) as capturar:
                self.assertEqual(self.enviar(self.rotas[0], dados).status_code, 400)
                capturar.assert_not_called()

    def test_indisponibilidade_de_metrica_nao_desfaz_inscricao_salva(self):
        with patch("apps.comercial.services.capturar_lead_site", return_value=object()), patch(
            "apps.comercial.services.enviar_capi_lead", side_effect=RuntimeError
        ):
            resposta = self.enviar(self.rotas[0])
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["ok"])
