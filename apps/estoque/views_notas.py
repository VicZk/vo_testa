"""Notas documentais, anexos privados e conferência de recebimentos."""

import uuid
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.nucleo.formularios import erros_do_formulario
from apps.nucleo.models import AnexoNotaEntrada, EmbalagemProduto, ItemRecebimentoNotaEntrada
from apps.nucleo.modulos import Modulo
from apps.nucleo.notas_entrada import (
    anexar_documento_nota,
    cadastrar_nota_entrada,
    itens_da_nota,
    notas_com_resumo,
    receber_nota_entrada,
)
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_modulo

from .forms_notas import (
    AnexosNotaForm,
    ItensNotaFormSet,
    NotaEntradaForm,
    ParcelasNotaFormSet,
    RecebimentoNotaForm,
)


def _render_form(request, template, contexto):
    if request.method == "POST" and request.headers.get("X-Form-Preserve") == "1":
        form, formset = contexto["form"], contexto.get("formset")
        erros = [erros_do_formulario(form)] if form.errors else []
        if formset is not None:
            erros.extend(str(erro) for erro in formset.non_form_errors())
            erros.extend(f"Item {indice}: {erros_do_formulario(item)}"
                         for indice, item in enumerate(formset.forms, 1)
                         if item.errors and not item.cleaned_data.get("DELETE"))
        if erros:
            return JsonResponse({"errors": erros}, status=422, headers={"Cache-Control": "no-store"})
    return render(request, template, contexto)


def _nota(pk):
    return get_object_or_404(notas_com_resumo().select_related("fornecedor", "criado_por"), pk=pk)


@requer_modulo(Modulo.ESTOQUE)
def notas(request):
    notas_qs = notas_com_resumo()
    busca = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    if busca:
        notas_qs = notas_qs.filter(Q(numero__icontains=busca) | Q(fornecedor_nome__icontains=busca)
                                  | Q(chave_acesso__icontains=busca))
    if estado == "pendente":
        notas_qs = notas_qs.filter(_tem_recebimentos=False)
    elif estado == "parcial":
        notas_qs = notas_qs.filter(_tem_recebimentos=True, _tem_pendencias=True)
    elif estado == "concluida":
        notas_qs = notas_qs.filter(_tem_recebimentos=True, _tem_pendencias=False)
    else:
        estado = ""
    return render(request, "estoque/notas_lista.html", {
        "pagina": paginar(request, notas_qs), "busca": busca, "estado": estado,
    })


@requer_modulo(Modulo.ESTOQUE)
def nota_nova(request):
    form = NotaEntradaForm(request.POST or None, request.FILES or None,
                           initial={"chave": uuid.uuid4(), "emissao": timezone.localdate()})
    formset = ItensNotaFormSet(request.POST or None, prefix="itens")
    if request.method == "POST":
        valido, itens_validos = form.is_valid(), formset.is_valid()
        if valido and itens_validos:
            dados = dict(form.cleaned_data)
            itens = [{nome: valor for nome, valor in item.cleaned_data.items() if nome != "DELETE"}
                     for item in formset.forms if item.cleaned_data and not item.cleaned_data.get("DELETE")]
            try:
                nota = cadastrar_nota_entrada(usuario=request.user, itens=itens, **dados)
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Nota registrada. O estoque será atualizado quando você receber os itens.")
                return redirect("estoque:nota", pk=nota.pk)
    embalagens = [{"id": item.pk, "produto": item.produto_id, "nome": item.nome,
                   "fator": str(item.fator), "unidade": item.produto.unidade}
                  for item in EmbalagemProduto.objects.filter(ativo=True, produto__ativo=True,
                      produto__usa_ficha_tecnica=False).select_related("produto")]
    return _render_form(request, "estoque/nota_cadastro.html", {
        "form": form, "formset": formset, "embalagens_data": embalagens,
    })


def _detalhe(request, nota, form=None):
    parcelas = ItemRecebimentoNotaEntrada.objects.select_related(
        "item", "movimento__local").prefetch_related("movimento__lotes__lote")
    return _render_form(request, "estoque/nota_detalhe.html", {
        "nota": nota, "itens": itens_da_nota(nota), "form": form or AnexosNotaForm(),
        "documentos": nota.documentos.defer("conteudo"),
        "recebimentos": nota.recebimentos.select_related("criado_por").prefetch_related(
            Prefetch("parcelas", queryset=parcelas)),
    })


@requer_modulo(Modulo.ESTOQUE)
def nota_detalhe(request, pk):
    return _detalhe(request, _nota(pk))


@requer_modulo(Modulo.ESTOQUE)
def nota_receber(request, pk):
    nota = _nota(pk)
    itens = list(itens_da_nota(nota).select_related("produto"))
    pendentes = [item for item in itens if item.quantidade_pendente > 0]
    form = RecebimentoNotaForm(request.POST or None, initial={
        "chave": uuid.uuid4(), "versao_conferida": nota.versao_recebimento,
    })
    formset = ParcelasNotaFormSet(request.POST or None, prefix="parcelas",
        initial=[{"item": item.pk} for item in pendentes], form_kwargs={"itens": itens})
    if request.method == "POST":
        valido, parcelas_validas = form.is_valid(), formset.is_valid()
        if valido and parcelas_validas:
            parcelas = [dict(item.cleaned_data) for item in formset.forms
                        if item.cleaned_data.get("quantidade") is not None]
            try:
                receber_nota_entrada(nota, parcelas=parcelas, usuario=request.user, **form.cleaned_data)
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Recebimento registrado. O estoque foi atualizado com os itens desta entrega.")
                return redirect("estoque:nota", pk=nota.pk)
    return _render_form(request, "estoque/nota_receber.html", {
        "nota": nota, "form": form, "formset": formset, "tem_pendencias": bool(pendentes),
    })


@requer_modulo(Modulo.ESTOQUE)
@require_POST
def nota_anexar(request, pk):
    nota = _nota(pk)
    form = AnexosNotaForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            with transaction.atomic():
                for documento in form.cleaned_data["documentos"]:
                    anexar_documento_nota(nota, usuario=request.user, documento_preparado=documento)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Anexos guardados nesta nota.")
            return redirect("estoque:nota", pk=nota.pk)
    return _detalhe(request, nota, form)


@requer_modulo(Modulo.ESTOQUE)
def nota_documento(request, pk, documento_id):
    documento = get_object_or_404(AnexoNotaEntrada, pk=documento_id, nota_id=pk)
    resposta = FileResponse(BytesIO(bytes(documento.conteudo)), as_attachment=True,
                            filename=documento.nome, content_type=documento.tipo)
    resposta["Cache-Control"] = "private, no-store"
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Security-Policy"] = "sandbox"
    return resposta
