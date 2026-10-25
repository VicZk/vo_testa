"""
Junta as duas pontas do Contábil: a do fork (0009 grupos fora da DRE e 0010 liquidação e
estoque) e a do original (0009 conta de dedução com rótulo neutro, Lucro Presumido).

O fechamento do mês passou a chamar o tributo de "Impostos sobre a receita". A categoria
antiga troca de nome junto, para o próximo "Fechar o mês" não criar uma segunda (o
`get_or_create` é pelo nome). Lançamento e conta contábil não mudam: seguem na 3.1.02.01.
"""

from django.db import migrations

ANTIGA = "Simples Nacional (DAS)"
NOVA = "Impostos sobre a receita"


def renomear_categoria(apps, schema_editor):
    CategoriaFinanceira = apps.get_model("nucleo", "CategoriaFinanceira")
    if not CategoriaFinanceira.objects.filter(nome=NOVA, tipo="despesa").exists():
        CategoriaFinanceira.objects.filter(nome=ANTIGA, tipo="despesa").update(nome=NOVA)


class Migration(migrations.Migration):
    dependencies = [
        ("contabil", "0009_conta_deducao_neutra"),
        ("contabil", "0010_liquidacao_e_estoque"),
    ]
    operations = [migrations.RunPython(renomear_categoria, migrations.RunPython.noop)]
