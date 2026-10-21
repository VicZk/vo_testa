"""No-show automático da auditoria da madrugada (Reservas).

Reserva confirmada cuja entrada passou há N noite(s) sem check-in vira "não
compareceu" e o quarto volta à venda. N vem da Tabela de Preços ("No-show
automático"); desligado (padrão), não faz nada — a recepção decide pela Auditoria.
Roda no grupo diário do `rotinas`, antes do fechamento do dia. Idempotente.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Marca o não comparecimento das reservas confirmadas sem check-in (se ligado)."

    def handle(self, *args, **opcoes):
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if not modulo_ativo(Modulo.RESERVAS):
            self.stdout.write("Reservas inativo: nada a marcar.")
            return
        from apps.reservas.services import configuracao_reservas, marcar_no_shows_vencidos

        if not configuracao_reservas().no_show_automatico_noites:
            self.stdout.write("No-show automático desligado: a recepção decide pela Auditoria.")
            return
        marcadas = marcar_no_shows_vencidos()
        for r in marcadas:
            self.stdout.write(f"No-show: reserva #{r.pk} ({r.uh.numero}, entrada {r.checkin:%d/%m}).")
        self.stdout.write(f"{len(marcadas)} não comparecimento(s) marcado(s).")
