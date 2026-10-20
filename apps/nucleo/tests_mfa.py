"""Testes do MFA (TOTP) — Fase 4 de segurança."""
import pyotp
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import mfa

Usuario = get_user_model()


class MFAFluxoTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(username="op", password="senha-forte-123")

    def test_ativar_mostra_qr_e_confirma_com_codigo(self):
        self.client.login(username="op", password="senha-forte-123")
        # GET gera o secret em sessão e mostra o QR
        r = self.client.get(reverse("mfa_ativar"))
        self.assertEqual(r.status_code, 200)
        secret = self.client.session["mfa_secret_novo"]
        self.assertTrue(secret)
        # POST com código válido ativa e revela backups
        codigo = pyotp.TOTP(secret).now()
        r = self.client.post(reverse("mfa_ativar"), {"codigo": codigo})
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_ativo)
        self.assertEqual(len(self.user.mfa_backup_codes), 8)

    def test_login_com_mfa_exige_segundo_fator(self):
        secret = mfa.novo_secret()
        self.user.mfa_secret = secret
        self.user.mfa_ativo = True
        self.user.save()
        # senha correta → NÃO loga, manda pro desafio
        r = self.client.post(reverse("login"),
                             {"username": "op", "password": "senha-forte-123"})
        self.assertRedirects(r, reverse("mfa_desafio"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        # código TOTP válido → loga
        r = self.client.post(reverse("mfa_desafio"), {"codigo": pyotp.TOTP(secret).now()})
        self.assertIn("_auth_user_id", self.client.session)

    def test_codigo_de_backup_funciona_uma_vez(self):
        claros, hashes = mfa.gerar_backup_codes()
        self.user.mfa_secret = mfa.novo_secret()
        self.user.mfa_ativo = True
        self.user.mfa_backup_codes = hashes
        self.user.save()
        self.assertTrue(mfa.consumir_backup(self.user, claros[0]))   # 1ª vez: ok
        self.assertFalse(mfa.consumir_backup(self.user, claros[0]))  # reuso: recusa

    def test_mfa_obrigatorio_para_superuser(self):
        su = Usuario.objects.create_superuser(username="chefe", password="senha-forte-123")
        self.assertTrue(mfa.mfa_obrigatorio(su))
        self.assertFalse(mfa.mfa_obrigatorio(self.user))


class HeadersSegurancaTests(TestCase):
    def test_csp_report_only_presente(self):
        r = self.client.get(reverse("login"))
        self.assertIn("Content-Security-Policy-Report-Only", r.headers)
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy-Report-Only"])

    def test_nosniff_presente(self):
        r = self.client.get(reverse("login"))
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

    def test_csp_aponta_o_relatorio(self):
        r = self.client.get(reverse("login"))
        self.assertIn("report-uri /csp/relatorio/", r.headers["Content-Security-Policy-Report-Only"])

    def test_relatorio_csp_registra_sem_token_e_sem_csrf(self):
        import json

        from django.test import Client

        corpo = {"csp-report": {
            "violated-directive": "script-src",
            "blocked-uri": "https://evil.example/x.js?k=1",
            "document-uri": "https://pousada/hospede/3f2b6c1e-8a1d-4c1e-9b2a-1c2d3e4f5a6b/?a=b",
        }}
        with self.assertLogs("csp", level="WARNING") as log:
            r = Client(enforce_csrf_checks=True).post(
                reverse("csp_relatorio"), json.dumps(corpo),
                content_type="application/csp-report")
        self.assertEqual(r.status_code, 204)
        linha = log.output[0]
        self.assertIn("script-src", linha)
        self.assertIn("https://evil.example/x.js", linha)
        self.assertIn("/hospede/<token>/", linha)
        self.assertNotIn("3f2b6c1e", linha)

    def test_relatorio_csp_com_lixo_nao_quebra(self):
        r = self.client.post(reverse("csp_relatorio"), "não é json",
                             content_type="application/csp-report")
        self.assertEqual(r.status_code, 400)


class AlcanceMFAObrigatorioTests(TestCase):
    """MFA_OBRIGATORIO_PARA escolhe de quem o MFA é obrigatório; o padrão segue o dono."""

    def setUp(self):
        from apps.nucleo.areas import Area
        self.gerente = Usuario.objects.create_user(username="ger", password="x", is_staff=True)
        self.caixa = Usuario.objects.create_user(username="cx", password="x",
                                                 areas=[Area.CAIXA])
        self.comum = Usuario.objects.create_user(username="com", password="x")

    def _obrigatorios(self):
        from apps.nucleo.mfa import mfa_obrigatorio
        return [u.username for u in (self.gerente, self.caixa, self.comum) if mfa_obrigatorio(u)]

    def test_padrao_so_superusuario(self):
        self.assertEqual(self._obrigatorios(), [])

    @override_settings(MFA_OBRIGATORIO_PARA="gerencia")
    def test_gerencia(self):
        self.assertEqual(self._obrigatorios(), ["ger"])

    @override_settings(MFA_OBRIGATORIO_PARA="financeiro")
    def test_financeiro_inclui_quem_opera_caixa(self):
        self.assertEqual(self._obrigatorios(), ["ger", "cx"])


@override_settings(LOGIN_TRAVA_POR_CONTA=True,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "trava-conta"}})
class TravaPorContaTests(TestCase):
    """Senhas erradas para o mesmo usuário, de qualquer IP, seguram a conta."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.u = Usuario.objects.create_user(username="recepcao", password="senha-forte-123")

    def _entrar(self, senha, ip="10.0.0.1"):
        return self.client.post(reverse("login"), {"username": "recepcao", "password": senha},
                                REMOTE_ADDR=ip)

    def test_oito_erros_seguram_a_conta_mesmo_com_a_senha_certa(self):
        for n in range(8):
            self._entrar("errada", ip=f"10.0.0.{n}")
        resposta = self._entrar("senha-forte-123", ip="10.0.0.99")
        self.assertContains(resposta, "Muitas tentativas para este usuário")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_acerto_zera_as_falhas(self):
        for _ in range(5):
            self._entrar("errada")
        self.assertEqual(self._entrar("senha-forte-123").status_code, 302)
        self.client.logout()
        for _ in range(5):
            self._entrar("errada")
        self.assertEqual(self._entrar("senha-forte-123").status_code, 302)

    def test_mensagem_de_senha_errada_em_portugues(self):
        self.assertContains(self._entrar("errada"), "Usuário ou senha incorretos")


class RecuperarSenhaTests(TestCase):
    def setUp(self):
        self.u = Usuario.objects.create_user(username="recepcao", password="senha-antiga-123",
                                             email="recepcao@pousada.test")

    def test_link_por_email_troca_a_senha(self):
        import re

        from django.core import mail

        self.assertContains(self.client.get(reverse("login")), "Esqueci minha senha")
        r = self.client.post(reverse("senha_esqueci"), {"email": "recepcao@pousada.test"})
        self.assertRedirects(r, reverse("senha_enviada"))
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/]+(/crm/senha/nova/\S+)", mail.outbox[0].body).group(1)
        pagina = self.client.get(link, follow=True)
        self.assertContains(pagina, "Crie sua senha nova")
        self.client.post(pagina.redirect_chain[-1][0] if pagina.redirect_chain else link,
                         {"new_password1": "senha-nova-456!", "new_password2": "senha-nova-456!"})
        self.u.refresh_from_db()
        self.assertTrue(self.u.check_password("senha-nova-456!"))

    def test_email_desconhecido_tem_a_mesma_resposta(self):
        from django.core import mail

        r = self.client.post(reverse("senha_esqueci"), {"email": "ninguem@pousada.test"})
        self.assertRedirects(r, reverse("senha_enviada"))
        self.assertEqual(len(mail.outbox), 0)
