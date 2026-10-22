"""Classificação e rateio de serviços do folio, antes da emissão de NFS-e."""
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.nucleo.models import NaturezaFiscal, registrar_auditoria
from apps.nucleo.permissoes import eh_gerente

from .models import DocumentoFiscal
from .rateio import ratear_desconto


def referencia(conta_id, codigo):
    return f"conta:{conta_id}" if codigo == settings.FISCAL_NFSE_CODIGO_SERVICO else f"conta:{conta_id}:servico:{codigo}"


def resumo(conta):
    from apps.reservas.models import LancamentoConta
    linhas = list(conta.lancamentos.filter(natureza=NaturezaFiscal.SERVICO)
        .exclude(tipo=LancamentoConta.Tipo.TAXA).order_by("pk"))
    grupos, pendentes, revisao = {}, [], []
    desconto = Decimal("0")
    for linha in linhas:
        if linha.tipo == LancamentoConta.Tipo.DESCONTO:
            desconto += linha.valor
            continue
        codigo = settings.FISCAL_NFSE_CODIGO_SERVICO if linha.tipo == LancamentoConta.Tipo.DIARIA else linha.codigo_servico_fiscal
        revisao.append({"linha":linha, "codigo":codigo, "diaria":linha.tipo == LancamentoConta.Tipo.DIARIA})
        if not re.fullmatch(r"[0-9]{6}", codigo):
            pendentes.append(linha)
        grupo = grupos.setdefault(codigo, {"codigo":codigo,"bruto":Decimal("0"),"linhas":[]})
        grupo["bruto"] += linha.valor
        grupo["linhas"].append(linha.pk)
    total = sum((g["bruto"] for g in grupos.values()), Decimal("0"))
    if desconto > total:
        raise ValidationError("Os descontos de serviço excedem a base fiscal. Confira os lançamentos da conta.")
    ordenados = sorted(grupos.values(), key=lambda g:g["codigo"])
    parcelas = ratear_desconto(desconto, [g["bruto"] for g in ordenados])
    documentos = {d.referencia:d for d in DocumentoFiscal.objects.filter(tipo="nfse",
        referencia__in=[referencia(conta.pk,g["codigo"]) for g in ordenados]).exclude(status="cancelada")}
    for indice, grupo in enumerate(ordenados):
        abatimento = parcelas[indice]
        grupo["desconto"], grupo["valor"] = abatimento, grupo["bruto"]-abatimento
        grupo["documento"] = documentos.get(referencia(conta.pk,grupo["codigo"]))
    return {"grupos":ordenados,"pendentes":pendentes,"revisao":revisao,"total":total-desconto}


@transaction.atomic
def classificar(conta_id, codigos, operador):
    from apps.reservas.models import ContaHospedagem, LancamentoConta
    if not eh_gerente(operador):
        raise ValidationError("A classificação fiscal exige permissão de gerência.")
    conta = ContaHospedagem.objects.select_for_update().get(pk=conta_id)
    if (DocumentoFiscal.objects.filter(referencia=f"conta:{conta.pk}").exclude(status="cancelada").exists()
            or DocumentoFiscal.objects.filter(referencia__startswith=f"conta:{conta.pk}:servico:").exclude(status="cancelada").exists()):
        raise ValidationError("Já existe emissão desta conta. Concilie ou cancele os documentos antes de reclassificar os serviços.")
    alterados = []
    for linha in conta.lancamentos.select_for_update().filter(natureza=NaturezaFiscal.SERVICO,
            tipo__in=[LancamentoConta.Tipo.SERVICO, LancamentoConta.Tipo.CONSUMO]):
        codigo = str(codigos.get(str(linha.pk), "")).strip()
        if not re.fullmatch(r"[0-9]{6}", codigo):
            raise ValidationError(f"Informe o código nacional de seis dígitos para o lançamento #{linha.pk}.")
        # A parte financeira continua imutável; somente este metadado fiscal é
        # atualizado sob trava e com auditoria própria.
        LancamentoConta.objects.filter(pk=linha.pk).update(codigo_servico_fiscal=codigo)
        alterados.append({"lancamento":linha.pk,"codigo":codigo})
    registrar_auditoria(operador,"classificacao_fiscal",conta,{"classificacoes":alterados})


def grupo_para_emitir(conta, codigo):
    dados = resumo(conta)
    if dados["pendentes"]:
        raise ValidationError("Classifique os serviços desta conta antes da emissão. Lavanderia e outros serviços não recebem o código de hospedagem automaticamente.")
    grupo = next((g for g in dados["grupos"] if g["codigo"] == codigo), None)
    if not grupo or grupo["valor"] <= 0:
        raise ValidationError("Não há serviço com valor positivo para este código na conta.")
    return grupo
