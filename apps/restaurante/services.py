"""Serviços do Restaurante: comanda aberta, itens (baixa estoque) e fechamento."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import (
    MovimentoEstoque,
    Produto,
    devolver_ao_estoque,
    receber_no_caixa,
    registrar_auditoria,
    registrar_saida,
)
from apps.nucleo.validadores import decimal_valido, identificador_valido

from .models import Comanda, GrupoOpcaoCardapio, ItemComanda

ZERO = Decimal("0.00")


def _opcoes_do_produto(produto, ids, anteriores=()):
    if not isinstance(ids, (list, tuple)) or len(ids) > 100:
        raise ValidationError("Confira as opções do pedido.")
    selecionadas = {identificador_valido(pk, nome="Opção") for pk in ids}
    if len(selecionadas) != len(ids):
        raise ValidationError("A mesma opção não pode ser escolhida duas vezes.")
    antigas = {opcao["id"]: opcao for opcao in anteriores}
    grupos = GrupoOpcaoCardapio.objects.filter(produto=produto, ativo=True).prefetch_related("opcoes")
    resultado, baixas = [], {}
    encontradas = set()
    for grupo in grupos:
        opcoes = [opcao for opcao in grupo.opcoes.all() if opcao.ativo and opcao.pk in selecionadas]
        if not grupo.minimo <= len(opcoes) <= grupo.maximo:
            raise ValidationError(f"{grupo.nome}: escolha entre {grupo.minimo} e {grupo.maximo} opção(ões).")
        for opcao in opcoes:
            encontrada = antigas.get(opcao.pk) or {
                "id": opcao.pk, "grupo": grupo.nome, "nome": opcao.nome,
                "adicional": str(opcao.adicional),
            }
            resultado.append(encontrada)
            encontradas.add(opcao.pk)
            if opcao.produto_estoque_id:
                baixas[opcao.produto_estoque_id] = baixas.get(opcao.produto_estoque_id, ZERO) + opcao.quantidade_estoque
    if encontradas != selecionadas:
        raise ValidationError("Uma opção não pertence a este produto ou não está mais disponível.")
    return resultado, baixas


def _dados_item(produto, quantidade, observacoes, opcoes, anteriores=(), preco_base=None):
    if produto is None or not produto.ativo or produto.preco_venda <= 0:
        raise ValidationError("Produto inválido ou indisponível.")
    qtd = decimal_valido(quantidade, nome="Quantidade", minimo=Decimal("0.001"),
                        maximo=Decimal("999999999.999"), casas=3)
    if not isinstance(observacoes, str) or len(observacoes.strip()) > 500:
        raise ValidationError("A observação deve ter no máximo 500 caracteres.")
    escolhas, extras = _opcoes_do_produto(produto, opcoes, anteriores)
    unitario = (produto.preco_venda if preco_base is None else preco_base) + sum(
        (Decimal(escolha["adicional"]) for escolha in escolhas), ZERO
    )
    unitario = decimal_valido(unitario, nome="Preço do item")
    decimal_valido(unitario * qtd, nome="Total do item", casas=5)
    # A composição fica congelada no item para devolução/cancelamento consistente.
    baixas = {produto.pk: qtd}
    for produto_id, consumo in extras.items():
        baixas[produto_id] = baixas.get(produto_id, ZERO) + consumo * qtd
    return qtd, observacoes.strip(), escolhas, unitario, baixas


def _estoque_do_item(item):
    if item.estoque_baixado:
        return {int(linha["produto_id"]): Decimal(linha["quantidade"]) for linha in item.estoque_baixado}
    return {item.produto_id: item.quantidade}


def _travar_produtos(ids):
    produtos = {p.pk: p for p in Produto.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if len(produtos) != len(set(ids)):
        raise ValidationError("Produto de estoque indisponível.")
    return produtos


def _registrar_baixas(comanda, baixas, produtos, operador):
    for pk, qtd in sorted(baixas.items()):
        registrar_saida(produtos[pk], comanda.local, qtd, operador, documento=f"Comanda #{comanda.pk}")


def _snapshot_baixas(baixas):
    return [{"produto_id": pk, "quantidade": str(qtd)} for pk, qtd in sorted(baixas.items())]


@transaction.atomic
def abrir_comanda(operador, local, mesa=None, cliente=None, rotulo="", conta_id=None):
    from apps.reservas.services import conta_para_pedido

    conta = conta_para_pedido(cliente=cliente, conta_id=conta_id)
    if conta:
        cliente = cliente or conta.reserva.hospede
        rotulo = rotulo or f"Quarto {conta.reserva.uh.numero}"
    if not (mesa or cliente or rotulo):
        raise ValidationError("Informe o ponto, o hóspede ou uma identificação.")
    return Comanda.objects.create(
        local=local, mesa=mesa, cliente=cliente, rotulo=rotulo, criado_por=operador, conta=conta,
    )


@transaction.atomic
def adicionar_item(comanda, produto, quantidade, operador, *, observacoes="", opcoes=()):
    """Lança um item na comanda e baixa o estoque na hora (o produto saiu).

    Trava a comanda (mesma âncora de `fechar_comanda`): dois garçons lançando ao
    mesmo tempo entram em fila, e nenhum item entra numa comanda que está fechando."""
    from apps.nucleo.sistema import travar

    comanda = travar(comanda)
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    quantidade, observacoes, escolhas, unitario, baixas = _dados_item(produto, quantidade, observacoes, opcoes)
    produtos = _travar_produtos(baixas)
    _registrar_baixas(comanda, baixas, produtos, operador)
    # Lido depois da trava: a quantidade é a atual, nunca a de antes do lançamento
    # concorrente (que somaria em cima de um valor velho e perderia itens).
    item = comanda.itens.filter(produto=produto, observacoes=observacoes, opcoes=escolhas,
                               preco_unitario=unitario, preparo=ItemComanda.Preparo.AGUARDANDO).first()
    if item:
        anteriores = _estoque_do_item(item)
        for pk, qtd in baixas.items():
            anteriores[pk] = anteriores.get(pk, ZERO) + qtd
        item.quantidade += quantidade
        decimal_valido(item.quantidade, nome="Quantidade total", minimo=Decimal("0.001"),
                       maximo=Decimal("999999999.999"), casas=3)
        decimal_valido(item.preco_unitario * item.quantidade, nome="Total do item", casas=5)
        item.estoque_baixado = _snapshot_baixas(anteriores)
        item.versao += 1
        item.save(update_fields=["quantidade", "estoque_baixado", "versao"])
        return item
    return ItemComanda.objects.create(
        comanda=comanda, produto=produto, descricao=produto.nome,
        natureza=produto.natureza, quantidade=quantidade,
        preco_unitario=unitario, observacoes=observacoes, opcoes=escolhas,
        estoque_baixado=_snapshot_baixas(baixas),
    )


@transaction.atomic
def remover_item(item, operador, motivo=""):
    """Remove um item da comanda e devolve o estoque (ajuste)."""
    from apps.nucleo.sistema import travar
    comanda = travar(item.comanda)  # não remove item de comanda sendo fechada
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    item = ItemComanda.objects.select_for_update().filter(pk=item.pk, comanda=comanda).first()
    if item is None:
        raise ValidationError("Este item já foi removido. Atualize a comanda.")
    from apps.nucleo.permissoes import eh_gerente

    iniciado = item.preparo != ItemComanda.Preparo.AGUARDANDO
    if iniciado and (not eh_gerente(operador) or not motivo.strip()):
        raise ValidationError("Item já enviado ao preparo: a gerência deve informar o motivo do cancelamento.")
    _devolver_item(item, operador, motivo or "Remoção antes do preparo", perda=iniciado)
    registrar_auditoria(operador, "item_comanda_cancelado", item,
                       {"motivo": motivo, "perda": iniciado, "descricao": item.descricao, "quantidade": str(item.quantidade)})
    item.delete()


def _devolver_item(item, operador, motivo, *, perda=False, produtos=None):
    baixas = _estoque_do_item(item)
    produtos = produtos or _travar_produtos(baixas)
    for pk, qtd in sorted(baixas.items()):
        devolver_ao_estoque(produtos[pk], item.comanda.local, qtd, operador,
                           motivo=f"Comanda #{item.comanda_id}: {motivo}")
        if perda:
            registrar_saida(produtos[pk], item.comanda.local, qtd, operador,
                            tipo=MovimentoEstoque.Tipo.PERDA,
                            documento=f"Comanda #{item.comanda_id}", observacao=motivo)


@transaction.atomic
def editar_item(item, operador, *, versao, quantidade, observacoes="", opcoes=()):
    from apps.nucleo.sistema import travar

    comanda = travar(item.comanda)
    item = ItemComanda.objects.select_for_update().filter(pk=item.pk, comanda=comanda).first()
    if item is None or not comanda.aberta:
        raise ValidationError("O pedido foi removido ou a comanda foi fechada. Atualize a tela.")
    if item.versao != identificador_valido(versao, nome="Versão do pedido"):
        raise ValidationError("Outro atendente alterou este item. Atualize antes de editar.")
    if item.preparo != ItemComanda.Preparo.AGUARDANDO:
        raise ValidationError("A cozinha já iniciou este item. Avise a equipe; alterações exigem cancelamento com motivo.")
    base = item.preco_unitario - sum((Decimal(o["adicional"]) for o in item.opcoes), ZERO)
    qtd, nota, escolhas, unitario, baixas = _dados_item(
        item.produto, quantidade, observacoes, opcoes, item.opcoes, preco_base=base
    )
    anteriores = _estoque_do_item(item)
    produtos = _travar_produtos(set(anteriores) | set(baixas))
    _devolver_item(item, operador, "Ajuste do pedido antes do preparo", produtos=produtos)
    _registrar_baixas(comanda, baixas, produtos, operador)
    item.quantidade, item.observacoes, item.opcoes = qtd, nota, escolhas
    item.preco_unitario, item.estoque_baixado = unitario, _snapshot_baixas(baixas)
    item.versao += 1
    item.save()
    registrar_auditoria(operador, "item_comanda_editado", item, {"versao": item.versao})
    return item


@transaction.atomic
def alterar_preparo(item, novo_estado, operador, *, versao):
    from apps.nucleo.sistema import travar

    comanda = travar(item.comanda)
    item = ItemComanda.objects.select_for_update().filter(pk=item.pk, comanda=comanda).first()
    if item is None or comanda.status == Comanda.Status.CANCELADA:
        raise ValidationError("Este pedido foi cancelado.")
    if item.versao != identificador_valido(versao, nome="Versão do pedido"):
        raise ValidationError("Este pedido mudou em outra tela. Confira os dados atualizados.")
    transicoes = {
        ItemComanda.Preparo.AGUARDANDO: {ItemComanda.Preparo.PREPARANDO, ItemComanda.Preparo.ENTREGUE},
        ItemComanda.Preparo.PREPARANDO: {ItemComanda.Preparo.PRONTO},
        ItemComanda.Preparo.PRONTO: {ItemComanda.Preparo.ENTREGUE},
    }
    if novo_estado not in transicoes.get(item.preparo, set()):
        raise ValidationError("Essa etapa de preparo já foi concluída ou não está disponível.")
    anterior = item.preparo
    item.preparo, item.versao = novo_estado, item.versao + 1
    item.save(update_fields=["preparo", "versao"])
    registrar_auditoria(operador, "preparo_comanda", item, {"de": anterior, "para": novo_estado})
    return item


@transaction.atomic
def fechar_comanda(comanda, operador, destino, forma=None, conta_id=None, desconto=ZERO):
    # Trava a comanda p/ serializar o fechamento — duplo POST não cobra/lança 2×.
    from apps.nucleo.sistema import travar
    comanda = travar(comanda)
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    if not comanda.itens.exists():
        raise ValidationError("A comanda está vazia.")
    from apps.nucleo.fiscal_regras import conferir_venda_de_produto
    conferir_venda_de_produto()
    if destino not in Comanda.Destino.values:
        raise ValidationError("Escolha o destino do pagamento.")
    desconto = decimal_valido(desconto or 0, nome="Desconto")
    if desconto < 0 or desconto > comanda.subtotal():
        raise ValidationError("Desconto inválido.")
    comanda.desconto = desconto
    total = comanda.total()

    if destino == Comanda.Destino.CAIXA:
        if not forma:
            raise ValidationError("Escolha a forma de pagamento.")
        from apps.nucleo.modulos import Modulo

        mov = receber_no_caixa(
            operador, forma, total, f"Comanda #{comanda.pk}", modulo=Modulo.RESTAURANTE,
        )
        comanda.forma_pagamento = forma
        comanda.movimento_caixa = mov
    else:
        from apps.reservas import services as reservas

        conta = reservas.travar_conta_aberta(conta_id or comanda.conta_id)
        if comanda.conta_id and comanda.conta_id != conta.pk:
            raise ValidationError("A comanda pertence a outra estadia. Confira o vínculo antes de cobrar.")
        comanda.conta = conta
        for item in comanda.itens.all():
            reservas.lancar_na_conta(
                conta, "consumo", item.natureza,
                f"Restaurante: {item.descricao}", item.subtotal, operador,
                quantidade=item.quantidade, preco_unitario=item.preco_unitario,
                observacoes=item.detalhe_preparo,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", "consumo", "Restaurante: desconto", desconto, operador
            )
        comanda.conta_ref = f"{conta.reserva.uh.numero}: {conta.reserva.hospede.nome}"

    comanda.destino = destino
    comanda.status = Comanda.Status.FECHADA
    comanda.fechada_em = timezone.now()
    comanda.save()
    return comanda


@transaction.atomic
def vincular_conta(comanda, conta_id, operador):
    from apps.nucleo.sistema import travar
    from apps.reservas.services import travar_conta_aberta

    travar(comanda)
    if not comanda.aberta:
        raise ValidationError("Só uma comanda aberta pode ser vinculada à estadia.")
    anterior = comanda.conta_id
    comanda.conta = travar_conta_aberta(conta_id)
    comanda.save(update_fields=["conta"])
    registrar_auditoria(operador, "comanda_vinculada", comanda,
                       {"conta_anterior": anterior, "conta": comanda.conta_id})
    return comanda


def pendencias_da_conta(conta_id):
    from django.urls import reverse

    return [{"rotulo": f"Comanda #{comanda.pk}", "valor": comanda.total(),
             "url": reverse("restaurante:comanda", args=[comanda.pk])}
            for comanda in Comanda.objects.filter(conta_id=conta_id, status=Comanda.Status.ABERTA)
            .prefetch_related("itens")]


@transaction.atomic
def cancelar_comanda(comanda, usuario, motivo):
    """Cancela a comanda aberta e devolve todo o estoque consumido."""
    from apps.nucleo.sistema import travar
    comanda = travar(comanda)  # dois cancelamentos juntos não devolvem o estoque 2×
    if not comanda.aberta:
        raise ValidationError("Só comandas abertas podem ser canceladas.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo do cancelamento.")
    # Ordem fixa (por produto) nas travas: duas operações com os mesmos itens em
    # ordens diferentes não se bloqueiam uma à outra.
    itens = list(comanda.itens.select_related("produto").order_by("produto_id"))
    produtos = _travar_produtos({pk for item in itens for pk in _estoque_do_item(item)})
    for item in itens:
        _devolver_item(item, usuario, motivo, perda=item.preparo != ItemComanda.Preparo.AGUARDANDO,
                       produtos=produtos)
    comanda.status = Comanda.Status.CANCELADA
    comanda.fechada_em = timezone.now()
    comanda.motivo_cancelamento = motivo
    comanda.save()
    registrar_auditoria(usuario, "cancelamento_comanda", comanda, {"motivo": motivo})
    return comanda


@transaction.atomic
def transferir_mesa(comanda, nova_mesa):
    from apps.nucleo.sistema import travar

    travar(comanda)
    if not comanda.aberta:
        raise ValidationError("Esta comanda já foi fechada.")
    if not nova_mesa:
        raise ValidationError("Selecione o ponto de atendimento de destino.")
    if nova_mesa == comanda.mesa:
        raise ValidationError("A comanda já está nesse ponto.")
    comanda.mesa = nova_mesa
    comanda.save(update_fields=["mesa"])
    return comanda


def pendencias_auditoria():
    """Comandas abertas há muito tempo, para a Auditoria (read-only)."""
    from datetime import timedelta

    from django.urls import reverse
    achados = []
    limite = timezone.now() - timedelta(hours=12)
    for c in Comanda.objects.filter(status=Comanda.Status.ABERTA, aberta_em__lt=limite):
        achados.append({
            "area": "Restaurante", "tipo": "comanda_antiga", "gravidade": "media",
            "descricao": f"Comanda #{c.pk} ({c.titulo}) aberta desde {c.aberta_em:%d/%m %H:%M}.",
            "url": reverse("restaurante:comanda", args=[c.pk]),
        })
    return achados


def faturamento_periodo(inicio, fim):
    """Faturamento das comandas fechadas no período (caixa do setor × folio).
    Interface pública p/ Relatórios (total é método, soma em Python)."""
    caixa = quarto = ZERO
    # Itens pré-carregados: o total de cada comanda soma em Python (arredondando item a
    # item, como na tela) sem uma consulta por comanda.
    for c in Comanda.objects.filter(fechada_em__date__range=(inicio, fim),
                                    status=Comanda.Status.FECHADA).prefetch_related("itens"):
        if c.destino == Comanda.Destino.CAIXA:
            caixa += c.total()
        else:
            quarto += c.total()
    return {"caixa": caixa, "quarto": quarto}
