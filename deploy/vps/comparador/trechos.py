"""Trechos de código do Comparativo: o mesmo ponto no `main` do original e na `dev` do fork.

Cada bloco tem:
- `arquivo`: o caminho na versão atualizada (`arquivo_antes`, quando mudou de lugar);
- `commit`: o commit do fork em que a mudança entrou; sem ele, o link vai para o arquivo
  na `dev` e o trecho é o de hoje;
- `antes`: o trecho no `main` do original, vazio quando o código é novo;
- `agora`: o trecho na versão atualizada.

A linha "…" marca um trecho omitido e é igual dos dois lados. O código é colado sem
retoque: `conferir_trechos.py` confere cada linha no git das duas versões. `demo` marca
um exemplo de terminal, que não vem do repositório.
"""

PAGAMENTO_ONLINE = [
    {"arquivo": "apps/pagamentos/services.py", "commit": "862a220",
     "antes": r'''
def confirmar_pagamento(cobranca, usuario=None, origem="webhook"):
    …
    cobranca.pago_em = timezone.now()
    cobranca.save(update_fields=["status", "pago_em"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="paga", origem=origem)

    # Sinal pago → confirma a reserva (ou o grupo inteiro), se Reservas ativo.
    …
    return cobranca
''',
     "agora": r'''
def confirmar_pagamento(cobranca, usuario=None, origem="webhook"):
    …
    cobranca.pago_em = timezone.now()
    cobranca.save(update_fields=["status", "pago_em"])
    EventoPagamento.objects.create(cobranca=cobranca, tipo="paga", origem=origem)
    _creditar_na_reserva(cobranca)

    # Sinal pago → confirma a reserva (ou o grupo inteiro), se Reservas ativo.
    …
    return cobranca


def _creditar_na_reserva(cobranca):
    """O dinheiro entrou pelo gateway, não pela gaveta: vira crédito na reserva (ou no
    folio do grupo), senão a conta cobra de novo no check-out. Idempotente."""
    if (cobranca.reserva_id or cobranca.grupo_id) and modulo_ativo(Modulo.RESERVAS):
        from apps.reservas.services import registrar_pagamento_online
        registrar_pagamento_online(
            cobranca_id=cobranca.pk, valor=cobranca.valor,
            descricao=f"{cobranca.get_metodo_display()} online — cobrança #{cobranca.pk}",
            reserva_id=cobranca.reserva_id, grupo_id=cobranca.grupo_id,
        )
'''},
    {"arquivo": "apps/reservas/models.py", "commit": "862a220",
     "antes": "",
     "agora": r'''
    cobranca_id = models.PositiveIntegerField(
        "cobrança online", null=True, blank=True, unique=True,
        help_text="Cobrança de Pagamentos que gerou este crédito (pago pelo gateway).",
    )
'''},
]

ESTORNO = [
    {"arquivo": "apps/nucleo/models/financeiro.py", "commit": "862a220",
     "antes": r'''
@transaction.atomic
def estornar_movimento(origem: MovimentoCaixa, sessao: SessaoCaixa, usuario, motivo: str,
                       valor: Decimal | None = None) -> MovimentoCaixa:
    …
    estorno.save()
    registrar_auditoria(
''',
     "agora": r'''
_AO_ESTORNAR = []


def ao_estornar(funcao):
    """Registra `funcao(origem=, estorno=, usuario=)` para rodar em todo estorno."""
    if funcao not in _AO_ESTORNAR:
        _AO_ESTORNAR.append(funcao)
    return funcao


@transaction.atomic
def estornar_movimento(origem: MovimentoCaixa, sessao: SessaoCaixa, usuario, motivo: str,
                       valor: Decimal | None = None) -> MovimentoCaixa:
    …
    estorno.save()
    for funcao in list(_AO_ESTORNAR):
        funcao(origem=origem, estorno=estorno, usuario=usuario)
    registrar_auditoria(
'''},
    {"arquivo": "apps/reservas/apps.py", "commit": "862a220",
     "antes": r'''
class ReservasConfig(AppConfig):
    …
    verbose_name = "Reservas"
''',
     "agora": r'''
class ReservasConfig(AppConfig):
    …
    verbose_name = "Reservas"

    def ready(self):
        # Estorno no caixa de um pagamento/adiantamento desfaz o crédito na conta junto.
        from apps.nucleo.models.financeiro import ao_estornar

        from .services import desfazer_credito_do_estorno

        ao_estornar(desfazer_credito_do_estorno)
'''},
]

