"""Auditoria noturna: grava o fechamento do dia que passou (ocupação, receita pela
competência, chegadas, saídas, no-shows e saldo em aberto).

Roda no grupo diário do `rotinas` (cron do Railway, de madrugada) e fecha ONTEM.
Idempotente: dia já fechado não se refaz. `--dia AAAA-MM-DD` fecha um dia específico
(ex.: um dia em que a rotina não rodou).
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Grava o fechamento do dia (padrão: ontem) — auditoria noturna das Reservas."

    def add_arguments(self, parser):
        parser.add_argument("--dia", help="dia a fechar (AAAA-MM-DD); padrão: ontem")

    def handle(self, *args, **opcoes):
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if not modulo_ativo(Modulo.RESERVAS):
            self.stdout.write("Reservas inativo: nada a fechar.")
            return
        dia = None
        if opcoes.get("dia"):
            try:
                dia = date.fromisoformat(opcoes["dia"])
            except ValueError as erro:
                raise CommandError("Use --dia no formato AAAA-MM-DD.") from erro
        from apps.nucleo.templatetags.moeda import intcomma_brl
        from apps.reservas.services import fechar_dia

        fechamento, criado = fechar_dia(dia)
        if criado:
            self.stdout.write(
                f"Dia {fechamento.data:%d/%m/%Y} fechado: {fechamento.quartos_ocupados} "
                f"quarto(s) ocupado(s), diárias {intcomma_brl(fechamento.receita_diarias)}.")
        else:
            self.stdout.write(f"Dia {fechamento.data:%d/%m/%Y} já estava fechado.")
