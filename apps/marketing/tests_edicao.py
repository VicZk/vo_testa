"""Criação e edição pelo formulário: erros não apagam dados nem criam duplicatas."""
import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .models import Campanha


class EdicaoCampanhaTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="editor", password=None)
        self.client.force_login(self.user)
        self.c = Campanha.objects.create(
            nome="Férias", objetivo="Reservar cabanas", verba_prevista=Decimal("500"),
            inicio=date(2026, 11, 1), fim=date(2026, 11, 15),
        )
        self.nova = reverse("marketing:nova_campanha")
        self.salvar = reverse("marketing:salvar_campanha", args=[self.c.pk])

    def test_abrir_formulario_nao_cria_campanha(self):
        antes = Campanha.objects.count()
        for _ in range(3):
            response = self.client.get(self.nova, HTTP_HX_REQUEST="true")
            self.assertContains(response, "Criar campanha")
            self.assertIsNotNone(response.context["form"]["chave"].value())
        self.assertEqual(Campanha.objects.count(), antes)

    def test_criacao_exige_nome_e_chave_valida(self):
        for data in ({"nome": "", "chave": uuid.uuid4()}, {"nome": "Nova", "chave": "inválida"}):
            with self.subTest(data=data):
                response = self.client.post(self.nova, data, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(Campanha.objects.count(), 1)

    def test_reenviar_criacao_devolve_a_mesma_campanha(self):
        data = {"nome": "Semana da família", "objetivo": "Reservar dias úteis", "chave": uuid.uuid4()}
        first = self.client.post(self.nova, data)
        again = self.client.post(self.nova, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, again.url)
        self.assertEqual(Campanha.objects.filter(nome=data["nome"]).count(), 1)
        campanha = Campanha.objects.get(nome=data["nome"])
        self.assertEqual(campanha.responsavel, self.user)

    def test_campanhas_diferentes_podem_ter_o_mesmo_nome(self):
        for _ in range(2):
            self.client.post(self.nova, {"nome": "Semana da família", "chave": uuid.uuid4()})
        self.assertEqual(Campanha.objects.filter(nome="Semana da família").count(), 2)

    def test_valor_invalido_nao_salva_nenhum_campo(self):
        for valor in ("abc", "-1", "NaN", "Infinity", "1000000000000000000"):
            with self.subTest(valor=valor):
                response = self.client.post(self.salvar, {"nome": "Nome editado", "verba_prevista": valor}, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'role="alert"')
                self.c.refresh_from_db()
                self.assertEqual(self.c.nome, "Férias")
                self.assertEqual(self.c.verba_prevista, Decimal("500"))

    def test_data_invertida_preserva_dados_e_explica_correcao(self):
        response = self.client.post(self.salvar, {"nome": "Nome editado", "fim": "2026-10-30"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "O término precisa ser no mesmo dia ou depois do início.")
        self.assertContains(response, "Nome editado")
        self.c.refresh_from_db()
        self.assertEqual(self.c.nome, "Férias")
        self.assertEqual(self.c.fim, date(2026, 11, 15))

    def test_data_malformada_nao_produz_erro_de_servidor(self):
        response = self.client.post(self.salvar, {"inicio": "amanhã"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form_dados"].errors)
        self.c.refresh_from_db()
        self.assertEqual(self.c.inicio, date(2026, 11, 1))

    def test_meta_invalida_nao_apaga_meta_anterior(self):
        self.c.meta_valor = Decimal("50")
        self.c.save()
        response = self.client.post(self.salvar, {"meta_valor": "cinquenta"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Digite um número válido")
        self.c.refresh_from_db()
        self.assertEqual(self.c.meta_valor, Decimal("50"))

    def test_numero_brasileiro_e_aceito(self):
        response = self.client.post(self.salvar, {"verba_prevista": "R$ 1.500,50"})
        self.assertEqual(response.status_code, 302)
        self.c.refresh_from_db()
        self.assertEqual(self.c.verba_prevista, Decimal("1500.50"))

    def test_valor_salvo_volta_ao_formulario_com_virgula_decimal(self):
        self.c.verba_prevista = Decimal("1500.50")
        self.c.save()
        response = self.client.get(reverse("marketing:ficha", args=[self.c.pk]))
        self.assertContains(response, 'value="1500,50"')

    def test_aprovacao_congela_inicio_e_verba_mesmo_com_post_alterado(self):
        self.c.aprovada_em = timezone.now()
        self.c.save()
        self.client.post(self.salvar, {"inicio": "2027-01-01", "verba_prevista": "1", "publico": "Famílias"})
        self.c.refresh_from_db()
        self.assertEqual(self.c.inicio, date(2026, 11, 1))
        self.assertEqual(self.c.verba_prevista, Decimal("500"))
        self.assertEqual(self.c.publico, "Famílias")

    def test_usuario_sem_marketing_nao_cria_nem_edita(self):
        outro = Usuario.objects.create_user(username="sem_marketing", password=None)
        self.client.force_login(outro)
        self.assertEqual(self.client.get(self.nova).status_code, 403)
        self.assertEqual(self.client.post(self.nova, {"nome": "Sem acesso", "chave": uuid.uuid4()}).status_code, 403)
        self.assertEqual(self.client.post(self.salvar, {"nome": "Sem acesso"}).status_code, 403)

    def test_modulo_inativo_nao_abre_formulario(self):
        ModuloContratado.objects.filter(codigo=Modulo.MARKETING).update(ativo=False)
        self.assertEqual(self.client.get(self.nova).status_code, 404)
