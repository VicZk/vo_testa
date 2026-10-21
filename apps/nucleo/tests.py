from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from . import logbook_services
from .models import EntradaLogbook, ModuloContratado, modulo_ativo, modulos_ativos
from .modulos import Modulo

Usuario = get_user_model()


class AutenticacaoTests(TestCase):
    def test_pagina_de_login_carrega(self):
        resposta = self.client.get(reverse("login"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Pousada Vô Testa")

    def test_dashboard_exige_login(self):
        resposta = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            resposta, f"{reverse('login')}?next={reverse('dashboard')}"
        )

    def test_dashboard_carrega_para_usuario_logado(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.get(reverse("dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Visão geral")

    def test_login_e_logout_funcionam(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        resposta = self.client.post(
            reverse("login"),
            {"username": "recepcao", "password": "senha-forte-123"},
        )
        self.assertRedirects(resposta, reverse("dashboard"))
        resposta = self.client.post(reverse("logout"))
        self.assertRedirects(resposta, reverse("login"))


class RegistroDeModulosTests(TestCase):
    def test_seed_ativou_os_modulos_da_fase_1(self):
        # 11 da fase 1 + Auditoria + Relatórios + Comercial = 14, menos Frigobar
        # (removido) = 13, + Marketing (novo módulo) = 14.
        self.assertEqual(ModuloContratado.objects.filter(ativo=True).count(), 14)
        self.assertTrue(modulo_ativo(Modulo.RESERVAS))
        self.assertTrue(modulo_ativo(Modulo.LOJA))
        self.assertTrue(modulo_ativo(Modulo.AUDITORIA))
        self.assertTrue(modulo_ativo(Modulo.RELATORIOS))
        self.assertTrue(modulo_ativo(Modulo.COMERCIAL))
        self.assertTrue(modulo_ativo(Modulo.MARKETING))
        self.assertFalse(modulo_ativo(Modulo.FISCAL))  # fase 2, não contratado

    def test_modulos_ativos_respeita_ordem_do_catalogo(self):
        ativos = modulos_ativos()
        self.assertEqual(ativos[0], Modulo.RESERVAS)
        self.assertIn(Modulo.APPSITE, ativos)

    def test_ativacao_valida_dependencias(self):
        # Loja depende de Estoque: desativando Estoque, Loja não pode ser ativada.
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        loja = ModuloContratado.objects.get(codigo=Modulo.LOJA)
        with self.assertRaises(ValidationError):
            loja.full_clean()

    def test_menu_so_aparece_para_usuario_logado(self):
        resposta = self.client.get(reverse("login"))
        self.assertNotContains(resposta, "nav-item")


class PermissoesPorModuloTests(TestCase):
    def setUp(self):
        self.funcionaria = Usuario.objects.create_user(
            username="loja", password="senha-forte-123"
        )
        self.funcionaria.modulos.add(
            ModuloContratado.objects.get(codigo=Modulo.LOJA)
        )
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )

    def test_usuario_acessa_somente_modulos_atribuidos(self):
        self.assertTrue(self.funcionaria.pode_acessar(Modulo.LOJA))
        self.assertFalse(self.funcionaria.pode_acessar(Modulo.RESERVAS))

    def test_superusuario_acessa_todos_os_modulos_ativos(self):
        self.assertTrue(self.gerente.pode_acessar(Modulo.RESERVAS))
        self.assertTrue(self.gerente.pode_acessar(Modulo.LOJA))

    def test_modulo_inativo_nega_acesso_mesmo_atribuido(self):
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.assertFalse(self.funcionaria.pode_acessar(Modulo.LOJA))
        self.assertFalse(self.gerente.pode_acessar(Modulo.LOJA))

    def test_menu_filtra_por_permissao_do_usuario(self):
        self.client.login(username="loja", password="senha-forte-123")
        resposta = self.client.get(reverse("dashboard"))
        self.assertContains(resposta, "Loja")
        self.assertNotContains(resposta, "Governança")

    def test_decorator_requer_modulo(self):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404, HttpResponse
        from django.test import RequestFactory

        from .permissoes import requer_modulo

        @requer_modulo(Modulo.LOJA)
        def view_loja(request):
            return HttpResponse("ok")

        @requer_modulo(Modulo.FISCAL)  # não contratado
        def view_fiscal(request):
            return HttpResponse("ok")

        fabrica = RequestFactory()

        pedido = fabrica.get("/loja/")
        pedido.user = self.funcionaria
        self.assertEqual(view_loja(pedido).status_code, 200)

        pedido = fabrica.get("/loja/")
        pedido.user = Usuario.objects.create_user(
            username="sem-acesso", password="senha-forte-123"
        )
        with self.assertRaises(PermissionDenied):
            view_loja(pedido)

        pedido = fabrica.get("/fiscal/")
        pedido.user = self.gerente
        with self.assertRaises(Http404):
            view_fiscal(pedido)


# ============================================================
# Núcleo completo: cadastros, financeiro/caixa, logbook
# ============================================================

from datetime import date, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from .models import (  # noqa: E402
    UH,
    CategoriaFinanceira,
    ContaPagarReceber,
    FormaPagamento,
    Hospede,
    LancamentoFinanceiro,
    MovimentoCaixa,
    Pessoa,
    SessaoCaixa,
    Temporada,
    TipoUH,
    TrilhaAuditoria,
    estornar_movimento,
)


class CadastrosTests(TestCase):
    def test_pessoa_com_especializacao_hospede(self):
        pessoa = Pessoa.objects.create(nome="Maria Silva", documento="111.222.333-44")
        Hospede.objects.create(pessoa=pessoa, preferencias="Quarto silencioso")
        self.assertEqual(pessoa.papeis, ["Hóspede"])

    def test_uh_exige_numero_unico(self):
        tipo = TipoUH.objects.create(nome="Standard", tarifa_base=Decimal("250.00"))
        UH.objects.create(numero="01", tipo=tipo)
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            UH.objects.create(numero="01", tipo=tipo)

    def test_temporada_rejeita_fim_antes_do_inicio(self):
        temporada = Temporada(
            nome="Réveillon",
            classificacao=Temporada.Classificacao.SUPER_ALTA,
            inicio=date(2026, 12, 28),
            fim=date(2026, 12, 20),
        )
        with self.assertRaises(ValidationError):
            temporada.full_clean()


class CaixaTestsBase(TestCase):
    def setUp(self):
        self.operador = Usuario.objects.create_user(
            username="recepcao", password="senha-forte-123"
        )
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.pix = FormaPagamento.objects.get(tipo="pix")
        self.sessao = SessaoCaixa.objects.create(
            operador=self.operador, modulo="nucleo", fundo_troco=Decimal("100.00")
        )

    def receber(self, valor, forma=None, descricao="Diária"):
        movimento = MovimentoCaixa(
            sessao=self.sessao,
            tipo=MovimentoCaixa.Tipo.RECEBIMENTO,
            forma_pagamento=forma or self.dinheiro,
            valor=Decimal(valor),
            descricao=descricao,
            criado_por=self.operador,
        )
        movimento.save()
        return movimento


class RegrasDeCaixaTests(CaixaTestsBase):
    def test_apenas_uma_sessao_aberta_por_operador_e_modulo(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            SessaoCaixa.objects.create(operador=self.operador, modulo="nucleo")

    def test_movimento_e_imutavel(self):
        movimento = self.receber("50.00")
        movimento.valor = Decimal("60.00")
        with self.assertRaises(ValidationError):
            movimento.save()
        with self.assertRaises(ValidationError):
            movimento.delete()

    def test_recebimento_guarda_autorizacao_nsu(self):
        from apps.nucleo.models import receber_no_caixa

        mov = receber_no_caixa(
            self.operador, self.pix, Decimal("150.00"),
            "Cartão na maquininha", autorizacao="  NSU-998877  ", modulo="nucleo")
        self.assertEqual(mov.autorizacao, "NSU-998877")  # normaliza (strip)
        # opcional: recebimento sem NSU fica em branco
        mov2 = receber_no_caixa(
            self.operador, self.dinheiro, Decimal("10.00"), "Dinheiro", modulo="nucleo")
        self.assertEqual(mov2.autorizacao, "")

    def test_movimento_exige_sessao_aberta(self):
        self.sessao.fechar(Decimal("150.00"), self.operador)
        with self.assertRaises(ValidationError):
            self.receber("10.00")

    def test_esperado_em_dinheiro_considera_apenas_dinheiro(self):
        self.receber("200.00")                      # dinheiro
        self.receber("300.00", forma=self.pix)      # pix não entra na gaveta
        MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.SANGRIA,
            valor=Decimal("80.00"), descricao="Sangria cofre",
            criado_por=self.operador,
        ).save()
        MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.REFORCO,
            valor=Decimal("30.00"), descricao="Reforço de troco",
            criado_por=self.operador,
        ).save()
        # 100 fundo + 200 dinheiro + 30 reforço − 80 sangria = 250
        self.assertEqual(self.sessao.esperado_em_dinheiro(), Decimal("250.00"))

    def test_fechamento_cego_aponta_diferenca(self):
        self.receber("200.00")
        self.sessao.fechar(Decimal("290.00"), self.operador)  # esperado: 300
        self.assertEqual(self.sessao.diferenca, Decimal("-10.00"))
        self.assertEqual(self.sessao.status, SessaoCaixa.Status.FECHADA)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="fechamento_caixa").exists()
        )

    def test_estorno_exige_motivo_e_nao_excede_original(self):
        movimento = self.receber("100.00")
        with self.assertRaises(ValidationError):
            estornar_movimento(movimento, self.sessao, self.gerente, motivo="")
        estornar_movimento(
            movimento, self.sessao, self.gerente, "Cobrança duplicada",
            valor=Decimal("60.00"),
        )
        with self.assertRaises(ValidationError):
            estornar_movimento(
                movimento, self.sessao, self.gerente, "De novo",
                valor=Decimal("50.00"),  # 60 + 50 > 100
            )
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="estorno").exists())

    def test_so_recebimento_pode_ser_estornado(self):
        sangria = MovimentoCaixa(
            sessao=self.sessao, tipo=MovimentoCaixa.Tipo.SANGRIA,
            valor=Decimal("10.00"), descricao="Sangria",
            criado_por=self.operador,
        )
        sangria.save()
        with self.assertRaises(ValidationError):
            estornar_movimento(sangria, self.sessao, self.gerente, "Teste")

    def test_reabertura_exige_motivo_e_audita(self):
        self.sessao.fechar(Decimal("100.00"), self.operador)
        with self.assertRaises(ValidationError):
            self.sessao.reabrir(self.gerente, motivo="  ")
        self.sessao.reabrir(self.gerente, motivo="Faltou lançar um recebimento")
        self.assertTrue(self.sessao.aberta)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="reabertura_caixa").exists()
        )

    def test_view_estorno_exige_gerencia(self):
        movimento = self.receber("50.00")
        self.client.login(username="recepcao", password="senha-forte-123")
        resposta = self.client.post(
            reverse("estorno", args=[movimento.pk]),
            {"valor": "50.00", "motivo": "Tentativa sem permissão"},
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(movimento.estornos.count(), 0)

    def test_fluxo_caixa_pelas_views(self):
        outro = Usuario.objects.create_user(
            username="loja", password="senha-forte-123"
        )
        outro.areas = ["financeiro"]
        outro.save()
        self.client.login(username="loja", password="senha-forte-123")
        self.client.post(
            reverse("caixa_abrir"), {"modulo": "nucleo", "fundo_troco": "50.00"}
        )
        sessao = SessaoCaixa.objects.get(operador=outro)
        self.client.post(
            reverse("caixa_movimento"),
            {
                "tipo": "recebimento",
                "forma_pagamento": self.dinheiro.pk,
                "valor": "70.00",
                "parcelas": "1",
                "descricao": "Venda balcão",
            },
        )
        self.client.post(
            reverse("caixa_fechar"), {"valor_contado": "120.00", "observacoes": ""}
        )
        sessao.refresh_from_db()
        self.assertEqual(sessao.status, SessaoCaixa.Status.FECHADA)
        self.assertEqual(sessao.diferenca, Decimal("0.00"))

    def test_dois_caixas_abertos_opera_o_modulo_escolhido(self):
        # Operador com 2 caixas abertos (reservas + loja): o movimento vai pro caixa
        # do módulo escolhido — não dá 500 nem lança no caixa errado.
        u = Usuario.objects.create_user(username="multi", password="senha-forte-123")
        u.areas = ["financeiro"]
        u.save()
        self.client.login(username="multi", password="senha-forte-123")
        cx_res = SessaoCaixa.objects.create(
            operador=u, modulo="reservas", fundo_troco=Decimal("0"))
        cx_loja = SessaoCaixa.objects.create(
            operador=u, modulo="loja", fundo_troco=Decimal("0"))
        r = self.client.post(reverse("caixa_movimento"), {
            "modulo": "loja", "tipo": "recebimento", "forma_pagamento": self.dinheiro.pk,
            "valor": "25.00", "parcelas": "1", "descricao": "Venda"})
        self.assertEqual(r.status_code, 302)          # não 500
        self.assertEqual(cx_loja.movimentos.count(), 1)   # foi pro caixa certo
        self.assertEqual(cx_res.movimentos.count(), 0)
        # Sem informar o módulo com 2 abertos → pede seleção, não lança (e não 500).
        r2 = self.client.post(reverse("caixa_movimento"), {
            "tipo": "recebimento", "forma_pagamento": self.dinheiro.pk,
            "valor": "9.00", "parcelas": "1", "descricao": "x"})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(cx_loja.movimentos.count(), 1)


class AreaCaixaTests(TestCase):
    """Operar o próprio caixa (área 'caixa') é separado da gestão financeira."""

    def setUp(self):
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def _user(self, username, areas):
        u = Usuario.objects.create_user(username=username, password="senha-forte-123")
        u.areas = areas
        u.save()
        self.client.force_login(u)
        return u

    def test_area_caixa_abre_o_proprio_caixa(self):
        u = self._user("atendente", ["caixa"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 200)
        self.client.post(
            reverse("caixa_abrir"), {"modulo": "nucleo", "fundo_troco": "50.00"}
        )
        self.assertTrue(SessaoCaixa.objects.filter(operador=u).exists())

    def test_sem_caixa_nem_financeiro_bloqueia(self):
        self._user("semacesso", ["logbook"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 403)

    def test_financeiro_ainda_acessa_caixa(self):
        self._user("gestor", ["financeiro"])
        self.assertEqual(self.client.get(reverse("caixa")).status_code, 200)

    def test_caixa_nao_da_acesso_a_gestao_financeira(self):
        self._user("atendente", ["caixa"])
        self.assertEqual(self.client.get(reverse("contas")).status_code, 403)
        self.assertEqual(self.client.get(reverse("lancamentos")).status_code, 403)
        # Baixar título (escrita financeira) exige a área Financeiro, não só login.
        self.assertEqual(
            self.client.post(reverse("conta_baixar", args=[1])).status_code, 403)


class FinanceiroTests(CaixaTestsBase):
    def setUp(self):
        super().setUp()
        self.categoria_despesa = CategoriaFinanceira.objects.create(
            nome="Insumos", tipo=CategoriaFinanceira.Tipo.DESPESA
        )
        self.categoria_receita = CategoriaFinanceira.objects.create(
            nome="Hospedagem", tipo=CategoriaFinanceira.Tipo.RECEITA
        )

    def test_lancamento_valida_tipo_da_categoria(self):
        lancamento = LancamentoFinanceiro(
            tipo="receita", categoria=self.categoria_despesa,
            descricao="Errado", valor=Decimal("10.00"), criado_por=self.operador,
        )
        with self.assertRaises(ValidationError):
            lancamento.full_clean()

    def test_baixa_de_conta_gera_lancamento_e_audita(self):
        fornecedor = Pessoa.objects.create(nome="Hortifrúti do Vale")
        conta = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR,
            pessoa=fornecedor,
            categoria=self.categoria_despesa,
            descricao="Frutas da semana",
            valor=Decimal("340.00"),
            vencimento=date.today(),
        )
        conta.baixar(self.operador)
        self.assertEqual(conta.status, ContaPagarReceber.Status.BAIXADA)
        self.assertIsNotNone(conta.lancamento)
        self.assertEqual(conta.lancamento.tipo, "despesa")
        self.assertEqual(conta.lancamento.valor, Decimal("340.00"))
        with self.assertRaises(ValidationError):
            conta.baixar(self.operador)  # não baixa duas vezes
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="baixa_conta").exists())

    def test_conta_vencida(self):
        conta = ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR,
            categoria=self.categoria_despesa,
            descricao="Atrasada",
            valor=Decimal("10.00"),
            vencimento=date.today() - timedelta(days=1),
        )
        self.assertTrue(conta.vencida)


