"""Países ISO alpha-2: nomes do IBGE, consultados em 22/10/2026.

Fonte: https://servicodados.ibge.gov.br/api/v1/paises/all
Não converte nacionalidade ou país desconhecido silenciosamente em Brasil.
"""
import json
import unicodedata
from pathlib import Path

from django.core.exceptions import ValidationError

PAISES = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8-sig"))
PAISES_CHOICES = sorted(PAISES.items(), key=lambda item: item[1])


def _normalizar(valor):
    return "".join(c for c in unicodedata.normalize("NFKD", str(valor).strip().casefold())
                   if not unicodedata.combining(c))


_NOMES = {_normalizar(nome): codigo for codigo, nome in PAISES.items()}
_NOMES.update({"brasileira": "BR", "brasileiro": "BR", "brazil": "BR", "argentino": "AR",
               "uruguaia": "UY", "uruguaio": "UY", "paraguaia": "PY", "paraguaio": "PY",
               "chilena": "CL", "chileno": "CL", "italiana": "IT", "italiano": "IT",
               "portuguesa": "PT", "portugues": "PT", "americana": "US", "americano": "US",
               "estados unidos": "US", "eua": "US", "united states": "US",
               "alema": "DE", "alemao": "DE", "francesa": "FR", "frances": "FR",
               "espanhola": "ES", "espanhol": "ES", "argentina": "AR"})


def codigo_pais(valor):
    codigo = str(valor or "").strip().upper()
    codigo = codigo if codigo in PAISES else _NOMES.get(_normalizar(valor))
    if not codigo:
        raise ValidationError("Selecione o país na lista; o valor informado não foi reconhecido.")
    return codigo
