"""Configuração das cópias de comparação da VPS: a do projeto mais o acesso livre.

O compose de cada cópia monta esta pasta em /opt/comparador (no PYTHONPATH) e aponta
DJANGO_SETTINGS_MODULE=settings_vps. Ver o README.md desta pasta.
"""

import os
from pathlib import Path

from config.settings import *  # noqa: F403

# Por último: roda depois da sessão e do usuário (para entrar) e devolve a resposta
# antes de as mensagens serem gravadas nela (para o aviso da tela mais próxima).
MIDDLEWARE = [*MIDDLEWARE, "acesso_livre.AcessoLivreMiddleware"]  # noqa: F405

# Só na cópia atualizada: a aba "Comparativo" (comparativo.py). O item do menu vem do nova.js.
if os.environ.get("COMPARATIVO_VERSOES") == "1":
    ROOT_URLCONF = "urls_vps"
    TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], Path(__file__).resolve().parent / "templates"]  # noqa: F405
