from django.db import migrations, models
from django.db.models import F


def marcar_existentes_como_enviadas(apps, schema_editor):
    # As reservas anteriores a este campo já tiveram a confirmação disparada na hora;
    # sem isto, o primeiro `reenviar_confirmacoes_site` mandaria o e-mail de novo.
    Reserva = apps.get_model("core", "Reserva")
    Reserva.objects.filter(confirmacao_enviada_em__isnull=True).update(
        confirmacao_enviada_em=F("criado_em"))


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_vitrinequarto"),
    ]

    operations = [
        migrations.AddField(
            model_name="reserva",
            name="confirmacao_enviada_em",
            field=models.DateTimeField(
                blank=True, editable=False, null=True, verbose_name="Confirmação enviada em"),
        ),
        migrations.RunPython(marcar_existentes_como_enviadas, migrations.RunPython.noop),
    ]
