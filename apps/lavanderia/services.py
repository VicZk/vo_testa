"""
Regras do módulo Lavanderia. Interface pública para as views e integrações.
Cobrança reusa `receber_no_caixa` (núcleo) e `reservas.lancar_na_conta` (folio),
sempre com natureza SERVIÇO. A rouparia é um livro-razão por estado do enxoval.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, receber_no_caixa, registrar_auditoria
from apps.nucleo.validadores import decimal_valido

from .icones import ICONES
from .models import (
    ItemEnxoval,
    ItemOrdemLavanderia,
    MovimentoEnxoval,
    OrdemLavanderia,
    ServicoLavanderia,
)

ZERO = Decimal("0.00")
# O teto é o da COLUNA (`quantidade`: max_digits=10, decimal_places=3 → 9.999.999,999):
# acima dele o banco respondia com `numeric field overflow` (página 500) em vez de
# "informe um número", e o campo de peso é texto livre no balcão.
MAXIMO_QUANTIDADE = Decimal("9999999.999")
LIMITE_OBSERVACAO = 240
# Peças de cada item que uma faxina consome, para sugerir o alvo da rouparia de um item
# NOVO (o item já cadastrado tem o seu `por_faxina`).
POR_FAXINA_PADRAO = 3


# ───────────────────────── (a) Serviço ao hóspede ─────────────────────────

@transaction.atomic
def abrir_ordem(operador, cliente=None, rotulo="", prazo=None, conta_id=None):
    from apps.reservas.services import conta_para_pedido

    conta = conta_para_pedido(cliente=cliente, conta_id=conta_id)
    if conta:
        cliente = cliente or conta.reserva.hospede
        rotulo = rotulo or f"Quarto {conta.reserva.uh.numero}"
    rotulo = (rotulo or "").strip()
    if not (cliente or rotulo):
        raise ValidationError("Informe o hóspede/cliente ou uma identificação.")
    return OrdemLavanderia.objects.create(
        cliente=cliente, rotulo=rotulo, prazo=prazo, criado_por=operador, conta=conta,
    )


def _quantidade_do_servico(servico, quantidade, *, minimo):
    """Valida a quantidade conforme a UNIDADE do serviço.

    O granel é pesado (3,400 kg); a peça é contada. Sem a conferência da unidade,
    «0,5» numa camisa de R$ 8,00 cobrava R$ 4,00 e os contadores da fila e da cesta
    (que truncam com `int`) diziam «0 peças» — o quilo vazava para a peça.
    """
    nome = "Peso" if servico.unidade == ServicoLavanderia.Unidade.KG else "Quantidade"
    numero = decimal_valido(quantidade, nome=nome, minimo=minimo,
                            maximo=MAXIMO_QUANTIDADE, casas=3)
    if (servico.unidade == ServicoLavanderia.Unidade.PECA
            and numero != numero.to_integral_value()):
        raise ValidationError(f"{servico.nome} é cobrado por peça: informe um número inteiro.")
    return numero


@transaction.atomic
def adicionar_item(ordem, servico, quantidade, operador):
    from apps.nucleo.sistema import travar

    travar(ordem)
    if not ordem.em_producao:
        raise ValidationError("Só é possível lançar itens antes da entrega.")
    quantidade = _quantidade_do_servico(servico, quantidade, minimo=Decimal("0.001"))
    existente = ordem.itens.filter(servico=servico).first()
    total_quantidade = quantidade + (existente.quantidade if existente else 0)
    decimal_valido(total_quantidade, nome="Quantidade", minimo=Decimal("0.001"), maximo=MAXIMO_QUANTIDADE, casas=3)
    preco = decimal_valido(existente.preco_unitario if existente else servico.preco, nome="Preço do serviço")
    decimal_valido((total_quantidade * preco).quantize(Decimal("0.01")), nome="Total do item")
    if existente:
        existente.quantidade += quantidade
        existente.save(update_fields=["quantidade"])
        return existente
    return ItemOrdemLavanderia.objects.create(
        ordem=ordem, servico=servico, descricao=servico.nome,
        quantidade=quantidade, preco_unitario=preco,
        natureza=NaturezaFiscal.SERVICO,
    )


@transaction.atomic
def remover_item(item):
    from apps.nucleo.sistema import travar

    ordem = travar(item.ordem)
    if not ordem.em_producao:
        raise ValidationError("A ordem já foi entregue.")
    item = ItemOrdemLavanderia.objects.select_for_update().filter(pk=item.pk, ordem=ordem).first()
    if item is None:
        raise ValidationError("Este item já foi removido. Atualize a ordem.")
    item.delete()


@transaction.atomic
def definir_quantidade(item, quantidade, operador):
    """DEFINE a quantidade do item (não soma): é o `−`/`+` da cesta e o campo de quilo.

    Zero remove a linha. O granel aceita 3 casas (3,400 kg) e a peça só número inteiro
    (`_quantidade_do_servico`). O `operador` fica na assinatura para a trilha automática
    saber de quem é a escrita.
    """
    from apps.nucleo.sistema import travar

    ordem = travar(item.ordem)
    if not ordem.em_producao:
        raise ValidationError("Só é possível alterar itens antes da entrega.")
    item = ItemOrdemLavanderia.objects.select_for_update().filter(pk=item.pk, ordem=ordem).first()
    if item is None:
        raise ValidationError("Este item já foi removido. Atualize a ordem.")
    quantidade = _quantidade_do_servico(item.servico, quantidade, minimo=ZERO)
    if quantidade == 0:
        item.delete()
        return None
    decimal_valido((quantidade * item.preco_unitario).quantize(Decimal("0.01")),
                   nome="Total do item")
    item.quantidade = quantidade
    item.save(update_fields=["quantidade"])
    return item


@transaction.atomic
def definir_observacao(ordem, texto, operador):
    """Recado da recepção para quem lava (mancha, não passar). Sai no cupom."""
    from apps.nucleo.sistema import travar

    travar(ordem)
    if not ordem.em_producao:
        raise ValidationError("A ordem já foi encerrada.")
    ordem.observacao = (texto or "").strip()[:LIMITE_OBSERVACAO]
    ordem.save(update_fields=["observacao"])
    return ordem


# Em que campo cada passo carimba a hora. Fonte única: o service grava e a trilha lê.
CARIMBO_DO_PASSO = {
    OrdemLavanderia.Status.RECEBIDA: "recebida_em",
    OrdemLavanderia.Status.LAVANDO: "lavando_em",
    OrdemLavanderia.Status.PRONTA: "pronta_em",
    OrdemLavanderia.Status.ENTREGUE: "entregue_em",
}

# Fonte única do rótulo do botão dourado: o painel e a ordem leem daqui, para a fila e a
# tela do balcão nunca discordarem sobre qual é o próximo passo.
PROXIMOS = {
    OrdemLavanderia.Status.RECEBIDA: {
        "codigo": OrdemLavanderia.Status.LAVANDO.value,
        "rotulo": "Enviar para lavagem",
        "url_name": "lavanderia:avancar",
    },
    OrdemLavanderia.Status.LAVANDO: {
        "codigo": OrdemLavanderia.Status.PRONTA.value,
        "rotulo": "Marcar como pronta",
        "url_name": "lavanderia:avancar",
    },
    OrdemLavanderia.Status.PRONTA: {
        # Cobrar exige escolher destino, forma e desconto: o passo abre a ordem.
        "codigo": OrdemLavanderia.Status.ENTREGUE.value,
        "rotulo": "Entregar e cobrar",
        "url_name": "lavanderia:ordem",
    },
}


def proximo_passo(ordem):
    """`{"codigo", "rotulo", "url_name"}` do próximo passo, ou None se já encerrada."""
    return PROXIMOS.get(ordem.status)


@transaction.atomic
def avancar_status(ordem, esperado=None):
    """Avança um passo no fluxo recebida → lavando → pronta.

    `esperado` é o status que a tela mostrava quando o botão foi desenhado: com ele, o
    segundo clique (ou a segunda aba) falha em vez de pular dois passos de uma vez —
    sem ele, duas requisições seguidas levavam a ordem de 'recebida' a 'pronta'. Quem
    chama pela web (as duas telas) é OBRIGADO a mandar o `de`: a view recusa o POST
    sem ele, porque é justamente a página velha que pulava passo.

    Ordem sem peça lançada não anda: o que não foi contado não é cobrado, e uma ordem
    vazia chegava a 'pronta' com a cesta dizendo "Nenhuma peça lançada".

    Cada passo grava o seu carimbo (`lavando_em`, `pronta_em`), que é o que a trilha
    da ordem mostra.
    """
    from apps.nucleo.sistema import travar

    esperado = esperado or ordem.status
    travar(ordem)
    if ordem.status != esperado:
        raise ValidationError("A ordem foi alterada em outra sessão. Atualize a tela.")
    fluxo = OrdemLavanderia.FLUXO
    if ordem.status not in fluxo or ordem.status == fluxo[-1]:
        raise ValidationError("A ordem já está pronta para entrega.")
    if not ordem.itens.exists():
        raise ValidationError("Lance ao menos uma peça antes de avançar.")
    ordem.status = fluxo[fluxo.index(ordem.status) + 1]
    campos = ["status"]
    carimbo = CARIMBO_DO_PASSO.get(ordem.status)
    if carimbo:
        setattr(ordem, carimbo, timezone.now())
        campos.append(carimbo)
    ordem.save(update_fields=campos)
    return ordem


@transaction.atomic
def entregar(ordem, operador, destino, forma=None, conta_id=None, desconto=ZERO,
             confirmar=False):
    """Cobra e encerra a ordem. Só entrega o que está PRONTO.

    `confirmar=True` libera a entrega antecipada (o hóspede vai embora antes de a roupa
    ficar pronta) e deixa o rastro na trilha — é exceção, não caminho normal.

    `destino` é conferido contra as escolhas do model: qualquer outro valor caía no
    ramo do fólio e lançava na conta do hóspede por fora do gate do Reservas, gravando
    um destino que depois contava como "conta" no faturamento.
    """
    # Trava a linha p/ serializar a entrega: sem o lock, um duplo POST cobra duas vezes
    # (dois entregar() passam no `em_producao` antes de qualquer um gravar).
    from apps.nucleo.sistema import travar

    if destino not in OrdemLavanderia.Destino.values:
        raise ValidationError("Escolha como cobrar: pagamento imediato ou conta do quarto.")
    ordem = travar(ordem)
    if not ordem.em_producao:
        raise ValidationError("Esta ordem já foi encerrada.")
    antecipada = ordem.status != OrdemLavanderia.Status.PRONTA
    if antecipada and not confirmar:
        raise ValidationError("Esta ordem ainda não está pronta. Confirme a entrega antecipada.")
    if not ordem.itens.exists():
        raise ValidationError("A ordem está vazia.")
    desconto = decimal_valido(desconto or 0, nome="Desconto")
    if desconto < 0 or desconto > ordem.subtotal():
        raise ValidationError("Desconto inválido.")
    ordem.desconto = desconto
    total = ordem.total()

    if destino == OrdemLavanderia.Destino.CAIXA:
        if not forma:
            raise ValidationError("Escolha a forma de pagamento.")
        from apps.nucleo.modulos import Modulo

        ordem.movimento_caixa = receber_no_caixa(
            operador, forma, total, f"Lavanderia #{ordem.pk}", modulo=Modulo.LAVANDERIA,
        )
        ordem.forma_pagamento = forma
    else:
        from apps.reservas import services as reservas

        conta = reservas.travar_conta_aberta(conta_id or ordem.conta_id)
        if ordem.conta_id and ordem.conta_id != conta.pk:
            raise ValidationError("A ordem pertence a outra estadia. Confira o vínculo antes de cobrar.")
        ordem.conta = conta
        for item in ordem.itens.all():
            reservas.lancar_na_conta(
                conta, "servico", item.natureza,
                f"Lavanderia: {item.descricao}", item.subtotal, operador,
                quantidade=item.quantidade, preco_unitario=item.preco_unitario,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", NaturezaFiscal.SERVICO,
                "Lavanderia: desconto", desconto, operador,
            )
        ordem.conta_ref = f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}"

    etapa_antes = ordem.status
    ordem.destino = destino
    ordem.status = OrdemLavanderia.Status.ENTREGUE
    ordem.entregue_em = timezone.now()
    ordem.save()
    if desconto > 0:
        # Abater dinheiro do que o hóspede paga é ajuste: fica na trilha com quem, quanto
        # e sobre qual subtotal (a tela só oferece o campo à gerência).
        registrar_auditoria(operador, "desconto_lavanderia", ordem, {
            "desconto": str(desconto), "subtotal": str(ordem.subtotal()),
            "total": str(total), "destino": destino,
        })
    if antecipada:
        registrar_auditoria(operador, "entrega_antecipada_lavanderia", ordem, {
            "etapa": etapa_antes, "destino": destino, "total": str(total),
        })
    return ordem


@transaction.atomic
def vincular_conta(ordem, conta_id, operador):
    from apps.nucleo.sistema import travar
    from apps.reservas.services import travar_conta_aberta

    travar(ordem)
    if not ordem.em_producao:
        raise ValidationError("Só uma ordem em produção pode ser vinculada à estadia.")
    anterior = ordem.conta_id
    ordem.conta = travar_conta_aberta(conta_id)
    ordem.save(update_fields=["conta"])
    registrar_auditoria(operador, "lavanderia_vinculada", ordem,
                       {"conta_anterior": anterior, "conta": ordem.conta_id})
    return ordem


def pendencias_da_conta(conta_id):
    from django.urls import reverse

    return [{"rotulo": f"Lavanderia #{ordem.pk}", "valor": ordem.total(),
             "url": reverse("lavanderia:ordem", args=[ordem.pk])}
            for ordem in OrdemLavanderia.objects.filter(conta_id=conta_id, status__in=OrdemLavanderia.FLUXO)
            .prefetch_related("itens")]


@transaction.atomic
def cancelar_ordem(ordem, operador, motivo=""):
    from apps.nucleo.sistema import travar

    travar(ordem)
    if ordem.status == OrdemLavanderia.Status.ENTREGUE:
        raise ValidationError("Ordem entregue não pode ser cancelada (já cobrada).")
    if ordem.status == OrdemLavanderia.Status.CANCELADA:
        raise ValidationError("Ordem já cancelada.")
    ordem.status = OrdemLavanderia.Status.CANCELADA
    ordem.motivo_cancelamento = motivo or ""
    ordem.save(update_fields=["status", "motivo_cancelamento"])
    registrar_auditoria(operador, "cancelamento_lavanderia", ordem, {"motivo": motivo or ""})
    return ordem


@transaction.atomic
def salvar_servico(servico, operador, **campos):
    """Cria (`servico=None`) ou ALTERA uma linha da tabela de preços.

    Antes a tela usava `get_or_create` e respondia "Serviço salvo." sem gravar nada
    quando o nome já existia: o preço novo era descartado em silêncio. Aqui o nome
    repetido é erro e a mudança de preço fica na trilha (é o que o hóspede vai pagar).
    Campos aceitos: `nome`, `unidade`, `preco`, `icone`, `ativo`.
    """
    from apps.nucleo.sistema import travar

    if servico is not None:
        travar(servico)
    nome = (campos.get("nome") or "").strip() if "nome" in campos else None
    if servico is None and not nome:
        raise ValidationError("Informe o nome do serviço.")
    if nome is not None:
        repetidos = ServicoLavanderia.objects.filter(nome__iexact=nome)
        if servico is not None:
            repetidos = repetidos.exclude(pk=servico.pk)
        if nome and repetidos.exists():
            raise ValidationError("Já existe um serviço com esse nome.")

    unidade = campos.get("unidade") or None
    if unidade is not None and unidade not in ServicoLavanderia.Unidade.values:
        raise ValidationError("Escolha a unidade: por peça ou por quilo.")
    preco = campos.get("preco")
    if preco is not None:
        preco = decimal_valido(str(preco).replace(",", "."), nome="Preço",
                               minimo=Decimal("0.01"))
    icone = campos.get("icone")
    if icone not in (None, "") and icone not in ICONES:
        raise ValidationError("Ícone inválido. Escolha um da lista.")

    novo = servico is None
    servico = servico or ServicoLavanderia(preco=ZERO)
    preco_antes = None if novo else servico.preco
    if nome:
        servico.nome = nome
    if unidade:
        servico.unidade = unidade
    if preco is not None:
        servico.preco = preco
    if icone is not None:
        servico.icone = icone
    if campos.get("ativo") is not None:
        servico.ativo = bool(campos["ativo"])
    servico.save()
    if not novo and preco is not None and preco != preco_antes:
        registrar_auditoria(operador, "preco_lavanderia", servico,
                            {"de": str(preco_antes), "para": str(preco)})
    return servico


# ───────────────────── (a.2) Leitura do painel e da fila ─────────────────────

def _atraso(ordem, hoje):
    """Dias de atraso da ordem (0 quando no prazo) — mesma regra de `pendencias_auditoria`."""
    if ordem.prazo and ordem.prazo < hoje:
        return (hoje - ordem.prazo).days
    return 0


def painel_do_setor():
    """Os quatro números do topo da Lavanderia + a contagem de cada chip da fila.

    Dinheiro em `Decimal`, somado em Python (o total da ordem é método, como em
    `faturamento_periodo`). Atraso = prazo vencido e ordem ainda em produção.
    """
    hoje = timezone.localdate()
    ordens = (OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO)
              .prefetch_related("itens__servico"))
    contagens = {status.value: 0 for status in OrdemLavanderia.FLUXO}
    para_hoje = atrasadas = ordens_lavando = pecas_lavando = 0
    granel_lavando = Decimal("0.000")
    for ordem in ordens:
        contagens[ordem.status] += 1
        if _atraso(ordem, hoje):
            atrasadas += 1
        elif ordem.prazo == hoje:
            para_hoje += 1
        if ordem.status == OrdemLavanderia.Status.LAVANDO:
            ordens_lavando += 1
            for item in ordem.itens.all():
                if item.servico.unidade == ServicoLavanderia.Unidade.KG:
                    granel_lavando += item.quantidade
                else:
                    pecas_lavando += int(item.quantidade)
    contagens["todas"] = sum(contagens[status.value] for status in OrdemLavanderia.FLUXO)
    contagens["atrasadas"] = atrasadas
    faturado = faturamento_periodo(hoje.replace(day=1), hoje)
    return {
        "para_hoje": para_hoje,
        "atrasadas": atrasadas,
        "pecas_lavando": pecas_lavando,
        "granel_lavando": granel_lavando,
        "ordens_lavando": ordens_lavando,
        "mes_total": faturado["caixa"] + faturado["quarto"],
        "mes_caixa": faturado["caixa"],
        "mes_conta": faturado["quarto"],
        "contagens": contagens,
    }


ETAPA_ATRASADAS = "atrasadas"
ETAPAS_DA_FILA = tuple(status.value for status in OrdemLavanderia.FLUXO) + (ETAPA_ATRASADAS,)
LIMITE_ICONES_NO_CARTAO = 4


def filas_de_producao(etapa=None):
    """As três colunas da fila (Recebida, Lavando, Pronta), cada ordem já lida.

    `etapa` = um status (só aquela coluna) ou "atrasadas" (as vencidas, onde estiverem).
    Sem filtro as três colunas vêm sempre, mesmo vazias — a fila é um quadro estável;
    com filtro, coluna sem ordem não aparece.

    A ordem dentro da coluna é explícita (atrasada → prazo → mais antiga primeiro):
    o `Meta.ordering = ["-recebida_em"]` do model afundaria justamente a mais urgente.
    """
    hoje = timezone.localdate()
    consulta = (OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO)
                .select_related("cliente", "conta__reserva__uh", "conta__reserva__hospede")
                .prefetch_related("itens__servico")
                .order_by("prazo", "recebida_em", "pk"))
    colunas = {status.value: [] for status in OrdemLavanderia.FLUXO}
    if etapa in colunas:
        consulta = consulta.filter(status=etapa)

    for ordem in consulta:
        dias = _atraso(ordem, hoje)
        if etapa == ETAPA_ATRASADAS and not dias:
            continue
        ordem.atrasada = bool(dias)
        ordem.dias_atraso = dias
        ordem.total_cobrado = ordem.total()
        pecas = 0
        granel = Decimal("0.000")
        desenhos = []
        for item in ordem.itens.all():
            # Nome gravado no item + ícone escolhido no serviço: a tira de peças do
            # cartão respeita a escolha manual da tabela de preços.
            desenhos.append({"nome": item.descricao, "icone": item.servico.icone})
            if item.servico.unidade == ServicoLavanderia.Unidade.KG:
                granel += item.quantidade
            else:
                pecas += int(item.quantidade)
        ordem.n_pecas = pecas
        ordem.granel = granel
        ordem.icones = desenhos[:LIMITE_ICONES_NO_CARTAO]
        ordem.icones_restantes = max(0, len(desenhos) - LIMITE_ICONES_NO_CARTAO)
        ordem.proximo = proximo_passo(ordem)
        colunas[ordem.status].append(ordem)

    # Sem prazo vai para o fim da coluna (o banco ordena NULL por último no ASC);
    # atrasada sobe na frente de todas.
    for ordens in colunas.values():
        ordens.sort(key=lambda o: (not o.atrasada, o.prazo or date.max))
    filas = [{"codigo": status.value, "rotulo": status.label,
              "ordens": colunas[status.value], "n": len(colunas[status.value])}
             for status in OrdemLavanderia.FLUXO]
    if etapa:
        filas = [fila for fila in filas if fila["n"]]
    return filas


DIAS_CURTOS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


def prazos_sugeridos():
    """Os chips de "Pronto para": hoje, amanhã e em dois dias, com a data por extenso.

    O `<input type=date>` cru mostra mm/dd/yyyy no Chrome em inglês e não há como forçar
    pt-BR; com os chips, o caminho comum não passa pelo campo de data.
    """
    hoje = timezone.localdate()
    return [
        {"codigo": codigo, "rotulo": rotulo, "data": data, "iso": data.isoformat(),
         "extenso": f"{DIAS_CURTOS[data.weekday()]}, {data:%d/%m}"}
        for codigo, rotulo, data in (
            ("hoje", "Hoje", hoje),
            ("amanha", "Amanhã", hoje + timedelta(days=1)),
            ("dois", "Em 2 dias", hoje + timedelta(days=2)),
        )
    ]


def trilha_da_ordem(ordem):
    """Os quatro passos da ordem, cada um com a HORA em que aconteceu.

    Os quatro carimbos existem no banco (`CARIMBO_DO_PASSO`): o passo cumprido mostra
    a hora, o que ainda não aconteceu mostra vazio. A tela não inventa «Cumprido» nem
    «Agora» no lugar de um horário — ordem antiga, de antes dos carimbos de produção,
    aparece sem hora no passo, e a cor do passo continua dizendo o que já foi feito.
    """
    caminho = [*OrdemLavanderia.FLUXO, OrdemLavanderia.Status.ENTREGUE]
    atual = ordem.status if ordem.status in caminho else None
    posicao = caminho.index(atual) if atual else -1
    return [{"codigo": status.value, "rotulo": status.label,
             "carimbo": getattr(ordem, CARIMBO_DO_PASSO[status], None),
             "feito": indice < posicao, "atual": status == atual}
            for indice, status in enumerate(caminho)]


# ───────────────────────── (b) Rouparia interna ─────────────────────────

Estado = MovimentoEnxoval.Estado

# Rótulo curto de cada estado: o `label` do model é longo demais para a barra e para a
# legenda ("Limpa (rouparia)"), e o código cru nunca aparece na tela.
ROTULOS_ESTADO = {
    Estado.LIMPA: "Limpa",
    Estado.EM_USO: "Em uso",
    Estado.SUJA: "Suja",
    Estado.LAVANDO: "Lavando",
}

# Motivo gravado no movimento → frase da tela (extrato e histórico da rouparia).
MOTIVOS = {
    "faxina": "Faxina",
    "coleta": "Coleta",
    "distribuicao": "Distribuição",
    "envio_lavagem": "Envio para lavagem",
    "retorno_lavagem": "Retorno da lavagem",
    "aquisicao": "Aquisição",
}


def rotulo_motivo(motivo: str) -> str:
    """"envio_lavagem" → "Envio para lavagem"; "baixa:desgaste" → "Baixa — desgaste"."""
    motivo = (motivo or "").strip()
    if motivo in MOTIVOS:
        return MOTIVOS[motivo]
    if motivo.startswith("baixa:"):
        resto = motivo.split(":", 1)[1].replace("_", " ").strip()
        return f"Baixa — {resto}" if resto else "Baixa"
    legivel = motivo.replace("_", " ")
    return legivel[:1].upper() + legivel[1:]


def rotulo_estado(estado: str) -> str:
    return ROTULOS_ESTADO.get(estado, Estado(estado).label if estado else "")


def saldo_enxoval(item, estado) -> int:
    total = item.movimentos.filter(estado=estado).aggregate(s=Sum("quantidade"))["s"]
    return total or 0


def _mov(item, estado, quantidade, motivo, usuario, uh=None):
    MovimentoEnxoval.objects.create(
        item=item, estado=estado, quantidade=quantidade,
        motivo=motivo, criado_por=usuario, uh=uh,
    )


@transaction.atomic
def _transferir(item, de, para, quantidade, motivo, usuario, uh=None):
    from apps.nucleo.sistema import travar

    travar(item)
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    if saldo_enxoval(item, de) < quantidade:
        # Sem o rótulo, a recepção lia o código do banco ("em 'em_uso'").
        raise ValidationError(
            f"Saldo insuficiente de {item} em “{rotulo_estado(de).lower()}” "
            f"({saldo_enxoval(item, de)})."
        )
    _mov(item, de, -quantidade, motivo, usuario, uh)
    _mov(item, para, quantidade, motivo, usuario, uh)


@transaction.atomic
def adquirir(item, quantidade, usuario):
    """Entrada de enxoval novo direto na rouparia (limpa)."""
    from apps.nucleo.sistema import travar

    travar(item)
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    _mov(item, Estado.LIMPA, quantidade, "aquisicao", usuario)


def distribuir(item, quantidade, usuario, uh=None):
    _transferir(item, Estado.LIMPA, Estado.EM_USO, quantidade, "distribuicao", usuario, uh)


def coletar_suja(item, quantidade, usuario, uh=None, origem="coleta"):
    _transferir(item, Estado.EM_USO, Estado.SUJA, quantidade, origem, usuario, uh)


def enviar_lavar(item, quantidade, usuario):
    _transferir(item, Estado.SUJA, Estado.LAVANDO, quantidade, "envio_lavagem", usuario)


def receber_limpo(item, quantidade, usuario):
    _transferir(item, Estado.LAVANDO, Estado.LIMPA, quantidade, "retorno_lavagem", usuario)


@transaction.atomic
def baixar(item, quantidade, estado, motivo, usuario):
    """Baixa por desgaste/dano — sai do estado sem destino. Auditada."""
    from apps.nucleo.sistema import travar

    travar(item)
    quantidade = int(quantidade)
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    if saldo_enxoval(item, estado) < quantidade:
        raise ValidationError("Saldo insuficiente para baixa.")
    _mov(item, estado, -quantidade, f"baixa:{motivo}"[:40], usuario)
    registrar_auditoria(usuario, "baixa_enxoval", item,
                        {"quantidade": quantidade, "estado": estado, "motivo": motivo})


def quartos_ativos() -> int:
    """Quartos que a rouparia precisa atender (o `UH` usa `status`, não `ativo`)."""
    from apps.nucleo.models import UH

    return UH.objects.exclude(status=UH.Status.INATIVA).count()


# Tocar no número de um estado propõe o movimento que SAI dele: o "4" de Suja manda
# 4 para lavar. A origem decide a ação — a tela não pergunta duas vezes a mesma coisa.
MOVIMENTO_DO_ESTADO = {
    Estado.LIMPA: ("distribuir", "Distribuir para os quartos"),
    Estado.EM_USO: ("coletar", "Recolher como suja"),
    Estado.SUJA: ("enviar", "Enviar para lavar"),
    Estado.LAVANDO: ("receber", "Receber limpa de volta"),
}


def _fatia(estado, quantidade, pct):
    acao, proposta = MOVIMENTO_DO_ESTADO[estado]
    return {"estado": estado.value, "rotulo": ROTULOS_ESTADO[estado],
            "quantidade": quantidade, "pct": pct, "acao": acao, "proposta": proposta}


def _barra(estados, total):
    """Quatro fatias inteiras somando 100 (maior resto): a fatia não some por
    arredondamento e a soma não passa de 100. Sem peça nenhuma, barra vazia.

    Cada fatia leva também o movimento que ela propõe (`acao`/`proposta`), porque na
    tela o número do estado é o botão que começa esse movimento.
    """
    if not total:
        return [_fatia(e, estados[e.value], 0) for e in Estado]
    bruto = [(estados[e.value] * 100) / total for e in Estado]
    inteiros = [int(valor) for valor in bruto]
    sobra = 100 - sum(inteiros)
    # Devolve o que o truncamento comeu a quem tem o maior resto.
    for indice in sorted(range(len(bruto)), key=lambda i: bruto[i] - inteiros[i],
                         reverse=True)[:sobra]:
        inteiros[indice] += 1
    return [_fatia(estado, estados[estado.value], inteiros[indice])
            for indice, estado in enumerate(Estado)]


def posicao_enxoval():
    """Situação de cada item por estado e a barra da situação.

    `barra` são as quatro fatias (limpa, em uso, suja, lavando) em percentual inteiro,
    para desenhar o livro-razão do item em vez de cinco números soltos; `fora` é o que
    não está na rouparia. O alvo da tela é o `minimo` do item (quem sugere a conta de
    quartos × peças por faxina é o cadastro de item novo, na view).
    """
    linhas = []
    for item in ItemEnxoval.objects.filter(ativo=True):
        estados = {e.value: saldo_enxoval(item, e) for e in Estado}
        limpa = estados[Estado.LIMPA]
        total = sum(estados.values())
        linhas.append({
            "item": item,
            "estados": estados,
            "total": total,
            "fora": total - limpa,
            "barra": _barra(estados, total),
            "abaixo_minimo": limpa < item.minimo,
        })
    return linhas


# Ações do lote da rouparia: rótulo da tela + o helper que já existe (nada de motor novo).
ACOES_DO_LOTE = {
    "enviar": ("Enviar para lavar", enviar_lavar),
    "receber": ("Receber limpa", receber_limpo),
    "distribuir": ("Distribuir", distribuir),
}


@transaction.atomic
def mover_lote(itens, acao, quantidade, usuario):
    """Mesma quantidade em vários itens de enxoval, tudo ou nada.

    Trava em ordem de `pk` (vários itens na mesma transação) e usa os helpers de sempre,
    então os movimentos continuam imutáveis — só `create`. Saldo insuficiente em
    qualquer item derruba o lote inteiro: ninguém fica com metade do carrinho lançada.
    """
    from apps.nucleo.sistema import travar

    if acao not in ACOES_DO_LOTE:
        raise ValidationError("Escolha o que fazer com os itens selecionados.")
    try:
        quantidade = int(quantidade)
    except (TypeError, ValueError):
        raise ValidationError("Quantidade inválida. Informe um número inteiro.") from None
    if quantidade <= 0:
        raise ValidationError("Quantidade inválida.")
    selecionados = list(ItemEnxoval.objects.filter(
        pk__in=[item.pk for item in itens], ativo=True).order_by("pk"))
    if not selecionados:
        raise ValidationError("Selecione ao menos um item do enxoval.")
    for item in selecionados:
        travar(item)
    mover = ACOES_DO_LOTE[acao][1]
    for item in selecionados:
        mover(item, quantidade, usuario)
    return selecionados


def extrato_enxoval(item=None, estado=None, de=None, ate=None):
    """Livro-razão do enxoval para a tela de extrato (já pronto para `paginar()`)."""
    movimentos = MovimentoEnxoval.objects.select_related("item", "uh", "criado_por")
    if item:
        movimentos = movimentos.filter(item_id=item)
    if estado:
        movimentos = movimentos.filter(estado=estado)
    if de:
        movimentos = movimentos.filter(criado_em__date__gte=de)
    if ate:
        movimentos = movimentos.filter(criado_em__date__lte=ate)
    return movimentos


@transaction.atomic
def coletar_faxina(uh, usuario):
    """Chamado pela conclusão da faxina (Governança): recolhe o kit padrão de cada
    item (por_faxina) de 'em uso' para 'suja', limitado ao saldo em uso."""
    for item in ItemEnxoval.objects.select_for_update().filter(
            ativo=True, por_faxina__gt=0).order_by("pk"):
        qtd = min(item.por_faxina, saldo_enxoval(item, Estado.EM_USO))
        if qtd > 0:
            coletar_suja(item, qtd, usuario, uh=uh, origem="faxina")


def pendencias_auditoria():
    """Ordens de lavanderia atrasadas / abertas há muito, para a Auditoria (read-only)."""
    from django.urls import reverse
    achados = []
    hoje = timezone.localdate()
    limite = timezone.now() - timedelta(days=3)
    for o in OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO):
        if o.prazo and o.prazo < hoje:
            achados.append({
                "area": "Lavanderia", "tipo": "lavanderia_atrasada", "gravidade": "alta",
                "descricao": f"Ordem #{o.pk} ({o.titulo}): prazo {o.prazo:%d/%m} venceu e não foi entregue.",
                "url": reverse("lavanderia:ordem", args=[o.pk]),
            })
        elif o.recebida_em < limite:
            achados.append({
                "area": "Lavanderia", "tipo": "lavanderia_antiga", "gravidade": "media",
                "descricao": f"Ordem #{o.pk} ({o.titulo}) em produção há mais de 3 dias.",
                "url": reverse("lavanderia:ordem", args=[o.pk]),
            })
    return achados


def faturamento_periodo(inicio, fim):
    """Faturamento das ordens entregues no período (caixa do setor × folio).
    Interface pública p/ Relatórios (total é método, soma em Python)."""
    caixa = quarto = ZERO
    for o in OrdemLavanderia.objects.filter(entregue_em__date__range=(inicio, fim),
                                            status=OrdemLavanderia.Status.ENTREGUE):
        if o.destino == OrdemLavanderia.Destino.CAIXA:
            caixa += o.total()
        else:
            quarto += o.total()
    return {"caixa": caixa, "quarto": quarto}
