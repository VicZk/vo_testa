from django.urls import path

from . import views, webhooks

app_name = "canais"
urlpatterns = [
    path("webhook/<str:ambiente>/", webhooks.receber, name="webhook"),
    path("", views.painel, name="painel"),
    path("conexoes/nova/", views.conexao, name="conexao_nova"),
    path("conexoes/<int:pk>/", views.conexao, name="conexao"),
    path("conexoes/<int:pk>/categorias/", views.categorias, name="categorias"),
    path("conexoes/<int:conexao_pk>/categorias/nova/", views.mapeamento, name="mapeamento_novo"),
    path("conexoes/<int:conexao_pk>/categorias/<int:pk>/", views.mapeamento, name="mapeamento"),
    path("conexoes/<int:pk>/validacao/", views.validacao, name="validacao"),
    path("conexoes/<int:pk>/solicitar/", views.solicitar, name="solicitar"),
    path("conexoes/<int:pk>/disponibilidade/", views.disponibilidade, name="disponibilidade"),
    path("conexoes/<int:pk>/envios/", views.envios, name="envios"),
    path("revisoes/<int:pk>/", views.revisao, name="revisao"),
    path("revisoes/<int:pk>/aplicar/", views.aplicar, name="aplicar"),
    path("revisoes/<int:pk>/resolver/", views.resolver, name="resolver"),
    path("envios/<int:pk>/", views.envio, name="envio"),
]
