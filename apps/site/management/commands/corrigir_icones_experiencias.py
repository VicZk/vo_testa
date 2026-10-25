from django.core.management.base import BaseCommand
from django.db import transaction

from apps.nucleo.models import registrar_auditoria
from apps.nucleo.sistema import usuario_de_sistema
from apps.site.icones_experiencias import ICONES_CORRIGIDOS
from apps.site.models import Experiencia


class Command(BaseCommand):
    help = "Corrige apenas os cinco fragmentos SVG do seed antigo; simula sem --aplicar."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true")

    def handle(self, *args, **options):
        candidatos = Experiencia.objects.filter(icone__in=ICONES_CORRIGIDOS)
        if not options["aplicar"]:
            self.stdout.write(f"Simulação: {candidatos.count()} ícone(s) a corrigir.")
            return
        with transaction.atomic():
            experiencias = list(candidatos.select_for_update().order_by("pk"))
            if experiencias:
                usuario = usuario_de_sistema("_manutencao_site", "Manutenção do site")
                for experiencia in experiencias:
                    anterior = experiencia.icone
                    experiencia.icone = ICONES_CORRIGIDOS[anterior]
                    # Uma única entrada explícita na trilha; não regrava conteúdo editorial.
                    Experiencia.objects.filter(pk=experiencia.pk).update(icone=experiencia.icone)
                    registrar_auditoria(usuario, "editar", experiencia, {
                        "alteracoes": {"icone": [anterior, experiencia.icone]},
                        "origem": "corrigir_icones_experiencias",
                    })
        self.stdout.write(self.style.SUCCESS(f"Ícones corrigidos: {len(experiencias)}."))
