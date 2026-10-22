"""Roda as rotinas agendadas do sistema num processo só (serviço de cron do Railway).

Grupos:
- frequentes (a cada 10 min): expira pré-reservas e recibos do site vencidos, reenvia à
  FNRH o que ficou pendente, dispara as campanhas de e-mail agendadas e reenvia as
  confirmações do site e os e-mails do Comercial que não saíram, e reprocessa os
  webhooks do WhatsApp que falharam; gera arrumações após o horário local configurado;
- diarias (madrugada): o no-show automático (se ligado na Tabela de Preços) e o
  fechamento do dia, conversões de mídia pendentes, gasto das campanhas, o backup do
  banco para fora do Railway (se R2_* ou BACKUP_DIR estiverem definidos), a purga da
  trilha e a cópia do Kit de contingência por e-mail (se
  KIT_CONTINGENCIA_EMAILS estiver definido).

Cada tarefa roda isolada: se uma falha, o erro vai para o log e as outras seguem. Ao fim,
se alguma falhou, o comando termina com erro para o Railway marcar a execução.

Monitor ("dead man's switch"): com ROTINAS_MONITOR_<GRUPO> definida (URL de um check do
Healthchecks.io ou compatível), o grupo avisa o começo (`/start`), o fim e a falha
(`/fail`, com o nome das tarefas). Se o cron parar de rodar, travar ou falhar, quem
alerta é o monitor — o Railway só pinta a execução de vermelho e ninguém fica sabendo.

Uso: manage.py rotinas [--grupo frequentes|diarias] [--so tarefa1,tarefa2]
Configuração dos serviços de cron: deploy/railway.rotinas*.json (ver README, seção 10).
"""

import logging
import time
import uuid
from urllib import request as urlrequest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

logger = logging.getLogger(__name__)

GRUPOS = {
    "frequentes": [
        "expirar_reservas",
        "expirar_recibos_site",
        "enviar_fnrh_pendentes",
        "gerar_arrumacoes",  # respeita o horário local e a configuração da governança
        "enviar_campanhas_email",
        "reenviar_confirmacoes_site",
        "reenviar_emails_pendentes",
        "reprocessar_webhooks_whatsapp",
    ],
    "diarias": [
        "marcar_no_shows",  # no-show automático (se ligado) antes de fechar o dia
        "fechar_dia",  # o backup do dia já leva o fechamento
        "enviar_conversoes_pendentes",
        "sincronizar_gastos_midia",
        "backup_banco",
        "purgar_trilha",
        "enviar_kit_contingencia",  # a folha do dia no celular de quem decide
    ],
}


def _avisar_monitor(grupo, execucao, sinal="", relatorio=""):
    """Avisa o monitor do grupo (`settings.ROTINAS_MONITOR`): `sinal` "start", "" (fim
    ok) ou "fail". O relatório vai no corpo (nomes das tarefas e tipo do erro — nada de
    dado de hóspede). Sem URL não faz nada; monitor fora do ar nunca derruba a rotina."""
    url = (getattr(settings, "ROTINAS_MONITOR", {}) or {}).get(grupo, "")
    if not url.startswith(("https://", "http://")):
        return
    alvo = url.rstrip("/") + (f"/{sinal}" if sinal else "") + f"?rid={execucao}"
    req = urlrequest.Request(alvo, data=relatorio.encode("utf-8")[:10_000], method="POST",
                             headers={"Content-Type": "text/plain; charset=utf-8"})
    try:
        with urlrequest.urlopen(req, timeout=10):
            pass
    except Exception:  # noqa: BLE001 — o monitor avisa; a rotina segue
        logger.warning("Monitor das rotinas não respondeu (grupo %s, sinal %s).",
                       grupo, sinal or "fim", exc_info=True)


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

        # O monitor acompanha o grupo inteiro: rodar só algumas (`--so`, à mão) não conta
        # como a execução do cron.
        monitorar = not options["so"]
        execucao = uuid.uuid4()
        if monitorar:
            _avisar_monitor(options["grupo"], execucao, "start")

        falhas, relatorio = [], []
        for tarefa in tarefas:
            inicio = time.monotonic()
            try:
                call_command(tarefa, stdout=self.stdout, stderr=self.stderr)
            except Exception as erro:
                logger.exception("Rotina %s falhou", tarefa)
                falhas.append(tarefa)
                relatorio.append(f"{tarefa}: FALHOU ({type(erro).__name__})")
                # Uma queda do banco deixa a conexão inutilizável: fecha só essa, para a
                # próxima tarefa reconectar. Dentro de transação (ex.: testes) não mexe.
                for conexao in connections.all(initialized_only=True):
                    if not conexao.in_atomic_block:
                        conexao.close_if_unusable_or_obsolete()
            else:
                duracao = time.monotonic() - inicio
                logger.info("Rotina %s concluída em %.1fs", tarefa, duracao)
                relatorio.append(f"{tarefa}: ok em {duracao:.1f}s")

        if monitorar:
            _avisar_monitor(options["grupo"], execucao, "fail" if falhas else "",
                            "\n".join(relatorio))
        if falhas:
            raise CommandError(f"Rotinas com falha: {', '.join(falhas)} (detalhes no log).")
        self.stdout.write(self.style.SUCCESS(
            f"{len(tarefas)} rotina(s) do grupo {options['grupo']} concluída(s)."))
