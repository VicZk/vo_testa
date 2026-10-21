"""
Módulo Governança (ESPECIFICACAO §5.2) — status de limpeza por quarto, fila de
faxinas geradas por evento (check-out/troca) e **conferência de ocupação** da ronda
(o que a camareira viu em cada quarto), que cruzada com o PMS acha o skip e o
sleeper. Depende de Reservas (ouve o sinal `quarto_liberado`, pergunta a ocupação
por service). Alimenta o Mapa de quartos com o estado real de limpeza.
"""

from django.conf import settings
from django.db import models


class StatusLimpeza(models.Model):
    """Situação de limpeza atual de cada quarto."""

    class Situacao(models.TextChoices):
        # Rótulos no masculino — concordam com "quarto" (Quarto 06 está limpo/sujo).
        LIMPA = "limpa", "Limpo"
        SUJA = "suja", "Sujo"
        EM_LIMPEZA = "em_limpeza", "Em limpeza"
        INSPECIONADA = "inspecionada", "Inspecionado"

    uh = models.OneToOneField(
        "nucleo.UH", on_delete=models.CASCADE,
        related_name="limpeza", verbose_name="quarto",
    )
    situacao = models.CharField(
        "situação", max_length=12, choices=Situacao.choices, default=Situacao.LIMPA
    )
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="atualizado por",
    )

    class Meta:
        verbose_name = "status de limpeza"
        verbose_name_plural = "status de limpeza"

    def __str__(self):
        return f"{self.uh.numero}: {self.get_situacao_display()}"

    @property
    def pronta(self) -> bool:
        return self.situacao in (self.Situacao.LIMPA, self.Situacao.INSPECIONADA)


class TarefaGovernanca(models.Model):
    """Faxina/arrumação de um quarto, atribuída a uma camareira."""

    class Tipo(models.TextChoices):
        FAXINA = "faxina_completa", "Faxina completa"
        ARRUMACAO = "arrumacao", "Arrumação"
        TROCA_ROUPA = "troca_roupa", "Troca de roupa de cama"
        POS_MANUTENCAO = "pos_manutencao", "Pós-manutenção"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="tarefas_governanca", verbose_name="quarto",
    )
    tipo = models.CharField(
        "tipo", max_length=16, choices=Tipo.choices, default=Tipo.FAXINA
    )
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PENDENTE
    )
    camareira = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="faxinas", verbose_name="camareira",
    )
    origem = models.CharField("origem", max_length=20, default="manual")
    observacoes = models.TextField("observações", blank=True)
    gerada_em = models.DateTimeField("gerada em", auto_now_add=True)
    iniciada_em = models.DateTimeField("iniciada em", null=True, blank=True)
    concluida_em = models.DateTimeField("concluída em", null=True, blank=True)

    # Inspeção da supervisora sobre ESTA faxina (quem limpou é quem responde pelo
    # resultado): aprovada marca `inspecionada_em`; reprovada marca `reprovada_em` e
    # nasce outra tarefa com origem="reprovada". É daqui que sai o relatório de
    # inspecionados × reprovados — o status do quarto guarda só o estado de agora.
    inspecionada_em = models.DateTimeField("inspecionada em", null=True, blank=True)
    inspecionada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="inspecionada por",
    )
    reprovada_em = models.DateTimeField("reprovada em", null=True, blank=True)
    motivo_reprovacao = models.CharField("motivo da reprovação", max_length=200, blank=True)

    class Meta:
        verbose_name = "tarefa de governança"
        verbose_name_plural = "tarefas de governança"
        ordering = ["status", "gerada_em"]

    def __str__(self):
        return f"{self.get_tipo_display()} — {self.uh.numero} ({self.get_status_display()})"

    @property
    def ativa(self) -> bool:
        return self.status != self.Status.CONCLUIDA

    @property
    def duracao(self):
        """Tempo entre iniciar e concluir (timedelta), ou None se faltar um dos dois."""
        if self.iniciada_em and self.concluida_em:
            return self.concluida_em - self.iniciada_em
        return None


