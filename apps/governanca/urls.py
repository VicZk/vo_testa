from django.urls import path

from . import views

app_name = "governanca"

urlpatterns = [
    # A ENTRADA é a visão geral (a casa em blocos); a lista operacional, que é a
    # ferramenta de quem está trabalhando, mora em /quartos/.
    path("", views.painel, name="painel"),
    path("quartos/", views.quartos, name="quartos"),
    # A fila da camareira: a mesma informação da lista, no formato do celular dela.
    path("minha-fila/", views.minha_fila, name="minha_fila"),
    path("discrepancias/", views.discrepancias, name="discrepancias"),
    path("faxina/nova/", views.nova_tarefa, name="nova_tarefa"),
    path("fila/distribuir/", views.distribuir, name="distribuir"),
    path("tarefa/<int:pk>/", views.tarefa_acao, name="tarefa_acao"),
    # Ficha do quarto: o toque na porta do corredor resolve o quarto ali.
    path("quarto/<int:pk>/", views.quarto, name="quarto"),
    path("quarto/<int:pk>/status/", views.status_marcar, name="status_marcar"),
    path("quarto/<int:pk>/ronda/", views.ronda, name="ronda"),
    path("quarto/<int:pk>/devolver/", views.devolver, name="devolver"),
    path("quarto/<int:pk>/problema/", views.reportar, name="reportar"),
]
