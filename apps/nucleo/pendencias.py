"""Pendências acionáveis de cada usuário, sem depender da permissão de Auditoria.

Os módulos continuam donos das regras e dos dados: esta interface agrega suas
consultas públicas somente depois de conferir o acesso. Resolver uma pendência
acontece na tela de origem; abrir a central não dispara rotinas ou grava estados.
"""

import hashlib
import importlib
import logging
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from .areas import Area
from .modulos import Modulo
from .permissoes import eh_gerente

ESTADOS = {
    "pendente": "Aguardando início",
    "em_andamento": "Em andamento",
    "inspecao": "Aguardando inspeção",
    "atencao": "Precisa de atenção",
}
_MODULOS = (
    (Modulo.GOVERNANCA, "Governança", "apps.governanca.services"),
    (Modulo.RESERVAS, "Reservas", "apps.reservas.services"),
    (Modulo.MANUTENCAO, "Manutenção", "apps.manutencao.services"),
    (Modulo.RESTAURANTE, "Restaurante", "apps.restaurante.services"),
    (Modulo.LAVANDERIA, "Lavanderia", "apps.lavanderia.services"),
    (Modulo.FISCAL, "Fiscal", "apps.fiscal.services"),
    (Modulo.COMERCIAL, "Comercial", "apps.comercial.services"),
)
_GRAVIDADE = {"alta": 0, "media": 1, "baixa": 2}
_TITULOS = {
    "checkout_vencido": "Check-out em atraso",
    "no_show_provavel": "Entrada sem check-in",
    "conta_com_saldo": "Conta de hospedagem em aberto",
    "prereserva_vencida": "Pré-reservas vencidas",
    "devolucao_pendente": "Devolução pendente",
    "sem_sinal": "Reserva sem sinal",
    "os_antiga": "Ordem de serviço em atraso",
    "quarto_bloqueado": "Quarto bloqueado",
    "comanda_antiga": "Comanda em aberto",
    "lavanderia_atrasada": "Prazo de lavanderia vencido",
    "lavanderia_antiga": "Lavanderia em produção",
    "nota_rejeitada": "Documento fiscal rejeitado",
    "ronda_incompleta": "Conferência de ocupação pendente",
    "oportunidade_sem_tarefa": "Oportunidade sem próxima ação",
    "oportunidade_parada": "Oportunidade sem atualização",
    "sla_primeiro_contato": "Primeiro contato em atraso",
    "sla_followup": "Retorno ao cliente em atraso",
    "telefone_incompleto": "Contato precisa de revisão",
}


def origens_permitidas(usuario):
    """Catálogo de origens visíveis, inclusive quando não há pendências nelas."""
    if not usuario.is_authenticated or not usuario.is_active:
        return {}
    origens = {codigo: rotulo for codigo, rotulo, _ in _MODULOS
               if usuario.pode_acessar(codigo)}
    if usuario.pode_acessar(Modulo.ESTOQUE):
        origens[Modulo.ESTOQUE] = "Estoque"
    if usuario.pode_area(Area.CAIXA) or usuario.pode_area(Area.FINANCEIRO):
        origens["caixa"] = "Caixa"
    if usuario.pode_area(Area.FINANCEIRO):
        origens["financeiro"] = "Financeiro"
    return origens


def url_pendencias(origem="", estado=""):
    filtros = {k: v for k, v in {"origem": origem, "estado": estado}.items() if v}
    return reverse("pendencias") + ("?" + urlencode(filtros) if filtros else "")


def _normalizar(achado, origem, rotulo):
    """Adapta o contrato público da Auditoria sem atribuir status que ele não informa."""
    item = dict(achado)
    item.update(origem=origem, origem_rotulo=rotulo)
    item.setdefault("estado", "atencao")
    item.setdefault("estado_rotulo", ESTADOS[item["estado"]])
    item.setdefault("titulo", _TITULOS.get(item.get("tipo"), "Conferência da operação"))
    item.setdefault("acao", "Ver e resolver")
    if not item.get("id"):
        identidade = "|".join(str(item.get(k, "")) for k in ("tipo", "url", "descricao"))
        item["id"] = hashlib.sha256(identidade.encode()).hexdigest()[:20]
    item["id"] = f"{origem}:{item['id']}"
    return item


