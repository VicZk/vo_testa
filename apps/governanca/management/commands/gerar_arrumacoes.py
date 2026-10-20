"""Rotina da manhã: uma arrumação para cada quarto ocupado em que o hóspede continua.

Roda no grupo diário do `rotinas` (cron do Railway, de manhã). Idempotente: rodar de
novo no mesmo dia não duplica tarefa.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Gera a arrumação diária dos quartos ocupados (Governança)."

    def handle(self, *args, **opcoes):
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if not modulo_ativo(Modulo.GOVERNANCA):
            self.stdout.write("Governança inativa: nada a gerar.")
            return
        from apps.governanca.services import gerar_arrumacoes_do_dia

        criadas = gerar_arrumacoes_do_dia()
        self.stdout.write(f"{criadas} arrumação(ões) gerada(s).")
