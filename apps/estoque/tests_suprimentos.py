import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    CategoriaProduto,
    EmbalagemProduto,
    FormaPagamento,
    Fornecedor,
    LocalEstoque,
    LoteEstoque,
    ModuloContratado,
    MovimentoEstoque,
    Pessoa,
    Produto,
    RegistroLote,
    SessaoCaixa,
    Usuario,
    ajustar,
    composicao_estoque,
    contar_lote,
    corrigir_identificacao,
    devolver_ao_estoque,
    devolver_movimentos,
    disponibilidade_produtos,
    identificar_saldo,
    marca_lote,
    registrar_compra,
    registrar_entrada,
    registrar_saida,
    saldo,
    saldo_vendavel,
    saldos_lotes,
    salvar_ficha,
    transferir,
)


class SuprimentosBase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="suprimentos", password="senha-forte-123")
        self.cat = CategoriaProduto.objects.create(nome="Ingredientes QA")
        self.local = LocalEstoque.objects.create(nome="Cozinha QA", modulo="restaurante")
        self.outro = LocalEstoque.objects.create(nome="Depósito QA", modulo="estoque")
        self.produto = Produto.objects.create(nome="Leite QA", categoria=self.cat, unidade="l",
                                              preco_venda=Decimal("9.00"), controla_validade=True)
        self.hoje = timezone.localdate()
        self.curto = self.lote("CURTO", 2)
        self.longo = self.lote("LONGO", 30)
        self.fornecedor = Pessoa.objects.create(nome="Fornecedor fictício QA")
        Fornecedor.objects.create(pessoa=self.fornecedor)
        self.client.force_login(self.user)
        for codigo in ("estoque", "loja", "restaurante"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})

    def lote(self, codigo, dias, produto=None):
        return LoteEstoque.objects.create(produto=produto or self.produto, codigo=codigo,
                                          validade=self.hoje + timedelta(days=dias), criado_por=self.user)

    def entrada(self, quantidade=10, lote=None):
        return registrar_entrada(self.produto, self.local, quantidade, 5, self.user, lote=lote or self.curto)

    def prato(self):
        prato = Produto.objects.create(nome="Café com leite QA", categoria=self.cat, usa_ficha_tecnica=True,
                                        preco_venda=Decimal("12.00"))
        salvar_ficha(prato, [(self.produto, Decimal("0.200"))], self.user)
        prato.refresh_from_db()
        return prato


