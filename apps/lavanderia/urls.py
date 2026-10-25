from django.urls import path

from . import views

app_name = "lavanderia"

urlpatterns = [
    path("", views.painel, name="painel"),
    path("abrir/", views.abrir, name="abrir"),
    path("historico/", views.historico, name="historico"),
    path("servicos/", views.servicos, name="servicos"),
    path("servicos/<int:pk>/", views.servico_salvar, name="servico_salvar"),
    path("rouparia/", views.rouparia, name="rouparia"),
    path("rouparia/item/", views.rouparia_item, name="rouparia_item"),
    path("rouparia/mover/", views.rouparia_mover, name="rouparia_mover"),
    path("rouparia/lote/", views.rouparia_lote, name="rouparia_lote"),
    path("rouparia/extrato/", views.extrato, name="extrato"),
    path("<int:pk>/", views.ordem, name="ordem"),
    path("<int:pk>/cupom/", views.cupom, name="cupom"),
    path("<int:pk>/item/", views.add_item, name="add_item"),
    path("<int:pk>/item/<int:item_pk>/qtd/", views.item_qtd, name="item_qtd"),
    path("<int:pk>/item/<int:item_pk>/remover/", views.remover_item, name="remover_item"),
    path("<int:pk>/observacao/", views.observacao, name="observacao"),
    path("<int:pk>/avancar/", views.avancar, name="avancar"),
    path("<int:pk>/entregar/", views.entregar, name="entregar"),
    path("<int:pk>/vincular/", views.vincular, name="vincular"),
    path("<int:pk>/cancelar/", views.cancelar, name="cancelar"),
]
