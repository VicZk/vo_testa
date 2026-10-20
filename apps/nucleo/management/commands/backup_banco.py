"""Cópia do banco para fora do Railway (complementa os backups do próprio Railway).

Gera o dump e guarda:
- no Cloudflare R2 (o mesmo bucket da mídia, prefixo `backups/`), se as variáveis R2_*
  estiverem definidas;
- senão, em BACKUP_DIR (pasta local), se a variável estiver definida.
Sem nenhum dos dois, `--destino auto` (padrão) só avisa e não faz nada: um arquivo no
disco do container do Railway se perde no próximo deploy.

Formato: `pg_dump --format=custom` quando o pg_dump existe e aceita a versão do
servidor; senão `dumpdata` de todos os modelos (JSON compactado), que restaura num banco
migrado. Restauração:
  - .dump:    pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" arquivo.dump
  - .json.gz: python manage.py migrate && python manage.py loaddata arquivo.json.gz

Uso: manage.py backup_banco [--destino auto|local|r2] [--formato auto|pgdump|json]
                            [--manter-dias 30]
Roda no grupo "diarias" do `rotinas`.
"""

import gzip
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

PREFIXO_R2 = "backups/"
# Tabelas sem valor de recuperação (recriadas sozinhas) ficam fora do dumpdata.
EXCLUIR_DO_JSON = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]


def _r2_configurado() -> bool:
    return bool(getattr(settings, "USE_R2", False))


def _cliente_r2():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _dump_pg(destino: Path) -> bool:
    """pg_dump no formato custom. False se não houver pg_dump ou se ele recusar o
    servidor (versão do cliente mais antiga que a do Postgres)."""
    executavel = shutil.which("pg_dump")
    if not executavel:
        return False
    cfg = connection.settings_dict
    env = {**os.environ, "PGPASSWORD": cfg.get("PASSWORD") or ""}
    comando = [
        executavel, "--format=custom", "--no-owner", "--file", str(destino),
        "--host", cfg.get("HOST") or "localhost", "--port", str(cfg.get("PORT") or 5432),
        "--username", cfg.get("USER") or "", cfg["NAME"],
    ]
    resultado = subprocess.run(comando, env=env, capture_output=True, text=True)
    if resultado.returncode != 0:
        logger.warning("pg_dump falhou (%s); usando dumpdata.", resultado.stderr.strip()[:300])
        return False
    return True


def _dump_json(destino: Path) -> None:
    with gzip.open(destino, "wt", encoding="utf-8") as saida:
        call_command(
            "dumpdata", "--natural-foreign", "--natural-primary",
            *[arg for app in EXCLUIR_DO_JSON for arg in ("--exclude", app)],
            stdout=saida,
        )


class Command(BaseCommand):
    help = "Gera um backup do banco e guarda no R2 ou em BACKUP_DIR."

    def add_arguments(self, parser):
        parser.add_argument("--destino", choices=["auto", "local", "r2"], default="auto")
        parser.add_argument("--formato", choices=["auto", "pgdump", "json"], default="auto")
        parser.add_argument("--manter-dias", type=int, default=30,
                            help="Apaga backups mais antigos que isto no mesmo destino.")

    def handle(self, *args, **options):
        destino = self._escolher_destino(options["destino"])
        if destino is None:
            self.stdout.write(
                "Backup não feito: defina as variáveis R2_* ou BACKUP_DIR "
                "(o disco do container do Railway não guarda arquivos entre deploys).")
            return

        carimbo = timezone.localtime().strftime("%Y%m%d-%H%M%S")
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = self._gerar(Path(pasta), carimbo, options["formato"])
            tamanho = arquivo.stat().st_size
            if destino == "r2":
                local = self._enviar_r2(arquivo, options["manter_dias"])
            else:
                local = self._guardar_local(arquivo, options["manter_dias"])
        self.stdout.write(self.style.SUCCESS(
            f"Backup {arquivo.name} ({tamanho / 1024:.0f} KB) guardado em {local}."))

    def _escolher_destino(self, pedido):
        if pedido == "r2":
            if not _r2_configurado():
                raise CommandError("R2 não configurado (variáveis R2_*).")
            return "r2"
        if pedido == "local":
            return "local"
        if _r2_configurado():
            return "r2"
        if os.environ.get("BACKUP_DIR"):
            return "local"
        return None

    def _gerar(self, pasta: Path, carimbo: str, formato: str) -> Path:
        if formato in ("auto", "pgdump"):
            arquivo = pasta / f"crm-{carimbo}.dump"
            if _dump_pg(arquivo):
                return arquivo
            if formato == "pgdump":
                raise CommandError("pg_dump indisponível ou incompatível com o servidor.")
        arquivo = pasta / f"crm-{carimbo}.json.gz"
        _dump_json(arquivo)
        return arquivo

    def _guardar_local(self, arquivo: Path, manter_dias: int) -> str:
        pasta = Path(os.environ.get("BACKUP_DIR") or settings.BASE_DIR / "backups")
        pasta.mkdir(parents=True, exist_ok=True)
        shutil.copy2(arquivo, pasta / arquivo.name)
        limite = timezone.now().timestamp() - manter_dias * 86400
        for antigo in pasta.glob("crm-*"):
            if antigo.stat().st_mtime < limite:
                antigo.unlink()
        return str(pasta / arquivo.name)

    def _enviar_r2(self, arquivo: Path, manter_dias: int) -> str:
        cliente = _cliente_r2()
        chave = f"{PREFIXO_R2}{timezone.localtime():%Y/%m}/{arquivo.name}"
        cliente.upload_file(str(arquivo), settings.R2_BUCKET, chave)
        limite = timezone.now() - timedelta(days=manter_dias)
        antigos = []
        paginas = cliente.get_paginator("list_objects_v2").paginate(
            Bucket=settings.R2_BUCKET, Prefix=PREFIXO_R2)
        for pagina in paginas:
            antigos += [{"Key": o["Key"]} for o in pagina.get("Contents", [])
                        if o["LastModified"] < limite]
        for inicio in range(0, len(antigos), 1000):
            cliente.delete_objects(Bucket=settings.R2_BUCKET,
                                   Delete={"Objects": antigos[inicio:inicio + 1000]})
        return f"r2://{settings.R2_BUCKET}/{chave}"
