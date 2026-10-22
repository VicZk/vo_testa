from django.urls import path

from . import views

app_name = "fiscal"

urlpatterns = [
    path("produtos/", views.produtos, name="produtos"),
    path("produtos/<int:pk>/", views.produto, name="produto"),
    path("conta/<int:pk>/", views.preparar_conta, name="preparar_conta"),
    path("", views.painel, name="painel"),
    path("webhook/", views.webhook, name="webhook"),
    path("emitir-nfse/", views.emitir_nfse, name="emitir_nfse"),
    path("consumo/<str:origem>/<int:pk>/", views.emitir_consumo, name="emitir_consumo"),
    path("<int:pk>/", views.detalhe, name="detalhe"),
    path("<int:pk>/atualizar/", views.atualizar, name="atualizar"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]
