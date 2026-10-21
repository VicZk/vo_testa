"""Telas de gestão do Estoque.

O motor (saldo, custo médio, kardex imutável) mora no núcleo
(`apps/nucleo/models/estoque.py`); aqui só tem leitura e formulário. Nenhuma
view escreve movimento na mão — tudo passa por `registrar_entrada`,
`registrar_saida`, `transferir` e `ajustar`.

Regra de consulta desta tela: o número de consultas não cresce com o tamanho do
catálogo. Posição = saldos agrupados + produtos + locais; o resto é Python.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.nucleo.models import (
    CategoriaProduto,
    Inventario,
    ItemInventario,
    LocalEstoque,
    MovimentoEstoque,
    Produto,
    ajustar,
    indicadores_estoque,
    posicao_estoque,
    registrar_entrada,
    registrar_saida,
    resumo_locais,
    saldos_por_local,
    transferir,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from .formato import sigla
from .forms import (
    AbrirInventarioForm,
    AjusteForm,
    CategoriaProdutoForm,
    EntradaForm,
    LocalEstoqueForm,
    ProdutoForm,
    SaidaForm,
    TransferenciaForm,
    fornecedores,
)

ZERO = Decimal("0")


# ---------- Dados compartilhados pelas telas ----------


def _locais_ativos():
    return list(LocalEstoque.objects.filter(ativo=True))


def _produtos_json(saldos=None):
    """Catálogo para o combobox e para a prévia da movimentação.

    `saldos` é o mapa `{(produto, local): saldo}` — UMA consulta para o catálogo
    inteiro, em vez de uma por produto. Quantidade vai como texto já formatado
    (é o que a tela mostra) e como número (é com ele que a prévia soma).
    """
    saldos = saldos_por_local() if saldos is None else saldos
    # Vira {produto: {local: saldo}} numa passada só — varrer o mapa inteiro
    # dentro do laço de produtos seria produtos × movimentos.
    agrupado: dict[int, dict] = {}
    for (produto_id, local_id), valor in saldos.items():
        agrupado.setdefault(produto_id, {})[str(local_id)] = float(valor)
    itens = []
    for produto in Produto.objects.filter(ativo=True).select_related("categoria"):
        por_local = agrupado.get(produto.pk, {})
        itens.append({
            "id": produto.pk,
            "nome": produto.nome,
            "grupo": produto.categoria.nome,
            "unidade": sigla(produto.unidade),
            "custo": float(produto.custo_medio),
            "saldos": por_local,
            "total": sum(por_local.values()),
        })
    itens.sort(key=lambda it: (it["grupo"].lower(), it["nome"].lower()))
    return itens


# ---------- Posição de estoque (home do módulo) ----------


SITUACOES = [
    ("", "Tudo"),
    ("alerta", "Abaixo do mínimo"),
    ("zerado", "Sem saldo"),
    ("ok", "Em dia"),
]


@requer_modulo(Modulo.ESTOQUE)
def posicao(request):
    local = None
    if request.GET.get("local"):
        local = get_object_or_404(LocalEstoque, pk=request.GET["local"])
    busca = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "")
    situacao = request.GET.get("situacao", "")
    # Compatibilidade: o painel e a Auditoria linkam `?alerta=1` há meses.
    if request.GET.get("alerta") and not situacao:
        situacao = "alerta"

    # Uma leitura só do escopo (local escolhido): os indicadores falam do
    # escopo inteiro, e a tabela é esta mesma lista peneirada.
    linhas = posicao_estoque(local)
    # Num depósito, o catálogo inteiro apareceria como "sem saldo" — 27 alarmes
    # vermelhos para dizer que a Loja não guarda detergente. Quem nunca passou
    # por ali sai da conta e da lista; o rodapé da tabela diz quantos são e
    # leva ao catálogo completo (`?catalogo=1`).
    catalogo = bool(request.GET.get("catalogo"))
    fora_do_local = 0
    if local and not catalogo:
        fora_do_local = sum(1 for linha in linhas if linha["nunca_movimentou"])
        linhas = [linha for linha in linhas if not linha["nunca_movimentou"]]
    indicadores = indicadores_estoque(linhas)
    recentes = MovimentoEstoque.objects.filter(
        criado_em__gte=timezone.now() - timedelta(days=7)
    )
    if local:
        recentes = recentes.filter(local=local)
    indicadores["movimentos7"] = recentes.count()

    if busca:
        alvo = busca.lower()
        linhas = [
            linha for linha in linhas
            if alvo in linha["produto"].nome.lower()
            or alvo in (linha["produto"].codigo_barras or "").lower()
        ]
    if categoria_id:
        linhas = [
            linha for linha in linhas
            if str(linha["produto"].categoria_id) == categoria_id
        ]
    if situacao == "alerta":
        linhas = [linha for linha in linhas if linha["abaixo_minimo"]]
    elif situacao == "zerado":
        linhas = [linha for linha in linhas if linha["zerado"]]
    elif situacao == "ok":
        linhas = [linha for linha in linhas if linha["situacao"] == "ok"]

    pagina = paginar(request, linhas)
    resumo = resumo_locais()
    # O cartão "Todos os locais" fala da pousada inteira mesmo quando a tela
    # está olhando um depósito — senão repetiria o número do depósito escolhido.
    geral = indicadores if local is None else indicadores_estoque(posicao_estoque())
    return render(
        request,
        "estoque/posicao.html",
        {
            "linhas": pagina,
            "pagina": pagina,
            "resumo_locais": resumo,
            "geral": geral,
            "alertas_geral": geral["abaixo"] + geral["zerados"],
            "fora_do_local": fora_do_local,
            "catalogo": catalogo,
            "local": local,
            "indicadores": indicadores,
            "categorias": CategoriaProduto.objects.filter(ativo=True),
            "situacoes": SITUACOES,
            "filtros": {"q": busca, "categoria": categoria_id, "situacao": situacao},
            "tem_filtro": bool(busca or categoria_id or situacao or catalogo),
        },
    )


# ---------- Produtos ----------


@requer_modulo(Modulo.ESTOQUE)
def produtos(request):
    busca = request.GET.get("q", "").strip()
    categoria_id = request.GET.get("categoria", "")
    lista = Produto.objects.select_related("categoria")
    if busca:
        lista = lista.filter(
            Q(nome__icontains=busca) | Q(codigo_barras__icontains=busca)
        )
    if categoria_id:
        lista = lista.filter(categoria_id=categoria_id)
    if request.GET.get("situacao") == "inativo":
        lista = lista.filter(ativo=False)
    elif request.GET.get("situacao") != "todos":
        lista = lista.filter(ativo=True)
    # Saldo por produto numa consulta só (era `p.saldo` por linha = N+1).
    lista = lista.annotate(
        saldo_total=Coalesce(
            Sum("movimentos__quantidade"), ZERO, output_field=DecimalField()
        )
    )
    pagina = paginar(request, lista)
    return render(
        request,
        "estoque/produtos.html",
        {
            "produtos": pagina,
            "pagina": pagina,
            "categorias": CategoriaProduto.objects.filter(ativo=True),
            "filtros": {
                "q": busca, "categoria": categoria_id,
                "situacao": request.GET.get("situacao", ""),
            },
        },
    )


@requer_modulo(Modulo.ESTOQUE)
def produto_form(request, pk=None):
    produto = get_object_or_404(Produto, pk=pk) if pk else None
    form = ProdutoForm(request.POST or None, instance=produto)
    if request.method == "POST" and form.is_valid():
        produto = form.save()
        messages.success(request, f"Produto “{produto.nome}” salvo.")
        return redirect("estoque:produtos")
    return render(
        request,
        "estoque/produto_form.html",
        {
            "form": form,
            "produto": produto,
            "saldos": _saldos_do_produto(produto) if produto else [],
        },
    )


def _saldos_do_produto(produto):
    """[(local, saldo)] — uma consulta, para o cabeçalho do kardex e da ficha."""
    mapa = saldos_por_local(produto)
    return [
        {"local": local, "saldo": mapa.get(local.pk, ZERO)}
        for local in _locais_ativos()
    ]


TIPOS_KARDEX = [
    ("", "Todos os tipos"),
    ("entrada", "Só entradas"),
    ("saida", "Só saídas"),
] + [(valor, texto) for valor, texto in MovimentoEstoque.Tipo.choices]


@requer_modulo(Modulo.ESTOQUE)
def kardex(request, pk):
    produto = get_object_or_404(Produto.objects.select_related("categoria"), pk=pk)
    movimentos = produto.movimentos.select_related("local", "criado_por", "fornecedor")

    local_id = request.GET.get("local", "")
    if local_id:
        movimentos = movimentos.filter(local_id=local_id)
    tipo = request.GET.get("tipo", "")
    if tipo == "entrada":
        movimentos = movimentos.filter(quantidade__gt=0)
    elif tipo == "saida":
        movimentos = movimentos.filter(quantidade__lt=0)
    elif tipo:
        movimentos = movimentos.filter(tipo=tipo)
    de, ate = request.GET.get("de", ""), request.GET.get("ate", "")
    if de:
        movimentos = movimentos.filter(criado_em__date__gte=de)
    if ate:
        movimentos = movimentos.filter(criado_em__date__lte=ate)

    pagina = paginar(request, movimentos)
    linhas = _com_saldo_corrente(produto, list(pagina), local_id)
    saldos = _saldos_do_produto(produto)
    total = sum((linha["saldo"] for linha in saldos), ZERO)
    return render(
        request,
        "estoque/kardex.html",
        {
            "produto": produto,
            "linhas": linhas,
            "pagina": pagina,
            "saldo": total,
            "valor": (total * produto.custo_medio).quantize(Decimal("0.01")),
            "saldos": saldos,
            "filtros": {"local": local_id, "tipo": tipo, "de": de, "ate": ate},
            "tipos": TIPOS_KARDEX,
            "tem_filtro": bool(local_id or tipo or de or ate),
        },
    )


def _com_saldo_corrente(produto, movimentos, local_id):
    """Saldo DEPOIS de cada movimento, do mais novo para o mais antigo.

    O saldo do topo da página é lido uma vez (uma consulta); daí para baixo é
    subtração. É o saldo real do produto naquele instante — se a pessoa filtrar
    por tipo, as linhas saltam, mas cada saldo continua sendo o verdadeiro.
    """
    if not movimentos:
        return []
    topo = movimentos[0]
    base = MovimentoEstoque.objects.filter(produto=produto).filter(
        Q(criado_em__lt=topo.criado_em)
        | Q(criado_em=topo.criado_em, pk__lte=topo.pk)
    )
    if local_id:
        base = base.filter(local_id=local_id)
    corrente = base.aggregate(s=Sum("quantidade"))["s"] or ZERO
    linhas = []
    for movimento in movimentos:
        linhas.append({"movimento": movimento, "saldo": corrente})
        corrente -= movimento.quantidade
    return linhas


# ---------- Cadastros (categorias e locais, numa tela só) ----------


@requer_modulo(Modulo.ESTOQUE)
def cadastros(request):
    qual = request.POST.get("cadastro", "")
    form_categoria = CategoriaProdutoForm(request.POST if qual == "categoria" else None)
    form_local = LocalEstoqueForm(request.POST if qual == "local" else None)
    if request.method == "POST":
        if qual == "categoria" and form_categoria.is_valid():
            form_categoria.save()
            messages.success(request, "Categoria salva.")
            return redirect("estoque:cadastros")
        if qual == "local" and form_local.is_valid():
            form_local.save()
            messages.success(request, "Local salvo.")
            return redirect("estoque:cadastros")
    valores = {lo["local"].pk: lo for lo in resumo_locais()}
    return render(
        request,
        "estoque/cadastros.html",
        {
            "categorias": CategoriaProduto.objects.annotate(
                total=Count("produtos"),
                ativos=Count("produtos", filter=Q(produtos__ativo=True)),
            ),
            "locais": [
                {"local": local, "resumo": valores.get(local.pk)}
                for local in LocalEstoque.objects.all()
            ],
            "form_categoria": form_categoria,
            "form_local": form_local,
        },
    )


# ---------- Movimentações ----------


OPERACOES = {
    "entrada": {
        "rotulo": "Entrada", "titulo": "Entrada de mercadoria",
        "acao": "Registrar entrada", "form": EntradaForm,
        "intro": "Compra que chegou: soma ao saldo do local e recalcula o custo médio.",
    },
    "saida": {
        "rotulo": "Saída", "titulo": "Saída de estoque",
        "acao": "Registrar saída", "form": SaidaForm,
        "intro": "O que saiu sem passar pela Loja ou pelo Restaurante — "
                 "consumo interno, perda, quebra, vencimento.",
    },
    "transferencia": {
        "rotulo": "Transferência", "titulo": "Transferência entre locais",
        "acao": "Transferir", "form": TransferenciaForm,
        "intro": "O produto muda de depósito. O saldo total da pousada não muda — "
                 "fica registrado dos dois lados.",
    },
    "ajuste": {
        "rotulo": "Ajuste", "titulo": "Ajuste de saldo",
        "acao": "Registrar ajuste", "form": AjusteForm,
        "intro": "O sistema passa a dizer o que a prateleira diz. A diferença "
                 "vira um movimento, com motivo e autor na trilha de auditoria.",
    },
}


def _executar(operacao, dados, usuario):
    if operacao == "entrada":
        registrar_entrada(
            dados["produto"], dados["local"], dados["quantidade"],
            dados["custo_unitario"], usuario, documento=dados["documento"],
            observacao=dados["observacao"], fornecedor=dados["fornecedor"],
        )
        return "Entrada registrada — saldo e custo médio atualizados."
    if operacao == "saida":
        registrar_saida(
            dados["produto"], dados["local"], dados["quantidade"], usuario,
            tipo=dados["tipo"], observacao=dados["observacao"],
        )
        return "Saída registrada."
    if operacao == "transferencia":
        transferir(
            dados["produto"], dados["origem"], dados["destino"],
            dados["quantidade"], usuario, observacao=dados["observacao"],
        )
        return "Transferência registrada nos dois locais."
    ajustar(
        dados["produto"], dados["local"], dados["quantidade"], usuario,
        motivo=dados["motivo"],
    )
    return "Ajuste registrado — operação auditada."


def _movimentar(request, operacao):
    config = OPERACOES[operacao]
    # Ação rápida da posição: "tirar deste produto, neste local" já chega
    # preenchida (?produto=&local=). Na transferência o local vira a origem.
    inicial = {}
    if request.GET.get("produto"):
        inicial["produto"] = request.GET["produto"]
    if request.GET.get("local"):
        campo = "origem" if operacao == "transferencia" else "local"
        inicial[campo] = request.GET["local"]
    form = config["form"](request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            sucesso = _executar(operacao, form.cleaned_data, request.user)
            messages.success(request, sucesso)
            return redirect("estoque:posicao")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))

    saldos = saldos_por_local()
    locais = _locais_ativos()
    return render(
        request,
        "estoque/movimentar.html",
        {
            "form": form,
            "operacao": operacao,
            "config": config,
            "operacoes": OPERACOES,
            "locais": locais,
            "locais_json": [{"id": lo.pk, "nome": lo.nome} for lo in locais],
            "produtos_json": _produtos_json(saldos),
            # Só a entrada tem fornecedor — as outras não pagam essa consulta.
            "fornecedores_json": (
                pessoas_agrupadas(fornecedores()) if operacao == "entrada" else []
            ),
            "escolhido": inicial.get("produto", ""),
            # Na transferência, o local que veio no atalho é a ORIGEM.
            "local_escolhido": inicial.get("local") or inicial.get("origem") or "",
        },
    )


@requer_modulo(Modulo.ESTOQUE)
def entrada(request):
    return _movimentar(request, "entrada")


@requer_modulo(Modulo.ESTOQUE)
def saida(request):
    return _movimentar(request, "saida")


@requer_modulo(Modulo.ESTOQUE)
def transferencia(request):
    return _movimentar(request, "transferencia")


@requer_modulo(Modulo.ESTOQUE)
def ajuste(request):
    return _movimentar(request, "ajuste")


# ---------- Inventário ----------


@requer_modulo(Modulo.ESTOQUE)
def inventarios(request):
    form = AbrirInventarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        local = form.cleaned_data["local"]
        inv = Inventario.objects.create(local=local, criado_por=request.user)
        # bulk_create (e não um create por produto): abrir a contagem de um
        # local com o catálogo inteiro são centenas de linhas. Quem abriu já
        # está na trilha pelo signal do próprio Inventário; os itens são a
        # fotografia do saldo, não decisão de ninguém.
        saldos = saldos_por_local()
        ItemInventario.objects.bulk_create([
            ItemInventario(
                inventario=inv, produto=produto,
                saldo_sistema=saldos.get((produto.pk, local.pk), ZERO),
                quantidade_contada=saldos.get((produto.pk, local.pk), ZERO),
            )
            for produto in Produto.objects.filter(ativo=True)
        ])
        messages.success(request, "Inventário aberto — faça a contagem.")
        return redirect("estoque:inventario", pk=inv.pk)

    diferenca = (
        F("itens__quantidade_contada") - F("itens__saldo_sistema")
    ) * F("itens__produto__custo_medio")
    lista = Inventario.objects.select_related("local", "criado_por").annotate(
        itens_total=Count("itens", distinct=True),
        itens_contados=Count("itens", filter=Q(itens__contado=True), distinct=True),
        valor_diferenca=Coalesce(
            Sum(diferenca, filter=Q(itens__contado=True), output_field=DecimalField()),
            ZERO, output_field=DecimalField(),
        ),
    )
    pagina = paginar(request, lista)
    return render(
        request,
        "estoque/inventarios.html",
        {
            "inventarios": pagina,
            "pagina": pagina,
            "form": form,
            "abertos": Inventario.objects.filter(
                status=Inventario.Status.ABERTO
            ).count(),
        },
    )


@requer_modulo(Modulo.ESTOQUE)
def inventario(request, pk):
    inv = get_object_or_404(Inventario.objects.select_related("local"), pk=pk)
    if request.method == "POST" and inv.status == Inventario.Status.ABERTO:
        invalidos = _salvar_contagem(request, inv)
        if invalidos:
            messages.error(
                request,
                "Contagem inválida (ignorada) em: " + ", ".join(invalidos[:8])
                + (" …" if len(invalidos) > 8 else "") + ". Use só números.",
            )
        if "aplicar" in request.POST:
            try:
                inv.aplicar(request.user, somente_contados=True)
                messages.success(
                    request, "Inventário aplicado — ajustes gerados e auditados."
                )
                return redirect("estoque:posicao")
            except ValidationError as erro:
                messages.error(request, " ".join(erro.messages))
        else:
            messages.success(request, "Contagem salva.")
        return redirect("estoque:inventario", pk=inv.pk)

    itens = list(
        inv.itens.select_related("produto", "produto__categoria").order_by(
            "produto__nome"
        )
    )
    contados = [item for item in itens if item.contado]
    divergentes = [item for item in contados if item.diferenca]
    return render(
        request,
        "estoque/inventario.html",
        {
            "inventario": inv,
            "itens": itens,
            "resumo": {
                "total": len(itens),
                "contados": len(contados),
                "falta": len(itens) - len(contados),
                "progresso": int(len(contados) / len(itens) * 100) if itens else 0,
                "divergentes": len(divergentes),
                "valor": sum((item.valor_diferenca for item in divergentes), ZERO),
            },
        },
    )


def _salvar_contagem(request, inv):
    """Grava o que foi digitado. Campo vazio = ainda não contado (fica fora do
    ajuste); número inválido não vira saldo em silêncio.

    Uma gravação só para a contagem inteira (`bulk_update`): a tela manda as
    centenas de linhas do local de uma vez. O que vale para a auditoria é o
    ajuste gerado no «Aplicar» — esse passa pelo motor e é registrado lá."""
    invalidos, mudados = [], []
    for item in inv.itens.select_related("produto"):
        bruto = request.POST.get(f"item_{item.pk}")
        if bruto is None:
            continue
        bruto = bruto.strip()
        if bruto == "":
            if item.contado:
                item.contado = False
                mudados.append(item)
            continue
        try:
            quantidade = Decimal(bruto.replace(",", "."))
        except (InvalidOperation, ValueError):
            invalidos.append(item.produto.nome)
            continue
        if quantidade < ZERO:
            invalidos.append(item.produto.nome)
            continue
        item.quantidade_contada, item.contado = quantidade, True
        mudados.append(item)
    if mudados:
        ItemInventario.objects.bulk_update(mudados, ["quantidade_contada", "contado"])
    return invalidos
