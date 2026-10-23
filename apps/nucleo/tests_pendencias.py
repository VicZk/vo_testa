"""Pendências com origem verificável, consultas sem efeitos e escopo por usuário."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.governanca import services as governanca
from apps.governanca.models import StatusLimpeza, TarefaGovernanca

from .areas import Area
from .context_processors import menu_modulos
from .models import (
    UH,
    CategoriaFinanceira,
    ContaPagarReceber,
    ModuloContratado,
    SessaoCaixa,
    TipoUH,
    Usuario,
)
from .models.cadastros import ConfiguracaoReservas
from .modulos import Modulo
from .pendencias import pendencias_usuario, url_pendencias


class PendenciasTests(TestCase):
    def setUp(self):
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        self.gov = ModuloContratado.objects.get_or_create(codigo=Modulo.GOVERNANCA)[0]
        self.gov.ativo = True
        self.gov.save()
        cache.clear()
        self.usuario = Usuario.objects.create_user(username="camareira-pendencias", password="qa-segura-123")
        self.usuario.modulos.add(self.gov)
        self.gerente = Usuario.objects.create_user(username="gerente-pendencias", password="qa-segura-123", is_staff=True)
        self.tipo = TipoUH.objects.create(nome="Quarto QA", tarifa_base=Decimal("100"))
        self.uh = UH.objects.create(numero="QA 01", tipo=self.tipo)
        self.client.force_login(self.usuario)

    def _ativar(self, codigo, usuario=None):
        modulo, _ = ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        if usuario:
            usuario.modulos.add(modulo)
        cache.clear()
        return modulo

    def _tarefa(self, numero, status=TarefaGovernanca.Status.PENDENTE):
        uh = UH.objects.create(numero=numero, tipo=self.tipo)
        return TarefaGovernanca.objects.create(uh=uh, status=status, camareira=self.usuario)

    def _conta(self):
        categoria = CategoriaFinanceira.objects.create(nome="Despesa QA", tipo=CategoriaFinanceira.Tipo.DESPESA)
        return ContaPagarReceber.objects.create(
            tipo=ContaPagarReceber.Tipo.PAGAR, categoria=categoria,
            descricao="Financeiro reservado QA", valor=Decimal("9876.54"),
            vencimento=timezone.localdate() - timedelta(days=1),
        )

    def _caixa(self, usuario):
        sessao = SessaoCaixa.objects.create(operador=usuario, modulo="nucleo", fundo_troco=Decimal("0"))
        SessaoCaixa.objects.filter(pk=sessao.pk).update(aberta_em=timezone.now() - timedelta(days=2))
        return sessao

    def test_contador_menu_polling_e_lista_correspondem_a_servicos_aguardando_inicio(self):
        primeira = self._tarefa("QA 02")
        segunda = self._tarefa("QA 03")
        self._tarefa("QA 04", TarefaGovernanca.Status.EM_ANDAMENTO)
        self._tarefa("QA 05", TarefaGovernanca.Status.CONCLUIDA)
        inativa = self._tarefa("QA inativo")
        inativa.uh.status = UH.Status.INATIVA
        inativa.uh.save()
        day_use = TipoUH.objects.create(nome="Day use QA", modalidade=TipoUH.Modalidade.DAY_USE, tarifa_base=Decimal("0"))
        uh_dia = UH.objects.create(numero="QA day use", tipo=day_use)
        TarefaGovernanca.objects.create(uh=uh_dia)

        request = RequestFactory().get(reverse("pendencias"))
        request.user = self.usuario
        self.assertEqual(menu_modulos(request)["governanca_pendentes"], 2)
        polling = self.client.get(reverse("governanca:atualizacoes")).json()
        self.assertEqual((polling["pendentes"], polling["em_andamento"]), (2, 1))
        resposta = self.client.get(url_pendencias("governanca", "pendente"))
        self.assertEqual(resposta.context["total"], 2)
        self.assertEqual({i["id"] for i in resposta.context["itens"]}, {
            f"governanca:tarefa-{primeira.pk}", f"governanca:tarefa-{segunda.pk}"})
        self.assertContains(resposta, "serviços de limpeza aguardando início")
        self.assertContains(resposta, "?servico=pendente")
        self.assertContains(resposta, 'class="nav-badge nav-badge-link"')

    def test_ciclo_tira_tarefa_do_contador_e_nao_inventa_pendencia_em_quarto_pronto(self):
        tarefa = governanca.abrir_faxina(self.uh, usuario=self.usuario)
        self.assertEqual(governanca.resumo_pendencias()["pendentes"], 1)
        governanca.iniciar_tarefa(tarefa, self.usuario)
        self.assertEqual(governanca.resumo_pendencias()["pendentes"], 0)
        self.assertEqual(governanca.pendencias_operacionais()[0]["estado"], "em_andamento")
        governanca.concluir_tarefa(tarefa, self.usuario)
        self.assertEqual(governanca.resumo_pendencias()["total"], 0)
        self.assertEqual(governanca.pendencias_operacionais()[0]["estado"], "inspecao")
        governanca.inspecionar(self.uh, self.usuario)
        self.assertEqual(governanca.pendencias_operacionais(), [])
        UH.objects.create(numero="Sem status QA", tipo=self.tipo)
        self.assertEqual(governanca.pendencias_operacionais(), [])

    def test_quarto_limpo_com_outro_servico_aberto_nao_duplica_inspecao(self):
        StatusLimpeza.objects.create(uh=self.uh, situacao=StatusLimpeza.Situacao.LIMPA)
        tarefa = TarefaGovernanca.objects.create(uh=self.uh)
        itens = governanca.pendencias_operacionais()
        self.assertEqual([i["id"] for i in itens], [f"tarefa-{tarefa.pk}"])

    def test_camareira_nao_consulta_nem_recebe_financeiro_caixa_ou_outro_modulo(self):
        self._tarefa("QA limpeza")
        self._conta()
        self._caixa(self.gerente)
        self._ativar(Modulo.COMERCIAL)
        with patch("apps.comercial.services.pendencias_auditoria") as comercial, patch(
            "apps.auditoria.services.varrer", side_effect=AssertionError("varredura irrestrita")):
            resposta = self.client.get(reverse("pendencias"))
            dados = self.client.get(reverse("pendencias_atualizacoes")).json()
        comercial.assert_not_called()
        self.assertEqual({o["codigo"] for o in resposta.context["origens"]}, {"governanca"})
        self.assertNotContains(resposta, "Financeiro reservado QA")
        self.assertNotIn("Financeiro reservado QA", dados["html"])
        self.assertNotIn("9876", dados["html"])
        for origem in ("financeiro", "caixa", "comercial"):
            self.assertEqual(self.client.get(reverse("pendencias"), {"origem": origem}).status_code, 403)
            self.assertEqual(self.client.get(reverse("pendencias_atualizacoes"), {"origem": origem}).status_code, 403)

    def test_caixa_respeita_operador_e_gerencia_como_a_tela_de_destino(self):
        self.usuario.areas = [Area.CAIXA]
        self.usuario.save()
        minha = self._caixa(self.usuario)
        outra = self._caixa(self.gerente)
        caixas = [i for i in pendencias_usuario(self.usuario)["itens"] if i["origem"] == "caixa"]
        self.assertEqual([i["url"] for i in caixas], [reverse("caixa_sessao", args=[minha.pk])])
        self.gerente.areas = [Area.CAIXA]
        self.gerente.save()
        caixas = [i for i in pendencias_usuario(self.gerente)["itens"] if i["origem"] == "caixa"]
        self.assertEqual({i["url"] for i in caixas}, {
            reverse("caixa_sessao", args=[minha.pk]), reverse("caixa_sessao", args=[outra.pk])})

    def test_financeiro_autorizado_recebe_link_a_linha_da_conta(self):
        conta = self._conta()
        self.usuario.areas = [Area.FINANCEIRO]
        self.usuario.save()
        resposta = self.client.get(url_pendencias("financeiro"))
        self.assertEqual(resposta.context["total"], 1)
        self.assertEqual(resposta.context["itens"][0]["url"], reverse("contas") + f"?situacao=abertas#conta-{conta.pk}")
        destino = self.client.get(reverse("contas"))
        self.assertContains(destino, f'id="conta-{conta.pk}"')

    def test_modulo_inativo_nao_vaza_contador_mesmo_que_usuario_tenha_vinculo(self):
        self._tarefa("QA escondido")
        self.gov.ativo = False
        self.gov.save()
        cache.clear()
        resposta = self.client.get(reverse("pendencias"))
        self.assertEqual(resposta.context["total"], 0)
        self.assertNotContains(resposta, "data-governanca-avisos")
        self.assertEqual(self.client.get(url_pendencias("governanca")).status_code, 403)
        self.assertEqual(self.client.get(reverse("governanca:atualizacoes")).status_code, 404)

    def test_paginacao_nao_corta_pendencias_nem_perde_filtros(self):
        for i in range(52):
            self._tarefa(f"QA lista {i:02}")
        # A lista grande não acrescenta uma consulta por quarto ou responsável.
        with self.assertNumQueries(2):
            self.assertEqual(len(governanca.pendencias_operacionais()), 52)
        resposta = self.client.get(url_pendencias("governanca", "pendente") + "&pagina=2")
        self.assertEqual(resposta.context["total"], 52)
        self.assertEqual(len(resposta.context["itens"]), 2)
        self.assertContains(resposta, "origem=governanca&amp;estado=pendente&amp;pagina=1")
        dados = self.client.get(reverse("pendencias_atualizacoes"), {
            "origem": "governanca", "estado": "pendente", "pagina": "2"}).json()
        self.assertEqual(dados["total"], 52)
        self.assertEqual(dados["html"].count("data-pendencia-id="), 2)

    def test_origem_selecionada_nao_consulta_outros_modulos_autorizados(self):
        self._ativar(Modulo.MANUTENCAO, self.usuario)
        self._ativar(Modulo.COMERCIAL, self.usuario)
        self._tarefa("QA origem única")
        with patch("apps.manutencao.services.pendencias_auditoria") as manutencao, patch(
            "apps.comercial.services.pendencias_auditoria") as comercial:
            resposta = self.client.get(url_pendencias("governanca", "pendente"))
            atualizacao = self.client.get(reverse("pendencias_atualizacoes"), {
                "origem": "governanca", "estado": "pendente"})
        self.assertEqual(resposta.context["total"], 1)
        self.assertEqual(atualizacao.json()["total"], 1)
        self.assertEqual({o["codigo"] for o in resposta.context["origens"]}, {
            "governanca", "manutencao", "comercial"})
        manutencao.assert_not_called()
        comercial.assert_not_called()
        with self.assertRaises(PermissionDenied):
            pendencias_usuario(self.usuario, origem="financeiro")

    def test_get_e_polling_nao_criam_configuracao_reservas_ou_estados_de_limpeza(self):
        self._ativar(Modulo.RESERVAS, self.usuario)
        ConfiguracaoReservas.objects.filter(pk=1).delete()
        status_antes = StatusLimpeza.objects.count()
        with CaptureQueriesContext(connection) as consultas:
            dados = pendencias_usuario(self.usuario)
        self.assertEqual(dados["indisponiveis"], [])
        escritas = [q["sql"] for q in consultas if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(escritas, [])
        self.assertEqual(self.client.get(reverse("pendencias")).status_code, 200)
        self.assertEqual(self.client.get(reverse("pendencias_atualizacoes")).status_code, 200)
        self.assertFalse(ConfiguracaoReservas.objects.filter(pk=1).exists())
        self.assertEqual(StatusLimpeza.objects.count(), status_antes)

    def test_falha_de_origem_fica_explicita_sem_fingir_ausencia_de_pendencias(self):
        self._ativar(Modulo.MANUTENCAO, self.usuario)
        self._tarefa("QA permanece")
        with patch("apps.manutencao.services.pendencias_auditoria", side_effect=RuntimeError("falha QA")):
            with self.assertLogs("apps.nucleo.pendencias", level="ERROR"):
                resposta = self.client.get(reverse("pendencias"))
        self.assertContains(resposta, "Não foi possível atualizar Manutenção")
        self.assertContains(resposta, "QA permanece")
        self.assertNotContains(resposta, "falha QA")

    def test_filtros_invalidos_e_autenticacao_nao_sao_bypass(self):
        self.assertEqual(self.client.get(reverse("pendencias"), {"estado": "concluida"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("pendencias_atualizacoes"), {"estado": "concluida"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("pendencias")).status_code, 405)
        self.assertEqual(self.client.post(reverse("pendencias_atualizacoes")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("pendencias")).status_code, 302)
        self.assertEqual(self.client.get(reverse("pendencias_atualizacoes")).status_code, 302)

    def test_origem_autorizada_reusa_interface_publica_e_escapa_descricao(self):
        self._ativar(Modulo.MANUTENCAO, self.usuario)
        achado = {"tipo": "os_antiga", "gravidade": "media", "descricao": '<script>QA</script>', "url": reverse("manutencao:painel")}
        with patch("apps.manutencao.services.pendencias_auditoria", return_value=[achado]) as interface:
            resposta = self.client.get(url_pendencias("manutencao"))
        interface.assert_called_once_with()
        self.assertEqual(resposta.context["total"], 1)
        self.assertContains(resposta, "&lt;script&gt;QA&lt;/script&gt;")
        self.assertNotContains(resposta, '<script>QA</script>')

    def test_quadro_recebe_estados_de_tarefas_da_mesma_fonte(self):
        tarefa = self._tarefa("QA filtro")
        self._tarefa("QA fazendo", TarefaGovernanca.Status.EM_ANDAMENTO)
        resposta = self.client.get(reverse("governanca:quartos"), {"servico": "pendente"})
        self.assertEqual(resposta.context["filtro_servico"], "pendente")
        linha = next(linha for linha in resposta.context["linhas"] if linha["uh"].pk == tarefa.uh_id)
        self.assertEqual(linha["servicos_estados"], ["pendente"])
        self.assertContains(resposta, 'data-servicos-estados="pendente"')