def _pendencias_nucleo(usuario, origens):
    from .models import ContaPagarReceber, SessaoCaixa, posicao_estoque

    itens = []
    hoje = timezone.localdate()
    if "caixa" in origens:
        sessoes = SessaoCaixa.objects.filter(
            status=SessaoCaixa.Status.ABERTA, aberta_em__date__lt=hoje,
        ).select_related("operador").order_by("aberta_em", "pk")
        # A central respeita o mesmo escopo da tela caixa_sessao.
        if not eh_gerente(usuario):
            sessoes = sessoes.filter(operador=usuario)
        for sessao in sessoes:
            itens.append(_normalizar({
                "id": f"sessao-{sessao.pk}", "tipo": "caixa_aberto_antigo", "gravidade": "alta",
                "titulo": "Sessão de caixa de dia anterior",
                "descricao": f"{sessao.operador} · Aberta em {timezone.localtime(sessao.aberta_em):%d/%m %H:%M}.",
                "url": reverse("caixa_sessao", args=[sessao.pk]), "acao": "Conferir sessão",
            }, "caixa", origens["caixa"]))
    if "financeiro" in origens:
        for conta in ContaPagarReceber.objects.filter(
            status=ContaPagarReceber.Status.ABERTA, vencimento__lt=hoje,
        ).order_by("vencimento", "pk"):
            itens.append(_normalizar({
                "id": f"conta-{conta.pk}", "tipo": "conta_vencida", "gravidade": "media",
                "titulo": f"{conta.get_tipo_display()} · Vencimento em {conta.vencimento:%d/%m}",
                "descricao": conta.descricao,
                "url": reverse("contas") + f"?situacao=abertas#conta-{conta.pk}", "acao": "Conferir conta",
            }, "financeiro", origens["financeiro"]))
    if Modulo.ESTOQUE in origens:
        # Interface pública do motor de estoque; uma linha por produto em falta.
        for linha in posicao_estoque():
            if not linha["abaixo_minimo"]:
                continue
            produto = linha["produto"]
            itens.append(_normalizar({
                "id": f"produto-{produto.pk}", "tipo": "estoque_minimo", "gravidade": "media",
                "titulo": produto.nome, "descricao": "Saldo no mínimo cadastrado ou zerado. Confira a reposição.",
                "url": reverse("estoque:kardex", args=[produto.pk]), "acao": "Conferir estoque",
            }, Modulo.ESTOQUE, origens[Modulo.ESTOQUE]))
    return itens


def pendencias_usuario(usuario, origem=""):
    """Retorna apenas itens autorizados, origens disponíveis e falhas explícitas.

    Uma origem indisponível não vira silenciosamente zero pendências. O erro não
    traz detalhes internos ou dados de outro módulo para a resposta.
    Quando há origem selecionada, os outros módulos nem são consultados.
    """
    origens = origens_permitidas(usuario)
    if origem and origem not in origens:
        raise PermissionDenied("Sem acesso a esta origem de pendências.")
    consultadas = {origem: origens[origem]} if origem else origens
    itens = _pendencias_nucleo(usuario, consultadas) if consultadas else []
    indisponiveis = []
    for codigo, rotulo, caminho in _MODULOS:
        if codigo not in consultadas:
            continue
        try:
            dono = importlib.import_module(caminho)
            achados = list(dono.pendencias_auditoria())
            if codigo == Modulo.GOVERNANCA:
                achados = list(dono.pendencias_operacionais()) + achados
            for achado in achados:
                if not achado.get("url"):
                    # Interfaces antigas podem apontar rotinas de suporte sem tela.
                    # Só a gestão vê esses achados; não se oferece ação fictícia.
                    if not eh_gerente(usuario):
                        continue
                    achado = {**achado, "acao": "Solicitar revisão da operação"}
                itens.append(_normalizar(achado, codigo, rotulo))
        except Exception:
            logging.getLogger(__name__).exception("leitura de pendências indisponível: %s", codigo)
            indisponiveis.append({"codigo": codigo, "rotulo": rotulo})
    itens.sort(key=lambda i: (_GRAVIDADE.get(i.get("gravidade"), 9), i["origem_rotulo"], i["titulo"], i["id"]))
    return {"itens": itens, "origens": origens, "indisponiveis": indisponiveis}
