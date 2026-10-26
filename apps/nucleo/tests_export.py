"""CSV pt-BR: o que o Excel abre como número e data, e o que continua neutralizado."""
from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import SimpleTestCase

from apps.nucleo.export import celula, sanitizar_celula


class CelulaCsvTests(SimpleTestCase):
    def test_numero_sai_com_virgula_e_sem_milhar(self):
        self.assertEqual(celula(Decimal("62983.20")), "62983,20")
        self.assertEqual(celula(Decimal("-150.00")), "-150,00")  # negativo segue número
        self.assertEqual(celula(Decimal("-0.00")), "0,00")
        self.assertEqual(celula(5.7), "5,7")  # "5.7" o Excel pt-BR pode ler como data
        self.assertEqual(celula(Decimal("1E+1")), "10")
        self.assertEqual(celula(24), "24")

    def test_data_e_hora_no_fuso_da_casa(self):
        self.assertEqual(celula(datetime(2026, 10, 26, 0, 24, tzinfo=UTC)), "25/10/2026 21:24")
        self.assertEqual(celula(date(2026, 10, 5)), "05/10/2026")
        self.assertEqual((celula(None), celula(True), celula(False)), ("", "Sim", "Não"))

    def test_texto_continua_neutralizado(self):
        self.assertEqual(celula('=HYPERLINK("x")'), "'=HYPERLINK(\"x\")")
        self.assertEqual(sanitizar_celula("-1+1"), "'-1+1")
        self.assertEqual(sanitizar_celula("-R$1"), "'-R$1")  # referência de célula
        # Negativo que o formatador escreve não ganha apóstrofo (o Excel o mostraria).
        self.assertEqual(sanitizar_celula("-R$ 50,50"), "-R$ 50,50")
        self.assertEqual(sanitizar_celula("-1.234,56"), "-1.234,56")
        self.assertEqual(sanitizar_celula("-3,5%"), "-3,5%")
