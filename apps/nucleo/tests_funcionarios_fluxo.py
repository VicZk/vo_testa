"""Ficha e login são uma operação: validar antes de criar ou alterar registros."""

from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Funcionario, ModuloContratado, Pessoa, Usuario


class FluxoFuncionarioTests(TestCase):
    def setUp(self):
        self.gestor = Usuario.objects.create_superuser(username="gestor-ficha-qa", password="senha-qa")
        self.client.force_login(self.gestor)
        self.modulo, _ = ModuloContratado.objects.update_or_create(codigo="reservas", defaults={"ativo": True})

    def dados(self, **alteracoes):
        return {"nome": "Equipe fictícia QA", "cargo": "Recepção", "username": "equipe-ficha-qa",
                "password": "Senha-ficticia-123", "ativo": "on", "modulos": ["reservas"], **alteracoes}

    def test_login_invalido_nao_cria_pessoa_funcionario_nem_login(self):
        for alteracoes in ({"username": self.gestor.username}, {"username": "login com espaço"},
                           {"password": ""}, {"password": "curta"}, {"username": ""},
                           {"nome": " "}, {"nome": "X" * 301}, {"documento": "1" * 19}):
            with self.subTest(alteracoes=alteracoes):
                resposta = self.client.post(reverse("funcionario_novo"), self.dados(**alteracoes),
                    HTTP_X_FORM_PRESERVE="1")
                self.assertEqual(resposta.status_code, 422)
                self.assertTrue(resposta.json()["errors"])
                self.assertFalse(Pessoa.objects.exists())
                self.assertFalse(Funcionario.objects.exists())
                self.assertEqual(Usuario.objects.count(), 1)

    def test_erro_sem_javascript_preserva_campos_e_acessos_sem_reexibir_senha(self):
        resposta = self.client.post(reverse("funcionario_novo"), self.dados(username=self.gestor.username,
            documento="Documento fictício", areas=["logbook"], gerente="on"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Já existe um usuário com esse login.")
        self.assertEqual(resposta.context["nome_preenchido"], "Equipe fictícia QA")
        self.assertEqual(resposta.context["documento_preenchido"], "Documento fictício")
        self.assertTrue(resposta.context["ativo_marcado"])
        self.assertTrue(resposta.context["gerente_marcado"])
        self.assertTrue(next(m for m in resposta.context["modulos"] if m["codigo"] == "reservas")["tem"])
        self.assertTrue(next(a for a in resposta.context["areas"] if a["codigo"] == "logbook")["tem"])
        self.assertNotContains(resposta, "Senha-ficticia-123")

    def test_erro_na_edicao_nao_altera_pessoa_rh_senha_nem_permissoes(self):
        usuario = Usuario.objects.create_user(username="equipe-existente-qa", password="Senha-original-123", areas=["logbook"])
        usuario.modulos.add(self.modulo)
        funcionario = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Nome original"),
            cargo="Cargo original", usuario=usuario)
        resposta = self.client.post(reverse("funcionario_editar", args=[funcionario.pk]),
            self.dados(nome="Nome alterado", cargo="Cargo alterado", password="curta", areas=["financeiro"]),
            HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        funcionario.refresh_from_db()
        usuario.refresh_from_db()
        self.assertEqual((funcionario.pessoa.nome, funcionario.cargo), ("Nome original", "Cargo original"))
        self.assertEqual(usuario.areas, ["logbook"])
        self.assertTrue(usuario.check_password("Senha-original-123"))
        self.assertTrue(usuario.modulos.filter(pk=self.modulo.pk).exists())

    def test_falha_ao_gravar_usuario_reverte_pessoa_e_funcionario(self):
        with patch.object(Usuario.objects, "create_user", side_effect=IntegrityError("Falha simulada")):
            with self.assertRaises(IntegrityError):
                self.client.post(reverse("funcionario_novo"), self.dados())
        self.assertFalse(Pessoa.objects.exists())
        self.assertFalse(Funcionario.objects.exists())

    def test_criar_sem_login_continua_permitido_e_nao_concede_acessos(self):
        resposta = self.client.post(reverse("funcionario_novo"), {"nome": "Equipe sem login"})
        self.assertEqual(resposta.status_code, 302)
        self.assertIsNone(Funcionario.objects.get().usuario_id)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_novo_login_pode_ser_desativado_explicitamente(self):
        dados = self.dados()
        dados.pop("ativo")
        resposta = self.client.post(reverse("funcionario_novo"), dados)
        self.assertEqual(resposta.status_code, 302)
        usuario = Funcionario.objects.get().usuario
        self.assertFalse(usuario.is_active)
        self.assertTrue(usuario.check_password("Senha-ficticia-123"))

    def test_usuario_existente_nao_tem_login_renomeado_pelo_post(self):
        usuario = Usuario.objects.create_user(username="login-original", password="Senha-original-123")
        funcionario = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Equipe existente"), usuario=usuario)
        resposta = self.client.post(reverse("funcionario_editar", args=[funcionario.pk]),
            self.dados(username="tentativa-renomear", password=""))
        self.assertEqual(resposta.status_code, 302)
        usuario.refresh_from_db()
        self.assertEqual(usuario.username, "login-original")
        self.assertTrue(usuario.check_password("Senha-original-123"))
