"""Prévia de LP para quem aprova (gestor ou cliente), pelo link, sem login."""
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from apps.nucleo.antirrobo import parece_robo
from apps.nucleo.models import modulo_ativo
from apps.nucleo.modulos import Modulo
from apps.nucleo.ratelimit import limite_excedido

from . import services_lp
from .forms_lp import ComentarioLPForm
from .models import AprovacaoLP
from .views_lps import contexto_revisao, resposta_previa


def _aprovacao(token):
    # Marketing desligado = link desligado.
    aprovacao = AprovacaoLP.objects.filter(token=token).first() if modulo_ativo(Modulo.MARKETING) else None
    if aprovacao is None:
        raise Http404("Link de prévia não encontrado.")
    return aprovacao


@never_cache
@require_http_methods(["GET", "POST"])
def ver(request, token):
    aprovacao = _aprovacao(token)
    url = reverse("previa_lp:ver", args=[token])
    form, erro = None, ""
    if request.method == "POST":
        # Robô ou envio em massa: finge que deu certo e descarta.
        if parece_robo(request.POST) or limite_excedido(
                request, "previa_lp", limite=30, janela_seg=3600, sufixo=str(aprovacao.pk)):
            return redirect(url + "?enviado=comentario#comentarios")
        form = ComentarioLPForm(request.POST)
        if form.is_valid():
            dados = form.cleaned_data
            try:
                services_lp.comentar(aprovacao, numero=dados["versao"], tipo=dados["tipo"],
                                     texto=dados["texto"], nome=dados["nome"], pelo_link=True)
            except ValidationError as e:
                erro = " ".join(e.messages)
            else:
                resposta = redirect(f"{url}?enviado={dados['tipo']}#comentarios")
                # Na próxima visita o nome já vem preenchido.
                resposta.set_cookie("lp_revisor", dados["nome"], max_age=180 * 24 * 3600,
                                    path=url, samesite="Lax", secure=request.is_secure(),
                                    httponly=True)
                return resposta
        else:
            erro = "Diga seu nome e escreva o comentário."
    contexto = contexto_revisao(
        request, aprovacao, form=form,
        pagina_url=lambda numero: reverse("previa_lp:pagina", args=[token, numero]))
    contexto.update({"erro": erro, "enviado": request.GET.get("enviado", ""), "acao": url})
    resposta = render(request, "marketing/previa_publica.html", contexto)
    resposta["X-Robots-Tag"] = "noindex, nofollow"
    resposta["Referrer-Policy"] = "no-referrer"
    return resposta


@never_cache
@require_GET
def pagina(request, token, numero):
    versao = _aprovacao(token).versoes.filter(numero=numero).first()
    if versao is None:
        raise Http404("Versão não encontrada.")
    return resposta_previa(versao)
