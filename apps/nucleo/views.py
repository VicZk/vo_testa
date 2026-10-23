from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .areas import Area, areas_catalogo
from .forms import (
    AbrirCaixaForm,
    AcessoFuncionarioForm,
    AgenciaForm,
    ConfiguracaoUHForm,
    ContaPagarReceberForm,
    EntradaLogbookForm,
    EstornoForm,
    FecharCaixaForm,
    FornecedorForm,
    FuncionarioForm,
    HospedeForm,
    LancamentoFinanceiroForm,
    MovimentoCaixaForm,
    PessoaForm,
    PosicaoCamaFormSet,
    TemporadaForm,
    TipoUHForm,
    UHForm,
)
from .models import (
    UH,
    Agencia,
    ContaPagarReceber,
    EntradaLogbook,
    Funcionario,
    Hospede,
    LancamentoFinanceiro,
    ModuloContratado,
    MovimentoCaixa,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    estornar_movimento,
)
from .modulos import APRESENTACAO
from .paginacao import paginar
from .permissoes import eh_gerente, pode_ver_salario, requer_area, requer_gerencia
from .precos_formulario import LeituraPrecos, valor_exibido

# ---------- Dashboard ----------


@login_required
def dashboard(request):
    from django.urls import NoReverseMatch, reverse

    from .modulos import Modulo

    modulos = ModuloContratado.objects.filter(ativo=True)
    if not request.user.is_superuser:
        modulos = modulos.filter(usuarios=request.user)
    modulos = sorted(
        modulos, key=lambda m: APRESENTACAO.get(m.codigo, {}).get("ordem", 999)
    )

    def _url(apres):
        nome = apres.get("url_name")
        if not nome:
            return None
        try:
            return reverse(nome)
        except NoReverseMatch:
            return None

    grupos: dict[str, list] = {}
    for m in modulos:
        apres = APRESENTACAO.get(m.codigo, {})
        grupos.setdefault(apres.get("grupo", "Outros"), []).append(
            {"nome": m.get_codigo_display(), "url": _url(apres),
             "descricao": apres.get("descricao", "")}
        )
    grupos_modulos = [
        {"titulo": titulo, "itens": itens} for titulo, itens in grupos.items()
    ]

    # Visão geral montada conforme o acesso do usuário — nada de outras áreas.
    hoje = timezone.localdate()
    tem_reservas = request.user.pode_acessar(Modulo.RESERVAS)
    tem_estoque = request.user.pode_acessar(Modulo.ESTOQUE)
    tem_financeiro = request.user.pode_area(Area.FINANCEIRO)
    tem_logbook = request.user.pode_area(Area.LOGBOOK)
    # Gráficos de decisão são de gestão — atendente não vê.
    tem_graficos = eh_gerente(request.user)

    indicadores: dict = {}
    atencao: list = []
    graficos: dict = {}
    resumo_reservas = None
    corredor = None
    recados_turno: list = []

    if tem_financeiro:
        contas_vencidas = ContaPagarReceber.objects.filter(
            status=ContaPagarReceber.Status.ABERTA, vencimento__lt=hoje
        ).count()
        indicadores["caixas_abertos"] = SessaoCaixa.objects.filter(
            status=SessaoCaixa.Status.ABERTA
        ).count()
        indicadores["contas_vencidas"] = contas_vencidas
        if contas_vencidas:
            atencao.append({
                "nivel": "alerta",
                "rotulo": f"{contas_vencidas} conta{'s' if contas_vencidas > 1 else ''} vencida{'s' if contas_vencidas > 1 else ''}",
                "detalhe": "A pagar/receber em atraso",
                "url": reverse("contas") + "?situacao=abertas",
            })
        if tem_graficos:
            mix = (
                MovimentoCaixa.objects.filter(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
                .values("forma_pagamento__nome")
                .annotate(t=Sum("valor"))
                .order_by("-t")
            )
            if mix:
                graficos["pagamento"] = {
                    "labels": [m["forma_pagamento__nome"] or "—" for m in mix],
                    "valores": [float(m["t"]) for m in mix],
                }

    if tem_reservas:
        from apps.reservas.models import Reserva
        from apps.reservas.services import (
            dados_graficos,
            mapa_quartos_hoje,
            resumo_do_dia,
        )

        indicadores["uhs_ativas"] = UH.objects.filter(
            status=UH.Status.ATIVA
        ).exclude(tipo__modalidade="day_use").count()
        indicadores["total_uhs"] = UH.objects.count()
        resumo_reservas = resumo_do_dia()
        corredor = mapa_quartos_hoje(
            ler_limpeza=request.user.pode_acessar(Modulo.GOVERNANCA),
        )
        pendentes = Reserva.objects.filter(status=Reserva.Status.PRE_RESERVA).count()
        if pendentes:
            atencao.append({
                "nivel": "aviso",
                "rotulo": f"{pendentes} pré-reserva{'s' if pendentes > 1 else ''} aguardando confirmação",
                "detalhe": "Confirme o sinal ou cancele",
                "url": reverse("reservas:lista") + "?status=pre_reserva",
            })
        # Saídas vencidas — o atendente finaliza (cobra e/ou fecha).
        from apps.reservas.services import saidas_vencidas

        vencidas = saidas_vencidas()
        from apps.nucleo.templatetags.moeda import intcomma_brl

        n_saldo = len(vencidas["com_saldo"])
        n_quit = len(vencidas["quitadas"])
        if n_saldo:
            atencao.append({
                "nivel": "alerta",
                "rotulo": (
                    f'{n_saldo} saída{('s' if n_saldo > 1 else '')} vencida{('s' if n_saldo > 1 else '')} com saldo em aberto de {intcomma_brl(vencidas['total_aberto'])} a receber'
                ),
                "detalhe": "Cobre no caixa e finalize o check-out",
                "url": reverse("reservas:lista") + "?saida=vencida_saldo",
            })
        if n_quit:
            atencao.append({
                "nivel": "aviso",
                "rotulo": (
                    f"{n_quit} saída{'s' if n_quit > 1 else ''} vencida"
                    f"{'s' if n_quit > 1 else ''} já quitada"
                    f"{'s' if n_quit > 1 else ''}. Confirmar saída"
                ),
                "detalhe": "Conta zerada, só finalizar o check-out",
                "url": reverse("reservas:lista") + "?saida=vencida_quitada",
            })
        # Colchões extra no limite/esgotados nas próximas noites.
        from apps.reservas.services import colchoes_alertas_proximos

        alerta_colchoes = colchoes_alertas_proximos()
        if alerta_colchoes:
            esg = len(alerta_colchoes["esgotadas"])
            ap = len(alerta_colchoes["apertadas"])
            if esg:
                noites = ", ".join(
                    f"{n['noite']:%d/%m}" for n in alerta_colchoes["esgotadas"][:4])
                atencao.append({
                    "nivel": "alerta",
                    "rotulo": f"Colchões extra esgotados em {esg} noite{'s' if esg > 1 else ''}",
                    "detalhe": f"Sem extra para novas lotações em {noites}",
                    "url": reverse("reservas:painel_colchoes"),
                })
            if ap:
                noites = ", ".join(
                    f"{n['noite']:%d/%m}" for n in alerta_colchoes["apertadas"][:4])
                atencao.append({
                    "nivel": "aviso",
                    "rotulo": f"Colchões extra no limite em {ap} noite{'s' if ap > 1 else ''}",
                    "detalhe": f"Resta pouco em {noites}",
                    "url": reverse("reservas:painel_colchoes"),
                })

        if tem_graficos:
            graficos.update(dados_graficos())

    if tem_estoque:
        from .models import produtos_abaixo_minimo

        minimo = produtos_abaixo_minimo()
        indicadores["estoque_minimo"] = minimo
        if minimo:
            atencao.append({
                "nivel": "aviso",
                "rotulo": f"{minimo} produto{'s' if minimo > 1 else ''} no estoque mínimo",
                "detalhe": "Repor antes de faltar",
                "url": reverse("estoque:posicao") + "?alerta=1",
            })

    # Nada desta tela é do usuário (a camareira só tem a Governança, o garçom só o
    # Restaurante): em vez de uma "Visão geral" vazia, ele entra no próprio módulo —
    # ou vê os atalhos dos que tem.
    sem_blocos = not (tem_reservas or tem_estoque or tem_financeiro or tem_graficos
                      or tem_logbook)
    if sem_blocos:
        com_tela = [m for m in modulos if _url(APRESENTACAO.get(m.codigo, {}))]
        if len(com_tela) == 1:
            apres = APRESENTACAO.get(com_tela[0].codigo, {})
            return redirect(apres.get("url_pessoal") or apres["url_name"])

    if tem_logbook:
        indicadores["logbook_hoje"] = EntradaLogbook.objects.filter(
            criado_em__date=hoje
        ).count()
        recados_turno = list(
            EntradaLogbook.objects.select_related("autor")
            .exclude(status=EntradaLogbook.RESOLVIDA)
            .order_by("-importante", "-criado_em")[:6]
        )

    return render(
        request,
        "nucleo/dashboard.html",
        {
            "grupos_modulos": grupos_modulos,
            "indicadores": indicadores,
            "resumo_reservas": resumo_reservas,
            "corredor": corredor,
            "atencao": atencao,
            "graficos": graficos,
            "recados_turno": recados_turno,
            "tem_reservas": tem_reservas,
            "tem_financeiro": tem_financeiro,
            "tem_logbook": tem_logbook,
            # Vários módulos e nenhum bloco desta tela: os atalhos deles.
            "atalhos_modulos": sem_blocos,
        },
    )


# ---------- Central de Módulos (gestão) ----------


@requer_gerencia
def modulos_central(request):
    """Catálogo dos módulos: funcionando / em construção / disponível, com
    dependências e ativação — a base do modelo 'contratado por módulo'."""
    from django.urls import NoReverseMatch, reverse

    from .modulos import DEPENDENCIAS, Modulo

    if request.method == "POST":
        codigo = request.POST.get("codigo", "")
        acao = request.POST.get("acao", "")
        if codigo in Modulo.values:
            _alternar_modulo(request, codigo, acao)
        return redirect("modulos_central")

    ativos = set(
        ModuloContratado.objects.filter(ativo=True).values_list("codigo", flat=True)
    )
    # dependentes reversos: quem depende de X
    dependentes: dict[str, list[str]] = {}
    for cod, deps in DEPENDENCIAS.items():
        for dep in deps:
            dependentes.setdefault(dep, []).append(cod)

    def tem_tela(apres):
        nome = apres.get("url_name")
        if not nome:
            return False
        try:
            reverse(nome)
            return True
        except NoReverseMatch:
            return False

    grupos: dict[str, list] = {}
    total_ativos = 0
    for codigo, apres in sorted(
        APRESENTACAO.items(), key=lambda kv: kv[1].get("ordem", 999)
    ):
        ativo = codigo in ativos
        if ativo:
            total_ativos += 1
        if ativo and tem_tela(apres):
            status = "funcionando"
        elif ativo:
            status = "construcao"
        else:
            status = "disponivel"
        bloqueia = [
            Modulo(c).label for c in dependentes.get(codigo, []) if c in ativos
        ]
        grupos.setdefault(apres.get("grupo", "Outros"), []).append({
            "codigo": codigo,
            "nome": Modulo(codigo).label,
            "descricao": apres.get("descricao", ""),
            "status": status,
            "ativo": ativo,
            "dependencias": [Modulo(c).label for c in DEPENDENCIAS.get(codigo, [])],
            "bloqueia_desativar": bloqueia,
        })

    return render(
        request,
        "nucleo/modulos_central.html",
        {
            "grupos": [
                {"titulo": t, "itens": itens} for t, itens in grupos.items()
            ],
            "total_ativos": total_ativos,
            "total": len(APRESENTACAO),
        },
    )


@transaction.atomic
def _alternar_modulo(request, codigo, acao):
    from .modulos import DEPENDENCIAS, Modulo

    modulo, _ = ModuloContratado.objects.get_or_create(codigo=codigo)
    label = Modulo(codigo).label
    if acao == "ativar":
        modulo.ativo = True
        modulo.desativado_em = None
        try:
            modulo.full_clean()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return
        modulo.save()
        messages.success(request, f"Módulo {label} ativado.")
    elif acao == "desativar":
        ativos = set(
            ModuloContratado.objects.filter(ativo=True)
            .exclude(codigo=codigo)
            .values_list("codigo", flat=True)
        )
        dependentes = [
            Modulo(c).label
            for c, deps in DEPENDENCIAS.items()
            if codigo in deps and c in ativos
        ]
        if dependentes:
            messages.error(
                request,
                f"Não dá para desativar {label}: {', '.join(dependentes)} "
                "depende(m) dele.",
            )
            return
        modulo.ativo = False
        modulo.desativado_em = timezone.now()
        try:
            modulo.full_clean()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
            return
        modulo.save()
        messages.success(request, f"Módulo {label} desativado.")


# ---------- Cadastros: pessoas ----------


PAPEL_FILTROS = {
    "hospedes": ("Hóspedes", Q(hospede__isnull=False)),
    "agencias": ("Agências", Q(agencia__categoria="agencia")),
    "empresas": ("Empresas", Q(agencia__categoria="empresa")),
    "fornecedores": ("Fornecedores", Q(fornecedor__isnull=False)),
    "funcionarios": ("Funcionários", Q(funcionario__isnull=False)),
    "avulsos": (
        "Clientes avulsos",
        Q(hospede__isnull=True, agencia__isnull=True,
          fornecedor__isnull=True, funcionario__isnull=True),
    ),
}

# Telas focadas por papel (Cadastros): perfil -> (título, filtro, papel do "novo").
PERFIS_PESSOA = {
    "hospedes": ("Hóspedes", "hospedes", "hospede"),
    "agencias": ("Agências", "agencias", "agencia"),
    "empresas": ("Empresas", "empresas", "empresa"),
    "fornecedores": ("Fornecedores", "fornecedores", "fornecedor"),
}


@requer_area(Area.PESSOAS)
def pessoas(request, perfil=None):
    """Base de pessoas. `perfil` (hospedes/agencias/empresas) foca a tela num papel:
    trava o filtro, muda o título e o 'novo' já marca o papel certo."""
    busca = request.GET.get("q", "").strip()
    papel = perfil or request.GET.get("papel", "")

    # Os papéis de cada linha (hóspede, agência, funcionário…) vêm no mesmo SELECT:
    # sem isto eram 5 consultas por pessoa listada.
    base = Pessoa.objects.select_related(
        "hospede", "agencia", "funcionario", "fornecedor", "prospecto")
    if busca:
        base = base.filter(
            Q(nome__icontains=busca)
            | Q(documento__icontains=busca)
            | Q(email__icontains=busca)
        )

    # Contadores por papel respeitam a busca atual.
    filtros = [{"chave": "", "rotulo": "Todos", "total": base.count()}]
    for chave, (rotulo, condicao) in PAPEL_FILTROS.items():
        filtros.append(
            {"chave": chave, "rotulo": rotulo, "total": base.filter(condicao).count()}
        )

    if perfil:  # mantém o recorte e oferece navegação para os demais papéis
        titulo, chave, novo_papel = PERFIS_PESSOA[perfil]
        pagina = paginar(request, base.filter(PAPEL_FILTROS[chave][1]))
        return render(request, "nucleo/pessoas.html", {
            "pessoas": pagina, "pagina": pagina,
            "busca": busca, "papel": chave, "perfil": perfil,
            "titulo": titulo, "novo_papel": novo_papel, "filtros": filtros,
        })

    lista = base
    if papel in PAPEL_FILTROS:
        lista = lista.filter(PAPEL_FILTROS[papel][1])

    pagina = paginar(request, lista)
    return render(request, "nucleo/pessoas.html", {
        "pessoas": pagina, "pagina": pagina,
        "busca": busca, "papel": papel, "filtros": filtros,
        "titulo": "Pessoas",
    })


@requer_area(Area.PESSOAS)
def hospedes(request):
    return pessoas(request, perfil="hospedes")


@requer_area(Area.PESSOAS)
def agencias(request):
    return pessoas(request, perfil="agencias")


@requer_area(Area.PESSOAS)
def empresas(request):
    return pessoas(request, perfil="empresas")


@requer_area(Area.PESSOAS)
def fornecedores(request):
    return pessoas(request, perfil="fornecedores")


@login_required
def busca_global(request):
    """Busca da paleta de comandos: hóspedes, reservas e produtos."""
    from django.urls import reverse

    from .modulos import Modulo

    q = request.GET.get("q", "").strip()
    resultados = []
    if len(q) >= 2:
        for pessoa in Pessoa.objects.filter(
            Q(nome__icontains=q) | Q(documento__icontains=q)
        )[:5]:
            papeis = ", ".join(pessoa.papeis) or "Cliente avulso"
            resultados.append({
                "rotulo": pessoa.nome, "tipo": papeis,
                "url": reverse("pessoa_editar", args=[pessoa.pk]),
            })
        if request.user.pode_acessar(Modulo.RESERVAS):
            from apps.reservas.models import Reserva

            for r in Reserva.objects.select_related("hospede", "uh").filter(
                Q(hospede__nome__icontains=q) | Q(uh__numero__icontains=q)
            )[:5]:
                resultados.append({
                    "rotulo": f"Reserva #{r.pk} — {r.hospede.nome}",
                    "tipo": f"{r.uh.numero} · {r.get_status_display()}",
                    "url": reverse("reservas:detalhe", args=[r.pk]),
                })
        if request.user.pode_acessar(Modulo.ESTOQUE):
            from apps.nucleo.models import Produto

            for p in Produto.objects.filter(
                Q(nome__icontains=q) | Q(codigo_barras__icontains=q)
            )[:5]:
                resultados.append({
                    "rotulo": p.nome, "tipo": "Produto",
                    "url": reverse("estoque:produto_editar", args=[p.pk]),
                })
        if request.user.pode_acessar(Modulo.COMERCIAL):
            from apps.comercial.models import Oportunidade

            for op in Oportunidade.objects.select_related("pessoa").filter(
                Q(pessoa__nome__icontains=q) | Q(titulo__icontains=q)
                | Q(pessoa__telefone__icontains=q)
            )[:5]:
                resultados.append({
                    "rotulo": f"{op.pessoa.nome} — {op.titulo_curto or op.titulo}",
                    "tipo": f"Lead · {op.get_status_display()}",
                    "url": reverse("comercial:oportunidade", args=[op.pk]),
                })
    return JsonResponse({"resultados": resultados})


@login_required
@require_POST
def pessoa_nova_rapida(request):
    """
    Cadastro rápido de hóspede sem sair da tela (ex.: dentro do modal de reserva).
    Só o nome é obrigatório; o resto da ficha se completa depois em Cadastros.
    Devolve JSON {id, nome} para o campo de seleção incluir e marcar a pessoa.
    """
    nome = request.POST.get("nome", "").strip()
    if not nome:
        return JsonResponse({"erro": "Informe o nome do hóspede."}, status=400)
    pessoa = Pessoa.objects.create(
        nome=nome,
        documento=request.POST.get("documento", "").strip(),
        telefone=request.POST.get("telefone", "").strip(),
        email=request.POST.get("email", "").strip(),
    )
    Hospede.objects.create(pessoa=pessoa)
    return JsonResponse({"id": pessoa.pk, "nome": pessoa.nome})


def _form_especializacao(request, form_cls, instancia, prefixo, marcado):
    """Instancia o sub-form da especialização só quando o papel está marcado."""
    if not marcado:
        return form_cls(prefix=prefixo, instance=instancia)
    return form_cls(request.POST, prefix=prefixo, instance=instancia)


@requer_area(Area.PESSOAS)
def pessoa_form(request, pk=None):
    pessoa = get_object_or_404(Pessoa, pk=pk) if pk else None
    hospede = getattr(pessoa, "hospede", None)
    agencia = getattr(pessoa, "agencia", None)
    funcionario = getattr(pessoa, "funcionario", None)
    fornecedor = getattr(pessoa, "fornecedor", None)

    # Funcionário tem tela própria (Funcionários/RH) — não é papel deste form.
    if request.method == "POST":
        form = PessoaForm(request.POST, instance=pessoa)
        eh_hospede = "eh_hospede" in request.POST
        eh_agencia = "eh_agencia" in request.POST
        eh_fornecedor = "eh_fornecedor" in request.POST
        form_hospede = _form_especializacao(
            request, HospedeForm, hospede, "hospede", eh_hospede
        )
        form_agencia = _form_especializacao(
            request, AgenciaForm, agencia, "agencia", eh_agencia
        )
        form_fornecedor = _form_especializacao(
            request, FornecedorForm, fornecedor, "fornecedor", eh_fornecedor
        )
        subforms_ok = (
            (not eh_hospede or form_hospede.is_valid())
            and (not eh_agencia or form_agencia.is_valid())
            and (not eh_fornecedor or form_fornecedor.is_valid())
        )
        if form.is_valid() and subforms_ok:
            pessoa = form.save()
            for marcado, subform, existente in [
                (eh_hospede, form_hospede, hospede),
                (eh_agencia, form_agencia, agencia),
                (eh_fornecedor, form_fornecedor, fornecedor),
            ]:
                if marcado:
                    obj = subform.save(commit=False)
                    obj.pessoa = pessoa
                    obj.save()
                elif existente:
                    existente.delete()
            messages.success(request, f"Cadastro de {pessoa.nome} salvo.")
            return redirect("pessoas")
    else:
        form = PessoaForm(instance=pessoa)
        # "Novo" vindo de uma tela focada (?papel=…) já marca o papel certo.
        papel_novo = request.GET.get("papel", "") if not pk else ""
        cat_inicial = None
        if papel_novo == "empresa":
            cat_inicial = Agencia.Categoria.EMPRESA
        elif papel_novo == "agencia":
            cat_inicial = Agencia.Categoria.AGENCIA
        form_hospede = HospedeForm(prefix="hospede", instance=hospede)
        form_agencia = AgenciaForm(
            prefix="agencia", instance=agencia,
            initial={"categoria": cat_inicial} if cat_inicial else None,
        )
        form_fornecedor = FornecedorForm(prefix="fornecedor", instance=fornecedor)
        eh_hospede = hospede is not None or papel_novo == "hospede"
        eh_agencia = agencia is not None or papel_novo in ("agencia", "empresa")
        eh_fornecedor = fornecedor is not None or papel_novo == "fornecedor"

    return render(
        request,
        "nucleo/pessoa_form.html",
        {
            "form": form,
            "pessoa": pessoa,
            "form_hospede": form_hospede,
            "form_agencia": form_agencia,
            "form_fornecedor": form_fornecedor,
            "eh_hospede": eh_hospede,
            "eh_agencia": eh_agencia,
            "eh_fornecedor": eh_fornecedor,
            "funcionario": funcionario,
        },
    )


# ---------- Cadastros: estrutura (tipos de UH e UHs) ----------


@requer_area(Area.QUARTOS)
def estrutura(request):
    from apps.reservas.services import tarifa_minima_do_tipo

    from .estrutura import faixa_do_tipo

    tipos = list(TipoUH.objects.prefetch_related("uhs__posicoes_cama", "uhs__config"))
    for tipo in tipos:
        tipo.tarifa_min = tarifa_minima_do_tipo(tipo)
        tipo.faixa_lotacao = faixa_do_tipo(tipo)
    return render(
        request,
        "nucleo/estrutura.html",
        {
            "tipos": tipos,
            "uhs": UH.objects.select_related("tipo").prefetch_related(
                "posicoes_cama", "config"
            ),
        },
    )


@requer_area(Area.QUARTOS)
@transaction.atomic
def tipo_uh_form(request, pk=None):
    tipo = get_object_or_404(TipoUH, pk=pk) if pk else None
    form = TipoUHForm(request.POST or None, instance=tipo)
    if request.method == "POST" and form.is_valid():
        tipo = form.save()
        messages.success(request, f"Tipo de quarto “{tipo.nome}” salvo.")
        return redirect("estrutura")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": f"Editar {tipo.nome}" if tipo else "Novo tipo de quarto", "voltar": "estrutura"},
    )


