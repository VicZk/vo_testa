"""Uma trava por dia serializa venda, configuração e entrada nas áreas comuns."""
import uuid
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.nucleo.models import receber_no_caixa, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente
from apps.nucleo.validadores import decimal_valido

from .models import DiaDayPass, PagamentoDayPass, TurnoDayPass, VisitaDayPass, VisitanteDayPass


def _dia(data):
    dia, _ = DiaDayPass.objects.get_or_create(data=data)
    return DiaDayPass.objects.select_for_update().get(pk=dia.pk)


def _uuid(chave):
    try:
        return uuid.UUID(str(chave))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Atualize o formulário e tente novamente.") from None


def ocupacao(turno):
    visitas = turno.visitas.exclude(status=VisitaDayPass.Status.CANCELADA)
    reservadas = visitas.aggregate(total=Sum("vagas"))["total"] or 0
    presentes = VisitanteDayPass.objects.filter(visita__in=visitas, entrou_em__isnull=False, saiu_em__isnull=True).count()
    return {"reservadas": reservadas, "disponiveis": max(0, turno.capacidade - reservadas), "presentes": presentes}


@transaction.atomic
def salvar_turno(turno, usuario):
    if not eh_gerente(usuario):
        raise PermissionDenied("A configuração do day pass exige gerência.")
    datas = {turno.dia_id}
    if turno.pk:
        datas.add(TurnoDayPass.objects.select_for_update().get(pk=turno.pk).dia_id)
    for data in sorted(datas):
        _dia(data)
    turno.full_clean()
    if turno.dia_id < timezone.localdate():
        raise ValidationError("Configure os turnos de hoje ou de uma data futura.")
    if turno.pk:
        anterior = TurnoDayPass.objects.get(pk=turno.pk)
        if anterior.visitas.exists() and any(getattr(anterior, c) != getattr(turno, c) for c in ("dia_id", "inicio", "fim", "contar_hospedes")):
            raise ValidationError("Este turno já tem visitantes. Preserve a data, os horários e a regra de lotação.")
    if turno.pk and turno.capacidade < ocupacao(turno)["reservadas"]:
        raise ValidationError("A lotação não pode ficar abaixo das vagas já reservadas.")
    # Turnos nunca sobrepostos: a mesma piscina não pode ter duas lotações independentes.
    if TurnoDayPass.objects.filter(dia_id=turno.dia_id, inicio__lt=turno.fim, fim__gt=turno.inicio).exclude(pk=turno.pk).exists():
        raise ValidationError("Já existe um turno nesse horário. Ajuste os horários para não se sobreporem.")
    turno.save()
    registrar_auditoria(usuario, "daypass_configurar_turno", turno, {"lotacao": turno.capacidade, "ativo": turno.ativo})
    return turno


def _nomes(valor, obrigatorio=False):
    if not isinstance(valor, (list, tuple)) or len(valor) > 200:
        raise ValidationError("Informe até 200 visitantes por grupo.")
    nomes = [str(nome).strip() for nome in valor]
    if (obrigatorio and not nomes) or any(not nome or len(nome) > 120 for nome in nomes):
        raise ValidationError("Informe o nome de cada visitante, com ao menos um adulto responsável.")
    return nomes


