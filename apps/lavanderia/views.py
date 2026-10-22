from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.nucleo.models import FormaPagamento, Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .models import (
    ItemEnxoval,
    ItemOrdemLavanderia,
    MovimentoEnxoval,
    OrdemLavanderia,
    ServicoLavanderia,
)


def _data(txt):
    if not txt:
        return None
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


# ───────────────────────── (a) Serviço ao hóspede ─────────────────────────

@never_cache
@requer_modulo(Modulo.LAVANDERIA)
def painel(request):
    from apps.reservas.services import contas_abertas

    abertas = (
        OrdemLavanderia.objects.filter(status__in=OrdemLavanderia.FLUXO)
        .select_related("cliente", "conta__reserva__uh")
        .prefetch_related("itens")
    )
    return render(request, "lavanderia/painel.html", {
        "abertas": abertas,
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
    cliente = Pessoa.objects.filter(pk=request.POST.get("cliente") or None).first()
    try:
        ordem = services.abrir_ordem(
            request.user, cliente=cliente,
            rotulo=request.POST.get("rotulo", ""),
            prazo=_data(request.POST.get("prazo")),
            conta_id=request.POST.get("conta") or None,
        )
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("lavanderia:painel")
    return redirect("lavanderia:ordem", pk=ordem.pk)


def _contexto_ordem(request, ordem):
    contas = []
    if request.user.pode_acessar(Modulo.RESERVAS):
        from apps.reservas.services import contas_abertas

        contas = [
            {"id": c.pk, "rotulo": f"{c.reserva.uh.numero} — {c.reserva.hospede.nome}"}
            for c in contas_abertas()
        ]
    return {
        "ordem": ordem,
        "servicos": ServicoLavanderia.objects.filter(ativo=True),
        "formas": FormaPagamento.objects.filter(ativo=True),
        "contas": contas,
        "eh_gerente": eh_gerente(request.user),
    }


@requer_modulo(Modulo.LAVANDERIA)
def ordem(request, pk):
    o = get_object_or_404(OrdemLavanderia.objects.select_related("cliente", "conta__reserva__uh"), pk=pk)
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
        servico = ServicoLavanderia.objects.filter(pk=request.POST.get("servico_id") or None).first()
        try:
            services.adicionar_item(o, servico, request.POST.get("quantidade") or 1, request.user)
        except (ValidationError, AttributeError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Serviço inválido."
            return render(request, "lavanderia/partials/itens.html", {"ordem": o, "erro": msg})
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
def avancar(request, pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method == "POST":
        try:
            services.avancar_status(o)
            messages.success(request, f"Ordem agora está: {o.get_status_display()}.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("lavanderia:ordem", pk=pk)


@requer_modulo(Modulo.LAVANDERIA)
def entregar(request, pk):
    o = get_object_or_404(OrdemLavanderia, pk=pk)
    if request.method != "POST":
        return redirect("lavanderia:ordem", pk=pk)
    forma = FormaPagamento.objects.filter(pk=request.POST.get("forma") or None).first()
    try:
        services.entregar(
            o, request.user, request.POST.get("destino"),
            forma=forma, conta_id=request.POST.get("conta_id") or None,
            desconto=Decimal(request.POST.get("desconto") or 0),
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


@requer_modulo(Modulo.LAVANDERIA)
def historico(request):
    ordens = paginar(request, (
        OrdemLavanderia.objects.filter(
            status__in=[OrdemLavanderia.Status.ENTREGUE, OrdemLavanderia.Status.CANCELADA]
        )
        .select_related("cliente", "forma_pagamento")
        .prefetch_related("itens")
    ))
    return render(request, "lavanderia/historico.html", {"ordens": ordens, "pagina": ordens})


@requer_modulo(Modulo.LAVANDERIA)
def servicos(request):
    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        preco = request.POST.get("preco") or "0"
        if nome:
            try:
                ServicoLavanderia.objects.get_or_create(
                    nome=nome,
                    defaults={"preco": Decimal(preco.replace(",", ".")),
                              "unidade": request.POST.get("unidade") or "peca"},
                )
                messages.success(request, "Serviço salvo.")
            except Exception:
                messages.error(request, "Dados inválidos.")
        return redirect("lavanderia:servicos")
    return render(request, "lavanderia/servicos.html", {
        "servicos": ServicoLavanderia.objects.all(),
        "unidades": ServicoLavanderia.Unidade.choices,
    })


# ───────────────────────── (b) Rouparia interna ─────────────────────────

@requer_modulo(Modulo.LAVANDERIA)
def rouparia(request):
    return render(request, "lavanderia/rouparia.html", {
        "posicao": services.posicao_enxoval(),
        "itens": ItemEnxoval.objects.filter(ativo=True),
        "estados": MovimentoEnxoval.Estado.choices,
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
