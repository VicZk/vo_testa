from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

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
from apps.nucleo.validadores import decimal_valido, identificador_valido

from . import services
from .forms import GrupoOpcaoForm, OpcoesForm, PedidoItemForm
from .models import Comanda, GrupoOpcaoCardapio, ItemComanda, Mesa


def _registro(modelo, valor, nome):
    pk = identificador_valido(valor, nome=nome, opcional=True)
    if pk is None:
        return None
    registro = modelo.objects.filter(pk=pk).first()
    if registro is None:
        raise ValidationError(f"{nome}: registro não encontrado.")
    return registro


def _local(request):
    return (
        LocalEstoque.objects.filter(modulo=Modulo.RESTAURANTE, ativo=True).first()
        or LocalEstoque.objects.filter(modulo=Modulo.LOJA, ativo=True).first()
        or LocalEstoque.objects.filter(ativo=True).first()
    )


@never_cache
@requer_modulo(Modulo.RESTAURANTE)
def comandas(request):
    from apps.reservas.services import contas_abertas

    abertas = (
        Comanda.objects.filter(status=Comanda.Status.ABERTA)
        .select_related("mesa", "cliente", "conta__reserva__uh")
        .prefetch_related("itens")
    )
    return render(request, "restaurante/comandas.html", {
        "abertas": abertas,
        "mesas": Mesa.objects.filter(ativa=True),
        "clientes": pessoas_agrupadas(),
        "tem_local": _local(request) is not None,
        "contas": contas_abertas() if request.user.pode_acessar(Modulo.RESERVAS) else [],
    })


