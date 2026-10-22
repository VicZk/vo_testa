from django.urls import path

from . import views

app_name = "restaurante"

urlpatterns = [
    path("", views.comandas, name="comandas"),
    path("abrir/", views.abrir, name="abrir"),
    path("historico/", views.historico, name="historico"),
    path("mesas/", views.mesas, name="mesas"),
    path("cozinha/", views.cozinha, name="cozinha"),
    path("cardapio/", views.cardapio_config, name="cardapio_config"),
    path("cardapio/<int:produto_pk>/", views.cardapio_produto, name="cardapio_produto"),
    path("<int:pk>/", views.comanda, name="comanda"),
    path("<int:pk>/cupom/", views.cupom, name="cupom"),
    path("<int:pk>/item/", views.add_item, name="add_item"),
    path("<int:pk>/produto/<int:produto_pk>/", views.pedir_item, name="pedir_item"),
    path("<int:pk>/item/<int:item_pk>/editar/", views.editar_item, name="editar_item"),
    path("<int:pk>/item/<int:item_pk>/preparo/", views.preparo_item, name="preparo_item"),
    path("<int:pk>/item/<int:item_pk>/remover/", views.remover_item, name="remover_item"),
    path("<int:pk>/fechar/", views.fechar, name="fechar"),
    path("<int:pk>/vincular/", views.vincular, name="vincular"),
    path("<int:pk>/transferir/", views.transferir, name="transferir"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]