# Só as classificações em uso (Baixa/Alta/Feriado); feriado especial = TarifaTemporada.
_CLASSIF_EM_USO = ("baixa", "alta", "feriado")


def _ler_tarifas_quarto(request):
    leitura = LeituraPrecos(request.POST)
    tarifas = [(cod, leitura.grupo({"valor": f"tarifa_{cod}",
                                   "pessoa_adicional": f"adicional_{cod}"}, f"Tarifa {cod}"))
               for cod in _CLASSIF_EM_USO]
    leitura.conferir()
    return tarifas


def _salvar_tarifas_quarto(tarifas, uh):
    from apps.reservas.models import TarifaUnidade
    for cod, valores in tarifas:
        if valores is None:
            continue
        if valores["valor"] is None:
            TarifaUnidade.objects.filter(uh=uh, classificacao=cod).delete()
        else:
            TarifaUnidade.objects.update_or_create(uh=uh, classificacao=cod, defaults=valores)


def _tarifas_quarto(uh, request):
    """Editor de preço por quarto: [{cod, rotulo, valor_fmt, adicional_fmt}]."""
    from apps.reservas.models import TarifaUnidade
    from apps.reservas.models import Temporada as _Temp

    from .forms import _brl

    rotulos = dict(_Temp.Classificacao.choices)
    atuais = {t.classificacao: t for t in TarifaUnidade.objects.filter(uh=uh)} if uh else {}
    linhas = []
    for cod in _CLASSIF_EM_USO:
        if cod not in rotulos:
            continue
        t = atuais.get(cod)
        linhas.append({
            "cod": cod, "rotulo": rotulos[cod],
            "valor_fmt": valor_exibido(request, f"tarifa_{cod}", _brl(t.valor) if t else ""),
            "adicional_fmt": valor_exibido(request, f"adicional_{cod}",
                _brl(t.pessoa_adicional) if t and t.pessoa_adicional is not None else ""),
        })
    return linhas


