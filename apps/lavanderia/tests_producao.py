"""Regras novas da produção da Lavanderia (§8 da especificação).

O que está aqui é o que dói quando erra no balcão: quilo com casa decimal, entrega
antes de a roupa estar pronta, duplo clique no "próximo passo", lote da rouparia pela
metade e preço de serviço que diz "salvo" sem salvar.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.nucleo.models import UH, FormaPagamento, SessaoCaixa, TipoUH, TrilhaAuditoria

from . import services
from .models import ItemEnxoval, MovimentoEnxoval, OrdemLavanderia, ServicoLavanderia

Usuario = get_user_model()
Estado = MovimentoEnxoval.Estado


class ProducaoBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="lav-prod",
                                                   password="senha-forte-123")
        self.camisa = ServicoLavanderia.objects.create(nome="Camisa social",
                                                       preco=Decimal("8.00"))
        self.quilo = ServicoLavanderia.objects.create(
            nome="Roupa por quilo", preco=Decimal("22.00"),
            unidade=ServicoLavanderia.Unidade.KG)
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def ordem_com_pecas(self, **campos):
        ordem = services.abrir_ordem(self.op, rotulo=campos.pop("rotulo", "Quarto 12"),
                                     **campos)
        services.adicionar_item(ordem, self.camisa, 2, self.op)
        return ordem


class QuantidadeDoItemTests(ProducaoBase):
    def test_quilo_grava_com_tres_casas(self):
        ordem = services.abrir_ordem(self.op, rotulo="Quarto 7")
        item = services.adicionar_item(ordem, self.quilo, 1, self.op)
        services.definir_quantidade(item, "3.400", self.op)
        item.refresh_from_db()
        self.assertEqual(item.quantidade, Decimal("3.400"))
        self.assertEqual(ordem.total(), Decimal("74.80"))

    def test_define_em_vez_de_somar(self):
        ordem = self.ordem_com_pecas()
        item = ordem.itens.get()
        services.definir_quantidade(item, 5, self.op)
        item.refresh_from_db()
        self.assertEqual(item.quantidade, Decimal("5"))   # 5, não 2 + 5

    def test_zero_remove_a_linha(self):
        ordem = self.ordem_com_pecas()
        self.assertIsNone(services.definir_quantidade(ordem.itens.get(), 0, self.op))
        self.assertEqual(ordem.itens.count(), 0)

    def test_fora_de_producao_recusa(self):
        ordem = self.ordem_com_pecas()
        item = ordem.itens.get()
        services.cancelar_ordem(ordem, self.op, "desistiu")
        with self.assertRaises(ValidationError):
            services.definir_quantidade(item, 3, self.op)

    def test_quantidade_invalida_recusa(self):
        item = self.ordem_com_pecas().itens.get()
        for valor in ("abc", "-1", "1.2345"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                services.definir_quantidade(item, valor, self.op)

    def test_quantidade_acima_do_teto_da_coluna_avisa_em_vez_de_estourar(self):
        """O campo de peso é texto livre no balcão: 12345678,9 passava pelo validador
        (o teto era 999.999.999,999) e estourava na coluna `numeric(10,3)` — página
        500 em vez de "informe um número"."""
        ordem = self.ordem_com_pecas()
        with self.assertRaises(ValidationError):
            services.adicionar_item(ordem, self.quilo, "12345678.9", self.op)
        item = services.adicionar_item(ordem, self.quilo, 1, self.op)
        with self.assertRaises(ValidationError):
            services.definir_quantidade(item, "12345678.9", self.op)
        self.assertEqual(services.MAXIMO_QUANTIDADE, Decimal("9999999.999"))

    def test_peca_nao_aceita_meia_unidade(self):
        """«0,5» numa camisa de R$ 8,00 cobrava R$ 4,00 e o cartão da fila dizia
        «0 peças» (o contador trunca com `int`): quilo é pesado, peça é contada."""
        ordem = self.ordem_com_pecas()
        with self.assertRaises(ValidationError) as erro:
            services.adicionar_item(ordem, self.camisa, "0.5", self.op)
        self.assertIn("por peça", " ".join(erro.exception.messages))
        with self.assertRaises(ValidationError):
            services.definir_quantidade(ordem.itens.get(), "1.5", self.op)
        # O granel continua aceitando as três casas do peso.
        granel = services.adicionar_item(ordem, self.quilo, "1.5", self.op)
        self.assertEqual(granel.quantidade, Decimal("1.5"))


class EntregaSoDoQueEstaProntoTests(ProducaoBase):
    def setUp(self):
        super().setUp()
        SessaoCaixa.objects.create(operador=self.op, modulo="lavanderia",
                                   fundo_troco=Decimal("0.00"))

    def test_entregar_em_lavando_sem_confirmar_recusa(self):
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        with self.assertRaises(ValidationError) as erro:
            services.entregar(ordem, self.op, "caixa", forma=self.dinheiro)
        self.assertIn("ainda não está pronta", " ".join(erro.exception.messages))
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.LAVANDO)

    def test_entrega_antecipada_confirmada_fica_na_trilha(self):
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        services.entregar(ordem, self.op, "caixa", forma=self.dinheiro, confirmar=True)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.ENTREGUE)
        trilha = TrilhaAuditoria.objects.filter(acao="entrega_antecipada_lavanderia").first()
        self.assertIsNotNone(trilha)
        self.assertEqual(trilha.detalhe["etapa"], OrdemLavanderia.Status.LAVANDO)

    def test_destino_inventado_recusa_antes_de_cobrar(self):
        """Qualquer valor diferente de "caixa" caía no ramo do fólio: a ordem era
        lançada na conta do hóspede por fora do gate do Reservas e gravava um destino
        que depois contava como "conta" no faturamento."""
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        for destino in ("xpto", "", None):
            with self.subTest(destino=destino), self.assertRaises(ValidationError) as erro:
                services.entregar(ordem, self.op, destino, forma=self.dinheiro)
            self.assertIn("Escolha como cobrar", " ".join(erro.exception.messages))
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.PRONTA)
        self.assertEqual(ordem.destino, "")

    def test_desconto_fica_na_trilha(self):
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        services.entregar(ordem, self.op, "caixa", forma=self.dinheiro,
                          desconto=Decimal("4.00"))
        ordem.refresh_from_db()
        self.assertEqual(ordem.total(), Decimal("12.00"))
        trilha = TrilhaAuditoria.objects.filter(acao="desconto_lavanderia").first()
        self.assertIsNotNone(trilha, "ajuste de dinheiro sem trilha")
        self.assertEqual(trilha.detalhe["desconto"], "4.00")

    def test_entrega_na_etapa_pronta_nao_vira_excecao_na_trilha(self):
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        services.entregar(ordem, self.op, "caixa", forma=self.dinheiro)
        self.assertFalse(
            TrilhaAuditoria.objects.filter(acao="entrega_antecipada_lavanderia").exists())


class ProximoPassoTests(ProducaoBase):
    def test_rotulo_do_passo_vem_de_uma_fonte_so(self):
        ordem = self.ordem_com_pecas()
        self.assertEqual(services.proximo_passo(ordem)["rotulo"], "Enviar para lavagem")
        services.avancar_status(ordem)
        self.assertEqual(services.proximo_passo(ordem)["rotulo"], "Marcar como pronta")
        services.avancar_status(ordem)
        passo = services.proximo_passo(ordem)
        self.assertEqual(passo["rotulo"], "Entregar e cobrar")
        self.assertEqual(passo["url_name"], "lavanderia:ordem")   # cobrar exige destino
        services.cancelar_ordem(ordem, self.op, "fim")
        self.assertIsNone(services.proximo_passo(ordem))

    def test_duplo_clique_nao_pula_dois_passos(self):
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem, esperado="recebida")
        with self.assertRaises(ValidationError):
            # O segundo POST do mesmo botão ainda diz "estava recebida".
            services.avancar_status(OrdemLavanderia.objects.get(pk=ordem.pk),
                                    esperado="recebida")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.LAVANDO)


class ObservacaoDaOrdemTests(ProducaoBase):
    def test_grava_cortando_no_limite_da_tela(self):
        ordem = self.ordem_com_pecas()
        services.definir_observacao(ordem, "  Mancha de vinho na manga.  ", self.op)
        ordem.refresh_from_db()
        self.assertEqual(ordem.observacao, "Mancha de vinho na manga.")
        services.definir_observacao(ordem, "x" * 400, self.op)
        ordem.refresh_from_db()
        self.assertEqual(len(ordem.observacao), services.LIMITE_OBSERVACAO)


class TabelaDePrecosTests(ProducaoBase):
    def test_editar_muda_o_preco_de_verdade_e_audita(self):
        services.salvar_servico(self.camisa, self.op, preco="9,50")
        self.camisa.refresh_from_db()
        self.assertEqual(self.camisa.preco, Decimal("9.50"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="preco_lavanderia").exists())

    def test_nome_repetido_recusa_em_vez_de_fingir_sucesso(self):
        with self.assertRaises(ValidationError):
            services.salvar_servico(None, self.op, nome="camisa social", preco="12")
        with self.assertRaises(ValidationError):
            services.salvar_servico(self.quilo, self.op, nome="Camisa social", preco="12")
        self.assertEqual(ServicoLavanderia.objects.count(), 2)

    def test_cria_com_icone_escolhido_e_recusa_icone_inventado(self):
        novo = services.salvar_servico(None, self.op, nome="Terno completo",
                                       preco="30", icone="blazer")
        self.assertEqual(novo.icone, "blazer")
        with self.assertRaises(ValidationError):
            services.salvar_servico(None, self.op, nome="Sapato", preco="10",
                                    icone="sutia")

    def test_desativar_tira_da_grade_e_mantem_no_historico(self):
        services.salvar_servico(self.quilo, self.op, ativo=False)
        self.quilo.refresh_from_db()
        self.assertFalse(self.quilo.ativo)
        self.assertEqual(ServicoLavanderia.objects.filter(ativo=True).count(), 1)


class FilaEPainelTests(ProducaoBase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()

    def test_atrasada_vem_na_frente_da_coluna(self):
        no_prazo = self.ordem_com_pecas(rotulo="Quarto 1",
                                        prazo=self.hoje + timedelta(days=2))
        atrasada = self.ordem_com_pecas(rotulo="Quarto 2",
                                        prazo=self.hoje - timedelta(days=3))
        recebidas = services.filas_de_producao()[0]
        self.assertEqual(recebidas["codigo"], OrdemLavanderia.Status.RECEBIDA)
        self.assertEqual([o.pk for o in recebidas["ordens"]], [atrasada.pk, no_prazo.pk])
        primeira = recebidas["ordens"][0]
        self.assertTrue(primeira.atrasada)
        self.assertEqual(primeira.dias_atraso, 3)
        self.assertEqual(primeira.n_pecas, 2)
        self.assertEqual(primeira.proximo["rotulo"], "Enviar para lavagem")

    def test_filtro_por_etapa_e_por_atraso(self):
        self.ordem_com_pecas(rotulo="Quarto 1", prazo=self.hoje)
        lavando = self.ordem_com_pecas(rotulo="Quarto 2",
                                       prazo=self.hoje - timedelta(days=1))
        services.avancar_status(lavando)
        so_lavando = services.filas_de_producao("lavando")
        self.assertEqual([fila["codigo"] for fila in so_lavando], ["lavando"])
        self.assertEqual([o.pk for o in so_lavando[0]["ordens"]], [lavando.pk])
        atrasadas = services.filas_de_producao(services.ETAPA_ATRASADAS)
        self.assertEqual([o.pk for fila in atrasadas for o in fila["ordens"]], [lavando.pk])

    def test_painel_conta_hoje_atrasada_e_pecas_em_lavagem(self):
        self.ordem_com_pecas(rotulo="Quarto 1", prazo=self.hoje)
        atrasada = self.ordem_com_pecas(rotulo="Quarto 2",
                                        prazo=self.hoje - timedelta(days=1))
        services.avancar_status(atrasada)
        services.adicionar_item(atrasada, self.quilo, "1.500", self.op)
        kpis = services.painel_do_setor()
        self.assertEqual(kpis["para_hoje"], 1)
        self.assertEqual(kpis["atrasadas"], 1)
        self.assertEqual(kpis["pecas_lavando"], 2)
        self.assertEqual(kpis["granel_lavando"], Decimal("1.500"))
        self.assertEqual(kpis["ordens_lavando"], 1)
        self.assertEqual(kpis["contagens"]["todas"], 2)
        self.assertEqual(kpis["contagens"]["recebida"], 1)
        self.assertEqual(kpis["contagens"]["atrasadas"], 1)

    def test_prazos_sugeridos_trazem_hoje_amanha_e_dois_dias(self):
        chips = services.prazos_sugeridos()
        self.assertEqual([chip["rotulo"] for chip in chips],
                         ["Hoje", "Amanhã", "Em 2 dias"])
        self.assertEqual(chips[0]["data"], self.hoje)
        self.assertEqual(chips[2]["data"], self.hoje + timedelta(days=2))
        self.assertTrue(chips[1]["extenso"][:1].isupper())

    def test_trilha_carimba_a_hora_de_cada_passo(self):
        """Cada passo grava a sua hora: a trilha responde "a que horas foi para a
        máquina?" com horário, em vez de escrever «Cumprido» no lugar do carimbo."""
        ordem = self.ordem_com_pecas()
        services.avancar_status(ordem)
        passos = services.trilha_da_ordem(ordem)
        self.assertEqual([passo["codigo"] for passo in passos],
                         ["recebida", "lavando", "pronta", "entregue"])
        self.assertIsNotNone(passos[0]["carimbo"])
        self.assertTrue(passos[0]["feito"])
        self.assertTrue(passos[1]["atual"])
        self.assertIsNotNone(passos[1]["carimbo"])      # foi para a máquina agora
        self.assertEqual(passos[1]["carimbo"], ordem.lavando_em)
        self.assertIsNone(passos[2]["carimbo"])         # ainda não ficou pronta
        services.avancar_status(ordem)
        ordem.refresh_from_db()
        self.assertIsNotNone(ordem.pronta_em)
        self.assertEqual(services.trilha_da_ordem(ordem)[2]["carimbo"], ordem.pronta_em)

    def test_ordem_vazia_nao_avanca(self):
        """Ordem sem peça chegava a «Pronta» com a cesta dizendo "Nenhuma peça
        lançada" — e o que não foi contado não é cobrado."""
        vazia = services.abrir_ordem(self.op, rotulo="Quarto 13")
        with self.assertRaises(ValidationError) as erro:
            services.avancar_status(vazia)
        self.assertIn("ao menos uma peça", " ".join(erro.exception.messages))
        vazia.refresh_from_db()
        self.assertEqual(vazia.status, OrdemLavanderia.Status.RECEBIDA)


