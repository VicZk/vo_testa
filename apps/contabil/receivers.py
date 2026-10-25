"""
Sinais da camada Contábil (Etapa 2) — o núcleo NÃO depende daqui.

- Carimba `conta_contabil` em LancamentoFinanceiro e ContaPagarReceber recém-criados
  (resolve via de-para). Usa `.update()` para não disparar o próprio post_save de
  novo (sem recursão) nem poluir a trilha de auditoria.
- Quando nasce uma CategoriaFinanceira sem de-para, cria um MapeamentoContabil
  inicial (heurístico) — mantém o de-para completo e o "nunca órfão".
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.nucleo.models.financeiro import (
    CategoriaFinanceira,
    ContaPagarReceber,
    LancamentoFinanceiro,
)

from .classificacao import classificacao_para
from .models import ContaContabil, MapeamentoContabil
from .services import resolver_conta

# Categoria `automatica` é alimentada por captura ou pelo fechamento: a DRE já tem o
# valor pela competência. A baixa de um título dela (faturado que a agência pagou,
# folha paga por recorrência) é só o dinheiro chegando ou saindo — vai para a conta
# patrimonial de liquidação, nunca de novo para receita ou custo.
LIQUIDACAO = {
    CategoriaFinanceira.Tipo.RECEITA: "liquidacao_receita",
    CategoriaFinanceira.Tipo.DESPESA: "liquidacao_despesa",
}


def _conta_da_entrada(tipo, categoria, centro, *, liquida=True):
    if liquida and categoria is not None and categoria.automatica:
        conta = resolver_conta(tipo=tipo, origem_sistema=LIQUIDACAO.get(tipo, ""))
        if conta:
            return conta
    return resolver_conta(tipo=tipo, categoria=categoria, centro=centro)


@receiver(post_save, sender=LancamentoFinanceiro)
def _carimbar_lancamento(sender, instance, created, **kwargs):
    if not created or instance.conta_contabil:
        return
    # Captura e fechamento chegam com a conta carimbada; se o de-para deles faltar, a
    # receita/custo capturada não pode virar liquidação — só a baixa manual (origem
    # "manual") de um título é dinheiro de algo já reconhecido.
    conta = _conta_da_entrada(instance.tipo, instance.categoria, instance.centro,
                              liquida=instance.origem == "manual")
    if conta:
        sender.objects.filter(pk=instance.pk).update(
            conta_contabil=conta.classificacao
        )


@receiver(post_save, sender=ContaPagarReceber)
def _carimbar_conta(sender, instance, created, **kwargs):
    if not created or instance.conta_contabil:
        return
    tipo = (
        CategoriaFinanceira.Tipo.DESPESA
        if instance.tipo == ContaPagarReceber.Tipo.PAGAR
        else CategoriaFinanceira.Tipo.RECEITA
    )
    conta = _conta_da_entrada(tipo, instance.categoria, instance.centro)
    if conta:
        sender.objects.filter(pk=instance.pk).update(
            conta_contabil=conta.classificacao
        )


@receiver(post_save, sender=CategoriaFinanceira)
def _garantir_depara_categoria(sender, instance, created, **kwargs):
    if not created:
        return
    if MapeamentoContabil.objects.filter(categoria=instance).exists():
        return
    classif = classificacao_para(instance.nome, instance.tipo)
    conta = ContaContabil.objects.filter(classificacao=classif).first()
    if conta:
        MapeamentoContabil.objects.create(
            conta=conta, categoria=instance, prioridade=10,
            observacao="de-para automático (categoria nova)",
        )
