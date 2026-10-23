"""
Módulo Restaurante Piscina (ESPECIFICACAO §5.7) — comandas abertas por mesa,
hóspede ou cliente avulso; itens lançados ao longo do dia (baixa estoque);
fechamento com pagamento imediato (caixa) ou conta do quarto. Usa os motores
do núcleo (estoque + caixa) e a conta do quarto via reservas.services.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Mesa(models.Model):
    nome = models.CharField("nome/número", max_length=40, unique=True)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "ponto de atendimento"
        verbose_name_plural = "pontos de atendimento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Comanda(models.Model):
    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"
        CANCELADA = "cancelada", "Cancelada"

    class Destino(models.TextChoices):
        CAIXA = "caixa", "Pagamento imediato"
        CONTA = "conta", "Conta do quarto"

    mesa = models.ForeignKey(
        Mesa, on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="ponto",
    )
    cliente = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="cliente/hóspede",
    )
    rotulo = models.CharField(
        "identificação", max_length=60, blank=True,
        help_text="Ex.: guarda-sol 4, espreguiçadeira 2.",
    )
    local = models.ForeignKey(
        "nucleo.LocalEstoque", on_delete=models.PROTECT,
        related_name="comandas", verbose_name="estoque de origem",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    destino = models.CharField(
        "destino", max_length=8, choices=Destino.choices, blank=True
    )
    desconto = models.DecimalField(
        "desconto (R$)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    forma_pagamento = models.ForeignKey(
        "nucleo.FormaPagamento", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas", verbose_name="forma de pagamento",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comanda", verbose_name="recebimento no caixa",
    )
    conta_ref = models.CharField("conta do quarto", max_length=120, blank=True)
    visita_daypass = models.ForeignKey("daypass.VisitaDayPass", on_delete=models.PROTECT, null=True, blank=True, related_name="comandas")
    conta = models.ForeignKey(
        "reservas.ContaHospedagem", on_delete=models.PROTECT, null=True, blank=True,
        related_name="comandas_restaurante", verbose_name="estadia vinculada",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="comandas", verbose_name="aberta por",
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)
    chave_abertura = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    assinatura_abertura = models.CharField(max_length=64, blank=True, editable=False)
    chave_pedido_portal = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    assinatura_pedido_portal = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = "comanda"
        verbose_name_plural = "comandas"
        ordering = ["-aberta_em"]

    def __str__(self):
        return f"Comanda #{self.pk} — {self.titulo}"

    @property
    def titulo(self) -> str:
        if self.mesa_id:
            return str(self.mesa)
        if self.rotulo:
            return self.rotulo
        if self.cliente_id:
            return self.cliente.nome
        return f"Comanda #{self.pk}"

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    def subtotal(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0.00"))

    def total(self) -> Decimal:
        return self.subtotal() - self.desconto

    @property
    def financeiro(self):
        """Situação do pagamento, independente do preparo e do consumo da comanda."""
        recebido = self.movimento_caixa.valor if self.movimento_caixa_id else Decimal("0.00")
        estornado = sum((mov.valor for mov in self.movimento_caixa.estornos.all()), Decimal("0.00")) \
            if self.movimento_caixa_id else Decimal("0.00")
        status, rotulo = "aberta", "Aguardando pagamento"
        if self.status == self.Status.CANCELADA:
            status, rotulo = "cancelada", "Comanda cancelada"
        elif self.status == self.Status.FECHADA and not self.movimento_caixa_id and self.total() == 0:
            status, rotulo = "sem_cobranca", "Sem valor a receber"
        elif self.destino == self.Destino.CONTA:
            status, rotulo = "conta", "Lançado na conta do quarto"
        elif recebido and estornado == recebido:
            status, rotulo = "estornado_total", "Pagamento estornado"
        elif estornado:
            status, rotulo = "estornado_parcial", "Pagamento parcialmente estornado"
        elif recebido:
            status, rotulo = "pago", "Pago"
        return {"recebido": recebido, "estornado": estornado, "liquido": recebido - estornado,
                "status": status, "rotulo": rotulo}


class ItemComanda(models.Model):
    class Preparo(models.TextChoices):
        AGUARDANDO = "aguardando", "A preparar"
        PREPARANDO = "preparando", "Em preparo"
        PRONTO = "pronto", "Pronto"
        ENTREGUE = "entregue", "Entregue"

    comanda = models.ForeignKey(
        Comanda, on_delete=models.CASCADE, related_name="itens", verbose_name="comanda"
    )
    produto = models.ForeignKey(
        "nucleo.Produto", on_delete=models.PROTECT,
        related_name="itens_comanda", verbose_name="produto",
    )
    descricao = models.CharField("descrição", max_length=120)
    natureza = models.CharField("natureza fiscal", max_length=10)
    quantidade = models.DecimalField("quantidade", max_digits=12, decimal_places=3)
    preco_unitario = models.DecimalField(
        "preço unitário (R$)", max_digits=10, decimal_places=2
    )
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)
    observacoes = models.CharField("observações para preparo", max_length=500, blank=True)
    opcoes = models.JSONField("escolhas do cliente", default=list, blank=True)
    estoque_baixado = models.JSONField("itens retirados do estoque", default=list, blank=True, editable=False)
    movimentos_estoque = models.JSONField("origens das baixas", default=list, blank=True, editable=False)
    preparo = models.CharField("preparo", max_length=12, choices=Preparo.choices, default=Preparo.AGUARDANDO)
    versao = models.PositiveIntegerField("versão", default=1, editable=False)

    class Meta:
        verbose_name = "item da comanda"
        verbose_name_plural = "itens da comanda"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.quantidade} × {self.descricao}"

    @property
    def subtotal(self) -> Decimal:
        return (self.preco_unitario * self.quantidade).quantize(Decimal("0.01"))

    @property
    def resumo_opcoes(self):
        return "; ".join(f"{opcao['grupo']}: {opcao['nome']}" for opcao in self.opcoes)

    @property
    def detalhe_preparo(self):
        return ". ".join(parte for parte in (self.resumo_opcoes, self.observacoes) if parte)


class InclusaoPedido(models.Model):
    """Uma intenção de inclusão; a chave permanece consumida se o item for removido."""

    chave = models.UUIDField(unique=True, editable=False)
    assinatura = models.CharField(max_length=64, editable=False)
    comanda = models.ForeignKey(Comanda, on_delete=models.PROTECT, related_name="inclusoes_pedido")
    item = models.ForeignKey(ItemComanda, on_delete=models.SET_NULL, null=True, related_name="inclusoes_pedido")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "inclusão de pedido"
        verbose_name_plural = "inclusões de pedido"


class GrupoOpcaoCardapio(models.Model):
    produto = models.ForeignKey("nucleo.Produto", on_delete=models.PROTECT, related_name="grupos_opcoes")
    nome = models.CharField("nome do grupo", max_length=60)
    minimo = models.PositiveSmallIntegerField("mínimo de escolhas", default=0)
    maximo = models.PositiveSmallIntegerField("máximo de escolhas", default=1)
    ordem = models.PositiveSmallIntegerField("ordem", default=0)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ["ordem", "pk"]
        constraints = [models.CheckConstraint(
            condition=models.Q(maximo__gte=models.F("minimo")) & models.Q(maximo__gte=1),
            name="grupo_opcao_limites_validos",
        )]

    def __str__(self):
        return f"{self.produto.nome} · {self.nome}"

    def clean(self):
        if self.maximo < 1 or self.minimo > self.maximo:
            raise ValidationError("O máximo deve ser pelo menos 1 e igual ou maior que o mínimo.")


class OpcaoCardapio(models.Model):
    grupo = models.ForeignKey(GrupoOpcaoCardapio, on_delete=models.CASCADE, related_name="opcoes")
    nome = models.CharField("opção", max_length=80)
    adicional = models.DecimalField("adicional por unidade (R$)", max_digits=10, decimal_places=2,
                                    default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    produto_estoque = models.ForeignKey("nucleo.Produto", on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="opcoes_consumo", verbose_name="produto consumido pelo adicional")
    quantidade_estoque = models.DecimalField("quantidade consumida por unidade", max_digits=12, decimal_places=3,
                                           default=Decimal("1"), validators=[MinValueValidator(Decimal("0.001"))])
    ordem = models.PositiveSmallIntegerField("ordem", default=0)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ["ordem", "pk"]

    def __str__(self):
        return self.nome
