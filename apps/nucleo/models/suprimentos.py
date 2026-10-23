"""Lotes, conversão de compras e fichas técnicas sobre o kardex do núcleo.

O saldo físico continua sendo a soma de MovimentoEstoque. RegistroLote só
identifica a parcela desse saldo cuja origem/validade foi conferida.
"""
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.nucleo.validadores import decimal_valido

from .estoque import (
    ZERO,
    MovimentoEstoque,
    Produto,
    _novo_movimento,
    quantidade_valida,
    saldo,
)
from .financeiro import registrar_auditoria


class EmbalagemProduto(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="embalagens")
    nome = models.CharField("embalagem de compra", max_length=80)
    fator = models.DecimalField("quantidade na unidade base", max_digits=12, decimal_places=3)
    ativo = models.BooleanField("ativa", default=True)

    class Meta:
        ordering = ["produto__nome", "nome", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["produto", "nome"], name="embalagem_produto_nome_unico"),
            models.CheckConstraint(condition=models.Q(fator__gt=0), name="embalagem_fator_positivo"),
        ]

    def __str__(self):
        return f"{self.produto.nome} · {self.nome} ({format(self.fator.normalize(), 'f')} {self.produto.unidade})"

    def clean(self):
        quantidade_valida(self.fator)
        if self.pk and EmbalagemProduto.objects.filter(pk=self.pk).exclude(produto_id=self.produto_id).exists():
            raise ValidationError("A embalagem já cadastrada mantém o produto de origem.")
        if self.produto_id and self.produto.usa_ficha_tecnica:
            raise ValidationError("Cadastre a embalagem dos ingredientes, não do prato.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class IngredienteFicha(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name="ingredientes")
    ingrediente = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="usado_em_fichas")
    quantidade = models.DecimalField("consumo por unidade vendida", max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["ingrediente__nome", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["produto", "ingrediente"], name="ingrediente_ficha_unico"),
            models.CheckConstraint(condition=models.Q(quantidade__gt=0), name="ficha_quantidade_positiva"),
            models.CheckConstraint(condition=~models.Q(produto=models.F("ingrediente")), name="ficha_sem_autorreferencia"),
        ]

    def clean(self):
        quantidade_valida(self.quantidade)
        if self.ingrediente_id == self.produto_id or self.ingrediente.usa_ficha_tecnica:
            raise ValidationError("Use ingredientes de estoque. Fichas dentro de outras fichas não são permitidas.")


class LoteEstoque(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="lotes")
    codigo = models.CharField("lote do fabricante ou etiqueta interna", max_length=80)
    validade = models.DateField("validade")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["validade", "pk"]
        constraints = [models.UniqueConstraint(fields=["produto", "codigo"], name="lote_produto_codigo_unico")]

    def __str__(self):
        return f"{self.produto.nome} · {self.codigo} · {self.validade:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("O lote já registrado mantém sua identificação e validade.")
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.produto_id and (not self.produto.controla_validade or self.produto.usa_ficha_tecnica):
            raise ValidationError("O produto precisa estar configurado para controle de validade.")