class LotesTests(SuprimentosBase):
    def test_recebimento_exige_lote_correto_e_nao_aceita_vencido(self):
        vencido = self.lote("VENCIDO", -1)
        for lote in (None, vencido):
            with self.subTest(lote=lote), self.assertRaises(ValidationError):
                registrar_entrada(self.produto, self.local, 10, 5, self.user, lote=lote)
        self.assertEqual(saldo(self.produto), 0)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, 0)

    def test_saida_fefo_ignora_vencidos_e_preserva_saldo_fisico(self):
        self.entrada(3, self.longo)
        self.entrada(2, self.curto)
        movimento = registrar_saida(self.produto, self.local, 4, self.user)
        alocacoes = dict(movimento.lotes.values_list("lote_id", "quantidade"))
        self.assertEqual(alocacoes, {self.curto.pk: Decimal("-2"), self.longo.pk: Decimal("-2")})
        self.assertEqual(saldo(self.produto, self.local), 1)
        with patch("django.utils.timezone.localdate", return_value=self.hoje + timedelta(days=31)):
            self.assertEqual(saldo_vendavel(self.produto, self.local), 0)
            with self.assertRaises(ValidationError):
                registrar_saida(self.produto, self.local, 1, self.user)
        self.assertEqual(saldo(self.produto, self.local), 1)

    def test_transferencia_conserva_lotes_e_vencimento(self):
        self.entrada(2, self.curto)
        self.entrada(3, self.longo)
        saida, entrada = transferir(self.produto, self.local, self.outro, 4, self.user)
        self.assertEqual(saldo(self.produto), 5)
        self.assertEqual(saldo(self.produto, self.local), 1)
        self.assertEqual(list(entrada.lotes.order_by("lote_id").values_list("lote_id", "quantidade")),
                         [(self.curto.pk, Decimal("2")), (self.longo.pk, Decimal("2"))])
        self.assertEqual(saida.transferencia_par_id, entrada.pk)

    def test_devolucao_restaura_lotes_originais_mesmo_depois_do_vencimento(self):
        self.entrada(4)
        saida = registrar_saida(self.produto, self.local, 3, self.user)
        with patch("django.utils.timezone.localdate", return_value=self.hoje + timedelta(days=3)):
            devolver_movimentos([saida.pk], self.user, "Cancelamento QA")
            self.assertEqual(saldo(self.produto, self.local), 4)
            self.assertEqual(saldo_vendavel(self.produto, self.local), 0)
        with self.assertRaises(ValidationError):
            devolver_movimentos([saida.pk], self.user, "Repetido")
        self.assertEqual(saldo(self.produto), 4)

    def test_perda_apos_preparo_reclassifica_os_mesmos_lotes_sem_repor_venda(self):
        self.entrada(4)
        saida = registrar_saida(self.produto, self.local, 2, self.user)
        devolver_movimentos([saida.pk], self.user, "Preparo descartado", perda=True)
        self.assertEqual(saldo(self.produto), 2)
        perda = MovimentoEstoque.objects.get(tipo="perda")
        self.assertEqual(perda.lotes.get().lote_id, self.curto.pk)
        self.assertEqual(perda.lotes.get().quantidade, -2)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 2)

    def test_perda_de_lote_vencido_e_aceita_venda_nao(self):
        self.entrada(4)
        with patch("django.utils.timezone.localdate", return_value=self.hoje + timedelta(days=3)):
            perda = registrar_saida(self.produto, self.local, 1, self.user, tipo="perda", lote=self.curto)
        self.assertEqual(perda.lotes.get().quantidade, -1)
        self.assertEqual(saldo(self.produto), 3)

    def test_identificacao_nao_inventa_saldo_e_reenvio_e_idempotente(self):
        # Mercadoria de antes da ativação permanece sem validade presumida.
        Produto.objects.filter(pk=self.produto.pk).update(controla_validade=False)
        self.produto.refresh_from_db()
        registrar_entrada(self.produto, self.local, 10, 5, self.user)
        self.produto.controla_validade = True
        self.produto.save()
        self.assertEqual(saldo_vendavel(self.produto, self.local), 0)
        chave = uuid.uuid4()
        a = identificar_saldo(self.produto, self.local, self.curto, 7, self.user, "Etiqueta conferida", chave)
        b = identificar_saldo(self.produto, self.local, self.curto, "7.0", self.user, "Etiqueta conferida", chave)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(saldo(self.produto), 10)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 7)
        with self.assertRaises(ValidationError):
            identificar_saldo(self.produto, self.local, self.longo, 4, self.user, "Excesso", uuid.uuid4())

    def test_identificacao_recusa_reuso_da_chave_e_produto_errado(self):
        self.entrada(4)
        with self.assertRaises(ValidationError):
            identificar_saldo(self.produto, self.local, self.curto, 1, self.user, "Já identificado", uuid.uuid4())
        produto = Produto.objects.create(nome="Outro perecível", categoria=self.cat, controla_validade=True)
        errado = self.lote("OUTRO", 4, produto)
        with self.assertRaises(ValidationError):
            registrar_entrada(self.produto, self.local, 2, 3, self.user, lote=errado)
        self.assertEqual(saldo(self.produto), 4)

    def test_contagem_posterior_a_movimento_e_recusada(self):
        self.entrada(4)
        marca = marca_lote(self.curto, self.local)
        registrar_saida(self.produto, self.local, 1, self.user)
        with self.assertRaisesMessage(ValidationError, "movimentado"):
            contar_lote(self.curto, self.local, 4, self.user, "Contagem antiga", uuid.uuid4(), marca)
        self.assertEqual(saldo(self.produto), 3)

    def test_contagem_corrige_so_o_lote_indicado_e_guarda_autoria(self):
        self.entrada(4)
        self.entrada(8, self.longo)
        chave = uuid.uuid4()
        marca = marca_lote(self.curto, self.local)
        a = contar_lote(self.curto, self.local, 3, self.user, "Uma embalagem danificada", chave, marca)
        b = contar_lote(self.curto, self.local, "3.0", self.user, "Uma embalagem danificada", chave, marca)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(saldo(self.produto), 11)
        self.assertEqual({linha["lote_id"]: linha["saldo"] for linha in saldos_lotes(self.produto)},
                         {self.curto.pk: Decimal("3"), self.longo.pk: Decimal("8")})
        with self.assertRaises(ValidationError):
            contar_lote(self.curto, self.local, 8, self.user, "Outra contagem", chave, marca)

    def test_lotes_e_registros_nao_podem_ser_reescritos(self):
        movimento = self.entrada()
        registro = movimento.lotes.get()
        registro.quantidade = 100
        with self.assertRaises(ValidationError):
            registro.save()
        with self.assertRaises(ValidationError):
            registro.delete()
        self.curto.validade = self.hoje + timedelta(days=50)
        with self.assertRaises(ValidationError):
            self.curto.save()

    def test_correcao_de_etiqueta_conserva_saldo_e_historico(self):
        self.entrada(4)
        chave = uuid.uuid4()
        registro = corrigir_identificacao(self.curto, self.longo, self.local, 3, self.user, "Etiqueta conferida", chave)
        repetido = corrigir_identificacao(self.curto, self.longo, self.local, 3, self.user, "Etiqueta conferida", chave)
        self.assertEqual(registro.pk, repetido.pk)
        self.assertEqual(registro.origem_correcao.quantidade, -3)
        self.assertEqual(saldo(self.produto), 4)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)
        self.assertEqual({linha["lote_id"]: linha["saldo"] for linha in saldos_lotes(self.produto)},
                         {self.curto.pk: Decimal("1"), self.longo.pk: Decimal("3")})
        with self.assertRaises(ValidationError):
            corrigir_identificacao(self.curto, self.longo, self.local, 2, self.user, "Excesso", uuid.uuid4())
        with self.assertRaises(ValidationError):
            corrigir_identificacao(self.curto, self.longo, self.local, 4, self.user, "Outra quantidade", chave)

    def test_correcao_incompleta_reverte_as_duas_pernas(self):
        self.entrada(4)
        criar = RegistroLote.objects.create
        def gravar(**kwargs):
            if kwargs.get("origem_correcao"):
                raise ValidationError("Falha QA na contrapartida")
            return criar(**kwargs)
        with patch.object(RegistroLote.objects, "create", side_effect=gravar), self.assertRaises(ValidationError):
            corrigir_identificacao(self.curto, self.longo, self.local, 3, self.user, "Correção QA", uuid.uuid4())
        self.assertEqual(RegistroLote.objects.count(), 1)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 4)

    def test_ajuste_generico_nao_remove_lotes_por_inferencia(self):
        self.entrada(4)
        with self.assertRaisesMessage(ValidationError, "por lote"):
            ajustar(self.produto, self.local, 2, self.user, "Contagem genérica")
        self.assertEqual(saldo(self.produto), 4)

    def test_contagem_nao_duplica_mercadoria_antiga_sem_lote(self):
        Produto.objects.filter(pk=self.produto.pk).update(controla_validade=False)
        self.produto.refresh_from_db()
        registrar_entrada(self.produto, self.local, 4, 5, self.user)
        self.produto.controla_validade = True
        self.produto.save()
        with self.assertRaisesMessage(ValidationError, "Identifique"):
            contar_lote(self.curto, self.local, 4, self.user, "Conferência", uuid.uuid4(), 0)
        self.assertEqual(saldo(self.produto), 4)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 0)


