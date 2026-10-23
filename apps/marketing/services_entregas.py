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


@transaction.atomic
def salvar_entrega(*, dados, usuario, peca=None):
    _exigir_acesso(usuario)
    campanha = dados["campanha"]
    if peca and peca.campanha_id != campanha.pk:
        raise ValidationError({"campanha": "A entrega pertence a outra campanha."})
    Campanha.objects.select_for_update().get(pk=campanha.pk)
    if peca is not None:
        peca = PecaCampanha.objects.select_for_update().get(pk=peca.pk)
    else:
        peca = PecaCampanha()
    anterior = peca.status if peca.pk else None
    if peca.pk and dados.get("versao") != peca.versao:
        raise ValidationError("Esta entrega mudou em outra tela. Reabra a entrega antes de salvar.")
    if dados.get("tipo") == PecaCampanha.Tipo.NAO_CLASSIFICADO and (
            not peca.pk or peca.tipo != PecaCampanha.Tipo.NAO_CLASSIFICADO):
        raise ValidationError({"tipo": "Escolha o tipo da entrega."})
    if peca.pk and peca.campanha_id != campanha.pk:
        raise ValidationError({"campanha": "A entrega pertence a outra campanha."})
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
    if anterior != peca.status:
        registrar_auditoria(usuario, "estado_entrega", peca, {"de": anterior, "para": peca.status})
    return peca


@transaction.atomic
def alterar_estado(peca, estado, usuario, *, versao=None):
    _exigir_acesso(usuario)
    Campanha.objects.select_for_update().get(pk=peca.campanha_id)
    peca = PecaCampanha.objects.select_for_update().get(pk=peca.pk)
    if versao is not None and str(versao) != str(peca.versao):
        raise ValidationError("Esta entrega mudou em outra tela. Reabra a entrega antes de salvar.")
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


def consultar_entregas(*, busca="", campanha=None, tipo="", situacao=""):
    consulta = PecaCampanha.objects.select_related(
        "campanha", "material_checklist", "concluida_por")
    if busca:
        consulta = consulta.filter(Q(nome__icontains=busca) | Q(canal__icontains=busca)
                                   | Q(campanha__nome__icontains=busca))
    if campanha:
        consulta = consulta.filter(campanha=campanha)
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
