"""Aprovação de LPs: lista, envio, prévia, comentários e publicação (equipe)."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.nucleo.paginacao import paginar
from apps.nucleo.permissoes import requer_modulo

from . import services_lp
from .forms_lp import ComentarioLPForm, NovaLPForm, NovaVersaoForm, PublicarLPForm
from .models import AprovacaoLP, ComentarioLP

# O HTML da LP vem de fora e tem script. Servido no mesmo endereço do CRM, rodaria com
# a sessão de quem abriu (S-A3). O `sandbox` do CSP põe a página numa origem opaca: o
# script roda, mas não lê cookie, não chama o CRM como o usuário e não envia formulário
# ao CRM. A moldura da prévia repete o sandbox no <iframe>.
CSP_PREVIA = ("sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox; "
              "frame-ancestors 'self'")


def resposta_previa(versao):
    resposta = HttpResponse(versao.html, content_type="text/html; charset=utf-8")
    resposta["X-Frame-Options"] = "SAMEORIGIN"  # só a moldura da própria prévia
    resposta["Content-Security-Policy"] = CSP_PREVIA
    # A política geral do CRM só observaria (e reportaria) o que a LP carrega de fora.
    resposta["Content-Security-Policy-Report-Only"] = "frame-ancestors 'self'"
    resposta["X-Robots-Tag"] = "noindex, nofollow"
    resposta["Referrer-Policy"] = "no-referrer"
    resposta["Cache-Control"] = "private, no-store"
    return resposta


def contexto_revisao(request, aprovacao, *, pagina_url, form=None):
    """O que a prévia mostra, igual para a equipe e para o link: versão escolhida
    (?v=), as versões, os comentários e os pedidos de ajuste em aberto."""
    versoes = list(aprovacao.versoes.only("id", "numero", "nota", "nome_arquivo", "tamanho",
                                          "enviada_em", "enviada_por"))
    ultima = versoes[0] if versoes else None
    try:
        numero = int(request.GET.get("v") or (ultima.numero if ultima else 0))
    except ValueError:
        numero = ultima.numero if ultima else 0
    versao = next((v for v in versoes if v.numero == numero), ultima)
    comentarios = list(aprovacao.comentarios.select_related("versao").order_by("-em", "-id"))
    decidir = (versao is not None and versao.numero == ultima.numero
               and aprovacao.situacao not in (AprovacaoLP.Situacao.APROVADA,
                                              AprovacaoLP.Situacao.PUBLICADA))
    return {
        "aprovacao": aprovacao, "versoes": versoes, "versao": versao, "ultima": ultima,
        "comentarios": comentarios, "pode_decidir": decidir,
        "ajustes_abertos": sum(1 for c in comentarios
                               if c.tipo == ComentarioLP.Tipo.AJUSTE and not c.resolvido),
        "pagina_url": pagina_url(versao.numero) if versao else "",
        "form_comentario": form or ComentarioLPForm(initial={
            "versao": versao.numero if versao else 1,
            "nome": request.COOKIES.get("lp_revisor", "")[:80]}),
        "limite_texto": services_lp.LIMITE_TEXTO,
    }


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def lps(request):
    situacao = request.GET.get("situacao", "")
    consulta = AprovacaoLP.objects.select_related("campanha").annotate(
        versao_atual=Max("versoes__numero"),
        ajustes=Count("comentarios", filter=Q(comentarios__tipo=ComentarioLP.Tipo.AJUSTE,
                                              comentarios__resolvido=False), distinct=True))
    contagem = dict(AprovacaoLP.objects.order_by().values_list("situacao").annotate(n=Count("id")))
    if situacao in AprovacaoLP.Situacao.values:
        consulta = consulta.filter(situacao=situacao)
    filtros = [{"valor": "", "nome": "Todas", "n": sum(contagem.values()), "ativo": not situacao}]
    filtros += [{"valor": valor, "nome": nome, "n": contagem.get(valor, 0), "ativo": valor == situacao}
                for valor, nome in AprovacaoLP.Situacao.choices]
    return render(request, "marketing/lps.html", {
        "pagina": paginar(request, consulta, por_pagina=20), "filtros": filtros,
        "atual": "marketing", "aba": "lps",
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_http_methods(["GET", "POST"])
def nova_lp(request):
    form = NovaLPForm(request.POST or None, request.FILES or None,
                      initial={"campanha": request.GET.get("campanha")})
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        try:
            aprovacao = services_lp.criar(
                nome=dados["nome"], arquivo=dados["arquivo"], usuario=request.user,
                campanha=dados["campanha"], prazo=dados["prazo"], nota=dados["nota"])
        except ValidationError as erro:
            form.add_error("arquivo", erro)
        else:
            messages.success(request, "LP enviada. Copie o link e mande para quem vai aprovar.")
            return redirect("marketing:lp_detalhe", pk=aprovacao.pk)
    return render(request, "marketing/lp_nova.html", {
        "form": form, "atual": "marketing", "aba": "lps"})


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def lp_detalhe(request, pk):
    aprovacao = get_object_or_404(AprovacaoLP.objects.select_related("campanha"), pk=pk)
    contexto = contexto_revisao(
        request, aprovacao,
        pagina_url=lambda numero: reverse("marketing:lp_pagina", args=[aprovacao.pk, numero]))
    contexto["form_comentario"].initial["nome"] = (request.user.get_full_name()
                                                   or request.user.username)
    pode_publicar = (modulo_ativo(Modulo.COMERCIAL) and request.user.pode_acessar(Modulo.COMERCIAL))
    contexto.update({
        "link_previa": request.build_absolute_uri(reverse("previa_lp:ver", args=[aprovacao.token])),
        "acao": reverse("marketing:lp_comentar", args=[aprovacao.pk]),
        "form_versao": NovaVersaoForm(),
        "form_publicar": PublicarLPForm(aprovacao=aprovacao) if pode_publicar else None,
        "url_publicada": (reverse("lp:publicada", args=[aprovacao.slug])
                          if aprovacao.publicada_versao and aprovacao.slug else ""),
        "atual": "marketing", "aba": "lps",
    })
    if contexto["url_publicada"]:
        contexto["link_publicada"] = request.build_absolute_uri(contexto["url_publicada"])
    return render(request, "marketing/lp_detalhe.html", contexto)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_GET
def lp_pagina(request, pk, numero):
    aprovacao = get_object_or_404(AprovacaoLP, pk=pk)
    return resposta_previa(get_object_or_404(aprovacao.versoes, numero=numero))


def _de_volta(aprovacao, ancora=""):
    return redirect(reverse("marketing:lp_detalhe", args=[aprovacao.pk]) + ancora)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lp_versao(request, pk):
    aprovacao = get_object_or_404(AprovacaoLP, pk=pk)
    form = NovaVersaoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Escolha o arquivo .html da nova versão.")
        return _de_volta(aprovacao)
    try:
        versao = services_lp.enviar_versao(aprovacao, arquivo=form.cleaned_data["arquivo"],
                                           usuario=request.user, nota=form.cleaned_data["nota"])
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    else:
        messages.success(request, f"Versão {versao.numero} enviada. Ela volta para aprovação.")
    return _de_volta(aprovacao)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lp_comentar(request, pk):
    aprovacao = get_object_or_404(AprovacaoLP, pk=pk)
    form = ComentarioLPForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Escreva o comentário.")
        return _de_volta(aprovacao, "#comentarios")
    dados = form.cleaned_data
    try:
        services_lp.comentar(aprovacao, numero=dados["versao"], tipo=dados["tipo"],
                             texto=dados["texto"], nome=dados["nome"], usuario=request.user)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    else:
        messages.success(request, {"aprovacao": "Versão aprovada.",
                                   "ajuste": "Pedido de ajuste registrado."}.get(
                                       dados["tipo"], "Comentário registrado."))
    return _de_volta(aprovacao, "#comentarios")


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lp_resolver(request, pk):
    comentario = get_object_or_404(ComentarioLP, pk=pk)
    services_lp.alternar_resolvido(comentario)
    return _de_volta(comentario.aprovacao, "#comentarios")


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lp_novo_link(request, pk):
    aprovacao = services_lp.novo_link(get_object_or_404(AprovacaoLP, pk=pk))
    messages.success(request, "Link novo gerado. O anterior não abre mais.")
    return _de_volta(aprovacao)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lp_publicar(request, pk):
    aprovacao = get_object_or_404(AprovacaoLP, pk=pk)
    form = PublicarLPForm(request.POST, aprovacao=aprovacao)
    if not form.is_valid():
        messages.error(request, "Use só letras minúsculas, números e hífen no endereço.")
        return _de_volta(aprovacao, "#publicar")
    try:
        services_lp.publicar(aprovacao, slug=form.cleaned_data["slug"], usuario=request.user)
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    else:
        messages.success(request, "LP no ar.")
    return _de_volta(aprovacao, "#publicar")
