"""Produção de entregas; orçamento, fases e publicação permanecem independentes."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone

from apps.nucleo.models import modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .models import Campanha, PecaCampanha


def referencias_lps(usuario, ids=None):
    from apps.comercial.services import paginas_para_marketing
    return paginas_para_marketing(usuario=usuario, ids=ids)


def _exigir_acesso(usuario):
    if not (usuario.is_authenticated and usuario.pode_acessar(Modulo.MARKETING)
            and modulo_ativo(Modulo.MARKETING)):
        raise PermissionDenied("Sem acesso ao Marketing.")


def _concluir(peca, anterior, usuario):
    if peca.status == PecaCampanha.Status.PRONTA and anterior != peca.status:
        peca.concluida_em = timezone.now()
        peca.concluida_por = usuario
    elif peca.status != PecaCampanha.Status.PRONTA:
        peca.concluida_em = None
        peca.concluida_por = None


def _travar_campanhas(ids):
    ids = {pk for pk in ids if pk is not None}
    encontradas = set(Campanha.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
    if encontradas != ids:
        raise ValidationError({"campanha": "Campanha indisponível. Atualize a tela."})


def _travar_entrega(peca, *, campanha_destino=None):
    """Campanhas em ordem de PK, depois a peça; nunca inverter a ordem dos portões.

    O vínculo é conferido novamente sob lock. Se uma avulsa foi vinculada enquanto
    aguardávamos, rejeitamos a gravação em vez de operar sem o lock da campanha.
    """
    try:
        campanha_id = PecaCampanha.objects.values_list("campanha_id", flat=True).get(pk=peca.pk)
        _travar_campanhas([campanha_id, campanha_destino])
        atual = PecaCampanha.objects.select_for_update().get(pk=peca.pk)
    except PecaCampanha.DoesNotExist:
        raise ValidationError("Entrega indisponível. Atualize a tela.") from None
    if atual.campanha_id != campanha_id:
        raise ValidationError("O vínculo desta entrega mudou em outra tela. Reabra a entrega antes de salvar.")
    return atual


def _conferir_versao(peca, versao):
    if str(versao) != str(peca.versao):
        raise ValidationError("Esta entrega mudou em outra tela. Reabra a entrega antes de salvar.")


@transaction.atomic
def salvar_entrega(*, dados, usuario, peca=None):
    _exigir_acesso(usuario)
    campanha = dados.get("campanha")
    campanha_id = campanha.pk if campanha else None
    if peca is not None:
        peca = _travar_entrega(peca, campanha_destino=campanha_id)
        _conferir_versao(peca, dados.get("versao"))
        if peca.campanha_id is not None and peca.campanha_id != campanha_id:
            raise ValidationError({"campanha": "O vínculo existente não pode ser removido ou trocado."})
    else:
        _travar_campanhas([campanha_id])
        peca = PecaCampanha()
    campanha_anterior = peca.campanha_id
    anterior = peca.status if peca.pk else None
    if dados.get("tipo") == PecaCampanha.Tipo.NAO_CLASSIFICADO and (
            not peca.pk or peca.tipo != PecaCampanha.Tipo.NAO_CLASSIFICADO):
        raise ValidationError({"tipo": "Escolha o tipo da entrega."})
    # A campanha é a mesma linha travada pelos portões; evita validar a produção
    # enquanto outro atendente adiciona ou altera uma entrega.
    pagina_id = dados.get("pagina_captacao")
    if pagina_id and pagina_id != peca.pagina_captacao_id and not referencias_lps(usuario, [pagina_id]):
        raise ValidationError({"pagina_captacao": "LP indisponível para este acesso."})
    peca.campanha = campanha
    for campo in ("nome", "tipo", "canal", "data", "status", "url_material", "material_checklist"):
        setattr(peca, campo, dados.get(campo))
    peca.pagina_captacao_id = pagina_id
    _concluir(peca, anterior, usuario)
    if peca.pk:
        peca.versao += 1
    peca.full_clean()
    peca.save()
    if campanha_anterior is None and campanha_id is not None:
        registrar_auditoria(usuario, "vinculo_entrega", peca, {"de": None, "para": campanha_id})
    if anterior != peca.status:
        registrar_auditoria(usuario, "estado_entrega", peca, {"de": anterior, "para": peca.status})
    return peca


@transaction.atomic
def alterar_estado(peca, estado, usuario, *, versao=None):
    _exigir_acesso(usuario)
    peca = _travar_entrega(peca)
    if versao is not None:
        _conferir_versao(peca, versao)
    if estado not in PecaCampanha.Status.values:
        raise ValidationError("Escolha uma situação válida.")
    anterior = peca.status
    if anterior == estado:
        return peca
    peca.status = estado
    peca.versao += 1
    _concluir(peca, anterior, usuario)
    peca.save(update_fields=["status", "concluida_em", "concluida_por", "versao"])
    registrar_auditoria(usuario, "estado_entrega", peca, {"de": anterior, "para": estado})
    return peca


@transaction.atomic
def remover_entrega(peca, usuario, *, versao):
    _exigir_acesso(usuario)
    peca = _travar_entrega(peca)
    _conferir_versao(peca, versao)
    campanha = peca.campanha
    registrar_auditoria(usuario, "remover_entrega", peca, {"campanha": peca.campanha_id})
    peca.delete()
    return campanha


def consultar_entregas(*, busca="", campanha=None, tipo="", situacao="", canal="", vinculo=""):
    consulta = PecaCampanha.objects.select_related(
        "campanha", "material_checklist", "concluida_por")
    if busca:
        consulta = consulta.filter(Q(nome__icontains=busca) | Q(canal__icontains=busca)
                                   | Q(campanha__nome__icontains=busca))
    if campanha:
        consulta = consulta.filter(campanha=campanha)
    elif vinculo == "sem":
        consulta = consulta.filter(campanha__isnull=True)
    elif vinculo == "com":
        consulta = consulta.filter(campanha__isnull=False)
    if canal:
        consulta = consulta.filter(canal__iexact=canal)
    contagens = {
        (linha["tipo"], linha["status"]): linha["quantidade"]
        for linha in consulta.values("tipo", "status").annotate(quantidade=Count("id"))
    }
    resumo = []
    for codigo, rotulo in PecaCampanha.Tipo.choices:
        fazer = contagens.get((codigo, PecaCampanha.Status.A_FAZER), 0)
        producao = contagens.get((codigo, PecaCampanha.Status.EM_PRODUCAO), 0)
        prontas = contagens.get((codigo, PecaCampanha.Status.PRONTA), 0)
        resumo.append({"tipo": codigo, "nome": rotulo, "pendentes": fazer + producao,
                       "producao": producao, "prontas": prontas, "total": fazer + producao + prontas})
    if tipo:
        consulta = consulta.filter(tipo=tipo)
    if situacao == "pendentes":
        consulta = consulta.exclude(status=PecaCampanha.Status.PRONTA)
    elif situacao:
        consulta = consulta.filter(status=situacao)
    ordem = Case(*(When(tipo=valor, then=Value(i)) for i, valor in enumerate(PecaCampanha.Tipo.values)),
                 output_field=IntegerField())
    return consulta.order_by(ordem, "data", "id"), resumo
