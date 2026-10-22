import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado
from apps.nucleo.modulos import Modulo
from apps.portal.services import get_acesso, rotacionar_acesso
from apps.reservas.models import Reserva
from apps.reservas.tests import ReservasTestsBase

from . import services
from .models import RespostaNPS


class NpsTests(ReservasTestsBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.APPSITE, defaults={"ativo": True})
        self.estadia = self.reserva(status=Reserva.Status.CHECKOUT)
        self.estadia.checkout_real = timezone.now()
        self.estadia.save(update_fields=["checkout_real"])
        self.acesso = get_acesso(self.estadia.pk)
        self.url = reverse("portal:nps", args=[self.acesso.token])
        self.api = reverse("nps_api:criar_resposta")

    def postar(self, **dados):
        return self.client.post(self.api, {"token": str(self.acesso.token), "consentimento": True, **dados}, content_type="application/json")

    def test_resposta_persiste_e_portal_apos_checkout_leva_a_pesquisa(self):
        self.assertRedirects(self.client.get(reverse("portal:home", args=[self.acesso.token])), self.url)
        resp = self.client.post(self.url, {"nota": "9", "comentario": "Gostamos da recepção.", "consentimento": "on"}, follow=True)
        self.assertContains(resp, "Sua avaliação foi registrada")
        resposta = RespostaNPS.objects.get(reserva=self.estadia)
        self.assertEqual((resposta.nota, resposta.hospede_id), (9, self.hospede.pk))
        self.assertEqual(resposta.consentimento_versao, "2026-10-22")
        self.assertIn("no-store", resp["Cache-Control"])

    def test_idempotencia_preserva_primeira_opiniao(self):
        self.assertEqual(self.postar(nota=8, comentario="Bom").status_code, 201)
        self.assertEqual(self.postar(nota=8, comentario="Bom").status_code, 200)
        self.assertEqual(self.postar(nota=10, comentario="Alterado").status_code, 409)
        self.assertEqual(RespostaNPS.objects.get().nota, 8)
        self.assertEqual(RespostaNPS.objects.count(), 1)

    def test_tokens_invalidos_expirados_rotacionados_e_modulo_inativo(self):
        self.assertEqual(self.client.post(self.api, {"token": "invalido", "nota": 10}, content_type="application/json").status_code, 404)
        anterior = self.acesso.token
        rotacionar_acesso(self.estadia.pk)
        self.assertEqual(self.client.get(reverse("portal:nps", args=[anterior])).status_code, 404)
        novo = get_acesso(self.estadia.pk)
        with patch("apps.nps.services.timezone.now", return_value=timezone.now() + timedelta(days=91)):
            self.assertEqual(self.client.get(reverse("portal:nps", args=[novo.token])).status_code, 404)
        ModuloContratado.objects.filter(codigo=Modulo.APPSITE).update(ativo=False)
        self.assertEqual(self.client.get(reverse("portal:nps", args=[novo.token])).status_code, 404)

    def test_estadia_ainda_aberta_nao_pode_ser_avaliada(self):
        Reserva.objects.filter(pk=self.estadia.pk).update(status=Reserva.Status.CONFIRMADA)
        self.assertEqual(self.postar(nota=10).status_code, 404)
        self.assertFalse(RespostaNPS.objects.exists())

    def test_nota_e_comentario_invalidos_nao_persistem(self):
        for nota in (-1, 11, True, 1.5, "NaN", "Infinity", None, [10], {"nota": 10}):
            with self.subTest(nota=nota):
                self.assertEqual(self.postar(nota=nota).status_code, 400)
        self.assertEqual(self.postar(nota=10, comentario="a" * 2001).status_code, 400)
        self.assertEqual(self.postar(nota=10, comentario=[]).status_code, 400)
        self.assertEqual(self.postar(nota=10, canal="equipe").status_code, 400)
        self.assertFalse(RespostaNPS.objects.exists())

    def test_json_invalido_e_corpos_excessivos(self):
        for corpo in ("[]", "null", "true", "42", "{", '"texto"', "x" * 17000):
            with self.subTest(corpo=corpo[:20]):
                self.assertEqual(self.client.post(self.api, corpo, content_type="application/json").status_code, 400)

    def test_token_nao_permite_escolher_outra_reserva(self):
        outra = self.reserva(status=Reserva.Status.CHECKOUT)
        resp = self.postar(nota=10, reserva_id=outra.pk)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(RespostaNPS.objects.get().reserva_id, self.estadia.pk)

    def test_resumo_calcula_faixas_e_nao_inventa_score_sem_respostas(self):
        self.assertIsNone(services.resumo(RespostaNPS.objects.all())["score"])
        for nota in (10, 9, 8, 7, 2):
            reserva = self.reserva(status=Reserva.Status.CHECKOUT)
            Reserva.objects.filter(pk=reserva.pk).update(checkout_real=timezone.now())
            services.responder(reserva.pk, nota, consentimento=True)
        resumo = services.resumo(RespostaNPS.objects.all())
        self.assertEqual(resumo, {"total": 5, "promotores": 2, "passivos": 2, "detratores": 1, "score": 20.0})

    def test_leitura_exige_area_nps_nao_apenas_login(self):
        services.responder(self.estadia.pk, 6, consentimento=True)
        usuario = get_user_model().objects.create_user(username="sem-nps", password="teste")
        self.client.force_login(usuario)
        for url in (reverse("nps:painel"), reverse("nps_api:resumo"), reverse("nps_api:resposta", args=[self.estadia.pk])):
            self.assertEqual(self.client.get(url).status_code, 403)
        usuario.areas = ["nps"]
        usuario.save(update_fields=["areas"])
        self.assertEqual(self.client.get(reverse("nps_api:resumo")).json()["score"], -100.0)
        self.assertEqual(self.client.get(reverse("nps_api:resumo") + "?de=ruim").status_code, 400)

    def test_sessao_interna_exige_csrf_enquanto_token_autentica_api(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        dados = json.dumps({"reserva_id": self.estadia.pk, "nota": 10, "consentimento": True})
        self.assertEqual(cliente.post(self.api, dados, content_type="application/json").status_code, 403)
        cliente.get(reverse("nps:painel"))
        csrf = cliente.cookies[settings.CSRF_COOKIE_NAME].value
        resp = cliente.post(self.api, dados, content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(RespostaNPS.objects.get().canal, "equipe")

    def test_portal_formulario_tem_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        self.assertEqual(cliente.post(self.url, {"nota": 10}).status_code, 403)
        resp = cliente.get(self.url)
        self.assertContains(resp, "Escolha sua nota")
        self.assertEqual(resp.content.count(b'type="radio"'), 11)
        csrf = cliente.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(cliente.post(self.url, {"nota": 10, "csrfmiddlewaretoken": csrf, "consentimento": "on"}).status_code, 302)

    def test_convite_e_acompanhamento_na_interface(self):
        self.client.force_login(self.usuario)
        convite = self.client.post(reverse("nps:convite", args=[self.estadia.pk]))
        self.assertContains(convite, self.url)
        resposta, _ = services.responder(self.estadia.pk, 3, "Atendimento demorado", consentimento=True)
        resp = self.client.post(reverse("nps:tratar", args=[resposta.pk]), {"tratativa": "Conversamos com a equipe."}, follow=True)
        self.assertContains(resp, "Acompanhamento registrado")
        resposta.refresh_from_db()
        self.assertEqual(resposta.tratada_por, self.usuario)
        self.assertIsNotNone(resposta.tratada_em)
        self.assertEqual(resposta.nota, 3)
        with self.assertRaises(ValidationError):
            services.tratar(resposta.pk, "", self.usuario)

    def test_consentimento_explicito_obrigatorio_no_formulario_e_api(self):
        self.assertEqual(self.client.post(self.url, {"nota": "9"}).status_code, 400)
        for valor in (False, None, "true", 1, [], {}):
            self.assertEqual(self.postar(nota=9, consentimento=valor).status_code, 400)
        self.assertEqual(self.client.post(self.api, {"token": str(self.acesso.token), "nota": 9}, content_type="application/json").status_code, 400)
        self.assertFalse(RespostaNPS.objects.exists())
