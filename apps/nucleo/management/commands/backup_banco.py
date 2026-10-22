"""Backup PostgreSQL verificado, persistente, com retenção e estado operacional.

Auto grava nos destinos configurados (local e/ou R2). Não ter destino ou pg_dump
compatível é falha. JSON só é gerado por escolha explícita, para uso auxiliar.
"""
import gzip
import hashlib
import json
import os
import re
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

from apps.nucleo.models import EstadoBackup

PREFIXO_R2 = "backups/"
EXCLUIR_DO_JSON = ["contenttypes", "auth.permission", "sessions", "admin.logentry"]
NOME_BACKUP = re.compile(r"crm-[0-9-]+\.(?:dump|json\.gz)\Z")


def _r2_configurado():
    chaves = ("BACKUP_R2_BUCKET", "BACKUP_R2_ENDPOINT_URL", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY")
    return bool(all(getattr(settings, k, "") for k in chaves) and settings.BACKUP_R2_PRIVADO
        and settings.BACKUP_R2_BUCKET != getattr(settings, "R2_BUCKET", ""))


def _cliente_r2():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=settings.BACKUP_R2_ENDPOINT_URL,
        aws_access_key_id=settings.BACKUP_R2_ACCESS_KEY_ID, aws_secret_access_key=settings.BACKUP_R2_SECRET_ACCESS_KEY,
        region_name="auto", config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 2}))


