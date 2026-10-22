import json

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.nucleo.models import Produto, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.validadores import identificador_valido

from . import services
from .forms import ConfigFiscalProdutoForm
from .models import ConfigFiscalProduto, DocumentoFiscal


@never_cache
@requer_modulo(Modulo.FISCAL)
@requer_gerencia
def produtos(request):
    from django.core.paginator import Paginator
    busca = request.GET.get("q", "").strip()[:120]
    qs = Produto.objects.filter(natureza="consumo").select_related("config_fiscal").order_by("nome", "pk")
    if busca:
        qs = qs.filter(nome__icontains=busca)
    return render(request, "fiscal/produtos.html", {"pagina": Paginator(qs, 50).get_page(request.GET.get("page")), "busca": busca})


@never_cache
@requer_modulo(Modulo.FISCAL)
@requer_gerencia
def produto(request, pk):
    item = get_object_or_404(Produto, pk=pk, natureza="consumo")
    configuracao = ConfigFiscalProduto.objects.filter(produto=item).first() or ConfigFiscalProduto(produto=item)
    form = ConfigFiscalProdutoForm(request.POST if request.method == "POST" else None, instance=configuracao)
    if request.method == "POST" and form.is_valid():
        configuracao = form.save()
        registrar_auditoria(request.user, "configuracao_fiscal_produto", configuracao, {"produto_id": item.pk})
        messages.success(request, "Cadastro fiscal salvo. Documentos já emitidos mantêm os dados registrados na emissão.")
        return redirect("fiscal:produtos")
    return render(request, "fiscal/produto.html", {"produto": item, "form": form})


@never_cache
@requer_modulo(Modulo.FISCAL)
def painel(request):
    docs = DocumentoFiscal.objects.select_related("tomador", "criado_por")[:60]
    return render(request, "fiscal/painel.html", {
        "documentos": docs,
        "gateway": getattr(settings, "FISCAL_GATEWAY", "simulado"),
        "eh_gerente": eh_gerente(request.user),
        "configuracao": services.configuracao(),
    })


@requer_modulo(Modulo.FISCAL)
def detalhe(request, pk):
    doc = get_object_or_404(
        DocumentoFiscal.objects.select_related("tomador", "criado_por")
        .prefetch_related("eventos"), pk=pk
    )
    return render(request, "fiscal/detalhe.html", {
        "doc": doc, "eh_gerente": eh_gerente(request.user),
    })


@requer_modulo(Modulo.FISCAL)
def emitir_nfse(request):
    """Emite a NFS-e da hospedagem a partir da conta (chamado do detalhe da reserva)."""
    if request.method == "POST":
        try:
            if not modulo_ativo(Modulo.RESERVAS) or not request.user.pode_acessar(Modulo.RESERVAS):
                return HttpResponseForbidden("Sem acesso à conta de hospedagem.")
            doc = services.emitir_nfse_da_conta(request.POST.get("conta_id"), request.user, request.POST.get("codigo_servico"))
            messages.success(request, f"NFS-e {doc.get_status_display().lower()} (#{doc.pk}).")
            return redirect("fiscal:detalhe", pk=doc.pk)
        except (ValidationError, NotImplementedError) as erro:
            msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else str(erro)
            messages.error(request, msg)
    return redirect("fiscal:painel")


@requer_modulo(Modulo.FISCAL)
@requer_modulo(Modulo.RESERVAS)
def preparar_conta(request, pk):
    from apps.reservas.models import ContaHospedagem

    from .servicos import classificar, resumo
    conta = get_object_or_404(ContaHospedagem.objects.select_related("reserva__hospede","grupo__titular"),pk=pk)
    if request.method == "POST":
        try:
            if request.POST.get("conferido") != "sim":
                raise ValidationError("Confirme a classificação com o responsável fiscal.")
            codigos = {chave.removeprefix("codigo-"):valor for chave,valor in request.POST.items() if chave.startswith("codigo-")}
            classificar(identificador_valido(pk), codigos, request.user)
            messages.success(request,"Classificação registrada. Confira os valores antes de emitir.")
            return redirect("fiscal:preparar_conta",pk=pk)
        except ValidationError as erro:
            messages.error(request," ".join(erro.messages))
    try:
        dados = resumo(conta)
    except ValidationError as erro:
        messages.error(request," ".join(erro.messages))
        dados = {"grupos":[],"revisao":[],"pendentes":[True]}
    return render(request,"fiscal/preparar_conta.html",{"conta":conta, "dados":dados,"eh_gerente":eh_gerente(request.user)})


