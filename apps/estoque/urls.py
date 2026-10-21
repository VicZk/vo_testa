from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "estoque"

urlpatterns = [
    path("", views.posicao, name="posicao"),
    path("produtos/", views.produtos, name="produtos"),
    path("produtos/novo/", views.produto_form, name="produto_novo"),
    path("produtos/<int:pk>/", views.produto_form, name="produto_editar"),
    path("produtos/<int:pk>/kardex/", views.kardex, name="kardex"),
    path("cadastros/", views.cadastros, name="cadastros"),
    path("entrada/", views.entrada, name="entrada"),
    path("saida/", views.saida, name="saida"),
    path("transferencia/", views.transferencia, name="transferencia"),
    path("ajuste/", views.ajuste, name="ajuste"),
    path("inventarios/", views.inventarios, name="inventarios"),
    path("inventarios/<int:pk>/", views.inventario, name="inventario"),
    # Categorias e locais viraram uma tela só (Cadastros). Os endereços antigos
    # seguem valendo — estavam em favoritos e na paleta de comandos.
    path(
        "categorias/",
        RedirectView.as_view(pattern_name="estoque:cadastros", permanent=False),
        name="categorias",
    ),
    path(
        "locais/",
        RedirectView.as_view(pattern_name="estoque:cadastros", permanent=False),
        name="locais",
    ),
]