class ComprasEFichasTests(SuprimentosBase):
    def test_embalagem_alterada_depois_de_abrir_tela_exige_nova_conferencia(self):
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Caixa", fator=6)
        with self.assertRaisesMessage(ValidationError, "por embalagem mudou"):
            registrar_compra(embalagem, self.local, 2, 30, self.user, lote=self.curto, fator_conferido=12)
        self.assertEqual(saldo(self.produto), 0)
    def test_compra_converte_embalagem_custo_e_reenvio_conserva_fator_original(self):
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Caixa com 12 litros", fator=12)
        chave = uuid.uuid4()
        dados = dict(lote=self.curto, fornecedor=self.fornecedor, documento="NF QA 123", chave=chave)
        compra = registrar_compra(embalagem, self.local, 2, 60, self.user, **dados)
        self.assertEqual(compra.quantidade, 24)
        self.assertEqual(compra.custo_unitario, 5)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, 5)
        embalagem.fator = 6
        embalagem.save()
        repetido = registrar_compra(embalagem, self.local, "2.0", "60.00", self.user, **dados)
        self.assertEqual(repetido.pk, compra.pk)
        self.assertEqual(saldo(self.produto), 24)
        self.assertEqual(compra.compra["fator"], "12.000")
        with self.assertRaises(ValidationError):
            registrar_compra(embalagem, self.local, 3, 60, self.user, **dados)

    def test_compra_preserva_valor_total_antes_de_arredondar_o_custo_base(self):
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Pacote com três", fator=3)
        mov = registrar_compra(embalagem, self.local, 2, 10, self.user, lote=self.curto)
        self.assertEqual(Decimal(mov.compra["valor_total"]), 20)
        self.assertEqual(mov.custo_unitario, Decimal("3.3333"))
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, Decimal("3.3333"))

    def test_compra_nao_gera_recebimento_financeiro_e_transacao_reverte_lote_e_custo(self):
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Caixa", fator=2)
        with patch("apps.nucleo.models.suprimentos.RegistroLote.objects.create", side_effect=ValidationError("Falha QA")):
            with self.assertRaises(ValidationError):
                registrar_compra(embalagem, self.local, 3, 10, self.user, lote=self.curto)
        self.assertEqual(saldo(self.produto), 0)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, 0)
        self.assertEqual(SessaoCaixa.objects.count(), 0)

    def test_ficha_recusa_ciclos_repeticoes_e_consumo_impreciso(self):
        prato = self.prato()
        outro = Produto.objects.create(nome="Outro prato", categoria=self.cat, usa_ficha_tecnica=True)
        for componentes in ([], [(prato, 1)], [(outro, 1)], [(self.produto, 1), (self.produto, 2)], [(self.produto, "0.0001")]):
            with self.subTest(componentes=componentes), self.assertRaises(ValidationError):
                salvar_ficha(prato, componentes, self.user)
        self.assertEqual(composicao_estoque(prato, 2), {self.produto.pk: Decimal("0.4")})
        with self.assertRaises(ValidationError):
            composicao_estoque(prato, "0.001")

    def test_mudar_unidade_de_produto_movimentado_e_trocar_ingrediente_por_prato_e_barrado(self):
        self.entrada()
        self.produto.unidade = "ml"
        with self.assertRaises(ValidationError):
            self.produto.full_clean()
        self.produto.refresh_from_db()
        self.prato()
        self.produto.controla_validade = False
        self.produto.usa_ficha_tecnica = True
        with self.assertRaises(ValidationError):
            self.produto.full_clean()

    def test_prato_baixa_ingredientes_e_cancelamento_devolve_snapshot_apos_editar_ficha(self):
        from apps.restaurante.services import abrir_comanda, adicionar_item, remover_item

        self.entrada(5)
        prato = self.prato()
        comanda = abrir_comanda(self.user, self.local, rotulo="Mesa QA")
        item = adicionar_item(comanda, prato, 2, self.user)
        self.assertEqual(saldo(self.produto), Decimal("4.6"))
        self.assertEqual(saldo(prato), 0)
        salvar_ficha(prato, [(self.produto, Decimal("0.5"))], self.user)
        remover_item(item, self.user)
        self.assertEqual(saldo(self.produto), 5)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 5)

    def test_editar_quantidade_da_comanda_reverte_baixa_antiga_e_consume_nova(self):
        from apps.restaurante.services import abrir_comanda, adicionar_item, editar_item

        self.entrada(2)
        prato = self.prato()
        comanda = abrir_comanda(self.user, self.local, rotulo="Mesa QA")
        item = adicionar_item(comanda, prato, 1, self.user)
        antigo = item.movimentos_estoque[0]
        editar_item(item, self.user, versao=item.versao, quantidade=3)
        self.assertEqual(saldo(self.produto), Decimal("1.4"))
        item.refresh_from_db()
        self.assertNotIn(antigo, item.movimentos_estoque)
        self.assertTrue(MovimentoEstoque.objects.filter(devolucao_de_id=antigo).exists())

    def test_comanda_agrupa_baixas_e_perda_apos_preparo_nao_repoe_ingredientes(self):
        from apps.restaurante.services import (
            abrir_comanda,
            adicionar_item,
            alterar_preparo,
            remover_item,
        )

        self.entrada(2)
        prato = self.prato()
        comanda = abrir_comanda(self.user, self.local, rotulo="Mesa QA")
        item = adicionar_item(comanda, prato, 1, self.user)
        segundo = adicionar_item(comanda, prato, 2, self.user)
        self.assertEqual(item.pk, segundo.pk)
        self.assertEqual(len(segundo.movimentos_estoque), 2)
        alterar_preparo(segundo, "preparando", self.user, versao=segundo.versao)
        remover_item(segundo, self.user, "Pedido preparado e descartado")
        self.assertEqual(saldo(self.produto), Decimal("1.4"))
        self.assertEqual(saldo_vendavel(self.produto, self.local), Decimal("1.4"))

    def test_pdv_vende_prato_e_cancelamento_restaura_lotes_sem_dobrar_caixa(self):
        from apps.loja.services import cancelar_venda, finalizar_venda

        self.entrada(2)
        prato = self.prato()
        SessaoCaixa.objects.create(operador=self.user, modulo="loja", fundo_troco=0)
        venda = finalizar_venda(self.user, self.local, [{"produto_id": prato.pk, "quantidade": 2}],
                                "caixa", forma=FormaPagamento.objects.get(tipo="dinheiro"), chave=uuid.uuid4())
        self.assertEqual(venda.total, 24)
        self.assertEqual(saldo(self.produto), Decimal("1.6"))
        cancelar_venda(venda, self.user, "Teste de cancelamento")
        self.assertEqual(saldo(self.produto), 2)
        self.assertEqual(saldo_vendavel(self.produto, self.local), 2)
        with self.assertRaises(ValidationError):
            cancelar_venda(venda, self.user, "Repetido")

    def test_falta_de_um_ingrediente_reverte_toda_venda(self):
        from apps.loja.models import Venda
        from apps.loja.services import finalizar_venda

        self.entrada(2)
        prato = self.prato()
        faltante = Produto.objects.create(nome="Café QA", categoria=self.cat)
        salvar_ficha(prato, [(self.produto, Decimal("0.2")), (faltante, 1)], self.user)
        SessaoCaixa.objects.create(operador=self.user, modulo="loja", fundo_troco=0)
        with self.assertRaises(ValidationError):
            finalizar_venda(self.user, self.local, [{"produto_id": prato.pk, "quantidade": 2}],
                             "caixa", forma=FormaPagamento.objects.get(tipo="dinheiro"))
        self.assertEqual(saldo(self.produto), 2)
        self.assertFalse(Venda.objects.exists())

    def test_disponibilidade_considera_ficha_validade_e_consultas_em_lote(self):
        self.entrada(2)
        prato = self.prato()
        produtos = [self.produto, prato]
        with self.assertNumQueries(3):
            valores = disponibilidade_produtos(produtos, self.local)
        self.assertEqual(valores, {self.produto.pk: Decimal("2"), prato.pk: Decimal("10")})
        with patch("django.utils.timezone.localdate", return_value=self.hoje + timedelta(days=3)):
            self.assertEqual(disponibilidade_produtos(produtos, self.local), {self.produto.pk: 0, prato.pk: 0})


