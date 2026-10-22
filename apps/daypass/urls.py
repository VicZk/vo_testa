from django.urls import path

from . import views

app_name = "daypass"
urlpatterns = [
    path("", views.painel, name="painel"),
    path("turnos/novo/", views.turno, name="turno_novo"),
    path("turnos/<int:pk>/", views.turno, name="turno"),
    path("turnos/<int:turno_pk>/visita/", views.nova_visita, name="nova_visita"),
    path("visitas/<int:pk>/", views.visita, name="visita"),
    path("visitas/<int:pk>/<str:acao>/", views.acao, name="acao"),
    path("visitas/<int:pk>/visitante/<int:visitante_pk>/<str:acao>/", views.acesso, name="acesso"),
]
