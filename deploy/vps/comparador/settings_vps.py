"""Configuração das cópias de comparação da VPS: a do projeto mais o acesso livre.

O compose de cada cópia monta esta pasta em /opt/comparador (no PYTHONPATH) e aponta
DJANGO_SETTINGS_MODULE=settings_vps. Ver o README.md desta pasta.
"""

from config.settings import *  # noqa: F403

# Por último: roda depois da sessão e do usuário (para entrar) e devolve a resposta
# antes de as mensagens serem gravadas nela (para o aviso da tela mais próxima).
MIDDLEWARE = [*MIDDLEWARE, "acesso_livre.AcessoLivreMiddleware"]  # noqa: F405