REAIS = [
    {"arquivo": "templates/base.html",
     "antes": r'''
  // Antes de enviar, converte "1.784,00" → "1784.00" para o backend (DecimalField).
  document.addEventListener('submit', e => {
    e.target.querySelectorAll('.mascara-reais').forEach(el => {
      if (el.value) el.value = el.value.replace(/\./g, '').replace(',', '.');
    });
  }, true);
''',
     "agora": r'''
  // Converte só a carga enviada. Campos visíveis nunca mudam em uma tentativa.
  document.addEventListener('formdata', e => {
    e.target.querySelectorAll('.mascara-reais[name]').forEach(el => {
      if (!el.disabled && el.value) e.formData.set(el.name, el.value.replace(/\./g, '').replace(',', '.'));
    });
  }, true);
  // HTMX serializa os valores sem alterar o que continua visível no formulário.
  // Assim um erro de rede não transforma R$ 50,00 em R$ 5.000,00 no reenvio.
  document.addEventListener('htmx:configRequest', e => {
    const form = e.detail.elt.closest('form');
    if (!form) return;
    form.querySelectorAll('.mascara-reais[name]').forEach(el => {
      if (!el.disabled && el.value) e.detail.parameters[el.name] = el.value.replace(/\./g, '').replace(',', '.');
    });
  });
'''},
    {"arquivo": "apps/nucleo/forms.py", "arquivo_antes": "apps/comercial/forms.py",
     "commit": "ad02cb9",
     "antes": r'''
class ReaisInput(forms.TextInput):
    """Campo de moeda BR: máscara 'mascara-reais' (formata ao digitar, converte no submit)."""

    def __init__(self, attrs=None):
        base = {"class": "mascara-reais", "inputmode": "numeric", "placeholder": "0,00"}
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)
''',
     "agora": r'''
class ReaisInput(forms.TextInput):
    """Campo de R$ com a máscara `mascara-reais` (base.html): formata ao digitar e, no
    submit, tira os pontos de milhar e troca a vírgula ("1.784,00" → "1784.00").

    Por isso o valor que vem do servidor (inicial ou o form que voltou com erro) também
    sai no formato da máscara: um "650.00" cru perdia o ponto no submit e chegava ao
    backend como 65000 — cem vezes o valor."""

    def __init__(self, attrs=None):
        base = {"class": "mascara-reais", "inputmode": "numeric", "placeholder": "0,00"}
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)

    def format_value(self, value):
        if value is None or value == "":
            return None
        try:
            return _brl(value)
        except (InvalidOperation, ValueError):
            return super().format_value(value)  # o que a pessoa digitou, como veio
'''},
]

ROTINAS = [
    {"arquivo": "deploy/railway.rotinas.json", "commit": "38b56c3",
     "antes": "",
     "agora": r'''
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "RAILPACK"
  },
  "deploy": {
    "startCommand": "python manage.py rotinas --grupo frequentes",
    "cronSchedule": "*/10 * * * *",
    "restartPolicyType": "NEVER"
  }
}
'''},
    {"arquivo": "apps/nucleo/management/commands/rotinas.py",
     "antes": "",
     "agora": r'''
GRUPOS = {
    "canais": ["sincronizar_canais"],  # a cada minuto; independente das rotinas de dez minutos
    "frequentes": [
        "expirar_reservas",
        "expirar_recibos_site",
        "enviar_fnrh_pendentes",
        "consultar_fiscal_pendente",
        …
    ],
    "diarias": [
        "marcar_no_shows",  # no-show automático (se ligado) antes de fechar o dia
        "fechar_dia",  # o backup do dia já leva o fechamento
        …
        "backup_banco",
        "purgar_trilha",
        …
    ],
}
'''},
]

