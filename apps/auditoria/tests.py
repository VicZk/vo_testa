from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, Pessoa, TipoUH, registrar_auditoria
from apps.reservas.models import Reserva

from . import services

Usuario = get_user_model()


class VarreduraTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 01", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede")

    def _hospedada(self, checkout_offset):
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje - timedelta(days=3),
            checkout=hoje + timedelta(days=checkout_offset),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        # A entrada ocorreu no início da estadia; a auditoria roda hoje, com saída atrasada.
        with patch("apps.reservas.services.timezone.localdate", return_value=r.checkin):
            r.fazer_checkin(self.op)
        return r

    def test_detecta_checkout_vencido(self):
        self._hospedada(checkout_offset=-1)  # checkout ontem, ainda hospedada
        achados = services.varrer()
        tipos = {a["tipo"] for a in achados}
        self.assertIn("checkout_vencido", tipos)
        # conta com saldo também aparece (diárias lançadas, nada pago)
        self.assertIn("conta_com_saldo", tipos)

    def test_sem_pendencias_quando_tudo_ok(self):
        # nenhuma reserva/pendência criada
        achados = services.varrer()
        self.assertEqual([a for a in achados if a["area"] == "Reservas"], [])

    def test_resumo_conta_por_gravidade(self):
        self._hospedada(checkout_offset=-1)
        achados = services.varrer()
        r = services.resumo(achados)
        self.assertEqual(r["total"], len(achados))
        self.assertGreaterEqual(r["por_gravidade"]["alta"], 1)


class ComandaLavanderiaTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")

    def test_comanda_aberta_ha_muito(self):
        from apps.nucleo.models import LocalEstoque
        from apps.restaurante.models import Comanda
        local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        c = Comanda.objects.create(local=local, rotulo="Mesa 1", criado_por=self.op)
        Comanda.objects.filter(pk=c.pk).update(
            aberta_em=timezone.now() - timedelta(hours=20)  # burla o auto_now_add
        )
        tipos = {a["tipo"] for a in services.varrer()}
        self.assertIn("comanda_antiga", tipos)

    def test_ordem_lavanderia_atrasada(self):
        from apps.lavanderia.models import OrdemLavanderia
        o = OrdemLavanderia.objects.create(rotulo="Quarto 5", criado_por=self.op,
                                           prazo=timezone.localdate() - timedelta(days=1))
        self.assertTrue(o.em_producao)
        tipos = {a["tipo"] for a in services.varrer()}
        self.assertIn("lavanderia_atrasada", tipos)


class PainelTrilhaTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="aud", password="senha-forte-123")
        self.client.login(username="aud", password="senha-forte-123")

    def test_painel_ok(self):
        self.assertEqual(self.client.get(reverse("auditoria:painel")).status_code, 200)

    def test_trilha_e_export_csv(self):
        registrar_auditoria(self.op, "estorno_pagamento", self.op, {"valor": "100"})
        r = self.client.get(reverse("auditoria:trilha"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "estorno_pagamento")
        csv_resp = self.client.get(reverse("auditoria:trilha"), {"export": "csv"})
        self.assertIn("text/csv", csv_resp["Content-Type"])
        corpo = csv_resp.content.decode()
        self.assertIn("Quando;Usuário;Descrição;Ação;Código da ação;Alvo;ID do alvo;Detalhe",
                      corpo)
        self.assertIn(";Estorno de pagamento;estorno_pagamento;", corpo)

    def test_sem_acesso_da_403(self):
        Usuario.objects.create_user(username="x", password="senha-forte-123")
        self.client.login(username="x", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("auditoria:painel")).status_code, 403)


