import json
import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.nucleo.catalogo import ilustracao_produto
from apps.nucleo.models import (
    FormaPagamento,
    LocalEstoque,
    Pessoa,
    Produto,
    disponibilidade_produtos,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas
from apps.nucleo.validadores import decimal_valido, filtro_identificador, identificador_valido

from . import services
from .models import Venda

# No balcão, a forma de pagamento é um botão por forma: as mais usadas vêm primeiro.
ORDEM_FORMAS = [
    FormaPagamento.Tipo.PIX, FormaPagamento.Tipo.DINHEIRO, FormaPagamento.Tipo.CARTAO_DEBITO,
    FormaPagamento.Tipo.CARTAO_CREDITO, FormaPagamento.Tipo.TRANSFERENCIA,
    FormaPagamento.Tipo.CORTESIA,
]


def _formas_do_balcao():
    def ordem(forma):
        posicao = ORDEM_FORMAS.index(forma.tipo) if forma.tipo in ORDEM_FORMAS else len(ORDEM_FORMAS)
        return posicao, forma.nome
    return sorted(FormaPagamento.objects.filter(ativo=True), key=ordem)


def _local_da_loja(request):
    local_id = filtro_identificador(request.GET.get("local"))
    if local_id:
        return get_object_or_404(LocalEstoque, pk=local_id, ativo=True)
    return (
        LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


@requer_modulo(Modulo.LOJA)
def pdv(request):
    local = _local_da_loja(request)
    produtos = []
    icones_categorias = {}
    if local:
        vendaveis = Produto.objects.filter(
            ativo=True, preco_venda__gt=0
        ).select_related("categoria")
        saldos = disponibilidade_produtos(vendaveis, local)
        for p in vendaveis:
            if p.categoria.nome not in icones_categorias:
                icones_categorias[p.categoria.nome] = ilustracao_produto(p.categoria.nome)["icone"]
            produtos.append({
                "id": p.pk, "nome": p.nome,
                "categoria": p.categoria.nome,
                "preco": float(p.preco_venda),
                "saldo": float(saldos[p.pk]),
                "unidade": p.get_unidade_display(),
                "unidade_sigla": p.unidade,
                "ilustracao": p.ilustracao_catalogo,
            })

    contas = []
    if request.user.pode_acessar(Modulo.RESERVAS):
        from apps.reservas.services import contas_abertas

        for c in contas_abertas():
            contas.append({
                "id": c.pk,
                "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}",
            })

    return render(request, "loja/pdv.html", {
        "local": local,
        "locais": LocalEstoque.objects.filter(ativo=True),
        "produtos_json": json.dumps(produtos),
        "icones_categorias_json": json.dumps(icones_categorias),
        "formas": _formas_do_balcao(),
        "clientes": pessoas_agrupadas(),
        "contas": contas,
        "url_finalizar": reverse("loja:finalizar"),
    })


def _chave_valida(valor):
    """A chave do carrinho, se for um UUID; qualquer outra coisa é ignorada."""
    try:
        return uuid.UUID(str(valor)) if valor else None
    except ValueError:
        return None


@requer_modulo(Modulo.LOJA)
def finalizar(request):
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido."}, status=405)
    try:
        dados = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"erro": "Dados inválidos."}, status=400)
    if not isinstance(dados, dict):
        return JsonResponse({"erro": "Envie os campos da venda em um objeto."}, status=400)
    try:
        local = get_object_or_404(LocalEstoque, pk=identificador_valido(dados.get("local_id"), nome="Local"), ativo=True)
        forma_id = identificador_valido(dados.get("forma_id"), nome="Pagamento", opcional=True)
        cliente_id = identificador_valido(dados.get("cliente_id"), nome="Cliente", opcional=True)
        forma = FormaPagamento.objects.filter(pk=forma_id, ativo=True).first() if forma_id else None
        cliente = Pessoa.objects.filter(pk=cliente_id).first() if cliente_id else None
        venda = services.finalizar_venda(
            operador=request.user, local=local, itens=dados.get("itens", []),
            destino=dados.get("destino"), forma=forma, cliente=cliente,
            conta_id=dados.get("conta_id"),
            desconto=decimal_valido(dados.get("desconto") or 0, nome="Desconto"),
            chave=_chave_valida(dados.get("chave")),
        )
    except ValidationError as erro:
        return JsonResponse({"erro": " ".join(erro.messages)}, status=400)
    return JsonResponse({
        "ok": True, "url": reverse("loja:venda", args=[venda.pk]),
    })


@requer_modulo(Modulo.LOJA)
def vendas(request):
    lista = paginar(request, Venda.objects.select_related("cliente", "criado_por"))
    return render(request, "loja/vendas.html", {"vendas": lista, "pagina": lista})


@requer_modulo(Modulo.LOJA)
def venda(request, pk):
    v = get_object_or_404(
        Venda.objects.select_related("cliente", "forma_pagamento", "criado_por"), pk=pk
    )
    return render(request, "loja/venda.html", {
        "venda": v, "itens": v.itens.all(), "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.LOJA)
def cupom(request, pk):
    """A venda no cupom de 80 mm (impressora térmica). `?imprimir=1` abre a impressão."""
    from django.utils.timezone import localtime

    from apps.nucleo.formatos import qtd_br

    v = get_object_or_404(
        Venda.objects.select_related("cliente", "forma_pagamento", "criado_por"), pk=pk
    )
    if v.destino == Venda.Destino.CONTA:
        pagamento = f"Lançado na conta: {v.conta_ref}"
    else:
        pagamento = f"Pago com {v.forma_pagamento.nome}" if v.forma_pagamento else ""
    if v.status == Venda.Status.CANCELADA:
        pagamento = "VENDA CANCELADA"
    cupom = {
        "titulo": f"Venda #{v.pk}", "origem": "Loja",
        "meta": [("Data", f"{localtime(v.criado_em):%d/%m/%Y %H:%M}"),
                 ("Cliente", v.cliente.nome if v.cliente else "avulso"),
                 ("Operador", v.criado_por.get_username())],
        "itens": [{"qtd": qtd_br(i.quantidade), "descricao": i.descricao,
                   "unitario": i.preco_unitario, "subtotal": i.subtotal}
                  for i in v.itens.all()],
        "subtotal": v.subtotal, "desconto": v.desconto, "total": v.total,
        "pagamento": pagamento,
        "voltar": reverse("loja:venda", args=[v.pk]),
    }
    return render(request, "componentes/cupom.html",
                  {"cupom": cupom, "imprimir": request.GET.get("imprimir") == "1"})


@requer_gerencia
def cancelar(request, pk):
    v = get_object_or_404(Venda, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_venda(v, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Venda cancelada. Estoque e caixa revertidos.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("loja:venda", pk=pk)