class LimitesMotorEstoqueTests(SuprimentosBase):
    def test_todas_operacoes_rejeitam_nao_finitos_excesso_e_fracoes_sem_gravar(self):
        simples = Produto.objects.create(nome="Simples QA", categoria=self.cat)
        for valor in ("NaN", "Infinity", "-Infinity", "1e999999", "1000000000", "0.0001", True, None):
            chamadas = [
                lambda: registrar_entrada(simples, self.local, valor, 1, self.user),
                lambda: registrar_entrada(simples, self.local, 1, valor, self.user),
                lambda: registrar_saida(simples, self.local, valor, self.user),
                lambda: transferir(simples, self.local, self.outro, valor, self.user),
                lambda: ajustar(simples, self.local, valor, self.user),
                lambda: devolver_ao_estoque(simples, self.local, valor, self.user),
            ]
            for indice, chamada in enumerate(chamadas):
                if valor == "0.0001" and indice == 1:
                    continue  # o custo aceita quatro casas
                with self.subTest(valor=valor, operacao=indice), self.assertRaises(ValidationError), transaction.atomic():
                    chamada()
        self.assertEqual(saldo(simples), 0)

    def test_chave_nao_pode_mudar_produto_local_ou_operacao(self):
        chave = uuid.uuid4()
        entrada = registrar_entrada(self.produto, self.local, 4, 5, self.user, lote=self.curto, chave=chave)
        self.assertEqual(registrar_entrada(self.produto, self.local, 4, 5, self.user, lote=self.curto, chave=chave).pk, entrada.pk)
        for chamada in (
            lambda: registrar_saida(self.produto, self.local, 4, self.user, chave=chave),
            lambda: registrar_entrada(self.produto, self.outro, 4, 5, self.user, lote=self.curto, chave=chave),
            lambda: registrar_entrada(self.produto, self.local, 4, 5, self.user, lote=self.longo, chave=chave),
        ):
            with self.assertRaises(ValidationError):
                chamada()
        self.assertEqual(saldo(self.produto), 4)


