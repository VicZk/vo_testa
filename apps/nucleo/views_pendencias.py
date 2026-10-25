"""Central de pendências: somente leitura, com autorização antes de qualquer filtro."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .paginacao import paginar
from .pendencias import ESTADOS, origens_permitidas, pendencias_usuario, url_pendencias
from .retorno_pendencias import com_retorno


def _contexto(request):
    origem = request.GET.get("origem", "")
    estado = request.GET.get("estado", "")
    permitidas = origens_permitidas(request.user)
    if origem and origem not in permitidas:
        raise PermissionDenied("Sem acesso a esta origem de pendências.")
    if estado and estado not in ESTADOS:
        return None
    dados = pendencias_usuario(request.user, origem=origem)
    itens_origem = [i for i in dados["itens"] if not origem or i["origem"] == origem]
    itens = [i for i in itens_origem if not estado or i["estado"] == estado]
    pagina = paginar(request, itens)
    retorno = url_pendencias(origem, estado)
    if request.GET.get("pagina"):
        retorno += ("&" if "?" in retorno else "?") + f"pagina={pagina.number}"
    for item in pagina.object_list:
        item["url_acao"] = com_retorno(item.get("url", ""), retorno)
    quartos = reverse("governanca:quartos")
    if estado in ("pendente", "em_andamento"):
        quartos += f"?servico={estado}"
    elif estado == "inspecao":
        quartos += "?estado=limpa"
    return {
        "origem": origem, "estado": estado,
        "origem_rotulo": permitidas.get(origem, "Todas as origens"),
        "estado_rotulo": ESTADOS.get(estado, "Todos os estados"),
        "origens": [{"codigo": codigo, "rotulo": rotulo,
                     "n": sum(i["origem"] == codigo for i in dados["itens"]),
                     "url": url_pendencias(codigo)} for codigo, rotulo in permitidas.items()],
        # "Precisa de atenção" vem logo depois de "Todas": é o que pede ação primeiro.
        "estados": [{"codigo": codigo, "rotulo": rotulo,
                     "n": sum(i["estado"] == codigo for i in itens_origem),
                     "url": url_pendencias(origem, codigo)}
                    for codigo, rotulo in sorted(ESTADOS.items(), key=lambda par: par[0] != "atencao")],
        "pagina": pagina, "itens": pagina.object_list, "total": len(itens),
        "total_geral": len(dados["itens"]), "total_origem": len(itens_origem),
        "indisponiveis": [i for i in dados["indisponiveis"] if not origem or i["codigo"] == origem],
        "tem_governanca": "governanca" in permitidas,
        "url_sem_estado": url_pendencias(origem),
        "url_governanca_painel": com_retorno(reverse("governanca:painel"), retorno),
        "url_governanca_quartos": com_retorno(quartos, retorno),
    }


@never_cache
@login_required
@require_GET
def painel(request):
    contexto = _contexto(request)
    if contexto is None:
        return HttpResponseBadRequest("Estado de pendência inválido.")
    return render(request, "nucleo/pendencias.html", contexto)


@never_cache
@login_required
@require_GET
def atualizacoes(request):
    contexto = _contexto(request)
    if contexto is None:
        return JsonResponse({"erro": "Estado de pendência inválido."}, status=400)
    return JsonResponse({
        "total": contexto["total"], "origem": contexto["origem"], "estado": contexto["estado"],
        "html": render_to_string("nucleo/partials/pendencias_resultados.html", contexto, request=request),
    })