class FormatacaoTrilhaTests(TestCase):
    """A trilha lê como frase, não como JSON cru."""

    def _reg(self, acao, alvo="", detalhe=None, alvo_id="1"):
        from types import SimpleNamespace
        return SimpleNamespace(acao=acao, alvo=alvo, detalhe=detalhe or {}, alvo_id=alvo_id)

    def _frase(self, *a, **k):
        from .formatacao import frase
        return frase(self._reg(*a, **k))

    def test_login_logout(self):
        self.assertEqual(self._frase("login", "Usuario"), "Entrou no sistema")
        self.assertEqual(self._frase("logout", "Usuario"), "Saiu do sistema")

    def test_abrir_caixa(self):
        f = self._frase("criar", "SessaoCaixa",
                        {"valores": {"modulo": "reservas", "fundo_troco": "50.00"}})
        self.assertIn("Abriu o caixa de reservas", f)
        self.assertIn("R$ 50,00", f)

    def test_fechar_caixa(self):
        f = self._frase("fechamento_caixa", "SessaoCaixa",
                        {"contado": "350.00", "diferenca": "0.00"})
        self.assertIn("Fechou o caixa", f)
        self.assertIn("Valor contado: R$ 350,00", f)
        self.assertIn("diferença R$ 0,00", f)

    def test_recebimento(self):
        f = self._frase("criar", "MovimentoCaixa",
                        {"valores": {"tipo": "recebimento", "valor": "120.00",
                                     "descricao": "Conta reserva #5"}})
        self.assertIn("Recebeu R$ 120,00", f)
        self.assertIn("Conta reserva #5", f)

    def test_editar_mostra_diff(self):
        f = self._frase("editar", "Reserva", {"alteracoes": {"status": ["confirmada", "hospedada"]}})
        self.assertIn("Alterou reserva", f)
        self.assertIn("Situação: Confirmada → Hospedada", f)

    def test_valores_legiveis_preservam_o_detalhe_original(self):
        from copy import deepcopy

        from .formatacao import frase
        detalhe = {"alteracoes": {
            "atualizado_em": [None, "2026-10-21T02:31:14+00:00"],
            "atualizado_por_id": [None, 12], "payload": [{"valor": "100.00"}, {"valor": "200.00"}],
        }}
        original = deepcopy(detalhe)
        texto = frase(self._reg("editar", "StatusLimpeza", detalhe))
        self.assertIn("Atualizado em: — → 20/10/2026 23:31", texto)
        self.assertIn("Responsável: — → #12", texto)
        self.assertIn("Dados do provedor: (detalhes técnicos) → (detalhes técnicos)", texto)
        self.assertEqual(detalhe, original)

    def test_data_booleano_uuid_lista_e_novo_model(self):
        from .formatacao import _valor_legivel, rotulo_alvo
        self.assertEqual(_valor_legivel("data", "2026-10-21"), "21/10/2026")
        self.assertEqual(_valor_legivel("ativo", False), "Não")
        self.assertEqual(_valor_legivel("itens", [1, 2]), "(detalhes técnicos)")
        self.assertEqual(_valor_legivel("chave", "12345678-1234-1234-1234-123456789abc"), "12345678…")
        self.assertEqual(rotulo_alvo("NovaConfiguracaoFNRH"), "Nova Configuracao FNRH")
        self.assertEqual(rotulo_alvo("FichaFNRH"), "Ficha FNRH")

    def test_fallback_nunca_quebra(self):
        f = self._frase("acao_desconhecida", "Reserva", {"algo": "x"})
        self.assertIn("Acao desconhecida", f)
        self.assertNotIn("{", f)  # nada de JSON cru

    def test_entidades_operacionais(self):
        self.assertEqual(self._frase("criar", "EntradaLogbook"), "Deixou um recado no turno")
        self.assertIn("Abriu ordem de serviço", self._frase("criar", "OrdemServico", alvo_id="12"))
        self.assertIn("Registrou venda", self._frase("criar", "Venda", alvo_id="45"))
        self.assertIn("Abriu comanda", self._frase("criar", "Comanda", alvo_id="3"))


