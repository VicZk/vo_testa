"""Telas do módulo Marketing. Passos 2–3: Quadro (Kanban) + painel da verba mensal."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import eh_gerente, requer_modulo

from . import services
from .forms import SECOES, DadosCampanhaForm, NovaCampanhaForm
from .models import Campanha


@never_cache
@requer_modulo(Modulo.MARKETING)
def quadro(request):
    user = request.user
    so_meus = request.GET.get("meus") == "1"
    pos = services.posicao_verba()
    teto = float(pos["teto"]) or 0
    gasta = float(pos["gasta"])
    travada = float(pos["travada"])
    atrasados = services.banda_atrasados()
    # Contador e filtro do "Só os meus" SAEM DA MESMA FUNÇÃO (senão divergem).
    minhas = services.motivos_meus(user)
    meus_count, meus_label = services.meus_resumo(user)
    return render(request, "marketing/quadro.html", {
        "colunas": services.quadro_colunas(minhas if so_meus else None),
        "proximos": services.banda_proximos(),
        "proximos_resumo": services.resumo_proximos(),
        "atrasados": atrasados,
        "atrasos_resumo": f"{len(atrasados)} pendência{'s' if len(atrasados) != 1 else ''} atrasada{'s' if len(atrasados) != 1 else ''}",
        "verba": pos,
        "pct_gasta": int(gasta / teto * 100) if teto else 0,
        "pct_trav_extra": int(max(0.0, travada - gasta) / teto * 100) if teto else 0,
        "mes_nome": MESES_PT[int(pos["mes"][5:7])].lower(),
        "eh_gerente": eh_gerente(user),
        "so_meus": so_meus,
        "meus_count": meus_count,
        "meus_label": meus_label,
        "atual": "marketing",
        "aba": "quadro",
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def editar_teto(request):
    """Gestor (gerência) cadastra/edita o teto do mês — a única fonte do número."""
    if not eh_gerente(request.user):
        raise PermissionDenied("Apenas a gerência edita o teto de verba.")
    mes = (request.POST.get("mes") or services.mes_atual()).strip()
    try:
        services.definir_teto(mes, request.POST.get("valor") or "0")
        messages.success(request, f"Teto de {mes} atualizado.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("marketing:quadro")


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def mover_fase(request, pk):
    """Arraste/ação = muda a fase, cobrando o portão de cada etapa (Passo 4).

    Avançar UMA fase passa pelo portão (`avancar`): Aprovação→Estruturação trava a verba
    (só gerência); No ar→Encerrada devolve o não gasto. Voltar uma ou mais fases é livre
    (`retroceder`) e destrava a verba se descer abaixo de Aprovação. Pular mais de uma fase
    adiante é recusado — cada portão precisa passar.
    """
    campanha = get_object_or_404(Campanha, pk=pk)
    fase = request.POST.get("fase")
    destino = request.POST.get("next") or "marketing:quadro"
    if fase not in Campanha.Fase.values:
        return _rota_pos(request, campanha, destino)
    try:
        origem = campanha.fase
        if fase != origem:
            if services.proxima_fase(origem) == fase:
                services.avancar(campanha, request.user)
                messages.success(request, f"Avançou para {campanha.get_fase_display()}.")
            elif services.ORDEM_FASES.index(fase) < services.ORDEM_FASES.index(origem):
                services.retroceder(campanha, fase, request.user)
                messages.success(request, f"Voltou para {campanha.get_fase_display()}.")
            else:
                raise ValidationError("Avance uma fase por vez, cumprindo os requisitos de cada etapa.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return _rota_pos(request, campanha, destino)


def _rota_pos(request, campanha, destino="marketing:quadro"):
    """HTMX → gaveta re-renderizada; senão o redirect (quadro por padrão, detalhe se pedido)."""
    from django.utils.http import url_has_allowed_host_and_scheme
    if request.headers.get("HX-Request"):
        return _pos_ficha(request, campanha)
    if destino == "detalhe":
        return redirect("marketing:detalhe", pk=campanha.pk)
    # S-M7: só redireciona para `next` se for URL interna segura; senão volta ao quadro.
    if destino and destino != "marketing:quadro" and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect("marketing:quadro")


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def avancar_fase(request, pk):
    """Botão 'Avançar para…' / 'Finalizar' do rodapé da ficha (gaveta)."""
    campanha = get_object_or_404(Campanha, pk=pk)
    try:
        services.avancar(campanha, request.user)
        messages.success(request, f"Avançou para {campanha.get_fase_display()}.")
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
    return _pos_ficha(request, campanha)


def _iniciais(nome: str) -> str:
    partes = (nome or "").strip().split()
    if not partes:
        return "—"
    ini = partes[0][:1] + (partes[-1][:1] if len(partes) > 1 else "")
    return ini.upper()


def _envolvidos(campanha):
    """Os 4 papéis com o nome atual e as iniciais — para os selects da ficha."""
    out = []
    for campo, papel, dica in services.PAPEIS:
        if campo == "fornecedor":
            nome, atual_id = campanha.fornecedor or "", None
        else:
            u = getattr(campanha, campo)
            nome = (u.get_full_name() or u.username) if u else ""
            atual_id = getattr(campanha, f"{campo}_id", None)
        out.append({
            "campo": campo, "papel": papel, "dica": dica,
            "atual_id": atual_id, "atual_texto": nome, "iniciais": _iniciais(nome),
        })
    return out


def _ficha_ctx(request, campanha, dados_invalidos=None):
    """Contexto único da ficha — vale para a página (detalhe) e a gaveta (HTMX)."""
    formularios = {}
    for secao, campos in SECOES.items():
        dados = None
        if dados_invalidos is not None and any(campo in dados_invalidos for campo in campos):
            dados = model_to_dict(campanha, fields=campos)
            dados.update({campo: dados_invalidos[campo] for campo in campos if campo in dados_invalidos})
        formularios[f"form_{secao}"] = DadosCampanhaForm(dados, instance=campanha, campos=campos)
    return {
        **formularios,
        "c": campanha,
        "portao": services.portao_da(campanha),
        "verba": services.posicao_verba(services._mes_de_campanha(campanha)),
        "aq": services.aquisicao(campanha),
        "etapas": list(campanha.etapas.select_related("dono").all()),
        "conversa": list(campanha.conversa.select_related("autor").all()),
        "envolvidos": _envolvidos(campanha),
        "usuarios": services.usuarios_equipe(),
        "canais_padrao": services.CANAIS_PADRAO,
        "eh_gerente": eh_gerente(request.user),
        "Fase": Campanha.Fase,
        "Funil": Campanha.Funil,
        "Objetivo": Campanha.Objetivo,
        "atual": "marketing",
    }


def _pos_ficha(request, campanha, dados_invalidos=None):
    """Resposta pós-ação: dentro da gaveta (HTMX) devolve a gaveta re-renderizada;
    fora dela, o redirect de sempre para a página da ficha."""
    if request.headers.get("HX-Request"):
        template = "marketing/_ficha_modal.html" if request.headers.get("HX-Target") == "modal-conteudo" else "marketing/_ficha_drawer.html"
        response = render(request, template, _ficha_ctx(request, campanha, dados_invalidos))
        if dados_invalidos is None:
            response.headers["HX-Trigger"] = "marketing:alterado"
        return response
    if dados_invalidos is not None:
        return render(request, "marketing/detalhe.html", _ficha_ctx(request, campanha, dados_invalidos))
    return redirect("marketing:detalhe", pk=campanha.pk)


@never_cache
@requer_modulo(Modulo.MARKETING)
def ficha(request, pk):
    """A ficha como GAVETA (partial): carregada por HTMX sobre o quadro."""
    campanha = get_object_or_404(Campanha, pk=pk)
    return render(request, "marketing/_ficha_modal.html", _ficha_ctx(request, campanha))


@never_cache
@requer_modulo(Modulo.MARKETING)
def detalhe(request, pk):
    campanha = get_object_or_404(Campanha, pk=pk)
    return render(request, "marketing/detalhe.html", _ficha_ctx(request, campanha))


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def salvar_campanha(request, pk):
    """Analista edita os campos da campanha (objetivo, público, canais, período, verba, retrô)."""
    with transaction.atomic():
        c = get_object_or_404(Campanha.objects.select_for_update(), pk=pk)
        campos = [campo for campo in DadosCampanhaForm.base_fields if campo in request.POST]
        form = DadosCampanhaForm(request.POST, instance=c, campos=campos)
        if not form.is_valid():
            return _pos_ficha(request, c, dados_invalidos=request.POST)
        form.save()
    if "salvar" in request.POST:
        messages.success(request, "Dados da campanha salvos.")
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def marcar_check(request, pk, chave):
    c = get_object_or_404(Campanha, pk=pk)
    services.garantir_itens(c)
    item = get_object_or_404(c.checks, chave=chave)
    services.marcar_item(item, request.user, feito=not item.feito)
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def salvar_nota_check(request, pk, chave):
    c = get_object_or_404(Campanha, pk=pk)
    services.garantir_itens(c)
    item = get_object_or_404(c.checks, chave=chave)
    services.salvar_nota(item, request.POST.get("nota", ""))
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def dispensar_check(request, pk, chave):
    if not eh_gerente(request.user):
        raise PermissionDenied("Apenas a gerência dispensa item de checklist.")
    c = get_object_or_404(Campanha, pk=pk)
    services.garantir_itens(c)
    item = get_object_or_404(c.checks, chave=chave)
    # Na gaveta o motivo vem pelo hx-prompt (cabeçalho HX-Prompt); na página, pelo POST.
    motivo = request.POST.get("motivo") or request.headers.get("HX-Prompt") or ""
    services.dispensar_item(item, request.user, motivo)
    messages.success(request, "Item dispensado.")
    return _pos_ficha(request, c)


# ── Ficha: etapas, envolvidos, canais e conversa ─────────────────────────────
from .models import EtapaCampanha  # noqa: E402


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def adicionar_etapa(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    services.adicionar_etapa(c, request.POST.get("texto"),
                             request.POST.get("dono") or None, request.POST.get("prazo") or None)
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def alternar_etapa(request, pk):
    e = get_object_or_404(EtapaCampanha, pk=pk)
    services.alternar_etapa(e)
    return _pos_ficha(request, e.campanha)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def remover_etapa(request, pk):
    e = get_object_or_404(EtapaCampanha, pk=pk)
    camp = e.campanha
    services.remover_etapa(e)
    return _pos_ficha(request, camp)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def atribuir_papel(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    services.atribuir_papel(c, request.POST.get("papel"), request.POST.get("valor"))
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def alternar_canal(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    services.alternar_canal(c, request.POST.get("canal"))
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def comentar(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    services.adicionar_comentario(c, request.user, request.POST.get("texto"))
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def anexar_item(request, pk, chave):
    """Anexa a evidência de um item do portão que 'não fecha sem' arquivo."""
    c = get_object_or_404(Campanha, pk=pk)
    services.garantir_itens(c)
    item = get_object_or_404(c.checks, chave=chave)
    arquivo = request.FILES.get("arquivo")
    if arquivo:
        try:
            services.anexar_arquivo(item, arquivo, request.user)
            messages.success(request, "Arquivo anexado.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_http_methods(["GET", "POST"])
def nova_campanha(request):
    """Abrir/cancelar não grava nada; reenviar a mesma criação devolve a campanha."""
    form = NovaCampanhaForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        c, criada = Campanha.objects.get_or_create(
            chave_criacao=form.cleaned_data["chave"],
            defaults={"nome": form.cleaned_data["nome"],
                      "objetivo": form.cleaned_data["objetivo"],
                      "solicitante": request.user, "responsavel": request.user},
        )
        if criada:
            messages.success(request, "Campanha criada. Agora organize os próximos passos.")
        return _pos_ficha(request, c)
    template = "marketing/_nova_campanha.html" if request.headers.get("HX-Request") else "marketing/nova.html"
    return render(request, template, {"form": form, "atual": "marketing", "em_modal": bool(request.headers.get("HX-Request"))})


# ── Passo 5: Calendário + peças ──────────────────────────────────────────────
from datetime import date as _date  # noqa: E402

from apps.nucleo.periodos import MESES_PT  # noqa: E402

from .models import PecaCampanha  # noqa: E402


@never_cache
@requer_modulo(Modulo.MARKETING)
def calendario(request):
    from datetime import timedelta

    from django.utils import timezone
    hoje = timezone.localdate()
    escala = "ano" if request.GET.get("vista") == "ano" else "mes"
    try:
        ano = int(request.GET.get("ano") or hoje.year)
        mes = int(request.GET.get("mes") or hoje.month)
    except (TypeError, ValueError):
        ano, mes = hoje.year, hoje.month
    if not 1 <= mes <= 12:
        mes = hoje.month
    if escala == "ano":
        prev, nxt = {"ano": ano - 1, "mes": mes}, {"ano": ano + 1, "mes": mes}
    else:
        p = _date(ano, mes, 1) - timedelta(days=1)
        x = _date(ano, mes, 28) + timedelta(days=7)
        prev, nxt = {"ano": p.year, "mes": p.month}, {"ano": x.year, "mes": x.month}
    return render(request, "marketing/calendario.html", {
        "tl": services.calendario_timeline(ano, mes, escala),
        "escala": escala, "ano": ano, "mes": mes, "prev": prev, "next": nxt,
        "atual": "marketing", "aba": "calendario",
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def adicionar_peca(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Dê um nome à peça.")
        return _pos_ficha(request, c)
    PecaCampanha.objects.create(
        campanha=c, nome=nome, canal=(request.POST.get("canal") or "").strip(),
        data=request.POST.get("data") or None)
    return _pos_ficha(request, c)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def marcar_peca(request, pk):
    p = get_object_or_404(PecaCampanha, pk=pk)
    novo = request.POST.get("status")
    if novo in PecaCampanha.Status.values:
        p.status = novo
        p.save(update_fields=["status"])
    return _pos_ficha(request, p.campanha)


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def remover_peca(request, pk):
    p = get_object_or_404(PecaCampanha, pk=pk)
    camp = p.campanha
    p.delete()
    return _pos_ficha(request, camp)


# ── Passo 6: relatório (mês/ano) + lançar gasto ──────────────────────────────
import csv  # noqa: E402

from django.http import HttpResponse  # noqa: E402

from apps.nucleo.periodos import periodo, selecao_periodo  # noqa: E402


@never_cache
@requer_modulo(Modulo.MARKETING)
def relatorio(request):
    inicio, fim, rotulo = periodo(request)
    dados = services.relatorio(inicio, fim)
    if request.GET.get("export") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="marketing_{inicio}_{fim}.csv"'
        resp.write("﻿")
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Relatório de Marketing", rotulo])
        w.writerow(["Teto", dados["teto"], "Gasto", dados["gasto"], "Sobra", dados["sobra"],
                    "Ritmo/dia", dados["ritmo"]])
        w.writerow([])
        w.writerow(["Campanha", "Gasto", "Retorno rastreado", "Retorno estimado (janela)",
                    "Fechamentos", "CAC"])
        from apps.nucleo.export import sanitizar_celula  # S-M2: anti CSV formula-injection
        for linha in dados["linhas"]:
            w.writerow([sanitizar_celula(linha["nome"]), linha["gasto"], linha["rastreada"],
                        linha["janela"], linha["fechamentos"],
                        linha["cac"] if linha["cac"] is not None else "—"])
        return resp
    return render(request, "marketing/relatorio.html", {
        "dados": dados, "inicio": inicio, "fim": fim, "rotulo": rotulo,
        "atual": "marketing", "aba": "relatorio", **selecao_periodo(request),
    })


@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def lancar_gasto(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    try:
        valor = services.parse_moeda(request.POST.get("valor"))
        data = request.POST.get("data") or services.timezone.localdate()
        services.lancar_gasto(c, data, valor, request.user)
        messages.success(request, "Gasto lançado.")
    except Exception as e:  # noqa: BLE001
        messages.error(request, f"Não foi possível lançar o gasto: {e}")
    return _pos_ficha(request, c)


# ── Passo 9: ocupação × campanha ─────────────────────────────────────────────
@never_cache
@requer_modulo(Modulo.MARKETING)
def ocupacao(request):
    blocos = services.ocupacao_x_campanha()
    problemas = sum(1 for b in blocos if b["situacao"] == "problema")
    oportunidades = sum(1 for b in blocos if b["situacao"] == "oportunidade")
    if problemas:
        resumo = f"{problemas} semana{'s' if problemas != 1 else ''} com campanha no ar e ainda vazia{'s' if problemas != 1 else ''}."
        resumo_tom = "perigo"
    elif oportunidades:
        resumo = f"{oportunidades} semana{'s' if oportunidades != 1 else ''} vazia{'s' if oportunidades != 1 else ''} sem campanha. Período disponível para anunciar."
        resumo_tom = "alerta"
    else:
        resumo = "Sem vazios preocupantes nos próximos 90 dias."
        resumo_tom = "sucesso"
    return render(request, "marketing/ocupacao.html", {
        "blocos": blocos, "resumo": resumo, "resumo_tom": resumo_tom,
        "marcos": services.marcos_ocupacao(),
        "atual": "marketing", "aba": "ocupacao",
    })


# ── Passo 10: duplicar campanha ──────────────────────────────────────────────
@never_cache
@requer_modulo(Modulo.MARKETING)
@require_POST
def duplicar(request, pk):
    c = get_object_or_404(Campanha, pk=pk)
    nova = services.duplicar(c, request.user)
    messages.success(request, "Campanha duplicada. A nova campanha começa na fase Ideia.")
    return redirect("marketing:detalhe", pk=nova.pk)