def _vitrine_do_quarto(request, uh):
    """(vitrine, form) da apresentação do quarto no site. Só para hospedagem e com
    o quarto já salvo — quarto novo/day use não tem vitrine ainda. Lazy import para
    não inverter a dependência (núcleo → site)."""
    if uh is None or uh.tipo.modalidade == uh.tipo.Modalidade.DAY_USE:
        return None, None
    from apps.site.forms import VitrineQuartoForm
    from apps.site.models import VitrineQuarto

    vitrine = VitrineQuarto.objects.filter(uh=uh).first() or VitrineQuarto(uh=uh)
    dados = request.POST if request.method == "POST" else None
    arquivos = request.FILES if request.method == "POST" else None
    return vitrine, VitrineQuartoForm(dados, arquivos, instance=vitrine)


def _ficha_comercial_do_quarto(request, uh):
    """(ficha, form) da copy comercial do quarto — editada no mesmo lugar. Só para
    hospedagem e com o quarto salvo. Lazy import para não inverter a dependência
    (núcleo → comercial)."""
    if uh is None or uh.tipo.modalidade == uh.tipo.Modalidade.DAY_USE:
        return None, None
    from apps.comercial.forms import FichaComercialForm
    from apps.comercial.models import FichaComercial

    ficha = FichaComercial.objects.filter(uh=uh).first() or FichaComercial(uh=uh)
    dados = request.POST if request.method == "POST" else None
    return ficha, FichaComercialForm(dados, instance=ficha)


