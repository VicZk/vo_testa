from django.test import TestCase
from django.urls import reverse

from .models import Usuario
from .textos import plural


class EstadosVaziosRetomadaTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_superuser(username="vazios", password="teste-local")
        self.client.force_login(self.usuario)

    def test_papeis_preservam_contexto_no_vazio_e_na_busca_sem_resultado(self):
        for perfil, papel, acao in (("hospedes", "hospede", "Novo hóspede"),
                                    ("agencias", "agencia", "Nova agência"),
                                    ("empresas", "empresa", "Nova empresa"),
                                    ("fornecedores", "fornecedor", "Novo fornecedor")):
            with self.subTest(perfil=perfil):
                resposta = self.client.get(reverse(perfil))
                self.assertEqual(resposta.context["acao_vazio"], acao)
                self.assertContains(resposta, reverse("pessoa_nova") + f"?papel={papel}")
                buscada = self.client.get(reverse(perfil), {"q": "<teste>"})
                self.assertEqual(buscada.context["url_vazio"], reverse(perfil))
                self.assertContains(buscada, "Limpar a busca")
                self.assertContains(buscada, "&lt;teste&gt;")
                filtro = self.client.get(reverse("pessoas"), {"papel": perfil, "q": "ausente"})
                self.assertEqual(filtro.context["url_vazio"], reverse("pessoas") + f"?papel={perfil}")

    def test_plural_apresenta_zero_um_e_varios_sem_parenteses(self):
        self.assertEqual(plural(0, "produto"), "produtos")
        self.assertEqual(plural(1, "quarto"), "quarto")
        self.assertEqual(plural(2, "ocupado"), "ocupados")