class TrilhaSalarioTests(TestCase):
    """Salário é sensível: a mudança é auditada, mas o VALOR só aparece na trilha
    para quem tem a área Remuneração (achado alta da auditoria multiagente)."""

    def _user(self, username, areas):
        from apps.nucleo.models import ModuloContratado
        u = Usuario.objects.create_user(username=username, password="senha-forte-123")
        u.areas = areas
        u.save()
        u.modulos.add(ModuloContratado.objects.get(codigo="auditoria"))
        return u

    def setUp(self):
        from apps.nucleo.models import TrilhaAuditoria
        TrilhaAuditoria.objects.create(
            acao="editar", alvo="Funcionario", alvo_id="7",
            detalhe={"alteracoes": {"salario": ["1500.00", "9999.00"],
                                    "cargo": ["Camareira", "Governanta"]}},
        )

    def test_redigir_sensiveis_helper(self):
        from apps.nucleo.audit import redigir_sensiveis
        r = redigir_sensiveis({"alteracoes": {"salario": ["1", "2"], "cargo": ["a", "b"]}})
        self.assertEqual(r["alteracoes"]["salario"], ["•••", "•••"])
        self.assertEqual(r["alteracoes"]["cargo"], ["a", "b"])
        r2 = redigir_sensiveis({"valores": {"salario": "3000.00", "nome": "X"}})
        self.assertEqual(r2["valores"]["salario"], "•••")
        self.assertEqual(r2["valores"]["nome"], "X")

    def test_sem_remuneracao_nao_ve_salario(self):
        self._user("semrem", [])
        self.client.login(username="semrem", password="senha-forte-123")
        r = self.client.get(reverse("auditoria:trilha"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "9999.00")   # valor do salário mascarado
        self.assertContains(r, "Governanta")   # mudança não-sensível continua visível

    def test_com_remuneracao_ve_salario(self):
        self._user("comrem", ["remuneracao"])
        self.client.login(username="comrem", password="senha-forte-123")
        r = self.client.get(reverse("auditoria:trilha"))
        self.assertContains(r, "9999.00")


class FechamentosTelaTests(TestCase):
    """Tela dos fechamentos do dia: lista o mês, soma e exporta (CSV só gerência)."""

    def setUp(self):
        from apps.reservas.models import FechamentoDiario

        hoje = timezone.localdate()
        FechamentoDiario.objects.create(
            data=hoje.replace(day=1), quartos_disponiveis=24, quartos_ocupados=12,
            chegadas=3, saidas=2, no_shows=1, receita_diarias=Decimal("2400.00"),
            receita_servico=Decimal("2500.00"), receita_consumo=Decimal("310.50"),
            saldo_em_aberto=Decimal("900.00"))

    def test_gerencia_ve_e_exporta(self):
        Usuario.objects.create_superuser(username="ger", password="senha-forte-123")
        self.client.login(username="ger", password="senha-forte-123")
        r = self.client.get(reverse("auditoria:fechamentos"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "R$ 2.400,00")
        self.assertContains(r, "12/24")
        self.assertContains(r, "R$ 200,00")  # ADR = 2.400 / 12
        csv_resp = self.client.get(reverse("auditoria:fechamentos"), {"export": "csv"})
        self.assertIn("text/csv", csv_resp["Content-Type"])
        corpo = csv_resp.content.decode("utf-8-sig")
        self.assertIn("Dia;Quartos disponíveis;Quartos ocupados;Ocupação (%);", corpo)
        self.assertIn(";2400,00;200,00;", corpo)  # vírgula: o Excel pt-BR lê como número

    def test_operador_ve_mas_nao_exporta(self):
        from apps.nucleo.models import ModuloContratado

        u = Usuario.objects.create_user(username="op", password="senha-forte-123")
        u.modulos.add(ModuloContratado.objects.get(codigo="auditoria"))
        self.client.login(username="op", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("auditoria:fechamentos")).status_code, 200)
        r = self.client.get(reverse("auditoria:fechamentos"), {"export": "csv"})
        self.assertEqual(r.status_code, 403)

    def test_painel_leva_aos_fechamentos(self):
        Usuario.objects.create_superuser(username="ger", password="senha-forte-123")
        self.client.login(username="ger", password="senha-forte-123")
        self.assertContains(self.client.get(reverse("auditoria:painel")),
                            reverse("auditoria:fechamentos"))


class RotulosDaTrilhaTests(TestCase):
    """A coluna Ação e o filtro da trilha mostravam o código cru ("no_show",
    "bloqueio_uh", "lead_fechado_movido") e a gravidade saía "media". Agora palavra de
    gente; o código continua no banco e no CSV (forense)."""

    def test_rotulos(self):
        from .formatacao import rotulo_acao, rotulo_alvo, rotulo_gravidade
        self.assertEqual(rotulo_acao("no_show"), "Não comparecimento")
        self.assertEqual(rotulo_acao("algo_novo_aqui"), "Algo novo aqui")   # sem molde
        self.assertEqual(rotulo_alvo("SessaoCaixa"), "Caixa")
        self.assertEqual(rotulo_alvo("OrdemServico"), "Ordem de serviço")
        self.assertEqual(rotulo_alvo("ModeloQualquer"), "Modelo Qualquer")
        self.assertEqual(rotulo_gravidade("media"), "Média")

    def test_trilha_e_filtro_mostram_o_rotulo(self):
        op = Usuario.objects.create_superuser(username="aud2", password="senha-forte-123")
        self.client.force_login(op)
        registrar_auditoria(op, "no_show", op, {})
        r = self.client.get(reverse("auditoria:trilha"))
        self.assertContains(r, '<span class="selo">Não comparecimento</span>', html=True)
        self.assertContains(r, '<option value="no_show">Não comparecimento</option>', html=True)
        self.assertNotContains(r, ">no_show<")
        csv_resp = self.client.get(reverse("auditoria:trilha"), {"export": "csv"})
        # O CSV guarda o código (forense), na coluna dele, ao lado do rótulo.
        self.assertIn(";Não comparecimento;no_show;", csv_resp.content.decode())