ISS = [
    {"arquivo": "apps/reservas/services.py", "commit": "4991a84",
     "antes": r'''
def resumo_fiscal_conta(conta_id):
    …
    por_nat = conta.total_por_natureza()  # {"Serviço": x, "Consumo": y}
    return {
        "conta_id": conta.pk,
        …
        "servico": por_nat.get(NaturezaFiscal.SERVICO.label, Decimal("0.00")),
        "consumo": por_nat.get(NaturezaFiscal.CONSUMO.label, Decimal("0.00")),
    }
''',
     "agora": r'''
def resumo_fiscal_conta(conta_id):
    …
    por_nat = conta.total_por_natureza()  # {"Serviço": x, "Consumo": y}
    # ISS e taxa de turismo entram na conta do hóspede, mas não são serviço prestado
    # pela pousada: saem da base da NFS-e (o ISS não incide sobre ele mesmo).
    taxas = conta._total(tipo=LancamentoConta.Tipo.TAXA)
    return {
        "conta_id": conta.pk,
        …
        "servico": por_nat.get(NaturezaFiscal.SERVICO.label, Decimal("0.00")) - taxas,
        "consumo": por_nat.get(NaturezaFiscal.CONSUMO.label, Decimal("0.00")),
        "taxas": taxas,
    }
'''},
    {"arquivo": "apps/reservas/models.py", "commit": "4991a84",
     "antes": r'''
        if t["iss"] > 0:
            LancamentoConta.objects.create(
                conta=self, tipo=LancamentoConta.Tipo.SERVICO,
                natureza=NaturezaFiscal.SERVICO,
''',
     "agora": r'''
        if t["iss"] > 0:
            LancamentoConta.objects.create(
                conta=self, tipo=LancamentoConta.Tipo.TAXA,
                natureza=NaturezaFiscal.SERVICO,
'''},
]

LOJA = [
    {"arquivo": "apps/loja/services.py", "commit": "a6d63a4",
     "antes": r'''
@transaction.atomic
def finalizar_venda(operador, local, itens, destino, forma=None, cliente=None,
                    conta_id=None, desconto=ZERO):
    """
    itens: lista de dicts {produto_id, quantidade}. Valida saldo, baixa estoque
    e cobra pelo destino escolhido (caixa OU conta do quarto).
    """
''',
     "agora": r'''
def finalizar_venda(operador, local, itens, destino, forma=None, cliente=None,
                    conta_id=None, desconto=ZERO, chave=None):
    """
    itens: lista de dicts {produto_id, quantidade}. Valida saldo, baixa estoque
    e cobra pelo destino escolhido (caixa OU conta do quarto).

    `chave` (UUID que o PDV gera para cada carrinho) torna a venda idempotente: o
    clique duplo, ou o reenvio depois de a conexão cair, devolve a venda já feita em
    vez de baixar o estoque e cobrar de novo.
    """
    if chave:
        existente = Venda.objects.filter(chave=chave).first()
        if existente:
            return existente
    try:
        return _finalizar_venda(operador, local, itens, destino, forma, cliente,
                                conta_id, desconto, chave)
    except IntegrityError:
        # Dois envios da mesma chave ao mesmo tempo: o segundo esbarra na unicidade
        # quando o primeiro grava; devolve a venda do primeiro.
        existente = Venda.objects.filter(chave=chave).first() if chave else None
        if existente:
            return existente
        raise
'''},
    {"arquivo": "apps/loja/models.py", "commit": "a6d63a4",
     "antes": "",
     "agora": r'''
    chave = models.UUIDField(
        "chave do carrinho", null=True, blank=True, unique=True, editable=False,
        help_text="Gerada pelo PDV para cada carrinho: o mesmo envio duas vezes não "
                  "vira duas vendas.",
    )
'''},
]

