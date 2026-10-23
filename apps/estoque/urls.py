from django.urls import path
from django.views.generic import RedirectView

from . import views, views_notas, views_suprimentos

app_name = "estoque"

urlpatterns = [
    path("notas/", views_notas.notas, name="notas"),
    path("notas/nova/", views_notas.nota_nova, name="nota_nova"),
    path("notas/<int:pk>/", views_notas.nota_detalhe, name="nota"),
    path("notas/<int:pk>/receber/", views_notas.nota_receber, name="nota_receber"),
    path("notas/<int:pk>/anexos/", views_notas.nota_anexar, name="nota_anexar"),
    path("notas/<int:pk>/anexos/<int:documento_id>/", views_notas.nota_documento, name="nota_documento"),
    path("compras/", views_suprimentos.compras, name="compras"),
    path("compras/receber/", views_suprimentos.compra_form, name="compra_receber"),
    path("produtos/<int:pk>/suprimentos/", views_suprimentos.produto_suprimentos, name="produto_suprimentos"),
    path("produtos/<int:produto_pk>/embalagens/nova/", views_suprimentos.embalagem_form, name="embalagem_nova"),
    path("produtos/<int:produto_pk>/embalagens/<int:pk>/", views_suprimentos.embalagem_form, name="embalagem_editar"),
    path("produtos/<int:pk>/ficha/", views_suprimentos.ficha_form, name="ficha_editar"),
    path("lotes/", views_suprimentos.lotes, name="lotes"),
    path("lotes/novo/", views_suprimentos.lote_form, name="lote_novo"),
    path("lotes/identificar/", views_suprimentos.identificar, name="lote_identificar"),
    path("lotes/<int:pk>/", views_suprimentos.lote_detalhe, name="lote"),
    path("lotes/<int:pk>/corrigir/", views_suprimentos.correcao_lote, name="lote_corrigir"),
    path("lotes/<int:pk>/contar/<int:local_pk>/", views_suprimentos.contagem_lote, name="lote_contar"),
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
