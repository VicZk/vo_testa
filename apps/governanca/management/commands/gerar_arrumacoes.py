"""Rotina da manhã: uma arrumação para cada quarto ocupado em que o hóspede continua.

Roda no grupo frequente do `rotinas`, respeitando o horário local configurado. Idempotente: rodar de
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
        from apps.governanca.services import executar_rotina_diaria

        resultado = executar_rotina_diaria()
        self.stdout.write(f"{resultado['geradas']} arrumação(ões) gerada(s); {resultado['atribuidas']} atribuída(s).")
