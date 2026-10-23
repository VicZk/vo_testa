"""Regressões: uma edição inválida nunca apaga tarifas nem salva meio quarto."""
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django import forms
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.comercial.models import FichaComercial
from apps.reservas.models import TarifaDayUse, TarifaTemporada, TarifaUnidade
from apps.site.models import VitrineQuarto

from .models import (
    UH,
    ConfiguracaoReservas,
    ConfiguracaoUH,
    ModuloContratado,
    PosicaoCama,
    Temporada,
    TipoUH,
    Usuario,
)


def dados_dos_forms(resposta, nomes):
    dados = {}
    for nome in nomes:
        form = resposta.context[nome]
        if form is None:
            continue
        for campo in form:
            if isinstance(campo.field, forms.FileField):
                continue
            valor = campo.value()
            if valor is not None and valor is not False:
                dados[campo.html_name] = "on" if valor is True else valor
    return dados


class EdicaoPrecosQuartosTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = Usuario.objects.create_superuser(username="precos-atomicos", password="senha-forte-qa-1")
        self.client.force_login(self.user)
        self.tipo = TipoUH.objects.create(nome="Tipo QA", capacidade=2, tarifa_base="300")
        self.uh = UH.objects.create(numero="QA-101", tipo=self.tipo)
        self.baixa = TarifaUnidade.objects.create(uh=self.uh, classificacao="baixa", valor="350",
                                                pessoa_adicional="70", meia="35")
        self.alta = TarifaUnidade.objects.create(uh=self.uh, classificacao="alta", valor="450")
        hoje = timezone.localdate()
        self.temporada = Temporada.objects.create(nome="Feriado QA", classificacao="feriado", inicio=hoje,
                                                  fim=hoje+timedelta(days=3))
        self.especial = TarifaTemporada.objects.create(uh=self.uh, temporada=self.temporada, valor="500")
        self.day = TarifaDayUse.objects.create(classificacao="baixa", valor_adulto="80", valor_meia="40")
        self.cfg = ConfiguracaoReservas.carregar()

    def assert_preco_original(self):
        self.baixa.refresh_from_db()
        self.alta.refresh_from_db()
        self.day.refresh_from_db()
        self.especial.refresh_from_db()
        self.assertEqual(self.baixa.valor, Decimal("350"))
        self.assertEqual(self.alta.valor, Decimal("450"))
        self.assertEqual(self.day.valor_adulto, Decimal("80"))
        self.assertEqual(self.especial.valor, Decimal("500"))

    def dados_quarto(self):
        resposta = self.client.get(reverse("uh_editar", args=[self.uh.pk]))
        dados = dados_dos_forms(resposta, ["form", "config_form", "vitrine_form", "ficha_comercial_form"])
        formset = resposta.context["formset"]
        for form in [formset.management_form, *formset]:
            for campo in form:
                valor = campo.value()
                if valor is not None and valor is not False:
                    dados[campo.html_name] = "on" if valor is True else valor
        dados.update({"tarifa_baixa": "600,00", "adicional_baixa": "90,00", "nome_tematico": "Edição QA"})
        return dados

    def test_get_quarto_nao_cria_cadastros_auxiliares(self):
        self.client.get(reverse("uh_editar", args=[self.uh.pk]))
        self.assertFalse(ConfiguracaoUH.objects.filter(uh=self.uh).exists())
        self.assertFalse(VitrineQuarto.objects.filter(uh=self.uh).exists())
        self.assertFalse(FichaComercial.objects.filter(uh=self.uh).exists())

    def test_quarto_novo_salva_uma_vez_e_abre_a_configuracao(self):
        resposta = self.client.post(reverse("uh_nova"), {"numero": "QA-102", "tipo": self.tipo.pk, "status": "ativa"})
        novo = UH.objects.get(numero="QA-102")
        self.assertRedirects(resposta, reverse("uh_editar", args=[novo.pk]))
        self.assertFalse(ConfiguracaoUH.objects.filter(uh=novo).exists())

    def test_quarto_novo_invalido_nao_cria_e_so_exibe_campos_visiveis(self):
        antes = UH.objects.count()
        resposta = self.client.post(reverse("uh_nova"), {"numero": "QA-102"}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertNotIn("sofá", str(resposta.json()))
        self.assertEqual(UH.objects.count(), antes)

    def test_quarto_valido_salva_junto_configuracao_vitrine_e_tarifa(self):
        dados = self.dados_quarto()
        dados["descricao_curta"] = "Descrição preservada QA"
        resposta = self.client.post(reverse("uh_editar", args=[self.uh.pk]), dados)
        self.assertRedirects(resposta, reverse("estrutura"))
        self.uh.refresh_from_db()
        self.baixa.refresh_from_db()
        self.assertEqual(self.uh.nome_tematico, "Edição QA")
        self.assertEqual(self.baixa.valor, Decimal("600"))
        self.assertEqual(self.baixa.meia, Decimal("35"))
        self.assertEqual(VitrineQuarto.objects.get(uh=self.uh).descricao_curta, "Descrição preservada QA")
        self.assertTrue(ConfiguracaoUH.objects.filter(uh=self.uh).exists())

    def test_campos_invalidos_nao_gravam_nenhuma_parte_do_quarto(self):
        for campo, valor in [("sofa_adultos", "-1"), ("tour_360_url", "endereco-invalido"),
                             ("tarifa_baixa", "NaN"), ("posicoes_cama-0-nome", "x"*41),
                             ("posicoes_cama-TOTAL_FORMS", "quebrado")]:
            with self.subTest(campo=campo):
                dados = self.dados_quarto()
                dados[campo] = valor
                resposta = self.client.post(reverse("uh_editar", args=[self.uh.pk]), dados, HTTP_X_FORM_PRESERVE="1")
                self.assertEqual(resposta.status_code, 422, resposta.content[:600])
                self.assertTrue(resposta.json()["errors"])
                self.uh.refresh_from_db()
                self.assertEqual(self.uh.nome_tematico, "")
                self.assert_preco_original()
                self.assertFalse(ConfiguracaoUH.objects.filter(uh=self.uh).exists())
                self.assertFalse(VitrineQuarto.objects.filter(uh=self.uh).exists())
                self.assertFalse(FichaComercial.objects.filter(uh=self.uh).exists())

    def test_quarto_com_cama_invalida_preserva_a_cama_e_demais_campos(self):
        cama = PosicaoCama.objects.create(uh=self.uh, nome="Cama existente", ordem=0)
        dados = self.dados_quarto()
        dados.update({"posicoes_cama-0-nome": "Nome alterado", "posicoes_cama-0-ordem": "-1"})
        self.assertEqual(self.client.post(reverse("uh_editar", args=[self.uh.pk]), dados).status_code, 200)
        cama.refresh_from_db()
        self.assertEqual(cama.nome, "Cama existente")
        self.assert_preco_original()

    def test_quarto_sem_js_conserva_tarifas_digitadas_apos_erro(self):
        dados = self.dados_quarto()
        dados.update({"sofa_adultos": "-1", "tarifa_alta": "123,45"})
        resposta = self.client.post(reverse("uh_editar", args=[self.uh.pk]), dados)
        self.assertContains(resposta, 'name="tarifa_alta" class="money-mask" value="123,45"')
        self.assert_preco_original()

    def test_post_parcial_de_parametros_nao_apaga_tarifa_alguma(self):
        resposta = self.client.post(reverse("tabela_precos"), {"hora_checkin": "13:30"})
        self.assertEqual(resposta.status_code, 302)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.hora_checkin, time(13, 30))
        self.assert_preco_original()

    def test_numero_invalido_em_qualquer_tarifa_rejeita_toda_tabela(self):
        for valor in ["NaN", "Infinity", "1e9999", "9"*1000, "-1,00", "1,234", "1.23.45", "0,00"]:
            with self.subTest(valor=valor[:30]):
                dados = {f"base_{self.uh.pk}_baixa": "700,00", "du_ad_alta": valor, "hora_checkin": "13:30"}
                resposta = self.client.post(reverse("tabela_precos"), dados, HTTP_X_FORM_PRESERVE="1")
                self.assertEqual(resposta.status_code, 422)
                self.assert_preco_original()
                self.cfg.refresh_from_db()
                self.assertEqual(self.cfg.hora_checkin, time(14, 0))

    def test_parametro_invalido_rejeita_tambem_as_tarifas_validas(self):
        invalidos = {"single_pct": "100,01", "nao_reemb_pct": "101", "iss": "-1",
                    "custo_canal_ota": "999", "taxa_turismo": "1000000,00", "hora_checkout": "25:80",
                    "hora_checkin": "", "no_show_noites": "9"}
        for campo, valor in invalidos.items():
            with self.subTest(campo=campo):
                resposta = self.client.post(reverse("tabela_precos"),
                    {f"base_{self.uh.pk}_baixa": "700,00", campo: valor}, HTTP_X_FORM_PRESERVE="1")
                self.assertEqual(resposta.status_code, 422)
                self.assert_preco_original()

    def test_percentuais_fracionados_preservam_duas_casas(self):
        resposta = self.client.post(reverse("tabela_precos"), {"single_pct": "70,25", "nao_reemb_pct": "12,50"})
        self.assertEqual(resposta.status_code, 302)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.single_fator, Decimal("0.7025"))
        self.assertEqual(self.cfg.nao_reembolsavel_desconto, Decimal("0.1250"))
        self.assertContains(self.client.get(reverse("tabela_precos")), 'name="single_pct" value="70,25"')

    def test_decimal_agrupado_e_decimal_simples_chegam_ao_mesmo_valor(self):
        for bruto in ["1.234,56", "1234.56", "1234,56"]:
            self.assertEqual(self.client.post(reverse("tabela_precos"),
                {f"base_{self.uh.pk}_baixa": bruto}).status_code, 302)
            self.baixa.refresh_from_db()
            self.assertEqual(self.baixa.valor, Decimal("1234.56"))
            self.assertEqual(self.baixa.pessoa_adicional, Decimal("70"))

    def test_vazio_explicito_remove_somente_a_tarifa_indicada(self):
        self.assertEqual(self.client.post(reverse("tabela_precos"),
            {f"base_{self.uh.pk}_baixa": "", f"add_{self.uh.pk}_baixa": "", f"meia_{self.uh.pk}_baixa": ""}).status_code, 302)
        self.assertFalse(TarifaUnidade.objects.filter(pk=self.baixa.pk).exists())
        self.alta.refresh_from_db()
        self.especial.refresh_from_db()
        self.day.refresh_from_db()

    def test_adicional_sem_base_nao_e_descartado_silenciosamente(self):
        for dados in [{f"add_{self.uh.pk}_baixa": "20"},
                      {f"base_{self.uh.pk}_baixa": "", f"add_{self.uh.pk}_baixa": "20"}]:
            self.assertEqual(self.client.post(reverse("tabela_precos"), dados, HTTP_X_FORM_PRESERVE="1").status_code, 422)
            self.assert_preco_original()

    def test_tabela_sem_js_conserva_os_valores_de_todas_as_secoes(self):
        dados = {f"base_{self.uh.pk}_baixa": "712,35", "du_ad_alta": "inválido", "single_pct": "71,25",
                 "custo_canal_ota": "17,25", "hora_checkin": "13:30", "no_show_noites": "2"}
        resposta = self.client.post(reverse("tabela_precos"), dados)
        for texto in ['value="712,35"', 'value="inválido"', 'value="71,25"', 'value="17,25"',
                      'value="13:30"', '<option value="2" selected>']:
            self.assertContains(resposta, texto)
        self.assert_preco_original()

    def test_temporada_invalida_preserva_nome_e_tarifa(self):
        dados = {"nome": "Alterado QA", "classificacao": "feriado", "inicio": self.temporada.inicio,
                 "fim": self.temporada.fim, f"tbase_{self.uh.pk}": "NaN"}
        resposta = self.client.post(reverse("temporada_editar", args=[self.temporada.pk]), dados, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.temporada.refresh_from_db()
        self.assertEqual(self.temporada.nome, "Feriado QA")
        self.assert_preco_original()

    def test_temporada_valida_e_tarifa_salvam_juntas(self):
        dados = {"nome": "Alterado QA", "classificacao": "feriado", "inicio": self.temporada.inicio,
                 "fim": self.temporada.fim, f"tbase_{self.uh.pk}": "1.234,56", f"tadd_{self.uh.pk}": "99,00"}
        self.assertEqual(self.client.post(reverse("temporada_editar", args=[self.temporada.pk]), dados).status_code, 302)
        self.especial.refresh_from_db()
        self.temporada.refresh_from_db()
        self.assertEqual(self.temporada.nome, "Alterado QA")
        self.assertEqual(self.especial.valor, Decimal("1234.56"))

    def test_falha_na_segunda_gravacao_reverte_a_primeira(self):
        dados = {f"base_{self.uh.pk}_baixa": "700", f"base_{self.uh.pk}_temp{self.temporada.pk}": "900"}
        with patch.object(TarifaTemporada.objects, "update_or_create", side_effect=RuntimeError("Falha QA")):
            with self.assertRaisesMessage(RuntimeError, "Falha QA"):
                self.client.post(reverse("tabela_precos"), dados)
        self.assert_preco_original()

    @override_settings(ROTINAS_MONITOR={"frequentes": "monitor-f", "diarias": "monitor-d", "canais": ""})
    def test_monitor_de_canais_so_e_exigido_com_modulo_ativo(self):
        ModuloContratado.objects.update_or_create(codigo="canais", defaults={"ativo": False})
        cache.clear()
        self.assertTrue(self.client.get(reverse("integracoes")).context["monitores"])
        ModuloContratado.objects.filter(codigo="canais").update(ativo=True)
        cache.clear()
        self.assertFalse(self.client.get(reverse("integracoes")).context["monitores"])
