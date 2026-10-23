"""Central de pendências: somente leitura, com autorização antes de qualquer filtro."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .paginacao import paginar
from .pendencias import ESTADOS, origens_permitidas, pendencias_usuario, url_pendencias


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
    return {
        "origem": origem, "estado": estado,
        "origem_rotulo": permitidas.get(origem, "Todas as origens"),
        "estado_rotulo": ESTADOS.get(estado, "Todos os estados"),
        "origens": [{"codigo": codigo, "rotulo": rotulo,
                     "n": sum(i["origem"] == codigo for i in dados["itens"]),
                     "url": url_pendencias(codigo)} for codigo, rotulo in permitidas.items()],
        "estados": [{"codigo": codigo, "rotulo": rotulo,
                     "n": sum(i["estado"] == codigo for i in itens_origem),
                     "url": url_pendencias(origem, codigo)} for codigo, rotulo in ESTADOS.items()],
        "pagina": pagina, "itens": pagina.object_list, "total": len(itens),
        "indisponiveis": [i for i in dados["indisponiveis"] if not origem or i["codigo"] == origem],
        "tem_governanca": "governanca" in permitidas,
        "url_sem_estado": url_pendencias(origem),
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
