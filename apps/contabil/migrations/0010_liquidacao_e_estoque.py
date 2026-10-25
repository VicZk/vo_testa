"""
Integração da camada Contábil com os fluxos do fork, sem contar nada duas vezes:

- Contas fora da DRE (ativo/passivo) para o dinheiro que só liquida o que a DRE já
  reconheceu pela competência: o faturado que a agência pagou (a diária já entrou), a
  folha paga por recorrência (o fechamento já lançou) e a compra que entra no estoque
  (o custo vem pela saída: CMV, consumo interno e perdas).
- Regras do de-para para as capturas novas (consumo interno, perdas, descontos da
  conta) e para a liquidação, todas editáveis depois pelo admin.
- "Hospedagem faturada" e "Salários" passam a geridas pelo sistema; "Outras receitas"
  nasce manual, para a conta a receber avulsa (evento, parceria) ter categoria.
- Recarimba só o que nasceu de baixa de título com categoria gerida pelo sistema, e o
  que é "Insumos" (compra para o estoque). Lançamento manual antigo fica como está.
"""

from django.db import migrations

# (classificacao, nome, grupo, natureza, tipo, ordem)
CONTAS = [
    ("1", "ATIVO", "ativo", "devedora", "sintetica", 100),
    ("1.1.02.01", "Recebimento de receita já reconhecida (faturado)", "ativo", "devedora",
     "analitica", 112),
    ("1.1.03.01", "Estoque (compras de mercadorias e insumos)", "ativo", "devedora",
     "analitica", 113),
    ("2", "PASSIVO", "passivo", "credora", "sintetica", 200),
    ("2.1.01.01", "Pagamento de despesa já reconhecida (folha, impostos)", "passivo",
     "credora", "analitica", 211),
]
# origem_sistema -> (classificação, prioridade)
REGRAS = {
    # Acima do de-para por categoria (10): a liquidação vence o "Hospedagem → serviço".
    "liquidacao_receita": ("1.1.02.01", 60),
    "liquidacao_despesa": ("2.1.01.01", 60),
    "consumo_estoque": ("4.2.01.02", 8),
    "perda_estoque": ("4.2.01.03", 8),
    "desconto_folio": ("3.1.02.02", 8),
}
LIQUIDACAO = {"receita": "1.1.02.01", "despesa": "2.1.01.01"}
ESTOQUE = "1.1.03.01"


def aplicar(apps, schema_editor):
    ContaContabil = apps.get_model("contabil", "ContaContabil")
    MapeamentoContabil = apps.get_model("contabil", "MapeamentoContabil")
    Categoria = apps.get_model("nucleo", "CategoriaFinanceira")
    Lancamento = apps.get_model("nucleo", "LancamentoFinanceiro")
    Titulo = apps.get_model("nucleo", "ContaPagarReceber")

    contas = {}
    for classif, nome, grupo, natureza, tipo, ordem in CONTAS:
        contas[classif], _ = ContaContabil.objects.get_or_create(
            classificacao=classif,
            defaults=dict(nome=nome, grupo=grupo, natureza=natureza, tipo=tipo, ordem=ordem),
        )
    for classif in ("1.1.02.01", "1.1.03.01"):
        if contas[classif].conta_pai_id is None:
            contas[classif].conta_pai = contas["1"]
            contas[classif].save(update_fields=["conta_pai"])
    if contas["2.1.01.01"].conta_pai_id is None:
        contas["2.1.01.01"].conta_pai = contas["2"]
        contas["2.1.01.01"].save(update_fields=["conta_pai"])

    for origem, (classif, prioridade) in REGRAS.items():
        conta = ContaContabil.objects.filter(classificacao=classif).first()
        if conta:
            MapeamentoContabil.objects.get_or_create(
                origem_sistema=origem,
                defaults=dict(conta=conta, prioridade=prioridade,
                              observacao="integração com o fork (liquidação e estoque)"),
            )

    Categoria.objects.filter(nome="Hospedagem faturada", tipo="receita").update(automatica=True)
    Categoria.objects.filter(nome="Salários", tipo="despesa").update(automatica=True)
    outras, _ = Categoria.objects.get_or_create(
        nome="Outras receitas", tipo="receita", defaults={"automatica": False})
    servico = ContaContabil.objects.filter(classificacao="3.1.01.03").first()
    if servico and not MapeamentoContabil.objects.filter(categoria=outras).exists():
        MapeamentoContabil.objects.create(
            conta=servico, categoria=outras, prioridade=10,
            observacao="receita avulsa (evento, parceria)")

    for insumos in Categoria.objects.filter(nome="Insumos", tipo="despesa"):
        regra = MapeamentoContabil.objects.filter(categoria=insumos).first()
        if regra:
            regra.conta = contas[ESTOQUE]
            regra.observacao = "compra para o estoque: o custo vem pela saída"
            regra.save(update_fields=["conta", "observacao"])
        else:
            MapeamentoContabil.objects.create(
                conta=contas[ESTOQUE], categoria=insumos, prioridade=10,
                observacao="compra para o estoque: o custo vem pela saída")
        Lancamento.objects.filter(categoria=insumos).update(conta_contabil=ESTOQUE)
        Titulo.objects.filter(categoria=insumos).update(conta_contabil=ESTOQUE)

    for tipo, classif in LIQUIDACAO.items():
        titulos = Titulo.objects.filter(categoria__automatica=True, categoria__tipo=tipo)
        titulos.update(conta_contabil=classif)
        Lancamento.objects.filter(
            pk__in=titulos.filter(lancamento__isnull=False).values("lancamento_id"),
            origem="manual",
        ).update(conta_contabil=classif)


class Migration(migrations.Migration):
    dependencies = [
        ("contabil", "0009_grupos_fora_da_dre"),
        ("nucleo", "0063_padroes_no_banco_contabil"),
    ]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