INVENTARIO = [
    {"arquivo": "apps/nucleo/models/estoque.py",
     "antes": r'''
    def aplicar(self, usuario):
        """Gera um ajuste para cada item com diferença e fecha o inventário."""
        if self.status != self.Status.ABERTO:
            raise ValidationError("Este inventário já foi aplicado ou cancelado.")
        for item in self.itens.select_related("produto"):
            ajustar(
                item.produto, self.local, item.quantidade_contada, usuario,
                motivo=f"Inventário #{self.pk}",
''',
     "agora": r'''
    def aplicar(self, usuario, somente_contados=False):
        """Gera um ajuste para cada item com diferença e fecha o inventário.

        `somente_contados=True` (o que a tela de contagem usa) ignora o item que
        ninguém contou. Importa: o item nasce com `quantidade_contada` = saldo da
        ABERTURA; se houver uma venda durante a contagem, aplicar esse número de
        volta apagaria a baixa. Quem não foi contado fica como está.
        """
        from apps.nucleo.sistema import travar

        travar(self)
        if self.status != self.Status.ABERTO:
            raise ValidationError("Este inventário já foi aplicado ou cancelado.")
        itens = self.itens.select_related("produto")
        if somente_contados:
            itens = itens.filter(contado=True)
        …
        for item in itens:
            # Corrige a diferença observada; movimentos posteriores à contagem
            # permanecem no kardex e não são sobrescritos pelo saldo físico antigo.
            destino = saldo(item.produto, self.local) + item.diferenca
            …
            ajustar(
                item.produto, self.local, destino, usuario,
                motivo=f"Inventário #{self.pk}",
'''},
]

CONSENTIMENTO = [
    {"arquivo": "templates/comercial/captacao_publica.html",
     "antes": r'''
{% if pagina.meta_pixel_id %}
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
…
fbq('init','{{ pagina.meta_pixel_id }}');fbq('track','PageView');
…
{% if pagina.google_tag_id %}
<script async src="https://www.googletagmanager.com/gtag/js?id={{ pagina.google_tag_id }}"></script>
<script>
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
''',
     "agora": r'''
{% if pagina.meta_pixel_id %}
<script type="text/plain" data-consentimento>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
…
fbq('init','{{ pagina.meta_pixel_id }}');fbq('track','PageView');
…
{% if pagina.google_tag_id %}
<script type="text/plain" data-consentimento async
        data-src="https://www.googletagmanager.com/gtag/js?id={{ pagina.google_tag_id }}"></script>
<script type="text/plain" data-consentimento>
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
'''},
    {"arquivo": "static/js/consentimento.js",
     "antes": "",
     "agora": r'''
  // Liga as tags marcadas, preservando a ordem em que estão no documento.
  function ligarTags() {
    var tags = document.querySelectorAll('script[type="text/plain"][data-consentimento]');
    for (var i = 0; i < tags.length; i++) {
      var velha = tags[i];
      var nova = document.createElement('script');
      for (var j = 0; j < velha.attributes.length; j++) {
        var at = velha.attributes[j];
        if (at.name === 'type' || at.name === 'data-consentimento' || at.name === 'data-src') continue;
        nova.setAttribute(at.name, at.value);
      }
      if (velha.dataset.src) nova.src = velha.dataset.src;
      else nova.textContent = velha.textContent;
      velha.parentNode.insertBefore(nova, velha);
      velha.parentNode.removeChild(velha);
    }
    document.dispatchEvent(new CustomEvent('consentimento:aceito'));
  }
'''},
]

PERCENTUAL = [
    {"arquivo": "Python 3.14 — módulo decimal", "demo": True,
     "antes": "",
     "agora": r'''
>>> from decimal import Decimal
>>> f"retemos {(Decimal('0.10') * 100).normalize()}%"
'retemos 1E+1%'
>>> format((Decimal('0.10') * 100).normalize(), "f")
'10'
'''},
    {"arquivo": "apps/reservas/cancelamento.py", "commit": "68d7e99",
     "antes": r'''
            f"após a confirmação da reserva. Depois desse prazo, retemos "
            f"{(_retencao_pct() * 100).normalize()}% do valor total (devolvemos o restante). "
''',
     "agora": r'''
            f"após a confirmação da reserva. Depois desse prazo, retemos "
            f"{pct_br(_retencao_pct() * 100)}% do valor total (devolvemos o restante). "
'''},
    {"arquivo": "apps/nucleo/formatos.py", "commit": "68d7e99",
     "antes": "",
     "agora": r'''
def pct_br(valor) -> str:
    """Percentual sem zeros à direita e com vírgula: 10 → "10", 12.5 → "12,5", 4.00 → "4".

    `Decimal.normalize()` sozinho escreve 10 como "1E+1" — era o que o site mostrava na
    política de cancelamento ("retemos 1E+1% do valor total") e o que ficava gravado no
    motivo do cancelamento ("reter 1E+1%")."""
    return format(Decimal(valor).normalize(), "f").replace(".", ",")
'''},
]

