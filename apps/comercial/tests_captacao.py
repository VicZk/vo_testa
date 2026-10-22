"""A página só confirma contato gravado; erro preserva o formulário."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import Pessoa, Usuario

from .models import Oportunidade, PaginaCaptacao


class CaptacaoPublicaValidacaoTests(TestCase):
    def setUp(self):
        cache.clear()
        usuario = Usuario.objects.create_superuser(username="captacao-qa", password="forte-123-abc")
        self.pagina = PaginaCaptacao.objects.create(
            nome="Campanha QA", slug="campanha-qa", status="publicada", criado_por=usuario,
        )
        self.url = reverse("captacao:publica", args=[self.pagina.slug])
        self.dados = {
            "nome": "Contato fictício preservado", "telefone": "49999990000",
            "email": "captacao@example.invalid", "pessoas": "4", "consent": "on",
            "checkin": "2026-11-14", "checkout": "2026-11-16", "utm_campaign": "campanha-qa",
        }

    def test_falha_de_gravacao_preserva_campos_e_desfaz_contato_parcial(self):
        with patch("apps.comercial.services.criar_oportunidade", side_effect=RuntimeError("falha fictícia")):
            resposta = self.client.post(self.url, self.dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não foi possível receber seu contato")
        for campo, valor in self.dados.items():
            if campo not in {"utm_campaign", "consent"}:
                self.assertEqual(resposta.context["form"][campo].value(), valor)
        self.assertContains(resposta, 'value="Contato fictício preservado"')
        self.assertContains(resposta, 'name="consent" id="id_consent" checked')
        self.assertFalse(Pessoa.objects.filter(email=self.dados["email"]).exists())
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())

    def test_indisponibilidade_nao_anuncia_sucesso(self):
        with patch("apps.comercial.views.services.capturar_lead_site", return_value=None):
            resposta = self.client.post(self.url, self.dados)
        self.assertContains(resposta, "Não foi possível receber seu contato")
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())

    def test_campos_invalidos_nao_viram_lead_incompleto(self):
        for campo, valor in (("telefone", "abc"), ("email", "invalido"), ("pessoas", "20"),
                             ("checkout", "2026-11-13"), ("checkin", "data inválida")):
            with self.subTest(campo=campo):
                resposta = self.client.post(self.url, {**self.dados, campo: valor})
                self.assertEqual(resposta.status_code, 200)
                self.assertIn(campo, resposta.context["form"].errors)
                self.assertEqual(resposta.context["form"][campo].value(), valor)
        self.assertFalse(Pessoa.objects.filter(email=self.dados["email"]).exists())
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())

    def test_robo_continua_descartado_sem_revelar_protecao(self):
        resposta = self.client.post(self.url, {**self.dados, "empresa_site": "robô"})
        self.assertRedirects(resposta, f"{self.url}?ok=1", fetch_redirect_response=False)
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())

    def test_correcao_grava_datas_pessoas_e_rastreio(self):
        self.client.post(self.url, {**self.dados, "checkout": "2026-11-13"})
        resposta = self.client.post(self.url, self.dados)
        self.assertRedirects(resposta, f"{self.url}?ok=1", fetch_redirect_response=False)
        lead = Oportunidade.objects.get(pagina_captacao=self.pagina)
        self.assertEqual(lead.hospedes, 4)
        self.assertEqual(str(lead.checkout_previsto), "2026-11-16")
        self.assertEqual(lead.origem_rastreio["utm_campaign"], "campanha-qa")
        self.assertTrue(lead.pessoa.aceita_email)
        self.assertTrue(lead.pessoa.aceita_whatsapp)
