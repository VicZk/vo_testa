"""Cria a tabela do cache compartilhado (DatabaseCache) quando o projeto não usa Redis.

O `createcachetable` só age sobre os caches do tipo DatabaseCache em `CACHES` e não faz
nada se a tabela já existe, então roda sem risco em qualquer ambiente: com Redis ou nos
testes (cache em memória) é um no-op.
"""

from django.core.management import call_command
from django.db import migrations


def criar_tabela_de_cache(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0045_configuracaoreservas_iss_aliquota_and_more"),
    ]

    operations = [
        migrations.RunPython(criar_tabela_de_cache, migrations.RunPython.noop),
    ]
