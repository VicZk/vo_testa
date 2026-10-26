"""Acesso sem senha das cópias de comparação da VPS (deploy/vps/comparador/acesso_livre.py)."""

import os
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponseNotFound
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from deploy.vps.comparador.acesso_livre import AcessoLivreMiddleware

NAVEGADOR = {"HTTP_SEC_FETCH_MODE": "navigate"}
DO_OUTRO_SITE = {**NAVEGADOR, "HTTP_SEC_FETCH_SITE": "cross-site"}


@override_settings(MIDDLEWARE=[*settings.MIDDLEWARE,
                               "deploy.vps.comparador.acesso_livre.AcessoLivreMiddleware"])
@mock.patch.dict(os.environ, {"ACESSO_LIVRE_USUARIO": "teste"})
class AcessoLivreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_superuser(username="teste", password=None)

    def test_tela_do_crm_abre_sem_senha(self):
        r = self.client.get(reverse("dashboard"), **NAVEGADOR)
        self.assertRedirects(r, f"{reverse('login')}?next={reverse('dashboard')}",
                             fetch_redirect_response=False)
        r = self.client.get(r["Location"], **NAVEGADOR)
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.usuario.pk)

    def test_next_para_fora_cai_no_painel(self):
        r = self.client.get(reverse("login") + "?next=https://exemplo.com/", **NAVEGADOR)
        self.assertRedirects(r, reverse("dashboard"), fetch_redirect_response=False)

    def test_sem_navegador_ou_depois_de_sair_pede_senha(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.client.force_login(self.usuario)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("login"), **NAVEGADOR).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    @mock.patch.dict(os.environ, {"ACESSO_LIVRE_USUARIO": ""})
    def test_sem_a_variavel_nada_muda(self):
        self.assertEqual(self.client.get(reverse("login"), **NAVEGADOR).status_code, 200)

    def test_tela_que_nao_existe_do_outro_lado_sobe_ate_uma_que_existe(self):
        r = self.client.get("/crm/nao-existe/", **DO_OUTRO_SITE)
        self.assertRedirects(r, "/crm/", fetch_redirect_response=False)
        # Caminho com "//" não vira endereço de outro site.
        request = RequestFactory().get("/", **DO_OUTRO_SITE)
        request.path_info = "//exemplo.com/x/"
        r = AcessoLivreMiddleware(lambda _: HttpResponseNotFound())(request)
        self.assertEqual(r["Location"], "/exemplo.com/")
