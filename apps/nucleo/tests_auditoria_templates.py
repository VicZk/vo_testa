"""Regressões de apresentação que poderiam alterar valores ou perder campos."""
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from django import forms
from django.conf import settings
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from apps.estoque.campos import DecimalBRField
from apps.estoque.forms import ProdutoForm
from apps.estoque.forms_suprimentos import CompraForm, IngredienteForm
from apps.site.auditoria_fixtures import criar_cenario_templates


class CamposHTML(HTMLParser):
    def __init__(self, texto):
        super().__init__()
        self.nomes = set()
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"input", "select", "textarea"} and "name" in attrs:
            self.nomes.add(attrs["name"])


class AuditoriaTemplatesTests(TestCase):
    def setUp(self):
        self.c = criar_cenario_templates()
        self.client.force_login(self.c.usuario)

    def test_templates_crm_compilam(self):
        raiz = Path(settings.BASE_DIR) / "templates"
        for arquivo in raiz.rglob("*.html"):
            with self.subTest(template=arquivo.relative_to(raiz).as_posix()):
                get_template(arquivo.relative_to(raiz).as_posix())

    def test_pagina_e_modal_da_reserva_preservam_os_mesmos_campos(self):
        pagina = self.client.get(reverse("reservas:nova"))
        modal = self.client.get(reverse("reservas:nova"), HTTP_HX_REQUEST="true")
        campos_pagina = CamposHTML(pagina.content.decode()).nomes
        campos_modal = CamposHTML(modal.content.decode()).nomes
        for nome in campos_modal - {"csrfmiddlewaretoken"}:
            self.assertIn(nome, campos_pagina)
        for resposta in (pagina, modal):
            self.assertContains(resposta, 'id="tarifa-hint"')
            self.assertContains(resposta, 'id="bloco-novo-hospede"')
            self.assertContains(resposta, 'name="hospede"')
            self.assertContains(resposta, 'name="titular"')

    def test_reenvio_invalido_da_reserva_mantem_dados_nas_duas_apresentacoes(self):
        dados = {"hospede": self.c.pessoa.pk, "uh": self.c.uh.pk,
                 "checkin": "2030-05-10", "checkout": "2030-05-09", "adultos": 2,
                 "criancas_6_15": 0, "criancas_0_5": 0, "faturamento": "particular",
                 "canal": "direto", "observacoes": "Preservar esta observação de conferência."}
        for headers in ({}, {"HTTP_HX_REQUEST": "true"}):
            resposta = self.client.post(reverse("reservas:nova"), dados, **headers)
            self.assertEqual(resposta.status_code, 200)
            self.assertContains(resposta, dados["observacoes"])
            self.assertContains(resposta, 'value="2030-05-10"')
            self.assertTrue(resposta.context["form"].errors)

    def test_perfil_de_pessoa_mantem_links_para_os_demais_papeis(self):
        resposta = self.client.get(reverse("hospedes"), {"q": "Ana"})
        self.assertContains(resposta, 'aria-label="Tipos de pessoa"')
        self.assertContains(resposta, reverse("pessoas") + "?q=Ana&papel=fornecedores")
        self.assertNotContains(resposta, 'class="num c-doc"')

    def test_titulos_identificam_tipo_e_temporada_editados(self):
        for rota, objeto in (("tipo_uh_editar", self.c.tipo), ("temporada_editar", self.c.temporada)):
            resposta = self.client.get(reverse(rota, args=[objeto.pk]))
            self.assertContains(resposta, f"Editar {objeto.nome}")

    def test_percentuais_dos_relatorios_nao_exibem_ponto_decimal(self):
        from apps.relatorios.services import rel_ocupacao
        with patch("apps.reservas.services.relatorio_ocupacao", return_value={
            "taxa": Decimal("33.3"), "adr": Decimal("348.90"), "revpar": Decimal("116.30"),
            "ocupadas": 1, "disponiveis": 3, "por_tipo": {"Suíte": 1},
        }):
            self.assertEqual(rel_ocupacao(self.c.hoje, self.c.hoje)["kpis"][0], ("Ocupação", "33,3%"))

    def test_decimal_portugues_preserva_tres_e_quatro_casas(self):
        custo = CompraForm.base_fields["custo_embalagem"]
        quantidade = IngredienteForm.base_fields["quantidade"]
        for valor in ("2,3456", "2.3456"):
            self.assertEqual(custo.clean(valor), Decimal("2.3456"))
        self.assertEqual(custo.clean("1.234,5678"), Decimal("1234.5678"))
        for valor in ("12,345", "12.345"):
            self.assertEqual(quantidade.clean(valor), Decimal("12.345"))
        with self.assertRaises(forms.ValidationError):
            custo.clean("2,34567")
        self.assertEqual(DecimalBRField(decimal_places=3).widget.format_value(Decimal("1.234")), "1,234")

    def test_produto_aceita_virgula_sem_mudar_escala_do_preco(self):
        form = ProdutoForm({
            "nome": "Produto da conferência de decimal", "categoria": self.c.categoria.pk,
            "unidade": "un", "natureza": "consumo", "preco_venda": "18,90",
            "estoque_minimo": "5,125", "ativo": "on", "icone_catalogo": "package",
        })
        self.assertTrue(form.is_valid(), form.errors)
        produto = form.save()
        self.assertEqual(produto.preco_venda, Decimal("18.90"))
        self.assertEqual(produto.estoque_minimo, Decimal("5.125"))

    def test_seletores_de_suprimentos_tem_rotulo_legivel(self):
        for nome, campo in CompraForm().fields.items():
            if isinstance(campo, forms.ModelChoiceField) and campo.empty_label is not None:
                self.assertNotEqual(campo.empty_label, "---------", nome)

    def test_decimal_invalido_preserva_texto_curto_sem_expandir_expoente(self):
        for entrada in ("1e10000000", "1e-10000000"):
            with self.subTest(entrada=entrada):
                resposta = self.client.post(reverse("estoque:produto_editar", args=[self.c.produto.pk]), {
                    "nome": self.c.produto.nome, "categoria": self.c.categoria.pk,
                    "unidade": "un", "natureza": "consumo", "preco_venda": entrada,
                    "estoque_minimo": "5,125", "ativo": "on", "icone_catalogo": "package",
                })
                self.assertEqual(resposta.status_code, 200)
                form = resposta.context["form"]
                self.assertIn("preco_venda", form.errors)
                self.assertContains(resposta, f'value="{entrada}"')
                self.assertLess(len(str(form["preco_venda"])), 512)
                self.c.produto.refresh_from_db()
                self.assertEqual(self.c.produto.preco_venda, Decimal("18.90"))

    def test_relatorio_marketing_sem_gastos_tem_estado_vazio(self):
        resposta = self.client.get(reverse("marketing:relatorio"))
        self.assertContains(resposta, "Nenhum gasto registrado nos meses exibidos.")
        self.assertNotContains(resposta, '<div class="mk-barras">')
