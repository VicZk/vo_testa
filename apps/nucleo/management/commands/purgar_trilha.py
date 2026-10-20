"""Apaga da trilha de auditoria o que passou do prazo de retenção (LGPD).

A trilha é append-only no dia a dia; a única saída é esta, pela política de retenção:
TRILHA_RETENCAO_DIAS (0 = guardar para sempre, o padrão). Deixa um registro da própria
purga (quantos, até quando). Rode no cron diário (grupo "diarias" do `rotinas`).
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Apaga registros da trilha de auditoria mais antigos que TRILHA_RETENCAO_DIAS."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=None,
                            help="Sobrepõe TRILHA_RETENCAO_DIAS nesta execução.")

    def handle(self, *args, **opcoes):
        from apps.nucleo.models import TrilhaAuditoria

        dias = opcoes["dias"] if opcoes["dias"] is not None else getattr(
            settings, "TRILHA_RETENCAO_DIAS", 0)
        if not dias or dias <= 0:
            self.stdout.write("Retenção desligada (TRILHA_RETENCAO_DIAS=0): nada apagado.")
            return
        limite = timezone.now() - timedelta(days=dias)
        apagados, _ = TrilhaAuditoria.objects.filter(criado_em__lt=limite).delete()
        if apagados:
            TrilhaAuditoria.objects.create(
                usuario=None, acao="purga_trilha", alvo="TrilhaAuditoria", alvo_id="-",
                detalhe={"apagados": apagados, "antes_de": limite.date().isoformat(),
                         "retencao_dias": dias},
            )
        self.stdout.write(f"{apagados} registro(s) da trilha anteriores a "
                          f"{limite:%d/%m/%Y} apagado(s).")
