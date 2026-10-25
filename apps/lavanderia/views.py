from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, Round
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from apps.nucleo.models import FormaPagamento, Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas
from apps.nucleo.validadores import (
    decimal_valido,
    filtro_identificador,
    identificador_valido,
)

from . import services
from .icones import ESCOLHAS_ICONES_LAV
from .models import (
    ItemEnxoval,
    ItemOrdemLavanderia,
    MovimentoEnxoval,
    OrdemLavanderia,
    ServicoLavanderia,
)

ZERO = Decimal("0.00")


def _data(txt):
    if not txt:
        return None
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


def _numero(txt):
    """"1,5" → "1.5": o teclado do balcão é pt-BR, o `Decimal` só entende ponto.

    Sem isto, pesar 1,5 kg devolvia "informe um número" para quem digitou certo.
    """
    return str(txt if txt is not None else "").strip().replace(",", ".")


# ───────────────────────── (a) Serviço ao hóspede ─────────────────────────

# Rótulo do chip de cada etapa: "Recebidas 3", mas "Lavando 2" (o `|pluralize` do Django
# só acrescenta "s" e não serve para nenhum dos três).
ROTULOS_DA_FILA = {
    OrdemLavanderia.Status.RECEBIDA: "Recebidas",
    OrdemLavanderia.Status.LAVANDO: "Lavando",
    OrdemLavanderia.Status.PRONTA: "Prontas",
}


def _chips_da_fila(contagens, etapa):
    """Os filtros da fila, com a contagem de cada etapa; o perigo só nas atrasadas."""
    chips = [{"codigo": "", "rotulo": "Todas", "n": contagens["todas"], "perigo": False}]
    chips += [{"codigo": status.value, "rotulo": ROTULOS_DA_FILA[status],
               "n": contagens[status.value], "perigo": False}
              for status in OrdemLavanderia.FLUXO]
    chips.append({"codigo": services.ETAPA_ATRASADAS, "rotulo": "Atrasadas",
                  "n": contagens["atrasadas"], "perigo": bool(contagens["atrasadas"])})
    for chip in chips:
        chip["ativo"] = chip["codigo"] == etapa
    return chips


@never_cache
@requer_modulo(Modulo.LAVANDERIA)
def painel(request):
    from apps.reservas.services import contas_abertas

    etapa = request.GET.get("etapa") or ""
    if etapa not in services.ETAPAS_DA_FILA:
        etapa = ""
    kpis = services.painel_do_setor()
    return render(request, "lavanderia/painel.html", {
        "kpis": kpis,
        "filas": services.filas_de_producao(etapa or None),
        "etapa": etapa,
        # O cartão da fila escreve "Pronto hoje" em vez da data quando o prazo é hoje.
        "hoje": timezone.localdate(),
        "chips": _chips_da_fila(kpis["contagens"], etapa),
        "prazos": services.prazos_sugeridos(),
        "clientes": pessoas_agrupadas(),
        "tem_servico": ServicoLavanderia.objects.filter(ativo=True).exists(),
        "contas": contas_abertas() if request.user.pode_acessar(Modulo.RESERVAS) else [],
    })


