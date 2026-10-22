"""Validadores compartilhados do núcleo (reusados por todos os módulos)."""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def decimal_valido(valor, *, nome="Valor", minimo=Decimal("0"),
                   maximo=Decimal("99999999.99"), casas=2):
    """Valida antes de calcular: rejeita NaN, infinito, expoentes e precisão excessiva."""
    texto = str(valor).strip() if valor is not None else ""
    if len(texto) > 64:
        raise ValidationError(f"{nome}: número fora do limite permitido.")
    try:
        numero = Decimal(texto)
        if not numero.is_finite() or numero < minimo or numero > maximo:
            raise InvalidOperation
        if numero.quantize(Decimal(1).scaleb(-casas)) != numero:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f"{nome}: informe um número entre {minimo} e {maximo}, com até {casas} casas decimais.")
    return numero


def identificador_valido(valor, *, nome="Registro", opcional=False):
    if opcional and valor in (None, ""):
        return None
    texto = str(valor)
    if not re.fullmatch(r"[0-9]{1,19}", texto) or not 0 < int(texto) <= 9223372036854775807:
        raise ValidationError(f"{nome}: selecione um registro válido.")
    return int(texto)


def filtro_identificador(valor):
    """Filtros GET inválidos recebem 400 antes de alcançar o ORM."""
    from django.core.exceptions import BadRequest
    try:
        return identificador_valido(valor, opcional=True)
    except ValidationError:
        raise BadRequest("Filtro inválido: selecione um registro da lista.")

# DDDs válidos no Brasil (há buracos — ex.: 20, 23, 25, 26, 29, 30, 36, 39, 40...).
DDDS_VALIDOS = frozenset({
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55,
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79,
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99,
})


def validar_telefone_br(valor, *, aceitar_fixo=False) -> str:
    """Valida e normaliza um telefone brasileiro. Devolve formatado — celular
    `(DD) 9XXXX-XXXX`; fixo `(DD) XXXX-XXXX` (só se `aceitar_fixo=True`).

    Levanta ValidationError com mensagem clara se faltar dígito / DDD inválido.
    Por padrão exige CELULAR (11 dígitos + 9º dígito 9) — é o caso das LPs/WhatsApp.
    """
    digitos = re.sub(r"\D", "", valor or "")
    # tolera o código do país (55) na frente
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]

    erro_cel = ("Telefone incompleto. Informe DDD + número de celular "
                "(11 dígitos, ex.: (49) 99999-9999).")
    erro_geral = ("Telefone incompleto. Informe DDD + número "
                  "(celular com 11 dígitos ou fixo com 10).")

    if len(digitos) == 11 and digitos[2] == "9":
        ddd, num = digitos[:2], digitos[2:]
        if int(ddd) not in DDDS_VALIDOS:
            raise ValidationError(f"DDD {ddd} inválido.")
        return f"({ddd}) {num[:5]}-{num[5:]}"

    if aceitar_fixo and len(digitos) == 10:
        ddd, num = digitos[:2], digitos[2:]
        if int(ddd) not in DDDS_VALIDOS:
            raise ValidationError(f"DDD {ddd} inválido.")
        if num[0] not in "2345":  # fixo começa em 2–5; 9 = celular incompleto
            raise ValidationError(erro_geral)
        return f"({ddd}) {num[:4]}-{num[4:]}"

    raise ValidationError(erro_geral if aceitar_fixo else erro_cel)