CAIXA = [
    {"arquivo": "apps/nucleo/models/financeiro.py", "commit": "421fba7",
     "antes": r'''
    def fechar(self, valor_contado: Decimal, usuario, observacoes: str = ""):
        """Fechamento com conferência cega: operador informa o contado,
        o sistema aponta a diferença. Sessão fechada não recebe movimento."""
        if not self.aberta:
            raise ValidationError("Esta sessão de caixa já está fechada.")
…
def receber_no_caixa(usuario, forma, valor: Decimal, descricao: str, parcelas: int = 1,
                     modulo: str = CENTRO_NUCLEO, autorizacao: str = ""):
    …
    sessao = SessaoCaixa.objects.filter(
        operador=usuario, modulo=modulo, status=SessaoCaixa.Status.ABERTA
    ).first()
''',
     "agora": r'''
    @transaction.atomic
    def fechar(self, valor_contado: Decimal, usuario, observacoes: str = ""):
        """Fechamento com conferência cega: operador informa o contado,
        o sistema aponta a diferença. Sessão fechada não recebe movimento.

        Trava a sessão antes de calcular o esperado: um recebimento feito ao mesmo tempo
        (outra aba do mesmo operador) ou entra antes e conta na conferência, ou chega
        depois e é recusado por sessão fechada — nunca cai numa sessão já conferida."""
        from apps.nucleo.sistema import travar

        travar(self)
        if not self.aberta:
            raise ValidationError("Esta sessão de caixa já está fechada.")
…
@transaction.atomic
def receber_no_caixa(usuario, forma, valor: Decimal, descricao: str, parcelas: int = 1,
                     modulo: str = CENTRO_NUCLEO, autorizacao: str = ""):
    …
    sessao = SessaoCaixa.objects.select_for_update().filter(
        operador=usuario, modulo=modulo, status=SessaoCaixa.Status.ABERTA
    ).first()
'''},
]

CHECKOUT = [
    {"arquivo": "apps/reservas/models.py",
     "antes": r'''
    def fazer_checkout(self, usuario):
        self._exige_status(self.Status.HOSPEDADA)
        conta = self.conta
        …
        self.checkout_real = timezone.now()
        self.save()
        # Governança (se ativa) escuta este sinal para gerar a faxina.
        from .signals import quarto_liberado

        quarto_liberado.send(
            sender=self.__class__, uh=self.uh, reserva=self,
            usuario=usuario, origem="checkout",
        )
''',
     "agora": r'''
    @transaction.atomic
    def fazer_checkout(self, usuario):
        # Trava reserva e conta antes de conferir o saldo: um consumo lançado ao
        # mesmo tempo (lancar_na_conta também trava a conta) ou entra antes e
        # aparece no saldo, ou chega depois e é recusado por conta fechada.
        from apps.nucleo.sistema import travar

        travar(self)
        self._exige_status(self.Status.HOSPEDADA)
        conta = travar(self.conta)
        …
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
'''},
    {"arquivo": "apps/nucleo/sinais.py", "commit": "1aa5175",
     "antes": "",
     "agora": r'''
def receptor_isolado(func):
    """Decorator de receptor: roda num savepoint e nunca levanta para o emissor."""

    @functools.wraps(func)
    def envoltorio(*args, **kwargs):
        try:
            with transaction.atomic():
                return func(*args, **kwargs)
        except Exception:
            logger.exception(
                "Receptor %s falhou; a operação de origem seguiu normalmente.",
                func.__qualname__,
            )
            return None

    return envoltorio
'''},
]

