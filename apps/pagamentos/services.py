"""
Regras de Pagamentos Online. Cria cobranças no gateway, processa a confirmação
(webhook) de forma idempotente e, quando a cobrança é sinal de reserva, confirma a
reserva (via reservas.services). Estorno pelo gateway. Tudo auditado por eventos.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.validadores import decimal_valido, identificador_valido

from .gateways import ResultadoIncerto, get_gateway
from .models import Cobranca, EventoPagamento

# Finalidades expostas para outros módulos (evita importar o model lá fora).
FINALIDADE_SINAL = Cobranca.Finalidade.SINAL
FINALIDADE_SALDO = Cobranca.Finalidade.SALDO
FINALIDADE_AVULSO = Cobranca.Finalidade.AVULSO


def criar_cobranca(operador, *, valor, metodo, descricao, finalidade=Cobranca.Finalidade.AVULSO,
                   pagador=None, reserva_id=None, grupo_id=None, parcelas=1):
    """Cria a cobrança e a registra no provedor.

    A chamada ao provedor fica fora de transação: a cobrança é gravada pendente antes, e
    o retorno é gravado depois. Um provedor lento não segura conexão nem travas do banco,
    e se o processo cair no meio a cobrança local existe para conferir com o provedor.
    Se o provedor recusar, a cobrança fica cancelada com o erro no histórico.
    (Chamada de dentro de outra transação, os blocos viram savepoints dela.)"""
    valor = decimal_valido(valor, minimo=Decimal("0.01"))
    parcelas = identificador_valido(parcelas, nome="Parcelas")
    if metodo not in Cobranca.Metodo.values or finalidade not in Cobranca.Finalidade.values or parcelas > 12:
        raise ValidationError("Método, finalidade ou parcelamento inválido.")
    if not descricao:
        raise ValidationError("Descreva a cobrança.")
    direto = metodo == Cobranca.Metodo.PIX and getattr(settings, "PIX_DIRETO", False)
    gw = None if direto else get_gateway()
    with transaction.atomic():
        cobranca = Cobranca.objects.create(
            valor=valor, metodo=metodo, parcelas=int(parcelas or 1),
            descricao=descricao, finalidade=finalidade, pagador=pagador,
            reserva_id=reserva_id or None, grupo_id=grupo_id or None, criado_por=operador,
            gateway=GATEWAY_PIX_DIRETO if direto else gw.nome,
            gateway_ambiente="manual" if direto else gw.ambiente,
        )
    try:
        # Pix direto (fora do PSP): gera o BR Code localmente; cartão/boleto seguem no gateway.
        if direto:
            dados = _pix_direto(cobranca)
        else:
            dados = gw.criar_cobranca(cobranca)
    except Exception as erro:
        with transaction.atomic():
            incerto = isinstance(erro, ResultadoIncerto) or not isinstance(erro, ValidationError)
            cobranca.status = Cobranca.Status.PENDENTE if incerto else Cobranca.Status.CANCELADO
            cobranca.conciliacao_pendente = incerto
            cobranca.save(update_fields=["status", "conciliacao_pendente"])
            EventoPagamento.objects.create(
                cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK if incerto else EventoPagamento.Tipo.CANCELADA, origem="sistema",
                detalhe={"erro": " ".join(erro.messages)[:500] if isinstance(erro, ValidationError) else "Resposta não confirmada pelo provedor.", "conciliar": incerto},
            )
        raise
    with transaction.atomic():
        for campo in ("gateway", "gateway_id", "pix_copia_cola", "expira_em", "payload"):
            if campo in dados:
                setattr(cobranca, campo, dados[campo])
        cobranca.save()
        EventoPagamento.objects.create(cobranca=cobranca, tipo="criada",
                                       origem="sistema", detalhe={"gateway": cobranca.gateway})
    return cobranca


GATEWAY_PIX_DIRETO = "pix_direto"


def _pix_direto(cobranca):
    """Monta a cobrança Pix pela chave da pousada (sem PSP). Confirmação é manual."""
    from .pix_br import montar_br_code
    try:
        codigo = montar_br_code(
            chave=getattr(settings, "PIX_CHAVE", ""),
            nome=getattr(settings, "PIX_RECEBEDOR_NOME", "POUSADA VO TESTA"),
            cidade=getattr(settings, "PIX_RECEBEDOR_CIDADE", "ITA"),
            valor=cobranca.valor,
            txid=f"VT{cobranca.pk}",
        )
    except ValueError as erro:
        raise ValidationError(
            f"Pix direto ligado, mas a chave não está configurada: {erro} "
            "Defina PIX_CHAVE no .env (ou desligue PIX_DIRETO)."
        )
    return {
        "gateway": GATEWAY_PIX_DIRETO,
        "gateway_id": f"VT{cobranca.pk}",
        "pix_copia_cola": codigo,
        "expira_em": timezone.now() + timezone.timedelta(hours=24),
        "payload": {"pix_direto": True, "confirmacao": "manual"},
    }


def pix_direto_ativo() -> bool:
    return bool(getattr(settings, "PIX_DIRETO", False))


@transaction.atomic
def confirmar_pagamento(cobranca, usuario=None, origem="webhook"):
    """Confirmação (idempotente) — o webhook do gateway chama por aqui."""
    from apps.nucleo.sistema import travar
    cobranca = travar(cobranca)  # S-M3: lock da linha evita confirmação/efeito duplicado (TOCTOU)
    if cobranca.status == Cobranca.Status.PAGO:
        return cobranca  # idempotência: já processado
    if cobranca.status not in (Cobranca.Status.PENDENTE,):
        raise ValidationError("Cobrança não está pendente.")
    cobranca.status = Cobranca.Status.PAGO
    cobranca.conciliacao_pendente = False
    cobranca.pago_em = timezone.now()
    cobranca.save(update_fields=["status", "pago_em", "conciliacao_pendente"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="paga", origem=origem)
    _creditar_na_reserva(cobranca)

    # Sinal pago → confirma a reserva (ou o grupo inteiro), se Reservas ativo.
    if cobranca.finalidade == Cobranca.Finalidade.SINAL and modulo_ativo(Modulo.RESERVAS):
        if cobranca.reserva_id:
            from apps.reservas.services import confirmar_reserva
            confirmar_reserva(cobranca.reserva_id, usuario or cobranca.criado_por)
            _sincronizar_recibo_site(cobranca)
        elif cobranca.grupo_id:
            from apps.reservas.services import confirmar_grupo
            confirmar_grupo(cobranca.grupo_id, usuario or cobranca.criado_por)

    # Avisa quem escuta (ex.: Comercial ganha a oportunidade do sinal pago).
    # `emitir` (send_robust + log): um receiver que falhe NUNCA pode desfazer a
    # confirmação do pagamento (o dinheiro já foi capturado no gateway).
    from apps.nucleo.sinais import emitir

    from .signals import pagamento_confirmado
    emitir(pagamento_confirmado, sender=Cobranca, cobranca=cobranca,
           usuario=usuario or cobranca.criado_por)
    return cobranca


def cobrancas_da_reserva(reserva_id):
    """Interface pública para Reservas: as cobranças vinculadas à reserva, mais nova
    primeiro (o painel financeiro do detalhe lista e soma as pendentes)."""
    return list(Cobranca.objects.filter(reserva_id=reserva_id).order_by("-criado_em"))


def _creditar_na_reserva(cobranca):
    """O dinheiro entrou pelo gateway, não pela gaveta: vira crédito na reserva (ou no
    folio do grupo), senão a conta cobra de novo no check-out. Idempotente."""
    if (cobranca.reserva_id or cobranca.grupo_id) and modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import registrar_pagamento_online
        registrar_pagamento_online(
            cobranca_id=cobranca.pk, valor=cobranca.valor,
            descricao=f"{cobranca.get_metodo_display()} online, cobrança #{cobranca.pk}",
            reserva_id=cobranca.reserva_id, grupo_id=cobranca.grupo_id,
        )


@transaction.atomic
def vincular_reserva(cobranca, reserva_id):
    """Amarra à reserva uma cobrança criada antes dela existir (o sinal pago sobre um
    lead do Comercial). Se já está paga, o valor vira crédito na reserva agora.
    Interface pública para quem cria a reserva depois do pagamento."""
    from apps.nucleo.sistema import travar
    cobranca = travar(cobranca)
    if cobranca.reserva_id != reserva_id:
        cobranca.reserva_id = reserva_id
        cobranca.save(update_fields=["reserva_id"])
    if cobranca.status == Cobranca.Status.PAGO:
        _creditar_na_reserva(cobranca)
    return cobranca


def _sincronizar_recibo_site(cobranca):
    """Atualiza o recibo do canal (site.Reserva) quando o sinal CRM é pago."""
    try:
        from apps.site.models import Reserva as SiteReserva
    except Exception:
        return
    qs = SiteReserva.objects.filter(
        crm_reserva_id=cobranca.reserva_id, status="aguardando",
    )
    for recibo in qs:
        recibo.status = "confirmada"
        if not recibo.pagamento_id:
            recibo.pagamento_id = str(cobranca.token)
        recibo.expira_em = None
        recibo.save(update_fields=["status", "pagamento_id", "expira_em", "atualizado_em"])


@transaction.atomic
def estornar(cobranca, operador, *, devolucao_confirmada=False, referencia_devolucao=""):
    from apps.nucleo.sistema import travar
    cobranca = travar(cobranca)  # dois cliques em "Estornar" não devolvem duas vezes
    if cobranca.status != Cobranca.Status.PAGO:
        raise ValidationError("Só é possível estornar uma cobrança paga.")
    credito_na_reserva = (cobranca.reserva_id or cobranca.grupo_id) and modulo_ativo(Modulo.RESERVAS)
    if credito_na_reserva:
        # Confere ANTES de devolver no gateway: depois do dinheiro devolvido não dá para
        # descobrir que a conta da hospedagem já estava fechada.
        from apps.reservas.services import verificar_estorno_online
        verificar_estorno_online(cobranca.pk)
    manual = cobranca.gateway == GATEWAY_PIX_DIRETO
    if manual:
        from apps.nucleo.permissoes import eh_gerente
        referencia_devolucao = str(referencia_devolucao).strip()
        if not eh_gerente(operador):
            raise ValidationError("Somente a gerência pode registrar uma devolução manual.")
        if devolucao_confirmada is not True or not 6 <= len(referencia_devolucao) <= 100:
            raise ValidationError("Devolva o Pix no banco e informe a referência do comprovante para registrar a devolução integral.")
        resultado = {"estornado": True, "manual": True, "referencia_devolucao": referencia_devolucao}
    else:
        resultado = get_gateway(cobranca).estornar(cobranca)
    if resultado.get("estornado") is not True:
        raise ResultadoIncerto("O provedor não confirmou o estorno; o pagamento permanece registrado.")
    cobranca.status = Cobranca.Status.ESTORNADO
    cobranca.save(update_fields=["status"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="estornada",
                                   origem="operador" if manual else "gateway", detalhe=resultado)
    if credito_na_reserva:
        from apps.reservas.services import estornar_pagamento_online
        estornar_pagamento_online(cobranca_id=cobranca.pk,
                                  motivo=f"cobrança #{cobranca.pk}: devolução {'manual conferida' if manual else 'confirmada no provedor'}")
    registrar_auditoria(operador, "estorno_pagamento", cobranca,
                        {"valor": str(cobranca.valor)})
    return cobranca


@transaction.atomic
def cancelar(cobranca, operador):
    from apps.nucleo.sistema import travar

    travar(cobranca)
    if cobranca.status != Cobranca.Status.PENDENTE:
        raise ValidationError("Só cobranças pendentes podem ser canceladas.")
    if cobranca.conciliacao_pendente:
        raise ValidationError("Consulte o provedor antes de cancelar uma cobrança com resposta pendente.")
    if cobranca.gateway == "safrapay" and cobranca.gateway_id:
        info = consultar_cobranca(cobranca)
        if info.get("status_raw") not in ("Denied", "Canceled"):
            raise ValidationError("Esta cobrança ainda existe no provedor. Concilie ou cancele no provedor antes de encerrar localmente.")
    cobranca.status = Cobranca.Status.CANCELADO
    cobranca.save(update_fields=["status"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="cancelada", origem="operador")
    return cobranca


def conciliacao():
    """Resumo por status para conferência gateway × sistema."""
    from django.db.models import Count, Sum
    linhas = list(
        Cobranca.objects.values("status")
        .annotate(qtd=Count("id"), total=Sum("valor"))
        .order_by("status")
    )
    rotulos = dict(Cobranca.Status.choices)
    for linha in linhas:   # a tela mostrava o código ("pendente"), não o rótulo
        linha["rotulo"] = rotulos.get(linha["status"], linha["status"])
    return linhas


@transaction.atomic
def registrar_liquidacao(cobranca, *, valor_liquido=None, taxa=None,
                         data_liquidacao=None, id_liquidacao="", origem="webhook"):
    """Marca o dinheiro como caído na conta (liquidação bancária).

    Idempotente: rechamar com os mesmos dados não duplica. Só cobranças pagas
    liquidam. `valor_liquido`/`taxa` são o depósito real (bruto − taxa da
    adquirente); `data_liquidacao`/`id_liquidacao` amarram na linha do extrato."""
    from apps.nucleo.sistema import travar

    travar(cobranca)
    if cobranca.status != Cobranca.Status.PAGO:
        raise ValidationError("Só uma cobrança paga pode ser liquidada.")
    valor_liquido = decimal_valido(
        valor_liquido, nome="Valor líquido", maximo=cobranca.valor) if valor_liquido is not None else None
    taxa = decimal_valido(taxa, nome="Taxa", maximo=cobranca.valor) if taxa is not None else None
    if valor_liquido is not None and taxa is not None and valor_liquido + taxa != cobranca.valor:
        raise ValidationError("O valor líquido mais a taxa deve corresponder ao valor da cobrança.")
    id_liquidacao = str(id_liquidacao or "").strip()
    if len(id_liquidacao) > Cobranca._meta.get_field("id_liquidacao").max_length:
        raise ValidationError("ID do depósito: informe até 80 caracteres.")
    if valor_liquido is not None and taxa is None:
        taxa = (cobranca.valor - valor_liquido)
    if taxa is not None and valor_liquido is None:
        valor_liquido = (cobranca.valor - taxa)
    ja_liquidada = cobranca.liquidado
    # Uma notificação resumida não desfaz os valores já conferidos no extrato.
    if ja_liquidada and valor_liquido is None and taxa is None:
        valor_liquido, taxa = cobranca.valor_liquido, cobranca.taxa
    if ja_liquidada and data_liquidacao is None:
        data_liquidacao = cobranca.data_liquidacao
    cobranca.liquidado = True
    cobranca.valor_liquido = valor_liquido
    cobranca.taxa = taxa
    cobranca.data_liquidacao = data_liquidacao
    cobranca.id_liquidacao = id_liquidacao or cobranca.id_liquidacao
    cobranca.save(update_fields=[
        "liquidado", "valor_liquido", "taxa", "data_liquidacao", "id_liquidacao",
    ])
    if not ja_liquidada:
        EventoPagamento.objects.create(
            cobranca=cobranca, tipo=EventoPagamento.Tipo.LIQUIDADA, origem=origem,
            detalhe={
                "valor_liquido": str(valor_liquido) if valor_liquido is not None else None,
                "taxa": str(taxa) if taxa is not None else None,
                "data_liquidacao": data_liquidacao.isoformat() if data_liquidacao else None,
                "id_liquidacao": id_liquidacao,
            },
        )
    return cobranca


def recebimentos(*, inicio=None, fim=None, metodo="", status="", liquidacao=""):
    """Lista de cobranças para a tela de conciliação (recebimentos × banco).

    Filtra por período de pagamento, método, status e situação de liquidação;
    devolve as cobranças + totais (bruto, taxa, líquido, quantidade)."""
    from django.db.models import Count, Sum

    qs = Cobranca.objects.select_related("pagador")
    # Recebimentos pagos → filtra pela data de pagamento; senão pela de criação.
    campo_data = "pago_em__date" if status == Cobranca.Status.PAGO else "criado_em__date"
    if inicio:
        qs = qs.filter(**{f"{campo_data}__gte": inicio})
    if fim:
        qs = qs.filter(**{f"{campo_data}__lte": fim})
    if metodo:
        qs = qs.filter(metodo=metodo)
    if status:
        qs = qs.filter(status=status)
    if liquidacao == "liquidado":
        qs = qs.filter(liquidado=True)
    elif liquidacao == "a_liquidar":
        qs = qs.filter(status=Cobranca.Status.PAGO, liquidado=False)

    agg = qs.aggregate(
        qtd=Count("id"), bruto=Sum("valor"),
        taxa=Sum("taxa"), liquido=Sum("valor_liquido"),
    )
    pagas = qs.filter(status=Cobranca.Status.PAGO)
    totais = {
        "qtd": agg["qtd"] or 0,
        "bruto": agg["bruto"] or Decimal("0"),
        "taxa": agg["taxa"] or Decimal("0"),
        "liquido": agg["liquido"] or Decimal("0"),
        "recebido": pagas.aggregate(t=Sum("valor"))["t"] or Decimal("0"),
        "liquidado_qtd": pagas.filter(liquidado=True).count(),
        "a_liquidar_qtd": pagas.filter(liquidado=False).count(),
    }
    return list(qs[:300]), totais


def consultar_cobranca(cobranca):
    """Recupera também uma resposta perdida pela referência persistida antes do envio."""
    gw = get_gateway(cobranca)
    if not hasattr(gw, "consultar_status"):
        raise ValidationError("Esta cobrança não possui consulta automática ao provedor.")
    info = gw.consultar_status(cobranca)
    with transaction.atomic():
        atual = Cobranca.objects.select_for_update().get(pk=cobranca.pk)
        if atual.tentativa_cartao != cobranca.tentativa_cartao:
            raise ValidationError("A cobrança mudou durante a consulta. Consulte novamente.")
        campos = []
        if info.get("gateway_id"):
            atual.gateway_id = info["gateway_id"]
            campos.append("gateway_id")
        if info.get("status_raw") in ("Denied", "Canceled", "Captured"):
            atual.conciliacao_pendente = False
            campos.append("conciliacao_pendente")
        if campos:
            atual.save(update_fields=campos)
    return info


def autorizar_cartao_online(cobranca, card: dict, usuario=None, remote_ip="", session_id=""):
    """Autoriza o cartão digitado pelo hóspede na página pública e, se aprovado,
    confirma o pagamento. Retorna (ok: bool, mensagem: str). Nunca guarda o PAN:
    o cartão só transita para o gateway — o payload persistido é o do provedor.
    `remote_ip` = IP do hóspede (o antifraude usa)."""
    if not cobranca.pagamento_cartao:
        return False, "Esta cobrança não é de cartão."
    if cobranca.status != Cobranca.Status.PENDENTE:
        return False, "Cobrança não está pendente."
    if cobranca.vencida:
        return False, "Este link de pagamento expirou."
    try:
        gw = get_gateway(cobranca)
    except ValidationError as erro:
        return False, " ".join(erro.messages)
    if not hasattr(gw, "autorizar_cartao"):
        return False, "Gateway não suporta autorização de cartão."
    with transaction.atomic():
        atual = Cobranca.objects.select_for_update().get(pk=cobranca.pk)
        if atual.status != Cobranca.Status.PENDENTE or atual.conciliacao_pendente or atual.vencida:
            return False, "Esta cobrança está em confirmação. Consulte o resultado antes de tentar novamente."
        if atual.gateway_id and atual.gateway != "simulado" and not atual.tentativa_cartao:
            return False, "Consulte o resultado da tentativa anterior antes de enviar outro cartão."
        atual.tentativa_cartao += 1
        atual.conciliacao_pendente = True
        atual.gateway_id = ""
        atual.save(update_fields=["tentativa_cartao", "conciliacao_pendente", "gateway_id"])
        cobranca = atual
    if session_id:
        cobranca.payload = {**cobranca.payload, "session_id": session_id}
    try:
        dados = gw.autorizar_cartao(cobranca, card, remote_ip=remote_ip)
    except ValidationError as erro:
        EventoPagamento.objects.create(
            cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
            origem="cartao", detalhe={"erro": " ".join(erro.messages)},
        )
        if not isinstance(erro, ResultadoIncerto):
            Cobranca.objects.filter(pk=cobranca.pk, tentativa_cartao=cobranca.tentativa_cartao).update(conciliacao_pendente=False)
        return False, " ".join(erro.messages)
    except Exception:
        return False, "Não foi possível confirmar a resposta. Consulte a cobrança antes de tentar novamente."
    # Persiste só o retorno do gateway (sem o cartão cru).
    gid = dados.get("gateway_id")
    if gid:
        cobranca.gateway_id = gid
    payload = dict(dados.get("payload") or {})
    payload.pop("card", None)  # nunca persistir o PAN
    cobranca.payload = payload
    cobranca.save(update_fields=["gateway_id", "payload"])

    # A requisição pode ter sido aceita (HTTP 200) e a transação RECUSADA. Só confirma
    # em status inequívoco de pago; recusa/desconhecido NÃO confirma (fail-safe).
    from .gateways import status_negado, status_pago
    status_raw = dados.get("status_raw")
    if status_pago(status_raw) is True:
        confirmar_pagamento(cobranca, usuario or cobranca.criado_por, origem="cartao")
        return True, "Pagamento aprovado."
    EventoPagamento.objects.create(
        cobranca=cobranca, tipo=EventoPagamento.Tipo.WEBHOOK,
        origem="cartao", detalhe={"status_raw": status_raw, "aprovado": False},
    )
    if status_negado(status_raw):
        Cobranca.objects.filter(pk=cobranca.pk, tentativa_cartao=cobranca.tentativa_cartao).update(conciliacao_pendente=False)
        return False, "Cartão não autorizado pela operadora. Tente outro cartão."
    return False, ("Não foi possível confirmar o pagamento agora. "
                   "Se o valor foi debitado, ele será conciliado automaticamente.")
