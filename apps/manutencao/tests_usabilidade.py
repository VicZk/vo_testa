"""Entradas reais de formulário: não transformar erros em uma OS concluída.

Os casos passam pelo contrato progressivo usado pelo navegador. Dados inválidos
devem manter a OS e devolver uma mensagem, preservando o formulário na tela.
"""

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import UH, Fornecedor, ModuloContratado, Pessoa, TipoUH, Usuario
from apps.nucleo.modulos import Modulo

from . import services
from .forms import ConcluirOSForm, NovaOSForm
from .models import OrdemServico


class ManutencaoEntradaUsabilidadeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.observacoes = []

    @classmethod
    def tearDownClass(cls):
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / "manutencao-entradas.json").write_text(
                json.dumps(cls.observacoes, ensure_ascii=False, indent=2), encoding="utf-8")
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        for codigo in (Modulo.MANUTENCAO, Modulo.RESERVAS, Modulo.GOVERNANCA):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="manutencao-uso", password="forte-qa-123")
        self.uh = UH.objects.create(
            numero="MU-01", tipo=TipoUH.objects.create(nome="Manutenção QA", tarifa_base="100.00"))
        self.client.force_login(self.usuario)
        self.client.raise_request_exception = False

    def enviar(self, rota, dados, ordem=None):
        resposta = self.client.post(
            reverse(f"manutencao:{rota}", args=[ordem.pk] if ordem else []), dados,
            HTTP_X_FORM_PRESERVE="1", HTTP_ACCEPT="application/json")
        registro = {"teste": self._testMethodName, "rota": rota, "dados": dados,
                    "status_http": resposta.status_code}
        if resposta.get("Content-Type", "").startswith("application/json"):
            registro["resposta"] = resposta.json()
        elif getattr(resposta, "exc_info", None):
            registro["excecao"] = resposta.exc_info[0].__name__
        registro["ordens"] = list(OrdemServico.objects.values(
            "status", "tipo", "prioridade", "custo_maodeobra", "custo_pecas",
            "previsto_para", "agendada_para", "garantia_ate", "motivo_cancelamento"))
        self.observacoes.append(json.loads(json.dumps(registro, default=str)))
        return resposta

    def nova_valida(self, **extras):
        return {"uh": str(self.uh.pk), "titulo": "Reparar iluminação QA", "tipo": "corretiva",
                "prioridade": "media", **extras}

    def ordem(self, **extras):
        return services.abrir_os(self.usuario, uh=self.uh, titulo="Reparar iluminação QA", **extras)

    def rejeitada(self, resposta):
        self.assertEqual(resposta.status_code, 422)
        self.assertTrue(resposta.json().get("errors"))

    def test_identificadores_textuais_retornam_erro_sem_criar_os(self):
        for campo in ("uh", "responsavel", "prestador"):
            for valor in ("abc", "1.5"):
                with self.subTest(campo=campo, valor=valor):
                    antes = OrdemServico.objects.count()
                    resposta = self.enviar("nova", self.nova_valida(**{campo: valor}))
                    self.assertEqual(OrdemServico.objects.count(), antes)
                    self.rejeitada(resposta)

    def test_identificadores_inexistentes_nao_sao_descartados_silenciosamente(self):
        for campo in ("responsavel", "prestador"):
            with self.subTest(campo=campo):
                antes = OrdemServico.objects.count()
                resposta = self.enviar("nova", self.nova_valida(**{campo: "999999999"}))
                self.assertEqual(OrdemServico.objects.count(), antes)
                self.rejeitada(resposta)

    def test_datas_invalidas_na_abertura_nao_viram_prazo_vazio(self):
        for campo in ("previsto_para", "agendada_para"):
            with self.subTest(campo=campo):
                antes = OrdemServico.objects.count()
                resposta = self.enviar("nova", self.nova_valida(tipo="preventiva", **{campo: "2026-02-30"}))
                self.assertEqual(OrdemServico.objects.count(), antes)
                self.rejeitada(resposta)

    def test_tipo_e_prioridade_desconhecidos_nao_entram_no_banco(self):
        for campo, valor in (("tipo", "outra"), ("prioridade", "maxima")):
            with self.subTest(campo=campo):
                antes = OrdemServico.objects.count()
                resposta = self.enviar("nova", self.nova_valida(**{campo: valor}))
                self.assertEqual(OrdemServico.objects.count(), antes)
                self.rejeitada(resposta)

    def test_recorrencia_fora_do_intervalo_nao_quebra_o_envio(self):
        for valor in ("0", "-1", "32768", "texto"):
            with self.subTest(valor=valor):
                antes = OrdemServico.objects.count()
                resposta = self.enviar("nova", self.nova_valida(tipo="preventiva", recorrencia_meses=valor))
                self.assertEqual(OrdemServico.objects.count(), antes)
                self.rejeitada(resposta)

    def test_titulo_acima_do_limite_mostra_erro_de_formulario(self):
        resposta = self.enviar("nova", self.nova_valida(titulo="A" * 121))
        self.assertEqual(OrdemServico.objects.count(), 0)
        self.rejeitada(resposta)

    def test_custo_invalido_nao_encerra_a_ordem_nem_altera_valores(self):
        for campo in ("custo_maodeobra", "custo_pecas"):
            for valor in ("texto", "NaN", "Infinity", "-1", "100000000.00", "1e100"):
                with self.subTest(campo=campo, valor=valor):
                    ordem = self.ordem()
                    resposta = self.enviar("concluir", {
                        "resolucao": "Lâmpada substituída e conferida QA", campo: valor}, ordem)
                    ordem.refresh_from_db()
                    self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
                    self.assertEqual(ordem.custo_total, Decimal("0.00"))
                    self.rejeitada(resposta)

    def test_valor_brasileiro_com_milhar_nunca_e_concluido_com_zero(self):
        ordem = self.ordem()
        resposta = self.enviar("concluir", {
            "resolucao": "Peças e mão de obra QA", "custo_maodeobra": "1.234,56"}, ordem)
        ordem.refresh_from_db()
        if resposta.status_code == 422:
            self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
            self.assertEqual(ordem.custo_total, Decimal("0.00"))
            self.assertTrue(resposta.json().get("errors"))
        else:
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(ordem.custo_maodeobra, Decimal("1234.56"))

    def test_garantia_invalida_nao_conclui_a_ordem(self):
        ordem = self.ordem()
        resposta = self.enviar("concluir", {"resolucao": "Reparo QA", "garantia_ate": "2026-02-30"}, ordem)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
        self.assertIsNone(ordem.garantia_ate)
        self.rejeitada(resposta)

    def test_numero_de_nota_acima_do_limite_nao_produz_erro_500(self):
        ordem = self.ordem()
        resposta = self.enviar("concluir", {"resolucao": "Reparo QA", "nota_fiscal": "N" * 61}, ordem)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
        self.rejeitada(resposta)

    def test_cancelamento_exige_o_motivo_solicitado_na_tela(self):
        for motivo in ("", "   "):
            with self.subTest(motivo=motivo):
                ordem = self.ordem()
                resposta = self.enviar("cancelar", {"motivo": motivo}, ordem)
                ordem.refresh_from_db()
                self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
                self.rejeitada(resposta)

    def test_reenvio_de_conclusao_preserva_primeiro_resultado_e_uma_sucessora(self):
        from apps.governanca.models import TarefaGovernanca

        ordem = self.ordem(tipo="preventiva", recorrencia_meses=1, agendada_para=date(2026, 1, 31), bloquear=True)
        dados = {"resolucao": "Primeiro reparo QA", "custo_pecas": "12,50", "nota_fiscal": "NF-QA-1"}
        self.assertEqual(self.enviar("concluir", dados, ordem).status_code, 200)
        tarefas = TarefaGovernanca.objects.filter(uh=self.uh, origem="manutencao").count()
        self.assertEqual(self.enviar("concluir", {
            **dados, "resolucao": "Reenvio atrasado QA", "custo_pecas": "999.00"}, ordem).status_code, 200)
        ordem.refresh_from_db()
        self.assertEqual(ordem.resolucao, dados["resolucao"])
        self.assertEqual(ordem.custo_pecas, Decimal("12.50"))
        self.assertEqual(OrdemServico.objects.filter(anterior=ordem).count(), 1)
        self.assertEqual(ordem.sucessora.agendada_para, date(2026, 2, 28))
        self.assertEqual(TarefaGovernanca.objects.filter(uh=self.uh, origem="manutencao").count(), tarefas)

    def test_transicoes_apos_cancelar_nao_reabrem_a_ordem(self):
        ordem = self.ordem()
        self.assertEqual(self.enviar("cancelar", {"motivo": "Chamado duplicado QA"}, ordem).status_code, 200)
        for rota in ("iniciar", "concluir"):
            with self.subTest(rota=rota):
                self.rejeitada(self.enviar(rota, {"resolucao": "Envio atrasado QA"}, ordem))
                ordem.refresh_from_db()
                self.assertEqual(ordem.status, OrdemServico.Status.CANCELADA)

    def test_cancelar_exige_gerencia_mesmo_com_acesso_ao_modulo(self):
        ordem = self.ordem()
        operador = Usuario.objects.create_user(username="manutencao-operador", password="forte-qa-123")
        operador.modulos.add(ModuloContratado.objects.get(codigo=Modulo.MANUTENCAO))
        self.client.force_login(operador)
        resposta = self.enviar("cancelar", {"motivo": "Tentativa sem gerência QA"}, ordem)
        self.assertEqual(resposta.status_code, 403)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)

    def test_conclusao_oferece_campo_de_anexo_real_com_envio_multipart(self):
        ordem = self.ordem()
        resposta = self.client.get(reverse("manutencao:detalhe", args=[ordem.pk]))
        self.assertContains(resposta, 'type="file"')
        self.assertContains(resposta, 'enctype="multipart/form-data"')

    def test_servico_rejeita_erro_sem_deixar_custo_parcial_na_instancia(self):
        ordem = self.ordem()
        with self.assertRaises(ValidationError):
            services.concluir_os(ordem, self.usuario, custo_maodeobra="10.00", custo_pecas="texto")
        self.assertEqual(ordem.custo_maodeobra, Decimal("0.00"))
        self.assertEqual(ordem.status, OrdemServico.Status.ABERTA)
        ordem.refresh_from_db()
        self.assertEqual(ordem.custo_total, Decimal("0.00"))

    def test_servico_aplica_limites_tambem_fora_da_view(self):
        casos = (
            {"titulo": "A" * 121}, {"tipo": "outra"}, {"prioridade": "maxima"},
            {"previsto_para": "2026-02-30"},
            {"tipo": "preventiva", "recorrencia_meses": 0},
            {"tipo": "preventiva", "recorrencia_meses": 121},
            {"tipo": "corretiva", "recorrencia_meses": 1},
            {"tipo": "preventiva", "agendada_para": date(2026, 5, 10), "previsto_para": date(2026, 5, 9)},
            {"tipo": "preventiva", "recorrencia_meses": 1, "agendada_para": date(9999, 12, 31)},
        )
        for dados in casos:
            with self.subTest(dados=dados):
                with self.assertRaises(ValidationError):
                    services.abrir_os(self.usuario, uh=self.uh, **{"titulo": "Reparo QA", **dados})
                self.assertEqual(OrdemServico.objects.count(), 0)

    def test_formulario_somente_aceita_opcoes_disponiveis_na_tela(self):
        inativo = Usuario.objects.create_user(username="inativo-qa", is_active=False)
        pessoa_comum = Pessoa.objects.create(nome="Pessoa sem papel de prestador QA")
        prestador_inativo = Pessoa.objects.create(nome="Fornecedor inativo QA", ativo=False)
        Fornecedor.objects.create(pessoa=prestador_inativo)
        quarto_inativo = UH.objects.create(numero="MU-inativa", tipo=self.uh.tipo, status=UH.Status.INATIVA)
        for campo, objeto in (("uh", quarto_inativo), ("responsavel", inativo),
                              ("prestador", pessoa_comum), ("prestador", prestador_inativo)):
            with self.subTest(campo=campo, pk=objeto.pk):
                form = NovaOSForm(self.nova_valida(**{campo: str(objeto.pk)}))
                self.assertFalse(form.is_valid())
                self.assertIn(campo, form.errors)

    def test_custos_aceitam_brl_e_decimal_sem_perder_centavos(self):
        for texto in ("1.234,56", "1234,56", "1234.56"):
            with self.subTest(valor=texto):
                form = ConcluirOSForm({"custo_maodeobra": texto})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["custo_maodeobra"], Decimal("1234.56"))
                self.assertEqual(form.cleaned_data["custo_pecas"], Decimal("0.00"))
        for texto in ("1.234", "12,345", "1e2", "1e10000", "1,234.56", "  "):
            with self.subTest(invalido=texto):
                form = ConcluirOSForm({"custo_maodeobra": texto})
                self.assertFalse(form.is_valid())
                self.assertIn("custo_maodeobra", form.errors)

    def test_garantia_passada_nao_e_recusada_sem_regra_de_negocio(self):
        form = ConcluirOSForm({"garantia_ate": "2020-01-01"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["garantia_ate"], date(2020, 1, 1))