COMPETENCIA = [
    {"arquivo": "apps/reservas/services.py", "commit": "8e421f2",
     "antes": r'''
def relatorio_producao(inicio: date, fim: date) -> dict:
    """Receita lançada nas contas no período, por natureza (serviço×consumo)."""
    from django.db.models import Sum
    lanc = LancamentoConta.objects.filter(criado_em__date__range=(inicio, fim))
…
def relatorio_ocupacao(inicio: date, fim: date, statuses=None) -> dict:
    …
    uhs = list(UH.objects.filter(status=UH.Status.ATIVA).select_related("tipo"))
    disp = len(uhs) * dias
''',
     "agora": r'''
def relatorio_producao(inicio: date, fim: date) -> dict:
    """Receita das contas no período, por natureza (serviço×consumo). Conta pela
    competência: a diária entra no mês da noite, não no do check-in."""
    from django.db.models import Sum
    lanc = LancamentoConta.objects.filter(competencia__range=(inicio, fim))
…
def relatorio_ocupacao(inicio: date, fim: date, statuses=None) -> dict:
    …
    # Só os quartos: o day use (Dia na Pousada) não é pernoite — contado aqui, as 8
    # unidades dele inflavam a disponibilidade e o preço do dia entrava no ADR.
    day_use = TipoUH.Modalidade.DAY_USE
    uhs = list(UH.objects.filter(status=UH.Status.ATIVA)
               .exclude(tipo__modalidade=day_use).select_related("tipo"))
    disp = len(uhs) * dias
'''},
]

# Interface e engenharia: código novo, sem "antes".
PAINEL_CSS = [
    {"arquivo": "static/css/app.css", "commit": "e604553",
     "antes": "",
     "agora": r'''
.painel-estadias { display:grid; gap:1rem; min-width:0; }
@container conteudo (width > 62rem) {
  .painel-hoje:has(> .painel-estadias + .mural) { grid-template-columns:minmax(0,1fr) minmax(17rem,22rem); }
  .painel-hoje > .painel-estadias + .mural { position:sticky; top:calc(var(--topbar-h) + 1rem); }
}
'''},
]

CI = [
    {"arquivo": ".github/workflows/testes.yml",
     "antes": "",
     "agora": r'''
      - name: Lint (ruff)
        if: ${{ !inputs.ref }}
        run: |
          pip install ruff==0.15.20
          ruff check apps/ config/

      - name: Migrations em dia com os models
        run: python manage.py makemigrations --check --dry-run

      - name: Suíte de testes
        run: python manage.py test --noinput
      …
      - name: Testes no navegador
        run: python manage.py test apps.site --pattern='tests*e2e.py' --noinput
'''},
]

# A base do Gefferson, igual nas duas versões.
OVERBOOKING = [
    {"arquivo": "apps/reservas/models.py", "nota": "igual nas duas versões",
     "antes": r'''
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
''',
     "agora": r'''
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
'''},
]

MODULOS = [
    {"arquivo": "apps/nucleo/permissoes.py", "nota": "igual nas duas versões",
     "antes": r'''
def requer_modulo(codigo: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not modulo_ativo(codigo):
                raise Http404("Módulo não contratado.")
            if not request.user.pode_acessar(codigo):
                raise PermissionDenied("Sem acesso a este módulo.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
''',
     "agora": r'''
def requer_modulo(codigo: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not modulo_ativo(codigo):
                raise Http404("Módulo não contratado.")
            if not request.user.pode_acessar(codigo):
                raise PermissionDenied("Sem acesso a este módulo.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
'''},
]

TRAVAR = [
    {"arquivo": "apps/nucleo/sistema.py", "nota": "igual nas duas versões",
     "antes": r'''
def travar(obj):
    """Trava a linha do objeto no banco (SELECT … FOR UPDATE) e recarrega a instância
    passada do estado já travado — serializa escritas concorrentes (duplo POST/corrida)
    sem trocar a referência do chamador. Usar DENTRO de uma transação atômica."""
    type(obj).objects.select_for_update().get(pk=obj.pk)
    obj.refresh_from_db()
    return obj
''',
     "agora": r'''
def travar(obj):
    """Trava a linha do objeto no banco (SELECT … FOR UPDATE) e recarrega a instância
    passada do estado já travado — serializa escritas concorrentes (duplo POST/corrida)
    sem trocar a referência do chamador. Usar DENTRO de uma transação atômica."""
    type(obj).objects.select_for_update().get(pk=obj.pk)
    obj.refresh_from_db()
    return obj
'''},
]
