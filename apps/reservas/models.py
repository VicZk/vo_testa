"""
Módulo Reservas (ESPECIFICACAO §5.1) — o carro-chefe.

Fonte de verdade da DISPONIBILIDADE. Regras que não se quebram:
- Overbooking é impossível no banco: ExclusionConstraint (PostgreSQL) impede
  duas reservas ativas na mesma UH com períodos sobrepostos.
- Todo lançamento da conta carrega natureza fiscal (SERVIÇO | CONSUMO),
  obrigatória, sem default silencioso.
- Pagamento da conta passa pelo caixa do operador (MovimentoCaixa do núcleo).
- Cancelamento exige motivo; ações sensíveis são auditadas.

Só importa models do NÚCLEO (permitido) — nunca de outros módulos.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Func, Q, Sum
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, Temporada, TipoUH, registrar_auditoria


def validar_periodo_day_use(tipo_uh, checkin, checkout):
    """Day use é de um dia só: no banco ele ocupa a unidade de `checkin` até
    `checkout` = dia seguinte (uma "noite"), como o site já cria. Mais que isso
    ocuparia a unidade de day use por dias."""
    if (tipo_uh is not None and checkin and checkout
            and tipo_uh.modalidade == TipoUH.Modalidade.DAY_USE
            and (checkout - checkin).days != 1):
        raise ValidationError(
            "Day use é de um dia só: a saída precisa ser no dia seguinte à entrada."
        )


class Tarifa(models.Model):
    """Matriz TipoUH × classificação de temporada. Sem linha → tarifa_base do tipo."""

    tipo_uh = models.ForeignKey(
        "nucleo.TipoUH", on_delete=models.CASCADE,
        related_name="tarifas", verbose_name="tipo de UH",
    )
    classificacao = models.CharField(
        "classificação da temporada", max_length=12,
        choices=Temporada.Classificacao.choices,
    )
    valor = models.DecimalField(
        "diária (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        verbose_name = "tarifa"
        verbose_name_plural = "tarifas"
        ordering = ["tipo_uh__nome", "classificacao"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_uh", "classificacao"],
                name="tarifa_unica_por_tipo_e_classificacao",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_uh.nome} / {self.get_classificacao_display()}: R$ {self.valor}"


class TarifaUnidade(models.Model):
    """Preço por QUARTO × classificação de temporada. Vende-se por unidade: cada
    quarto pode ter seu próprio preço sazonal. Sem linha → cai na tarifa do tipo."""

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.CASCADE,
        related_name="tarifas_unidade", verbose_name="quarto",
    )
    classificacao = models.CharField(
        "classificação da temporada", max_length=12,
        choices=Temporada.Classificacao.choices,
    )
    valor = models.DecimalField(
        "diária base — 2 adultos (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    pessoa_adicional = models.DecimalField(
        "pessoa adicional (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Valor por adulto além dos 2 da base, nesta temporada. "
                  "Vazio = usa o do tipo. Criança 6-15 paga metade; ≤5 não paga.",
    )
    meia = models.DecimalField(
        "meia — criança 6-15 (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Valor por criança de 6 a 15 anos. Vazio = metade da pessoa "
                  "adicional. ≤5 não paga.",
    )

    class Meta:
        verbose_name = "tarifa por quarto"
        verbose_name_plural = "tarifas por quarto"
        ordering = ["uh__numero", "classificacao"]
        constraints = [
            models.UniqueConstraint(
                fields=["uh", "classificacao"],
                name="tarifa_unica_por_quarto_e_classificacao",
            ),
        ]

    def __str__(self):
        return f"{self.uh.numero} / {self.get_classificacao_display()}: R$ {self.valor}"


class TarifaTemporada(models.Model):
    """Preço por QUARTO num feriado/temporada ESPECÍFICO (ex.: Natal, Ano Novo).

    Vence o preço da classificação: quando a data cai numa temporada que tem linha
    aqui para o quarto, usa-se este valor. Permite Natal ≠ Ano Novo ≠ feriado comum.
    Sem linha → cai na tarifa da classificação (TarifaUnidade) → tipo."""

    temporada = models.ForeignKey(
        "nucleo.Temporada", on_delete=models.CASCADE,
        related_name="tarifas_quarto", verbose_name="temporada",
    )
    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.CASCADE,
        related_name="tarifas_temporada", verbose_name="quarto",
    )
    valor = models.DecimalField(
        "diária base — 2 adultos (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    pessoa_adicional = models.DecimalField(
        "pessoa adicional (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Valor por adulto além dos 2. Vazio = usa o do tipo.",
    )
    meia = models.DecimalField(
        "meia — criança 6-15 (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Valor por criança de 6 a 15 anos. Vazio = metade da pessoa adicional.",
    )

    class Meta:
        verbose_name = "tarifa de feriado por quarto"
        verbose_name_plural = "tarifas de feriado por quarto"
        ordering = ["temporada__inicio", "uh__numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["temporada", "uh"],
                name="tarifa_unica_por_temporada_e_quarto",
            ),
        ]

    def __str__(self):
        return f"{self.temporada.nome} / {self.uh.numero}: R$ {self.valor}"


class TarifaDayUse(models.Model):
    """Preço do Dia na Pousada (day use) por PESSOA, por classificação de temporada.
    Day use não é por quarto — é por pessoa. Sem linha → cai no `preco_day_use` do tipo."""

    classificacao = models.CharField(
        "classificação da temporada", max_length=12,
        choices=Temporada.Classificacao.choices, unique=True,
    )
    valor_adulto = models.DecimalField(
        "valor por adulto (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    valor_meia = models.DecimalField(
        "meia — criança 6-15 (R$)", max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Vazio = metade do adulto. ≤5 não paga.",
    )

    class Meta:
        verbose_name = "tarifa de day use"
        verbose_name_plural = "tarifas de day use"
        ordering = ["classificacao"]

    def __str__(self):
        return f"Day use / {self.get_classificacao_display()}: R$ {self.valor_adulto}"


class Reserva(models.Model):
    """
    Ciclo: Orçamento → Pré-reserva → Confirmada → Hospedada → Check-out.
    Orçamento não segura UH; os demais estados ativos seguram (constraint).
    """

    class Status(models.TextChoices):
        ORCAMENTO = "orcamento", "Orçamento"
        PRE_RESERVA = "pre_reserva", "Pré-reserva"
        CONFIRMADA = "confirmada", "Confirmada"
        HOSPEDADA = "hospedada", "Hospedada"
        CHECKOUT = "checkout", "Saída"
        CANCELADA = "cancelada", "Cancelada"
        NO_SHOW = "no_show", "Não compareceu"

    # Estados que seguram a UH (entram na constraint antioverbooking)
    STATUS_ATIVOS = [Status.PRE_RESERVA, Status.CONFIRMADA, Status.HOSPEDADA]

    class Canal(models.TextChoices):
        BALCAO = "balcao", "Balcão/telefone"
        WHATSAPP = "whatsapp", "WhatsApp"
        SITE = "site", "Site/APP"
        OTA = "ota", "Sites de reserva (Booking/Airbnb)"

    class Faturamento(models.TextChoices):
        PARTICULAR = "particular", "Particular (o hóspede paga)"
        AGENCIA = "agencia", "Agência"
        EMPRESA = "empresa", "Empresa"

    class SincFNRH(models.TextChoices):
        NAO_ENVIADA = "nao_enviada", "Não enviada"
        PENDENTE = "pendente", "Pendente de envio"
        ENVIADA = "enviada", "Enviada à FNRH"
        ERRO = "erro", "Erro no envio"

    uh = models.ForeignKey(
        "nucleo.UH", on_delete=models.PROTECT,
        related_name="reservas", verbose_name="quarto",
    )
    hospede = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT,
        related_name="reservas", verbose_name="hóspede",
    )
    faturamento = models.CharField(
        "faturamento", max_length=12, choices=Faturamento.choices,
        default=Faturamento.PARTICULAR,
    )
    titular = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="reservas_faturadas", verbose_name="titular do faturamento",
        help_text="Quem paga a conta, quando não é o próprio hóspede (agência/empresa).",
    )
    grupo = models.ForeignKey(
        "GrupoReserva", on_delete=models.PROTECT, null=True, blank=True,
        related_name="filhas", verbose_name="grupo (reserva-mãe)",
        help_text="Bloco de quartos: as diárias vão ao folio do grupo; o consumo "
                  "fica na conta do quarto. Vazio = reserva avulsa.",
    )
    checkin = models.DateField("entrada (check-in)")
    checkout = models.DateField("saída (check-out)")
    adultos = models.PositiveSmallIntegerField("adultos (16+)", default=2)
    criancas = models.PositiveSmallIntegerField("crianças", default=0)
    # Faixas etárias p/ o preço (Manual §2): ≤5 não paga · 6-15 meia pessoa adicional ·
    # 16+ conta como adulto. `criancas` = total (0-5 + 6-15), mantido pelos forms.
    criancas_0_5 = models.PositiveSmallIntegerField("crianças até 5 anos", default=0)
    criancas_6_15 = models.PositiveSmallIntegerField("crianças de 6 a 15 anos", default=0)
    cobra_iss = models.BooleanField("cobrar ISS", default=True)
    cobra_taxa_turismo = models.BooleanField("cobrar taxa de turismo", default=True)
    # Tarifa não-reembolsável: desconto pré-pago (ConfiguracaoReservas), sem direito a
    # cancelamento. O desconto já entra na diária acordada ao criar a reserva.
    nao_reembolsavel = models.BooleanField("tarifa não-reembolsável", default=False)
    # Berço (grátis, recurso global limitado — não conta como pessoa/cama/colchão).
    usa_berco = models.BooleanField("usa berço", default=False)
    # Arranjo de camas (estoque de colchões — docs/Reservas/PLANO_ESTOQUE_COLCHOES.md).
    # casal = 2 colchões de solteiro; base do quarto (2×casais_max) é garantida; só o que
    # passa dela consome o pool de "colchões extra". Sofá-cama NÃO consome colchão.
    casais = models.PositiveSmallIntegerField("camas de casal", default=1)
    solteiros = models.PositiveSmallIntegerField("camas de solteiro (avulsas)", default=0)
    usa_sofa_cama = models.BooleanField("usa o sofá-cama", default=False)
    status = models.CharField(
        "status", max_length=12, choices=Status.choices, default=Status.PRE_RESERVA
    )
    canal = models.CharField(
        "canal", max_length=10, choices=Canal.choices, default=Canal.BALCAO
    )
    valor_diaria = models.DecimalField(
        "diária acordada (R$)", max_digits=10, decimal_places=2,
        help_text="Preenchida pela tarifa vigente; alteração manual exige gerência.",
    )
    valor_hospedagem = models.DecimalField(
        "hospedagem cotada (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Soma exata das diárias da cotação. A diária acordada é a média "
                  "arredondada; as diárias lançadas no check-in somam este valor.",
    )
    observacoes = models.TextField("observações", blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)
    valor_retido = models.DecimalField(
        "retido no cancelamento (R$)", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="O que a política de cancelamento deixa com a pousada (diárias usadas + "
                  "retenção), gravado no cancelamento. O resto do que foi pago é devolvido.",
    )
    expira_em = models.DateTimeField(
        "retenção até", null=True, blank=True,
        help_text="Pré-reserva de canal (site) segura o quarto só até aqui; depois expira.",
    )
    checkin_real = models.DateTimeField("entrada realizada em", null=True, blank=True)
    # Marco da confirmação (pagamento do sinal) — referência da janela de 7 dias de
    # arrependimento (CDC). Ver apps/reservas/cancelamento.py.
    confirmada_em = models.DateTimeField("confirmada em", null=True, blank=True)
    checkout_real = models.DateTimeField("saída realizada em", null=True, blank=True)
    # Sincronização com a FNRH Digital (Embratur/Serpro) — ver fnrh_gateway.py
    fnrh_reserva_id = models.UUIDField("ID da reserva na FNRH", null=True, blank=True)
    fnrh_status = models.CharField(
        "situação FNRH", max_length=12,
        choices=SincFNRH.choices, default=SincFNRH.NAO_ENVIADA,
    )
    fnrh_sincronizada_em = models.DateTimeField("sincronizada com a FNRH em", null=True, blank=True)
    fnrh_erro = models.TextField("último erro FNRH", blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="reservas_criadas", verbose_name="criada por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["-checkin"]
        # Chegadas, saídas e hospedados do dia (mapa, dashboard, Auditoria) filtram por
        # situação + data; sem índice, cada tela varre a tabela inteira.
        indexes = [
            models.Index(fields=["status", "checkin"], name="reserva_status_checkin_idx"),
            models.Index(fields=["status", "checkout"], name="reserva_status_checkout_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(checkout__gt=F("checkin")),
                name="reserva_checkout_depois_do_checkin",
            ),
            # Antioverbooking: duas reservas ativas não podem ocupar a mesma UH
            # em períodos sobrepostos. daterange é [checkin, checkout) — a noite
            # do checkout fica livre para a próxima entrada.
            ExclusionConstraint(
                name="reserva_sem_overbooking",
                expressions=[
                    (F("uh"), RangeOperators.EQUAL),
                    (
                        Func(
                            F("checkin"), F("checkout"),
                            function="daterange",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status__in=["pre_reserva", "confirmada", "hospedada"]),
            ),
        ]

    def __str__(self):
        return (
            f"Reserva #{self.pk} — {self.hospede.nome} — {self.uh.numero} "
            f"({self.checkin:%d/%m} → {self.checkout:%d/%m})"
        )

    @property
    def noites(self) -> int:
        return (self.checkout - self.checkin).days

    @property
    def ativa(self) -> bool:
        return self.status in self.STATUS_ATIVOS

    @property
    def pagador(self):
        """Quem paga: o titular do faturamento ou, se particular, o próprio hóspede."""
        return self.titular or self.hospede

    @property
    def total_hospedes(self) -> int:
        return self.adultos + self.criancas

    def valores_das_diarias(self) -> list[Decimal]:
        """O valor de cada noite lançado no check-in. A diária acordada é a média
        arredondada da cotação; quando a reserva guarda o total exato
        (`valor_hospedagem`), a última noite absorve os centavos do arredondamento e a
        soma bate com o que foi cotado ao hóspede. Sem total exato (diária definida à
        mão), ou se ele não combinar mais com a diária, todas as noites valem a diária."""
        noites = self.noites
        if noites <= 0:
            return []
        diarias = [self.valor_diaria] * noites
        if self.valor_hospedagem is not None:
            resto = self.valor_hospedagem - self.valor_diaria * noites
            # Só arredondamento (até meio centavo por noite) é absorvido.
            if abs(resto) <= Decimal("0.005") * noites + Decimal("0.005"):
                diarias[-1] = self.valor_diaria + resto
        return diarias

    def hospedagem_prevista(self) -> Decimal:
        """Total das diárias que o check-in vai lançar."""
        return sum(self.valores_das_diarias(), Decimal("0.00"))

    def total_previsto(self, cfg=None) -> Decimal:
        """O que a estadia vai custar no check-in: diárias + ISS + taxa de turismo, pelas
        mesmas regras de `ContaHospedagem.lancar_diarias`/`lancar_taxas`. Sem consumo.

        `cfg` = a `ConfiguracaoReservas` já carregada, para quem calcula o total de uma
        LISTA de reservas (Kit de contingência) sem reler a configuração a cada linha."""
        base = self.hospedagem_prevista()
        if not getattr(settings, "PRECO_TAXAS_ATIVAS", True):
            return base
        from apps.reservas.precos import taxas

        t = taxas(base, cobra_iss=self.cobra_iss,
                  cobra_taxa_turismo=self.cobra_taxa_turismo, diarias=self.noites,
                  cfg=cfg)
        return base + t["iss"] + t["taxa_turismo"]

    @property
    def colchoes_consumidos(self) -> int:
        """Colchões de solteiro que o arranjo ocupa: casal = 2, solteiro avulso = 1."""
        return 2 * (self.casais or 0) + (self.solteiros or 0)

    @property
    def colchoes_extra(self) -> int:
        """Colchões deste arranjo que saem do POOL de extras (acima da base garantida
        do quarto = 2×casais_max). Sofá-cama não entra. Day use e quartos sem
        configuração de camas = 0."""
        from apps.nucleo.estrutura import casais_max
        from apps.reservas.colchoes import configurado
        if not self.uh_id or not configurado(self.uh):
            return 0
        base = 2 * casais_max(self.uh)
        return max(0, self.colchoes_consumidos - base)

    @property
    def menores_pendentes(self) -> list:
        """Fichas de menores de idade sem os pais/responsável nem autorização conferida."""
        return [f for f in self.fichas_fnrh.all() if not f.menor_regular]

    @property
    def fnrh_pronta(self) -> bool:
        """FNRH em ordem para check-in: uma ficha completa por hóspede, com o
        titular entre elas."""
        fichas = list(self.fichas_fnrh.all())
        completas = [f for f in fichas if f.completa]
        tem_titular = any(f.titular and f.completa for f in fichas)
        return tem_titular and len(completas) >= self.total_hospedes

    @property
    def status_ajuda(self) -> str:
        """Explicação do status, para dica ao passar o mouse."""
        return {
            self.Status.ORCAMENTO: "Cotação de preço — não segura o quarto.",
            self.Status.PRE_RESERVA: "Reserva provisória — segura o quarto por um tempo até a confirmação.",
            self.Status.CONFIRMADA: "Sinal recebido ou garantia registrada.",
            self.Status.HOSPEDADA: "Hóspede em casa (entrada já feita).",
            self.Status.CHECKOUT: "Estadia encerrada (saída já feita).",
            self.Status.CANCELADA: "Reserva cancelada.",
            self.Status.NO_SHOW: "Confirmada, mas o hóspede não compareceu.",
        }.get(self.status, "")

    def clean(self):
        if self.checkin and self.checkout and self.checkout <= self.checkin:
            raise ValidationError(
                {"checkout": "A saída (check-out) deve ser depois da entrada (check-in)."}
            )
        if self.uh_id:
            validar_periodo_day_use(self.uh.tipo, self.checkin, self.checkout)
        # Pelo menos 1 adulto: 0 hóspedes burlaria a trava de FNRH (len>=0) e zeraria
        # o cálculo de colchão/diária.
        if (self.adultos or 0) < 1:
            raise ValidationError({"adultos": "Informe ao menos 1 adulto."})
        if self.faturamento != self.Faturamento.PARTICULAR and not self.titular_id:
            raise ValidationError(
                {"titular": "Faturamento por agência/empresa exige o titular."}
            )
        if self.faturamento == self.Faturamento.PARTICULAR:
            # Particular: o hóspede é o pagador; não guardamos titular separado.
            self.titular = None

    # ---- Transições de estado ----

    def _exige_status(self, *validos):
        if self.status not in validos:
            nomes = ", ".join(self.Status(s).label for s in validos)
            raise ValidationError(
                f"Ação disponível apenas para reserva em: {nomes}."
            )

    def confirmar(self, usuario):
        """Pré-reserva/orçamento → confirmada (sinal recebido ou garantia)."""
        era_orcamento = self.status == self.Status.ORCAMENTO
        self._exige_status(self.Status.ORCAMENTO, self.Status.PRE_RESERVA)
        # Orçamento não reservava o pool de colchões; ao ativar, revalida a noite
        # (pré-reserva já contava, então só o orçamento precisa reconferir).
        if era_orcamento:
            from apps.reservas.colchoes import configurado
            from apps.reservas.services import conferir_arranjo
            if configurado(self.uh):
                conf = conferir_arranjo(
                    self.uh, casais=self.casais, solteiros=self.solteiros,
                    usa_sofa_cama=self.usa_sofa_cama, adultos=self.adultos,
                    criancas=self.criancas, checkin=self.checkin,
                    checkout=self.checkout, excluir_id=self.pk)
                if conf["erros"]:
                    raise ValidationError(conf["erros"])
        self.status = self.Status.CONFIRMADA
        self.expira_em = None  # confirmada não expira mais
        if self.confirmada_em is None:
            self.confirmada_em = timezone.now()  # marca a janela de arrependimento
        self.save()

    @transaction.atomic
    def fazer_checkin(self, usuario):
        # Atômico + trava da reserva: se uma diária/taxa falhar, nada fica pela
        # metade (reserva hospedada com conta incompleta); clique duplo ou duas
        # recepções ao mesmo tempo esbarram no status já relido do banco.
        from apps.nucleo.sistema import travar

        travar(self)
        self._exige_status(self.Status.CONFIRMADA, self.Status.PRE_RESERVA)
        # FNRH obrigatória: ficha completa de cada hóspede antes de hospedar.
        if getattr(settings, "FNRH_BLOQUEAR_CHECKIN", True) and not self.fnrh_pronta:
            raise ValidationError(
                "FNRH pendente — registre a ficha de cada hóspede antes do check-in."
            )
        if getattr(settings, "ECA_BLOQUEAR_CHECKIN", True):
            pendentes = self.menores_pendentes
            if pendentes:
                nomes = ", ".join(f.nome or "sem nome" for f in pendentes)
                raise ValidationError(
                    f"Menor de idade sem os pais ou o responsável legal, nem autorização "
                    f"escrita conferida (ECA, art. 82): {nomes}. Registre na FNRH."
                )
        if self.uh.status != self.uh.Status.ATIVA:
            raise ValidationError(
                f"O quarto {self.uh.numero} está {self.uh.get_status_display().lower()}."
            )
        # Governança ativa: só entra em quarto limpo/inspecionado (degrada se off).
        from apps.nucleo.models import modulo_ativo
        from apps.nucleo.modulos import Modulo

        if modulo_ativo(Modulo.GOVERNANCA):
            from apps.governanca.services import uh_pronta_para_checkin

            if not uh_pronta_para_checkin(self.uh):
                raise ValidationError(
                    f"O quarto {self.uh.numero} não está limpo/inspecionado — "
                    "aguarde a governança."
                )
        self.status = self.Status.HOSPEDADA
        self.checkin_real = timezone.now()
        # Marca para envio à FNRH (o push real é best-effort, fora da transação).
        if self.fnrh_status == self.SincFNRH.NAO_ENVIADA:
            self.fnrh_status = self.SincFNRH.PENDENTE
        self.save()
        conta = ContaHospedagem.objects.create(reserva=self)
        # Grupo (folio híbrido): diária + colchão vão ao folio-mãe; o consumo fica
        # nesta conta do quarto. Reserva avulsa: tudo na própria conta.
        acomodacao = self.grupo.folio if self.grupo_id else conta
        total_diarias = acomodacao.lancar_diarias(usuario, reserva=self)
        # Colchão extra deixou de cobrar (virou só disponibilidade — Fase 6). A pessoa
        # extra é cobrada na própria diária (pessoa adicional, Manual §2); aqui só as taxas.
        acomodacao.lancar_taxas(usuario, reserva=self, base=total_diarias)
        return conta

    @transaction.atomic
    def fazer_checkout(self, usuario):
        # Trava reserva e conta antes de conferir o saldo: um consumo lançado ao
        # mesmo tempo (lancar_na_conta também trava a conta) ou entra antes e
        # aparece no saldo, ou chega depois e é recusado por conta fechada.
        from apps.nucleo.sistema import travar

        travar(self)
        self._exige_status(self.Status.HOSPEDADA)
        conta = travar(self.conta)
        # Único bloqueio de check-out é o dinheiro: saldo tem que estar zerado.
        # (A pousada não trabalha com consumo de frigobar, então não há trava de
        # conferência na saída.)
        saldo = conta.saldo()
        tolerancia = Decimal(str(getattr(settings, "CHECKOUT_TOLERANCIA_ARREDONDAMENTO", "0")))
        if Decimal("0.00") < saldo <= tolerancia:
            # Centavos de arredondamento (diária média × noites ≠ total cotado): o
            # hóspede pagou o valor combinado e o atendente não pode dar desconto
            # (exige gerência). Quita o resíduo com um desconto rastreável.
            LancamentoConta.objects.create(
                conta=conta, tipo=LancamentoConta.Tipo.DESCONTO,
                natureza=NaturezaFiscal.SERVICO,
                descricao="Ajuste de arredondamento no check-out",
                valor=saldo, criado_por=usuario,
            )
            registrar_auditoria(
                usuario, "ajuste_arredondamento", self, {"valor": str(saldo)}
            )
            saldo = conta.saldo()
        if saldo < 0:
            raise ValidationError(
                f"O hóspede tem R$ {-saldo} de crédito nesta conta (pagou mais do que o "
                "total): devolva a diferença em \"Devolver ao hóspede\" antes de fechar."
            )
        if saldo != Decimal("0.00"):
            raise ValidationError(
                f"A conta tem saldo de R$ {saldo} — receba ou ajuste antes."
            )
        conta.status = ContaHospedagem.Status.FECHADA
        conta.fechada_em = timezone.now()
        conta.save()
        self.status = self.Status.CHECKOUT
        self.checkout_real = timezone.now()
        self.save()
        # Governança (se ativa) escuta este sinal para gerar a faxina. `emitir`: um
        # módulo ouvinte que falhe não desfaz a saída (ver apps/nucleo/sinais.py).
        from apps.nucleo.sinais import emitir

        from .signals import quarto_liberado

        emitir(
            quarto_liberado, sender=self.__class__, uh=self.uh, reserva=self,
            usuario=usuario, origem="checkout",
        )

    def cancelar(self, usuario, motivo: str):
        self._exige_status(
            self.Status.ORCAMENTO, self.Status.PRE_RESERVA, self.Status.CONFIRMADA
        )
        if not motivo.strip():
            raise ValidationError("Informe o motivo do cancelamento.")
        self.status = self.Status.CANCELADA
        self.motivo_cancelamento = motivo
        self.save()
        registrar_auditoria(
            usuario, "cancelamento_reserva", self, {"motivo": motivo}
        )
        from apps.nucleo.sinais import emitir

        from .signals import reserva_encerrada

        emitir(
            reserva_encerrada, sender=self.__class__, reserva=self, evento="cancelada",
            motivo=motivo, usuario=usuario,
        )

    def marcar_no_show(self, usuario):
        self._exige_status(self.Status.CONFIRMADA)
        self.status = self.Status.NO_SHOW
        self.save()
        registrar_auditoria(usuario, "no_show", self, {})
        from apps.nucleo.sinais import emitir

        from .signals import reserva_encerrada

        emitir(
            reserva_encerrada, sender=self.__class__, reserva=self, evento="no_show",
            motivo="", usuario=usuario,
        )


class GrupoReserva(models.Model):
    """Reserva-mãe: bloco de quartos com um titular e um folio compartilhado.

    Não ocupa quarto — cada quarto é uma `Reserva` (filha) com FK `grupo`. As
    diárias de todas as filhas caem no folio-mãe (`folio`), pago pelo titular; o
    consumo fica na conta de cada quarto. O status é derivado das filhas.
    """

    rotulo = models.CharField(
        "identificação do grupo", max_length=120,
        help_text="Ex.: «Grupo Ribeiro», «Casamento Ana & João».",
    )
    titular = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.PROTECT,
        related_name="grupos_titular", verbose_name="titular (paga o folio)",
    )
    faturamento = models.CharField(
        "faturamento", max_length=12, choices=Reserva.Faturamento.choices,
        default=Reserva.Faturamento.PARTICULAR,
    )
    canal = models.CharField(
        "canal", max_length=10, choices=Reserva.Canal.choices,
        default=Reserva.Canal.BALCAO,
    )
    checkin = models.DateField("entrada (check-in)")
    checkout = models.DateField("saída (check-out)")
    observacoes = models.TextField("observações", blank=True)
    motivo_cancelamento = models.TextField("motivo do cancelamento", blank=True)
    expira_em = models.DateTimeField(
        "retenção até", null=True, blank=True,
        help_text="Pré-reserva do grupo: segura os quartos só até aqui; depois expira.",
    )
    encerrado_em = models.DateTimeField("encerrado em", null=True, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="grupos_criados", verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "reserva de grupo"
        verbose_name_plural = "reservas de grupo"
        ordering = ["-checkin"]

    def __str__(self):
        return f"Grupo #{self.pk} — {self.rotulo}"

    @property
    def filhas_ativas(self):
        return self.filhas.filter(status__in=Reserva.STATUS_ATIVOS)

    @property
    def pagador(self):
        return self.titular

    def situacao(self) -> str:
        """Status derivado das filhas (não é gravado — evita divergir da verdade).

        Ordem de precedência do bloco inteiro: cancelado (nada ativo) → hospedado
        (algum quarto em casa) → check-out (todas as ativas saíram) → confirmado
        (todas confirmadas) → pré-reserva.
        """
        filhas = list(self.filhas.all())
        if not filhas:
            return "vazio"
        ativas = [f for f in filhas if f.status in Reserva.STATUS_ATIVOS]
        if not ativas and any(f.status == Reserva.Status.CHECKOUT for f in filhas):
            return Reserva.Status.CHECKOUT
        if not ativas:
            return Reserva.Status.CANCELADA
        if any(f.status == Reserva.Status.HOSPEDADA for f in ativas):
            return Reserva.Status.HOSPEDADA
        if all(f.status == Reserva.Status.CONFIRMADA for f in ativas):
            return Reserva.Status.CONFIRMADA
        return Reserva.Status.PRE_RESERVA

    def situacao_display(self) -> str:
        cod = self.situacao()
        if cod == "vazio":
            return "Sem quartos"
        return Reserva.Status(cod).label


class Acompanhante(models.Model):
    """Lista simples de acompanhantes (legado). Superada pela FichaFNRH, que é o
    registro legal por hóspede. Mantida para não perder dados históricos."""

    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE,
        related_name="acompanhantes", verbose_name="reserva",
    )
    nome = models.CharField("nome", max_length=150)
    documento = models.CharField("documento", max_length=30, blank=True)

    class Meta:
        verbose_name = "acompanhante"
        verbose_name_plural = "acompanhantes"

    def __str__(self):
        return self.nome


class FichaFNRH(models.Model):
    """Ficha Nacional de Registro de Hóspedes (Min. do Turismo/Embratur, Lei
    11.771/2008). Um registro por pessoa hospedada — snapshot da estadia, não
    espelho editável do cadastro. Alimenta o BOH (Boletim de Ocupação Hoteleira).
    Enquanto incompleta, bloqueia o check-in (uma ficha completa por hóspede:
    titular + acompanhantes)."""

    # Domínios alinhados 1:1 com os códigos oficiais da FNRH Digital (GET /dominios/…);
    # o valor É o id aceito pela API — sem de-para.
    class Sexo(models.TextChoices):
        HOMEM = "HOMEM", "Masculino"
        MULHER = "MULHER", "Feminino"
        OUTRO = "OUTRO", "Outro"
        NAOINFORMADO = "NAOINFORMADO", "Prefiro não informar"

    class Documento(models.TextChoices):
        CPF = "CPF", "CPF"
        PASSAPORTE = "PASSAPORTE", "Passaporte"

    class MotivoViagem(models.TextChoices):
        LAZER_FERIAS = "LAZER_FERIAS", "Turismo / lazer / férias"
        NEGOCIOS = "NEGOCIOS", "Negócios / trabalho"
        CONGRESSO_FEIRA = "CONGRESSO_FEIRA", "Congresso / feira / evento"
        PARENTES_AMIGOS = "PARENTES_AMIGOS", "Visita a parentes / amigos"
        SAUDE = "SAUDE", "Saúde"
        ESTUDOS_CURSOS = "ESTUDOS_CURSOS", "Estudos / cursos"
        RELIGIAO = "RELIGIAO", "Religião"
        COMPRAS = "COMPRAS", "Compras"

    class Transporte(models.TextChoices):
        AUTOMOVEL = "AUTOMOVEL", "Automóvel"
        ONIBUS = "ONIBUS", "Ônibus"
        AVIAO = "AVIAO", "Avião"
        MOTO = "MOTO", "Motocicleta"
        NAVIO_BARCO = "NAVIO_BARCO", "Navio / barco"
        TREM = "TREM", "Trem"
        BICICLETA = "BICICLETA", "Bicicleta"
        PE = "PE", "A pé"

    class Origem(models.TextChoices):
        RECEPCAO = "recepcao", "Recepção"
        PORTAL = "portal", "Portal do hóspede"

    # Campos mínimos para a ficha valer (usados na trava de check-in).
    class AcompanhamentoMenor(models.TextChoices):
        PAIS = "pais", "Com os pais (ou um deles)"
        RESPONSAVEL = "responsavel", "Com o responsável legal (tutor ou guardião)"
        AUTORIZADO = "autorizado", "Com adulto autorizado por escrito pelos pais"

    CAMPOS_OBRIGATORIOS = ("nome", "nascimento", "documento_numero", "cidade", "motivo_viagem")

    reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE,
        related_name="fichas_fnrh", verbose_name="reserva",
    )
    titular = models.BooleanField("hóspede responsável", default=False)
    pessoa = models.ForeignKey(
        "nucleo.Pessoa", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fichas_fnrh", verbose_name="pessoa (cadastro)",
    )

    # Identificação
    nome = models.CharField("nome completo", max_length=150)
    nascimento = models.DateField("data de nascimento", null=True, blank=True)
    sexo = models.CharField("sexo", max_length=12, choices=Sexo.choices, blank=True)
    nacionalidade = models.CharField(
        "nacionalidade", max_length=60, blank=True, default="Brasileira"
    )
    profissao = models.CharField("profissão", max_length=80, blank=True)

    # Documento
    documento_tipo = models.CharField(
        "tipo de documento", max_length=12,
        choices=Documento.choices, default=Documento.CPF,
    )
    documento_numero = models.CharField("nº do documento", max_length=30, blank=True)
    documento_emissor = models.CharField("órgão emissor / país", max_length=40, blank=True)
    cpf = models.CharField("CPF", max_length=14, blank=True)

    # Endereço residencial
    pais = models.CharField("país", max_length=40, blank=True, default="Brasil")
    cep = models.CharField("CEP", max_length=9, blank=True)
    endereco = models.CharField("endereço", max_length=200, blank=True)
    cidade = models.CharField("cidade", max_length=80, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    telefone = models.CharField("telefone", max_length=20, blank=True)
    email = models.EmailField("e-mail", blank=True)

    # Viagem — dimensões do BOH
    motivo_viagem = models.CharField(
        "motivo da viagem", max_length=20, choices=MotivoViagem.choices, blank=True,
    )
    meio_transporte = models.CharField(
        "meio de transporte", max_length=15, choices=Transporte.choices, blank=True,
    )
    procedencia = models.CharField(
        "procedência", max_length=120, blank=True,
        help_text="Cidade/UF/país de onde o hóspede veio nesta viagem.",
    )
    proximo_destino = models.CharField("próximo destino", max_length=120, blank=True)
    # ECA, art. 82: criança ou adolescente só se hospeda com os pais/responsável ou com
    # autorização escrita deles. Só vale para quem tem menos de 18 anos na entrada.
    acompanhamento_menor = models.CharField(
        "se menor de 18 anos, está", max_length=12, choices=AcompanhamentoMenor.choices,
        blank=True,
        help_text="Só para menores de idade (ECA, art. 82).",
    )
    autorizacao_conferida = models.BooleanField(
        "autorização escrita dos pais conferida pela recepção", default=False,
        help_text="Quando o menor vem com outro adulto: a recepção viu o documento.",
    )

    origem = models.CharField(
        "preenchida via", max_length=8, choices=Origem.choices, default=Origem.RECEPCAO,
    )
    # IDs devolvidos pela FNRH Digital ao empurrar a ficha (ver fnrh_gateway.py)
    fnrh_pessoa_id = models.UUIDField("ID da pessoa na FNRH", null=True, blank=True)
    fnrh_hospede_id = models.UUIDField("ID do hóspede na FNRH", null=True, blank=True)
    preenchida_em = models.DateTimeField("preenchida em", null=True, blank=True)
    preenchida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fichas_fnrh_preenchidas", verbose_name="preenchida por",
    )
    criado_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "ficha FNRH"
        verbose_name_plural = "fichas FNRH"
        ordering = ["-titular", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["reserva"], condition=Q(titular=True),
                name="fnrh_um_titular_por_reserva",
            ),
        ]

    def __str__(self):
        return f"FNRH — {self.nome} (reserva #{self.reserva_id})"

    @property
    def completa(self) -> bool:
        return all(getattr(self, campo) for campo in self.CAMPOS_OBRIGATORIOS)

    @property
    def menor(self) -> bool:
        """Menos de 18 anos no dia da entrada (sem data de nascimento: não se sabe)."""
        if not self.nascimento or not self.reserva_id:
            return False
        dia = self.reserva.checkin
        idade = dia.year - self.nascimento.year - (
            (dia.month, dia.day) < (self.nascimento.month, self.nascimento.day))
        return idade < 18

    @property
    def menor_regular(self) -> bool:
        """ECA, art. 82: menor com os pais/responsável, ou com adulto autorizado por
        escrito e a autorização conferida pela recepção."""
        if not self.menor:
            return True
        A = self.AcompanhamentoMenor
        if self.acompanhamento_menor in (A.PAIS, A.RESPONSAVEL):
            return True
        return self.acompanhamento_menor == A.AUTORIZADO and self.autorizacao_conferida


class ContaHospedagem(models.Model):
    """Folio: diárias, consumos, serviços e descontos; crédito de adiantamentos."""

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        FECHADA = "fechada", "Fechada"

    reserva = models.OneToOneField(
        Reserva, on_delete=models.PROTECT, related_name="conta", verbose_name="reserva",
        null=True, blank=True,
    )
    grupo = models.OneToOneField(
        "GrupoReserva", on_delete=models.PROTECT, related_name="folio",
        verbose_name="grupo (folio-mãe)", null=True, blank=True,
        help_text="Folio do grupo: as diárias de todos os quartos do bloco.",
    )
    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ABERTA
    )
    aberta_em = models.DateTimeField("aberta em", auto_now_add=True)
    fechada_em = models.DateTimeField("fechada em", null=True, blank=True)

    class Meta:
        verbose_name = "conta de hospedagem"
        verbose_name_plural = "contas de hospedagem"
        constraints = [
            # Uma conta é OU de um quarto OU o folio de um grupo, nunca os dois.
            models.CheckConstraint(
                condition=(
                    Q(reserva__isnull=False, grupo__isnull=True)
                    | Q(reserva__isnull=True, grupo__isnull=False)
                ),
                name="conta_reserva_xor_grupo",
            ),
        ]

    def __str__(self):
        if self.grupo_id:
            return f"Folio do grupo #{self.grupo_id} ({self.get_status_display()})"
        return f"Conta da reserva #{self.reserva_id} ({self.get_status_display()})"

    @property
    def aberta(self) -> bool:
        return self.status == self.Status.ABERTA

    def lancar_diarias(self, usuario, reserva=None) -> Decimal:
        """Lança uma diária (SERVIÇO) por noite, pela diária acordada da reserva.
        Retorna o total de hospedagem lançado (base do ISS). `reserva` permite lançar
        a diária de um quarto do grupo neste folio-mãe; omitido, usa a desta conta.
        """
        reserva = reserva or self.reserva
        total = Decimal("0.00")
        for n, valor in enumerate(reserva.valores_das_diarias()):
            dia = reserva.checkin + timezone.timedelta(days=n)
            LancamentoConta.objects.create(
                conta=self,
                tipo=LancamentoConta.Tipo.DIARIA,
                natureza=NaturezaFiscal.SERVICO,
                descricao=f"Diária {dia:%d/%m/%Y} — {reserva.uh.numero}",
                valor=valor,
                competencia=dia,
                criado_por=usuario,
            )
            total += valor
        return total

    def lancar_taxas(self, usuario, reserva=None, base=None):
        """Lança ISS + taxa de turismo da hospedagem (SERVIÇO), itemizados à parte
        (Fase 6 — Manual §2). ISS = alíquota × hospedagem (por fora); taxa de turismo =
        valor fixo × nº de diárias. Cada uma respeita a flag da reserva; desligado em
        teste por `PRECO_TAXAS_ATIVAS`. `base` = total de hospedagem já lançado.
        """
        from django.conf import settings

        from apps.reservas.precos import taxas

        if not getattr(settings, "PRECO_TAXAS_ATIVAS", True):
            return
        reserva = reserva or self.reserva
        if base is None:
            base = reserva.hospedagem_prevista()
        noites = reserva.noites
        t = taxas(base, cobra_iss=reserva.cobra_iss,
                  cobra_taxa_turismo=reserva.cobra_taxa_turismo, diarias=noites)

        if t["iss"] > 0:
            LancamentoConta.objects.create(
                conta=self, tipo=LancamentoConta.Tipo.TAXA,
                natureza=NaturezaFiscal.SERVICO,
                descricao=f"ISS {t['iss_aliquota'].normalize()}% — {reserva.uh.numero}",
                valor=t["iss"], criado_por=usuario,
            )
        if t["taxa_turismo"] > 0:
            rotulo = "diária" if noites == 1 else "diárias"
            LancamentoConta.objects.create(
                conta=self, tipo=LancamentoConta.Tipo.TAXA,
                natureza=NaturezaFiscal.SERVICO,
                descricao=f"Taxa de turismo · {noites} {rotulo} — {reserva.uh.numero}",
                valor=t["taxa_turismo"], criado_por=usuario,
            )

    # ---- Totais ----

    def _total(self, **filtros) -> Decimal:
        return self.lancamentos.filter(**filtros).aggregate(t=Sum("valor"))[
            "t"
        ] or Decimal("0.00")

    def total_lancamentos(self) -> Decimal:
        """Débitos menos descontos."""
        debitos = self._total(tipo__in=LancamentoConta.TIPOS_DEBITO)
        descontos = self._total(tipo=LancamentoConta.Tipo.DESCONTO)
        return debitos - descontos

    def total_por_natureza(self) -> dict:
        """Subtotais SERVIÇO × CONSUMO (descontos abatem da própria natureza)."""
        resultado = {}
        for natureza in NaturezaFiscal:
            debitos = self._total(
                tipo__in=LancamentoConta.TIPOS_DEBITO, natureza=natureza
            )
            descontos = self._total(
                tipo=LancamentoConta.Tipo.DESCONTO, natureza=natureza
            )
            resultado[natureza.label] = debitos - descontos
        return resultado

    def total_pago(self) -> Decimal:
        return self.pagamentos.aggregate(t=Sum("valor"))["t"] or Decimal("0.00")

    def total_adiantamentos(self) -> Decimal:
        if not self.reserva_id:
            return Decimal("0.00")  # folio-mãe do grupo não tem adiantamento próprio
        return self.reserva.adiantamentos.aggregate(t=Sum("valor"))["t"] or Decimal(
            "0.00"
        )

    def saldo(self) -> Decimal:
        """O que falta receber: lançamentos − pagamentos − adiantamentos."""
        return self.total_lancamentos() - self.total_pago() - self.total_adiantamentos()

    @classmethod
    def saldos(cls, contas) -> dict:
        """{conta.pk: saldo} de várias contas com 4 consultas no total, e não 4 por conta.
        Mesma regra de `saldo()` (há teste comparando as duas). Para telas que mostram o
        saldo de cada quarto (mapa, pendências da Auditoria)."""
        contas = list(contas)
        if not contas:
            return {}
        ids = [c.pk for c in contas]
        reservas_ids = [c.reserva_id for c in contas if c.reserva_id]

        def somas(qs, campo):
            return {
                linha[campo]: linha["t"] or Decimal("0.00")
                for linha in qs.order_by().values(campo).annotate(t=Sum("valor"))
            }

        debitos = somas(LancamentoConta.objects.filter(
            conta_id__in=ids, tipo__in=LancamentoConta.TIPOS_DEBITO), "conta_id")
        descontos = somas(LancamentoConta.objects.filter(
            conta_id__in=ids, tipo=LancamentoConta.Tipo.DESCONTO), "conta_id")
        pagos = somas(PagamentoConta.objects.filter(conta_id__in=ids), "conta_id")
        adiantados = somas(Adiantamento.objects.filter(reserva_id__in=reservas_ids), "reserva_id")
        zero = Decimal("0.00")
        return {
            c.pk: debitos.get(c.pk, zero) - descontos.get(c.pk, zero) - pagos.get(c.pk, zero)
            - (adiantados.get(c.reserva_id, zero) if c.reserva_id else zero)
            for c in contas
        }


class LancamentoConta(models.Model):
    """
    Lançamento do folio. Natureza fiscal obrigatória (4ª veia): SERVIÇO ou
    CONSUMO, para extrato separado e futura emissão de nota (módulo Fiscal).
    """

    class Tipo(models.TextChoices):
        DIARIA = "diaria", "Diária"
        CONSUMO = "consumo", "Consumo"
        SERVICO = "servico", "Serviço"
        # ISS e taxa de turismo: o hóspede paga, mas não é receita de serviço da
        # pousada — fica fora da base da NFS-e (senão o ISS incidiria sobre ele mesmo).
        TAXA = "taxa", "Imposto/taxa"
        DESCONTO = "desconto", "Desconto"

    TIPOS_DEBITO = [Tipo.DIARIA, Tipo.CONSUMO, Tipo.SERVICO, Tipo.TAXA]

    conta = models.ForeignKey(
        ContaHospedagem, on_delete=models.PROTECT,
        related_name="lancamentos", verbose_name="conta",
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    natureza = models.CharField(
        "natureza fiscal", max_length=10, choices=NaturezaFiscal.choices
    )
    descricao = models.CharField("descrição", max_length=200)
    valor = models.DecimalField(
        "valor (R$)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="lancamentos_conta", verbose_name="lançado por",
    )
    criado_em = models.DateTimeField("lançado em", auto_now_add=True)
    # O dia a que o lançamento se refere: na diária, a NOITE (todas são lançadas no
    # check-in, uma linha por noite); no resto, o dia do lançamento. A receita dos
    # relatórios conta por aqui — por `criado_em`, uma estadia de 28/10 a 03/11 caía
    # inteira em outubro e o ADR do mês misturava receita de um mês com ocupação de outro.
    competencia = models.DateField("competência", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "lançamento da conta"
        verbose_name_plural = "lançamentos da conta"
        ordering = ["criado_em"]
        # Relatórios de receita filtram pela competência (o dia do serviço).
        indexes = [
            models.Index(fields=["criado_em"], name="lancamento_criado_em_idx"),
            models.Index(fields=["competencia"], name="lancamento_competencia_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(valor__gt=0), name="lancamento_conta_valor_positivo"
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.descricao} (R$ {self.valor})"

    def clean(self):
        if self.conta_id and not self.conta.aberta:
            raise ValidationError("A conta deste quarto já foi fechada.")
        if not self.natureza:
            raise ValidationError({"natureza": "Informe a natureza fiscal."})

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Lançamento de conta não é editado — lance um desconto/ajuste."
            )
        if self.competencia is None:
            self.competencia = timezone.localdate()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Lançamento de conta não é apagado — lance um desconto/ajuste."
        )


class CreditoNaReserva(models.Model):
    """Base de PagamentoConta e Adiantamento: dinheiro que abate a conta do hóspede.

    Origens:
    - **caixa** — `movimento_caixa` (a veia do dinheiro na gaveta do operador);
    - **online** — `cobranca_id`, a cobrança de Pagamentos paga pelo gateway (Pix,
      cartão, boleto). Não passa pela gaveta; único por cobrança (idempotência);
    - **estorno** — `estorno_de` aponta o crédito desfeito e o valor é NEGATIVO (a
      conta volta a cobrar o que foi devolvido). Vem do estorno do movimento de caixa
      ou do estorno da cobrança no gateway.
    - **faturado** (só PagamentoConta) — `conta_receber`: o saldo de uma reserva de
      agência/empresa virou título a receber no Financeiro; quem paga é o titular.
    """

    cobranca_id = models.PositiveIntegerField(
        "cobrança online", null=True, blank=True, unique=True,
        help_text="Cobrança de Pagamentos que gerou este crédito (pago pelo gateway).",
    )
    valor = models.DecimalField("valor (R$)", max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def eh_estorno(self) -> bool:
        return self.valor < 0

    @property
    def valor_absoluto(self) -> Decimal:
        return abs(self.valor)

    @property
    def origem(self) -> str:
        if self.eh_estorno:
            return "estorno"
        if getattr(self, "conta_receber_id", None):
            return "faturado"
        return "online" if self.cobranca_id else "caixa"


class PagamentoConta(CreditoNaReserva):
    """
    Pagamento da conta: pela gaveta (movimento de caixa do operador), online (cobrança
    paga no gateway) ou o estorno de um dos dois (valor negativo). Ver CreditoNaReserva.
    """

    conta = models.ForeignKey(
        ContaHospedagem, on_delete=models.PROTECT,
        related_name="pagamentos", verbose_name="conta",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="pagamento_conta", verbose_name="movimento de caixa",
    )
    estorno_de = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="estornos", verbose_name="estorno do pagamento",
    )
    conta_receber = models.OneToOneField(
        "nucleo.ContaPagarReceber", on_delete=models.PROTECT, null=True, blank=True,
        related_name="pagamento_conta", verbose_name="faturado (conta a receber)",
    )
    observacao = models.CharField(
        "pagador / observação", max_length=120, blank=True,
        help_text="Quem pagou esta parte (ex.: 'Casal A', 'cartão do João') — para rateio.",
    )

    class Meta:
        verbose_name = "pagamento da conta"
        verbose_name_plural = "pagamentos da conta"
        ordering = ["criado_em"]
        constraints = [
            # Crédito positivo; estorno negativo e sempre apontando o crédito desfeito.
            models.CheckConstraint(
                condition=(Q(valor__gt=0, estorno_de__isnull=True)
                           | Q(valor__lt=0, estorno_de__isnull=False)),
                name="pagamento_conta_sinal_coerente",
            ),
        ]

    def __str__(self):
        return f"Pagamento R$ {self.valor} — conta #{self.conta_id}"


class Adiantamento(CreditoNaReserva):
    """Valor recebido antes do check-in, vinculado à reserva; crédito na conta. Pela
    gaveta, online (sinal pago no site) ou o estorno de um dos dois (valor negativo)."""

    reserva = models.ForeignKey(
        Reserva, on_delete=models.PROTECT,
        related_name="adiantamentos", verbose_name="reserva",
    )
    movimento_caixa = models.OneToOneField(
        "nucleo.MovimentoCaixa", on_delete=models.PROTECT, null=True, blank=True,
        related_name="adiantamento", verbose_name="movimento de caixa",
    )
    estorno_de = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="estornos", verbose_name="estorno do adiantamento",
    )
    observacao = models.CharField("observação", max_length=120, blank=True)

    class Meta:
        verbose_name = "adiantamento"
        verbose_name_plural = "adiantamentos"
        ordering = ["criado_em"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(valor__gt=0, estorno_de__isnull=True)
                           | Q(valor__lt=0, estorno_de__isnull=False)),
                name="adiantamento_sinal_coerente",
            ),
        ]

    def __str__(self):
        return f"Adiantamento R$ {self.valor} — reserva #{self.reserva_id}"


class ColchoesExtra(models.Model):
    """Pool GLOBAL de colchões de solteiro EXTRAS — recurso compartilhado e limitado.

    **Só os extras são compartilhados.** As **camas fixas** de cada quarto (2×casais_max =
    a base) são sempre dele e NUNCA entram nesta disputa — 35 posições de casal = 70
    colchões fixos (a montagem muda, a quantidade não). Só o que um quarto monta ALÉM da
    base consome este pool. Por noite, a soma do consumo de extra das reservas ativas não
    pode passar da `quantidade` (10). Sofá-cama não consome colchão. Singleton (uma linha).
    Ver docs/Reservas/PLANO_ESTOQUE_COLCHOES.md.
    """

    quantidade = models.PositiveSmallIntegerField("colchões extra em estoque", default=10)
    alerta_minimo = models.PositiveSmallIntegerField(
        "avisar quando restar ≤", default=1,
        help_text="Quando os colchões extra livres numa noite ficam neste número ou "
                  "abaixo, o sistema avisa (não bloqueia a reserva).",
    )
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "estoque de colchões extra"
        verbose_name_plural = "estoque de colchões extra"

    def __str__(self):
        return f"{self.quantidade} colchões extra (avisa ≤ {self.alerta_minimo})"

    @classmethod
    def atual(cls) -> ColchoesExtra:
        """Linha única do estoque (cria com os defaults se ainda não existir)."""
        obj = cls.objects.order_by("pk").first()
        if obj is None:
            # pk fixo: duas primeiras chamadas ao mesmo tempo viram uma linha só (a
            # segunda esbarra na chave e o get_or_create devolve a da primeira).
            obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BercoEstoque(models.Model):
    """Estoque GLOBAL de berços — recurso compartilhado e limitado (a pousada tem 1).

    Berço é **grátis**, não conta como pessoa nem como cama/colchão. Por noite, a soma
    dos berços das reservas ativas não pode passar da `quantidade`. Singleton (uma linha),
    editável no admin.
    """

    quantidade = models.PositiveSmallIntegerField("berços em estoque", default=1)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "estoque de berços"
        verbose_name_plural = "estoque de berços"

    def __str__(self):
        return f"{self.quantidade} berço(s)"

    @classmethod
    def atual(cls) -> BercoEstoque:
        """Linha única do estoque (cria com o default se ainda não existir)."""
        obj = cls.objects.order_by("pk").first()
        if obj is None:
            # pk fixo: duas primeiras chamadas ao mesmo tempo viram uma linha só (a
            # segunda esbarra na chave e o get_or_create devolve a da primeira).
            obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class FechamentoDiario(models.Model):
    """Fechamento do dia (auditoria noturna): o retrato do dia que passou — ocupação,
    receita pela competência, chegadas, saídas, no-shows e o saldo que ficou em aberto.

    A rotina da madrugada grava o de ontem (`services.fechar_dia`) e ele nunca muda: é o
    número que a gerência e o contador conferem no dia seguinte. Um lançamento feito
    depois com data daquele dia aparece no relatório do período, não aqui — e a
    diferença entre os dois fica à vista.
    """

    data = models.DateField("dia", unique=True)
    quartos_disponiveis = models.PositiveIntegerField("quartos disponíveis")
    quartos_ocupados = models.PositiveIntegerField("quartos ocupados")
    chegadas = models.PositiveIntegerField("chegadas")
    saidas = models.PositiveIntegerField("saídas")
    no_shows = models.PositiveIntegerField(
        "no-shows", help_text="Entrada no dia sem check-in (no-show marcado ou provável).")
    receita_diarias = models.DecimalField("diárias (R$)", max_digits=12, decimal_places=2)
    receita_servico = models.DecimalField(
        "serviço (R$)", max_digits=12, decimal_places=2,
        help_text="Diárias, serviços e taxas do dia, menos os descontos.")
    receita_consumo = models.DecimalField("consumo (R$)", max_digits=12, decimal_places=2)
    saldo_em_aberto = models.DecimalField(
        "saldo em aberto (R$)", max_digits=12, decimal_places=2,
        help_text="O que as contas abertas deviam na hora do fechamento.")
    criado_em = models.DateTimeField("fechado em", auto_now_add=True)

    class Meta:
        verbose_name = "fechamento do dia"
        verbose_name_plural = "fechamentos do dia"
        ordering = ["-data"]

    def __str__(self):
        return f"Fechamento de {self.data:%d/%m/%Y}"

    @property
    def taxa_ocupacao(self) -> Decimal:
        if not self.quartos_disponiveis:
            return Decimal("0.0")
        return (Decimal(self.quartos_ocupados) * 100 / self.quartos_disponiveis).quantize(
            Decimal("0.1"))

    @property
    def adr(self) -> Decimal:
        if not self.quartos_ocupados:
            return Decimal("0.00")
        return (self.receita_diarias / self.quartos_ocupados).quantize(Decimal("0.01"))

    @property
    def revpar(self) -> Decimal:
        if not self.quartos_disponiveis:
            return Decimal("0.00")
        return (self.receita_diarias / self.quartos_disponiveis).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("O fechamento do dia não é editado.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O fechamento do dia não é apagado.")
