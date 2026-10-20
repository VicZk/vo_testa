"""Sinais entre módulos sem deixar um receptor derrubar quem emitiu.

Regra: a operação de origem (check-out, troca de quarto, faxina concluída, reparo
concluído) é a fonte de verdade e não pode ser desfeita porque um módulo ouvinte
falhou. Por isso:

- quem emite usa `emitir(sinal, ...)` (send_robust + log das falhas);
- todo receptor entre módulos usa `@receptor_isolado`, que roda o corpo num
  savepoint próprio. No PostgreSQL um erro de banco dentro de uma transação aborta
  a transação inteira; o savepoint contém o estrago só no receptor.

A falha fica no log (logger "apps.nucleo.sinais") para alguém agir à mão.
"""

import functools
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def emitir(sinal, sender, **kwargs):
    """Envia o sinal a todos os receptores; falhas são registradas e não propagam."""
    respostas = sinal.send_robust(sender=sender, **kwargs)
    for receptor, resultado in respostas:
        if isinstance(resultado, Exception):
            logger.error(
                "Receptor %s falhou ao tratar o sinal %s",
                getattr(receptor, "__qualname__", receptor), sinal,
                exc_info=(type(resultado), resultado, resultado.__traceback__),
            )
    return respostas


def receptor_isolado(func):
    """Decorator de receptor: roda num savepoint e nunca levanta para o emissor."""

    @functools.wraps(func)
    def envoltorio(*args, **kwargs):
        try:
            with transaction.atomic():
                return func(*args, **kwargs)
        except Exception:
            logger.exception(
                "Receptor %s falhou; a operação de origem seguiu normalmente.",
                func.__qualname__,
            )
            return None

    return envoltorio
