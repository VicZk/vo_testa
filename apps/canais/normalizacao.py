"""Lista explícita de campos operacionais; garantia/cartão nunca entra no CRM."""
import uuid
from datetime import UTC, date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.nucleo.validadores import decimal_valido


def _id(valor, nome, *, opcional=False):
    if opcional and not valor:
        return ""
    try:
        return str(uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(f"{nome}: identificador inválido.") from None


def _texto(valor, limite, nome, *, obrigatorio=False):
    if not isinstance(valor, str) or len(valor.strip()) > limite or (obrigatorio and not valor.strip()):
        raise ValidationError(f"{nome}: confira o conteúdo recebido.")
    return valor.strip()


def _inteiro(valor, nome, minimo=0, maximo=50):
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise ValidationError(f"{nome}: quantidade inválida.")
    return valor


def _valor(valor, nome):
    if isinstance(valor, bool) or not isinstance(valor, (str, int, Decimal)):
        raise ValidationError(f"{nome}: valor inválido.")
    return str(decimal_valido(valor, nome=nome, minimo=Decimal("0"), casas=2))


def normalizar(item, propriedade):
    if not isinstance(item, dict) or item.get("type") != "booking_revision":
        raise ValidationError("Revisão de reserva inválida.")
    a = item.get("attributes")
    if not isinstance(a, dict):
        raise ValidationError("A revisão não contém os dados da reserva.")
    revisao_id = _id(item.get("id"), "Revisão")
    if _id(a.get("id"), "Revisão") != revisao_id:
        raise ValidationError("Os identificadores da revisão não coincidem.")
    if _id(a.get("property_id"), "Estabelecimento") != str(propriedade):
        raise ValidationError("A reserva pertence a outro estabelecimento.")
    status = a.get("status")
    if status not in ("new", "modified", "cancelled"):
        raise ValidationError("O estado recebido não é reconhecido.")
    try:
        instante = parse_datetime(a.get("inserted_at", ""))
    except (ValueError, TypeError):
        instante = None
    if instante is None:
        raise ValidationError("A revisão não informa uma data de atualização válida.")
    if timezone.is_naive(instante):
        instante = instante.replace(tzinfo=UTC)
    resultado = {"revisao_id": revisao_id, "reserva_id": _id(a.get("booking_id"), "Reserva"),
        "status": status, "alterada_em": instante.isoformat(),
        "canal": _texto(a.get("ota_name", ""), 80, "Canal"),
        "codigo": _texto(a.get("ota_reservation_code", ""), 100, "Código"),
        "moeda": _texto(a.get("currency", ""), 3, "Moeda"),
        "valor": _valor(a.get("amount", "0"), "Total da reserva"),
        "cobrador": a.get("payment_collect") or "property", "quartos": [],
        "extras_pendentes": bool(a.get("services"))}
    if resultado["cobrador"] not in ("property", "ota"):
        raise ValidationError("O responsável pelo recebimento não é reconhecido.")
    cliente = a.get("customer") or {}
    if not isinstance(cliente, dict):
        raise ValidationError("Dados do titular inválidos.")
    nome = " ".join(filter(None, (
        _texto(cliente.get("name") or "", 100, "Nome"),
        _texto(cliente.get("surname") or "", 100, "Sobrenome"))))
    email = _texto(cliente.get("mail") or "", 254, "E-mail")
    if email:
        validate_email(email)
    resultado["cliente"] = {"nome": _texto(nome, 200, "Nome", obrigatorio=status != "cancelled"),
        "email": email, "telefone": _texto(cliente.get("phone") or "", 30, "Telefone")}
    quartos = a.get("rooms") or []
    if not isinstance(quartos, list) or len(quartos) > 50 or (status != "cancelled" and not quartos):
        raise ValidationError("Confira os quartos da reserva recebida.")
    for quarto in quartos:
        if not isinstance(quarto, dict):
            raise ValidationError("Quarto inválido na revisão.")
        try:
            inicio = date.fromisoformat(quarto.get("checkin_date", ""))
            fim = date.fromisoformat(quarto.get("checkout_date", ""))
        except (ValueError, TypeError):
            raise ValidationError("A reserva contém datas inválidas.") from None
        if not 1 <= (fim-inicio).days <= 365:
            raise ValidationError("A estadia deve ter entre uma e 365 noites.")
        pessoas = quarto.get("occupancy") or {}
        if not isinstance(pessoas, dict):
            raise ValidationError("Ocupação recebida inválida.")
        adultos = _inteiro(pessoas.get("adults"), "Adultos", minimo=1)
        criancas = _inteiro(pessoas.get("children", 0), "Crianças")
        bebes = _inteiro(pessoas.get("infants", 0), "Bebês")
        idades = pessoas.get("ages") or []
        if not isinstance(idades, list) or len(idades) > 50:
            raise ValidationError("Idades recebidas inválidas.")
        idades = [_inteiro(idade, "Idade", maximo=17) for idade in idades]
        identificador = quarto.get("ota_unique_id") or quarto.get("booking_room_id") or ("unico" if len(quartos) == 1 else "")
        dias = quarto.get("days") or {}
        if not isinstance(dias, dict) or len(dias) > 365:
            raise ValidationError("Detalhamento das diárias inválido.")
        diarias = {}
        for dia, valor in dias.items():
            try:
                data = date.fromisoformat(dia)
            except (ValueError, TypeError):
                raise ValidationError("A diária contém uma data inválida.") from None
            if not inicio <= data < fim:
                raise ValidationError("Há diária fora do período da hospedagem.")
            diarias[data.isoformat()] = _valor(valor, "Diária")
        resultado["quartos"].append({
            "identificador": _texto(identificador, 100, "Identificação do quarto"),
            "tipo_id": _id(quarto.get("room_type_id"), "Tipo do quarto", opcional=True),
            "tarifa_id": _id(quarto.get("rate_plan_id"), "Plano de tarifa", opcional=True),
            "checkin": inicio.isoformat(), "checkout": fim.isoformat(),
            "adultos": adultos, "criancas": criancas, "bebes": bebes, "idades": idades,
            "valor": _valor(quarto.get("amount"), "Valor do quarto"),
            "diarias": diarias,
            "extras_pendentes": bool(quarto.get("services") or quarto.get("taxes") or quarto.get("collected_taxes"))})
    return resultado