@requer_modulo(Modulo.RESTAURANTE)
def abrir(request):
    if request.method != "POST":
        return redirect("restaurante:comandas")
    if request.POST.get("conta") and not request.user.pode_acessar(Modulo.RESERVAS):
        raise PermissionDenied
    local = _local(request)
    if not local:
        messages.error(request, "Cadastre um depósito do Restaurante em Estoque → Locais.")
        return redirect("restaurante:comandas")
    try:
        mesa = _registro(Mesa, request.POST.get("mesa"), "Ponto")
        cliente = _registro(Pessoa, request.POST.get("cliente"), "Cliente")
        comanda = services.abrir_comanda(
            request.user, local, mesa=mesa, cliente=cliente,
            rotulo=request.POST.get("rotulo", "").strip(),
            conta_id=request.POST.get("conta") or None,
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("restaurante:comandas")
    return redirect("restaurante:comanda", pk=comanda.pk)


def _contexto_comanda(request, comanda):
    local = comanda.local
    cardapio = [
        {"id": p.pk, "nome": p.nome, "preco": p.preco_venda, "saldo": saldo(p, local)}
        for p in Produto.objects.filter(ativo=True, preco_venda__gt=0)
    ]
    contas = []
    if request.user.pode_acessar(Modulo.RESERVAS):
        from apps.reservas.services import contas_abertas

        contas = [
            {"id": c.pk, "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}"}
            for c in contas_abertas()
        ]
    return {
        "comanda": comanda,
        "cardapio": cardapio,
        "formas": FormaPagamento.objects.filter(ativo=True),
        "contas": contas,
        "mesas": Mesa.objects.filter(ativa=True),
        "eh_gerente": eh_gerente(request.user),
    }


@requer_modulo(Modulo.RESTAURANTE)
def comanda(request, pk):
    c = get_object_or_404(
        Comanda.objects.select_related("mesa", "cliente", "local", "conta__reserva__uh"), pk=pk
    )
    return render(request, "restaurante/comanda.html", _contexto_comanda(request, c))


@requer_modulo(Modulo.RESTAURANTE)
@requer_modulo(Modulo.RESERVAS)
def vincular(request, pk):
    if request.method == "POST":
        try:
            services.vincular_conta(get_object_or_404(Comanda, pk=pk), request.POST.get("conta_id"), request.user)
            messages.success(request, "Comanda vinculada à estadia.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:comanda", pk=pk)


@requer_modulo(Modulo.RESTAURANTE)
def cupom(request, pk):
    """A comanda no cupom de 80 mm: aberta, é a conferência da conta que vai à mesa;
    fechada, o recibo. `?imprimir=1` abre a impressão."""
    from django.utils.timezone import localtime

    from apps.nucleo.formatos import qtd_br

    c = get_object_or_404(
        Comanda.objects.select_related("mesa", "cliente", "forma_pagamento", "criado_por"),
        pk=pk,
    )
    itens = list(c.itens.all())
    subtotal = sum((i.subtotal for i in itens), Decimal("0.00"))
    meta = [("Aberta", f"{localtime(c.aberta_em):%d/%m/%Y %H:%M}")]
    if c.fechada_em:
        meta.append(("Fechada", f"{localtime(c.fechada_em):%d/%m/%Y %H:%M}"))
    meta.append(("Atendente", c.criado_por.get_username()))
    pagamento, aviso = "", "Não é documento fiscal"
    if c.status == Comanda.Status.ABERTA:
        aviso = "Conferência de conta — não é documento fiscal"
    elif c.status == Comanda.Status.CANCELADA:
        pagamento = "COMANDA CANCELADA"
    elif c.destino == Comanda.Destino.CONTA:
        pagamento = f"Lançado na conta: {c.conta_ref}"
    elif c.forma_pagamento:
        pagamento = f"Pago com {c.forma_pagamento.nome}"
    cupom = {
        "titulo": c.titulo, "origem": f"Comanda #{c.pk}", "meta": meta,
        "itens": [{"qtd": qtd_br(i.quantidade), "descricao": i.descricao, "detalhe": i.detalhe_preparo,
                   "unitario": i.preco_unitario, "subtotal": i.subtotal} for i in itens],
        "subtotal": subtotal, "desconto": c.desconto, "total": subtotal - c.desconto,
        "pagamento": pagamento, "aviso": aviso,
        "voltar": reverse("restaurante:comanda", args=[c.pk]),
    }
    return render(request, "componentes/cupom.html",
                  {"cupom": cupom, "imprimir": request.GET.get("imprimir") == "1"})


@requer_modulo(Modulo.RESTAURANTE)
def historico(request):
    """Comandas já fechadas e canceladas (as abertas ficam na tela principal)."""
    filtro = request.GET.get("status", "")
    qs = (
        Comanda.objects.exclude(status=Comanda.Status.ABERTA)
        .select_related("mesa", "cliente", "forma_pagamento", "criado_por")
        .prefetch_related("itens")
    )
    base = Comanda.objects.exclude(status=Comanda.Status.ABERTA)
    filtros = [
        {"chave": "", "rotulo": "Todas", "total": base.count()},
        {"chave": "fechada", "rotulo": "Fechadas",
         "total": base.filter(status=Comanda.Status.FECHADA).count()},
        {"chave": "cancelada", "rotulo": "Canceladas",
         "total": base.filter(status=Comanda.Status.CANCELADA).count()},
    ]
    if filtro in (Comanda.Status.FECHADA, Comanda.Status.CANCELADA):
        qs = qs.filter(status=filtro)
    pagina = paginar(request, qs)
    return render(request, "restaurante/historico.html", {
        "comandas": pagina,
        "pagina": pagina,
        "filtro": filtro,
        "filtros": filtros,
    })


@requer_modulo(Modulo.RESTAURANTE)
def add_item(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        try:
            produto = _registro(Produto, request.POST.get("produto_id"), "Produto")
            services.adicionar_item(
                c, produto, request.POST.get("quantidade", 1), request.user,
                observacoes=request.POST.get("observacoes", ""), opcoes=request.POST.getlist("opcoes"),
            )
        except (ValidationError, AttributeError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Produto inválido."
            return render(request, "restaurante/partials/itens.html",
                          {"comanda": c, "erro": msg})
    return render(request, "restaurante/partials/itens.html", {"comanda": c})


@requer_modulo(Modulo.RESTAURANTE)
def remover_item(request, pk, item_pk):
    c = get_object_or_404(Comanda, pk=pk)
    item = get_object_or_404(ItemComanda, pk=item_pk, comanda=c)
    erro = ""
    if request.method == "POST":
        try:
            services.remover_item(item, request.user, request.POST.get("motivo", ""))
        except ValidationError as exc:
            erro = " ".join(exc.messages)
    return render(request, "restaurante/partials/itens.html", {"comanda": c, "erro": erro})


@requer_modulo(Modulo.RESTAURANTE)
def fechar(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method != "POST":
        return redirect("restaurante:comanda", pk=pk)
    if request.POST.get("destino") == Comanda.Destino.CONTA and not request.user.pode_acessar(Modulo.RESERVAS):
        raise PermissionDenied
    try:
        forma = _registro(FormaPagamento, request.POST.get("forma"), "Forma de pagamento")
        services.fechar_comanda(
            c, request.user, request.POST.get("destino"),
            forma=forma, conta_id=request.POST.get("conta_id") or None,
            desconto=decimal_valido(request.POST.get("desconto") or 0, nome="Desconto"),
        )
        messages.success(request, f"Comanda #{c.pk} fechada.")
        return redirect("restaurante:comandas")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("restaurante:comanda", pk=pk)


@requer_modulo(Modulo.RESTAURANTE)
def transferir(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        try:
            mesa = _registro(Mesa, request.POST.get("mesa"), "Ponto")
            services.transferir_mesa(c, mesa)
            messages.success(request, "Comanda transferida de ponto.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:comanda", pk=pk)


@requer_gerencia
def cancelar(request, pk):
    c = get_object_or_404(Comanda, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_comanda(c, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Comanda cancelada. Itens sem preparo devolvidos; itens iniciados registrados como perda.")
            return redirect("restaurante:comandas")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:comanda", pk=pk)


@requer_modulo(Modulo.RESTAURANTE)
def mesas(request):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        if nome:
            Mesa.objects.get_or_create(nome=nome)
            messages.success(request, "Ponto cadastrado.")
        return redirect("restaurante:mesas")
    return render(request, "restaurante/mesas.html", {"mesas": Mesa.objects.all()})


def _pedido_item(request, c, produto, item=None):
    form = PedidoItemForm(request.POST if request.method == "POST" else None, produto=produto, item=item)
    if request.method == "POST" and form.is_valid():
        try:
            dados = form.cleaned_data
            if item:
                services.editar_item(item, request.user, versao=dados["versao"],
                                     quantidade=dados["quantidade"], observacoes=dados["observacoes"],
                                     opcoes=dados["opcoes"])
            else:
                services.adicionar_item(c, produto, dados["quantidade"], request.user,
                                        observacoes=dados["observacoes"], opcoes=dados["opcoes"])
            if request.headers.get("HX-Request"):
                resposta = render(request, "restaurante/partials/itens.html", {"comanda": c})
                resposta["HX-Retarget"] = "#comanda-itens"
                resposta["HX-Reswap"] = "outerHTML"
                resposta["HX-Trigger-After-Swap"] = "pedidoSalvo"
                return resposta
            return redirect("restaurante:comanda", pk=c.pk)
        except ValidationError as erro:
            form.add_error(None, erro)
    template = "restaurante/partials/pedido_item.html" if request.headers.get("HX-Request") else "restaurante/pedido_item.html"
    return render(request, template, {"form": form, "comanda": c, "produto": produto,
                                     "item": item, "acao": request.path})


@requer_modulo(Modulo.RESTAURANTE)
def pedir_item(request, pk, produto_pk):
    return _pedido_item(request, get_object_or_404(Comanda, pk=pk),
                        get_object_or_404(Produto, pk=produto_pk, ativo=True))


@requer_modulo(Modulo.RESTAURANTE)
def editar_item(request, pk, item_pk):
    item = get_object_or_404(ItemComanda.objects.select_related("comanda", "produto"),
                             pk=item_pk, comanda_id=pk)
    return _pedido_item(request, item.comanda, item.produto, item)


@never_cache
@requer_modulo(Modulo.RESTAURANTE)
def cozinha(request):
    itens = ItemComanda.objects.exclude(comanda__status=Comanda.Status.CANCELADA).exclude(
        preparo=ItemComanda.Preparo.ENTREGUE).select_related("comanda__mesa", "comanda__cliente").order_by("criado_em", "pk")
    colunas = [{"codigo": codigo, "nome": nome, "itens": []}
               for codigo, nome in ItemComanda.Preparo.choices if codigo != ItemComanda.Preparo.ENTREGUE]
    grupos = {coluna["codigo"]: coluna["itens"] for coluna in colunas}
    for item in itens:
        grupos[item.preparo].append(item)
    template = "restaurante/partials/cozinha.html" if request.headers.get("HX-Request") else "restaurante/cozinha.html"
    return render(request, template, {"colunas": colunas})


@requer_modulo(Modulo.RESTAURANTE)
def preparo_item(request, pk, item_pk):
    if request.method == "POST":
        item = get_object_or_404(ItemComanda, pk=item_pk, comanda_id=pk)
        try:
            services.alterar_preparo(item, request.POST.get("preparo"), request.user,
                                    versao=request.POST.get("versao"))
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("restaurante:cozinha")


@requer_modulo(Modulo.RESTAURANTE)
@requer_gerencia
def cardapio_config(request):
    produtos = Produto.objects.filter(ativo=True, preco_venda__gt=0).annotate(
        total_grupos=Count("grupos_opcoes")).order_by("nome", "pk")
    return render(request, "restaurante/cardapio_config.html", {"produtos": produtos})


@requer_modulo(Modulo.RESTAURANTE)
@requer_gerencia
def cardapio_produto(request, produto_pk):
    produto = get_object_or_404(Produto, pk=produto_pk)
    try:
        grupo_id = identificador_valido(request.GET.get("grupo"), nome="Grupo", opcional=True)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("restaurante:cardapio_produto", produto_pk=produto.pk)
    grupo = get_object_or_404(GrupoOpcaoCardapio, pk=grupo_id, produto=produto) if grupo_id else GrupoOpcaoCardapio(produto=produto)
    dados = request.POST if request.method == "POST" else None
    form = GrupoOpcaoForm(dados, instance=grupo)
    opcoes = OpcoesForm(dados, instance=grupo, prefix="opcoes")
    if request.method == "POST" and form.is_valid() and opcoes.is_valid():
        with transaction.atomic():
            grupo = form.save()
            opcoes.instance = grupo
            opcoes.save()
        messages.success(request, "Escolhas do cardápio salvas.")
        return redirect(f"{reverse('restaurante:cardapio_produto', args=[produto.pk])}?grupo={grupo.pk}")
    return render(request, "restaurante/cardapio_produto.html", {
        "produto": produto, "grupo": grupo, "form": form, "opcoes": opcoes,
        "grupos": produto.grupos_opcoes.prefetch_related("opcoes"),
    })