class ConferenciaOcupacao(models.Model):
    """O que a camareira VIU no quarto durante a ronda.

    A governança é a única que entra em todos os quartos todo dia, e até aqui não
    dizia nada sobre ocupação: o PMS podia jurar que o 12 estava ocupado com o
    hóspede já embora (conta em aberto) ou livre com gente dentro (check-in não
    lançado) e ninguém cruzava as duas versões.

    Histórico, nunca sobrescreve: cada toque é uma linha nova (a ronda da manhã e a
    da tarde contam separado, e a correção de quem errou o botão fica à vista). A
    comparação com o PMS fica GRAVADA no momento da ronda (`pms_ocupado`,
    `divergencia`, `reserva_id`) — é um retrato, como a ficha do FNRH: amanhã a
    reserva de hoje não está mais hospedada e o relatório do mês continuaria certo.
    A tela de hoje, essa sim, refaz a conta ao vivo — divergência resolvida pela
    recepção tem de sair da lista.
    """

    class Visto(models.TextChoices):
        VAGO = "vago", "Vago"
        OCUPADO = "ocupado", "Ocupado (com bagagem)"
        SEM_BAGAGEM = "ocupado_sem_bagagem", "Ocupado sem bagagem"

    class Divergencia(models.TextChoices):
        OK = "ok", "Confere"
        SKIP = "skip", "Saiu sem check-out (skip)"
        SAIDA_NAO_LANCADA = "saida_nao_lancada", "Saída não lançada"
        SLEEPER = "sleeper", "Hóspede sem check-in (sleeper)"
        SEM_BAGAGEM = "sem_bagagem", "Ocupado sem bagagem"
        SEM_BASE = "sem_base", "Sem base de comparação"

    # Divergências que pedem ação de alguém (as outras são registro da ronda).
    DIVERGENTES = (Divergencia.SKIP, Divergencia.SAIDA_NAO_LANCADA,
                   Divergencia.SLEEPER, Divergencia.SEM_BAGAGEM)

    # Rótulo curto do botão da ronda (o de `choices` explica no `title`): três alvos
    # lado a lado no celular da camareira não cabem com a frase inteira.
    CURTO = {Visto.VAGO: "Vago", Visto.OCUPADO: "Com bagagem",
             Visto.SEM_BAGAGEM: "Sem bagagem"}

    @classmethod
    def botoes_da_ronda(cls):
        """[(valor, rótulo curto, explicação)] — a ordem dos botões na linha."""
        return [(cod, cls.CURTO[cod], label) for cod, label in cls.Visto.choices]

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="conferencias_ocupacao", verbose_name="quarto",
    )
    dia = models.DateField("dia da ronda")
    visto = models.CharField("o que foi visto", max_length=20, choices=Visto.choices)
    # Retrato do PMS na hora da ronda. Nulo = Reservas inativo (sem base de comparação).
    pms_ocupado = models.BooleanField("PMS dizia ocupado", null=True, blank=True)
    # Referência SOLTA à reserva (mesmo padrão de `cobranca_id`): a Governança não
    # importa models de Reservas, então aqui não cabe uma FK.
    reserva_id = models.PositiveIntegerField("reserva no PMS", null=True, blank=True)
    divergencia = models.CharField(
        "divergência", max_length=20, choices=Divergencia.choices,
        default=Divergencia.OK,
    )
    observacao = models.CharField("observação", max_length=200, blank=True)
    registrado_em = models.DateTimeField("registrado em", auto_now_add=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="conferencias_ocupacao", verbose_name="registrado por",
    )

    class Meta:
        verbose_name = "conferência de ocupação"
        verbose_name_plural = "conferências de ocupação"
        ordering = ["-registrado_em"]
        indexes = [
            # A pergunta da tela é sempre "a ronda de hoje, por quarto".
            models.Index(fields=["dia", "uh"], name="gov_conf_dia_uh"),
            models.Index(fields=["dia", "divergencia"], name="gov_conf_dia_diverg"),
        ]

    def __str__(self):
        return f"{self.uh.numero} em {self.dia:%d/%m}: {self.get_visto_display()}"

    @property
    def ocupado(self) -> bool:
        """Viu gente/bagagem — com ou sem mala, o quarto está em uso."""
        return self.visto != self.Visto.VAGO

    @property
    def divergente(self) -> bool:
        return self.divergencia in self.DIVERGENTES
