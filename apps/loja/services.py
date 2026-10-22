"""Serviços da Loja: fechar venda (dois destinos) e cancelar."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.nucleo.models import (
    Produto,
    devolver_ao_estoque,
    estornar_movimento,
    receber_no_caixa,
    registrar_auditoria,
    registrar_saida,
    saldo,
)
from apps.nucleo.validadores import decimal_valido, identificador_valido

from .models import ItemVenda, Venda

ZERO = Decimal("0.00")


def finalizar_venda(operador, local, itens, destino, forma=None, cliente=None,
                    conta_id=None, desconto=ZERO, chave=None):
    """
    itens: lista de dicts {produto_id, quantidade}. Valida saldo, baixa estoque
    e cobra pelo destino escolhido (caixa OU conta do quarto).

    `chave` (UUID que o PDV gera para cada carrinho) torna a venda idempotente: o
    clique duplo, ou o reenvio depois de a conexão cair, devolve a venda já feita em
    vez de baixar o estoque e cobrar de novo.
    """
    if chave:
        existente = Venda.objects.filter(chave=chave).first()
        if existente:
            return existente
    try:
        return _finalizar_venda(operador, local, itens, destino, forma, cliente,
                                conta_id, desconto, chave)
    except IntegrityError:
        # Dois envios da mesma chave ao mesmo tempo: o segundo esbarra na unicidade
        # quando o primeiro grava; devolve a venda do primeiro.
        existente = Venda.objects.filter(chave=chave).first() if chave else None
        if existente:
            return existente
        raise


@transaction.atomic
def _finalizar_venda(operador, local, itens, destino, forma, cliente, conta_id,
                     desconto, chave):
    desconto = decimal_valido(desconto or 0, nome="Desconto")
    if not isinstance(itens, list) or not itens or len(itens) > 100:
        raise ValidationError("Adicione ao menos um item à venda.")
    if destino not in Venda.Destino.values:
        raise ValidationError("Escolha o destino da cobrança.")
    from apps.nucleo.fiscal_regras import conferir_venda_de_produto
    conferir_venda_de_produto()

    # Monta as linhas com preço e valida saldo no local.
    linhas = []
    subtotal = ZERO
    for item in itens:
        if not isinstance(item, dict):
            raise ValidationError("Item da venda inválido.")
        produto_id = identificador_valido(item.get("produto_id"), nome="Produto")
        produto = Produto.objects.filter(pk=produto_id, ativo=True).first()
        if not produto:
            raise ValidationError("Produto inválido na venda.")
        qtd = decimal_valido(item.get("quantidade"), nome="Quantidade", minimo=Decimal("0.001"), maximo=Decimal("999999999.999"), casas=3)
        if saldo(produto, local) < qtd:
            raise ValidationError(
                f"Saldo insuficiente de {produto.nome} em {local.nome} "
                f"(disponível: {saldo(produto, local)})."
            )
        valor = decimal_valido((produto.preco_venda * qtd).quantize(Decimal("0.01")), nome="Total do item")
        subtotal += valor
        decimal_valido(subtotal, nome="Total da venda")
        linhas.append((produto, qtd, valor))

    if desconto < 0 or desconto > subtotal:
        raise ValidationError("Desconto inválido.")
    total = subtotal - desconto
    # Travas sempre na mesma ordem (por produto, depois o caixa): duas vendas com os
    # mesmos itens em ordens diferentes não se bloqueiam uma à outra.
    linhas.sort(key=lambda linha: linha[0].pk)

    if destino == Venda.Destino.CAIXA and not forma:
        raise ValidationError("Escolha a forma de pagamento.")
    if destino == Venda.Destino.CONTA:
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo
        if not modulo_ativo(Modulo.RESERVAS):
            raise ValidationError("Lançar no quarto exige o módulo Reservas ativo.")

    venda = Venda.objects.create(
        local=local, destino=destino, cliente=cliente, forma_pagamento=forma,
        desconto=desconto, total=total, criado_por=operador, chave=chave,
    )
    for produto, qtd, valor in linhas:
        ItemVenda.objects.create(
            venda=venda, produto=produto, descricao=produto.nome,
            natureza=produto.natureza, quantidade=qtd,
            preco_unitario=produto.preco_venda, subtotal=valor,
        )
        registrar_saida(
            produto, local, qtd, operador,
            documento=f"Venda Loja #{venda.pk}",
        )

    if destino == Venda.Destino.CAIXA:
        from apps.nucleo.modulos import Modulo

        mov = receber_no_caixa(
            operador, forma, total, f"Venda Loja #{venda.pk}", modulo=Modulo.LOJA,
        )
        venda.movimento_caixa = mov
        venda.save(update_fields=["movimento_caixa"])
    else:
        from apps.reservas import services as reservas

        conta = reservas.conta_aberta(conta_id)
        if not conta:
            raise ValidationError("Selecione uma conta do quarto aberta.")
        for produto, qtd, valor in linhas:
            reservas.lancar_na_conta(
                conta, "consumo", produto.natureza,
                f"Loja: {produto.nome}", valor, operador,
                quantidade=qtd, preco_unitario=produto.preco_venda,
            )
        if desconto > 0:
            reservas.lancar_na_conta(
                conta, "desconto", "consumo", "Loja: desconto", desconto, operador
            )
        venda.conta_ref = f"{conta.reserva.uh.numero} — {conta.reserva.hospede.nome}"
        venda.save(update_fields=["conta_ref"])

    return venda


@transaction.atomic
def cancelar_venda(venda, usuario, motivo):
    """Cancela uma venda de pagamento imediato: devolve estoque e estorna o caixa."""
    from apps.nucleo.sistema import travar
    venda = travar(venda)  # dois cancelamentos juntos não devolvem o estoque 2×
    if venda.status != Venda.Status.FECHADA:
        raise ValidationError("Esta venda não está aberta para cancelamento.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo do cancelamento.")
    if venda.destino == Venda.Destino.CONTA:
        raise ValidationError(
            "Esta venda foi lançada na conta do quarto. Faça o ajuste pela conta da hospedagem."
        )
    # Devolve o estoque (sem mexer no custo médio), travando na mesma ordem da venda.
    for item in venda.itens.select_related("produto").order_by("produto_id"):
        devolver_ao_estoque(item.produto, venda.local, item.quantidade, usuario,
                            motivo=f"Cancelamento venda Loja #{venda.pk}")
    # Estorna o recebimento no caixa (exige o caixa aberto).
    if venda.movimento_caixa:
        estornar_movimento(
            venda.movimento_caixa, venda.movimento_caixa.sessao, usuario, motivo
        )
    venda.status = Venda.Status.CANCELADA
    venda.cancelada_em = timezone.now()
    venda.motivo_cancelamento = motivo
    venda.save()
    registrar_auditoria(usuario, "cancelamento_venda", venda, {"motivo": motivo})
    return venda


def vendas_do_dia():
    """Total e contagem de vendas fechadas hoje (para o dashboard)."""
    from django.db.models import Sum

    hoje = timezone.localdate()
    qs = Venda.objects.filter(status=Venda.Status.FECHADA, criado_em__date=hoje)
    return {"quantidade": qs.count(), "total": qs.aggregate(t=Sum("total"))["t"] or ZERO}


def faturamento_periodo(inicio, fim):
    """Faturamento FECHADO no período, separado por destino (caixa do setor × folio).
    Interface pública p/ Relatórios não importar os models internos da Loja."""
    from django.db.models import Sum
    v = Venda.objects.filter(criado_em__date__range=(inicio, fim), status=Venda.Status.FECHADA)
    caixa = v.filter(destino=Venda.Destino.CAIXA).aggregate(t=Sum("total"))["t"] or ZERO
    quarto = v.filter(destino=Venda.Destino.CONTA).aggregate(t=Sum("total"))["t"] or ZERO
    return {"caixa": caixa, "quarto": quarto}
