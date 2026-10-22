"""Falhas de validação não viram navegação nem perdem mensagens de outras ações."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.test import TestCase, override_settings
from django.urls import path


def enviar(request):
    acao = request.POST.get("acao")
    if acao == "erro":
        messages.error(request, "Confira a quantidade informada.")
    elif acao == "aviso":
        messages.warning(request, "Aviso de uma operação anterior.")
    else:
        messages.success(request, "Registro salvo.")
    return redirect("/mensagens/")


def destino(request):
    return JsonResponse({"mensagens": [str(m) for m in get_messages(request)]})


urlpatterns = [path("enviar/", enviar), path("mensagens/", destino),
               path("entrar/", destino, name="login"),
               path("protegido/", login_required(enviar)),
               path("negado/", lambda request: HttpResponse(status=403))]


@override_settings(ROOT_URLCONF=__name__)
class PreservacaoFormularioTests(TestCase):
    def test_sessao_expirada_nao_navega_nem_descarta_os_dados(self):
        resposta = self.client.post("/protegido/", {"nome": "Rascunho QA"}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 401)
        self.assertIn("sessão expirou", resposta.json()['errors'][0])
        self.assertNotIn('redirect', resposta.json())
        self.assertNotIn('Rascunho QA', resposta.content.decode())
        self.assertEqual(self.client.post("/protegido/").status_code, 302)

    def test_erro_nao_redireciona_nao_repete_mensagem_nem_expoe_os_campos(self):
        resposta = self.client.post("/enviar/", {"acao": "erro", "rascunho": "conteudo-privado-qa"},
                                    HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json(), {"errors": ["Confira a quantidade informada."]})
        self.assertEqual(resposta.headers["Cache-Control"], "no-store")
        self.assertEqual(resposta.headers["X-Frame-Options"], "DENY")
        self.assertNotIn("conteudo-privado-qa", resposta.content.decode())
        self.assertNotIn("conteudo-privado-qa", str(dict(self.client.session)))
        self.assertEqual(self.client.get("/mensagens/").json()["mensagens"], [])

    def test_aviso_anterior_sobrevive_a_erro_novo_e_sucesso_aparece_uma_vez(self):
        self.client.post("/enviar/", {"acao": "aviso"})
        resposta = self.client.post("/enviar/", {"acao": "erro"}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(self.client.get("/mensagens/").json()["mensagens"], ["Aviso de uma operação anterior."])
        self.client.post("/enviar/", {"acao": "erro"})
        resposta = self.client.post("/enviar/", {"acao": "ok"}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.json(), {"redirect": "/mensagens/"})
        self.assertEqual(self.client.get("/mensagens/").json()["mensagens"], ["Confira a quantidade informada.", "Registro salvo."])
        self.assertEqual(self.client.get("/mensagens/").json()["mensagens"], [])

    def test_formulario_sem_javascript_e_recusa_de_acesso_mantem_contrato(self):
        resposta = self.client.post("/enviar/", {"acao": "erro"})
        self.assertRedirects(resposta, "/mensagens/", fetch_redirect_response=False)
        self.assertEqual(self.client.post("/negado/", HTTP_X_FORM_PRESERVE="1").status_code, 403)
