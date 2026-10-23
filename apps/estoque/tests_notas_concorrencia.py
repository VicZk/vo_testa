"""Disputas reais de cadastro/recebimento no PostgreSQL, com conexões separadas."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections, models
from django.test import TransactionTestCase

from apps.nucleo.models import (
    Fornecedor,
    ItemNotaEntrada,
    MovimentoEstoque,
    NotaEntrada,
    Pessoa,
    Produto,
    RecebimentoNotaEntrada,
    saldo,
)
from apps.nucleo.notas_entrada import cadastrar_nota_entrada, receber_nota_entrada

from .tests_notas import NotasFixture


class ConcorrenciaNotasTests(NotasFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql", "As garantias de travamento exigem PostgreSQL real.")

    def disputar(self, operacao):
        barreira = threading.Barrier(2)

        def executar(indice):
            close_old_connections()
            try:
                # Força duas conexões de verdade antes de liberar a disputa.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pid = cursor.fetchone()[0]
                barreira.wait(timeout=10)
                try:
                    objeto = operacao(indice)
                    return {"pid": pid, "resultado": "ok", "pk": objeto.pk}
                except ValidationError:
                    return {"pid": pid, "resultado": "recusado"}
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [pool.submit(executar, indice) for indice in range(2)]
            resultados = [futuro.result(timeout=25) for futuro in futuros]
        self.assertNotEqual(resultados[0]["pid"], resultados[1]["pid"])
        return resultados

    def test_duplo_envio_concorrente_do_cadastro_retorna_a_mesma_nota(self):
        dados = self.dados_nota()
        resultados = self.disputar(lambda _: cadastrar_nota_entrada(**dados))
        self.assertEqual([r["resultado"] for r in resultados], ["ok", "ok"])
        self.assertEqual(resultados[0]["pk"], resultados[1]["pk"])
        self.assertEqual((NotaEntrada.objects.count(), ItemNotaEntrada.objects.count()), (1, 1))
        self.conferir_sem_movimento()

    def test_chaves_diferentes_na_mesma_identidade_fiscal_criam_apenas_uma_nota(self):
        dados = self.dados_nota(chave_acesso="2" * 44)
        chaves = [uuid.uuid4(), uuid.uuid4()]
        resultados = self.disputar(lambda i: cadastrar_nota_entrada(**{**dados, "chave": chaves[i]}))
        self.assertCountEqual([r["resultado"] for r in resultados], ["ok", "recusado"])
        self.assertEqual((NotaEntrada.objects.count(), ItemNotaEntrada.objects.count()), (1, 1))
        self.conferir_sem_movimento()

    def test_emitente_duplicado_em_pessoas_distintas_e_barrado_pela_constraint_do_banco(self):
        outro_fornecedor = Pessoa.objects.create(nome="Mesmo emitente em outro cadastro QA", documento="12345678000195")
        Fornecedor.objects.create(pessoa=outro_fornecedor)
        outro_produto = Produto.objects.create(nome="Outro produto da disputa QA", categoria=self.cat)
        dados = [self.dados_nota(numero="NF-UNICA-PG", fornecedor=fornecedor,
                                itens=[self.item_previsto(produto=produto)])
                 for fornecedor, produto in ((self.fornecedor, self.produto), (outro_fornecedor, outro_produto))]
        antes_do_insert = threading.Barrier(2)
        salvar_original = models.Model.save
        conflitos = []

        def salvar_juntos(objeto, *args, **kwargs):
            if not isinstance(objeto, NotaEntrada):
                return salvar_original(objeto, *args, **kwargs)
            # As consultas prévias de identidade e full_clean já terminaram.
            # Pessoas/produtos distintos não se serializam por outro row lock.
            antes_do_insert.wait(timeout=10)
            try:
                return salvar_original(objeto, *args, **kwargs)
            except IntegrityError:
                conflitos.append(True)
                raise

        with patch.object(models.Model, "save", salvar_juntos):
            resultados = self.disputar(lambda i: cadastrar_nota_entrada(**dados[i]))
        self.assertCountEqual([r["resultado"] for r in resultados], ["ok", "recusado"])
        self.assertEqual(len(conflitos), 1)
        self.assertEqual((NotaEntrada.objects.count(), ItemNotaEntrada.objects.count()), (1, 1))
        self.conferir_sem_movimento()

    def test_mesmo_uuid_recebido_simultaneamente_soma_uma_vez(self):
        nota = self.nota()
        item, chave = nota.itens.get(), uuid.uuid4()
        dados = {"parcelas": [self.parcela(item, "3")], "usuario": self.user,
                 "chave": chave, "versao_conferida": 0}
        resultados = self.disputar(lambda _: receber_nota_entrada(nota.pk, **dados))
        self.assertEqual([r["resultado"] for r in resultados], ["ok", "ok"])
        self.assertEqual(resultados[0]["pk"], resultados[1]["pk"])
        self.assertEqual((MovimentoEstoque.objects.count(), RecebimentoNotaEntrada.objects.count()), (1, 1))
        self.assertEqual(saldo(self.produto), 3)
        nota.refresh_from_db()
        self.assertEqual(nota.versao_recebimento, 1)

    def test_duas_abas_com_chaves_distintas_nao_recebem_a_mesma_pendencia(self):
        nota = self.nota()
        parcelas = [self.parcela(nota.itens.get(), "4")]
        chaves = [uuid.uuid4(), uuid.uuid4()]
        resultados = self.disputar(lambda i: receber_nota_entrada(
            nota.pk, parcelas=parcelas, usuario=self.user, chave=chaves[i], versao_conferida=0))
        self.assertCountEqual([r["resultado"] for r in resultados], ["ok", "recusado"])
        self.assertEqual((MovimentoEstoque.objects.count(), RecebimentoNotaEntrada.objects.count()), (1, 1))
        self.assertEqual(saldo(self.produto), 4)
        nota.refresh_from_db()
        self.assertEqual((nota.status, nota.versao_recebimento), ("parcial", 1))

    def test_mesmo_uuid_com_conteudo_divergente_tem_um_vencedor_sem_duplicacao(self):
        nota = self.nota()
        item, chave = nota.itens.get(), uuid.uuid4()
        resultados = self.disputar(lambda i: receber_nota_entrada(
            nota.pk, parcelas=[self.parcela(item, str(i + 1))], usuario=self.user,
            chave=chave, versao_conferida=0))
        self.assertCountEqual([r["resultado"] for r in resultados], ["ok", "recusado"])
        self.assertEqual((MovimentoEstoque.objects.count(), RecebimentoNotaEntrada.objects.count()), (1, 1))
        self.assertIn(saldo(self.produto), (1, 2))
        nota.refresh_from_db()
        self.assertEqual(nota.versao_recebimento, 1)

    def test_notas_distintas_com_produtos_em_ordem_inversa_preservam_saldo_e_custo(self):
        outro = Produto.objects.create(nome="Produto concorrente fictício", categoria=self.cat)
        notas = [
            self.nota(itens=[self.item_previsto(quantidade="2", custo="3"),
                            self.item_previsto(outro, quantidade="2", custo="5")]),
            self.nota(itens=[self.item_previsto(outro, quantidade="2", custo="7"),
                            self.item_previsto(quantidade="2", custo="9")]),
        ]
        dados = [{"parcelas": [self.parcela(item, "2") for item in nota.itens.all()],
                  "usuario": self.user, "chave": uuid.uuid4(), "versao_conferida": 0}
                 for nota in notas]

        resultados = self.disputar(lambda indice: receber_nota_entrada(notas[indice].pk, **dados[indice]))

        self.assertEqual([resultado["resultado"] for resultado in resultados], ["ok", "ok"])
        self.assertEqual((MovimentoEstoque.objects.count(), RecebimentoNotaEntrada.objects.count()), (4, 2))
        for produto in (self.produto, outro):
            produto.refresh_from_db()
            self.assertEqual(saldo(produto), 4)
            self.assertEqual(produto.custo_medio, 6)
        for nota in notas:
            nota.refresh_from_db()
            self.assertEqual((nota.status, nota.versao_recebimento), ("concluida", 1))
