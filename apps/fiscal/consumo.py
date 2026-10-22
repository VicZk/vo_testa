"""Retrato fiscal de uma venda/comanda fechada, sem alterar estoque ou recebimento."""
import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.nucleo.validadores import identificador_valido

from .models import ConfigFiscalProduto, DocumentoFiscal
from .rateio import ratear_desconto


def payload_consumo(origem, pix_modalidade=""):
    itens = list(origem.itens.select_related("produto").all())
    consumos = [i for i in itens if i.natureza == "consumo"]
    bruto = sum((i.subtotal for i in consumos), Decimal("0"))
    completo = sum((i.subtotal for i in itens), Decimal("0"))
    if bruto <= 0:
        raise ValidationError("Não há itens de consumo para emitir NFC-e.")
    desconto = (origem.desconto*bruto/completo).quantize(Decimal(".01"))
    total = bruto-desconto
    if total <= 0:
        raise ValidationError("O valor do consumo deve ser positivo para esta emissão.")
    codigos = {c.produto_id:c for c in ConfigFiscalProduto.objects.filter(produto_id__in=[i.produto_id for i in consumos])}
    linhas = []
    parcelas = ratear_desconto(desconto, [i.subtotal for i in consumos])
    for numero, item in enumerate(consumos, 1):
        cfg = codigos.get(item.produto_id)
        if not cfg or not re.fullmatch(r"[0-9]{8}",cfg.ncm) or not re.fullmatch(r"[0-9]{4}",cfg.cfop) or not re.fullmatch(r"[0-9]{2,3}",cfg.cst_csosn):
            raise ValidationError(f"Complete NCM, CFOP e CST/CSOSN de {item.descricao} com o responsável fiscal.")
        if not isinstance(cfg.tributos,dict) or not all(cfg.tributos.get(k) for k in ("pis_situacao_tributaria","cofins_situacao_tributaria")):
            raise ValidationError(f"Complete os parâmetros tributários de {item.descricao} com o responsável fiscal.")
        if settings.FISCAL_REGIME == "lucro_presumido" and len(cfg.cst_csosn) != 2:
            raise ValidationError(f"O regime configurado exige CST, não CSOSN, para {item.descricao}.")
        parcela = parcelas[numero-1]
        linhas.append({**cfg.tributos, "numero_item":str(numero), "codigo_produto":str(item.produto_id),
            "descricao":item.descricao, "codigo_ncm":cfg.ncm, "cfop":cfg.cfop,
            "icms_origem":cfg.origem, "icms_situacao_tributaria":cfg.cst_csosn,
            "unidade_comercial":item.produto.unidade.upper(), "unidade_tributavel":item.produto.unidade.upper(),
            "quantidade_comercial":str(item.quantidade), "quantidade_tributavel":str(item.quantidade),
            "valor_unitario_comercial":str(item.preco_unitario), "valor_unitario_tributavel":str(item.preco_unitario),
            "valor_bruto":str(item.subtotal), "valor_desconto":str(parcela), "inclui_no_total":"1"})
    if origem.destino == "conta":
        codigo = "91"  # pagamento posterior; não inventa recebimento no caixa.
    else:
        tipo = origem.forma_pagamento.tipo if origem.forma_pagamento else ""
        codigo = {"dinheiro":"01","cartao_credito":"03","cartao_debito":"04","transferencia":"18"}.get(tipo)
        if tipo == "pix" and pix_modalidade in ("17","20","23"):
            codigo = pix_modalidade
        if not codigo:
            raise ValidationError("Confira a forma fiscal do pagamento; para Pix, selecione a modalidade usada.")
    pagamento = {"forma_pagamento":codigo,"valor_pagamento":str(total)}
    if codigo in ("03","04"):
        pagamento["tipo_integracao"]="2"  # recebimento manual em POS, sem captura TEF neste fluxo.
    dados = {"natureza_operacao":"VENDA AO CONSUMIDOR", "modalidade_frete":"9", "local_destino":"1",
        "presenca_comprador":"1", "indicador_inscricao_estadual_destinatario":"9", "items":linhas,
        "formas_pagamento":[pagamento], "valor_produtos":str(bruto), "valor_desconto":str(desconto), "valor_total":str(total)}
    cliente = origem.cliente
    if cliente:
        documento = re.sub(r"\D","",cliente.documento)
        if len(documento) not in (11,14):
            raise ValidationError("Confira o CPF/CNPJ do cliente identificado antes de emitir.")
        dados["cpf_destinatario" if len(documento) == 11 else "cnpj_destinatario"] = documento
        dados["nome_destinatario"] = cliente.nome
    return total, dados


def emitir_origem(origem, origem_id, usuario, pix_modalidade=""):
    from apps.loja.models import Venda
    from apps.restaurante.models import Comanda

    from .services import _criar, _executar
    if not settings.FISCAL_NFCE_HABILITADA:
        raise ValidationError("NFC-e desabilitada até configurar inscrição estadual, CSC e cadastro fiscal.")
    modelo = {"venda":Venda,"comanda":Comanda}.get(origem)
    if modelo is None:
        raise ValidationError("Origem fiscal inválida.")
    origem_id = identificador_valido(origem_id)
    with transaction.atomic():
        registro = modelo.objects.select_for_update().filter(pk=origem_id).first()
        if not registro or registro.status != "fechada":
            raise ValidationError("Emita a NFC-e de uma venda ou comanda fechada.")
        ref = f"{origem}:{registro.pk}"
        doc = DocumentoFiscal.objects.filter(referencia=ref,tipo="nfce").exclude(status="cancelada").first()
        if doc is None:
            total, payload = payload_consumo(registro,pix_modalidade)
            doc = _criar(usuario,natureza="consumo",valor=total,descricao=f"Consumo — {origem} #{registro.pk}",
                tomador=registro.cliente,referencia=ref,payload={"nfce":payload})
    return _executar(doc.pk,"emitir")


def conferir_cancelamento(origem, origem_id):
    if DocumentoFiscal.objects.filter(referencia=f"{origem}:{origem_id}").exclude(status__in=("cancelada","rejeitada")).exists():
        raise ValidationError("Concilie e cancele o documento fiscal antes de cancelar esta venda/comanda.")


def renovar_payload(doc):
    from apps.loja.models import Venda
    from apps.restaurante.models import Comanda
    origem, _, identificador = doc.referencia.partition(":")
    modelo = {"venda": Venda, "comanda": Comanda}.get(origem)
    if modelo is None or not identificador.isdigit():
        raise ValidationError("Corrija esta origem diretamente com o responsável fiscal.")
    registro = modelo.objects.filter(pk=int(identificador), status="fechada").first()
    if registro is None:
        raise ValidationError("A venda de origem precisa estar fechada.")
    pagamentos = doc.payload_envio.get("formas_pagamento", [])
    pix = pagamentos[0].get("forma_pagamento", "") if pagamentos else ""
    total, dados = payload_consumo(registro, pix)
    if total != doc.valor:
        raise ValidationError("O valor da origem mudou. Concilie a emissão com o responsável fiscal.")
    return dados