@requer_modulo(Modulo.LAVANDERIA)
def abrir(request):
    if request.method != "POST":
        return redirect("lavanderia:painel")
    if request.POST.get("conta") and not request.user.pode_acessar(Modulo.RESERVAS):
        raise PermissionDenied
    try:
        cliente = Pessoa.objects.filter(pk=identificador_valido(request.POST.get("cliente"), opcional=True)).first()
        ordem = services.abrir_ordem(
            request.user, cliente=cliente,
            rotulo=request.POST.get("rotulo", ""),
            # Chip de prazo grava em `prazo`; "Outra data" manda `prazo_data`.
            prazo=_data(request.POST.get("prazo") or request.POST.get("prazo_data")),
            conta_id=request.POST.get("conta") or None,
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("lavanderia:painel")
    return redirect("lavanderia:ordem", pk=ordem.pk)


RECADO_PRONTA = ("Olá, {nome}! Sua roupa da lavanderia já está pronta — "
                 "pode retirar na recepção.")


def _contexto_ordem(request, ordem):
    tem_reservas = request.user.pode_acessar(Modulo.RESERVAS)
    contas = []
    if tem_reservas:
        from apps.reservas.services import contas_abertas

        contas = [
            {"id": c.pk, "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}"}
            for c in contas_abertas()
        ]
    # Sem o módulo Reservas não há a quem avisar pelo portal: o balcão segue sozinho.
    contato = {}
    if tem_reservas and ordem.conta_id and ordem.conta.reserva_id:
        from apps.reservas.services import contato_da_reserva

        contato = contato_da_reserva(ordem.conta.reserva_id)
    hoje = timezone.localdate()
    return {
        "ordem": ordem,
        "servicos": ServicoLavanderia.objects.filter(ativo=True),
        "formas": FormaPagamento.objects.filter(ativo=True),
        "contas": contas,
        "eh_gerente": eh_gerente(request.user),
        "trilha": services.trilha_da_ordem(ordem),
        "proximo": services.proximo_passo(ordem),
        "pode_entregar": ordem.status == OrdemLavanderia.Status.PRONTA,
        # Ordem sem peça lançada não avança (nem é cobrada): a tela apaga o botão do
        # próximo passo e diz o que falta, em vez de deixar a ordem chegar vazia.
        "vazia": not ordem.itens.exists(),
        "dias_atraso": (hoje - ordem.prazo).days if ordem.prazo and ordem.prazo < hoje
                       and ordem.em_producao else 0,
        "contato": contato,
        "recado": RECADO_PRONTA.format(nome=(contato.get("nome") or ordem.titulo)),
        # Qual das duas abas do balcão abre no celular: em "Pronta" não há mais o que
        # lançar, e o que o operador quer é cobrar — a cesta abre primeiro.
        "painel_inicial": ("carrinho" if ordem.status == OrdemLavanderia.Status.PRONTA
                           else "produtos"),
    }


@requer_modulo(Modulo.LAVANDERIA)
def ordem(request, pk):
    o = get_object_or_404(
        OrdemLavanderia.objects.select_related("cliente", "conta__reserva__uh"), pk=pk)
    return render(request, "lavanderia/ordem.html", _contexto_ordem(request, o))


@requer_modulo(Modulo.LAVANDERIA)
@requer_modulo(Modulo.RESERVAS)
def vincular(request, pk):
    if request.method == "POST":
        try:
            services.vincular_conta(get_object_or_404(OrdemLavanderia, pk=pk), request.POST.get("conta_id"), request.user)
            messages.success(request, "Ordem vinculada à estadia.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("lavanderia:ordem", pk=pk)


@requer_modulo(Modulo.LAVANDERIA)
def cupom(request, pk):
    """A ordem no cupom de 80 mm: na recepção da roupa, o comprovante que fica com o
    hóspede (o que entrou e quando fica pronto); na entrega, o recibo."""
    from django.utils.timezone import localtime

    from apps.nucleo.formatos import qtd_br

    o = get_object_or_404(
        OrdemLavanderia.objects.select_related("cliente", "forma_pagamento", "criado_por"),
        pk=pk,
    )
    itens = list(o.itens.all())
    subtotal = sum((i.subtotal for i in itens), Decimal("0.00"))
    meta = [("Recebida", f"{localtime(o.recebida_em):%d/%m/%Y %H:%M}")]
    if o.prazo and o.status != OrdemLavanderia.Status.ENTREGUE:
        meta.append(("Pronta em", f"{o.prazo:%d/%m/%Y}"))
    if o.observacao:
        # O recado da recepção vai impresso com a roupa, não fica só na tela.
        meta.append(("Observação", o.observacao))
    if o.entregue_em:
        meta.append(("Entregue", f"{localtime(o.entregue_em):%d/%m/%Y %H:%M}"))
    meta.append(("Atendente", o.criado_por.get_username()))
    pagamento, aviso = "", "Não é documento fiscal"
    if o.status == OrdemLavanderia.Status.CANCELADA:
        pagamento = "ORDEM CANCELADA"
    elif o.status != OrdemLavanderia.Status.ENTREGUE:
        aviso = "Comprovante de recebimento. Não é documento fiscal."
    elif o.destino == OrdemLavanderia.Destino.CONTA:
        pagamento = f"Lançado na conta: {o.conta_ref}"
    elif o.forma_pagamento:
        pagamento = f"Pago com {o.forma_pagamento.nome}"
    cupom = {
        "titulo": o.titulo, "origem": f"Lavanderia #{o.pk}", "meta": meta,
        "itens": [{"qtd": qtd_br(i.quantidade), "descricao": i.descricao,
                   "unitario": i.preco_unitario, "subtotal": i.subtotal} for i in itens],
        "subtotal": subtotal, "desconto": o.desconto, "total": subtotal - o.desconto,
        "pagamento": pagamento, "aviso": aviso,
        "voltar": reverse("lavanderia:ordem", args=[o.pk]),
    }
    return render(request, "componentes/cupom.html",
                  {"cupom": cupom, "imprimir": request.GET.get("imprimir") == "1"})


@requer_modulo(Modulo.LAVANDERIA)
def add_item(request, pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method == "POST":
        try:
            servico = ServicoLavanderia.objects.filter(pk=identificador_valido(request.POST.get("servico_id")), ativo=True).first()
            if not servico:
                raise ValidationError("Serviço inválido.")
            services.adicionar_item(o, servico, _numero(request.POST.get("quantidade", 1)), request.user)
        except (ValidationError, AttributeError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Serviço inválido."
            return render(request, "lavanderia/partials/itens.html", {"ordem": o, "erro": msg})
    return render(request, "lavanderia/partials/itens.html", {"ordem": o})


@requer_modulo(Modulo.LAVANDERIA)
def item_qtd(request, pk, item_pk):
    """O −/+ da cesta e o campo de quilo: DEFINE a quantidade (zero remove a linha)."""
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    item = get_object_or_404(ItemOrdemLavanderia, pk=item_pk, ordem=o)
    if request.method == "POST":
        try:
            services.definir_quantidade(item, _numero(request.POST.get("quantidade")), request.user)
        except ValidationError as erro:
            return render(request, "lavanderia/partials/itens.html",
                          {"ordem": o, "erro": " ".join(erro.messages)})
    return render(request, "lavanderia/partials/itens.html", {"ordem": o})


@requer_modulo(Modulo.LAVANDERIA)
def remover_item(request, pk, item_pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    item = get_object_or_404(ItemOrdemLavanderia, pk=item_pk, ordem=o)
    if request.method == "POST":
        try:
            services.remover_item(item)
        except ValidationError:
            pass
    return render(request, "lavanderia/partials/itens.html", {"ordem": o})


@requer_modulo(Modulo.LAVANDERIA)
def observacao(request, pk):
    """Recado da recepção, salvo por HTMX quando o campo perde o foco."""
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method != "POST":
        return redirect("lavanderia:ordem", pk=pk)
    try:
        services.definir_observacao(o, request.POST.get("observacao", ""), request.user)
        recado = "Observação salva."
    except ValidationError as erro:
        recado = " ".join(erro.messages)
    return render(request, "lavanderia/partials/observacao_status.html", {"recado": recado})


@requer_modulo(Modulo.LAVANDERIA)
def avancar(request, pk):
    """Um passo da produção. Volta para a FILA quando o botão foi o do cartão."""
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method == "POST":
        try:
            # `de` é o status que a tela mostrava: o segundo clique não pula dois passos.
            # Sem ele o service compararia o status com ele mesmo e a proteção virava
            # enfeite — então aqui o campo é obrigatório (as duas telas o mandam).
            etapa = request.POST.get("de") or ""
            if not etapa:
                raise ValidationError("Atualize a tela antes de avançar a ordem.")
            services.avancar_status(o, esperado=etapa)
            messages.success(request, f"Ordem agora está: {o.get_status_display()}.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    if request.POST.get("voltar") == "painel":
        # Avançar pelo cartão é trabalho em série no tablet: a fila continua na tela,
        # com o mesmo filtro de etapa. Abrir a ordem a cada toque custava uma volta.
        etapa = request.POST.get("etapa") or ""
        destino = reverse("lavanderia:painel")
        return redirect(f"{destino}?etapa={etapa}" if etapa in services.ETAPAS_DA_FILA
                        else destino)
    return redirect("lavanderia:ordem", pk=pk)


@requer_modulo(Modulo.LAVANDERIA)
def entregar(request, pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method != "POST":
        return redirect("lavanderia:ordem", pk=pk)
    try:
        destino = request.POST.get("destino") or ""
        if destino not in OrdemLavanderia.Destino.values:
            raise ValidationError("Escolha como cobrar: pagamento imediato ou conta do quarto.")
        if destino == OrdemLavanderia.Destino.CONTA and not request.user.pode_acessar(Modulo.RESERVAS):
            raise PermissionDenied
        desconto = decimal_valido(request.POST.get("desconto") or 0, nome="Desconto")
        # A tela só mostra o campo de desconto à gerência ("Desconto só com a
        # gerência."): a promessa é cumprida aqui, não no template — o POST de quem não
        # é gerente chegava com desconto e abatia o dinheiro do mesmo jeito.
        if desconto > ZERO and not eh_gerente(request.user):
            raise PermissionDenied
        forma = FormaPagamento.objects.filter(pk=identificador_valido(request.POST.get("forma"), opcional=True), ativo=True).first()
        services.entregar(
            o, request.user, destino,
            forma=forma, conta_id=request.POST.get("conta_id") or None,
            desconto=desconto,
            # Entrega antes de ficar pronta é exceção confirmada na tela (fica na trilha).
            confirmar=request.POST.get("confirmar") == "1",
        )
        messages.success(request, f"Lavanderia #{o.pk} entregue.")
        return redirect("lavanderia:painel")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("lavanderia:ordem", pk=pk)


@requer_modulo(Modulo.LAVANDERIA)
@requer_gerencia
def cancelar(request, pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_ordem(o, request.user, request.POST.get("motivo", ""))
            messages.success(request, "Ordem cancelada.")
            return redirect("lavanderia:painel")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("lavanderia:ordem", pk=pk)


# Chips de período do histórico (o recorte de cada um está em `_inicio_do_periodo`).
PERIODOS = (("hoje", "Hoje"), ("7", "7 dias"), ("mes", "Este mês"), ("tudo", "Tudo"))
SITUACOES = (("", "Todas"), (OrdemLavanderia.Status.ENTREGUE.value, "Entregues"),
             (OrdemLavanderia.Status.CANCELADA.value, "Canceladas"))


def _numeros_do_historico(consulta):
    """Os quatro números do topo do histórico — somados NO BANCO.

    Percorrer a consulta em Python trazia todas as ordens do recorte (e todos os seus
    itens, pelo `prefetch_related`) para a memória a cada carregamento: com o chip
    "Tudo", o histórico inteiro. O item é arredondado a duas casas antes de somar, como
    faz `ItemOrdemLavanderia.subtotal`, para o número do topo fechar com o da linha; o
    desconto sai numa consulta própria, porque o `join` dos itens repetiria a ordem.
    `faturamento_periodo` continua sendo a interface pública dos Relatórios.
    """
    entregue = Q(status=OrdemLavanderia.Status.ENTREGUE)
    no_caixa = Q(destino=OrdemLavanderia.Destino.CAIXA)
    ordens = consulta.aggregate(
        quantas=Count("pk"),
        desconto_caixa=Coalesce(Sum("desconto", filter=entregue & no_caixa), ZERO),
        desconto_conta=Coalesce(Sum("desconto", filter=entregue & ~no_caixa), ZERO),
    )
    pecas = Round(F("quantidade") * F("preco_unitario"), 2)
    itens = (ItemOrdemLavanderia.objects
             .filter(ordem__in=consulta.filter(entregue).order_by().values("pk"))
             .aggregate(
                 caixa=Coalesce(Sum(pecas, filter=Q(ordem__destino=OrdemLavanderia.Destino.CAIXA)), ZERO),
                 conta=Coalesce(Sum(pecas, filter=~Q(ordem__destino=OrdemLavanderia.Destino.CAIXA)), ZERO),
             ))
    caixa = itens["caixa"] - ordens["desconto_caixa"]
    conta = itens["conta"] - ordens["desconto_conta"]
    return {"ordens": ordens["quantas"], "total": caixa + conta,
            "caixa": caixa, "conta": conta}


def _inicio_do_periodo(periodo, hoje):
    if periodo == "hoje":
        return hoje
    if periodo == "7":
        return hoje - timedelta(days=6)
    if periodo == "mes":
        return hoje.replace(day=1)
    return None


@requer_modulo(Modulo.LAVANDERIA)
def historico(request):
    periodo = request.GET.get("periodo") or "mes"
    if periodo not in [codigo for codigo, _ in PERIODOS]:
        periodo = "mes"
    situacao = request.GET.get("situacao") or ""
    if situacao not in [codigo for codigo, _ in SITUACOES]:
        situacao = ""
    busca = (request.GET.get("busca") or "").strip()[:80]

    encerradas = [OrdemLavanderia.Status.ENTREGUE, OrdemLavanderia.Status.CANCELADA]
    consulta = (
        OrdemLavanderia.objects.filter(status__in=[situacao] if situacao else encerradas)
        .select_related("cliente", "forma_pagamento")
        .prefetch_related("itens")
        # A ordem cancelada não tem data de entrega: o "quando" dela é a recepção.
        .annotate(encerrada_em=Coalesce("entregue_em", "recebida_em"))
        .order_by("-encerrada_em", "-pk")
    )
    hoje = timezone.localdate()
    inicio = _inicio_do_periodo(periodo, hoje)
    if inicio:
        consulta = consulta.filter(encerrada_em__date__gte=inicio)
    if busca:
        numero = busca.lstrip("#")
        por_id = Q(pk=numero) if numero.isdigit() else Q()
        consulta = consulta.filter(
            por_id | Q(rotulo__icontains=busca) | Q(cliente__nome__icontains=busca)
            | Q(conta_ref__icontains=busca)
        )

    pagina = paginar(request, consulta)
    return render(request, "lavanderia/historico.html", {
        "ordens": pagina, "pagina": pagina,
        "periodos": [{"codigo": c, "rotulo": r, "ativo": c == periodo}
                     for c, r in PERIODOS],
        "situacoes": [{"codigo": c, "rotulo": r, "ativo": c == situacao}
                      for c, r in SITUACOES],
        "periodo": periodo, "situacao": situacao, "busca": busca,
        "kpis": _numeros_do_historico(consulta),
    })


@requer_modulo(Modulo.LAVANDERIA)
def servicos(request):
    """Tabela de preços: cria sem `pk`, ALTERA com `pk`.

    O `get_or_create` antigo respondia "Serviço salvo." e descartava o preço novo quando
    o nome já existia — sucesso falso. Agora nome repetido é erro na cara do operador.
    """
    if request.method == "POST":
        try:
            pk = identificador_valido(request.POST.get("pk"), opcional=True)
            servico = get_object_or_404(ServicoLavanderia, pk=pk) if pk else None
            services.salvar_servico(
                servico, request.user,
                nome=request.POST.get("nome", ""),
                unidade=request.POST.get("unidade") or ServicoLavanderia.Unidade.PECA,
                preco=request.POST.get("preco") or "0",
                icone=request.POST.get("icone") or "",
            )
            messages.success(request, "Serviço atualizado." if pk else "Serviço cadastrado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        return redirect("lavanderia:servicos")
    editar = ServicoLavanderia.objects.filter(
        pk=filtro_identificador(request.GET.get("editar"))).first()
    return render(request, "lavanderia/servicos.html", {
        "servicos": ServicoLavanderia.objects.all(),
        "unidades": ServicoLavanderia.Unidade.choices,
        "escolhas_icones": ESCOLHAS_ICONES_LAV,
        "editar": editar,
    })


@requer_modulo(Modulo.LAVANDERIA)
def servico_salvar(request, pk):
    """Ações da LINHA do quadro: desativar e reativar.

    Editar é o formulário de cima (`servicos`), que recebe a linha inteira. Havia aqui
    um ramo "editar" que a tela nunca usava e que gravava `icone=""` — isto é, limpava o
    desenho escolhido — sempre que o POST não trouxesse o campo.
    """
    servico = get_object_or_404(ServicoLavanderia, pk=pk)
    if request.method == "POST":
        acao = request.POST.get("acao") or ""
        try:
            if acao not in ("desativar", "reativar"):
                raise ValidationError("Ação inválida para a linha do quadro.")
            services.salvar_servico(servico, request.user, ativo=acao == "reativar")
            messages.success(request, "Serviço reativado." if acao == "reativar"
                             else "Serviço desativado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("lavanderia:servicos")


# ───────────────────────── (b) Rouparia interna ─────────────────────────

# Teto de linhas por lote: a tela marca uma caixinha por item de enxoval (dezenas, não
# milhares). Acima disto o POST é recusado — nunca cortado em silêncio.
LIMITE_DO_LOTE = 200

# Chips de período do extrato: os mesmos do histórico, mais a data livre. O livro-razão
# abre em "Tudo" porque nada nele se apaga — quem quer recorte usa os chips.
OUTRO_PERIODO = "outro"
PERIODOS_DO_EXTRATO = PERIODOS + ((OUTRO_PERIODO, "Outro período"),)

@requer_modulo(Modulo.LAVANDERIA)
def rouparia(request):
    posicao = services.posicao_enxoval()
    quartos = services.quartos_ativos()
    Estado = MovimentoEnxoval.Estado
    return render(request, "lavanderia/rouparia.html", {
        "posicao": posicao,
        "itens": ItemEnxoval.objects.filter(ativo=True),
        "estados": [(codigo, services.rotulo_estado(codigo))
                    for codigo, _ in Estado.choices],
        "kpis": {
            "limpa": sum(linha["estados"][Estado.LIMPA] for linha in posicao),
            "fora": sum(linha["fora"] for linha in posicao),
            "suja": sum(linha["estados"][Estado.SUJA] for linha in posicao),
            "abaixo": sum(1 for linha in posicao if linha["abaixo_minimo"]),
        },
        "acoes_lote": [(codigo, rotulo) for codigo, (rotulo, _)
                       in services.ACOES_DO_LOTE.items()],
        "quartos": quartos,
        # Alvo já preenchido no cadastro de um item novo (quartos × peças por faxina).
        "alvo_novo": quartos * services.POR_FAXINA_PADRAO,
        "por_faxina_padrao": services.POR_FAXINA_PADRAO,
    })


@requer_modulo(Modulo.LAVANDERIA)
def rouparia_lote(request):
    """Mesma quantidade nas linhas marcadas, numa transação: tudo ou nada."""
    if request.method != "POST":
        return redirect("lavanderia:rouparia")
    try:
        marcados = request.POST.getlist("itens")
        if len(marcados) > LIMITE_DO_LOTE:
            raise ValidationError(f"Selecione no máximo {LIMITE_DO_LOTE} itens por lote.")
        ids = [identificador_valido(valor, nome="Item") for valor in marcados]
        itens = list(ItemEnxoval.objects.filter(pk__in=set(ids), ativo=True))
        # "Tudo ou nada" vale também para a lista: item desativado em outra aba (ou id
        # que não existe mais) derruba o lote, em vez de sair do movimento calado.
        if len(itens) != len(set(ids)):
            raise ValidationError("Algum item saiu da lista. Atualize a tela e marque de novo.")
        movidos = services.mover_lote(itens, request.POST.get("acao"),
                                      request.POST.get("quantidade") or 0, request.user)
        quantas = len(movidos)
        messages.success(request, f"{quantas} ite{'ns' if quantas > 1 else 'm'}: "
                                  "movimento registrado.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("lavanderia:rouparia")


@requer_modulo(Modulo.LAVANDERIA)
def extrato(request):
    """Livro-razão do enxoval: quem moveu o que, quando e por quê.

    O período vem em chip, como no histórico: o `<input type=date>` cru mostra
    mm/dd/yyyy no Chrome em inglês e não há como forçar pt-BR, então o caminho comum
    não passa pelo campo de data — ele fica atrás de «Outro período».
    """
    estado = request.GET.get("estado") or ""
    if estado not in MovimentoEnxoval.Estado.values:
        estado = ""
    item = filtro_identificador(request.GET.get("item"))
    de, ate = _data(request.GET.get("de")), _data(request.GET.get("ate"))
    periodo = request.GET.get("periodo") or (OUTRO_PERIODO if de or ate else "tudo")
    if periodo not in [codigo for codigo, _ in PERIODOS_DO_EXTRATO]:
        periodo = "tudo"
    if periodo != OUTRO_PERIODO:
        de, ate = _inicio_do_periodo(periodo, timezone.localdate()), None
    movimentos = services.extrato_enxoval(item=item, estado=estado or None, de=de, ate=ate)
    pagina = paginar(request, movimentos)
    return render(request, "lavanderia/extrato.html", {
        "pagina": pagina,
        # Motivo nunca cru na tela: "envio_lavagem" → "Envio para lavagem".
        "linhas": [{"mov": mov, "motivo": services.rotulo_motivo(mov.motivo),
                    "estado": services.rotulo_estado(mov.estado)} for mov in pagina],
        "itens": ItemEnxoval.objects.all(),
        "estados": [(codigo, services.rotulo_estado(codigo))
                    for codigo in MovimentoEnxoval.Estado.values],
        "periodos": [{"codigo": codigo, "rotulo": rotulo, "ativo": codigo == periodo}
                     for codigo, rotulo in PERIODOS_DO_EXTRATO],
        "periodo": periodo, "outro_periodo": OUTRO_PERIODO,
        "filtros": {"item": item or "", "estado": estado,
                    "de": de.isoformat() if de and periodo == OUTRO_PERIODO else "",
                    "ate": ate.isoformat() if ate else ""},
    })


@requer_modulo(Modulo.LAVANDERIA)
def rouparia_item(request):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        if nome:
            ItemEnxoval.objects.get_or_create(nome=nome, defaults={
                "minimo": int(request.POST.get("minimo") or 0),
                "por_faxina": int(request.POST.get("por_faxina") or 0),
                "unidade": request.POST.get("unidade") or "peça",
            })
            messages.success(request, "Item de enxoval cadastrado.")
    return redirect("lavanderia:rouparia")


@requer_modulo(Modulo.LAVANDERIA)
def rouparia_mover(request):
    if request.method != "POST":
        return redirect("lavanderia:rouparia")
    item = get_object_or_404(ItemEnxoval, pk=request.POST.get("item") or None)
    acao = request.POST.get("acao")
    qtd = request.POST.get("quantidade") or 0
    mapa = {
        "adquirir": lambda: services.adquirir(item, qtd, request.user),
        "distribuir": lambda: services.distribuir(item, qtd, request.user),
        "coletar": lambda: services.coletar_suja(item, qtd, request.user),
        "enviar": lambda: services.enviar_lavar(item, qtd, request.user),
        "receber": lambda: services.receber_limpo(item, qtd, request.user),
    }
    try:
        if acao == "baixar":
            services.baixar(item, qtd, request.POST.get("estado"),
                            request.POST.get("motivo", "desgaste"), request.user)
        elif acao in mapa:
            mapa[acao]()
        else:
            raise ValidationError("Ação inválida.")
        messages.success(request, f"{item.nome}: movimento registrado.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    except (ValueError, TypeError):   # quantidade não-numérica → sem 500
        messages.error(request, "Quantidade inválida. Informe um número inteiro.")
    return redirect("lavanderia:rouparia")
