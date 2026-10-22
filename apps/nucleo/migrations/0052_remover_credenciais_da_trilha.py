"""Remove apenas valores de credenciais; preserva eventos e autoria da trilha."""
from django.db import migrations


def sanear(apps, schema_editor):
    trilha = apps.get_model("nucleo", "TrilhaAuditoria")
    campos = {
        "password", "senha", "secret", "segredo", "mfa_secret", "mfa_backup_codes",
        "backup_codes", "token", "access_token", "refresh_token", "api_key",
        "client_secret", "authorization",
    }

    def limpar(valor):
        if isinstance(valor, dict):
            saida = {}
            for chave, item in valor.items():
                nome = str(chave).casefold().replace("-", "_")
                sensivel = nome in campos or nome.endswith(
                    ("_secret", "_password", "_token", "_api_key")
                )
                saida[chave] = "•••" if sensivel else limpar(item)
            return saida
        if isinstance(valor, list):
            return [limpar(item) for item in valor]
        return valor

    qs = trilha.objects.using(schema_editor.connection.alias)
    for registro in qs.only("pk", "detalhe").iterator(chunk_size=500):
        seguro = limpar(registro.detalhe)
        if seguro != registro.detalhe:
            qs.filter(pk=registro.pk).update(detalhe=seguro)


class Migration(migrations.Migration):
    dependencies = [("nucleo", "0051_revisar_textos_da_interface")]
    # Segredos removidos não podem ser reconstruídos no rollback.
    operations = [migrations.RunPython(sanear, migrations.RunPython.noop)]
