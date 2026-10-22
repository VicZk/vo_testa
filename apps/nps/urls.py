from django.urls import path

from . import views

app_name = "nps"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("convite/<int:reserva_id>/", views.convite, name="convite"),
    path("resposta/<int:resposta_id>/acompanhar/", views.tratar, name="tratar"),
]