class LoteDaRoupariaTests(ProducaoBase):
    def setUp(self):
        super().setUp()
        # O banco já nasce com os quartos da pousada (migração de estrutura): a conta do
        # alvo é sobre TODOS os quartos ativos, não só os criados aqui.
        tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        for numero in ("QA Quarto 01", "QA Quarto 02"):
            UH.objects.create(numero=numero, tipo=tipo)
        self.quartos = services.quartos_ativos()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol casal", minimo=10,
                                                 por_faxina=1)
        self.toalha = ItemEnxoval.objects.create(nome="Toalha de banho", minimo=10,
                                                 por_faxina=2)

    def test_lote_move_todos_os_itens_marcados(self):
        for item in (self.lencol, self.toalha):
            services.adquirir(item, 20, self.op)
        services.mover_lote([self.lencol, self.toalha], "distribuir", 5, self.op)
        for item in (self.lencol, self.toalha):
            self.assertEqual(services.saldo_enxoval(item, Estado.EM_USO), 5)

    def test_um_item_sem_saldo_derruba_o_lote_inteiro(self):
        services.adquirir(self.lencol, 20, self.op)
        services.adquirir(self.toalha, 2, self.op)
        movimentos_antes = MovimentoEnxoval.objects.count()
        with self.assertRaises(ValidationError):
            services.mover_lote([self.lencol, self.toalha], "distribuir", 5, self.op)
        self.assertEqual(MovimentoEnxoval.objects.count(), movimentos_antes)
        self.assertEqual(services.saldo_enxoval(self.lencol, Estado.EM_USO), 0)

    def test_acao_e_quantidade_invalidas_recusam(self):
        services.adquirir(self.lencol, 5, self.op)
        for acao, quantidade in (("inventar", 1), ("distribuir", 0), ("distribuir", "x")):
            with self.subTest(acao=acao, quantidade=quantidade), \
                    self.assertRaises(ValidationError):
                services.mover_lote([self.lencol], acao, quantidade, self.op)
        with self.assertRaises(ValidationError):
            services.mover_lote([], "distribuir", 1, self.op)

    def test_quartos_ativos_nao_conta_quarto_inativo(self):
        inativa = UH.objects.first()
        inativa.status = UH.Status.INATIVA
        inativa.save(update_fields=["status"])
        self.assertEqual(services.quartos_ativos(), self.quartos - 1)

    def test_posicao_traz_barra_fora_e_alvo(self):
        services.adquirir(self.lencol, 10, self.op)
        services.distribuir(self.lencol, 6, self.op)
        services.coletar_suja(self.lencol, 2, self.op)
        linha = next(linha for linha in services.posicao_enxoval() if linha["item"] == self.lencol)
        self.assertEqual(linha["total"], 10)
        self.assertEqual(linha["fora"], 6)
        self.assertEqual(sum(fatia["pct"] for fatia in linha["barra"]), 100)
        self.assertEqual([fatia["rotulo"] for fatia in linha["barra"]],
                         ["Limpa", "Em uso", "Suja", "Lavando"])
        self.assertTrue(linha["abaixo_minimo"])        # 4 limpas < alvo 10

    def test_barra_vazia_quando_o_item_nao_tem_peca(self):
        linha = next(linha for linha in services.posicao_enxoval() if linha["item"] == self.toalha)
        self.assertEqual([fatia["pct"] for fatia in linha["barra"]], [0, 0, 0, 0])


