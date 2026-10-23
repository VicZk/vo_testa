"""Cadastro documental e recebimento parcial sobre o motor único de estoque."""
import hashlib
import json
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from itertools import islice

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from .documentos_privados import LIMITE_BYTES, preparar_documento
from .models import (
    AnexoNotaEntrada,
    EmbalagemProduto,
    ItemNotaEntrada,
    ItemRecebimentoNotaEntrada,
    LocalEstoque,
    LoteEstoque,
    NotaEntrada,
    Pessoa,
    Produto,
    RecebimentoNotaEntrada,
    registrar_auditoria,
    registrar_entrada,
)
from .models.estoque import ZERO, quantidade_valida
from .models.suprimentos import conferir_lote
from .validadores import decimal_valido, identificador_valido

LIMITE_ITENS = 100
LIMITE_PARCELAS = 200
LIMITE_DOCUMENTOS = 10
Q_CUSTO = Decimal("0.0001")
MAX_CUSTO = Decimal("99999999.9999")


def _id(valor, nome="Registro", *, opcional=False):
    return identificador_valido(getattr(valor, "pk", valor), nome=nome, opcional=opcional)


def _chave(valor):
    try:
        return valor if isinstance(valor, uuid.UUID) else uuid.UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Reabra o formulário para gerar uma chave de envio válida.") from None


def _texto(valor, nome, limite, *, obrigatorio=False):
    if valor is None:
        valor = ""
    if not isinstance(valor, str) or len(valor) > limite:
        raise ValidationError(f"{nome}: informe um texto com até {limite} caracteres.")
    valor = valor.strip()
    if obrigatorio and not valor:
        raise ValidationError(f"Informe {nome.lower()}.")
    return valor


def _referencia(valor, nome, limite, *, obrigatorio=False):
    valor = re.sub(r"\s+", "", _texto(valor, nome, limite, obrigatorio=obrigatorio)).upper()
    if valor.isascii() and valor.isdigit():
        valor = valor.lstrip("0") or "0"
    return valor


def _lista(valores, limite, nome, *, vazio=False):
    try:
        resultado = list(islice(iter(valores), limite + 1))
    except TypeError:
        raise ValidationError(f"Confira {nome}.") from None
    if len(resultado) > limite or (not resultado and not vazio):
        raise ValidationError(f"Informe {'até' if vazio else 'entre 1 e'} {limite} {nome}.")
    return resultado


