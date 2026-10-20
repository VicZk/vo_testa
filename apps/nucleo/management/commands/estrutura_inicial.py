"""Cria a estrutura física da pousada num banco novo: os 4 tipos de quarto de
pernoite e as 24 unidades "Quarto 01".."Quarto 24".

Os seeds de preço e camas (`carregar_tarifas`, `configurar_camas`, `popular_camas`)
assumem que esses tipos e quartos já existem com estes nomes exatos, mas nada os
criava — só a migração do day use. Este comando fecha esse buraco para
desenvolvimento, homologação e recuperação de desastre.

Idempotente e conservador: só cria o que falta; nunca altera tipo ou quarto que já
existe (seguro rodar em produção). Mapa de quartos por tipo conforme
`reservas/management/commands/carregar_tarifas.py` e `docs/Reservas/CONFIGURACAO_QUARTOS.md`.

Uso:
    python manage.py estrutura_inicial               # só tipos e quartos
    python manage.py estrutura_inicial --completo    # + camas, tarifas e vitrine do site
"""

from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.nucleo.models import UH, TipoUH

# Tipo → (capacidade de referência, tarifa base da baixa temporada). A lotação real de
# cada quarto vem da composição de camas (`configurar_camas`); os preços finais vêm
# de `carregar_tarifas`.
TIPOS = {
    "Padrão": (3, Decimal("250.00")),
    "Intermediário": (7, Decimal("350.00")),
    "Cabana Intermediária": (8, Decimal("490.00")),
    "Cabana Hobbit": (8, Decimal("650.00")),
}

QUARTOS_POR_TIPO = {
    "Intermediário": (1, 2, 9, 15),
    "Padrão": (3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14),
    "Cabana Intermediária": (16, 17, 18, 19, 20, 21),
    "Cabana Hobbit": (22, 23, 24),
}

QUARTOS_PCD = {4, 14}


class Command(BaseCommand):
    help = "Cria os tipos de quarto de pernoite e os 24 quartos (só o que faltar)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--completo", action="store_true",
            help="Depois da estrutura, roda configurar_camas, carregar_tarifas e "
                 "sincronizar_vitrine.",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            tipos_novos, quartos_novos = self._criar_estrutura()
        self.stdout.write(self.style.SUCCESS(
            f"Tipos criados: {tipos_novos} · quartos criados: {quartos_novos} · "
            f"quartos de pernoite no banco: "
            f"{UH.objects.filter(tipo__nome__in=TIPOS).count()}"
        ))
        if options["completo"]:
            for comando in ("configurar_camas", "carregar_tarifas", "sincronizar_vitrine"):
                self.stdout.write(f"→ {comando}")
                call_command(comando, stdout=self.stdout, stderr=self.stderr)

    def _criar_estrutura(self):
        tipos_novos = quartos_novos = 0
        tipos = {}
        for nome, (capacidade, tarifa) in TIPOS.items():
            tipo, criado = TipoUH.objects.get_or_create(
                nome=nome,
                defaults={
                    "capacidade": capacidade,
                    "tarifa_base": tarifa,
                    "modalidade": TipoUH.Modalidade.HOSPEDAGEM,
                },
            )
            tipos[nome] = tipo
            tipos_novos += criado
        for nome_tipo, numeros in QUARTOS_POR_TIPO.items():
            for n in numeros:
                _, criado = UH.objects.get_or_create(
                    numero=f"Quarto {n:02d}",
                    defaults={"tipo": tipos[nome_tipo], "pcd": n in QUARTOS_PCD},
                )
                quartos_novos += criado
        return tipos_novos, quartos_novos
