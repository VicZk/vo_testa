"""Roda as rotinas agendadas do sistema num processo só (serviço de cron do Railway).

Grupos:
- frequentes (a cada 10 min): expira pré-reservas e recibos do site vencidos, reenvia à
  FNRH o que ficou pendente, dispara as campanhas de e-mail agendadas e reenvia as
  confirmações do site e os e-mails do Comercial que não saíram, e reprocessa os
  webhooks do WhatsApp que falharam;
- diarias (madrugada): conversões de mídia pendentes, gasto das campanhas e o backup do
  banco para fora do Railway (se R2_* ou BACKUP_DIR estiverem definidos).

Cada tarefa roda isolada: se uma falha, o erro vai para o log e as outras seguem. Ao fim,
se alguma falhou, o comando termina com erro para o Railway marcar a execução.

Uso: manage.py rotinas [--grupo frequentes|diarias] [--so tarefa1,tarefa2]
Configuração dos serviços de cron: deploy/railway.rotinas*.json (ver README, seção 10).
"""

import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

logger = logging.getLogger(__name__)

GRUPOS = {
    "frequentes": [
        "expirar_reservas",
        "expirar_recibos_site",
        "enviar_fnrh_pendentes",
        "enviar_campanhas_email",
        "reenviar_confirmacoes_site",
        "reenviar_emails_pendentes",
        "reprocessar_webhooks_whatsapp",
    ],
    "diarias": [
        "enviar_conversoes_pendentes",
        "sincronizar_gastos_midia",
        "backup_banco",
    ],
}


class Command(BaseCommand):
    help = "Roda as rotinas agendadas (expirações, reenvios, campanhas) de um grupo."

    def add_arguments(self, parser):
        parser.add_argument("--grupo", choices=sorted(GRUPOS), default="frequentes")
        parser.add_argument(
            "--so", default="",
            help="Roda só estas tarefas do grupo (separadas por vírgula).")

    def handle(self, *args, **options):
        tarefas = GRUPOS[options["grupo"]]
        if options["so"]:
            pedidas = [t.strip() for t in options["so"].split(",") if t.strip()]
            desconhecidas = sorted(set(pedidas) - set(tarefas))
            if desconhecidas:
                raise CommandError(
                    f"Fora do grupo {options['grupo']}: {', '.join(desconhecidas)}.")
            tarefas = pedidas

        falhas = []
        for tarefa in tarefas:
            inicio = time.monotonic()
            try:
                call_command(tarefa, stdout=self.stdout, stderr=self.stderr)
            except Exception:
                logger.exception("Rotina %s falhou", tarefa)
                falhas.append(tarefa)
                # Uma queda do banco deixa a conexão inutilizável: fecha só essa, para a
                # próxima tarefa reconectar. Dentro de transação (ex.: testes) não mexe.
                for conexao in connections.all(initialized_only=True):
                    if not conexao.in_atomic_block:
                        conexao.close_if_unusable_or_obsolete()
            else:
                logger.info("Rotina %s concluída em %.1fs", tarefa, time.monotonic() - inicio)

        if falhas:
            raise CommandError(f"Rotinas com falha: {', '.join(falhas)} (detalhes no log).")
        self.stdout.write(self.style.SUCCESS(
            f"{len(tarefas)} rotina(s) do grupo {options['grupo']} concluída(s)."))
