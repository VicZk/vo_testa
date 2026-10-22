"""
Serviços do Portal do Hóspede. Cada ação do hóspede é encaminhada ao service do
módulo dono (Restaurante, Governança, Manutenção, Pagamentos) e atribuída a um
usuário de sistema (_portal) para auditoria. Degrada com graça se um módulo
opcional estiver inativo.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.nucleo.models import UH, LocalEstoque, Produto, modulo_ativo, saldo
from apps.nucleo.modulos import Modulo

from .models import AcessoPortal, SolicitacaoPortal


def _usuario_sistema():
    from apps.nucleo.sistema import usuario_de_sistema
    return usuario_de_sistema("_portal", "Portal")


def get_acesso(reserva_id) -> AcessoPortal:
    return AcessoPortal.objects.get_or_create(reserva_id=reserva_id)[0]


def rotacionar_acesso(reserva_id, usuario=None) -> AcessoPortal:
    """Troca o token do portal da reserva: o QR/link anterior para de funcionar na
    hora (ex.: foi encaminhado num grupo). Auditado."""
    import uuid

    from apps.nucleo.models import registrar_auditoria

    acesso = get_acesso(reserva_id)
    acesso.token = uuid.uuid4()
    acesso.save(update_fields=["token"])
    registrar_auditoria(usuario, "portal_novo_qr", acesso, {"reserva_id": reserva_id})
    return acesso


def resolver(token):
    """Token → dados da estadia (ou None se inválido / estadia encerrada)."""
    from apps.reservas.services import dados_estadia
    acesso = AcessoPortal.objects.filter(token=token).first()
    if not acesso:
        return None
    return dados_estadia(acesso.reserva_id)


def acesso_por_token(token) -> AcessoPortal | None:
    """AcessoPortal cru pelo token — usado no pré check-in (FNRH), que acontece
    ANTES da hospedagem, quando `resolver` ainda não retorna dados de estadia."""
    return AcessoPortal.objects.filter(token=token).first()


def _local_restaurante():
    return (
        LocalEstoque.objects.filter(modulo=Modulo.RESTAURANTE, ativo=True).first()
        or LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


MAX_ITENS_POR_PEDIDO = 20


def cardapio():
    """Produtos vendáveis com saldo, para o hóspede pedir no restaurante."""
    local = _local_restaurante()
    if not local or not modulo_ativo(Modulo.RESTAURANTE):
        return []
    itens = []
    for p in Produto.objects.filter(ativo=True, preco_venda__gt=0).prefetch_related("grupos_opcoes__opcoes"):
        if saldo(p, local) > 0:
            itens.append({"id": p.pk, "nome": p.nome, "preco": p.preco_venda,
                          "grupos": [grupo for grupo in p.grupos_opcoes.all() if grupo.ativo]})
    return itens


@transaction.atomic
def pedir_restaurante(estadia, pedidos):
    """`pedidos`: lista de (produto_id, quantidade). Abre uma comanda no quarto e
    lança os itens (a cozinha vê na lista de comandas). Atômico: se um item falhar
    (saldo insuficiente), a comanda e as baixas de estoque já feitas são revertidas."""
    if not modulo_ativo(Modulo.RESTAURANTE):
        raise ValidationError("O restaurante não está disponível no momento.")
    from apps.restaurante import services as restaurante
    local = _local_restaurante()
    if not local:
        raise ValidationError("Restaurante indisponível.")
    # Só o que está no cardápio (ativo, com preço) e em quantidade de pedido de quarto;
    # entrada inválida vira mensagem, não erro 500.
    itens = []
    if not isinstance(pedidos, (list, tuple)) or len(pedidos) > 100:
        raise ValidationError("Pedido inválido: confira os itens.")
    from apps.nucleo.validadores import identificador_valido

    for pedido in pedidos:
        if isinstance(pedido, dict):
            produto_id, qtd = pedido.get("produto_id"), pedido.get("quantidade")
            observacoes, opcoes = pedido.get("observacoes", ""), pedido.get("opcoes", [])
        elif isinstance(pedido, (tuple, list)) and len(pedido) == 2:
            produto_id, qtd = pedido
            observacoes, opcoes = "", []
        else:
            raise ValidationError("Pedido inválido: confira os itens.")
        try:
            produto_id = identificador_valido(produto_id, nome="Produto")
            qtd = int(str(qtd or 0).strip() or 0)
        except (TypeError, ValueError):
            raise ValidationError("Pedido inválido: confira as quantidades.")
        if qtd <= 0:
            continue
        if qtd > MAX_ITENS_POR_PEDIDO:
            raise ValidationError(
                f"Até {MAX_ITENS_POR_PEDIDO} unidades por item. Para mais, fale com a recepção.")
        produto = Produto.objects.filter(pk=produto_id, ativo=True, preco_venda__gt=0).first()
        if produto is None:
            raise ValidationError("Um dos itens não está mais no cardápio.")
        itens.append((produto, qtd, observacoes, opcoes))
    if not itens:
        raise ValidationError("Escolha ao menos um item.")
    op = _usuario_sistema()
    from apps.reservas.services import travar_conta_aberta

    conta = travar_conta_aberta(reserva_id=estadia["reserva_id"])
    comanda = restaurante.abrir_comanda(op, local, rotulo=f"{estadia['uh']} · app", conta_id=conta.pk)
    total_itens = 0
    for produto, qtd, observacoes, opcoes in itens:
        restaurante.adicionar_item(comanda, produto, qtd, op, observacoes=observacoes, opcoes=opcoes)
        total_itens += qtd
    SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.RESTAURANTE,
        detalhe=f"Comanda #{comanda.pk} · {total_itens} item(ns)",
    )
    return comanda


def solicitar_limpeza(estadia):
    reg = SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.LIMPEZA, detalhe="Limpeza extra pedida pelo hóspede.",
    )
    if modulo_ativo(Modulo.GOVERNANCA):
        from apps.governanca import services as gov
        uh = UH.objects.filter(pk=estadia["uh_id"]).first()
        if uh:
            gov.abrir_faxina(uh, usuario=_usuario_sistema(), origem="portal")
    return reg


def solicitar_manutencao(estadia, descricao):
    descricao = (descricao or "").strip() or "Solicitação do hóspede pelo portal."
    reg = SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.MANUTENCAO, detalhe=descricao[:200],
    )
    if modulo_ativo(Modulo.MANUTENCAO):
        from apps.manutencao import services as manut
        uh = UH.objects.filter(pk=estadia["uh_id"]).first()
        if uh:
            manut.abrir_os(_usuario_sistema(), uh=uh,
                           titulo="Solicitação do hóspede (portal)", descricao=descricao)
    return reg


def cobrar_saldo(estadia, metodo="pix"):
    """Gera a cobrança do saldo da conta via Pagamentos e devolve a cobrança."""
    if not modulo_ativo(Modulo.PAGAMENTOS):
        raise ValidationError("Pagamento online indisponível. Faça o pagamento na recepção.")
    saldo_conta = Decimal(estadia["saldo"])
    if saldo_conta <= 0:
        raise ValidationError("Não há saldo a pagar.")
    from apps.pagamentos import services as pag
    return pag.criar_cobranca(
        _usuario_sistema(), valor=saldo_conta, metodo=metodo,
        descricao=f"Saldo da hospedagem: {estadia['uh']}",
        finalidade=pag.FINALIDADE_SALDO, reserva_id=estadia["reserva_id"],
    )


def solicitar_checkout(estadia):
    return SolicitacaoPortal.objects.create(
        reserva_id=estadia["reserva_id"], uh_numero=estadia["uh"],
        tipo=SolicitacaoPortal.Tipo.CHECKOUT,
        detalhe="Check-out expresso solicitado pelo hóspede.",
    )
