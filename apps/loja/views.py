import json
import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.nucleo.models import (
    FormaPagamento,
    LocalEstoque,
    Pessoa,
    Produto,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas
from apps.nucleo.validadores import decimal_valido, filtro_identificador, identificador_valido

from . import services
from .models import Venda


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
    if local:
        vendaveis = Produto.objects.filter(
            ativo=True, preco_venda__gt=0
        ).select_related("categoria")
        for p in vendaveis:
            produtos.append({
                "id": p.pk, "nome": p.nome,
                "categoria": p.categoria.nome,
                "preco": float(p.preco_venda),
                "saldo": float(saldo(p, local)),
                "unidade": p.get_unidade_display(),
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
        "formas": FormaPagamento.objects.filter(ativo=True),
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
