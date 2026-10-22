import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import CategoriaProduto, ModuloContratado, Produto
from apps.nucleo.modulos import Modulo

from .forms import ConfigFiscalProdutoForm
from .models import ConfigFiscalProduto


class CadastroFiscalTests(TestCase):
    def setUp(self):
        ModuloContratado.objects.update_or_create(codigo=Modulo.FISCAL, defaults={"ativo":True})
        self.op = get_user_model().objects.create_superuser(username="fiscal-cadastro", password="teste-local")
        self.produto = Produto.objects.create(nome="Produto fiscal QA", categoria=CategoriaProduto.objects.create(nome="Categoria QA"), natureza="consumo")
        self.url = reverse("fiscal:produto", args=[self.produto.pk])
        self.dados = {"ncm":"22021000", "cfop":"5102", "cst_csosn":"00", "origem":"0", "pis":"01", "cofins":"01", "tributos":'{"pis_aliquota_porcentual":"1.65"}', "conferido":"on"}
        self.client.force_login(self.op)

    def test_cadastro_pelo_formulario_e_preservacao_dos_complementos(self):
        self.assertContains(self.client.get(self.url), "Classificação do produto")
        self.assertEqual(self.client.post(self.url, self.dados).status_code, 302)
        cfg = ConfigFiscalProduto.objects.get(produto=self.produto)
        self.assertEqual(cfg.tributos["pis_situacao_tributaria"], "01")
        form = ConfigFiscalProdutoForm(instance=cfg)
        self.assertEqual(json.loads(form["tributos"].value()), {"pis_aliquota_porcentual":"1.65"})
        self.assertContains(self.client.get(reverse("fiscal:produtos")), "Produto fiscal QA")

    def test_dados_invalidos_e_sem_conferencia_nao_gravam(self):
        for alteracao in ({"ncm":"1"}, {"cfop":"999"}, {"conferido":""},
                          {"tributos":'[]'}, {"tributos":'{"icms_aliquota": NaN}'}, {"tributos":'{"valor_total": 0}'}):
            resposta = self.client.post(self.url, {**self.dados, **alteracao})
            self.assertEqual(resposta.status_code, 200)
            self.assertTrue(resposta.context["form"].errors)
            self.assertFalse(ConfigFiscalProduto.objects.exists())

    def test_permissao_e_modulo_desligado(self):
        usuario = get_user_model().objects.create_user(username="operador-fiscal", password="teste-local")
        usuario.modulos.add(ModuloContratado.objects.get(codigo=Modulo.FISCAL))
        self.client.force_login(usuario)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.op)
        ModuloContratado.objects.update_or_create(codigo=Modulo.FISCAL, defaults={"ativo":False})
        self.assertEqual(self.client.post(self.url, self.dados).status_code, 404)
        self.assertFalse(ConfigFiscalProduto.objects.exists())
