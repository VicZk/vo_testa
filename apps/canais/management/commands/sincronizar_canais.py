from django.core.management.base import BaseCommand, CommandError

from apps.canais.services import sincronizar


class Command(BaseCommand):
    help = "Recebe revisões e envia disponibilidade, tarifas e restrições da conexão ativa."

    def add_arguments(self, parser):
        parser.add_argument("--forcar", action="store_true", help="Reenvia o mapa completo mesmo sem mudanças.")

    def handle(self, *args, **options):
        resultado = sincronizar(forcar=options["forcar"])
        if resultado["estado"] == "falha":
            raise CommandError(resultado["erro"])
        rotulos = {"desativado": "Conexão desabilitada", "em_andamento": "Outra atualização está em andamento", "concluido": "Atualização concluída", "aguardando": "Aguardando o horário da próxima tentativa"}
        self.stdout.write(f"{rotulos[resultado['estado']]}; revisões recebidas: {resultado['recebidas']}.")
