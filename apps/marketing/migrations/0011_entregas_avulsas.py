import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketing", "0010_versao_entregas")]

    operations = [
        migrations.AlterField(
            model_name="pecacampanha",
            name="campanha",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="pecas", to="marketing.campanha", verbose_name="campanha",
            ),
        ),
    ]