def _dump_pg(destino):
    executavel, restaurador = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not executavel or not restaurador:
        return False
    cfg = connection.settings_dict
    env = {**os.environ, "PGPASSWORD": cfg.get("PASSWORD") or ""}
    comando = [executavel, "--format=custom", "--no-owner", "--file", str(destino),
        "--host", cfg.get("HOST") or "localhost", "--port", str(cfg.get("PORT") or 5432),
        "--username", cfg.get("USER") or "", cfg["NAME"]]
    for chave, variavel in (("sslmode", "PGSSLMODE"), ("sslrootcert", "PGSSLROOTCERT")):
        if cfg.get("OPTIONS", {}).get(chave):
            env[variavel] = str(cfg["OPTIONS"][chave])
    try:
        resultado = subprocess.run(comando, env=env, capture_output=True, timeout=300)
        if resultado.returncode or not destino.is_file() or not destino.stat().st_size:
            return False
        indice = subprocess.run([restaurador, "--list", str(destino)], capture_output=True, timeout=60)
        return indice.returncode == 0 and bool(indice.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return False


def _dump_json(destino):
    with gzip.open(destino, "wt", encoding="utf-8") as saida:
        call_command("dumpdata", "--natural-foreign", "--natural-primary",
            *[arg for app in EXCLUIR_DO_JSON for arg in ("--exclude", app)], stdout=saida)


def metadados(arquivo):
    with arquivo.open("rb") as entrada:
        sha = hashlib.file_digest(entrada, "sha256").hexdigest()
    return {"versao": 1, "arquivo": arquivo.name, "sha256": sha, "bytes": arquivo.stat().st_size,
        "criado_em": timezone.now().isoformat(), "formato": "postgresql-custom" if arquivo.suffix == ".dump" else "django-json-gzip"}


class Command(BaseCommand):
    help = "Grava e verifica backup nos destinos persistentes configurados."

    def add_arguments(self, parser):
        parser.add_argument("--destino", choices=["auto", "local", "r2"], default="auto")
        parser.add_argument("--formato", choices=["auto", "pgdump", "json"], default="auto")
        parser.add_argument("--manter-dias", type=int, default=30)

    def handle(self, *args, **options):
        if not 1 <= options["manter_dias"] <= 3650:
            raise CommandError("Retenção deve ficar entre 1 e 3650 dias.")
        # Trava de sessão: dois cron/manual concorrentes não disputam retenção/estado.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(271025)")
            if not cursor.fetchone()[0]:
                raise CommandError("Um backup já está em execução.")
        estado, _ = EstadoBackup.objects.get_or_create(pk=1)
        estado.ultima_tentativa, estado.situacao, estado.erro = timezone.now(), "executando", ""
        estado.save()
        try:
            destinos = self._escolher_destinos(options["destino"])
            carimbo = timezone.localtime().strftime("%Y%m%d-%H%M%S-%f")
            with tempfile.TemporaryDirectory() as pasta:
                arquivo = self._gerar(Path(pasta), carimbo, options["formato"])
                meta = metadados(arquivo)
                if not meta["bytes"]:
                    raise CommandError("O arquivo de backup está vazio.")
                for destino in destinos:
                    if destino == "local":
                        self._guardar_local(arquivo, meta, options["manter_dias"])
                    else:
                        self._enviar_r2(arquivo, meta, options["manter_dias"])
            estado.ultimo_sucesso, estado.situacao = timezone.now(), "concluido"
            estado.destinos, estado.arquivo = destinos, meta["arquivo"]
            estado.sha256, estado.tamanho = meta["sha256"], meta["bytes"]
            estado.save()
            self.stdout.write(self.style.SUCCESS(f"Backup {meta['arquivo']} verificado em {', '.join(destinos)}; SHA-256 {meta['sha256']}."))
        except Exception as erro:
            estado.situacao = "falha"
            estado.erro = str(erro)[:200] if isinstance(erro, CommandError) else f"Falha de backup ({type(erro).__name__}); confira o destino configurado."
            estado.save(update_fields=["situacao", "erro"])
            raise CommandError(estado.erro) from erro
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(271025)")

    def _escolher_destinos(self, pedido):
        local, r2 = bool(os.environ.get("BACKUP_DIR")), _r2_configurado()
        parcial = any(getattr(settings,k,"") for k in ("BACKUP_R2_BUCKET", "BACKUP_R2_ENDPOINT_URL", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY"))
        if pedido == "auto" and parcial and not r2:
            raise CommandError("A configuração da cópia externa está incompleta ou usa um bucket de mídia pública. Revise BACKUP_R2_*.")
        if pedido == "local" and not local:
            raise CommandError("BACKUP_DIR deve apontar para um volume persistente.")
        if pedido == "r2" and not r2:
            raise CommandError("Configure um bucket privado de backup, separado da mídia pública, e as credenciais BACKUP_R2_*.")
        destinos = (["local"] if local else []) + (["r2"] if r2 else []) if pedido == "auto" else [pedido]
        if not destinos:
            raise CommandError("Backup não feito: configure BACKUP_DIR persistente e/ou BACKUP_R2_* privado.")
        return destinos

    def _gerar(self, pasta, carimbo, formato):
        arquivo = pasta / f"crm-{carimbo}.dump"
        if formato != "json":
            if not _dump_pg(arquivo):
                raise CommandError("pg_dump/pg_restore indisponível, incompatível ou backup sem índice válido.")
            return arquivo
        arquivo = pasta / f"crm-{carimbo}.json.gz"
        _dump_json(arquivo)
        return arquivo

    def _guardar_local(self, arquivo, meta, manter_dias):
        pasta = Path(os.environ["BACKUP_DIR"])
        pasta.mkdir(mode=0o700, parents=True, exist_ok=True)
        final = pasta / arquivo.name
        temporario = pasta / (arquivo.name + ".part")
        try:
            with arquivo.open("rb") as entrada, temporario.open("wb") as saida:
                os.chmod(temporario, 0o600)
                shutil.copyfileobj(entrada, saida)
                saida.flush()
                os.fsync(saida.fileno())
            if metadados(temporario)["sha256"] != meta["sha256"]:
                raise CommandError("O hash da cópia local não confere.")
            temporario.replace(final)
            manifesto = pasta / ("metadata-" + arquivo.name + ".json")
            rascunho = manifesto.with_suffix(".part")
            rascunho.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            os.chmod(rascunho, 0o600)
            rascunho.replace(manifesto)
        finally:
            temporario.unlink(missing_ok=True)
        limite = timezone.now().timestamp() - manter_dias * 86400
        for antigo in pasta.glob("crm-*"):
            if antigo.is_file() and not antigo.is_symlink() and NOME_BACKUP.fullmatch(antigo.name) and antigo.stat().st_mtime < limite:
                antigo.unlink()
                (pasta / ("metadata-"+antigo.name+".json")).unlink(missing_ok=True)
        return str(final)

    def _enviar_r2(self, arquivo, meta, manter_dias):
        cliente = _cliente_r2()
        chave = f"{PREFIXO_R2}{timezone.localtime():%Y/%m}/{arquivo.name}"
        cliente.upload_file(str(arquivo), settings.BACKUP_R2_BUCKET, chave, ExtraArgs={"Metadata": {"sha256": meta["sha256"]}})
        recebido = cliente.head_object(Bucket=settings.BACKUP_R2_BUCKET, Key=chave)
        if recebido.get("ContentLength") != meta["bytes"] or recebido.get("Metadata", {}).get("sha256") != meta["sha256"]:
            raise CommandError("O objeto recebido no R2 não confere com o backup gerado.")
        cliente.put_object(Bucket=settings.BACKUP_R2_BUCKET, Key=chave+".metadata.json", Body=json.dumps(meta).encode(), ContentType="application/json")
        limite = timezone.now()-timedelta(days=manter_dias)
        paginas = cliente.get_paginator("list_objects_v2").paginate(Bucket=settings.BACKUP_R2_BUCKET, Prefix=PREFIXO_R2)
        antigos=[]
        for pagina in paginas:
            antigos.extend({"Key": o["Key"]} for o in pagina.get("Contents", [])
                if o["LastModified"] < limite and NOME_BACKUP.fullmatch(o["Key"].rsplit("/",1)[-1].removesuffix(".metadata.json")))
        for inicio in range(0,len(antigos),1000):
            cliente.delete_objects(Bucket=settings.BACKUP_R2_BUCKET, Delete={"Objects": antigos[inicio:inicio+1000]})
        return f"r2://{settings.BACKUP_R2_BUCKET}/{chave}"