class LogbookTests(TestCase):
    def test_registro_pela_view(self):
        u = Usuario.objects.create_user(username="turno", password="senha-forte-123")
        u.areas = ["logbook"]
        u.save()
        self.client.login(username="turno", password="senha-forte-123")
        resposta = self.client.post(
            reverse("logbook"),
            {"texto": "Hóspede do 12 pediu late check-out.", "importante": "on"},
        )
        self.assertRedirects(resposta, reverse("logbook"))
        resposta = self.client.get(reverse("logbook"))
        self.assertContains(resposta, "late check-out")


class CadastroRapidoTests(TestCase):
    def setUp(self):
        Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        self.client.login(username="recepcao", password="senha-forte-123")

    def test_cria_hospede_e_devolve_json(self):
        resposta = self.client.post(
            reverse("pessoa_nova_rapida"),
            {"nome": "Hóspede Rápido", "documento": "529.982.247-25",
             "telefone": "(49) 99999-0000"},
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        pessoa = Pessoa.objects.get(pk=dados["id"])
        self.assertEqual(dados["nome"], "Hóspede Rápido")
        self.assertTrue(hasattr(pessoa, "hospede"))

    def test_nome_obrigatorio(self):
        resposta = self.client.post(reverse("pessoa_nova_rapida"), {"nome": "  "})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("erro", resposta.json())

    def test_exige_login(self):
        self.client.logout()
        resposta = self.client.post(reverse("pessoa_nova_rapida"), {"nome": "X"})
        self.assertEqual(resposta.status_code, 302)


class TabelaPessoasTests(TestCase):
    def setUp(self):
        from apps.nucleo.models import Agencia, Fornecedor, Hospede
        u = Usuario.objects.create_user(username="recepcao", password="senha-forte-123")
        u.areas = ["pessoas"]
        u.save()
        self.client.login(username="recepcao", password="senha-forte-123")
        h = Pessoa.objects.create(nome="Hóspede Um")
        Hospede.objects.create(pessoa=h)
        f = Pessoa.objects.create(nome="Fornecedor Um", tipo=Pessoa.Tipo.JURIDICA)
        Fornecedor.objects.create(pessoa=f)
        a = Pessoa.objects.create(nome="Agência Um", tipo=Pessoa.Tipo.JURIDICA)
        Agencia.objects.create(pessoa=a)
        Pessoa.objects.create(nome="Avulso Um")  # sem papel

    def test_filtro_por_papel(self):
        r = self.client.get(reverse("pessoas"), {"papel": "agencias"})
        self.assertContains(r, "Agência Um")
        self.assertNotContains(r, "Fornecedor Um")

    def test_filtro_avulsos(self):
        r = self.client.get(reverse("pessoas"), {"papel": "avulsos"})
        self.assertContains(r, "Avulso Um")
        self.assertNotContains(r, "Hóspede Um")

    def test_sigla_tipo(self):
        self.assertEqual(Pessoa.objects.get(nome="Fornecedor Um").sigla_tipo, "PJ")
        self.assertEqual(Pessoa.objects.get(nome="Hóspede Um").sigla_tipo, "PF")


class CentralModulosTests(TestCase):
    def setUp(self):
        self.gerente = Usuario.objects.create_superuser(
            username="gerente", password="senha-forte-123"
        )
        self.operador = Usuario.objects.create_user(
            username="op", password="senha-forte-123"
        )

    def test_exige_gerencia(self):
        self.client.login(username="op", password="senha-forte-123")
        self.assertEqual(
            self.client.get(reverse("modulos_central")).status_code, 403
        )

    def test_carrega_para_gerencia(self):
        self.client.login(username="gerente", password="senha-forte-123")
        r = self.client.get(reverse("modulos_central"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Central de Módulos")

    def test_ativar_modulo_disponivel(self):
        self.client.login(username="gerente", password="senha-forte-123")
        self.assertFalse(modulo_ativo(Modulo.FISCAL))
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.FISCAL, "acao": "ativar"},
        )
        self.assertTrue(modulo_ativo(Modulo.FISCAL))

    def test_ativar_sem_dependencia_falha(self):
        # Loja exige Estoque: desativa Estoque no banco e tenta ativar Loja isolada
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.client.login(username="gerente", password="senha-forte-123")
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.LOJA, "acao": "ativar"},
        )
        self.assertFalse(modulo_ativo(Modulo.LOJA))

    def test_desativar_bloqueado_por_dependente(self):
        # Estoque tem Loja ativa dependendo dele → não pode desativar
        self.client.login(username="gerente", password="senha-forte-123")
        self.client.post(
            reverse("modulos_central"),
            {"codigo": Modulo.ESTOQUE, "acao": "desativar"},
        )
        self.assertTrue(modulo_ativo(Modulo.ESTOQUE))