@requer_area(Area.QUARTOS)
@transaction.atomic
def uh_form(request, pk=None):
    from .estrutura import capacidade, descricao_camas
    from .models import ConfiguracaoUH

    uh = get_object_or_404(UH.objects.select_for_update(), pk=pk) if pk else None
    config = None
    if uh is not None:
        config = ConfiguracaoUH.objects.filter(uh=uh).first() or ConfiguracaoUH(uh=uh)

    vitrine, vitrine_form = _vitrine_do_quarto(request, uh)
    ficha_com, ficha_com_form = _ficha_comercial_do_quarto(request, uh)

    form = UHForm(request.POST or None, instance=uh)
    config_form = ConfiguracaoUHForm(request.POST or None, instance=config)
    formset = PosicaoCamaFormSet(request.POST or None, instance=uh)

    if request.method == "POST":
        if uh is None:
            if form.is_valid():
                novo = form.save()
                messages.success(request, f"Quarto {novo.numero} criado. Confira agora as camas, a capacidade e os preços.")
                return redirect("uh_editar", pk=novo.pk)
        else:
            formularios = [form, config_form, formset, vitrine_form, ficha_com_form]
            validos = [f.is_valid() for f in formularios if f is not None]
            try:
                tarifas = _ler_tarifas_quarto(request)
            except ValidationError as erro:
                form.add_error(None, erro)
                validos.append(False)
            if all(validos):
                form.save()
                config_form.save()
                formset.save()
                _salvar_tarifas_quarto(tarifas, uh)
                if vitrine_form is not None:
                    vitrine_form.save()
                if ficha_com_form is not None:
                    ficha_com_form.save()
                messages.success(request, f"Quarto {uh.numero} salvo.")
                return redirect("estrutura")

        if request.headers.get("X-Form-Preserve") == "1":
            from .formularios import erros_do_formulario
            forms_com_erros = (form, config_form, vitrine_form, ficha_com_form) if uh else (form,)
            erros = [erros_do_formulario(f) for f in forms_com_erros
                     if f is not None and f.errors]
            if uh:
                erros.extend(erros_do_formulario(f) for f in formset if f.errors)
                erros.extend(str(erro) for erro in formset.non_form_errors())
            return JsonResponse({"errors": erros}, status=422, headers={"Cache-Control": "no-store"})

    contexto = {
        "form": form,
        "config_form": config_form,
        "formset": formset,
        "vitrine_form": vitrine_form,
        "ficha_comercial_form": ficha_com_form,
        "uh": uh,
        "titulo": "Quarto",
        "voltar": "estrutura",
        "tarifas_quarto": _tarifas_quarto(uh, request),
    }
    if uh is not None:
        contexto["capacidade"] = capacidade(uh)
        contexto["descricao_camas"] = descricao_camas(uh)
    return render(request, "nucleo/uh_form.html", contexto)


# ---------- Cadastros: temporadas ----------


@requer_area(Area.TEMPORADAS)
def temporadas(request):
    from .models import ConfiguracaoReservas

    config = ConfiguracaoReservas.carregar()
    if request.method == "POST":
        config.feriados_automaticos = request.POST.get("feriados_automaticos") == "on"
        config.save()
        messages.success(
            request,
            "Feriados automáticos ativados."
            if config.feriados_automaticos
            else "Feriados automáticos desativados.",
        )
        return redirect("temporadas")
    return render(
        request,
        "nucleo/temporadas.html",
        {"temporadas": Temporada.objects.all(), "config": config},
    )


def _uhs_hospedagem():
    from apps.nucleo.models.cadastros import TipoUH
    return (UH.objects.exclude(tipo__modalidade=TipoUH.Modalidade.DAY_USE)
            .select_related("tipo").order_by("numero"))


def _ler_tarifas_temporada(request):
    leitura = LeituraPrecos(request.POST)
    tarifas = [(uh, leitura.grupo({"valor": f"tbase_{uh.id}", "pessoa_adicional": f"tadd_{uh.id}"},
                                  f"Quarto {uh.numero}")) for uh in _uhs_hospedagem()]
    leitura.conferir()
    return tarifas


def _salvar_tarifas_temporada(tarifas, temporada):
    from apps.reservas.models import TarifaTemporada
    for uh, valores in tarifas:
        if valores is None:
            continue
        if valores["valor"] is None:
            TarifaTemporada.objects.filter(temporada=temporada, uh=uh).delete()
        else:
            TarifaTemporada.objects.update_or_create(temporada=temporada, uh=uh, defaults=valores)


def _tarifas_temporada(temporada, request):
    """[{uh_id, numero, tematico, base_fmt, adicional_fmt}] para o editor."""
    from apps.reservas.models import TarifaTemporada

    from .forms import _brl

    atuais = ({t.uh_id: t for t in TarifaTemporada.objects.filter(temporada=temporada)}
              if temporada else {})
    linhas = []
    for uh in _uhs_hospedagem():
        t = atuais.get(uh.id)
        linhas.append({
            "uh_id": uh.id, "numero": uh.numero,
            "tematico": getattr(uh, "nome_tematico", "") or "",
            "base_fmt": valor_exibido(request, f"tbase_{uh.id}", _brl(t.valor) if t else ""),
            "adicional_fmt": valor_exibido(request, f"tadd_{uh.id}",
                _brl(t.pessoa_adicional) if t and t.pessoa_adicional is not None else ""),
        })
    return linhas


