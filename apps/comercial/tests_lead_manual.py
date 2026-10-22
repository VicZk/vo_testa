"""Cadastro e atribuição de leads: preservação, atomicidade e integração."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado, Pessoa, Prospecto, Usuario
from apps.nucleo.modulos import Modulo

from . import services
from .models import Campanha, EtapaFunil, MotivoPerda, Oportunidade


class LeadManualTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(username="atendimento-ui", password=None)
        self.client.force_login(self.user)
        self.url = reverse("comercial:nova")
        self.campanha = Campanha.objects.create(nome="Férias", codigo="ferias-ui", criado_por=self.user)
        self.data = {"chave": uuid.uuid4(), "tipo_contato": "novo", "contato-nome": "Contato de teste",
                     "contato-telefone": "49999990000", "contato-email": "contato@example.invalid",
                     "origem": "whatsapp", "tipo_interesse": "hospedagem", "quartos": "1", "hospedes": "2",
                     "faturamento": "particular", "observacao": "Fim de semana em família",
                     "campanha": self.campanha.pk}

    def test_get_nao_cria_contato_e_preseleciona_campanha(self):
        for htmx in (False, True):
            response = self.client.get(self.url, {"campanha": self.campanha.pk},
                                       **({"HTTP_HX_REQUEST": "true"} if htmx else {}))
            self.assertContains(response, "Salvar e abrir atendimento")
            self.assertEqual(str(response.context["form"]["campanha"].value()), str(self.campanha.pk))
            self.assertIsNotNone(response.context["form"]["chave"].value())
        self.assertFalse(Oportunidade.objects.exists())
        self.assertFalse(Pessoa.objects.filter(nome=self.data["contato-nome"]).exists())

    def test_cria_contato_e_lead_juntos_com_origem_e_sem_optin_implicito(self):
        response = self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        self.assertRedirects(response, reverse("comercial:oportunidade", args=[op.pk]))
        self.assertEqual(op.campanha, self.campanha)
        self.assertEqual(op.responsavel, self.user)
        self.assertEqual(op.adultos, op.hospedes)
        self.assertTrue(Prospecto.objects.filter(pessoa=op.pessoa).exists())
        self.assertFalse(op.pessoa.aceita_email)
        self.assertFalse(op.pessoa.aceita_whatsapp)

    def test_reenvio_nao_duplica_contato_ou_atendimento(self):
        first = self.client.post(self.url, self.data, HTTP_HX_REQUEST="true")
        again = self.client.post(self.url, self.data, HTTP_HX_REQUEST="true")
        self.assertEqual(first.headers["HX-Redirect"], again.headers["HX-Redirect"])
        self.assertEqual(Oportunidade.objects.count(), 1)
        self.assertEqual(Pessoa.objects.filter(nome=self.data["contato-nome"]).count(), 1)

    def test_contato_existente_nao_e_modificado(self):
        pessoa = Pessoa.objects.create(nome="Cliente cadastrado", telefone="4933330000")
        response = self.client.post(self.url, {**self.data, "tipo_contato": "cadastrado", "pessoa": pessoa.pk})
        self.assertEqual(response.status_code, 302)
        pessoa.refresh_from_db()
        self.assertEqual(pessoa.nome, "Cliente cadastrado")
        self.assertEqual(pessoa.telefone, "4933330000")
        self.assertEqual(Oportunidade.objects.get().pessoa, pessoa)
        self.assertFalse(Pessoa.objects.filter(nome=self.data["contato-nome"]).exists())

    def test_erros_preservam_preenchimento_sem_contato_orfao(self):
        casos = [
            {"contato-nome": ""}, {"contato-email": "invalido"}, {"contato-telefone": "123"},
            {"valor_estimado": "abc"}, {"valor_estimado": "-1"}, {"valor_estimado": "NaN"},
            {"valor_estimado": "Infinity"}, {"valor_estimado": "9999999999"},
            {"quartos": "zero"}, {"hospedes": "0"}, {"chave": "invalida"},
            {"checkin_previsto": "2026-11-20", "checkout_previsto": "2026-11-19"},
            {"checkin_previsto": "2026-11-20", "checkout_previsto": "2026-11-20"},
            {"checkin_previsto": "data"}, {"campanha": "invalida"}, {"tipo_contato": "cadastrado"},
        ]
        for valores in casos:
            with self.subTest(valores=valores):
                response = self.client.post(self.url, {**self.data, **valores}, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("HX-Redirect", response.headers)
                self.assertContains(response, self.data["observacao"])
                self.assertTrue(response.context["form"].errors or response.context["contato_form"].errors)
                self.assertFalse(Oportunidade.objects.exists())
                self.assertFalse(Pessoa.objects.filter(email=self.data["contato-email"]).exists())

    def test_data_igual_permitida_somente_no_day_use(self):
        response = self.client.post(self.url, {**self.data, "tipo_interesse": "day_use",
                                              "checkin_previsto": "2026-11-20", "checkout_previsto": "2026-11-20"})
        self.assertEqual(response.status_code, 302)

    def test_valor_brasileiro_nao_multiplica_por_cem(self):
        response = self.client.post(self.url, {**self.data, "valor_estimado": "1.500,50"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Oportunidade.objects.get().valor_estimado, Decimal("1500.50"))

    def test_nao_inicia_como_ganho_nem_com_responsavel_inativo(self):
        ganho = EtapaFunil.objects.get(tipo=EtapaFunil.Tipo.GANHO)
        inativo = Usuario.objects.create_user(username="inativo-ui", is_active=False)
        for valores in ({"etapa": ganho.pk}, {"responsavel": inativo.pk}):
            response = self.client.post(self.url, {**self.data, **valores})
            self.assertTrue(response.context["form"].errors)
        self.assertFalse(Oportunidade.objects.exists())

    def test_falha_ao_criar_atendimento_desfaz_contato(self):
        with patch("apps.comercial.services.analisar_lead", side_effect=ValidationError("Não foi possível abrir.")):
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "Não foi possível abrir.")
        self.assertFalse(Oportunidade.objects.exists())
        self.assertFalse(Pessoa.objects.filter(nome=self.data["contato-nome"]).exists())

    def test_filtro_campanha_inclui_fechados_e_preserva_demais_filtros(self):
        self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        outra = services.criar_oportunidade(usuario=self.user, pessoa=op.pessoa, titulo="Outra origem", valor_estimado=Decimal("700"))
        op.valor_estimado = Decimal("500")
        op.save()
        url = reverse("comercial:funil")
        response = self.client.get(url, {"campanha": self.campanha.pk, "fat": "particular", "fechados": "todos"})
        self.assertEqual(response.context["qtd_total"], 1)
        self.assertEqual(response.context["valor_total"], Decimal("500"))
        ids = [o.pk for col in response.context["colunas"] for o in col["itens"]]
        self.assertEqual(ids, [op.pk])
        self.assertNotIn(outra.pk, ids)
        self.assertContains(response, f"campanha={self.campanha.pk}")
        op.status, op.fechado_em = Oportunidade.Status.PERDIDA, timezone.now()
        op.etapa = EtapaFunil.objects.get(tipo=EtapaFunil.Tipo.PERDIDO)
        op.save()
        response = self.client.get(url, {"campanha": self.campanha.pk, "fechados": "todos"})
        self.assertEqual([o.pk for col in response.context["colunas"] for o in col["itens"]], [op.pk])
        self.assertEqual(response.context["qtd_total"], 0)

    def test_filtro_invalido_nao_vira_pagina_de_todos(self):
        for valor in ("abc", "99999999"):
            self.assertEqual(self.client.get(reverse("comercial:funil"), {"campanha": valor}).status_code, 404)

    def test_link_planejamento_respeita_acesso_marketing(self):
        from apps.marketing.models import Campanha as Planejamento
        planejamento = Planejamento.objects.create(nome="Plano Férias", anuncio=self.campanha)
        self.client.post(self.url, self.data)
        url = reverse("comercial:oportunidade", args=[Oportunidade.objects.get().pk])
        self.assertContains(self.client.get(url), reverse("marketing:detalhe", args=[planejamento.pk]))
        atendente = Usuario.objects.create_user(username="so-atendimento-ui", password=None)
        atendente.modulos.add(ModuloContratado.objects.get(codigo=Modulo.COMERCIAL))
        self.client.force_login(atendente)
        self.assertNotContains(self.client.get(url), "Ver planejamento da campanha")

    def test_modulo_inativo_e_sem_acesso(self):
        restrito = Usuario.objects.create_user(username="sem-modulo-ui", password=None)
        self.client.force_login(restrito)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        self.client.force_login(self.user)
        ModuloContratado.objects.filter(codigo=Modulo.COMERCIAL).update(ativo=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_rota_comum_nao_reabre_lead_fechado(self):
        self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        etapa_inicial = op.etapa
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.user)
        atendente = Usuario.objects.create_user(username="sem-gestao-fechados", password=None)
        atendente.modulos.add(ModuloContratado.objects.get(codigo=Modulo.COMERCIAL))
        self.client.force_login(atendente)
        response = self.client.post(reverse("comercial:mover", args=[op.pk]), {"etapa": etapa_inicial.pk})
        self.assertContains(response, "Este atendimento já foi encerrado.")
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.PERDIDA)

    def test_perder_nao_desfaz_venda_fora_do_fluxo_da_gestao(self):
        self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        op.status, op.reserva_id = Oportunidade.Status.GANHA, 123
        op.save()
        with self.assertRaises(ValidationError):
            services.marcar_perdida(op, MotivoPerda.objects.first(), self.user)
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.GANHA)
        self.assertEqual(op.reserva_id, 123)

    def test_repetir_perda_ou_mesma_etapa_nao_repete_historico(self):
        self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        antes = op.permanencias.count()
        services.mover_etapa(op, op.etapa, self.user)
        self.assertEqual(op.permanencias.count(), antes)
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.user)
        historico, quando = op.atividades.count(), op.fechado_em
        services.marcar_perdida(op, MotivoPerda.objects.first(), self.user)
        self.assertEqual(op.atividades.count(), historico)
        self.assertEqual(op.fechado_em, quando)

    def test_perda_invalida_preserva_texto_e_retorno_rejeita_site_externo(self):
        self.client.post(self.url, self.data)
        op = Oportunidade.objects.get()
        response = self.client.post(reverse("comercial:mover", args=[op.pk]), {
            "etapa": EtapaFunil.objects.get(tipo="perdido").pk,
            "detalhe": "Solicitou retorno em novembro", "next": "https://example.invalid/fora"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Solicitou retorno em novembro")
        self.assertContains(response, "Escolha o motivo")
        self.assertEqual(response.context["destino"], reverse("comercial:funil"))
        op.refresh_from_db()
        self.assertEqual(op.status, Oportunidade.Status.ABERTA)


class ConcorrenciaLeadManualTests(TransactionTestCase):
    def test_duas_requisicoes_criam_um_contato_e_um_atendimento(self):
        user = Usuario.objects.create_superuser(username="corrida-lead", password=None)
        etapa = EtapaFunil.objects.create(nome="Novo concorrente", ordem=1)
        chave, barreira = uuid.uuid4(), Barrier(2)

        def criar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                op, criado = services.criar_lead_manual(
                    usuario=user, chave=chave, contato={"nome": "Contato concorrente"},
                    etapa=etapa, disparar_crm=False)
                return op.pk, criado
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(lambda _: criar(), range(2)))
        self.assertEqual(resultados[0][0], resultados[1][0])
        self.assertEqual(sum(criado for _, criado in resultados), 1)
        self.assertEqual(Pessoa.objects.filter(nome="Contato concorrente").count(), 1)
        self.assertEqual(Oportunidade.objects.filter(chave_criacao=chave).count(), 1)