class MoedaFiltroTests(TestCase):
    """Filtro de moeda único do sistema (apps/nucleo/templatetags/moeda.py)."""

    def _fmt(self, valor):
        from apps.nucleo.templatetags.moeda import intcomma_brl
        return intcomma_brl(valor)

    def test_zero(self):
        self.assertEqual(self._fmt(0), "R$ 0,00")

    def test_milhar(self):
        self.assertEqual(self._fmt(1600), "R$ 1.600,00")

    def test_milhao_com_centavos(self):
        self.assertEqual(self._fmt(Decimal("1234567.5")), "R$ 1.234.567,50")

    def test_negativo(self):
        self.assertEqual(self._fmt(Decimal("-67.5")), "-R$ 67,50")

    def test_none_e_vazio(self):
        self.assertEqual(self._fmt(None), "R$ 0,00")
        self.assertEqual(self._fmt(""), "R$ 0,00")

    def test_invalido(self):
        self.assertEqual(self._fmt("abc"), "R$ 0,00")


class EstruturaCamasTests(TestCase):
    """Capacidade derivada da unidade e frase de camas gerada (Passo 2).

    Os 24 quartos vêm de um seed manual (não de migração), então o teste cria a
    estrutura e roda o seeder de camas para valer sobre dados controlados.
    """

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        from apps.nucleo.management.commands.popular_camas import semear_camas
        from apps.nucleo.models import UH, TipoUH

        # As unidades day use (DAY-01..08) já vêm da migração 0015; aqui criamos
        # só os 24 quartos de pernoite (que em produção vêm do seed manual).
        hosp = TipoUH.objects.create(nome="Hospedagem Teste", tarifa_base=Decimal("250"))
        for i in range(1, 25):
            UH.objects.create(numero=f"Quarto {i:02d}", tipo=hosp)
        semear_camas()

    def _uh(self, numero):
        from apps.nucleo.models import UH
        return UH.objects.get(numero=numero)

    def test_lotacao_total_bate_118_e_131(self):
        from apps.nucleo.estrutura import capacidade
        from apps.nucleo.models import UH
        hosp = UH.objects.filter(tipo__modalidade="hospedagem")
        self.assertEqual(sum(capacidade(u)["maxima"] for u in hosp), 118)
        self.assertEqual(sum(capacidade(u)["maxima_criancas"] for u in hosp), 131)
        self.assertEqual(sum(capacidade(u)["fixa"] for u in hosp), 70)
        self.assertEqual(sum(capacidade(u)["extras"] for u in hosp), 35)

    def test_dois_comodos_com_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 17"))
        self.assertEqual(cap["maxima"], 7)
        self.assertEqual(cap["maxima_criancas"], 8)

    def test_um_comodo_com_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 09"))
        self.assertEqual(cap["maxima"], 4)
        self.assertEqual(cap["maxima_criancas"], 5)

    def test_um_comodo_sem_sofa(self):
        from apps.nucleo.estrutura import capacidade
        cap = capacidade(self._uh("Quarto 03"))
        self.assertEqual(cap["maxima"], 3)
        self.assertEqual(cap["maxima_criancas"], 3)

    def test_day_use_zero_e_sem_camas(self):
        from apps.nucleo.estrutura import capacidade, descricao_camas
        from apps.nucleo.models import UH
        day = UH.objects.filter(tipo__modalidade="day_use").first()
        self.assertEqual(capacidade(day)["maxima"], 0)
        self.assertEqual(
            descricao_camas(day), "Sem pernoite · acesso à estrutura no período"
        )

    def test_descricao_dois_comodos_exata(self):
        from apps.nucleo.estrutura import descricao_camas
        self.assertEqual(
            descricao_camas(self._uh("Quarto 17")),
            "Quarto 1 com 1 cama de casal · Quarto 2 com 1 cama de casal · "
            "sofá-cama para 1 adulto ou 2 crianças até 15 anos · "
            "até 2 colchões de solteiro extras",
        )

    def test_descricao_um_comodo_omite_prefixo(self):
        from apps.nucleo.estrutura import descricao_camas
        self.assertEqual(
            descricao_camas(self._uh("Quarto 03")),
            "1 cama de casal · até 1 colchão de solteiro extra",
        )

    def test_faixa_do_tipo_mostra_intervalo(self):
        """Quando as unidades do tipo variam, a faixa é 'N a M', não 'até M'."""
        from decimal import Decimal

        from apps.nucleo.estrutura import faixa_do_tipo
        from apps.nucleo.models import UH, ConfiguracaoUH, PosicaoCama, TipoUH
        tipo = TipoUH.objects.create(nome="Teste Faixa", tarifa_base=Decimal("200"))
        pequena = UH.objects.create(numero="TST-P", tipo=tipo)
        PosicaoCama.objects.create(uh=pequena, nome="Quarto", ordem=0)
        grande = UH.objects.create(numero="TST-G", tipo=tipo)
        PosicaoCama.objects.create(uh=grande, nome="Quarto 1", ordem=0)
        PosicaoCama.objects.create(uh=grande, nome="Quarto 2", ordem=1)
        ConfiguracaoUH.objects.create(uh=grande, tem_sofa_cama=True, max_colchoes_extras=2)
        self.assertEqual(faixa_do_tipo(tipo), "2 a 8 pessoas")


class EquipeAcessosTests(TestCase):
    """Equipe & Acessos: gating por área, gestão de usuários e travas."""

    def setUp(self):
        self.dono = Usuario.objects.create_superuser(
            username="dono", password="senha-forte-123"
        )
        self.op = Usuario.objects.create_user(
            username="operador", password="senha-forte-123"
        )

    def test_pode_area(self):
        self.assertFalse(self.op.pode_area("quartos"))
        self.op.areas = ["quartos"]
        self.assertTrue(self.op.pode_area("quartos"))
        self.assertTrue(self.dono.pode_area("financeiro"))  # super bypassa

    def test_estrutura_gateada_por_area(self):
        self.client.force_login(self.op)
        self.assertEqual(self.client.get(reverse("estrutura")).status_code, 403)
        self.op.areas = ["quartos"]
        self.op.save()
        self.assertEqual(self.client.get(reverse("estrutura")).status_code, 200)

    # A gestão de acesso migrou para a ficha do Funcionário — coberta em
    # FuncionariosTests (conceder acesso, salário só-gerência, self-protection).


class AuditoriaAutomaticaTests(TestCase):
    """Piso garantido: escrita em model de negócio com usuário no contexto vira trilha."""

    def setUp(self):
        from apps.nucleo import audit
        self.audit = audit
        self.user = Usuario.objects.create_user(username="rec", password="x")

    def tearDown(self):
        self.audit.limpar_contexto()

    def _pessoa(self):
        from apps.nucleo.models import Pessoa
        return Pessoa

    def _trilha(self, **f):
        from apps.nucleo.models import TrilhaAuditoria
        return TrilhaAuditoria.objects.filter(**f)

    def test_sem_usuario_no_contexto_nao_registra(self):
        self.audit.limpar_contexto()
        p = self._pessoa().objects.create(nome="Anônimo")
        self.assertFalse(self._trilha(alvo="Pessoa", alvo_id=str(p.pk)).exists())

    def test_criar_registra_com_usuario_e_ip(self):
        self.audit.definir_contexto(self.user, "200.1.2.3")
        p = self._pessoa().objects.create(nome="Fulano")
        t = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="criar").first()
        self.assertIsNotNone(t)
        self.assertEqual(t.usuario, self.user)
        self.assertEqual(t.ip, "200.1.2.3")
        self.assertIn("valores", t.detalhe)

    def test_editar_registra_diff(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        p.nome = "Beltrano"
        p.save()
        t = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="editar").first()
        self.assertIsNotNone(t)
        self.assertEqual(t.detalhe["alteracoes"]["nome"], ["Fulano", "Beltrano"])

    def test_save_sem_mudanca_nao_registra_edicao(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        antes = self._trilha(alvo="Pessoa", acao="editar").count()
        p.save()  # nenhum campo mudou
        self.assertEqual(self._trilha(alvo="Pessoa", acao="editar").count(), antes)

    def test_excluir_registra(self):
        self.audit.definir_contexto(self.user)
        p = self._pessoa().objects.create(nome="Fulano")
        pk = p.pk
        p.delete()
        self.assertTrue(
            self._trilha(alvo="Pessoa", alvo_id=str(pk), acao="excluir").exists()
        )

    def test_middleware_define_e_limpa_contexto(self):
        from django.test import RequestFactory
        capturado = {}

        def get_response(req):
            capturado["u"] = self.audit.usuario_atual()
            capturado["ip"] = self.audit.ip_atual()
            return "ok"

        req = RequestFactory().get("/", REMOTE_ADDR="9.9.9.9")
        req.user = self.user
        self.audit.AuditContextMiddleware(get_response)(req)
        self.assertEqual(capturado["u"], self.user)
        self.assertEqual(capturado["ip"], "9.9.9.9")
        self.assertIsNone(self.audit.usuario_atual())  # limpou depois da requisição

    def test_usuario_anonimo_nao_vira_contexto(self):
        from django.contrib.auth.models import AnonymousUser
        self.audit.definir_contexto(AnonymousUser(), "1.1.1.1")
        self.assertIsNone(self.audit.usuario_atual())

    def test_login_registra_na_trilha(self):
        self.user.set_password("senha-forte-123")
        self.user.save()
        self.client.login(username="rec", password="senha-forte-123")
        t = self._trilha(alvo="Usuario", acao="login", usuario=self.user).first()
        self.assertIsNotNone(t)

    def test_logout_registra_na_trilha(self):
        self.user.set_password("senha-forte-123")
        self.user.save()
        self.client.login(username="rec", password="senha-forte-123")
        self.client.logout()
        self.assertTrue(
            self._trilha(alvo="Usuario", acao="logout", usuario=self.user).exists()
        )


class FuncionariosTests(TestCase):
    """Onda 1: tela de Funcionários (RH) + acesso derivando do funcionário."""

    def setUp(self):
        from apps.nucleo.models import Funcionario, Pessoa
        self.Funcionario = Funcionario
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        p = Pessoa.objects.create(nome="Fulano")
        self.func = Funcionario.objects.create(pessoa=p, cargo="Recepcionista")

    def test_lista_exige_area(self):
        op = Usuario.objects.create_user(username="op", password="x")
        self.client.force_login(op)
        self.assertEqual(self.client.get(reverse("funcionarios")).status_code, 403)
        op.areas = ["funcionarios"]
        op.save()
        self.assertEqual(self.client.get(reverse("funcionarios")).status_code, 200)

    def test_novo_cria_pessoa_e_funcionario(self):
        self.client.force_login(self.dono)
        n = self.Funcionario.objects.count()
        self.client.post(reverse("funcionario_novo"), {"nome": "Nova Camareira", "cargo": "Camareira"})
        self.assertEqual(self.Funcionario.objects.count(), n + 1)
        self.assertTrue(self.Funcionario.objects.filter(pessoa__nome="Nova Camareira").exists())

    def test_gerencia_edita_rh_e_salario(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano da Silva", "cargo": "Gerente", "setor": "Recepção",
            "turno": "manha", "carga_semanal": "40", "salario": "2.400,00",
        })
        self.func.refresh_from_db()
        self.assertEqual(self.func.cargo, "Gerente")
        self.assertEqual(self.func.turno, "manha")
        self.assertEqual(str(self.func.salario), "2400.00")
        self.assertEqual(self.func.pessoa.nome, "Fulano da Silva")

    def test_nao_gerencia_nao_ve_nem_edita_salario(self):
        op = Usuario.objects.create_user(username="rh", password="x")
        op.areas = ["funcionarios"]
        op.save()
        self.client.force_login(op)
        r = self.client.get(reverse("funcionario_editar", args=[self.func.pk]))
        self.assertNotContains(r, "Salário base")
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista", "salario": "9999",
        })
        self.func.refresh_from_db()
        self.assertIsNone(self.func.salario)  # ignorado — não é gerência

    def test_gerencia_cria_login_e_concede_acesso(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista",
            "username": "fulano", "password": "senha-forte-123",
            "areas": ["caixa", "logbook"],
        })
        self.func.refresh_from_db()
        self.assertIsNotNone(self.func.usuario)
        self.assertEqual(self.func.usuario.username, "fulano")
        self.assertIn("caixa", self.func.usuario.areas)

    def test_conceder_acesso_entra_na_trilha(self):
        # Conceder MÓDULO é M2M — não entra na trilha por signal; registramos à mão.
        from apps.nucleo.models import TrilhaAuditoria
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista",
            "username": "fulano3", "password": "senha-forte-123",
            "modulos": ["reservas"], "areas": ["caixa"],
        })
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="alterar_acesso").exists())

    def test_nao_rebaixa_a_si_mesmo(self):
        from apps.nucleo.models import Funcionario, Pessoa
        ger = Usuario.objects.create_user(username="ger", password="x", is_staff=True)
        ger.areas = ["funcionarios"]
        ger.save()
        fg = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Ger"), cargo="Gerente", usuario=ger)
        self.client.force_login(ger)
        self.client.post(reverse("funcionario_editar", args=[fg.pk]), {
            "nome": "Ger", "cargo": "Gerente",  # sem 'gerente'/'ativo' — tentaria rebaixar
        })
        ger.refresh_from_db()
        self.assertTrue(ger.is_staff)   # não se rebaixou
        self.assertTrue(ger.is_active)  # não se desativou

    def test_area_invalida_descartada(self):
        self.client.force_login(self.dono)
        self.client.post(reverse("funcionario_editar", args=[self.func.pk]), {
            "nome": "Fulano", "cargo": "Recepcionista",
            "username": "ful", "password": "senha-forte-123",
            "areas": ["caixa", "hackeando"],
        })
        self.func.refresh_from_db()
        self.assertEqual(self.func.usuario.areas, ["caixa"])  # 'hackeando' fora