@transaction.atomic
def reservar(*, turno, responsavel, adultos, criancas, usuario, chave, hospedagem=None):
    # Recarrega antes de escolher o dia: uma edição concorrente pode ter mudado a data.
    turno = TurnoDayPass.objects.select_for_update().get(pk=turno.pk)
    _dia(turno.dia_id)
    chave = _uuid(chave)
    adultos, criancas = _nomes(adultos, True), _nomes(criancas)
    existente = VisitaDayPass.objects.filter(chave=chave).first()
    if existente:
        visitantes = list(existente.visitantes.values_list("nome", "crianca"))
        solicitados = [(nome, False) for nome in adultos] + [(nome, True) for nome in criancas]
        if (existente.turno_id != turno.pk or existente.responsavel_id != responsavel.pk
                or existente.hospedagem_id != getattr(hospedagem, "pk", None)
                or visitantes != solicitados):
            raise ValidationError("Esse envio já foi registrado com outros dados. Confira a visita existente antes de cadastrar outro grupo.")
        return existente
    if not turno.ativo or turno.dia_id < timezone.localdate():
        raise ValidationError("Este turno não está aberto para novas reservas.")
    if timezone.localtime() >= timezone.make_aware(datetime.combine(turno.dia_id, turno.fim)):
        raise ValidationError("O horário deste turno já terminou.")
    if responsavel.nome.strip().casefold() not in {nome.casefold() for nome in adultos}:
        raise ValidationError("Inclua o nome do responsável na lista de adultos.")
    nomes = adultos + criancas
    if len(nomes) > 200:
        raise ValidationError("Cadastre até 200 visitantes por grupo.")
    if len({n.casefold() for n in nomes}) != len(nomes):
        raise ValidationError("Há nomes repetidos na lista. Identifique cada visitante separadamente.")
    if not responsavel.ativo:
        raise ValidationError("O cadastro do responsável está inativo.")
    total = len(nomes)
    if hospedagem:
        from apps.reservas.services import reserva_por_id
        hospedagem = reserva_por_id(hospedagem.pk)
        if (hospedagem.status not in ("confirmada", "hospedada")
                or hospedagem.uh.tipo.eh_day_use
                or hospedagem.hospede_id != responsavel.pk
                or not hospedagem.checkin <= turno.dia_id <= hospedagem.checkout
                or total > hospedagem.total_hospedes):
            raise ValidationError("Confira a estadia, o titular e a quantidade de hóspedes vinculados.")
        if turno.preco_hospede is None:
            raise ValidationError("Defina o valor de acesso de hóspedes antes de registrá-los; zero significa incluso.")
        if turno.visitas.filter(hospedagem=hospedagem).exclude(status="cancelada").exists():
            raise ValidationError("Esta hospedagem já tem um grupo cadastrado no turno.")
        valor = turno.preco_hospede * total
    else:
        valor = turno.preco_adulto * len(adultos) + turno.preco_crianca * len(criancas)
    vagas = total if not hospedagem or turno.contar_hospedes else 0
    if vagas > ocupacao(turno)["disponiveis"]:
        raise ValidationError("Não há vagas suficientes neste turno para todo o grupo.")
    valor = decimal_valido(valor, nome="Total dos ingressos", minimo=Decimal("0"))
    try:
        with transaction.atomic():
            visita = VisitaDayPass.objects.create(turno=turno, responsavel=responsavel, hospedagem=hospedagem, vagas=vagas, valor_ingressos=valor, chave=chave, criado_por=usuario)
    except IntegrityError:
        if VisitaDayPass.objects.filter(chave=chave).exists():
            raise ValidationError("Esse envio já foi registrado com outros dados. Confira a visita existente.") from None
        raise
    VisitanteDayPass.objects.bulk_create([VisitanteDayPass(visita=visita, nome=n, crianca=crianca) for crianca, lista in ((False, adultos), (True, criancas)) for n in lista])
    registrar_auditoria(usuario, "daypass_reservar", visita, {"visitantes": total, "vagas": vagas, "valor": str(valor)})
    return visita


def _visita(visita):
    _dia(visita.turno.dia_id)
    return VisitaDayPass.objects.select_for_update(of=("self",)).select_related("turno", "hospedagem", "responsavel").get(pk=visita.pk)


@transaction.atomic
def receber(visita, usuario, forma, valor, chave):
    visita = _visita(visita)
    chave = _uuid(chave)
    valor = decimal_valido(valor, nome="Pagamento", minimo=Decimal("0.01"))
    anterior = PagamentoDayPass.objects.filter(chave=chave).first()
    if anterior:
        if (anterior.visita_id != visita.pk or anterior.movimento.valor != valor
                or anterior.movimento.forma_pagamento_id != forma.pk):
            raise ValidationError("Esse envio já foi registrado com outros dados. Confira o recebimento existente.")
        return anterior
    if visita.status not in (VisitaDayPass.Status.RESERVADA, VisitaDayPass.Status.EM_VISITA):
        raise ValidationError("Recebimento indisponível para visita encerrada ou cancelada.")
    if valor > visita.saldo():
        raise ValidationError("O pagamento supera o saldo dos ingressos.")
    try:
        with transaction.atomic():
            movimento = receber_no_caixa(usuario, forma, valor, f"Ingressos day pass #{visita.pk}", modulo=Modulo.RESERVAS)
            return PagamentoDayPass.objects.create(visita=visita, movimento=movimento, chave=chave)
    except IntegrityError:
        if PagamentoDayPass.objects.filter(chave=chave).exists():
            raise ValidationError("Esse envio já foi registrado com outros dados. Confira o recebimento existente.") from None
        raise


