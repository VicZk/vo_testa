from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conciliacao", "0002_lancamentoextrato_chave_importacao"),
    ]

    operations = [
        migrations.AddField(
            model_name="transacaocartao",
            name="chave_importacao",
            field=models.CharField(
                blank=True, editable=False, max_length=64, null=True,
                unique=True, verbose_name="chave de importação",
            ),
        ),
    ]
