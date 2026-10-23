"""Dados bancários inválidos não se tornam uma liquidação confirmada."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado, Usuario

from . import services
from .models import EventoPagamento


@override_settings(PAGAMENTOS_GATEWAY="simulado", PIX_DIRETO=False)
class LiquidacaoValidacaoTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="liquidacao-validacao", password="forte-123-abc")
        ModuloContratado.objects.update_or_create(codigo="pagamentos", defaults={"ativo": True})
        self.cobranca = services.criar_cobranca(
            self.op, valor=Decimal("100"), metodo="pix", descricao="Cobrança fictícia")
        services.confirmar_pagamento(self.cobranca, self.op)

    def test_valores_invalidos_nao_alteram_a_cobranca(self):
        for valor in ("-5", "100.01", "NaN", "Infinity", "1e9999", "99.999", "texto"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValidationError):
                    services.registrar_liquidacao(self.cobranca, valor_liquido=valor)
                self.cobranca.refresh_from_db()
                self.assertFalse(self.cobranca.liquidado)
                self.assertIsNone(self.cobranca.valor_liquido)
        self.assertFalse(EventoPagamento.objects.filter(tipo="liquidada").exists())

    def test_taxa_deve_caber_no_bruto_e_conferir_com_liquido(self):
        for dados in ({"taxa": "-1"}, {"taxa": "101"}, {"taxa": "NaN"},
                      {"valor_liquido": "98", "taxa": "1"}):
            with self.subTest(dados=dados):
                with self.assertRaises(ValidationError):
                    services.registrar_liquidacao(self.cobranca, **dados)
                self.cobranca.refresh_from_db()
                self.assertFalse(self.cobranca.liquidado)

    def test_notificacao_sem_valores_nao_apaga_conferencia_anterior(self):
        hoje = timezone.localdate()
        services.registrar_liquidacao(
            self.cobranca, valor_liquido="98", data_liquidacao=hoje, id_liquidacao="DEP-01")
        services.registrar_liquidacao(self.cobranca, id_liquidacao="DEP-01")
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.valor_liquido, Decimal("98"))
        self.assertEqual(self.cobranca.taxa, Decimal("2"))
        self.assertEqual(self.cobranca.data_liquidacao, hoje)
        self.assertEqual(EventoPagamento.objects.filter(tipo="liquidada").count(), 1)

    def test_id_do_deposito_muito_longo_e_recusado_antes_de_gravar(self):
        with self.assertRaises(ValidationError):
            services.registrar_liquidacao(self.cobranca, valor_liquido="98", id_liquidacao="x" * 81)
        self.cobranca.refresh_from_db()
        self.assertFalse(self.cobranca.liquidado)

    def test_data_invalida_nao_e_trocada_silenciosamente_por_hoje(self):
        self.client.force_login(self.op)
        resposta = self.client.post(reverse("pagamentos:liquidar", args=[self.cobranca.pk]), {
            "valor_liquido": "98", "data_liquidacao": "2026-02-30", "id_liquidacao": "DEP-01",
        }, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertIn("data", " ".join(resposta.json()["errors"]).lower())
        self.cobranca.refresh_from_db()
        self.assertFalse(self.cobranca.liquidado)
