"""Associa IDs anteriores ao controle de ambiente; não escreve na API externa."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.reservas.fnrh_gateway import get_gateway
from apps.reservas.models import Reserva


class Command(BaseCommand):
    help = "Confere a origem de IDs FNRH legados. Sem --aplicar, apenas verifica."

    def add_arguments(self, parser):
        parser.add_argument("--reserva", type=int, required=True)
        parser.add_argument("--origem", choices=("simulado", "serpro"), required=True)
        parser.add_argument("--aplicar", action="store_true")

    def handle(self, *args, **opcoes):
        reserva = Reserva.objects.filter(pk=opcoes["reserva"]).first()
        if not reserva or not reserva.fnrh_reserva_id or reserva.fnrh_ambiente:
            raise CommandError("Selecione uma reserva com identificador legado e sem ambiente associado.")
        gw = get_gateway()
        if opcoes["origem"] != gw.nome:
            raise CommandError("A origem declarada deve corresponder ao gateway configurado.")
        if gw.nome == "serpro":
            dados = gw._req("GET", f"/reservas/{reserva.fnrh_reserva_id}").get("reserva", {})
            if dados.get("numero_reserva") != f"VT-{reserva.pk}":
                raise CommandError("A reserva remota não corresponde à origem local. Nada foi alterado.")
        if not opcoes["aplicar"]:
            self.stdout.write("Origem conferida. Use --aplicar após confirmar que este é o ambiente correto.")
            return
        with transaction.atomic():
            atual = Reserva.objects.select_for_update().get(pk=reserva.pk)
            if atual.fnrh_ambiente or atual.fnrh_reserva_id != reserva.fnrh_reserva_id:
                raise CommandError("O registro mudou durante a conferência. Repita a verificação.")
            atual.fnrh_ambiente = gw.ambiente
            atual.fnrh_status = Reserva.SincFNRH.PENDENTE
            atual.save(update_fields=["fnrh_ambiente", "fnrh_status"])
        self.stdout.write("Origem associada; reserva permanece pendente para sincronização.")