@requer_area(Area.TEMPORADAS)
@transaction.atomic
def temporada_form(request, pk=None):
    temporada = get_object_or_404(Temporada.objects.select_for_update(), pk=pk) if pk else None
    form = TemporadaForm(request.POST or None, instance=temporada)
    if request.method == "POST":
        valido = form.is_valid()
        try:
            tarifas = _ler_tarifas_temporada(request)
        except ValidationError as erro:
            form.add_error(None, erro)
            valido = False
        if valido:
            temporada = form.save()
            _salvar_tarifas_temporada(tarifas, temporada)
            messages.success(request, f"Temporada “{temporada.nome}” salva.")
            return redirect("temporadas")
        if request.headers.get("X-Form-Preserve") == "1":
            from .formularios import erros_do_formulario
            return JsonResponse({"errors": [erros_do_formulario(form)]}, status=422,
                                headers={"Cache-Control": "no-store"})
    return render(
        request,
        "nucleo/temporada_form.html",
        {"form": form, "titulo": f"Editar {temporada.nome}" if temporada else "Nova temporada", "voltar": "temporadas",
         "temporada": temporada, "tarifas_temporada": _tarifas_temporada(temporada, request)},
    )


_CLASSIF_PRECO = [("baixa", "Baixa"), ("alta", "Alta"), ("feriado", "Feriados")]

# Custo de vender por canal (%), na ordem em que aparece na tela. As chaves são as de
# `Reserva.Canal` — ver `ConfiguracaoReservas.custo_por_canal()`.
_CANAIS_CUSTO = [("ota", "Sites de reserva (OTA)"), ("site", "Site da pousada"),
                 ("whatsapp", "WhatsApp"), ("balcao", "Balcão/telefone")]


@requer_area(Area.QUARTOS)
@transaction.atomic
def tabela_precos(request):
    """Tabela central de preços: quartos (por ala) × Baixa/Alta/Feriados (+ feriados
    especiais Natal/Ano Novo), cada célula = base (2 adultos) + adulto + meia (6-15).
    Mais a seção Day use (por pessoa) e os Parâmetros (single / não-reembolsável /
    taxas). Grava em TarifaUnidade, TarifaTemporada, TarifaDayUse e ConfiguracaoReservas."""
    from apps.nucleo.alas import ORDEM_ALAS
    from apps.reservas.models import (
        TarifaDayUse,
        TarifaTemporada,
        TarifaUnidade,
    )

    from .forms import _brl
    from .models import ConfiguracaoReservas

    especiais = list(Temporada.objects.filter(classificacao="feriado").order_by("inicio"))
    colunas = [{"key": k, "label": r} for k, r in _CLASSIF_PRECO] \
        + [{"key": f"temp{t.pk}", "label": t.nome, "temporada": t} for t in especiais]

    uhs = list(_uhs_hospedagem())
    cfg = ConfiguracaoReservas.carregar()

    if request.method == "POST":
        from .sistema import travar
        travar(cfg)
        leitura = LeituraPrecos(request.POST)
        alteracoes = []
        for uh in uhs:
            for col in colunas:
                valores = leitura.grupo({"valor": f"base_{uh.id}_{col['key']}",
                    "pessoa_adicional": f"add_{uh.id}_{col['key']}", "meia": f"meia_{uh.id}_{col['key']}"},
                    f"Quarto {uh.numero} · {col['label']}")
                if "temporada" in col:
                    modelo, filtros = TarifaTemporada, {"temporada": col["temporada"], "uh": uh}
                else:
                    modelo, filtros = TarifaUnidade, {"uh": uh, "classificacao": col["key"]}
                alteracoes.append((modelo, filtros, valores, "valor"))
        for k, rotulo in _CLASSIF_PRECO:
            valores = leitura.grupo({"valor_adulto": f"du_ad_{k}", "valor_meia": f"du_meia_{k}"},
                                     f"Day use · {rotulo}")
            alteracoes.append((TarifaDayUse, {"classificacao": k}, valores, "valor_adulto"))
        parametros_post = [
            ("single_pct", "single_fator", "Hóspede sozinho", Decimal("100"), True),
            ("nao_reemb_pct", "nao_reembolsavel_desconto", "Desconto comercial", Decimal("100"), True),
            ("iss", "iss_aliquota", "ISS", Decimal("100"), False),
            ("taxa_turismo", "taxa_turismo_diaria", "Taxa de turismo", Decimal("999999.99"), False),
            *[(f"custo_canal_{canal}", f"custo_canal_{canal}", rotulo, Decimal("100"), False)
              for canal, rotulo in _CANAIS_CUSTO],
        ]
        campos_cfg = []
        for campo, atributo, rotulo, maximo, fracao in parametros_post:
            if campo not in request.POST:
                continue
            valor = leitura.decimal(campo, rotulo, maximo=maximo)
            if valor is None:
                if not request.POST[campo].strip():
                    leitura.erros.append(f"{rotulo}: informe um valor; use zero quando não houver cobrança.")
            else:
                setattr(cfg, atributo, valor / 100 if fracao else valor)
                campos_cfg.append(atributo)
        for campo in ("hora_checkin", "hora_checkout"):
            if campo in request.POST:
                valor = leitura.horario(campo, "Horário de check-in" if campo == "hora_checkin" else "Horário de check-out")
                if valor is not None:
                    setattr(cfg, campo, valor)
                    campos_cfg.append(campo)
        if "no_show_noites" in request.POST:
            valor = leitura.escolha("no_show_noites", "No-show automático", cfg.NoShowAutomatico.values)
            if valor is not None:
                cfg.no_show_automatico_noites = valor
                campos_cfg.append("no_show_automatico_noites")
        try:
            leitura.conferir()
            cfg.full_clean()
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
        else:
            for modelo, filtros, valores, base in alteracoes:
                if valores is None:
                    continue
                if valores[base] is None:
                    modelo.objects.filter(**filtros).delete()
                else:
                    modelo.objects.update_or_create(**filtros, defaults=valores)
            if campos_cfg:
                cfg.save(update_fields=campos_cfg)
            messages.success(request, "Tabela de preços salva.")
            return redirect("tabela_precos")

    tus = {(t.uh_id, t.classificacao): t for t in TarifaUnidade.objects.all()}
    tts = {(t.uh_id, t.temporada_id): t for t in TarifaTemporada.objects.all()}

    def _fmt(v):
        return _brl(v) if v is not None else ""

    def _cel(uh, col):
        t = (tts.get((uh.id, col["temporada"].pk)) if "temporada" in col
             else tus.get((uh.id, col["key"])))
        return {
            "key": col["key"],
            "rotulo": col["label"],
            "base_fmt": valor_exibido(request, f"base_{uh.id}_{col['key']}", _fmt(t.valor if t else None)),
            "add_fmt": valor_exibido(request, f"add_{uh.id}_{col['key']}", _fmt(t.pessoa_adicional if t else None)),
            "meia_fmt": valor_exibido(request, f"meia_{uh.id}_{col['key']}", _fmt(t.meia if t else None)),
        }

    por_ala: dict[str, list] = {}
    for uh in uhs:
        por_ala.setdefault(uh.ala or "Outros", []).append({
            "uh_id": uh.id, "numero": uh.numero,
            "tematico": getattr(uh, "nome_tematico", "") or "",
            "celulas": [_cel(uh, c) for c in colunas],
        })
    ordem = {nome: i for i, nome in enumerate(ORDEM_ALAS)}
    grupos = [{"titulo": k, "quartos": v}
              for k, v in sorted(por_ala.items(), key=lambda kv: ordem.get(kv[0], 99))]

    dus = {d.classificacao: d for d in TarifaDayUse.objects.all()}
    day_use = [{"key": k, "label": r,
                "ad_fmt": valor_exibido(request, f"du_ad_{k}", _fmt(dus[k].valor_adulto if k in dus else None)),
                "meia_fmt": valor_exibido(request, f"du_meia_{k}", _fmt(dus[k].valor_meia if k in dus else None))}
               for k, r in _CLASSIF_PRECO]

    parametros = {
        "single_pct": _brl(cfg.single_fator * 100),
        "nao_reemb_pct": _brl(cfg.nao_reembolsavel_desconto * 100),
        "iss": _brl(cfg.iss_aliquota),
        "taxa_turismo": _brl(cfg.taxa_turismo_diaria),
        "hora_checkin": cfg.hora_checkin.strftime("%H:%M"),
        "hora_checkout": cfg.hora_checkout.strftime("%H:%M"),
        "no_show_noites": cfg.no_show_automatico_noites,
        "no_show_opcoes": cfg.NoShowAutomatico.choices,
    }
    for campo in parametros.keys() - {"no_show_opcoes"}:
        parametros[campo] = valor_exibido(request, campo, parametros[campo])
    parametros["no_show_noites"] = str(parametros["no_show_noites"])
    custos_canal = [{"campo": f"custo_canal_{k}", "label": rotulo,
                     "valor_fmt": valor_exibido(request, f"custo_canal_{k}", _brl(getattr(cfg, f"custo_canal_{k}")))}
                    for k, rotulo in _CANAIS_CUSTO]

    return render(request, "nucleo/tabela_precos.html",
                  {"colunas": colunas, "grupos": grupos, "day_use": day_use, "total_quartos": len(uhs),
                   "parametros": parametros, "custos_canal": custos_canal})