def _assinatura(dados):
    return hashlib.sha256(json.dumps(dados, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode("utf-8")).hexdigest()


def _conferir_reenvio(existente, assinatura):
    if existente.assinatura != assinatura:
        raise ValidationError("A chave de envio já foi usada com outros dados. Reabra o formulário.")
    return existente


def _preparar_anexo(documento):
    if documento is None:
        return None
    if not isinstance(documento, dict):
        if not hasattr(documento, "read") or not hasattr(documento, "name"):
            raise ValidationError("Escolha um arquivo válido para anexar à nota.")
        if hasattr(documento, "seek"):
            try:
                documento.seek(0)
            except (OSError, ValueError):
                raise ValidationError("Não foi possível ler o documento. Escolha o arquivo novamente.") from None
        return preparar_documento(documento)
    conteudo = documento.get("conteudo")
    if not isinstance(conteudo, (bytes, bytearray, memoryview)) or len(conteudo) > LIMITE_BYTES:
        raise ValidationError("Confira o documento: o arquivo deve ter até 10 MB.")
    nome = documento.get("nome")
    if not isinstance(nome, str) or not nome:
        raise ValidationError("Informe um arquivo com nome e extensão válidos.")
    preparado = preparar_documento(SimpleUploadedFile(nome, bytes(conteudo)))
    if documento.get("sha256", preparado["sha256"]) != preparado["sha256"]:
        raise ValidationError("O conteúdo do documento mudou. Escolha o arquivo novamente.")
    return preparado


def _salvar_anexo(nota, usuario, documento):
    existente = nota.documentos.defer("conteudo").filter(sha256=documento["sha256"]).first()
    if existente:
        return existente
    if nota.documentos.count() >= LIMITE_DOCUMENTOS:
        raise ValidationError("Esta nota já tem 10 documentos anexados.")
    anexo = AnexoNotaEntrada.objects.create(nota=nota, enviado_por=usuario, **documento)
    registrar_auditoria(usuario, "documento_nota_entrada", nota,
                       {"documento_id": anexo.pk, "tamanho": anexo.tamanho, "sha256": anexo.sha256})
    return anexo


def anexar_documento_nota(nota, usuario, documento_preparado):
    documento = _preparar_anexo(documento_preparado)
    if documento is None:
        return None
    with transaction.atomic():
        nota = NotaEntrada.objects.select_for_update().filter(pk=_id(nota, "Nota")).first()
        if nota is None:
            raise ValidationError("A nota de entrada não foi encontrada.")
        return _salvar_anexo(nota, usuario, documento)


def _itens_cadastro(itens):
    normalizados = []
    for item in _lista(itens, LIMITE_ITENS, "itens da nota"):
        if not isinstance(item, dict):
            raise ValidationError("Confira os itens da nota.")
        embalagem_id = _id(item.get("embalagem"), "Embalagem", opcional=True)
        fator = quantidade_valida(item.get("fator_conferido")) if embalagem_id else Decimal("1.000")
        quantidade = quantidade_valida(item.get("quantidade"))
        custo = decimal_valido(item.get("custo_unidade_compra"), nome="Custo por unidade de compra",
                               maximo=MAX_CUSTO, casas=4).quantize(Q_CUSTO)
        quantidade_valida(quantidade * fator)
        decimal_valido((custo / fator).quantize(Q_CUSTO), nome="Custo na unidade base",
                       maximo=MAX_CUSTO, casas=4)
        normalizados.append({"produto": _id(item.get("produto"), "Produto"), "embalagem": embalagem_id,
                             "fator": str(fator), "quantidade": str(quantidade), "custo": str(custo)})
    return normalizados


def _identidade_fornecedor(fornecedor):
    documento = re.sub(r"[.\-/\s]", "", fornecedor.documento or "")
    if documento and (not documento.isascii() or not documento.isdigit()):
        raise ValidationError("Confira o CPF/CNPJ do fornecedor no cadastro antes de registrar a nota.")
    return documento or f"pessoa:{fornecedor.pk}"


def _duplicada(fornecedor_id, identidade, tipo, numero, serie, chave_acesso):
    filtro = (Q(documento_numero=identidade) | Q(fornecedor_id=fornecedor_id)) & Q(
        tipo=tipo, numero=numero, serie=serie)
    if chave_acesso:
        filtro |= Q(chave_acesso=chave_acesso)
    return NotaEntrada.objects.filter(filtro).exists()


def cadastrar_nota_entrada(*, fornecedor, tipo, numero, emissao, itens, usuario, chave,
                           serie="", chave_acesso="", observacao="", documentos=()):
    """Congela documento e itens. Nenhum saldo, lote ou custo é alterado aqui."""
    chave = _chave(chave)
    fornecedor_id = _id(fornecedor, "Fornecedor")
    tipo = _texto(tipo, "Tipo de documento", 8, obrigatorio=True)
    if tipo not in NotaEntrada.Tipo.values:
        raise ValidationError("Escolha um tipo de documento válido.")
    numero = _referencia(numero, "Número do documento", 40, obrigatorio=True)
    serie = _referencia(serie, "Série", 20)
    try:
        emissao = NotaEntrada._meta.get_field("emissao").clean(emissao, None)
    except (ValueError, TypeError):
        raise ValidationError("Informe uma data de emissão válida.") from None
    chave_acesso = re.sub(r"[.\-\s]", "", _texto(chave_acesso, "Chave de acesso", 90))
    if chave_acesso and not re.fullmatch(r"[0-9]{44}", chave_acesso):
        raise ValidationError("A chave de acesso deve ter 44 dígitos.")
    observacao = _texto(observacao, "Observação", 200)
    itens = _itens_cadastro(itens)
    documentos = [_preparar_anexo(d) for d in _lista(documentos, LIMITE_DOCUMENTOS, "documentos", vazio=True)]
    documentos = [d for d in documentos if d is not None]
    assinatura = _assinatura({"fornecedor": fornecedor_id, "tipo": tipo, "numero": numero, "serie": serie,
        "emissao": emissao.isoformat(), "chave_acesso": chave_acesso, "observacao": observacao,
        "itens": itens, "documentos": sorted({d["sha256"] for d in documentos})})
    existente = NotaEntrada.objects.filter(chave=chave).first()
    if existente:
        return _conferir_reenvio(existente, assinatura)
    identidade = None
    try:
        with transaction.atomic():
            fornecedor = Pessoa.objects.select_for_update().filter(pk=fornecedor_id, ativo=True).first()
            if fornecedor is None or not Pessoa.objects.filter(pk=fornecedor_id).filter(
                    Q(fornecedor__isnull=False) | Q(agencia__isnull=False)).exists():
                raise ValidationError("Selecione um fornecedor ou empresa ativo.")
            existente = NotaEntrada.objects.filter(chave=chave).first()
            if existente:
                return _conferir_reenvio(existente, assinatura)
            identidade = _identidade_fornecedor(fornecedor)
            if _duplicada(fornecedor_id, identidade, tipo, numero, serie, chave_acesso):
                raise ValidationError("Este documento já foi cadastrado. Abra a nota existente para conferir ou receber.")
            produtos = {p.pk: p for p in Produto.objects.select_for_update().filter(
                pk__in={i["produto"] for i in itens}).order_by("pk")}
            embalagens = {e.pk: e for e in EmbalagemProduto.objects.select_for_update().filter(
                pk__in={i["embalagem"] for i in itens if i["embalagem"]}).order_by("pk")}
            nota = NotaEntrada.objects.create(fornecedor=fornecedor, fornecedor_nome=fornecedor.nome,
                documento_numero=identidade, tipo=tipo, numero=numero, serie=serie, emissao=emissao,
                chave_acesso=chave_acesso, observacao=observacao, chave=chave, assinatura=assinatura, criado_por=usuario)
            for sequencia, dados in enumerate(itens, 1):
                produto = produtos.get(dados["produto"])
                if produto is None or not produto.ativo or produto.usa_ficha_tecnica:
                    raise ValidationError(f"Item {sequencia}: escolha um produto físico ativo.")
                embalagem = embalagens.get(dados["embalagem"])
                if dados["embalagem"] and (embalagem is None or not embalagem.ativo
                        or embalagem.produto_id != produto.pk):
                    raise ValidationError(f"Item {sequencia}: escolha uma embalagem ativa deste produto.")
                fator = Decimal(dados["fator"])
                if embalagem is not None and embalagem.fator != fator:
                    raise ValidationError(f"Item {sequencia}: a quantidade por embalagem mudou. Atualize e confira a nota.")
                ItemNotaEntrada.objects.create(nota=nota, sequencia=sequencia, produto=produto,
                    produto_nome=produto.nome, embalagem=embalagem, embalagem_nome=embalagem.nome if embalagem else "",
                    unidade_base=produto.unidade, fator=fator, quantidade=Decimal(dados["quantidade"]),
                    custo_unidade_compra=Decimal(dados["custo"]))
            for documento in documentos:
                _salvar_anexo(nota, usuario, documento)
            registrar_auditoria(usuario, "cadastro_nota_entrada", nota, {"itens": len(itens)})
            return nota
    except IntegrityError:
        existente = NotaEntrada.objects.filter(chave=chave).first()
        if existente:
            return _conferir_reenvio(existente, assinatura)
        if identidade is not None and _duplicada(fornecedor_id, identidade, tipo, numero, serie, chave_acesso):
            raise ValidationError("Este documento já foi cadastrado. Abra a nota existente para conferir ou receber.") from None
        raise


def _parcelas_recebimento(parcelas):
    agrupadas = defaultdict(lambda: ZERO)
    for parcela in _lista(parcelas, LIMITE_PARCELAS, "parcelas de recebimento"):
        if not isinstance(parcela, dict):
            raise ValidationError("Confira os itens do recebimento.")
        identidade = (_id(parcela.get("item"), "Item da nota"), _id(parcela.get("local"), "Local"),
                      _id(parcela.get("lote"), "Lote", opcional=True) or 0)
        agrupadas[identidade] = quantidade_valida(agrupadas[identidade] + quantidade_valida(parcela.get("quantidade")))
    return [{"item": item, "local": local, "lote": lote or None, "quantidade": str(quantidade)}
            for (item, local, lote), quantidade in sorted(agrupadas.items())]


def _versao(valor):
    texto = str(valor)
    if not re.fullmatch(r"[0-9]{1,10}", texto) or int(texto) > 2147483646:
        raise ValidationError("Atualize a nota para conferir a versão do recebimento.")
    return int(texto)


def receber_nota_entrada(nota, *, parcelas, usuario, chave, versao_conferida, observacao=""):
    """Recebe todas as parcelas ou nenhuma; versão e teto são conferidos sob lock."""
    nota_id, chave = _id(nota, "Nota"), _chave(chave)
    versao = _versao(versao_conferida)
    observacao = _texto(observacao, "Observação", 200)
    parcelas = _parcelas_recebimento(parcelas)
    assinatura = _assinatura({"nota": nota_id, "versao": versao, "observacao": observacao, "parcelas": parcelas})
    existente = RecebimentoNotaEntrada.objects.filter(chave=chave).first()
    if existente:
        return _conferir_reenvio(existente, assinatura)
    try:
        with transaction.atomic():
            nota = NotaEntrada.objects.select_for_update().filter(pk=nota_id).first()
            if nota is None:
                raise ValidationError("A nota de entrada não foi encontrada.")
            existente = RecebimentoNotaEntrada.objects.filter(chave=chave).first()
            if existente:
                return _conferir_reenvio(existente, assinatura)
            if nota.versao_recebimento != versao:
                raise ValidationError("Esta nota recebeu mercadoria depois que a tela abriu. Atualize e confira o saldo pendente.")
            itens = {i.pk: i for i in nota.itens.filter(pk__in={p["item"] for p in parcelas})}
            if len(itens) != len({p["item"] for p in parcelas}):
                raise ValidationError("Todos os itens recebidos devem pertencer a esta nota.")
            produtos = {p.pk: p for p in Produto.objects.select_for_update().filter(
                pk__in={i.produto_id for i in itens.values()}).order_by("pk")}
            locais = {local.pk: local for local in LocalEstoque.objects.filter(
                pk__in={p["local"] for p in parcelas}, ativo=True)}
            lotes = {lote.pk: lote for lote in LoteEstoque.objects.filter(
                pk__in={p["lote"] for p in parcelas if p["lote"]})}
            recebido = dict(ItemRecebimentoNotaEntrada.objects.filter(item_id__in=itens).values_list(
                "item_id").annotate(total=Sum("quantidade")))
            totais = defaultdict(lambda: ZERO)
            for parcela in parcelas:
                item = itens[parcela["item"]]
                produto = produtos[item.produto_id]
                quantidade = Decimal(parcela["quantidade"])
                totais[item.pk] += quantidade
                if not produto.ativo or produto.usa_ficha_tecnica or produto.unidade != item.unidade_base:
                    raise ValidationError(f"{item.produto_nome}: confira o produto e a unidade base antes de receber.")
                if parcela["local"] not in locais:
                    raise ValidationError("Selecione um local de recebimento ativo.")
                if parcela["lote"] and parcela["lote"] not in lotes:
                    raise ValidationError("O lote selecionado não foi encontrado.")
                conferir_lote(produto, lotes.get(parcela["lote"]), compra=True)
                quantidade_valida(quantidade * item.fator)
            for item_id, quantidade in totais.items():
                item = itens[item_id]
                pendente = item.quantidade - recebido.get(item_id, ZERO)
                if quantidade > pendente:
                    raise ValidationError(f"{item.produto_nome}: a quantidade supera o saldo pendente de {pendente}.")
            recebimento = RecebimentoNotaEntrada.objects.create(nota=nota, chave=chave, assinatura=assinatura,
                versao_conferida=versao, observacao=observacao, criado_por=usuario)
            movimentos = []
            for parcela in parcelas:
                item = itens[parcela["item"]]
                quantidade = Decimal(parcela["quantidade"])
                custo = item.custo_unidade_compra
                compra = {"nota_id": nota.pk, "item_nota_id": item.pk,
                    "embalagem_id": item.embalagem_id, "embalagem": item.embalagem_nome or item.unidade_base,
                    "quantidade": str(quantidade), "fator": str(item.fator),
                    "custo_embalagem": str(custo), "unidade": item.unidade_base,
                    "valor_total": str(quantidade * custo)}
                chave_movimento = uuid.uuid5(chave, f"{item.pk}:{parcela['local']}:{parcela['lote'] or 0}")
                movimento = registrar_entrada(produtos[item.produto_id], locais[parcela["local"]],
                    quantidade_valida(quantidade * item.fator), (custo / item.fator).quantize(Q_CUSTO), usuario,
                    documento=nota.referencia, observacao=observacao, fornecedor=nota.fornecedor,
                    chave=chave_movimento, lote=lotes.get(parcela["lote"]), compra=compra)
                ItemRecebimentoNotaEntrada.objects.create(recebimento=recebimento, item=item,
                                                          quantidade=quantidade, movimento=movimento)
                movimentos.append(movimento.pk)
            if NotaEntrada.objects.filter(pk=nota.pk, versao_recebimento=versao)._avancar_versao() != 1:
                raise ValidationError("A nota mudou durante o recebimento. Atualize e confira as quantidades.")
            nota.versao_recebimento = versao + 1
            registrar_auditoria(usuario, "recebimento_nota_entrada", nota,
                               {"recebimento_id": recebimento.pk, "versao": nota.versao_recebimento,
                                "movimentos": movimentos})
            return recebimento
    except IntegrityError:
        existente = RecebimentoNotaEntrada.objects.filter(chave=chave).first()
        if existente:
            return _conferir_reenvio(existente, assinatura)
        raise


def _itens_com_recebidos():
    return ItemNotaEntrada.objects.annotate(_quantidade_recebida=Coalesce(
        Sum("recebimentos__quantidade"), ZERO, output_field=models.DecimalField(max_digits=12, decimal_places=3)))


def itens_da_nota(nota):
    return _itens_com_recebidos().filter(nota_id=_id(nota, "Nota")).select_related("produto", "embalagem")


def notas_com_resumo():
    pendentes = _itens_com_recebidos().filter(nota_id=OuterRef("pk"), quantidade__gt=F("_quantidade_recebida"))
    valores = ItemNotaEntrada.objects.filter(nota_id=OuterRef("pk")).order_by().values("nota_id").annotate(
        total=Sum(F("quantidade") * F("custo_unidade_compra"),
                  output_field=models.DecimalField(max_digits=28, decimal_places=7)), itens=Count("pk"))
    return NotaEntrada.objects.select_related("fornecedor", "criado_por").annotate(
        _tem_recebimentos=Exists(RecebimentoNotaEntrada.objects.filter(nota_id=OuterRef("pk"))),
        _tem_pendencias=Exists(pendentes),
        _valor_total=Coalesce(Subquery(valores.values("total")[:1]), ZERO,
                             output_field=models.DecimalField(max_digits=28, decimal_places=7)),
        _total_itens=Coalesce(Subquery(valores.values("itens")[:1]), 0))
