import uuid
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.models import (
    EmbalagemProduto,
    LocalEstoque,
    LoteEstoque,
    MovimentoEstoque,
    Produto,
    RegistroLote,
    contar_lote,
    corrigir_identificacao,
    identificar_saldo,
    marca_lote,
    registrar_compra,
    saldos_por_local,
    salvar_ficha,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_gerencia, requer_modulo
from apps.nucleo.validadores import filtro_identificador

from .forms_suprimentos import (
    CompraForm,
    ContagemLoteForm,
    CorrecaoLoteForm,
    EmbalagemForm,
    IdentificarForm,
    IngredientesFormSet,
    LoteForm,
)

ZERO = Decimal("0")


def _formulario(request, contexto, template="estoque/suprimento_form.html"):
    forms = contexto["formset"] if "formset" in contexto else [contexto["form"]]
    if request.headers.get("X-Form-Preserve") == "1" and request.method == "POST":
        erros = [erros_do_formulario(form) for form in forms if form.errors]
        if contexto.get("formset") is not None:
            erros += list(contexto["formset"].non_form_errors())
        if erros:
            return JsonResponse({"errors": erros}, status=422, headers={"Cache-Control": "no-store"})
    return render(request, template, contexto)


@requer_modulo(Modulo.ESTOQUE)
def compras(request):
    movimentos = MovimentoEstoque.objects.filter(tipo=MovimentoEstoque.Tipo.ENTRADA_COMPRA).select_related(
        "produto", "local", "fornecedor", "criado_por").prefetch_related("lotes__lote")
    busca = request.GET.get("q", "").strip()
    if busca:
        movimentos = movimentos.filter(Q(produto__nome__icontains=busca) | Q(documento__icontains=busca)
                                        | Q(fornecedor__nome__icontains=busca))
    pagina = paginar(request, movimentos.order_by("-criado_em", "-pk"))
    return render(request, "estoque/compras.html", {"pagina": pagina, "busca": busca})


@requer_modulo(Modulo.ESTOQUE)
def compra_form(request):
    form = CompraForm(request.POST or None, initial={"chave": uuid.uuid4()})
    if request.method == "POST" and form.is_valid():
        try:
            registrar_compra(usuario=request.user, **form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Recebimento registrado. Confira a obrigação e o pagamento no Financeiro.")
            return redirect("estoque:compras")
    embalagens = [{"id": item.pk, "nome": item.nome, "produto": item.produto.nome,
                   "fator": str(item.fator), "unidade": item.produto.unidade}
                  for item in form.fields["embalagem"].queryset]
    return _formulario(request, {"form": form, "titulo": "Receber compra por embalagem",
                                "descricao": "Confira quantidades, nota e validade na chegada. Este recebimento atualiza o estoque e o custo médio.",
                                "botao": "Registrar recebimento", "voltar": "estoque:compras", "compra": True,
                                "embalagens_data": embalagens})


@requer_modulo(Modulo.ESTOQUE)
@requer_gerencia
@transaction.atomic
def embalagem_form(request, produto_pk, pk=None):
    produto = get_object_or_404(Produto.objects.select_for_update(), pk=produto_pk)
    embalagem = get_object_or_404(EmbalagemProduto, pk=pk, produto=produto) if pk else EmbalagemProduto(produto=produto)
    form = EmbalagemForm(request.POST or None, instance=embalagem)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Embalagem salva. Recebimentos anteriores mantêm a conversão registrada na época.")
        return redirect("estoque:produto_suprimentos", pk=produto.pk)
    return _formulario(request, {"form": form, "titulo": f"Embalagem · {produto.nome}",
                                "descricao": f"Informe quantas unidades de {produto.unidade} há nesta embalagem. Ex.: caixa com 12 unidades = fator 12.",
                                "botao": "Salvar embalagem", "produto": produto})


@requer_modulo(Modulo.ESTOQUE)
def produto_suprimentos(request, pk):
    produto = get_object_or_404(Produto.objects.select_related("categoria"), pk=pk)
    pagina = paginar(request, produto.embalagens.all())
    return render(request, "estoque/produto_suprimentos.html", {
        "produto": produto, "embalagens": pagina, "pagina": pagina,
        "ingredientes": produto.ingredientes.select_related("ingrediente"),
    })


@requer_modulo(Modulo.ESTOQUE)
@requer_gerencia
def ficha_form(request, pk):
    produto = get_object_or_404(Produto, pk=pk, usa_ficha_tecnica=True)
    formset = IngredientesFormSet(request.POST or None, prefix="ingredientes", initial=[
        {"ingrediente": item.ingrediente_id, "quantidade": item.quantidade} for item in produto.ingredientes.all()])
    if request.method == "POST" and formset.is_valid():
        componentes = [(f.cleaned_data["ingrediente"], f.cleaned_data["quantidade"]) for f in formset
                       if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        try:
            salvar_ficha(produto, componentes, request.user)
        except ValidationError as erro:
            formset._non_form_errors = formset.error_class(erro.messages)
        else:
            messages.success(request, "Ficha técnica salva. Os pedidos já feitos mantêm a baixa original para cancelamento.")
            return redirect("estoque:produto_suprimentos", pk=produto.pk)
    return _formulario(request, {"formset": formset, "produto": produto}, "estoque/ficha_form.html")


@requer_modulo(Modulo.ESTOQUE)
def lotes(request):
    lista = LoteEstoque.objects.select_related("produto").annotate(
        saldo_total=Coalesce(Sum("registros__quantidade"), ZERO, output_field=DecimalField()))
    busca = request.GET.get("q", "").strip()
    if busca:
        lista = lista.filter(Q(produto__nome__icontains=busca) | Q(codigo__icontains=busca))
    situacao = request.GET.get("situacao", "")
    if situacao == "vencidos":
        lista = lista.filter(validade__lt=timezone.localdate(), saldo_total__gt=0)
    elif situacao == "com_saldo":
        lista = lista.filter(saldo_total__gt=0)
    pagina = paginar(request, lista.order_by("validade", "pk"))
    return render(request, "estoque/lotes.html", {"pagina": pagina, "busca": busca,
                  "situacao": situacao, "hoje": timezone.localdate()})


@requer_modulo(Modulo.ESTOQUE)
def lote_form(request):
    inicial = {"produto": filtro_identificador(request.GET.get("produto"))}
    form = LoteForm(request.POST or None, initial=inicial, instance=LoteEstoque(criado_por=request.user))
    if request.method == "POST" and form.is_valid():
        lote = form.save()
        messages.success(request, "Lote cadastrado. Agora registre a compra recebida ou identifique mercadoria já existente.")
        return redirect("estoque:lote", pk=lote.pk)
    return _formulario(request, {"form": form, "titulo": "Cadastrar lote",
                                "descricao": "Copie o lote e a validade da embalagem. O cadastro identifica a mercadoria; o saldo vem do recebimento ou da conferência.",
                                "botao": "Cadastrar lote", "voltar": "estoque:lotes"})


@requer_modulo(Modulo.ESTOQUE)
def lote_detalhe(request, pk):
    lote = get_object_or_404(LoteEstoque.objects.select_related("produto"), pk=pk)
    fisicos = saldos_por_local(lote.produto)
    todos = dict(RegistroLote.objects.filter(lote__produto=lote.produto).values_list("local_id").annotate(s=Sum("quantidade")))
    deste = dict(lote.registros.values_list("local_id").annotate(s=Sum("quantidade")))
    locais = [{"local": local, "saldo": deste.get(local.pk, ZERO),
               "pendente": max(ZERO, fisicos.get(local.pk, ZERO) - todos.get(local.pk, ZERO))}
              for local in LocalEstoque.objects.filter(ativo=True)]
    pagina = paginar(request, lote.registros.select_related("local", "criado_por", "movimento").order_by("-pk"))
    return render(request, "estoque/lote.html", {"lote": lote, "locais": locais, "pagina": pagina,
                                                 "hoje": timezone.localdate()})


@requer_modulo(Modulo.ESTOQUE)
@requer_gerencia
def identificar(request):
    inicial = {"chave": uuid.uuid4(), "lote": filtro_identificador(request.GET.get("lote")),
               "local": filtro_identificador(request.GET.get("local"))}
    form = IdentificarForm(request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        try:
            identificar_saldo(dados["lote"].produto, usuario=request.user, **dados)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Saldo identificado por lote. A quantidade física permaneceu a mesma.")
            return redirect("estoque:lote", pk=dados["lote"].pk)
    return _formulario(request, {"form": form, "titulo": "Identificar saldo existente",
                                "descricao": "Use somente para mercadoria que já está no saldo físico, mas ainda não tem lote identificado. Confira a embalagem antes de informar a validade.",
                                "botao": "Confirmar identificação", "voltar": "estoque:lotes"})


@requer_modulo(Modulo.ESTOQUE)
@requer_gerencia
def contagem_lote(request, pk, local_pk):
    lote = get_object_or_404(LoteEstoque.objects.select_related("produto"), pk=pk)
    local = get_object_or_404(LocalEstoque, pk=local_pk, ativo=True)
    form = ContagemLoteForm(request.POST or None, initial={"chave": uuid.uuid4(), "marca": marca_lote(lote, local)})
    if request.method == "POST" and form.is_valid():
        try:
            contar_lote(lote, local, usuario=request.user, **form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Contagem do lote conferida. A diferença, quando existente, ficou no kardex e na auditoria.")
            return redirect("estoque:lote", pk=lote.pk)
    return _formulario(request, {"form": form, "titulo": "Contar lote", "lote": lote,
                                "descricao": f"{lote.produto.nome} · {local.nome}. Conte em {lote.produto.unidade}. Se houver movimentação durante a conferência, atualize a tela e conte novamente.",
                                "botao": "Aplicar contagem", "voltar": "estoque:lotes"})


@requer_modulo(Modulo.ESTOQUE)
@requer_gerencia
def correcao_lote(request, pk):
    lote = get_object_or_404(LoteEstoque.objects.select_related("produto"), pk=pk)
    form = CorrecaoLoteForm(request.POST or None, lote=lote, initial={"chave": uuid.uuid4()})
    if request.method == "POST" and form.is_valid():
        try:
            destino = corrigir_identificacao(lote=lote, usuario=request.user, **form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Identificação corrigida com histórico e sem alterar o saldo físico.")
            return redirect("estoque:lote", pk=destino.lote_id)
    return _formulario(request, {"form": form, "titulo": "Corrigir identificação do lote", "lote": lote,
                                "descricao": "Confira a embalagem e cadastre primeiro o lote com os dados corretos. Informe somente a quantidade que ainda está neste local; o histórico da venda permanece registrado.",
                                "botao": "Confirmar correção", "voltar": "estoque:lotes"})