# ---------- Caixa ----------


def _sessoes_abertas(user):
    return (SessaoCaixa.objects.filter(operador=user, status=SessaoCaixa.Status.ABERTA)
            .order_by("modulo"))


def _sessao_a_operar(request, modulo=None):
    """A sessão de caixa selecionada do operador. Um operador pode ter um caixa
    aberto POR MÓDULO (gaveta separada) — escolher pelo módulo evita lançar no caixa
    errado e o 500 que `get` com múltiplos resultados dava."""
    qs = _sessoes_abertas(request.user)
    if modulo:
        return qs.filter(modulo=modulo).first()
    return qs.first() if qs.count() == 1 else None


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa(request):
    abertas = _sessoes_abertas(request.user)
    modulo_sel = request.GET.get("modulo") or ""
    sessao = abertas.filter(modulo=modulo_sel).first() if modulo_sel else abertas.first()
    form_abrir = AbrirCaixaForm(usuario=request.user)
    form_movimento = MovimentoCaixaForm()
    form_fechar = FecharCaixaForm()
    return render(
        request,
        "nucleo/caixa.html",
        {
            "sessao": sessao,
            "sessoes_abertas": abertas,
            "form_abrir": form_abrir,
            "form_movimento": form_movimento,
            "form_fechar": form_fechar,
            "eh_gerente": eh_gerente(request.user),
        },
    )


def _voltar_ao_caixa(modulo):
    """Mantém a gaveta escolhida após salvar ou corrigir uma operação."""
    return redirect(f"{reverse('caixa')}?{urlencode({'modulo': modulo})}")


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_abrir(request):
    if request.method != "POST":
        return redirect("caixa")
    form = AbrirCaixaForm(request.POST, usuario=request.user)
    if form.is_valid():
        try:
            SessaoCaixa.objects.create(
                operador=request.user,
                modulo=form.cleaned_data["modulo"],
                fundo_troco=form.cleaned_data["fundo_troco"],
            )
            messages.success(request, "Caixa aberto. Bom trabalho!")
        except IntegrityError:
            messages.error(request, "Você já tem um caixa aberto neste módulo.")
        return _voltar_ao_caixa(form.cleaned_data["modulo"])
    else:
        messages.error(request, "Não foi possível abrir o caixa. Confira os dados.")
    return redirect("caixa")


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_movimento(request):
    if request.method != "POST":
        return redirect("caixa")
    sessao = _sessao_a_operar(request, request.POST.get("modulo"))
    if not sessao:
        messages.error(request, "Selecione o caixa (módulo) a operar.")
        return redirect("caixa")
    form = MovimentoCaixaForm(request.POST)
    if form.is_valid():
        movimento = form.save(commit=False)
        movimento.sessao = sessao
        movimento.criado_por = request.user
        try:
            movimento.save()
            messages.success(
                request,
                f"{movimento.get_tipo_display()} de R$ {movimento.valor} registrado.",
            )
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        erros = "; ".join(
            f"{campo}: {' '.join(msgs)}" for campo, msgs in form.errors.items()
        )
        messages.error(request, f"Movimento não registrado: {erros}")
    return _voltar_ao_caixa(sessao.modulo)


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_fechar(request):
    if request.method != "POST":
        return redirect("caixa")
    sessao = _sessao_a_operar(request, request.POST.get("modulo"))
    if not sessao:
        messages.error(request, "Selecione o caixa (módulo) a fechar.")
        return redirect("caixa")
    form = FecharCaixaForm(request.POST)
    if form.is_valid():
        try:
            sessao.fechar(form.cleaned_data["valor_contado"], request.user,
                          observacoes=form.cleaned_data["observacoes"])
        except ValidationError as erro:  # ex.: fechada ao mesmo tempo em outra aba
            messages.error(request, " ".join(erro.messages))
            return _voltar_ao_caixa(sessao.modulo)
        if sessao.diferenca == Decimal("0.00"):
            messages.success(request, "Caixa fechado sem diferença. 🎉")
        else:
            messages.warning(
                request,
                f"Caixa fechado com diferença de R$ {sessao.diferenca}. "
                "A gerência pode revisar na lista de sessões.",
            )
        return redirect("caixa_sessao", pk=sessao.pk)
    messages.error(request, "Informe o valor contado para fechar o caixa.")
    return _voltar_ao_caixa(sessao.modulo)


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_sessoes(request):
    """Histórico de sessões: gerência vê todas; operador, só as suas."""
    sessoes = SessaoCaixa.objects.select_related("operador")
    if not eh_gerente(request.user):
        sessoes = sessoes.filter(operador=request.user)
    return render(request, "nucleo/caixa_sessoes.html", {"sessoes": sessoes})


@requer_area(Area.CAIXA, Area.FINANCEIRO)
def caixa_sessao(request, pk):
    sessao = get_object_or_404(SessaoCaixa.objects.select_related("operador"), pk=pk)
    if sessao.operador != request.user and not eh_gerente(request.user):
        raise PermissionDenied
    return render(
        request,
        "nucleo/caixa_sessao.html",
        {
            "sessao": sessao,
            "movimentos": sessao.movimentos.select_related("forma_pagamento"),
            "eh_gerente": eh_gerente(request.user),
            "form_estorno": EstornoForm(),
        },
    )


@requer_gerencia
def caixa_reabrir(request, pk):
    if request.method != "POST":
        return redirect("caixa_sessao", pk=pk)
    sessao = get_object_or_404(SessaoCaixa, pk=pk)
    try:
        sessao.reabrir(request.user, request.POST.get("motivo", ""))
        messages.success(request, "Sessão reaberta. A ação foi registrada na auditoria.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("caixa_sessao", pk=pk)


@requer_gerencia
def estorno(request, movimento_pk):
    movimento = get_object_or_404(
        MovimentoCaixa.objects.select_related("sessao"), pk=movimento_pk
    )
    if request.method != "POST":
        return redirect("caixa_sessao", pk=movimento.sessao_id)
    form = EstornoForm(request.POST)
    if form.is_valid():
        try:
            estornar_movimento(
                movimento,
                movimento.sessao,
                request.user,
                form.cleaned_data["motivo"],
                form.cleaned_data["valor"],
            )
            messages.success(request, "Estorno registrado no histórico de auditoria.")
        except ValidationError as erro:
            messages.error(request, " ".join(erro.messages))
    else:
        messages.error(request, "Informe valor e motivo do estorno.")
    return redirect("caixa_sessao", pk=movimento.sessao_id)


# ---------- Financeiro: lançamentos e contas ----------


@requer_area(Area.FINANCEIRO)
def lancamentos(request):
    lista = LancamentoFinanceiro.objects.select_related("categoria")
    tipo = request.GET.get("tipo", "")
    if tipo in ("receita", "despesa"):
        lista = lista.filter(tipo=tipo)
    totais = {
        "receitas": lista.filter(tipo="receita").aggregate(t=Sum("valor"))["t"] or 0,
        "despesas": lista.filter(tipo="despesa").aggregate(t=Sum("valor"))["t"] or 0,
    }
    pagina = paginar(request, lista, 100)
    return render(
        request,
        "nucleo/lancamentos.html",
        {"lancamentos": pagina, "pagina": pagina, "tipo": tipo, "totais": totais},
    )


@requer_area(Area.FINANCEIRO)
def lancamento_form(request):
    form = LancamentoFinanceiroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lancamento = form.save(commit=False)
        lancamento.criado_por = request.user
        lancamento.save()
        messages.success(request, "Lançamento registrado.")
        return redirect("lancamentos")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Lançamento financeiro", "voltar": "lancamentos"},
    )


