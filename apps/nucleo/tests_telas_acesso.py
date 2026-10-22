"""Os formulários públicos de acesso também aparecem com uma sessão aberta."""
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import Usuario


class TelasAcessoTests(TestCase):
    def test_recuperacao_com_e_sem_sessao_mostra_conteudo(self):
        usuario = Usuario.objects.create_user(username="acesso-qa", password="forte-123-abc")
        paginas = [("login", [], "Entrar no sistema"),
                   ("senha_esqueci", [], "Esqueci minha senha"),
                   ("senha_enviada", [], "Confira seu e-mail"),
                   ("senha_trocada", [], "Senha trocada"),
                   ("password_reset_confirm", ["invalido", "invalido"], "Link expirado")]
        for conectado in (False, True):
            if conectado:
                self.client.force_login(usuario)
            for nome, args, titulo in paginas:
                with self.subTest(conectado=conectado, pagina=nome):
                    resposta = self.client.get(reverse(nome, args=args))
                    self.assertContains(resposta, f"<h1>{titulo}</h1>", html=True)