@csrf_exempt
@require_POST
def webhook(request):
    """Recebe o retorno do Focus NFe (autorização/cancelamento da nota) e atualiza o
    documento (status + PDF/DANFSE + XML). Configurar esta URL no painel do Focus."""
    # Valida o header de autorização (mesmo segredo posto na 'Chave de Autorização' do Focus).
    import hmac
    esperado = getattr(settings, "FISCAL_WEBHOOK_TOKEN", "")
    if not esperado:
        # Gateway real sem token = webhook aberto. Recusa até configurar o segredo.
        return JsonResponse({"erro": "webhook não configurado"}, status=503)
    recebido = request.headers.get("Authorization", "")
    if esperado and not hmac.compare_digest(recebido, esperado):
        return JsonResponse({"erro": "não autorizado"}, status=401)
    try:
        if len(request.body) > 65536:
            raise ValueError()
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError()
        doc = services.processar_retorno_focus(payload)
    except (ValueError, UnicodeDecodeError, ValidationError):
        return JsonResponse({"erro": "retorno fiscal inválido"}, status=400)
    if not doc:
        return JsonResponse({"erro": "documento (ref) não encontrado"}, status=404)
    return JsonResponse({"ok": True, "status": doc.status})


@requer_modulo(Modulo.FISCAL)
@requer_gerencia
def cancelar(request, pk):
    doc = get_object_or_404(DocumentoFiscal, pk=pk)
    if request.method == "POST":
        try:
            doc = services.cancelar(doc, request.user, request.POST.get("motivo", ""))
            if doc.status == DocumentoFiscal.Status.CANCELADA:
                messages.success(request, "Cancelamento confirmado pelo provedor.")
            else:
                messages.info(request, "Há uma operação em andamento. Consulte o documento para conferir o resultado.")
        except (ValidationError, NotImplementedError) as erro:
            messages.error(request, str(getattr(erro, "messages", [str(erro)])[0]
                                        if isinstance(erro, ValidationError) else erro))
    return redirect("fiscal:detalhe", pk=pk)


@requer_modulo(Modulo.FISCAL)
@require_POST
def atualizar(request, pk):
    doc = get_object_or_404(DocumentoFiscal, pk=pk)
    try:
        acao = {"reenviar": services.reenviar, "corrigir": services.corrigir}.get(request.POST.get("acao"), services.consultar)
        if request.POST.get("acao") == "corrigir" and not eh_gerente(request.user):
            return HttpResponseForbidden("Somente a gerência pode reenviar uma emissão corrigida.")
        doc = acao(doc)
        messages.info(request, f"Situação fiscal: {doc.get_status_display().lower()}.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("fiscal:detalhe", pk=pk)


@requer_modulo(Modulo.FISCAL)
@require_POST
def emitir_consumo(request, origem, pk):
    from .consumo import emitir_origem
    modulo = {"venda":Modulo.LOJA,"comanda":Modulo.RESTAURANTE}.get(origem)
    if modulo is None or not modulo_ativo(modulo) or not request.user.pode_acessar(modulo):
        return HttpResponseForbidden("Sem acesso à origem da venda.")
    try:
        doc = emitir_origem(origem, pk, request.user, request.POST.get("pix_modalidade", ""))
        return redirect("fiscal:detalhe", pk=doc.pk)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
        return redirect("loja:venda" if origem == "venda" else "restaurante:comanda", pk=pk)