@requer_area(Area.FINANCEIRO)
def contas(request):
    lista = ContaPagarReceber.objects.select_related("pessoa", "categoria")
    situacao = request.GET.get("situacao", "abertas")
    if situacao == "abertas":
        lista = lista.filter(status=ContaPagarReceber.Status.ABERTA)
    return render(
        request, "nucleo/contas.html", {"contas": lista, "situacao": situacao}
    )


@requer_area(Area.FINANCEIRO)
def conta_form(request):
    form = ContaPagarReceberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Conta registrada.")
        return redirect("contas")
    return render(
        request,
        "nucleo/form_simples.html",
        {"form": form, "titulo": "Conta a pagar/receber", "voltar": "contas"},
    )


@requer_area(Area.FINANCEIRO)
def conta_baixar(request, pk):
    if request.method != "POST":
        return redirect("contas")
    conta = get_object_or_404(ContaPagarReceber, pk=pk)
    try:
        conta.baixar(request.user)
        messages.success(request, f"Conta “{conta.descricao}” baixada.")
    except ValidationError as erro:
        messages.error(request, " ".join(erro.messages))
    return redirect("contas")


# ---------- Logbook ----------

from . import logbook_services  # noqa: E402


def _contexto_logbook(filtro):
    base = EntradaLogbook.objects.select_related(
        "autor", "resolvida_por"
    ).prefetch_related("comentarios__autor")
    abertas_qs = base.exclude(status=EntradaLogbook.RESOLVIDA)
    resolvidas_qs = base.filter(status=EntradaLogbook.RESOLVIDA)

    if filtro == "importantes":
        # "Importantes" é o histórico dos importantes: pendentes em cima,
        # resolvidos embaixo — bate com o contador.
        abertas = list(abertas_qs.filter(importante=True).order_by("-criado_em"))
        resolvidas = list(resolvidas_qs.filter(importante=True))
        mostra_resolvidas = True
    else:
        # "Todas" mostra o histórico completo (bate com o contador); "Abertas"
        # mostra só as últimas resolvidas como contexto.
        abertas = list(abertas_qs.order_by("-importante", "-criado_em"))
        mostra_resolvidas = filtro in ("abertas", "todas")
        resolvidas = []
        if mostra_resolvidas:
            resolvidas = list(resolvidas_qs if filtro == "todas" else resolvidas_qs[:5])

    return {
        "filtro": filtro,
        "contagens": {
            "abertas": abertas_qs.count(),
            "todas": base.count(),
            "importantes": base.filter(importante=True).count(),
        },
        "abertas": abertas,
        "resolvidas": resolvidas,
        "mostra_resolvidas": mostra_resolvidas,
    }


@requer_area(Area.LOGBOOK)
def logbook(request):
    if request.method == "POST":
        form = EntradaLogbookForm(request.POST)
        if form.is_valid():
            logbook_services.registrar_ocorrencia(
                request.user,
                form.cleaned_data["texto"],
                form.cleaned_data.get("importante", False),
            )
            messages.success(request, "Ocorrência registrada no logbook.")
            return redirect("logbook")
    else:
        form = EntradaLogbookForm()
    filtro = request.GET.get("filtro", "abertas")
    if filtro not in ("abertas", "todas", "importantes"):
        filtro = "abertas"
    ctx = {"form": form, **_contexto_logbook(filtro)}
    return render(request, "nucleo/logbook.html", ctx)


@requer_area(Area.LOGBOOK)
@require_POST
def logbook_comentar(request, pk):
    entrada = get_object_or_404(EntradaLogbook, pk=pk)
    try:
        logbook_services.comentar(request.user, entrada, request.POST.get("texto", ""))
    except ValidationError as erro:
        return render(
            request, "nucleo/partials/logbook_ocorrencia.html",
            {"e": entrada, "erro": " ".join(erro.messages),
             "texto_respondido": request.POST.get("texto", "")},
        )
    entrada.refresh_from_db()
    return render(request, "nucleo/partials/logbook_ocorrencia.html", {"e": entrada})


@requer_area(Area.LOGBOOK)
@require_POST
def logbook_resolver(request, pk):
    entrada = get_object_or_404(EntradaLogbook, pk=pk)
    ja_resolvida = entrada.status == EntradaLogbook.RESOLVIDA
    logbook_services.resolver(request.user, entrada, request.POST.get("nota", ""))
    entrada.refresh_from_db()
    ctx = {"e": entrada}
    if ja_resolvida:
        # Alguém fechou antes (resolver é idempotente, mantém o 1º) — avisa o 2º
        # para ele saber que a nota dele não foi gravada.
        ctx["erro"] = f"Já havia sido resolvida por {entrada.resolvida_por or '—'}."
    return render(request, "nucleo/partials/logbook_ocorrencia.html", ctx)


# ---------- Funcionários (RH) — Pessoal; Equipe & Acessos deriva daqui ----------

from django.contrib.auth import get_user_model  # noqa: E402

Usuario = get_user_model()


@requer_area(Area.FUNCIONARIOS, Area.EQUIPE)
def funcionarios(request):
    """Lista de quem trabalha na pousada — cargo/setor/turno/admissão + acesso."""
    setor = request.GET.get("setor", "")
    qs = Funcionario.objects.select_related("pessoa", "usuario")
    if setor:
        qs = qs.filter(setor=setor)
    lista = []
    for f in qs:
        u = f.usuario
        nivel = "Gerência" if u and (u.is_superuser or u.is_staff) else ("Operador" if u else "Sem login")
        lista.append({"f": f, "nivel": nivel, "ativo": bool(u and u.is_active)})
    setores = (
        Funcionario.objects.exclude(setor="")
        .values_list("setor", flat=True).distinct().order_by("setor")
    )
    return render(request, "nucleo/funcionarios.html", {
        "funcionarios": lista, "setores": setores, "setor": setor,
        "total": Funcionario.objects.count(),
    })


def _contexto_novo(request, gerente, form=None):
    """Ficha em branco para o cadastro em uma etapa (mesmo layout da edição)."""
    modulos_qs = ModuloContratado.objects.filter(ativo=True).order_by("codigo")
    contexto = {
        "modo": "novo", "f": None, "usuario": None, "gerente": gerente,
        "proprio": False, "historico": None,
        "form": form or FuncionarioForm(ver_salario=pode_ver_salario(request.user)),
        "modulos": [{"codigo": m.codigo, "nome": m.get_codigo_display(),
                     "tem": m.codigo in request.POST.getlist("modulos")}
                    for m in modulos_qs],
        "areas": [{"codigo": c, "nome": rot, "tem": c in request.POST.getlist("areas")}
                  for c, rot in areas_catalogo()],
    }
    contexto.update(_dados_ficha(request, pendente=request.method == "POST"))
    return contexto


def _dados_ficha(request, f=None, *, pendente=False):
    u = f.usuario if f else None
    return {
        "nome_preenchido": request.POST.get("nome", "") if pendente else (f.pessoa.nome if f else ""),
        "documento_preenchido": request.POST.get("documento", "") if pendente else (f.pessoa.documento if f else ""),
        "login_preenchido": request.POST.get("username", "") if pendente else "",
        "gerente_marcado": request.POST.get("gerente") == "on" if pendente else bool(u and (u.is_staff or u.is_superuser)),
        "ativo_marcado": request.POST.get("ativo") == "on" if pendente else (u.is_active if u else True),
    }


