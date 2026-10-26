"""Rotas da cópia atualizada na VPS: as do projeto mais a aba "Comparativo"."""

from comparativo import comparativo
from django.urls import path

from config.urls import *  # noqa: F403  (handler404 e afins vêm junto)
from config.urls import urlpatterns as rotas_do_projeto

urlpatterns = [path("crm/comparativo/", comparativo, name="comparativo"), *rotas_do_projeto]