class RegistroLote(models.Model):
    lote = models.ForeignKey(LoteEstoque, on_delete=models.PROTECT, related_name="registros")
    local = models.ForeignKey("nucleo.LocalEstoque", on_delete=models.PROTECT, related_name="registros_lotes")
    movimento = models.ForeignKey(MovimentoEstoque, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="lotes")
    origem_correcao = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                          related_name="destino_correcao", editable=False)
    quantidade = models.DecimalField(max_digits=12, decimal_places=3)
    chave = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    motivo = models.CharField(max_length=200, blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        constraints = [models.CheckConstraint(condition=~models.Q(quantidade=0), name="registro_lote_nao_zero")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Registro de lote é imutável. Registre uma correção com motivo.")
        quantidade_valida(abs(self.quantidade))
        if self.movimento_id and (self.movimento.produto_id != self.lote.produto_id
                                  or self.movimento.local_id != self.local_id):
            raise ValidationError("O lote deve pertencer ao produto e local do movimento.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Registro de lote é imutável.")


def saldos_lotes(produto=None, local=None, *, vendaveis=False):
    qs = RegistroLote.objects.all()
    if produto is not None:
        qs = qs.filter(lote__produto=produto)
    if local is not None:
        qs = qs.filter(local=local)
    if vendaveis:
        qs = qs.filter(lote__validade__gte=timezone.localdate())
    return qs.values("lote_id", "local_id", "lote__produto_id", "lote__codigo", "lote__validade").annotate(
        saldo=Sum("quantidade")).filter(saldo__gt=0).order_by("lote__validade", "lote_id", "local_id")


def saldo_vendavel(produto, local=None):
    if not produto.controla_validade:
        return saldo(produto, local)
    return sum((linha["saldo"] for linha in saldos_lotes(produto, local, vendaveis=True)), ZERO)


def conferir_lote(produto, lote, *, compra=False):
    if not produto.controla_validade:
        if lote is not None:
            raise ValidationError("Ative o controle de validade antes de informar um lote.")
        return
    if lote is None or lote.produto_id != produto.pk:
        raise ValidationError(f"{produto.nome}: informe um lote deste produto.")
    if compra and lote.validade < timezone.localdate():
        raise ValidationError("A compra não pode receber um lote vencido. Confira a mercadoria com o fornecedor.")


def marca_lote(lote, local):
    return RegistroLote.objects.filter(lote=lote, local=local).aggregate(m=Max("pk"))["m"] or 0


@transaction.atomic
def contar_lote(lote, local, quantidade, usuario, motivo, chave, marca):
    from apps.nucleo.sistema import travar

    produto = travar(lote.produto)
    quantidade = quantidade_valida(quantidade, zero=True)
    conferir_lote(produto, lote)
    if not motivo.strip() or not chave:
        raise ValidationError("Informe o motivo e reabra a contagem para gerar a chave de envio.")
    existente = MovimentoEstoque.objects.filter(chave=chave).first()
    if existente:
        if existente.compra != {"contagem_lote": lote.pk, "local": local.pk, "quantidade": str(quantidade)}:
            raise ValidationError("A chave já foi usada com outra contagem.")
        return existente
    if marca != marca_lote(lote, local):
        raise ValidationError("Este lote foi movimentado depois que a tela abriu. Atualize e confira a quantidade novamente.")
    atual = RegistroLote.objects.filter(lote=lote, local=local).aggregate(s=Sum("quantidade"))["s"] or ZERO
    diferenca = quantidade - atual
    if diferenca == ZERO:
        return None
    identificado = sum((linha["saldo"] for linha in saldos_lotes(produto, local)), ZERO)
    if diferenca > ZERO and saldo(produto, local) > identificado:
        raise ValidationError("Identifique o saldo sem lote antes de aumentar uma contagem. Isso evita registrar a mesma mercadoria duas vezes.")
    movimento = _novo_movimento(produto, local, MovimentoEstoque.Tipo.AJUSTE, diferenca, usuario,
                                custo_unitario=produto.custo_medio, observacao=motivo, chave=chave,
                                compra={"contagem_lote": lote.pk, "local": local.pk, "quantidade": str(quantidade)})
    registrar_lotes(movimento, [(lote.pk, abs(diferenca))], sinal=1 if diferenca > ZERO else -1)
    registrar_auditoria(usuario, "contagem_lote", movimento,
                       {"lote": lote.pk, "antes": str(atual), "depois": str(quantidade), "motivo": motivo})
    return movimento


@transaction.atomic
def corrigir_identificacao(lote, destino, local, quantidade, usuario, motivo, chave):
    """Corrige a etiqueta/validade sem alterar o saldo físico nem o histórico."""
    from apps.nucleo.sistema import travar

    produto = travar(lote.produto)
    quantidade = quantidade_valida(quantidade)
    conferir_lote(produto, lote)
    conferir_lote(produto, destino)
    if lote.pk == destino.pk or not motivo.strip() or not chave:
        raise ValidationError("Escolha outro lote do mesmo produto e informe o motivo da correção.")
    existente = RegistroLote.objects.filter(chave=chave).first()
    if existente:
        par = RegistroLote.objects.filter(origem_correcao=existente).first()
        if (existente.lote_id != lote.pk or existente.local_id != local.pk
                or existente.quantidade != -quantidade or par is None or par.lote_id != destino.pk):
            raise ValidationError("A chave de envio já foi usada com outros dados.")
        return par
    planejar_lotes(produto, local, quantidade, permite_vencido=True, lote=lote)
    origem = RegistroLote.objects.create(lote=lote, local=local, quantidade=-quantidade,
                                         criado_por=usuario, motivo=motivo, chave=chave)
    entrada = RegistroLote.objects.create(lote=destino, local=local, quantidade=quantidade,
                                          criado_por=usuario, motivo=motivo, origem_correcao=origem)
    registrar_auditoria(usuario, "correcao_lote", entrada, {"de": lote.pk, "para": destino.pk,
                        "local": local.pk, "quantidade": str(quantidade), "motivo": motivo})
    return entrada


def planejar_lotes(produto, local, quantidade, *, permite_vencido=False, lote=None):
    """Chamada com o produto travado; primeiro vence, primeiro sai (FEFO)."""
    if not produto.controla_validade:
        conferir_lote(produto, lote)
        return []
    linhas = saldos_lotes(produto, local, vendaveis=not permite_vencido)
    if lote is not None:
        conferir_lote(produto, lote)
        linhas = linhas.filter(lote_id=lote.pk)
    restante, plano = quantidade, []
    for linha in linhas:
        retirar = min(restante, linha["saldo"])
        plano.append((linha["lote_id"], retirar))
        restante -= retirar
        if restante == ZERO:
            break
    if restante:
        raise ValidationError(f"{produto.nome}: saldo de lotes {'conferidos' if permite_vencido else 'válidos'} insuficiente. Confira validade e identifique o saldo antigo antes de vender ou transferir.")
    return plano


def registrar_lotes(movimento, plano, *, sinal=1):
    for lote_id, quantidade in plano:
        RegistroLote.objects.create(lote_id=lote_id, local=movimento.local, movimento=movimento,
                                    quantidade=quantidade * sinal, criado_por=movimento.criado_por)


@transaction.atomic
def identificar_saldo(produto, local, lote, quantidade, usuario, motivo, chave):
    from apps.nucleo.sistema import travar

    produto = travar(produto)
    quantidade = quantidade_valida(quantidade)
    conferir_lote(produto, lote)
    if not motivo.strip() or not chave:
        raise ValidationError("Informe o motivo e reabra o formulário para gerar a chave de envio.")
    existente = RegistroLote.objects.filter(chave=chave).first()
    if existente:
        if (existente.lote_id, existente.local_id, existente.quantidade) != (lote.pk, local.pk, quantidade):
            raise ValidationError("A chave de envio já foi usada com outros dados.")
        return existente
    identificado = sum((linha["saldo"] for linha in saldos_lotes(produto, local)), ZERO)
    if quantidade > saldo(produto, local) - identificado:
        raise ValidationError("A quantidade supera o saldo que ainda não foi identificado por lote.")
    registro = RegistroLote.objects.create(lote=lote, local=local, quantidade=quantidade,
                                         criado_por=usuario, motivo=motivo.strip(), chave=chave)
    registrar_auditoria(usuario, "identificacao_lote", registro,
                       {"quantidade": str(quantidade), "motivo": motivo, "lote": lote.pk})
    return registro


@transaction.atomic
def devolver_movimentos(ids, usuario, motivo, *, perda=False):
    """Reverte integralmente as baixas congeladas no item, inclusive seus lotes."""
    movimentos = list(MovimentoEstoque.objects.filter(pk__in=ids).order_by("produto_id", "pk"))
    if len(movimentos) != len(set(ids)):
        raise ValidationError("Não foi possível localizar a origem da baixa de estoque.")
    list(Produto.objects.select_for_update().filter(pk__in=[m.produto_id for m in movimentos]).order_by("pk"))
    for origem in movimentos:
        if origem.quantidade >= ZERO or origem.tipo != MovimentoEstoque.Tipo.SAIDA_VENDA:
            raise ValidationError("A devolução precisa apontar para a saída original da venda.")
        if MovimentoEstoque.objects.filter(devolucao_de=origem).exists():
            raise ValidationError("Esta saída já foi devolvida. Atualize a venda ou comanda.")
        plano = [(r.lote_id, -r.quantidade) for r in origem.lotes.all()]
        volta = _novo_movimento(origem.produto, origem.local, MovimentoEstoque.Tipo.AJUSTE,
                                -origem.quantidade, usuario, custo_unitario=origem.custo_unitario,
                                devolucao_de=origem, observacao=motivo[:200])
        registrar_lotes(volta, plano)
        if perda:
            descarte = _novo_movimento(origem.produto, origem.local, MovimentoEstoque.Tipo.PERDA,
                                      origem.quantidade, usuario, custo_unitario=origem.custo_unitario,
                                      documento=origem.documento, observacao=motivo[:200])
            registrar_lotes(descarte, plano, sinal=-1)
        registrar_auditoria(usuario, "devolucao_estoque", volta,
                           {"origem": origem.pk, "motivo": motivo, "perda": perda})


def composicao_estoque(produto, quantidade):
    quantidade = quantidade_valida(quantidade)
    if not produto.usa_ficha_tecnica:
        return {produto.pk: quantidade}
    itens = list(produto.ingredientes.select_related("ingrediente"))
    if not itens:
        raise ValidationError(f"{produto.nome}: cadastre os ingredientes da ficha técnica antes de vender.")
    baixas = {}
    for item in itens:
        if not item.ingrediente.ativo or item.ingrediente.usa_ficha_tecnica:
            raise ValidationError(f"{produto.nome}: confira os ingredientes da ficha técnica.")
        baixas[item.ingrediente_id] = quantidade_valida(item.quantidade * quantidade)
    return baixas


def conferir_versao_ficha(produto, produtos_travados):
    atual = produtos_travados[produto.pk]
    if (atual.usa_ficha_tecnica, atual.versao_ficha) != (produto.usa_ficha_tecnica, produto.versao_ficha):
        raise ValidationError("A ficha técnica mudou durante o pedido. Atualize e tente novamente.")


@transaction.atomic
def salvar_ficha(produto, componentes, usuario):
    """Substitui uma ficha completa; a venda conserva a baixa que já registrou."""
    ids = {produto.pk} | {i.pk for i, _ in componentes}
    travados = {p.pk: p for p in Produto.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    produto = travados[produto.pk]
    if not produto.usa_ficha_tecnica:
        raise ValidationError("Ative o uso de ficha técnica no cadastro deste produto.")
    if not componentes or len(componentes) > 100 or len(ids) != len(componentes) + 1:
        raise ValidationError("Informe ingredientes diferentes, sem repetir o prato.")
    novos = []
    for ingrediente, quantidade in componentes:
        item = IngredienteFicha(produto=produto, ingrediente=travados[ingrediente.pk],
                                quantidade=quantidade_valida(quantidade))
        if not item.ingrediente.ativo:
            raise ValidationError("O ingrediente está inativo.")
        item.clean()
        novos.append(item)
    produto.ingredientes.all().delete()
    IngredienteFicha.objects.bulk_create(novos)
    produto.versao_ficha += 1
    produto.save(update_fields=["versao_ficha"])
    registrar_auditoria(usuario, "ficha_tecnica_salva", produto,
                       {"versao": produto.versao_ficha, "ingredientes": [
                           {"produto": i.ingrediente_id, "quantidade": str(i.quantidade)} for i in novos]})
    return produto


@transaction.atomic
def registrar_compra(embalagem, local, quantidade, custo_embalagem, usuario, *,
                     lote=None, fornecedor=None, documento="", observacao="", chave=None, fator_conferido=None):
    from .estoque import registrar_entrada

    quantidade = quantidade_valida(quantidade)
    custo = decimal_valido(custo_embalagem, nome="Custo da embalagem", casas=4,
                          maximo=Decimal("99999999.9999")).quantize(Decimal("0.0001"))
    existente = MovimentoEstoque.objects.filter(chave=chave).first() if chave else None
    if existente:
        meta = existente.compra
        if (existente.local_id != local.pk or meta.get("embalagem_id") != embalagem.pk
                or meta.get("quantidade") != str(quantidade) or meta.get("custo_embalagem") != str(custo)
                or existente.fornecedor_id != getattr(fornecedor, "pk", None) or existente.documento != documento
                or set(existente.lotes.values_list("lote_id", flat=True)) != ({lote.pk} if lote else set())):
            raise ValidationError("A chave de envio já foi usada com outros dados.")
        return existente
    Produto.objects.select_for_update().get(pk=embalagem.produto_id)
    embalagem = EmbalagemProduto.objects.select_for_update().select_related("produto").get(pk=embalagem.pk)
    if not embalagem.ativo or not embalagem.produto.ativo:
        raise ValidationError("A embalagem ou produto está inativo.")
    if fator_conferido is not None and quantidade_valida(fator_conferido) != embalagem.fator:
        raise ValidationError("A quantidade por embalagem mudou. Atualize a tela e confira a compra antes de receber.")
    base = quantidade_valida(quantidade * embalagem.fator)
    unitario = decimal_valido((custo / embalagem.fator).quantize(Decimal("0.0001")),
                             nome="Custo na unidade base", casas=4, maximo=Decimal("99999999.9999"))
    compra = {"embalagem_id": embalagem.pk, "embalagem": embalagem.nome,
              "quantidade": str(quantidade), "fator": str(embalagem.fator),
              "custo_embalagem": str(custo), "unidade": embalagem.produto.unidade,
              "valor_total": str(quantidade * custo)}
    return registrar_entrada(embalagem.produto, local, base, unitario, usuario,
                             documento=documento, observacao=observacao, fornecedor=fornecedor,
                             chave=chave, lote=lote, compra=compra)


def disponibilidade_produtos(produtos, local):
    """Disponibilidade do catálogo em consultas por conjunto, incluindo pratos."""
    produtos = list(produtos)
    ids = {p.pk for p in produtos}
    ingredientes = list(IngredienteFicha.objects.filter(produto_id__in=ids).select_related("ingrediente"))
    relacionados = {i.ingrediente_id: i.ingrediente for i in ingredientes}
    todos = {**relacionados, **{p.pk: p for p in produtos}}
    fisicos = dict(MovimentoEstoque.objects.filter(local=local, produto_id__in=todos).values_list(
        "produto_id").annotate(s=Sum("quantidade")))
    validos = defaultdict(lambda: ZERO)
    for linha in saldos_lotes(local=local, vendaveis=True).filter(lote__produto_id__in=todos):
        validos[linha["lote__produto_id"]] += linha["saldo"]
    saldos = {pk: validos[pk] if p.controla_validade else fisicos.get(pk, ZERO) for pk, p in todos.items()}
    fichas = defaultdict(list)
    for item in ingredientes:
        fichas[item.produto_id].append(item)
    for produto in produtos:
        if produto.usa_ficha_tecnica:
            itens = fichas[produto.pk]
            saldos[produto.pk] = min((saldos[i.ingrediente_id] / i.quantidade for i in itens), default=ZERO)
            if any(not i.ingrediente.ativo or i.ingrediente.usa_ficha_tecnica for i in itens):
                saldos[produto.pk] = ZERO
            saldos[produto.pk] = saldos[produto.pk].quantize(Decimal("0.001"), rounding="ROUND_DOWN")
    return {p.pk: saldos[p.pk] for p in produtos}