class ExtratoDoEnxovalTests(ProducaoBase):
    def setUp(self):
        super().setUp()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol casal", por_faxina=1)
        self.toalha = ItemEnxoval.objects.create(nome="Toalha de rosto", por_faxina=1)
        services.adquirir(self.lencol, 10, self.op)
        services.distribuir(self.lencol, 4, self.op)
        services.adquirir(self.toalha, 5, self.op)

    def test_filtra_por_item_e_por_estado(self):
        self.assertEqual(services.extrato_enxoval().count(), 4)
        self.assertEqual(services.extrato_enxoval(item=self.toalha.pk).count(), 1)
        self.assertEqual(
            services.extrato_enxoval(estado=Estado.EM_USO).count(), 1)

    def test_filtra_por_periodo(self):
        hoje = timezone.localdate()
        self.assertEqual(services.extrato_enxoval(de=hoje, ate=hoje).count(), 4)
        self.assertEqual(
            services.extrato_enxoval(de=hoje + timedelta(days=1)).count(), 0)

    def test_motivo_nunca_aparece_cru(self):
        self.assertEqual(services.rotulo_motivo("envio_lavagem"), "Envio para lavagem")
        self.assertEqual(services.rotulo_motivo("retorno_lavagem"), "Retorno da lavagem")
        self.assertEqual(services.rotulo_motivo("distribuicao"), "Distribuição")
        self.assertEqual(services.rotulo_motivo("faxina"), "Faxina")
        self.assertEqual(services.rotulo_motivo("aquisicao"), "Aquisição")
        self.assertEqual(services.rotulo_motivo("coleta"), "Coleta")
        self.assertEqual(services.rotulo_motivo("baixa:desgaste"), "Baixa — desgaste")
        self.assertEqual(services.rotulo_motivo("motivo_novo"), "Motivo novo")

    def test_estado_nunca_aparece_cru(self):
        self.assertEqual(services.rotulo_estado("em_uso"), "Em uso")
        self.assertEqual(services.rotulo_estado("limpa"), "Limpa")