def _validar_ficha_funcionario(request, form, gerente, usuario=None):
    form.is_valid()
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        form.add_error(None, "Informe o nome do funcionário.")
    elif len(nome) > Pessoa._meta.get_field("nome").max_length:
        form.add_error(None, "O nome do funcionário é longo demais.")
    documento = (request.POST.get("documento") or "").strip()
    if len(documento) > Pessoa._meta.get_field("documento").max_length:
        form.add_error(None, "CPF/CNPJ deve ter até 18 caracteres.")
    acesso = AcessoFuncionarioForm(request.POST, usuario=usuario) if gerente else None
    if acesso and not acesso.is_valid():
        for campo, erros in acesso.errors.items():
            for erro in erros:
                form.add_error(None, f"{acesso.fields[campo].label}: {erro}" if campo in acesso.fields else erro)
    return acesso


def _erro_ficha_funcionario(request, form):
    from .formularios import erros_do_formulario

    erro = erros_do_formulario(form)
    if request.headers.get("X-Form-Preserve") == "1":
        return JsonResponse({"errors": [erro]}, status=422, headers={"Cache-Control": "no-store"})
    if request.headers.get("HX-Request"):
        import json

        from django.http import HttpResponse

        return HttpResponse("", headers={"HX-Reswap": "none", "HX-Trigger": json.dumps(
            {"aviso": {"texto": erro, "tipo": "error"}})})
    return None


@requer_area(Area.FUNCIONARIOS, Area.EQUIPE)
def funcionario_novo(request):
    """Cadastro do funcionário em UMA etapa: ficha de RH + escala + acesso."""
    gerente = eh_gerente(request.user)
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        form = FuncionarioForm(request.POST, ver_salario=pode_ver_salario(request.user))
        acesso = _validar_ficha_funcionario(request, form, gerente)
        if form.is_valid():
            try:
                with transaction.atomic():
                    pessoa = Pessoa.objects.create(
                        nome=nome, documento=(request.POST.get("documento") or "").strip())
                    f = form.save(commit=False)
                    f.pessoa = pessoa
                    f.save()
                    if gerente:
                        _aplicar_acesso_funcionario(request, f,
                            ModuloContratado.objects.filter(ativo=True).order_by("codigo"), acesso)
            except IntegrityError:
                if not acesso or not Usuario.objects.filter(username=acesso.cleaned_data.get("username")).exists():
                    raise
                form.add_error(None, "Já existe um usuário com esse login.")
            else:
                messages.success(request, f"Funcionário “{nome}” cadastrado.")
                return redirect("funcionarios")
        erro = _erro_ficha_funcionario(request, form)
        if erro is not None:
            return erro
        return render(request, "nucleo/funcionario_form.html",
                      _contexto_novo(request, gerente, form))
    return render(request, "nucleo/funcionario_form.html", _contexto_novo(request, gerente))


def _aplicar_acesso_funcionario(request, f, modulos_ativos_qs, acesso):
    """Cria/atualiza o login do funcionário + módulos/áreas. Só gerência chama."""
    username = acesso.cleaned_data.get("username", "")
    senha = acesso.cleaned_data.get("password", "")
    u = f.usuario
    if not u:
        if not username:
            return  # sem login e não pediram — ok
        u = Usuario.objects.create_user(
            username=username, first_name=f.pessoa.nome, password=senha
        )
        f.usuario = u
        f.save(update_fields=["usuario"])
        senha = ""  # já consumida na criação
    proprio = u.pk == request.user.pk
    u.modulos.set(modulos_ativos_qs.filter(codigo__in=set(request.POST.getlist("modulos"))))
    codigos_areas = {c for c, _ in areas_catalogo()}
    u.areas = [a for a in request.POST.getlist("areas") if a in codigos_areas]
    # Travas: nunca rebaixar/desativar a si mesmo NEM um superusuário (o dono é
    # gerido pelo admin — evita lockout acidental pela ficha).
    if not proprio and not u.is_superuser:
        u.is_staff = request.POST.get("gerente") == "on"
        u.is_active = request.POST.get("ativo") == "on"
    if senha and len(senha) >= 8:
        u.set_password(senha)
    u.save()
    # Conceder/revogar MÓDULO é M2M — não entra na trilha automática por signal.
    # Registra explicitamente a mudança de acesso (quem/para quem/o quê).
    from .models import registrar_auditoria
    registrar_auditoria(request.user, "alterar_acesso", u, {
        "modulos": sorted(u.modulos.values_list("codigo", flat=True)),
        "areas": list(u.areas or []),
    })


def _ficha_contexto(request, f, gerente, form=None):
    """Contexto editável da ficha do funcionário (compartilhado painel × página)."""
    from .historico import historico_funcionario

    modulos_qs = ModuloContratado.objects.filter(ativo=True).order_by("codigo")
    u = f.usuario
    ver_salario = pode_ver_salario(request.user)
    pendente = bool(form is not None and form.is_bound and form.errors)
    contexto = {
        "f": f, "gerente": gerente, "usuario": u,
        "form": form or FuncionarioForm(instance=f, ver_salario=ver_salario),
        "modulos": [
            {"codigo": m.codigo, "nome": m.get_codigo_display(),
             "tem": m.codigo in request.POST.getlist("modulos") if pendente else bool(u and u.modulos.filter(pk=m.pk).exists())}
            for m in modulos_qs
        ],
        "areas": [
            {"codigo": c, "nome": rot,
             "tem": c in request.POST.getlist("areas") if pendente else bool(u and c in (u.areas or []))}
            for c, rot in areas_catalogo()
        ],
        "proprio": bool(u and u.pk == request.user.pk),
        "historico": historico_funcionario(f) if gerente else None,
    }
    contexto.update(_dados_ficha(request, f, pendente=pendente))
    return contexto


def _salvar_ficha(request, f, gerente):
    """Aplica a ficha (dados pessoais + RH + acesso). Retorna (ok, form)."""
    usuario_existente = f.usuario_id
    form = FuncionarioForm(request.POST, instance=f, ver_salario=pode_ver_salario(request.user))
    acesso = _validar_ficha_funcionario(request, form, gerente, f.usuario)
    if not form.is_valid():
        return False, form
    try:
        with transaction.atomic():
            f.pessoa.nome = request.POST.get("nome", "").strip()
            doc = request.POST.get("documento")
            if doc is not None:
                f.pessoa.documento = doc.strip()
            f.pessoa.save()
            form.save()
            if gerente:
                _aplicar_acesso_funcionario(request, f,
                    ModuloContratado.objects.filter(ativo=True).order_by("codigo"), acesso)
    except IntegrityError:
        if usuario_existente or not acesso or not Usuario.objects.filter(username=acesso.cleaned_data.get("username")).exists():
            raise
        form.add_error(None, "Já existe um usuário com esse login.")
        return False, form
    return True, form


@requer_area(Area.FUNCIONARIOS, Area.EQUIPE)
def funcionario_editar(request, pk):
    """Página cheia da ficha (fallback). O editor principal é o painel inline."""
    f = get_object_or_404(Funcionario.objects.select_related("pessoa", "usuario"), pk=pk)
    gerente = eh_gerente(request.user)
    form = None
    if request.method == "POST":
        ok, form = _salvar_ficha(request, f, gerente)
        if ok:
            # Vindo do painel inline (HTMX): devolve o painel atualizado.
            if request.headers.get("HX-Request"):
                ctx = _ficha_contexto(request, f, gerente)
                ctx["salvo"] = True
                return render(request, "nucleo/partials/funcionario_painel.html", ctx)
            messages.success(request, f"Ficha de {f.pessoa.nome} salva.")
            return redirect("funcionarios")
        erro = _erro_ficha_funcionario(request, form)
        if erro is not None:
            return erro
    ctx = _ficha_contexto(request, f, gerente, form=form)
    ctx["modo"] = "editar"
    return render(request, "nucleo/funcionario_form.html", ctx)


@requer_area(Area.FUNCIONARIOS, Area.EQUIPE)
def funcionario_painel(request, pk):
    """Painel expansível editável (HTMX): abas Ficha RH · Acesso · Histórico.
    Histórico e salário só para gerência."""
    f = get_object_or_404(Funcionario.objects.select_related("pessoa", "usuario"), pk=pk)
    gerente = eh_gerente(request.user)
    return render(request, "nucleo/partials/funcionario_painel.html",
                  _ficha_contexto(request, f, gerente))
