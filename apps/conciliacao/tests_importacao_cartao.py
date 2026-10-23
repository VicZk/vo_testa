"""A reimportação de vendas não deve duplicar recebimentos nem perder datas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase

from .models import LoteCartao, TransacaoCartao
from .services import importar_cartao_csv
from .tests import CSV_CARTAO


class ImportacaoCartaoIdempotenteTests(TestCase):
    def test_reimportacao_nao_duplica_mesmo_com_nome_de_arquivo_diferente(self):
        primeiro = importar_cartao_csv(conteudo=CSV_CARTAO, arquivo_nome="vendas.csv")
        segundo = importar_cartao_csv(conteudo=CSV_CARTAO, arquivo_nome="vendas-copia.csv")
        self.assertEqual(primeiro["novos"], 1)
        self.assertEqual(segundo["novos"], 0)
        self.assertEqual(segundo["ignorados"], 1)
        self.assertEqual(TransacaoCartao.objects.count(), 1)

    def test_utf8_com_bom_e_latin1_preservam_data_da_liquidacao(self):
        for codificacao in ("utf-8-sig", "latin-1"):
            with self.subTest(codificacao=codificacao):
                importar_cartao_csv(conteudo=CSV_CARTAO.encode(codificacao), adquirente=codificacao)
                transacao = TransacaoCartao.objects.get(lote__adquirente=codificacao)
                self.assertEqual(transacao.data_liquidacao, date(2026, 9, 11))
                self.assertEqual(transacao.liquido, Decimal("195"))

    def test_nsu_em_outra_data_adquirente_ou_parcela_nao_e_descartado(self):
        importar_cartao_csv(conteudo=CSV_CARTAO)
        importar_cartao_csv(conteudo=CSV_CARTAO, adquirente="Outra adquirente")
        importar_cartao_csv(conteudo=CSV_CARTAO.replace("10/09/2026", "12/09/2026"))
        importar_cartao_csv(conteudo=CSV_CARTAO.replace("11/09/2026", "11/10/2026"))
        self.assertEqual(TransacaoCartao.objects.count(), 4)

    def test_linha_anterior_a_chave_e_reutilizada_sem_alterar_estado(self):
        lote = LoteCartao.objects.create(adquirente="SafraPay")
        original = TransacaoCartao.objects.create(
            lote=lote, nsu="NSU123", bruto=Decimal("200"), taxa=Decimal("5"),
            liquido=Decimal("195"), data_venda=date(2026, 9, 10),
            data_liquidacao=date(2026, 9, 11), bandeira="Visa", status="sem_venda",
        )
        resultado = importar_cartao_csv(conteudo=CSV_CARTAO)
        self.assertEqual(resultado["novos"], 0)
        self.assertEqual(TransacaoCartao.objects.count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.status, "sem_venda")


class ImportacaoCartaoConcorrenteTests(TransactionTestCase):
    def test_duas_importacoes_simultaneas_criam_uma_transacao(self):
        barreira = Barrier(2)

        def importar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return importar_cartao_csv(conteudo=CSV_CARTAO)["novos"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: importar(), range(2)))
        self.assertEqual(sorted(resultados), [0, 1])
        self.assertEqual(TransacaoCartao.objects.count(), 1)
