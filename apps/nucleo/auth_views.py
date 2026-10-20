"""LoginView com rate-limit (S-M1) + passo de MFA (Fase 4).

O login de funcionários (/crm/entrar/) é alvo de alto valor — contas de gerência abrem
caixa, estornam e veem PII/FNRH. Sem limite, fica exposto a brute-force/credential-stuffing.
Aqui limitamos por IP (o mesmo helper já usado em portal/pagamentos/site). Se o usuário tem
MFA ativo, a senha sozinha NÃO loga: redireciona para o desafio TOTP.
"""
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, PasswordResetView
from django.shortcuts import redirect
from django.urls import reverse_lazy

from .ratelimit import (
    falhas_da_conta,
    limite_excedido,
    limpar_falhas_da_conta,
    registrar_falha_da_conta,
)

# Trava por conta: muitas senhas erradas para o MESMO usuário, de qualquer IP, seguram
# aquela conta por um tempo (o limite por IP sozinho não segura um ataque distribuído).
FALHAS_POR_CONTA = 8
JANELA_CONTA_SEG = 15 * 60


class FormularioEntrada(AuthenticationForm):
    """Mensagens da entrada em português e sem dizer se o usuário existe."""

    error_messages = {
        "invalid_login": "Usuário ou senha incorretos. Confira e tente de novo.",
        "inactive": "Esta conta está desativada. Fale com a gerência.",
    }


class LoginComLimite(LoginView):
    authentication_form = FormularioEntrada

    def _usuario_digitado(self) -> str:
        return self.request.POST.get("username", "")

    def post(self, request, *args, **kwargs):
        # Testes não passam pelo limite por IP (evita flakiness por cache compartilhado).
        if not getattr(settings, "TESTING", False) and limite_excedido(
            request, "login", limite=10, janela_seg=300
        ):
            form = self.get_form()
            form.add_error(
                None, "Muitas tentativas de login. Aguarde alguns minutos e tente de novo."
            )
            return self.form_invalid(form)
        if self._trava_ligada() and (
                falhas_da_conta("login", self._usuario_digitado()) >= FALHAS_POR_CONTA):
            # Mesma resposta exista ou não a conta: não confirma quem é usuário.
            form = self.get_form()
            form.add_error(None, "Muitas tentativas para este usuário. Aguarde 15 minutos "
                                 "ou use \"Esqueci minha senha\".")
            return super().form_invalid(form)
        return super().post(request, *args, **kwargs)

    @staticmethod
    def _trava_ligada() -> bool:
        return getattr(settings, "LOGIN_TRAVA_POR_CONTA", True)

    def form_invalid(self, form):
        if self.request.method == "POST" and self._usuario_digitado() and self._trava_ligada():
            registrar_falha_da_conta("login", self._usuario_digitado(), JANELA_CONTA_SEG)
        return super().form_invalid(form)

    def form_valid(self, form):
        """Senha correta. Se o usuário tem MFA, não loga ainda — manda pro desafio."""
        limpar_falhas_da_conta("login", self._usuario_digitado())
        user = form.get_user()
        if user.mfa_ativo and user.mfa_secret:
            self.request.session["mfa_pending_user"] = user.pk
            self.request.session["mfa_next"] = self.get_success_url()
            return redirect("mfa_desafio")
        return super().form_valid(form)


class RecuperarSenha(PasswordResetView):
    """"Esqueci minha senha" do CRM: manda o link de troca para o e-mail cadastrado. A
    tela de "enviado" é a mesma exista ou não o e-mail (não revela quem é usuário), e o
    envio é limitado por IP."""

    template_name = "registration/senha_esqueci.html"
    email_template_name = "registration/senha_email.txt"
    subject_template_name = "registration/senha_assunto.txt"
    success_url = reverse_lazy("senha_enviada")

    def post(self, request, *args, **kwargs):
        if not getattr(settings, "TESTING", False) and limite_excedido(
            request, "senha_esqueci", limite=5, janela_seg=900
        ):
            return redirect(self.success_url)  # mesma resposta: não ajuda a sondar
        return super().post(request, *args, **kwargs)