class PessoasPapelTests(TestCase):
    """Onda 2: telas separadas por papel (Hóspedes/Agências/Empresas)."""

    def setUp(self):
        from apps.nucleo.models import Agencia, Hospede, Pessoa
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        self.client.force_login(self.dono)
        self.ph = Pessoa.objects.create(nome="Hospede X")
        Hospede.objects.create(pessoa=self.ph)
        self.pa = Pessoa.objects.create(nome="Agencia CVC")
        Agencia.objects.create(pessoa=self.pa, categoria="agencia")
        self.pe = Pessoa.objects.create(nome="Empresa ACME")
        Agencia.objects.create(pessoa=self.pe, categoria="empresa")

    def test_papeis_distingue_agencia_empresa(self):
        self.assertIn("Agência", self.pa.papeis)
        self.assertIn("Empresa", self.pe.papeis)
        self.assertNotIn("Empresa", self.pa.papeis)

    def test_tela_hospedes_so_hospedes(self):
        b = self.client.get(reverse("hospedes")).content.decode()
        self.assertIn("Hospede X", b)
        self.assertNotIn("Agencia CVC", b)
        self.assertNotIn("Empresa ACME", b)

    def test_tela_agencias_so_agencias(self):
        b = self.client.get(reverse("agencias")).content.decode()
        self.assertIn("Agencia CVC", b)
        self.assertNotIn("Empresa ACME", b)

    def test_tela_empresas_so_empresas(self):
        b = self.client.get(reverse("empresas")).content.decode()
        self.assertIn("Empresa ACME", b)
        self.assertNotIn("Agencia CVC", b)

    def test_novo_empresa_cria_agencia_categoria_empresa(self):
        from apps.nucleo.models import Pessoa
        self.client.post(reverse("pessoa_nova") + "?papel=empresa", {
            "nome": "Nova Empresa Ltda", "tipo": "juridica",
            "eh_agencia": "on",
            "agencia-categoria": "empresa", "agencia-comissao_padrao": "0",
        })
        p = Pessoa.objects.filter(nome="Nova Empresa Ltda").first()
        self.assertIsNotNone(p)
        self.assertEqual(p.agencia.categoria, "empresa")

    def test_tela_fornecedores_so_fornecedores(self):
        from apps.nucleo.models import Fornecedor, Pessoa
        pf = Pessoa.objects.create(nome="Hortifruti Itá")
        Fornecedor.objects.create(pessoa=pf, atividade="hortifrúti")
        b = self.client.get(reverse("fornecedores")).content.decode()
        self.assertIn("Hortifruti Itá", b)
        self.assertNotIn("Hospede X", b)
        self.assertNotIn("Empresa ACME", b)

    def test_pessoa_form_nao_mexe_no_funcionario(self):
        from apps.nucleo.models import Funcionario, Pessoa
        p = Pessoa.objects.create(nome="Zé Funcionário")
        Funcionario.objects.create(pessoa=p, cargo="Jardineiro")
        # Salvar a pessoa (sem eh_funcionario, que nem existe mais) não apaga o funcionário.
        self.client.post(reverse("pessoa_editar", args=[p.pk]), {"nome": "Zé F.", "tipo": "fisica"})
        self.assertTrue(Funcionario.objects.filter(pessoa=p).exists())


