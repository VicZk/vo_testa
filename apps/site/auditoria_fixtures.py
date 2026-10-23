"""Dados sintéticos de apresentação, recriados no PostgreSQL descartável dos testes."""
from datetime import time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.core.cache import cache
from django.utils import timezone


def criar_cenario_templates():
    from apps.comercial.models import CampanhaEmail, EtapaFunil, Oportunidade, TemplateEmail
    from apps.daypass.models import DiaDayPass, TurnoDayPass, VisitaDayPass, VisitanteDayPass
    from apps.escala.models import Atribuicao, Turno
    from apps.governanca.services import situacao_uh
    from apps.lavanderia.models import (
        ItemEnxoval,
        ItemOrdemLavanderia,
        OrdemLavanderia,
        ServicoLavanderia,
    )
    from apps.loja.services import finalizar_venda
    from apps.manutencao.models import OrdemServico
    from apps.marketing.models import Campanha as CampanhaMarketing
    from apps.nps.models import RespostaNPS
    from apps.nucleo.models import (
        UH,
        CategoriaFinanceira,
        CategoriaProduto,
        ConfiguracaoReservas,
        ContaPagarReceber,
        EmbalagemProduto,
        FormaPagamento,
        Fornecedor,
        Funcionario,
        Hospede,
        Inventario,
        ItemInventario,
        LocalEstoque,
        LoteEstoque,
        ModuloContratado,
        Pessoa,
        PosicaoCama,
        Produto,
        SessaoCaixa,
        Temporada,
        TipoUH,
        Usuario,
        registrar_entrada,
    )
    from apps.nucleo.modulos import Modulo
    from apps.pagamentos.models import Cobranca
    from apps.reservas.models import FechamentoDiario, Reserva, RestricaoVenda
    from apps.restaurante import services as restaurante
    from apps.restaurante.models import Mesa

    c = SimpleNamespace(hoje=timezone.localdate())
    c.usuario = Usuario.objects.create_superuser(username="qa-templates", password=f"qa-{uuid4()}")
    for codigo in Modulo.values:
        ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
    ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={"feriados_automaticos": False})
    cache.clear()
    c.tipo = TipoUH.objects.create(nome="Suíte familiar de conferência", tarifa_base="348.90")
    c.uh = UH.objects.create(numero="QA 01", tipo=c.tipo, bloco="A")
    c.uh2 = UH.objects.create(numero="QA 02", tipo=c.tipo, bloco="B")
    for quarto in (c.uh, c.uh2):
        PosicaoCama.objects.create(uh=quarto, nome="Quarto", montagem_padrao="casal")
    c.pessoa = Pessoa.objects.create(
        nome="Ana Clara de Conferência Visual", documento="11144477735",
        telefone="(49) 99900-0000", email="ana.visual@example.test",
    )
    Hospede.objects.create(pessoa=c.pessoa)
    c.fornecedor = Pessoa.objects.create(nome="Fornecedor da Conferência de Estoque")
    Fornecedor.objects.create(pessoa=c.fornecedor)
    c.funcionario = Funcionario.objects.create(
        pessoa=Pessoa.objects.create(nome="Marina da Conferência Operacional"),
        cargo="Camareira", setor="Governança", turno="manha", admissao=c.hoje,
        expediente_inicio=time(8), expediente_fim=time(16), usuario=c.usuario,
    )
    c.temporada = Temporada.objects.create(
        nome="Temporada da conferência", classificacao="baixa",
        inicio=c.hoje, fim=c.hoje + timedelta(days=90),
    )
    c.reserva = Reserva.objects.create(
        uh=c.uh, hospede=c.pessoa, checkin=c.hoje + timedelta(days=10),
        checkout=c.hoje + timedelta(days=12), status="confirmada", valor_diaria="348.90",
        criado_por=c.usuario,
    )
    passada = Reserva.objects.create(
        uh=c.uh2, hospede=c.pessoa, checkin=c.hoje - timedelta(days=3),
        checkout=c.hoje - timedelta(days=1), status="checkout", valor_diaria="348.90",
        checkout_real=timezone.now(), criado_por=c.usuario,
    )
    RespostaNPS.objects.create(
        reserva=passada, hospede=c.pessoa, nota=9, consentimento_versao="qa-v1",
        comentario="Quarto confortável e atendimento atencioso. Conferência de texto longo.",
    )
    RestricaoVenda.objects.create(
        descricao="Feriado de conferência", inicio=c.hoje + timedelta(days=60),
        fim=c.hoje + timedelta(days=62), min_noites=3, criado_por=c.usuario,
    )
    FechamentoDiario.objects.create(
        data=c.hoje - timedelta(days=1), quartos_disponiveis=3, quartos_ocupados=1,
        chegadas=1, saidas=2, no_shows=0, receita_diarias="348.90",
        receita_servico="376.81", receita_consumo="85.90", saldo_em_aberto="462.71",
    )
    c.categoria = CategoriaProduto.objects.create(nome="Bebidas de conferência")
    c.local = LocalEstoque.objects.create(nome="Depósito da conferência", modulo="loja")
    c.cozinha = LocalEstoque.objects.create(nome="Cozinha da conferência", modulo="restaurante")
    c.produto = Produto.objects.create(
        nome="Água mineral sem gás · embalagem de conferência", categoria=c.categoria,
        preco_venda="18.90", estoque_minimo="5.500",
    )
    registrar_entrada(c.produto, c.local, 30, Decimal("2.3456"), c.usuario)
    registrar_entrada(c.produto, c.cozinha, 10, Decimal("2.3456"), c.usuario)
    c.perecivel = Produto.objects.create(
        nome="Ingrediente refrigerado de conferência", categoria=c.categoria,
        controla_validade=True, unidade="kg", preco_venda="24.50",
    )
    c.lote = LoteEstoque.objects.create(
        produto=c.perecivel, codigo="QA-LOTE-2026", validade=c.hoje + timedelta(days=8), criado_por=c.usuario,
    )
    c.embalagem = EmbalagemProduto.objects.create(produto=c.produto, nome="Caixa de conferência", fator="12.000")
    c.inventario = Inventario.objects.create(local=c.local, criado_por=c.usuario)
    ItemInventario.objects.create(
        inventario=c.inventario, produto=c.produto, saldo_sistema="30.000",
        quantidade_contada="29.500", contado=True,
    )
    c.dinheiro, _ = FormaPagamento.objects.get_or_create(nome="Dinheiro QA", defaults={"tipo": "dinheiro"})
    c.sessao = SessaoCaixa.objects.create(operador=c.usuario, modulo="loja", fundo_troco="100.00")
    c.venda = finalizar_venda(
        c.usuario, c.local, [{"produto_id": c.produto.pk, "quantidade": "2"}],
        "caixa", forma=c.dinheiro, cliente=c.pessoa, chave=uuid4(),
    )
    categoria_financeira = CategoriaFinanceira.objects.create(nome="Compras da conferência", tipo="despesa")
    ContaPagarReceber.objects.create(
        tipo="pagar", pessoa=c.fornecedor, categoria=categoria_financeira,
        descricao="Compra para conferência dos valores da listagem", valor="1234.56",
        vencimento=c.hoje - timedelta(days=1),
    )
    Cobranca.objects.create(
        valor="1458.90", metodo="pix", descricao="Recebimento para conferência visual",
        status="pago", pago_em=timezone.now(), valor_liquido="1450.00", taxa="8.90",
        criado_por=c.usuario,
    )
    c.servico = ServicoLavanderia.objects.create(nome="Lavagem de roupa pessoal", preco="12.50")
    ordem = OrdemLavanderia.objects.create(
        cliente=c.pessoa, criado_por=c.usuario, status="entregue", entregue_em=timezone.now(),
    )
    ItemOrdemLavanderia.objects.create(
        ordem=ordem, servico=c.servico, descricao=c.servico.nome,
        quantidade="2.500", preco_unitario="12.50",
    )
    ItemEnxoval.objects.create(nome="Toalha de banho da conferência", minimo=4, por_faxina=2)
    situacao_uh(c.uh)
    situacao_uh(c.uh2)
    c.os = OrdemServico.objects.create(
        uh=c.uh, titulo="Conferir vedação da janela e iluminação do quarto",
        criado_por=c.usuario, responsavel=c.usuario,
    )
    c.turno = TurnoDayPass.objects.create(
        dia=DiaDayPass.objects.create(data=c.hoje), nome="Tarde de conferência",
        inicio=time(13), fim=time(18), capacidade=30, contar_hospedes=False,
        preco_adulto="59.90", preco_crianca="29.95", ativo=True,
    )
    visita = VisitaDayPass.objects.create(
        turno=c.turno, responsavel=c.pessoa, vagas=2, valor_ingressos="89.85", criado_por=c.usuario,
    )
    VisitanteDayPass.objects.create(visita=visita, nome="Visitante adulto da conferência")
    VisitanteDayPass.objects.create(visita=visita, nome="Visitante criança da conferência", crianca=True)
    etapa = EtapaFunil.objects.create(nome="Conversa de conferência", ordem=10)
    c.oportunidade = Oportunidade.objects.create(
        pessoa=c.pessoa, etapa=etapa, titulo="Estadia em família para conferência visual",
        valor_estimado="1458.90", criado_por=c.usuario, responsavel=c.usuario,
    )
    c.template_email = TemplateEmail.objects.create(
        nome="Confirmação da conferência", assunto="Detalhes da sua hospedagem",
        corpo="Olá, {primeiro_nome}. Confira os dados da sua estadia.", criado_por=c.usuario,
    )
    CampanhaEmail.objects.create(
        nome="Campanha da conferência", assunto="Estadia em família e experiências na pousada",
        corpo="Olá, {primeiro_nome}.", criado_por=c.usuario,
    )
    CampanhaMarketing.objects.create(
        nome="Planejamento da conferência visual", solicitante=c.usuario,
        inicio=c.hoje, fim=c.hoje + timedelta(days=20), verba_prevista="1450.50",
    )
    turno = Turno.objects.create(nome="Manhã da conferência", setor="governanca", inicio=time(8), fim=time(16))
    Atribuicao.objects.create(turno=turno, funcionario=c.funcionario, data=c.hoje, criado_por=c.usuario)
    c.comanda = restaurante.abrir_comanda(c.usuario, c.cozinha, mesa=Mesa.objects.create(nome="Mesa QA"))
    restaurante.adicionar_item(c.comanda, c.produto, "1", c.usuario)
    return c
