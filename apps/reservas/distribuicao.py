"""Distribuição usa o mesmo estoque físico, preço e travas das reservas diretas.

Chamadores externos entram pelas funções públicas em services.py. Nenhum acesso
ao provedor ocorre aqui e nenhuma importação registra recebimento de dinheiro.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.nucleo.models import UH, Hospede, Pessoa, TipoUH, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.sistema import travar_quartos

from . import colchoes, precos, services
from .models import ContaHospedagem, Reserva


def previa(mapeamentos, inicio, fim):
    """Uma leitura por coleção; sem consulta por quarto/noite nem reserva de vaga.

    Cada categoria recebe estoque por noite e uma tarifa para a ocupação indicada.
    Diferenças de preço entre unidades exigem separar o mapeamento. Colchões
    compartilhados não viram vagas independentes em múltiplos canais.
    """
    if not 1 <= (fim-inicio).days <= 500:
        raise ValidationError("Escolha um período de uma a 500 noites.")
    ids = {pk for m in mapeamentos for pk in m["unidades"]}
    uhs = {u.pk: u for u in UH.objects.filter(pk__in=ids).select_related("tipo", "config").prefetch_related("posicoes_cama")}
    ocupadas = list(services.reservas_ativas_qs().filter(
        uh_id__in=ids, checkin__lt=fim, checkout__gt=inicio).values("uh_id", "checkin", "checkout"))
    bloqueios = []
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao.services import bloqueios as bloqueios_manutencao
        bloqueios = bloqueios_manutencao(inicio, fim-timedelta(days=1))
    regras = services.restricoes_no_periodo(inicio, fim)
    linhas, pendencias = [], []
    with services.precos_em_lote():
        services.precarregar_classificacoes(inicio, fim)
        services.precarregar_tarifas_unidade(list(uhs.values()))
        for mapa in mapeamentos:
            unidades = [uhs[pk] for pk in mapa["unidades"] if pk in uhs]
            aptas = []
            for uh in unidades:
                if uh.status != UH.Status.ATIVA or uh.tipo.modalidade != TipoUH.Modalidade.HOSPEDAGEM:
                    continue
                if not colchoes.configurado(uh):
                    pendencias.append(f"{mapa['nome']}: confira as camas das unidades mapeadas.")
                    continue
                arranjo = colchoes.sugerir_arranjo(uh, mapa["ocupacao"], 0)
                if colchoes.cabe_no_quarto(uh, arranjo.casais, arranjo.solteiros, arranjo.usa_sofa_cama, mapa["ocupacao"], 0):
                    pendencias.append(f"{mapa['nome']}: a ocupação da tarifa não cabe em todas as unidades.")
                    continue
                if colchoes.consumo_extra(uh, arranjo.casais, arranjo.solteiros):
                    pendencias.append(f"{mapa['nome']}: a ocupação depende de colchões compartilhados; reduza a ocupação publicada.")
                    continue
                aptas.append(uh)
            for n in range((fim-inicio).days):
                dia = inicio+timedelta(days=n)
                valores = set()
                livres = 0
                minimo, chegada, saida = 1, False, False
                for uh in aptas:
                    valores.add(precos.cotacao(uh=uh, checkin=dia, checkout=dia+timedelta(days=1), adultos=mapa["ocupacao"])["total"])
                    aplicaveis = [r for r in regras if r.vale_para(uh=uh) and r.inicio <= dia <= r.fim]
                    minimo = max([minimo] + [r.min_noites or 1 for r in aplicaveis])
                    chegada |= any(r.fechado_chegada for r in aplicaveis)
                    saida |= any(r.fechado_saida for r in aplicaveis)
                    bloqueada = any(r.parar_vendas for r in aplicaveis)
                    bloqueada |= any(r["uh_id"] == uh.pk and r["checkin"] <= dia < r["checkout"] for r in ocupadas)
                    bloqueada |= any(b["uh_id"] == uh.pk and b["inicio"] <= dia and (b["fim"] is None or dia <= b["fim"]) for b in bloqueios)
                    livres += not bloqueada
                preco = next(iter(valores)) if len(valores) == 1 else None
                problema = ""
                if not aptas:
                    problema = "Nenhuma unidade apta para esta ocupação."
                elif preco is None:
                    problema = "As unidades têm tarifas diferentes; separe as categorias."
                elif preco <= 0:
                    problema = "Cadastre uma tarifa maior que zero."
                if problema:
                    pendencias.append(f"{mapa['nome']}: {problema}")
                quantidade = max(0, min(mapa["limite"], livres - mapa["margem"]))
                if problema or not mapa["ativo"] or len(aptas) != len(mapa["unidades"]):
                    quantidade = 0
                linhas.append({"mapeamento": mapa["id"], "nome": mapa["nome"], "data": dia.isoformat(),
                    "livres": livres, "disponibilidade": quantidade, "tarifa": f"{preco:.2f}" if preco is not None and preco > 0 else None,
                    "min_noites": minimo, "fechado_chegada": chegada, "fechado_saida": saida,
                    "parar_vendas": quantidade == 0, "pendencia": problema})
    return {"linhas": linhas, "pendencias": sorted(set(pendencias))}


_CAMPOS_ESTADO = ("uh_id", "hospede_id", "checkin", "checkout", "adultos", "criancas_0_5", "criancas_6_15",
    "valor_diaria", "valor_hospedagem", "cobra_iss", "cobra_taxa_turismo", "faturamento", "titular_id",
    "status", "casais", "solteiros", "usa_sofa_cama", "usa_berco", "grupo_id")


def estado(reserva):
    return {chave: str(getattr(reserva, chave)) for chave in _CAMPOS_ESTADO}


def _composicao(quarto):
    if len(quarto["idades"]) != quarto["criancas"]:
        raise ValidationError("Confira as idades de todas as crianças antes de aplicar a reserva.")
    return {"adultos": quarto["adultos"] + sum(i >= 16 for i in quarto["idades"]),
        "criancas_0_5": quarto["bebes"] + sum(i <= 5 for i in quarto["idades"]),
        "criancas_6_15": sum(6 <= i <= 15 for i in quarto["idades"])}


def _exigir_alteravel(reserva, esperado):
    if reserva.status not in (Reserva.Status.PRE_RESERVA, Reserva.Status.CONFIRMADA):
        raise ValidationError("A reserva já foi iniciada ou encerrada. A recepção precisa conferir a alteração.")
    if esperado and estado(reserva) != esperado:
        raise ValidationError("A reserva foi alterada no PMS. Confira as duas versões antes de continuar.")
    if reserva.grupo_id or reserva.adiantamentos.exists() or ContaHospedagem.objects.filter(reserva=reserva).exists():
        raise ValidationError("Há conta, grupo ou recebimento vinculado. Confira a alteração com a recepção.")
    if modulo_ativo(Modulo.PAGAMENTOS):
        from apps.pagamentos.services import cobrancas_da_reserva
        if cobrancas_da_reserva(reserva.pk):
            raise ValidationError("Há cobrança vinculada. Confira o financeiro antes de alterar a reserva.")


@transaction.atomic
def aplicar(dados, destinos, vinculos, usuario):
    """Aplica o conjunto inteiro ou nenhum quarto; valor bruto não vira pagamento.

    `destinos` mapeia a identidade estável do quarto a IDs físicos autorizados.
    `vinculos` contém {reserva_id, estado} da última aplicação para impedir que uma
    revisão sobrescreva uma intervenção posterior da recepção.
    """
    ids_existentes = [v["reserva_id"] for v in vinculos.values()]
    existentes = {r.pk: r for r in Reserva.objects.select_for_update().filter(pk__in=ids_existentes).order_by("pk")}
    if len(existentes) != len(ids_existentes):
        raise ValidationError("Uma reserva vinculada não foi encontrada. Confira os vínculos.")
    for vinculo in vinculos.values():
        atual = existentes[vinculo["reserva_id"]]
        if dados["status"] != "cancelled" or atual.status != Reserva.Status.CANCELADA:
            _exigir_alteravel(atual, vinculo.get("estado"))
    if dados["status"] == "cancelled":
        travar_quartos(*(r.uh for r in existentes.values()))
        for reserva in existentes.values():
            if reserva.status != Reserva.Status.CANCELADA:
                reserva.cancelar(usuario, "Cancelamento recebido do canal de origem.")
        return {chave: {"reserva_id": v["reserva_id"], "estado": estado(existentes[v["reserva_id"]])} for chave, v in vinculos.items()}
    if dados["moeda"] != "BRL" or dados["cobrador"] != "property":
        raise ValidationError("Moeda diferente de real ou recebimento pela OTA exige conferência do faturamento.")
    if dados["extras_pendentes"] or any(q["extras_pendentes"] for q in dados["quartos"]):
        raise ValidationError("Há serviços ou tributos informados pelo canal. Confira a composição antes de vincular.")
    chaves = [q["identificador"] for q in dados["quartos"]]
    if not all(chaves) or len(set(chaves)) != len(chaves):
        raise ValidationError("O canal não identificou cada quarto de forma única. Faça a conferência manual.")
    if vinculos and set(vinculos) != set(chaves):
        raise ValidationError("A quantidade ou a identificação dos quartos mudou. Confira os vínculos manualmente.")
    if sum((Decimal(q["valor"]) for q in dados["quartos"]), Decimal("0")) != Decimal(dados["valor"]):
        raise ValidationError("A soma dos quartos difere do total da reserva. Confira os valores no canal.")
    cliente = dados["cliente"]
    if len(cliente["nome"]) > 150 or len(cliente["telefone"]) > 20:
        raise ValidationError("Os dados do titular precisam ser ajustados ao cadastro do PMS.")
    candidatos = {pk for ids in destinos.values() for pk in ids} | {r.uh_id for r in existentes.values()}
    quartos = {u.pk: u for u in UH.objects.filter(pk__in=candidatos).select_related("tipo", "config").prefetch_related("posicoes_cama")}
    travar_quartos(*quartos.values())
    pessoa = next(iter(existentes.values())).hospede if existentes else None
    if pessoa and (pessoa.nome != cliente["nome"] or pessoa.email != cliente["email"] or pessoa.telefone != cliente["telefone"]):
        raise ValidationError("O titular ou seu contato mudou. Confira o cadastro antes de aplicar a revisão.")
    resultado = {}
    for recebido in dados["quartos"]:
        chave = recebido["identificador"]
        inicio, fim = date.fromisoformat(recebido["checkin"]), date.fromisoformat(recebido["checkout"])
        if inicio < timezone.localdate():
            raise ValidationError("Reserva com chegada passada exige conferência da recepção.")
        valor = Decimal(recebido["valor"])
        if valor <= 0:
            raise ValidationError("Confira o valor da hospedagem antes de aplicar a reserva.")
        diarias = recebido["diarias"]
        if diarias and (len(diarias) != (fim-inicio).days or sum(map(Decimal, diarias.values())) != valor):
            raise ValidationError("O detalhamento das diárias não coincide com o valor do quarto.")
        composicao = _composicao(recebido)
        criancas = composicao["criancas_0_5"] + composicao["criancas_6_15"]
        reserva = existentes[vinculos[chave]["reserva_id"]] if chave in vinculos else None
        ids = [reserva.uh_id] if reserva else sorted(destinos.get(chave, []))
        uh = None
        for pk in ids:
            candidata = quartos.get(pk)
            if not candidata or pk not in destinos.get(chave, []):
                continue
            if candidata.status != UH.Status.ATIVA or candidata.tipo.modalidade != TipoUH.Modalidade.HOSPEDAGEM:
                continue
            if services.reservas_no_periodo(candidata, inicio, fim).exclude(pk=reserva.pk if reserva else None).exists():
                continue
            if candidata.pk in services._uhs_bloqueio_manutencao(inicio, fim):
                continue
            if services.restricoes_da_estadia(inicio, fim, uh=candidata):
                continue
            if not colchoes.configurado(candidata):
                continue
            arr = colchoes.sugerir_arranjo(candidata, composicao["adultos"], criancas)
            conf = services.conferir_arranjo(candidata, casais=arr.casais, solteiros=arr.solteiros,
                usa_sofa_cama=arr.usa_sofa_cama, adultos=composicao["adultos"], criancas=criancas,
                checkin=inicio, checkout=fim, excluir_id=reserva.pk if reserva else None)
            if conf["erros"]:
                continue
            uh = candidata
            break
        if uh is None:
            raise ValidationError("Nenhum quarto mapeado está livre e apto durante toda a estadia. Confira a disponibilidade.")
        media = (valor / (fim-inicio).days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if pessoa is None:
            # Endereços de OTA podem ser compartilhados. Não sobrescrever um hóspede
            # existente nem atribuir consentimento comercial a uma reserva externa.
            pessoa = Pessoa.objects.create(**cliente, aceita_email=False, aceita_whatsapp=False)
            Hospede.objects.create(pessoa=pessoa)
        if reserva is None:
            reserva = services.criar_prereserva(uh=uh, checkin=inicio, checkout=fim, hospede=pessoa,
                usuario=usuario, canal=Reserva.Canal.OTA, valor_diaria=media,
                cobra_iss=False, cobra_taxa_turismo=False, respeitar_restricoes=True, **composicao)
            reserva.valor_hospedagem = valor
            reserva.save(update_fields=["valor_hospedagem"])
            reserva.confirmar(usuario)
        else:
            arranjo = services._travar_e_resolver_arranjo(uh, casais=None, solteiros=None, usa_sofa_cama=None,
                adultos=composicao["adultos"], criancas=criancas, checkin=inicio, checkout=fim, excluir_id=reserva.pk)
            if reserva.usa_berco:
                services.conferir_berco(inicio, fim, excluir_id=reserva.pk)
            for campo, novo in {"checkin": inicio, "checkout": fim, "valor_diaria": media,
                    "valor_hospedagem": valor, "cobra_iss": False, "cobra_taxa_turismo": False,
                    "criancas": criancas, **composicao, **arranjo}.items():
                setattr(reserva, campo, novo)
            reserva.clean()
            try:
                with transaction.atomic():
                    reserva.save()
            except IntegrityError:
                raise ValidationError("A disponibilidade mudou durante a conferência. Atualize e tente novamente.") from None
        registrar_auditoria(usuario, "reserva_canal_aplicada", reserva, {"origem": "canal", "revisao": dados["revisao_id"]})
        resultado[chave] = {"reserva_id": reserva.pk, "estado": estado(reserva)}
    return resultado


@transaction.atomic
def conferir_vinculos(dados, ids, usuario, *, anteriores=(), destinos=None):
    """Conferência manual só fecha a pendência com reservas reais correspondentes."""
    quartos = dados["quartos"]
    chaves = [q["identificador"] or f"manual-{indice}" for indice, q in enumerate(quartos)]
    if len(set(chaves)) != len(chaves):
        raise ValidationError("A revisão repete a identificação de um quarto. Solicite a correção no canal.")
    if len(ids) != len(quartos) or len(set(ids)) != len(ids):
        raise ValidationError("Informe uma reserva do PMS para cada quarto recebido, na mesma ordem.")
    reservas = {r.pk: r for r in Reserva.objects.select_for_update().filter(pk__in=set(ids) | set(anteriores)).order_by("pk")}
    for pk in set(anteriores)-set(ids):
        if pk not in reservas or reservas[pk].status != Reserva.Status.CANCELADA:
            raise ValidationError("Cancele no PMS os quartos retirados pelo canal antes de concluir a conferência.")
    resultado = {}
    for indice, (recebido, pk) in enumerate(zip(quartos, ids, strict=True)):
        reserva = reservas.get(pk)
        if not reserva:
            raise ValidationError("Uma das reservas informadas não existe.")
        comp = _composicao(recebido)
        if (reserva.checkin.isoformat() != recebido["checkin"] or reserva.checkout.isoformat() != recebido["checkout"]
                or any(getattr(reserva, campo) != valor for campo, valor in comp.items())):
            raise ValidationError("Datas e hóspedes precisam corresponder aos dados recebidos do canal.")
        if dados["status"] == "cancelled":
            if reserva.status != Reserva.Status.CANCELADA:
                raise ValidationError("Conclua o cancelamento e a conferência financeira no PMS antes de resolver a revisão.")
        else:
            if destinos is not None and reserva.uh_id not in destinos.get(chaves[indice], []):
                raise ValidationError("O quarto do PMS precisa pertencer à categoria recebida do canal.")
            if reserva.status not in Reserva.STATUS_ATIVOS or reserva.canal != Reserva.Canal.OTA:
                raise ValidationError("Vincule uma reserva ativa do canal Sites de reserva.")
            if dados["moeda"] != "BRL" or reserva.total_previsto() != Decimal(recebido["valor"]):
                raise ValidationError("Confira a moeda e o total previsto da hospedagem antes de vincular.")
            if dados["cobrador"] == "ota" and (reserva.faturamento != Reserva.Faturamento.AGENCIA or not reserva.titular_id):
                raise ValidationError("Recebimento pela OTA exige faturamento por agência com titular definido.")
        resultado[recebido["identificador"] or f"manual-{indice}"] = {"reserva_id": pk, "estado": estado(reserva)}
        registrar_auditoria(usuario, "reserva_canal_conferida", reserva, {"revisao": dados["revisao_id"]})
    return resultado