@transaction.atomic
def registrar_entrada(visitante, usuario):
    visita = _visita(visitante.visita)
    visitante = VisitanteDayPass.objects.get(pk=visitante.pk)
    if visitante.entrou_em:
        raise ValidationError("A entrada deste visitante já foi registrada.")
    if visita.status not in (VisitaDayPass.Status.RESERVADA, VisitaDayPass.Status.EM_VISITA):
        raise ValidationError("Esta visita foi encerrada ou cancelada.")
    agora = timezone.localtime()
    if agora.date() != visita.turno.dia_id or not visita.turno.inicio <= agora.time().replace(tzinfo=None) < visita.turno.fim:
        raise ValidationError("A entrada deve ocorrer na data e no horário do turno.")
    if visita.hospedagem_id and visita.hospedagem.status != "hospedada":
        raise ValidationError("Registre o check-in da hospedagem antes de liberar o acesso de hóspedes.")
    if visita.saldo() > 0:
        raise ValidationError("Receba os ingressos antes de registrar a entrada.")
    visitante.entrou_em = agora
    visitante.save(update_fields=["entrou_em"])
    visita.status = VisitaDayPass.Status.EM_VISITA
    visita.save(update_fields=["status"])
    registrar_auditoria(usuario, "daypass_entrada", visitante)


@transaction.atomic
def registrar_saida(visitante, usuario):
    visita = _visita(visitante.visita)
    visitante = VisitanteDayPass.objects.get(pk=visitante.pk)
    if not visitante.entrou_em or visitante.saiu_em:
        raise ValidationError("O visitante ainda não entrou ou já teve a saída registrada.")
    visitante.saiu_em = timezone.now()
    visitante.save(update_fields=["saiu_em"])
    registrar_auditoria(usuario, "daypass_saida", visitante)
    # A saída física é sempre registrada; o grupo só encerra após acertar o consumo.
    return visita


@transaction.atomic
def encerrar(visita, usuario):
    visita = _visita(visita)
    if visita.status != VisitaDayPass.Status.EM_VISITA:
        raise ValidationError("Somente um grupo em visita pode ser encerrado.")
    if visita.visitantes.filter(entrou_em__isnull=False, saiu_em__isnull=True).exists():
        raise ValidationError("Registre a saída de todos os visitantes presentes.")
    if visita.comandas.filter(status="aberta").exists() or visita.saldo() > 0:
        raise ValidationError("Acerte os ingressos e as comandas abertas antes de encerrar a visita.")
    visita.status = VisitaDayPass.Status.ENCERRADA
    visita.save(update_fields=["status"])
    registrar_auditoria(usuario, "daypass_encerrar", visita)


@transaction.atomic
def cancelar(visita, usuario, motivo):
    if not eh_gerente(usuario):
        raise PermissionDenied("O cancelamento exige gerência.")
    visita = _visita(visita)
    motivo = str(motivo or "").strip()
    if not 5 <= len(motivo) <= 300:
        raise ValidationError("Informe um motivo com 5 a 300 caracteres.")
    if visita.status != VisitaDayPass.Status.RESERVADA or visita.visitantes.filter(entrou_em__isnull=False).exists():
        raise ValidationError("A visita já começou ou foi encerrada. Não é possível liberar suas vagas por cancelamento.")
    if visita.total_pago() != 0:
        raise ValidationError("Devolva o valor e registre o estorno no caixa antes de cancelar a visita.")
    if visita.comandas.exclude(status="cancelada").exists():
        raise ValidationError("Resolva as comandas vinculadas antes de cancelar a visita.")
    visita.status, visita.motivo_cancelamento = VisitaDayPass.Status.CANCELADA, motivo
    visita.save(update_fields=["status", "motivo_cancelamento"])
    registrar_auditoria(usuario, "daypass_cancelar", visita, {"motivo": motivo})


def faturamento_periodo(inicio, fim):
    """Ingressos do day pass pela data do turno (competência). Interface pública para a
    camada Contábil: a visita que aconteceu vale o ingresso; a reservada vale o que já
    foi pago (quem pagou e não veio); a cancelada não entra — ela só cancela com o
    pago devolvido. O consumo do dia vai pelas comandas do Restaurante."""
    total = Decimal("0.00")
    visitas = (VisitaDayPass.objects.filter(turno__dia__data__range=(inicio, fim))
               .exclude(status=VisitaDayPass.Status.CANCELADA))
    for visita in visitas:
        if visita.status == VisitaDayPass.Status.RESERVADA:
            total += visita.total_pago()
        else:
            total += visita.valor_ingressos
    return {"ingressos": total}


@transaction.atomic
def abrir_consumo(visita, usuario, local):
    from apps.nucleo.models import modulo_ativo
    from apps.restaurante.services import abrir_comanda_daypass
    if not modulo_ativo(Modulo.RESTAURANTE) or not usuario.pode_acessar(Modulo.RESTAURANTE):
        raise PermissionDenied("O consumo exige acesso ao restaurante.")
    visita = _visita(visita)
    if visita.status != VisitaDayPass.Status.EM_VISITA or not local.ativo:
        raise ValidationError("Abra a comanda durante a visita e escolha um estoque ativo.")
    existente = visita.comandas.filter(status="aberta").first()
    if existente:
        return existente
    return abrir_comanda_daypass(usuario, local, visita)
