from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketing", "0006_alter_itemchecklist_arquivo")]
    operations = [
        migrations.AddField(
            model_name="campanha", name="chave_criacao",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
    ]
