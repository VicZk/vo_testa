"""
A DRE em dia sozinha: capturas do mês (receita, descontos, taxa de cartão, CMV, saídas
do estoque) e os títulos das contas recorrentes. Roda no grupo `diarias` de
`manage.py rotinas` (cron da casa). Idempotente — repetir não duplica.
"""
from django.core.management.base import BaseCommand

from apps.contabil.capturas import rotina_diaria


class Command(BaseCommand):
    help = "Capturas contábeis do mês e contas recorrentes (rotina diária)."

    def handle(self, *args, **opts):
        resultado = rotina_diaria()
        meses = ", ".join(resultado["capturas"]) or "Contábil inativo, sem capturas"
        self.stdout.write(self.style.SUCCESS(
            f"Contábil: {meses}; títulos recorrentes novos: {resultado['recorrentes_criadas']}."))
