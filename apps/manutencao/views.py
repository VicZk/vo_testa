from io import BytesIO

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.models import UH, Pessoa
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import eh_gerente, requer_gerencia, requer_modulo
from apps.nucleo.seletores import pessoas_agrupadas

from . import services
from .anexos import preparar_documento, salvar_documento
from .models import DocumentoOrdemServico, OrdemServico

Usuario = get_user_model()


def _prestadores_data():
    externos = Pessoa.objects.filter(ativo=True).filter(
        Q(fornecedor__isnull=False) | Q(agencia__isnull=False)
    )
    return pessoas_agrupadas(externos)


@requer_modulo(Modulo.MANUTENCAO)
def painel(request):
    situacoes = {"abertas": "Ordens abertas", "concluidas": "Ordens concluídas",
                 "canceladas": "Ordens canceladas", "todas": "Todas as ordens"}
    situacao = request.GET.get("situacao", "abertas")
    if situacao not in situacoes:
        situacao = "abertas"
    ordens = OrdemServico.objects.select_related("uh", "responsavel")
    if situacao == "abertas":
        ordens = ordens.filter(status__in=[OrdemServico.Status.ABERTA, OrdemServico.Status.EM_ANDAMENTO])
    elif situacao != "todas":
        ordens = ordens.filter(status=OrdemServico.Status.CONCLUIDA if situacao == "concluidas" else OrdemServico.Status.CANCELADA)
    busca = request.GET.get("q", "").strip()[:120]
    if busca:
        consulta = Q(titulo__icontains=busca) | Q(area__icontains=busca) | Q(uh__numero__icontains=busca) | Q(nota_fiscal__icontains=busca)
        numero = busca.lstrip("#")
        if numero.isascii() and numero.isdigit() and len(numero) < 19:
            consulta |= Q(pk=int(numero))
        ordens = ordens.filter(consulta)
    pagina = paginar(request, ordens)
    bloqueados = set(services.motivos_bloqueio())
    bloqueados.update(UH.objects.filter(status=UH.Status.BLOQUEADA).values_list("pk", flat=True))
    return render(request, "manutencao/painel.html", {
        "ordens": pagina, "pagina": pagina, "titulo_lista": situacoes[situacao],
        "situacao": situacao, "busca": busca,
        "bloqueados": len(bloqueados),
        "quartos": UH.objects.exclude(status=UH.Status.INATIVA).select_related("tipo"),
        "responsaveis": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        "prestadores_data": _prestadores_data(),
        "prioridades": OrdemServico.Prioridade.choices,
        "tipos": OrdemServico.Tipo.choices,
    })


@requer_modulo(Modulo.MANUTENCAO)
def nova(request):
    from .forms import NovaOSForm

    if request.method != "POST":
        return redirect("manutencao:painel")
    form = NovaOSForm(request.POST)
    if not form.is_valid():
        messages.error(request, erros_do_formulario(form))
        return redirect("manutencao:painel")
    try:
        ordem = services.abrir_os(request.user, **form.cleaned_data)
    except (ValidationError, ValueError) as erro:
        msg = " ".join(erro.messages) if isinstance(erro, ValidationError) else "Dados inválidos."
        messages.error(request, msg)
        return redirect("manutencao:painel")
    messages.success(request, f"OS #{ordem.pk} aberta.")
    return redirect("manutencao:detalhe", pk=ordem.pk)


@requer_modulo(Modulo.MANUTENCAO)
def detalhe(request, pk):
    ordem = get_object_or_404(
        OrdemServico.objects.select_related("uh", "responsavel", "criado_por"), pk=pk
    )
    return render(request, "manutencao/os_detalhe.html", {
        "os": ordem, "eh_gerente": eh_gerente(request.user),
        "documentos": ordem.documentos.defer("conteudo").select_related("enviado_por"),
    })


@requer_modulo(Modulo.MANUTENCAO)
def iniciar(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        try:
            services.iniciar_os(ordem, request.user)
            messages.success(request, "OS em andamento.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)


@requer_modulo(Modulo.MANUTENCAO)
def concluir(request, pk):
    from .forms import ConcluirOSForm

    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        form = ConcluirOSForm(request.POST)
        if not form.is_valid():
            messages.error(request, erros_do_formulario(form))
            return redirect("manutencao:detalhe", pk=pk)
        try:
            anexo = preparar_documento(request.FILES.get("anexo_nota_fiscal"))
            with transaction.atomic():
                # O serviço trava a OS. Documento e conclusão fazem parte da mesma
                # transação: uma falha não libera o quarto nem deixa custo parcial.
                proxima = services.concluir_os(ordem, request.user, **form.cleaned_data)
                salvar_documento(ordem, request.user, anexo)
            if proxima:
                messages.success(
                    request,
                    f"OS concluída. Próxima preventiva agendada para {proxima.agendada_para:%d/%m/%Y}.",
                )
            else:
                messages.success(request, "OS concluída.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)


@requer_modulo(Modulo.MANUTENCAO)
@require_POST
def anexar_documento(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    try:
        anexo = preparar_documento(request.FILES.get("anexo_nota_fiscal"))
        if anexo is None:
            raise ValidationError("Escolha o documento que deseja anexar.")
        salvar_documento(ordem, request.user, anexo)
        messages.success(request, "Documento anexado à OS.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    resposta = redirect("manutencao:detalhe", pk=pk)
    resposta["Location"] += "#documentos-os"
    return resposta


@requer_modulo(Modulo.MANUTENCAO)
def documento(request, pk, documento_id):
    anexo = get_object_or_404(DocumentoOrdemServico, pk=documento_id, ordem_id=pk)
    if not anexo.conteudo:
        raise Http404("Documento indisponível.")
    resposta = FileResponse(BytesIO(bytes(anexo.conteudo)), as_attachment=True,
                            filename=anexo.nome, content_type=anexo.tipo)
    resposta["Cache-Control"] = "private, no-store"
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Security-Policy"] = "sandbox"
    return resposta


@requer_modulo(Modulo.MANUTENCAO)
@requer_gerencia
def cancelar(request, pk):
    ordem = get_object_or_404(OrdemServico, pk=pk)
    if request.method == "POST":
        try:
            services.cancelar_os(ordem, request.user, request.POST.get("motivo", ""))
            messages.success(request, "OS cancelada.")
            return redirect("manutencao:painel")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return redirect("manutencao:detalhe", pk=pk)
