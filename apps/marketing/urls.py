from django.urls import path

from . import views, views_entregas, views_lps

app_name = "marketing"

urlpatterns = [
    path("", views.quadro, name="quadro"),
    path("entregas/", views_entregas.entregas, name="entregas"),
    path("entregas/nova/", views_entregas.nova_entrega, name="nova_entrega"),
    path("entregas/anexos/", views_entregas.anexos_da_entrega, name="anexos_da_entrega"),
    path("entregas/<int:pk>/editar/", views_entregas.editar_entrega, name="editar_entrega"),
    path("entregas/<int:pk>/situacao/", views_entregas.alterar_estado, name="estado_entrega"),
    path("entregas/<int:pk>/lp/", views_entregas.abrir_lp, name="abrir_lp"),
    path("materiais/<int:pk>/", views_entregas.abrir_material, name="abrir_material"),
    path("verba/teto/", views.editar_teto, name="editar_teto"),
    path("campanha/nova/", views.nova_campanha, name="nova_campanha"),
    path("campanha/<int:pk>/", views.detalhe, name="detalhe"),
    path("campanha/<int:pk>/ficha/", views.ficha, name="ficha"),
    path("campanha/<int:pk>/fase/", views.mover_fase, name="mover_fase"),
    path("campanha/<int:pk>/avancar/", views.avancar_fase, name="avancar_fase"),
    path("campanha/<int:pk>/salvar/", views.salvar_campanha, name="salvar_campanha"),
    path("campanha/<int:pk>/check/<slug:chave>/", views.marcar_check, name="marcar_check"),
    path("campanha/<int:pk>/nota/<slug:chave>/", views.salvar_nota_check, name="salvar_nota"),
    path("campanha/<int:pk>/dispensar/<slug:chave>/", views.dispensar_check, name="dispensar_check"),
    path("campanha/<int:pk>/anexar/<slug:chave>/", views.anexar_item, name="anexar_item"),
    # Ficha (gaveta): etapas, envolvidos, canais e conversa
    path("campanha/<int:pk>/etapa/", views.adicionar_etapa, name="adicionar_etapa"),
    path("etapa/<int:pk>/alternar/", views.alternar_etapa, name="alternar_etapa"),
    path("etapa/<int:pk>/remover/", views.remover_etapa, name="remover_etapa"),
    path("campanha/<int:pk>/papel/", views.atribuir_papel, name="atribuir_papel"),
    path("campanha/<int:pk>/canal/", views.alternar_canal, name="alternar_canal"),
    path("campanha/<int:pk>/aprovacao/", views.definir_aprovacao, name="definir_aprovacao"),
    path("campanha/<int:pk>/comentar/", views.comentar, name="comentar"),
    # Passo 5 — calendário + peças
    path("calendario/", views.calendario, name="calendario"),
    path("cronograma/", views.cronograma, name="cronograma"),
    # Aprovação de LPs (a prévia pública mora em urls_previa)
    path("lps/", views_lps.lps, name="lps"),
    path("lps/nova/", views_lps.nova_lp, name="nova_lp"),
    path("lps/<int:pk>/", views_lps.lp_detalhe, name="lp_detalhe"),
    path("lps/<int:pk>/v<int:numero>/", views_lps.lp_pagina, name="lp_pagina"),
    path("lps/<int:pk>/versao/", views_lps.lp_versao, name="lp_versao"),
    path("lps/<int:pk>/comentar/", views_lps.lp_comentar, name="lp_comentar"),
    path("lps/<int:pk>/link/", views_lps.lp_novo_link, name="lp_novo_link"),
    path("lps/<int:pk>/publicar/", views_lps.lp_publicar, name="lp_publicar"),
    path("lps/comentario/<int:pk>/resolver/", views_lps.lp_resolver, name="lp_resolver"),
    path("campanha/<int:pk>/peca/", views.adicionar_peca, name="adicionar_peca"),
    path("peca/<int:pk>/status/", views.marcar_peca, name="marcar_peca"),
    path("peca/<int:pk>/remover/", views.remover_peca, name="remover_peca"),
    # Passo 6 — relatório + gastos
    path("relatorio/", views.relatorio, name="relatorio"),
    path("campanha/<int:pk>/gasto/", views.lancar_gasto, name="lancar_gasto"),
    # Passo 9 — ocupação × campanha
    path("ocupacao/", views.ocupacao, name="ocupacao"),
    # Passo 10 — duplicar
    path("campanha/<int:pk>/duplicar/", views.duplicar, name="duplicar"),
]
