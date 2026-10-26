"""Aba "Comparativo" da cópia atualizada na VPS (deploy/vps/comparador/comparativo.py)."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import path

from config.urls import urlpatterns as rotas_do_projeto
from deploy.vps.comparador.comparativo import ANTERIOR, comparativo

urlpatterns = [path("crm/comparativo/", comparativo, name="comparativo"), *rotas_do_projeto]
TEMPLATES = [{**settings.TEMPLATES[0], "DIRS": [
    *settings.TEMPLATES[0]["DIRS"], Path(settings.BASE_DIR) / "deploy/vps/comparador/templates"]}]


@override_settings(ROOT_URLCONF=__name__, TEMPLATES=TEMPLATES)
class ComparativoTests(TestCase):
    def test_abre_com_as_telas_das_duas_versoes(self):
        usuario = get_user_model().objects.create_superuser(username="teste", password=None)
        self.client.force_login(usuario)
        r = self.client.get("/crm/comparativo/")
        self.assertContains(r, "<h1>Comparativo entre versões</h1>", html=True)
        self.assertContains(r, f'href="{ANTERIOR}/crm/')
