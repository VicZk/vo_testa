"""Rotas PÚBLICAS da prévia de LP (fora do /crm/): o link que vai para quem aprova."""
from django.urls import path

from . import views_previa

app_name = "previa_lp"

urlpatterns = [
    path("<str:token>/", views_previa.ver, name="ver"),
    path("<str:token>/v<int:numero>/", views_previa.pagina, name="pagina"),
]