class HistoricoFuncionarioTests(TestCase):
    """Fase 1: histórico do funcionário montado da trilha, gerência-only."""

    def setUp(self):
        from datetime import date

        from apps.nucleo.models import Funcionario, Pessoa
        self.dono = Usuario.objects.create_superuser(username="dono", password="senha-forte-123")
        p = Pessoa.objects.create(nome="Zé Cozinha")
        self.f = Funcionario.objects.create(pessoa=p, cargo="Cozinheiro", admissao=date(2024, 3, 12))

    def test_tempo_de_casa(self):
        from datetime import date

        from apps.nucleo.historico import tempo_de_casa
        self.assertIsNone(tempo_de_casa(None))
        self.assertIn("ano", tempo_de_casa(date(2024, 3, 12)))

    def test_progressao_le_da_trilha(self):
        from apps.nucleo.historico import progressao_salarial
        from apps.nucleo.models import TrilhaAuditoria
        TrilhaAuditoria.objects.create(
            usuario=self.dono, acao="editar", alvo="Funcionario", alvo_id=str(self.f.pk),
            detalhe={"alteracoes": {"salario": ["2000", "2200"]}},
        )
        prog = progressao_salarial(self.f)
        self.assertEqual(len(prog), 1)
        self.assertEqual(str(prog[0]["valor"]), "2200")

    def test_painel_historico_so_gerencia(self):
        self.client.force_login(self.dono)
        self.assertContains(self.client.get(reverse("funcionario_painel", args=[self.f.pk])), "Tempo de casa")
        op = Usuario.objects.create_user(username="rh", password="x")
        op.areas = ["funcionarios"]
        op.save()
        self.client.force_login(op)
        r = self.client.get(reverse("funcionario_painel", args=[self.f.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Tempo de casa")  # sem aba Histórico p/ não-gerência

    def test_ficha_nao_desativa_superusuario(self):
        from apps.nucleo.models import Funcionario, Pessoa
        dono2 = Usuario.objects.create_superuser(username="dono2", password="senha-forte-123")
        fs = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Dono2"), cargo="Dono", usuario=dono2)
        self.client.force_login(self.dono)  # outro gerente edita a ficha do superusuário
        self.client.post(reverse("funcionario_editar", args=[fs.pk]), {"nome": "Dono2", "cargo": "Dono"})
        dono2.refresh_from_db()
        self.assertTrue(dono2.is_active)   # superusuário não é desativado pela ficha
        self.assertTrue(dono2.is_superuser)

    def test_produtividade_conta_faxinas(self):
        from django.utils import timezone

        from apps.governanca.models import TarefaGovernanca
        from apps.nucleo.historico import produtividade
        from apps.nucleo.models import UH, TipoUH
        u = Usuario.objects.create_user(username="cam", password="x")
        self.f.usuario = u
        self.f.save()
        tipo = TipoUH.objects.create(nome="T", tarifa_base=Decimal("100"))
        uh = UH.objects.create(numero="Q1", tipo=tipo)
        TarefaGovernanca.objects.create(
            uh=uh, camareira=u, status="concluida", concluida_em=timezone.now()
        )
        hoje = timezone.localdate()
        prod = produtividade(self.f, hoje.replace(day=1), hoje)
        self.assertTrue(any("Faxina" in p["rotulo"] for p in prod))


class LogbookThreadTests(TestCase):
    """Recados do turno: thread + ciclo de vida (aberta → andamento → resolvida)."""

    def setUp(self):
        self.autor = Usuario.objects.create_user(
            username="ana", password="senha-forte-123"
        )
        self.colega = Usuario.objects.create_user(
            username="bru", password="senha-forte-123"
        )

    def test_registrar_ocorrencia_nasce_aberta(self):
        e = logbook_services.registrar_ocorrencia(self.autor, "vazamento no 12")
        self.assertEqual(e.status, EntradaLogbook.ABERTA)
        self.assertTrue(e.aberta)

    def test_ocorrencia_sem_texto_falha(self):
        with self.assertRaises(ValidationError):
            logbook_services.registrar_ocorrencia(self.autor, "   ")

    def test_resposta_de_outro_move_para_em_andamento(self):
        e = logbook_services.registrar_ocorrencia(self.autor, "conferir NF")
        logbook_services.comentar(self.colega, e, "já vi, cuido disso")
        e.refresh_from_db()
        self.assertEqual(e.status, EntradaLogbook.EM_ANDAMENTO)
        self.assertEqual(e.comentarios.count(), 1)

    def test_resposta_do_proprio_autor_nao_muda_status(self):
        e = logbook_services.registrar_ocorrencia(self.autor, "lembrete")
        logbook_services.comentar(self.autor, e, "complementando")
        e.refresh_from_db()
        self.assertEqual(e.status, EntradaLogbook.ABERTA)

    def test_qualquer_operador_resolve_e_registra_autoria(self):
        e = logbook_services.registrar_ocorrencia(self.autor, "ar do 15 com ruído")
        logbook_services.resolver(self.colega, e, "trocado o filtro")
        e.refresh_from_db()
        self.assertEqual(e.status, EntradaLogbook.RESOLVIDA)
        self.assertEqual(e.resolvida_por, self.colega)
        self.assertIsNotNone(e.resolvida_em)
        self.assertEqual(e.resolucao_nota, "trocado o filtro")

    def test_nao_comenta_em_resolvida(self):
        e = logbook_services.registrar_ocorrencia(self.autor, "x")
        logbook_services.resolver(self.colega, e)
        with self.assertRaises(ValidationError):
            logbook_services.comentar(self.autor, e, "reabrir?")

    def test_view_lista_so_pendencias_por_padrao(self):
        logbook_services.registrar_ocorrencia(self.autor, "pendente-aqui")
        fechada = logbook_services.registrar_ocorrencia(self.autor, "fechada-aqui")
        logbook_services.resolver(self.colega, fechada)
        gerente = Usuario.objects.create_superuser(
            username="ger", password="senha-forte-123"
        )
        self.client.force_login(gerente)
        resp = self.client.get(reverse("logbook"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pendente-aqui")
        # a fechada aparece na seção "resolvidas recentes" (filtro padrão mostra ambas)
        self.assertContains(resp, "Pendências abertas")

    def test_filtro_todas_mostra_historico_e_bate_contador(self):
        # 6 resolvidas > cap de 5 do filtro "abertas": só "todas" mostra todas.
        for i in range(6):
            fechada = logbook_services.registrar_ocorrencia(self.autor, f"fechada-{i}")
            logbook_services.resolver(self.colega, fechada)
        gerente = Usuario.objects.create_superuser(
            username="ger", password="senha-forte-123"
        )
        self.client.force_login(gerente)
        resp = self.client.get(reverse("logbook"), {"filtro": "todas"})
        self.assertEqual(resp.status_code, 200)
        # o contador "Todas" conta o histórico inteiro (6) e todas devem estar na página
        self.assertEqual(resp.context["contagens"]["todas"], 6)
        for i in range(6):
            self.assertContains(resp, f"fechada-{i}")

    def test_importantes_inclui_resolvidos_e_conta_todos(self):
        # #2: aba Importantes é histórico (aberto + resolvido), contador bate.
        logbook_services.registrar_ocorrencia(
            self.autor, "importante-pendente", importante=True
        )
        fechado = logbook_services.registrar_ocorrencia(
            self.autor, "importante-fechado", importante=True
        )
        logbook_services.resolver(self.colega, fechado)
        logbook_services.registrar_ocorrencia(self.autor, "comum-aberto")  # não importa
        gerente = Usuario.objects.create_superuser(
            username="ger", password="senha-forte-123"
        )
        self.client.force_login(gerente)
        resp = self.client.get(reverse("logbook"), {"filtro": "importantes"})
        self.assertEqual(resp.context["contagens"]["importantes"], 2)
        self.assertContains(resp, "importante-pendente")
        self.assertContains(resp, "importante-fechado")
        self.assertNotContains(resp, "comum-aberto")

    def test_resolver_concorrente_avisa_o_segundo(self):
        # #6: quem resolve depois é avisado; vale o 1º (autoria + nota).
        e = logbook_services.registrar_ocorrencia(self.autor, "trocar lâmpada")
        logbook_services.resolver(self.autor, e, "primeira nota")
        self.colega.areas = ["logbook"]
        self.colega.save()
        self.client.force_login(self.colega)
        resp = self.client.post(
            reverse("logbook_resolver", args=[e.pk]), {"nota": "segunda nota"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já havia sido resolvida por")
        e.refresh_from_db()
        self.assertEqual(e.resolvida_por, self.autor)
        self.assertEqual(e.resolucao_nota, "primeira nota")


class SalarioFlagETela1EtapaTests(TestCase):
    def setUp(self):
        self.gestor = Usuario.objects.create_superuser(username="chefia", password="senha-forte-123")

    def test_pode_ver_salario_por_flag(self):
        from apps.nucleo.areas import Area
        from apps.nucleo.permissoes import pode_ver_salario
        u = Usuario.objects.create_user(username="rh", password="senha-forte-123")
        self.assertFalse(pode_ver_salario(u))          # sem flag
        u.areas = [Area.REMUNERACAO]
        u.save()
        self.assertTrue(pode_ver_salario(u))            # com flag
        self.assertTrue(pode_ver_salario(self.gestor))  # superusuário bypassa

    def test_form_esconde_salario_sem_flag(self):
        from apps.nucleo.forms import FuncionarioForm
        self.assertNotIn("salario", FuncionarioForm(ver_salario=False).fields)
        self.assertIn("salario", FuncionarioForm(ver_salario=True).fields)

    def test_cadastro_em_uma_etapa_cria_tudo(self):
        from apps.nucleo.models import Funcionario
        self.client.force_login(self.gestor)
        resp = self.client.post(reverse("funcionario_novo"), {
            "nome": "Tião Silva", "cargo": "Manutenção", "setor": "Manutenção",
            "sexo": "M", "turno": "integral",
            "username": "tiao", "password": "senha-forte-123",
            "areas": ["remuneracao"], "modulos": [], "ativo": "on",
        })
        self.assertRedirects(resp, reverse("funcionarios"))
        f = Funcionario.objects.get(pessoa__nome="Tião Silva")
        self.assertEqual(f.setor, "Manutenção")
        self.assertEqual(f.sexo, "M")
        self.assertTrue(f.usuario.is_active)
        self.assertIn("remuneracao", f.usuario.areas)

    def test_cadastro_so_nome_obrigatorio(self):
        from apps.nucleo.models import Funcionario
        self.client.force_login(self.gestor)
        resp = self.client.post(reverse("funcionario_novo"), {"nome": "Só Nome"})
        self.assertRedirects(resp, reverse("funcionarios"))
        self.assertTrue(Funcionario.objects.filter(pessoa__nome="Só Nome").exists())


class SistemaHelpersTests(TestCase):
    """Helpers compartilhados extraídos no code-review (usuario_de_sistema, travar)."""

    def test_usuario_de_sistema_idempotente_e_nao_logavel(self):
        from apps.nucleo.sistema import usuario_de_sistema
        u1 = usuario_de_sistema("_bot", "Bot")
        u2 = usuario_de_sistema("_bot", "Bot")
        self.assertEqual(u1.pk, u2.pk)                 # idempotente (get_or_create)
        self.assertFalse(u1.has_usable_password())     # nunca é conta logável

    def test_travar_recarrega_a_instancia_passada(self):
        from django.db import transaction

        from apps.nucleo.models import Pessoa
        from apps.nucleo.sistema import travar
        p = Pessoa.objects.create(nome="Antigo")
        Pessoa.objects.filter(pk=p.pk).update(nome="Novo")  # muda no banco por fora
        with transaction.atomic():
            travar(p)
        self.assertEqual(p.nome, "Novo")               # a instância foi recarregada


class NomesQuartosTests(TestCase):
    """Sem nomes temáticos: os quartos exibem só o número ('Quarto N')."""

    def test_limpar_nomes_e_exibicao_por_numero(self):
        from decimal import Decimal

        from django.core.management import call_command

        from apps.nucleo.models import UH, TipoUH
        tipo = TipoUH.objects.create(nome="Padrão N", tarifa_base=Decimal("100"))
        uh = UH.objects.create(numero="Quarto 11", tipo=tipo,
                               nome_tematico="Celeiro do Moleiro")
        call_command("limpar_nomes_quartos", verbosity=0)
        uh.refresh_from_db()
        self.assertEqual(uh.nome_tematico, "")
        # `numero` já é "Quarto 11" — o fallback é o próprio número, sem duplicar "Quarto".
        self.assertEqual(uh.nome_tematico or uh.numero, "Quarto 11")


class ValidarTelefoneBRTests(TestCase):
    """Validador compartilhado de telefone (LPs = celular estrito; agência = fixo ok)."""

    def _val(self, v, **k):
        from apps.nucleo.validadores import validar_telefone_br
        return validar_telefone_br(v, **k)

    def test_celular_valido_normaliza(self):
        self.assertEqual(self._val("49999999999"), "(49) 99999-9999")
        self.assertEqual(self._val("(49) 99999-9999"), "(49) 99999-9999")
        self.assertEqual(self._val("5549999999999"), "(49) 99999-9999")  # tolera 55

    def test_celular_incompleto_rejeita(self):
        with self.assertRaises(ValidationError):
            self._val("4999999999")        # 10 dígitos
        with self.assertRaises(ValidationError):
            self._val("(49) 8999-9999")    # sem o 9

    def test_fixo_so_com_aceitar(self):
        with self.assertRaises(ValidationError):
            self._val("4933333333")                       # estrito recusa fixo
        self.assertEqual(self._val("4933333333", aceitar_fixo=True), "(49) 3333-3333")

    def test_ddd_invalido(self):
        with self.assertRaises(ValidationError):
            self._val("20999999999")       # DDD 20 não existe


class HealthzTests(TestCase):
    """O healthcheck do Railway só passa com o banco respondendo."""

    def test_ok_com_banco(self):
        r = self.client.get("/healthz/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"ok")

    def test_503_sem_banco(self):
        from unittest import mock

        with mock.patch("config.urls._banco_ok", return_value=False):
            r = self.client.get("/healthz/")
        self.assertEqual(r.status_code, 503)


class EstruturaInicialTests(TestCase):
    """`manage.py estrutura_inicial` monta a estrutura física num banco novo."""

    def _rodar(self, *args):
        from io import StringIO

        from django.core.management import call_command

        call_command("estrutura_inicial", *args, stdout=StringIO(), stderr=StringIO())

    def test_cria_tipos_e_24_quartos_sem_duplicar(self):
        from apps.nucleo.models import UH, TipoUH

        self._rodar()
        self._rodar()  # idempotente
        quartos = UH.objects.filter(numero__startswith="Quarto ")
        self.assertEqual(quartos.count(), 24)
        self.assertEqual(
            TipoUH.objects.filter(nome__in=["Padrão", "Intermediário",
                                            "Cabana Intermediária", "Cabana Hobbit"]).count(), 4)
        self.assertEqual(UH.objects.get(numero="Quarto 22").tipo.nome, "Cabana Hobbit")
        self.assertTrue(UH.objects.get(numero="Quarto 04").pcd)

    def test_nao_altera_quarto_existente(self):
        from decimal import Decimal

        from apps.nucleo.models import UH, TipoUH

        outro = TipoUH.objects.create(nome="Suíte Especial", tarifa_base=Decimal("900"))
        UH.objects.create(numero="Quarto 01", tipo=outro)
        self._rodar()
        self.assertEqual(UH.objects.get(numero="Quarto 01").tipo, outro)

    def test_completo_aplica_camas_tarifas_e_vitrine(self):
        from apps.nucleo.models import UH, PosicaoCama
        from apps.reservas.models import TarifaUnidade

        self._rodar("--completo")
        self.assertTrue(PosicaoCama.objects.filter(uh__numero="Quarto 16").exists())
        self.assertTrue(TarifaUnidade.objects.filter(uh__numero="Quarto 22").exists())
        self.assertEqual(UH.objects.filter(numero__startswith="Quarto ").count(), 24)


@override_settings(FNRH_BLOQUEAR_CHECKIN=True)   # como na produção
class DemonstracaoBancoNovoTests(TestCase):
    """A demonstração monta sozinha num banco novo — o caso do ambiente de teste na VPS.

    Lá, num banco virgem, quebravam três coisas: `popular_demo` precisava de um
    superusuário criado ANTES (passava `None` para `criado_por`); os seeds abriam o
    caixa do núcleo, mas a reserva recebe no caixa de Reservas e a Lavanderia no
    dela; e `popular_escala` só reclamava sem funcionário cadastrado. E o check-in
    da demonstração esbarrava na trava da FNRH (hóspede de mentira não tem ficha).
    """

    def _rodar(self, comando, *args):
        from io import StringIO

        from django.core.management import call_command

        call_command(comando, *args, stdout=StringIO(), stderr=StringIO())

    def test_estrutura_e_demonstracao_sem_superusuario(self):
        from apps.escala.models import Atribuicao
        from apps.lavanderia.models import OrdemLavanderia
        from apps.nucleo.models import Funcionario, SessaoCaixa, Usuario
        from apps.reservas.models import Reserva

        self.assertFalse(Usuario.objects.filter(is_superuser=True).exists())
        self._rodar("estrutura_inicial", "--completo")
        self._rodar("popular_demo")
        self._rodar("popular_lavanderia", "--limpar")
        self._rodar("popular_escala", "--limpar")
        self._rodar("popular_estoque")
        self._rodar("popular_manutencao", "--limpar")
        self._rodar("popular_lotacao")

        self.assertTrue(Reserva.objects.filter(observacoes__icontains="[lotacao]",
                                               status=Reserva.Status.HOSPEDADA).exists())
        self.assertTrue(SessaoCaixa.objects.filter(modulo="loja").exists())
        self.assertTrue(Reserva.objects.filter(observacoes__icontains="[demo]",
                                               status=Reserva.Status.HOSPEDADA).exists())
        self.assertTrue(SessaoCaixa.objects.filter(modulo="reservas").exists())
        self.assertTrue(OrdemLavanderia.objects.filter(
            status=OrdemLavanderia.Status.ENTREGUE).exists())
        self.assertGreaterEqual(Funcionario.objects.count(), 6)
        self.assertTrue(Atribuicao.objects.exists())
        # A trava da FNRH continua valendo fora do seed.
        from django.conf import settings
        self.assertTrue(settings.FNRH_BLOQUEAR_CHECKIN)


@override_settings(ROTINAS_MONITOR={})   # a URL de um .env local nunca recebe aviso de teste
class RotinasAgendadasTests(TestCase):
    """`rotinas` roda as tarefas de um grupo, isolando falhas."""

    def test_grupos_rodam_os_comandos_de_verdade(self):
        # Sem mock: garante que todo nome listado em GRUPOS existe e roda num banco vazio.
        from io import StringIO

        from django.core.management import call_command

        for grupo in ("frequentes", "diarias"):
            saida = StringIO()
            call_command("rotinas", "--grupo", grupo, stdout=saida)
            self.assertIn(f"do grupo {grupo} concluída(s)", saida.getvalue())

    def test_falha_de_uma_tarefa_nao_impede_as_outras(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.nucleo.management.commands import rotinas

        chamadas = []

        def falso(nome, **kwargs):
            chamadas.append(nome)
            if nome == "expirar_reservas":
                raise RuntimeError("banco fora")

        with mock.patch.object(rotinas, "call_command", side_effect=falso), \
                self.assertLogs("apps.nucleo.management.commands.rotinas", "ERROR"):
            with self.assertRaisesMessage(CommandError, "expirar_reservas"):
                call_command("rotinas", stdout=StringIO())
        self.assertEqual(chamadas, rotinas.GRUPOS["frequentes"])

    def test_so_filtra_e_recusa_tarefa_de_fora(self):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from apps.nucleo.management.commands import rotinas

        with mock.patch.object(rotinas, "call_command") as falso:
            call_command("rotinas", "--so", "enviar_fnrh_pendentes", stdout=StringIO())
        falso.assert_called_once()
        self.assertEqual(falso.call_args.args[0], "enviar_fnrh_pendentes")
        with self.assertRaises(CommandError):
            call_command("rotinas", "--so", "comando_que_nao_existe", stdout=StringIO())

    # ── monitor ("dead man's switch") ──────────────────────────────────────────
    URL_MONITOR = "https://hc-ping.com/abc-123"

    def _rodar_com_monitor(self, *args, tarefa=None, abrir=None, monitor=None, pedidos=None):
        """Roda `rotinas` com o urlopen trocado e anota [(url, corpo, método, timeout)] em
        `pedidos` (passe a lista quando o comando for terminar com erro)."""
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        from apps.nucleo.management.commands import rotinas

        pedidos = [] if pedidos is None else pedidos

        class Resposta:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def anotar(req, timeout):
            pedidos.append((req.full_url, req.data.decode("utf-8"), req.get_method(), timeout))
            return Resposta()

        monitor = {"frequentes": self.URL_MONITOR} if monitor is None else monitor
        with self.settings(ROTINAS_MONITOR=monitor), \
                mock.patch.object(rotinas, "call_command", side_effect=tarefa), \
                mock.patch.object(rotinas.urlrequest, "urlopen", side_effect=abrir or anotar):
            call_command("rotinas", *args, stdout=StringIO())
        return pedidos

    def test_monitor_recebe_comeco_e_fim_da_mesma_execucao(self):
        pedidos = self._rodar_com_monitor()
        self.assertEqual(len(pedidos), 2)
        (comeco, _, metodo, prazo), (fim, corpo, _, _) = pedidos
        self.assertTrue(comeco.startswith(self.URL_MONITOR + "/start?rid="))
        execucao = comeco.split("rid=")[1]
        self.assertEqual(fim, f"{self.URL_MONITOR}?rid={execucao}")
        self.assertEqual((metodo, prazo), ("POST", 10))
        self.assertIn("expirar_reservas: ok em", corpo)

    def test_falha_vai_ao_monitor_sem_a_mensagem_do_erro(self):
        from django.core.management.base import CommandError

        def tarefa(nome, **kwargs):
            if nome == "expirar_reservas":
                raise RuntimeError("Maria Silva, CPF 123")   # mensagem pode ter dado pessoal

        pedidos = []
        with self.assertLogs("apps.nucleo.management.commands.rotinas", "ERROR"), \
                self.assertRaises(CommandError):     # o comando ainda termina com erro
            self._rodar_com_monitor(tarefa=tarefa, pedidos=pedidos)
        url, corpo, _, _ = pedidos[-1]
        self.assertIn("/fail?rid=", url)
        self.assertIn("expirar_reservas: FALHOU (RuntimeError)", corpo)
        self.assertNotIn("Maria", corpo)

    def test_monitor_fora_do_ar_nao_derruba_a_rotina(self):
        def fora(req, timeout):
            raise OSError("timeout")

        with self.assertLogs("apps.nucleo.management.commands.rotinas", "WARNING") as logs:
            self._rodar_com_monitor(abrir=fora)
        self.assertTrue(any("Monitor das rotinas não respondeu" in m for m in logs.output))

    def test_sem_url_ou_rodando_so_algumas_nao_avisa(self):
        self.assertEqual(self._rodar_com_monitor(monitor={}), [])
        self.assertEqual(self._rodar_com_monitor("--so", "expirar_reservas"), [])
        self.assertEqual(self._rodar_com_monitor(monitor={"frequentes": "file:///etc/passwd"}), [])


class HostsPermitidosTests(TestCase):
    """O Host de qualquer projeto do Railway não é aceito: só os domínios do serviço."""

    def test_sem_curinga_do_railway(self):
        from django.conf import settings

        self.assertNotIn(".railway.app", settings.ALLOWED_HOSTS)
        self.assertNotIn(".up.railway.app", settings.ALLOWED_HOSTS)
        self.assertIn("healthcheck.railway.app", settings.ALLOWED_HOSTS)


class BackupDoBancoTests(TestCase):
    """`backup_banco` gera o dump e guarda fora do container, com retenção."""

    def _rodar(self, *args, env=None):
        import os
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        saida = StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False):
            call_command("backup_banco", *args, stdout=saida)
        return saida.getvalue()

    def test_backup_local_em_json_tem_os_dados(self):
        import gzip
        import json
        import tempfile
        from pathlib import Path

        from .models import Pessoa

        Pessoa.objects.create(nome="Hóspede do Backup")
        with tempfile.TemporaryDirectory() as pasta:
            self._rodar("--formato", "json", env={"BACKUP_DIR": pasta})
            arquivos = list(Path(pasta).glob("crm-*.json.gz"))
            self.assertEqual(len(arquivos), 1)
            with gzip.open(arquivos[0], "rt", encoding="utf-8") as f:
                dados = json.load(f)
        self.assertTrue(any(o["model"] == "nucleo.pessoa"
                            and o["fields"]["nome"] == "Hóspede do Backup" for o in dados))

    def test_apaga_backups_mais_velhos_que_o_prazo(self):
        import os
        import tempfile
        import time
        from pathlib import Path

        with tempfile.TemporaryDirectory() as pasta:
            velho = Path(pasta) / "crm-20260101-000000.json.gz"
            velho.write_bytes(b"x")
            quarenta_dias = time.time() - 40 * 86400
            os.utime(velho, (quarenta_dias, quarenta_dias))
            self._rodar("--formato", "json", "--manter-dias", "30", env={"BACKUP_DIR": pasta})
            self.assertFalse(velho.exists())
            self.assertEqual(len(list(Path(pasta).glob("crm-*"))), 1)

    def test_sem_destino_configurado_so_avisa(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BACKUP_DIR", None)
            saida = self._rodar()
        self.assertIn("Backup não feito", saida)

    def test_r2_envia_com_prefixo_e_apaga_antigos(self):
        from datetime import timedelta
        from unittest import mock

        from django.test import override_settings
        from django.utils import timezone

        from .management.commands import backup_banco

        cliente = mock.MagicMock()
        cliente.get_paginator.return_value.paginate.return_value = [{"Contents": [
            {"Key": "backups/2026/08/crm-velho.json.gz",
             "LastModified": timezone.now() - timedelta(days=60)},
            {"Key": "backups/2026/10/crm-novo.json.gz", "LastModified": timezone.now()},
        ]}]
        with override_settings(USE_R2=True, R2_BUCKET="midia"), \
                mock.patch.object(backup_banco, "_cliente_r2", return_value=cliente):
            saida = self._rodar("--formato", "json")
        chave = cliente.upload_file.call_args.args[2]
        self.assertTrue(chave.startswith("backups/"))
        self.assertIn("r2://midia/backups/", saida)
        cliente.delete_objects.assert_called_once_with(
            Bucket="midia", Delete={"Objects": [{"Key": "backups/2026/08/crm-velho.json.gz"}]})


class AuditoriaSemCustoExtraTests(TestCase):
    """A auditoria automática não lê a linha à toa e só compara o que foi gravado."""

    def test_sem_usuario_no_contexto_nao_le_a_linha_antiga(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from .models import Pessoa

        p = Pessoa.objects.create(nome="Ana")
        p.nome = "Ana Maria"
        with CaptureQueriesContext(connection) as ctx:
            p.save()
        selects = [q["sql"] for q in ctx.captured_queries
                   if q["sql"].startswith("SELECT") and "nucleo_pessoa" in q["sql"]]
        self.assertEqual(selects, [])

    def test_update_fields_registra_so_os_campos_gravados(self):
        from . import audit
        from .models import Pessoa, TrilhaAuditoria

        u = Usuario.objects.create_user(username="aud", password="senha-forte-123")
        p = Pessoa.objects.create(nome="Ana", email="ana@ex.com")
        audit.definir_contexto(u, "127.0.0.1")
        try:
            p.nome = "Ana Maria"
            p.email = "mudou-so-na-memoria@ex.com"
            p.save(update_fields=["nome"])
        finally:
            audit.limpar_contexto()
        trilha = TrilhaAuditoria.objects.filter(acao="editar", alvo="Pessoa", alvo_id=p.pk).get()
        self.assertEqual(set(trilha.detalhe["alteracoes"]), {"nome"})


class ModulosPorRequisicaoTests(TestCase):
    """Dentro de uma requisição, os módulos ativos são lidos uma vez."""

    def test_varias_perguntas_uma_consulta(self):
        from .models.usuarios import memoria_de_modulos

        with memoria_de_modulos():
            modulo_ativo(Modulo.RESERVAS)
            with self.assertNumQueries(0):
                for codigo in (Modulo.RESERVAS, Modulo.LOJA, Modulo.GOVERNANCA):
                    modulo_ativo(codigo)
                modulos_ativos()

    def test_ativar_modulo_no_meio_da_requisicao_limpa_a_memoria(self):
        from .models.usuarios import memoria_de_modulos

        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        with memoria_de_modulos():
            self.assertFalse(modulo_ativo(Modulo.LOJA))
            m = ModuloContratado.objects.get(codigo=Modulo.LOJA)
            m.ativo = True
            m.save()
            self.assertTrue(modulo_ativo(Modulo.LOJA))

    def test_fora_de_requisicao_continua_consultando_o_banco(self):
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        self.assertFalse(modulo_ativo(Modulo.LOJA))
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=True)
        self.assertTrue(modulo_ativo(Modulo.LOJA))


class PessoasSemConsultaPorLinhaTests(TestCase):
    """A lista de Pessoas não consulta os papéis de cada linha separadamente."""

    def _consultas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.get(reverse("pessoas"))
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse("pessoas"))
        self.assertEqual(resp.status_code, 200)
        return len(ctx.captured_queries)

    def test_consultas_nao_crescem_com_as_pessoas(self):
        from .models import Pessoa

        u = Usuario.objects.create_superuser(username="pes", password="senha-forte-123")
        self.client.force_login(u)
        for i in range(3):
            Pessoa.objects.create(nome=f"Pessoa {i}")
        com_3 = self._consultas()
        for i in range(3, 12):
            Pessoa.objects.create(nome=f"Pessoa {i}")
        self.assertEqual(com_3, self._consultas())


class CaixaConcorrenciaEEstornoTests(CaixaTestsBase):
    """Receber e fechar serializados; estorno de sessão fechada vai para a de hoje."""

    def test_fechar_grava_as_observacoes(self):
        self.sessao.fechar(Decimal("100.00"), self.operador, observacoes="Faltou uma moeda")
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.observacoes_fechamento, "Faltou uma moeda")

    def test_fechar_pela_outra_aba_recusa_sessao_ja_fechada(self):
        outra_aba = SessaoCaixa.objects.get(pk=self.sessao.pk)
        self.sessao.fechar(Decimal("100.00"), self.operador)
        with self.assertRaises(ValidationError):
            outra_aba.fechar(Decimal("100.00"), self.operador)

    def test_receber_depois_de_fechado_recusa(self):
        from .models import receber_no_caixa

        self.sessao.fechar(Decimal("100.00"), self.operador)
        with self.assertRaises(ValidationError):
            receber_no_caixa(self.operador, self.dinheiro, Decimal("10.00"), "Diária",
                             modulo="nucleo")

    def test_estorno_de_sessao_fechada_entra_no_caixa_aberto_do_operador(self):
        movimento = self.receber("80.00")
        self.sessao.fechar(Decimal("180.00"), self.operador)  # fundo 100 + 80
        conferida = SessaoCaixa.objects.get(pk=self.sessao.pk).diferenca
        hoje = SessaoCaixa.objects.create(operador=self.gerente, modulo="nucleo",
                                          fundo_troco=Decimal("200.00"))
        estorno = estornar_movimento(movimento, movimento.sessao, self.gerente,
                                     "Devolução ao hóspede")
        self.assertEqual(estorno.sessao, hoje)
        self.assertEqual(SessaoCaixa.objects.get(pk=self.sessao.pk).diferenca, conferida)
        self.assertEqual(hoje.esperado_em_dinheiro(), Decimal("120.00"))  # 200 − 80

    def test_estorno_sem_caixa_aberto_explica_o_que_fazer(self):
        movimento = self.receber("50.00")
        self.sessao.fechar(Decimal("150.00"), self.operador)
        with self.assertRaisesMessage(ValidationError, "abra o seu caixa"):
            estornar_movimento(movimento, movimento.sessao, self.gerente, "Devolução")


class TrilhaLGPDTests(TestCase):
    """Trilha: documento mascarado, escrita pública atribuída, retenção e exportação."""

    def setUp(self):
        from apps.nucleo import audit
        self.audit = audit
        self.user = Usuario.objects.create_user(username="rec2", password="x")

    def tearDown(self):
        self.audit.limpar_contexto()

    def _trilha(self, **f):
        from apps.nucleo.models import TrilhaAuditoria
        return TrilhaAuditoria.objects.filter(**f)

    def test_documento_vai_mascarado_mas_a_mudanca_fica(self):
        from apps.nucleo.models import Pessoa
        self.audit.definir_contexto(self.user, "200.1.2.3")
        p = Pessoa.objects.create(nome="Ana Doc", documento="529.982.247-25")
        criar = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="criar").get()
        self.assertEqual(criar.detalhe["valores"]["documento"], "•••")
        self.assertEqual(criar.detalhe["valores"]["nome"], "Ana Doc")
        p.documento = "111.444.777-35"
        p.save()
        editar = self._trilha(alvo="Pessoa", alvo_id=str(p.pk), acao="editar").get()
        self.assertEqual(editar.detalhe["alteracoes"]["documento"], ["•••", "•••"])
        self.assertNotIn("111.444.777-35", str(editar.detalhe))

    def test_escrita_publica_fica_na_trilha_com_usuario_de_sistema(self):
        r = self.client.post(reverse("core:pedir_proposta"), {
            "nome": "Lead Público", "telefone": "49999880303", "email": "pub@ex.com",
            "tipo_interesse": "hospedagem"})
        self.assertEqual(r.status_code, 302)
        t = self._trilha(alvo="Pessoa", acao="criar").select_related("usuario").first()
        self.assertIsNotNone(t)
        self.assertEqual(t.usuario.username, "_site")

    def test_purga_respeita_a_retencao(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        from apps.nucleo.models import TrilhaAuditoria
        velho = TrilhaAuditoria.objects.create(acao="x", alvo="X", alvo_id="1")
        TrilhaAuditoria.objects.filter(pk=velho.pk).update(
            criado_em=timezone.now() - timedelta(days=400))
        novo = TrilhaAuditoria.objects.create(acao="y", alvo="Y", alvo_id="2")
        call_command("purgar_trilha", stdout=__import__("io").StringIO())  # padrão: 0 = não apaga
        self.assertTrue(TrilhaAuditoria.objects.filter(pk=velho.pk).exists())
        call_command("purgar_trilha", "--dias", "365", stdout=__import__("io").StringIO())
        self.assertFalse(TrilhaAuditoria.objects.filter(pk=velho.pk).exists())
        self.assertTrue(TrilhaAuditoria.objects.filter(pk=novo.pk).exists())
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="purga_trilha").exists())

    def test_exportar_a_trilha_exige_gerencia(self):
        from apps.nucleo.models import ModuloContratado
        from apps.nucleo.modulos import Modulo
        ModuloContratado.objects.update_or_create(codigo=Modulo.AUDITORIA, defaults={"ativo": True})
        self.user.modulos.add(ModuloContratado.objects.get(codigo=Modulo.AUDITORIA))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("auditoria:trilha")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("auditoria:trilha") + "?export=csv").status_code, 403)


class HorariosNaTabelaDePrecosTests(TestCase):
    def test_salva_os_horarios(self):
        import datetime

        from apps.nucleo.models import ConfiguracaoReservas
        gerente = Usuario.objects.create_superuser(username="precos", password="x-senha-forte-1")
        self.client.force_login(gerente)
        self.client.post(reverse("tabela_precos"),
                         {"hora_checkin": "13:30", "hora_checkout": "11:00"})
        cfg = ConfiguracaoReservas.carregar()
        self.assertEqual((cfg.hora_checkin, cfg.hora_checkout),
                         (datetime.time(13, 30), datetime.time(11, 0)))
        self.assertContains(self.client.get(reverse("tabela_precos")), 'value="13:30"')


class CustoPorCanalNaTabelaDePrecosTests(TestCase):
    """Percentual de custo de venda por canal — base do relatório de distribuição."""

    def setUp(self):
        self.gerente = Usuario.objects.create_superuser(
            username="precos-canal", password="x-senha-forte-1")
        self.client.force_login(self.gerente)

    def test_padrao_ota_18_e_direto_zero(self):
        from apps.nucleo.models import ConfiguracaoReservas
        custos = ConfiguracaoReservas.carregar().custo_por_canal()
        self.assertEqual(custos["ota"], Decimal("18.00"))
        self.assertEqual([custos["site"], custos["whatsapp"], custos["balcao"]],
                         [Decimal("0.00")] * 3)

    def test_salva_os_percentuais_em_formato_brl(self):
        from apps.nucleo.models import ConfiguracaoReservas
        self.client.post(reverse("tabela_precos"), {
            "custo_canal_ota": "16,50", "custo_canal_site": "2,99",
            "custo_canal_whatsapp": "0,00", "custo_canal_balcao": "0,00",
        })
        custos = ConfiguracaoReservas.carregar().custo_por_canal()
        self.assertEqual(custos["ota"], Decimal("16.50"))
        self.assertEqual(custos["site"], Decimal("2.99"))
        self.assertContains(self.client.get(reverse("tabela_precos")),
                            'name="custo_canal_ota" value="16,50"')


class PaginacaoTests(TestCase):
    """Listas paginadas: total real, página estável e busca/filtros que seguem junto
    (antes cada lista cortava em 200/300 e o resto sumia; a de Pessoas trazia tudo)."""

    def setUp(self):
        u = Usuario.objects.create_superuser(username="pag", password="senha-forte-123")
        self.client.force_login(u)

    def test_paginar_desempata_pela_pk(self):
        # Mesmo nome = mesma posição na ordem por nome: sem desempate, uma pessoa podia
        # aparecer em duas páginas e outra em nenhuma.
        from django.test import RequestFactory

        from .paginacao import paginar

        for _ in range(5):
            Pessoa.objects.create(nome="Mesmo Nome")
        consulta = Pessoa.objects.filter(nome="Mesmo Nome")
        vistos = []
        for numero in (1, 2, 3):
            pedido = RequestFactory().get("/", {"pagina": numero})
            vistos += [p.pk for p in paginar(pedido, consulta, 2)]
        self.assertEqual(sorted(vistos), sorted(consulta.values_list("pk", flat=True)))

    def test_pagina_invalida_ou_alem_do_fim(self):
        from django.test import RequestFactory

        from .paginacao import paginar

        for i in range(3):
            Pessoa.objects.create(nome=f"P{i}")
        pedido = RequestFactory().get("/", {"pagina": "abc"})
        self.assertEqual(paginar(pedido, Pessoa.objects.all(), 2).number, 1)
        pedido = RequestFactory().get("/", {"pagina": "99"})
        self.assertEqual(paginar(pedido, Pessoa.objects.all(), 2).number, 2)

    def test_pessoas_em_paginas_com_a_busca_junto(self):
        for i in range(60):
            Pessoa.objects.create(nome=f"Fulano {i:02d}")
        resp = self.client.get(reverse("pessoas"), {"q": "Fulano"})
        self.assertEqual(len(resp.context["pessoas"]), 50)
        self.assertContains(resp, "Página 1 de 2")
        self.assertContains(resp, "1–50 de 60")
        self.assertContains(resp, "?q=Fulano&amp;pagina=2")
        resp = self.client.get(reverse("pessoas"), {"q": "Fulano", "pagina": 2})
        self.assertEqual(len(resp.context["pessoas"]), 10)
        self.assertContains(resp, "Fulano 59")

    def test_lista_curta_sem_paginacao(self):
        Pessoa.objects.create(nome="Sozinha")
        resp = self.client.get(reverse("pessoas"))
        self.assertNotContains(resp, 'class="paginacao"')

    def test_milhar(self):
        from .templatetags.moeda import milhar

        self.assertEqual(milhar(1234567), "1.234.567")
        self.assertEqual(milhar(950), "950")
        self.assertEqual(milhar("x"), "x")



class ReaisInputTests(TestCase):
    """O campo de R$ sai do servidor no formato da máscara: o submit tira os pontos de
    milhar, e um "10000.00" cru chegava ao backend como 1000000."""

    def test_valor_inicial_e_valor_devolvido_saem_como_a_mascara(self):
        from decimal import Decimal

        from .forms import ReaisInput

        w = ReaisInput()
        self.assertEqual(w.format_value(Decimal("10000.00")), "10.000,00")
        self.assertEqual(w.format_value("1784.00"), "1.784,00")  # form que voltou com erro
        self.assertEqual(w.format_value("12,3x"), "12,3x")  # o que a pessoa digitou
        self.assertIsNone(w.format_value(""))
        self.assertIn('value="650,00"', w.render("valor", Decimal("650")))



class PctBrTests(TestCase):
    """`Decimal.normalize()` escreve 10 como "1E+1": o site mostrava "retemos 1E+1%"."""

    def test_percentual_sai_como_gente_escreve(self):
        from decimal import Decimal

        from .formatos import pct_br

        self.assertEqual(pct_br(Decimal("10.00")), "10")
        self.assertEqual(pct_br(Decimal("100")), "100")
        self.assertEqual(pct_br(Decimal("12.50")), "12,5")
        self.assertEqual(pct_br(Decimal("4.00")), "4")
        self.assertEqual(pct_br(Decimal("0.00")), "0")
        self.assertEqual(pct_br("20"), "20")


class CopiarECompartilharTests(TestCase):
    """O botão «Copiar» e o «Enviar pelo WhatsApp» (apps/nucleo/compartilhar.py +
    {% copiar %}). O que a recepção fazia com o mouse: selecionar o link de
    pagamento, copiar e colar na conversa."""

    def render(self, template, **ctx):
        from django.template import Context, Template

        return Template("{% load nucleo_extras %}" + template).render(Context(ctx))

    # ── telefone ────────────────────────────────────────────────────────────
    def test_telefone_com_mascara_vira_numero_discavel(self):
        from .compartilhar import telefone_whatsapp

        self.assertEqual(telefone_whatsapp("(49) 99964-8702"), "5549999648702")
        self.assertEqual(telefone_whatsapp("49 2055-0005"), "554920550005")

    def test_telefone_que_ja_tem_ddi_nao_ganha_outro(self):
        from .compartilhar import telefone_whatsapp

        self.assertEqual(telefone_whatsapp("+55 (49) 99964-8702"), "5549999648702")
        self.assertEqual(telefone_whatsapp("554920550005"), "554920550005")

    def test_ddd_55_de_santa_maria_nao_e_confundido_com_o_ddi(self):
        """11 dígitos começando em 55 é DDD 55 (RS), não DDI — leva o 55 na frente."""
        from .compartilhar import telefone_whatsapp

        self.assertEqual(telefone_whatsapp("55999990000"), "5555999990000")

    def test_telefone_pela_metade_nao_vira_link_errado(self):
        from .compartilhar import telefone_whatsapp

        for valor in ("", None, "99964", "0000-0000", "abc"):
            self.assertEqual(telefone_whatsapp(valor), "", valor)

    # ── mensagem e link ─────────────────────────────────────────────────────
    def test_mensagem_junta_recado_e_link(self):
        from .compartilhar import mensagem_whatsapp

        self.assertEqual(mensagem_whatsapp("Olá!", "http://x/y"), "Olá!\n\nhttp://x/y")
        self.assertEqual(mensagem_whatsapp("", "http://x/y"), "http://x/y")
        self.assertEqual(mensagem_whatsapp("Olá!", ""), "Olá!")

    def test_link_do_whatsapp_leva_telefone_normalizado_e_texto_codificado(self):
        from .compartilhar import link_whatsapp

        url = link_whatsapp("Olá! Seu link:\nhttp://x/y", "(49) 99964-8702")
        self.assertTrue(url.startswith("https://wa.me/5549999648702?text="))
        self.assertIn("Ol%C3%A1", url)          # acento codificado
        self.assertIn("%0A", url)               # quebra de linha preservada
        self.assertNotIn(" ", url)

    def test_sem_telefone_abre_o_whatsapp_para_escolher_o_contato(self):
        from .compartilhar import link_whatsapp

        self.assertTrue(link_whatsapp("oi", "").startswith("https://wa.me/?text="))

    # ── componente ──────────────────────────────────────────────────────────
    def test_componente_poe_o_texto_no_botao_e_na_tela(self):
        html = self.render('{% copiar "http://x/y" rotulo="Link de pagamento" %}')
        self.assertIn('data-copiar="http://x/y"', html)
        self.assertIn("Link de pagamento", html)
        self.assertIn(">Copiar<", html)
        self.assertIn(">Copiado<", html)        # o retorno já está no HTML
        self.assertIn('class="ico', html)       # ícone é SVG, não emoji

    def test_sem_recado_nao_aparece_botao_de_whatsapp(self):
        html = self.render('{% copiar "http://x/y" %}')
        self.assertNotIn("wa.me", html)

    def test_com_recado_e_telefone_o_botao_abre_a_conversa_certa(self):
        html = self.render(
            '{% copiar "http://x/y" recado="Olá! Segue o link:" telefone="(49) 99964-8702" %}'
        )
        self.assertIn("https://wa.me/5549999648702?text=", html)
        self.assertIn("Enviar pelo WhatsApp", html)
        self.assertIn("http%3A//x/y", html)     # o link vai dentro da mensagem

    def test_mostrar_false_deixa_so_os_botoes(self):
        html = self.render('{% copiar "http://x/y" mostrar=False %}')
        self.assertNotIn("copiar-texto", html)
        self.assertIn("data-copiar", html)

    def test_aspas_no_texto_nao_quebram_o_atributo(self):
        html = self.render('{% copiar texto %}', texto='di"ga')
        self.assertIn("data-copiar=\"di&quot;ga\"", html)

    def test_script_do_copiar_vai_em_toda_tela_do_crm(self):
        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("js/copiar.js", base)
