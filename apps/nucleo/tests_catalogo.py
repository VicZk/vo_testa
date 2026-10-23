"""Identificação dos produtos, escolha explícita e publicação sob prefixo."""

import json
from decimal import Decimal

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.estoque.forms import ProdutoForm
from apps.nucleo.catalogo import ilustracao_produto
from apps.nucleo.models import CategoriaProduto, LocalEstoque, ModuloContratado, Produto, Usuario


class IlustracaoCatalogoTests(SimpleTestCase):
    def test_nomes_reconhecidos_sem_depender_de_acento_marca_ou_abreviacao(self):
        casos = {
            "Coca-Cola lata 350 ml": "cup-soda", "PEPSI zero": "cup-soda",
            "Água c/ gás": "bubbles", "agua com gas 500ml": "bubbles",
            "Água s/ gás": "glass-water", "Água sem gás": "glass-water",
            "Água gasosa": "bubbles", "Café c/ leite": "coffee",
            "Cappuccino": "coffee", "Leite integral": "milk", "Suco de laranja": "citrus",
            "Cerveja artesanal": "beer", "Vinho tinto": "wine", "Caipirinha": "martini",
            "Hambúrguer colonial": "sandwich", "Pizza margherita": "pizza",
            "Camarões": "fish", "Salada da horta": "salad", "Caldo verde": "soup",
            "Bolo de chocolate": "cake", "Pão francês": "croissant", "Biscoito integral": "cookie",
            "Pipoca salgada": "popcorn", "Chocolate ao leite": "candy", "Bolo de café": "cake",
            "Bebida Coca-Cola": "cup-soda", "Arroz com leite": "wheat",
            "Banana": "apple", "Protetor solar": "spray-can", "Camiseta": "shirt",
        }
        for nome, esperado in casos.items():
            with self.subTest(nome=nome):
                self.assertEqual(ilustracao_produto(nome)["icone"], esperado)

    def test_nome_tem_prioridade_e_categoria_cobre_produto_sem_palavra_conhecida(self):
        self.assertEqual(ilustracao_produto("Café da casa", "Bebidas")["icone"], "coffee")
        self.assertEqual(ilustracao_produto("Especial da casa", "Sobremesas")["icone"], "cake")
        self.assertEqual(ilustracao_produto("Item sem classificação", "Diversos")["icone"], "package")

    def test_escolha_explicita_e_limitada_a_catalogo_local(self):
        self.assertEqual(ilustracao_produto("Água com gás", escolha="coffee")["icone"], "coffee")
        for malicioso in ("../../segredo", "https://fora.example/icone", "<svg/onload=alert(1)>"):
            self.assertEqual(ilustracao_produto("Água", escolha=malicioso)["icone"], "glass-water")


class CatalogoHttpTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="catalogo", password="senha-qa")
        self.client.force_login(self.op)
        for codigo in ("loja", "estoque", "restaurante"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.categoria = CategoriaProduto.objects.create(nome="Bebidas QA")
        LocalEstoque.objects.create(nome="Balcão QA", modulo="loja")
        self.produto = Produto.objects.create(nome="Coca-Cola 350 ml", categoria=self.categoria, preco_venda="7.50")

    def dados(self, **alteracoes):
        return {"nome": self.produto.nome, "categoria": self.categoria.pk, "unidade": "un",
                "natureza": "consumo", "preco_venda": "7.50", "estoque_minimo": "0", "ativo": "on",
                "icone_catalogo": "coffee", **alteracoes}

    def test_formulario_invalido_preserva_icone_sem_alterar_produto(self):
        resposta = self.client.post(reverse("estoque:produto_editar", args=[self.produto.pk]),
                                    self.dados(preco_venda="NaN"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["form"]["icone_catalogo"].value(), "coffee")
        self.assertEqual(resposta.context["produto"].preco_venda, Decimal("7.50"))
        self.assertEqual(resposta.context["form"]["preco_venda"].value(), "NaN")
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.icone_catalogo, "")
        self.assertEqual(self.produto.preco_venda, Decimal("7.50"))

    def test_escolha_e_gravada_e_pdv_usa_o_mesmo_cadastro(self):
        resposta = self.client.post(reverse("estoque:produto_editar", args=[self.produto.pk]), self.dados())
        self.assertRedirects(resposta, reverse("estoque:produtos"))
        dados = json.loads(self.client.get(reverse("loja:pdv")).context["produtos_json"])
        self.assertEqual(dados[0]["ilustracao"]["icone"], "coffee")
        self.assertEqual(dados[0]["nome"], self.produto.nome)
        self.assertEqual(dados[0]["preco"], 7.5)
        self.assertEqual(dados[0]["saldo"], 0)

    def test_formulario_recusa_caminho_ou_url_como_icone(self):
        form = ProdutoForm(data=self.dados(icone_catalogo="https://fora.example/icone.svg"), instance=self.produto)
        self.assertFalse(form.is_valid())
        self.assertIn("icone_catalogo", form.errors)

    @override_settings(STATIC_URL="/votesta/static/")
    def test_icone_respeita_caminho_estatico_da_instalacao(self):
        resposta = self.client.get(reverse("loja:pdv"))
        self.assertContains(resposta, "/votesta/static/vendor/lucide/catalogo.svg")
        resposta = self.client.get(reverse("estoque:produtos"))
        self.assertContains(resposta, '/votesta/static/vendor/lucide/catalogo.svg#cup-soda')
        resposta = self.client.get(reverse("estoque:produto_editar", args=[self.produto.pk]))
        self.assertContains(resposta, 'data-sprite="/votesta/static/vendor/lucide/catalogo.svg"')