class TelasSuprimentosTests(SuprimentosBase):
    def urls(self):
        prato = self.prato()
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Caixa QA", fator=12)
        return [
            reverse("estoque:compras"), reverse("estoque:compra_receber"),
            reverse("estoque:produto_suprimentos", args=[self.produto.pk]),
            reverse("estoque:produto_suprimentos", args=[prato.pk]),
            reverse("estoque:embalagem_nova", args=[self.produto.pk]),
            reverse("estoque:embalagem_editar", args=[self.produto.pk, embalagem.pk]),
            reverse("estoque:ficha_editar", args=[prato.pk]), reverse("estoque:lotes"),
            reverse("estoque:lote_novo"), reverse("estoque:lote", args=[self.curto.pk]),
            reverse("estoque:lote_corrigir", args=[self.curto.pk]),
            reverse("estoque:lote_identificar"), reverse("estoque:lote_contar", args=[self.curto.pk, self.local.pk]),
        ]

    def test_telas_abrem_sem_gravar_movimentos(self):
        self.entrada()
        urls = self.urls()
        antes = MovimentoEstoque.objects.count(), RegistroLote.objects.count(), LoteEstoque.objects.count()
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual((MovimentoEstoque.objects.count(), RegistroLote.objects.count(), LoteEstoque.objects.count()), antes)

    def test_estoque_sem_permissao_403_e_modulo_desativado_404(self):
        urls = self.urls()
        comum = Usuario.objects.create_user(username="sem-estoque", password="senha-forte-123")
        self.client.force_login(comum)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.user)
        ModuloContratado.objects.filter(codigo="estoque").update(ativo=False)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_contagem_identificacao_ficha_e_embalagem_exigem_gerencia(self):
        comum = Usuario.objects.create_user(username="operador-estoque", password="senha-forte-123")
        comum.modulos.set(ModuloContratado.objects.filter(codigo="estoque"))
        prato = self.prato()
        self.client.force_login(comum)
        for url in (reverse("estoque:lote_identificar"), reverse("estoque:lote_contar", args=[self.curto.pk, self.local.pk]),
                    reverse("estoque:ficha_editar", args=[prato.pk]), reverse("estoque:embalagem_nova", args=[self.produto.pk])):
            self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertEqual(MovimentoEstoque.objects.count(), 0)

    def test_compra_invalida_preserva_campos_e_devolve_erro_json(self):
        embalagem = EmbalagemProduto.objects.create(produto=self.produto, nome="Caixa QA", fator=12)
        dados = {"chave": str(uuid.uuid4()), "embalagem": embalagem.pk, "local": self.local.pk,
                  "quantidade": "1e999999", "custo_embalagem": "60", "fornecedor": self.fornecedor.pk,
                  "documento": "NF QA que deve permanecer", "observacao": "Nota para conferir", "lote": self.curto.pk}
        url = reverse("estoque:compra_receber")
        resposta = self.client.post(url, dados)
        self.assertContains(resposta, "NF QA que deve permanecer")
        self.assertContains(resposta, "Nota para conferir")
        resposta = self.client.post(url, dados, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertTrue(resposta.json()["errors"])
        self.assertEqual(saldo(self.produto), 0)
        dados["quantidade"] = "2"
        for _ in range(2):
            self.assertRedirects(self.client.post(url, dados), reverse("estoque:compras"))
        self.assertEqual(saldo(self.produto), 24)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_lote_invalido_e_ficha_sem_ingredientes_preservam_formulario(self):
        resposta = self.client.post(reverse("estoque:lote_novo"), {
            "produto": self.produto.pk, "codigo": "CAIXA-QA", "validade": "data impossível",
        }, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(LoteEstoque.objects.count(), 2)
        prato = self.prato()
        resposta = self.client.post(reverse("estoque:ficha_editar", args=[prato.pk]), {
            "ingredientes-TOTAL_FORMS": "0", "ingredientes-INITIAL_FORMS": "0",
            "ingredientes-MIN_NUM_FORMS": "0", "ingredientes-MAX_NUM_FORMS": "100",
        }, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertTrue(prato.ingredientes.exists())

    def test_contagem_http_aplica_uma_vez_e_recusa_tela_antiga(self):
        self.entrada(10)
        url = reverse("estoque:lote_contar", args=[self.curto.pk, self.local.pk])
        dados = {"chave": str(uuid.uuid4()), "marca": marca_lote(self.curto, self.local),
                  "quantidade": "8", "motivo": "Contagem QA"}
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        self.assertEqual(saldo(self.produto), 8)
        dados["chave"] = str(uuid.uuid4())
        self.assertEqual(self.client.post(url, dados, HTTP_X_FORM_PRESERVE="1").status_code, 422)
        self.assertEqual(saldo(self.produto), 8)

    def test_inventario_geral_separa_pereciveis_e_pratos(self):
        from apps.nucleo.models import Inventario

        self.prato()
        simples = Produto.objects.create(nome="Guardanapo QA", categoria=self.cat)
        self.client.post(reverse("estoque:inventarios"), {"local": self.local.pk})
        inventario = Inventario.objects.latest("pk")
        self.assertEqual(list(inventario.itens.values_list("produto_id", flat=True)), [simples.pk])
        self.assertContains(self.client.get(reverse("estoque:inventarios")), "Perecíveis são contados por lote")

    def test_pdv_e_comanda_usam_disponibilidade_dos_ingredientes(self):
        from apps.restaurante.services import abrir_comanda

        self.entrada(2)
        prato = self.prato()
        resposta = self.client.get(reverse("loja:pdv"), {"local": self.local.pk})
        self.assertEqual(resposta.status_code, 200)
        import json
        catalogo = json.loads(resposta.context["produtos_json"])
        self.assertEqual(next(p["saldo"] for p in catalogo if p["id"] == prato.pk), 10)
        comanda = abrir_comanda(self.user, self.local, rotulo="Mesa QA")
        resposta = self.client.get(reverse("restaurante:comanda", args=[comanda.pk]))
        self.assertEqual(resposta.status_code, 200)

    def test_identificadores_invalidos_recebem_400_e_nao_500(self):
        for nome, campo in (("estoque:lote_novo", "produto"), ("estoque:lote_identificar", "lote"),
                             ("estoque:lote_identificar", "local")):
            self.assertEqual(self.client.get(reverse(nome), {campo: "1e999999"}).status_code, 400)
