"""Agenda, filtros de canal e ações de produção preservam o fluxo da campanha."""
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.messages import ERROR
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .models import Campanha, PecaCampanha


class AgendaMarketingTests(TestCase):
    def setUp(self):
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="agenda")
        self.client.force_login(self.usuario)
        self.campanha = Campanha.objects.create(nome="Semana da casa", fase="producao",
                                               inicio=date(2026, 10, 19), fim=date(2026, 10, 25),
                                               canais=["Rádio local"])
        self.entrega = PecaCampanha.objects.create(campanha=self.campanha, nome="Convite de outubro",
                                                  tipo="post", canal="Instagram", data=date(2026, 10, 23))
        self.calendario = reverse("marketing:calendario")

    def test_semana_e_padrao_e_exibe_sete_dias_e_entrega_na_data_certa(self):
        resposta = self.client.get(self.calendario, {"data": "2026-10-23"})
        self.assertEqual(resposta.context["escala"], "semana")
        dias = resposta.context["agenda"]["dias"]
        self.assertEqual([dia["data"].weekday() for dia in dias], list(range(7)))
        self.assertEqual(dias[4]["entregas"], [self.entrega])
        self.assertContains(resposta, "Sem entregas neste dia.", count=6)
        self.assertNotContains(resposta, 'class="cal-track"')

    def test_entrega_com_prazo_aparece_mesmo_sem_periodo_na_campanha(self):
        self.campanha.inicio = self.campanha.fim = None
        self.campanha.save()
        resposta = self.client.get(self.calendario, {"data": "2026-10-23"})
        self.assertContains(resposta, self.entrega.nome)
        self.assertFalse(resposta.context["agenda"]["campanhas"].exists())

    def test_canais_personalizados_filtram_e_preservam_periodo_na_navegacao(self):
        outra = PecaCampanha.objects.create(campanha=self.campanha, nome="Áudio rádio",
                                            tipo="anuncio", canal="Rádio local", data=self.entrega.data)
        resposta = self.client.get(self.calendario, {"data": "2026-10-23", "canal": "Rádio local"})
        self.assertEqual(resposta.context["agenda"]["dias"][4]["entregas"], [outra])
        self.assertNotContains(resposta, self.entrega.nome)
        seguinte = parse_qs(urlsplit(resposta.context["proximo_url"]).query)
        self.assertEqual(seguinte, {"vista": ["semana"], "data": ["2026-10-26"], "canal": ["Rádio local"]})
        for vista in resposta.context["vistas"]:
            self.assertEqual(parse_qs(urlsplit(vista["url"]).query)["canal"], ["Rádio local"])

    def test_virada_do_ano_e_parametros_invalidos_nao_geram_erro(self):
        resposta = self.client.get(self.calendario, {"data": "2027-01-01"})
        self.assertEqual(resposta.context["agenda"]["dias"][0]["data"], date(2026, 12, 28))
        for parametros in ({"data": "0001-01-01"}, {"data": "9999-12-31"}, {"data": "erro"},
                           {"vista": "ano", "ano": "9999"}, {"vista": "mes", "ano": "x", "mes": "20"}):
            with self.subTest(parametros=parametros):
                self.assertEqual(self.client.get(self.calendario, parametros).status_code, 200)

    def test_bookmark_mensal_antigo_e_limites_de_navegacao(self):
        resposta = self.client.get(self.calendario, {"ano": 2025, "mes": 9})
        self.assertEqual(resposta.context["escala"], "mes")
        self.assertEqual((resposta.context["ano"], resposta.context["mes"]), (2025, 9))
        for parametros, chave in (({"vista": "ano", "ano": 2}, "anterior_url"),
                                  ({"vista": "mes", "ano": 9998, "mes": 12}, "proximo_url"),
                                  ({"vista": "semana", "data": "0002-01-01"}, "anterior_url")):
            self.assertIsNone(self.client.get(self.calendario, parametros).context[chave])

    def test_canal_filtra_urgencias_e_contagem_das_minhas_campanhas(self):
        self.campanha.responsavel = self.usuario
        self.campanha.save()
        outra = Campanha.objects.create(nome="Campanha WhatsApp", responsavel=self.usuario, canais=["WhatsApp"])
        hoje = timezone.localdate()
        self.entrega.data = hoje
        self.entrega.save()
        PecaCampanha.objects.create(campanha=outra, nome="Aviso hoje", canal="WhatsApp", data=hoje)
        PecaCampanha.objects.create(campanha=outra, nome="Aviso vencido", canal="WhatsApp", data=hoje - timedelta(days=1))
        resposta = self.client.get(reverse("marketing:quadro"), {"canal": "Instagram", "meus": 1})
        self.assertEqual([p["nome"] for p in resposta.context["proximos"]], [self.entrega.nome])
        self.assertEqual(resposta.context["proximos_resumo"], "1 hoje")
        self.assertEqual(resposta.context["atrasados"], [])
        self.assertEqual(resposta.context["meus_count"], 1)
        self.assertContains(resposta, "ORÇAMENTO GERAL")

    def test_ficha_preserva_origem_local_e_rejeita_origem_externa(self):
        ficha = reverse("marketing:ficha", args=[self.campanha.pk])
        origem = self.calendario + "?data=2026-10-23&canal=Instagram"
        resposta = self.client.get(ficha, headers={"HX-Request": "true", "HX-Current-URL": "http://testserver" + origem})
        self.assertEqual(resposta.context["voltar_entrega"], origem)
        resposta = self.client.get(ficha, headers={"HX-Request": "true", "HX-Current-URL": "https://externo.test/"})
        self.assertEqual(resposta.context["voltar_entrega"], reverse("marketing:detalhe", args=[self.campanha.pk]))

    def test_canal_desconhecido_nao_remove_filtro_nem_retorna_tudo(self):
        resposta = self.client.get(self.calendario, {"data": "2026-10-23", "canal": "Não cadastrado"})
        self.assertFalse(any(dia["entregas"] for dia in resposta.context["agenda"]["dias"]))
        self.assertEqual(resposta.context["canal"], "Não cadastrado")

    def test_canal_personalizado_longo_nao_e_truncado_e_caixa_nao_duplica_opcoes(self):
        longo = "Parcerias com os estabelecimentos da região serrana"
        self.campanha.canais = [longo, "INSTAGRAM"]
        self.campanha.save()
        for canal in (longo, "instagram", "INSTAGRAM"):
            resposta = self.client.get(reverse("marketing:quadro"), {"canal": canal})
            cards = [card["obj"].pk for coluna in resposta.context["colunas"] for card in coluna["cards"]]
            self.assertEqual(cards, [self.campanha.pk])
        opcoes = [canal["valor"].lower() for canal in resposta.context["canais"]]
        self.assertEqual(opcoes.count("instagram"), 1)

    def test_lista_e_quadro_respeitam_canal_da_entrega_ou_campanha(self):
        outra = Campanha.objects.create(nome="Campanha de outro canal", canais=["WhatsApp"])
        PecaCampanha.objects.create(campanha=outra, nome="Mensagem aos hóspedes", canal="WhatsApp")
        resposta = self.client.get(reverse("marketing:entregas"), {"canal": "Instagram"})
        self.assertEqual(list(resposta.context["pagina"]), [self.entrega])
        for canal in ("Instagram", "Rádio local"):
            resposta = self.client.get(reverse("marketing:quadro"), {"canal": canal})
            cards = [card["obj"].pk for coluna in resposta.context["colunas"] for card in coluna["cards"]]
            self.assertEqual(cards, [self.campanha.pk])

    def test_acao_rapida_atualiza_producao_sem_avancar_campanha(self):
        url = reverse("marketing:estado_entrega", args=[self.entrega.pk])
        voltar = self.calendario + "?data=2026-10-23&canal=Instagram"
        for estado in ("em_producao", "pronta", "em_producao"):
            resposta = self.client.post(url, {"status": estado, "versao": self.entrega.versao, "voltar": voltar})
            self.assertRedirects(resposta, voltar, fetch_redirect_response=False)
            self.entrega.refresh_from_db()
            self.assertEqual(self.entrega.status, estado)
            self.assertEqual(self.entrega.concluida_em is not None, estado == "pronta")
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.fase, "producao")
        self.assertIsNone(self.campanha.aprovada_em)

    def test_acao_rapida_rejeita_get_versao_obsoleta_ausente_e_estado_invalido(self):
        url = reverse("marketing:estado_entrega", args=[self.entrega.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for dados in ({"status": "pronta", "versao": 0}, {"status": "pronta"},
                      {"status": "publicada", "versao": self.entrega.versao}):
            resposta = self.client.post(url, dados, follow=True)
            self.assertTrue(any(m.level == ERROR for m in resposta.context["messages"]))
            self.entrega.refresh_from_db()
            self.assertEqual(self.entrega.status, "a_fazer")
            self.assertEqual(self.entrega.versao, 1)

    def test_acao_exige_csrf_acesso_e_retorno_local(self):
        url = reverse("marketing:estado_entrega", args=[self.entrega.pk])
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.usuario)
        self.assertEqual(protegido.post(url, {"status": "pronta", "versao": 1}).status_code, 403)
        restrito = Usuario.objects.create_user(username="sem-marketing")
        self.client.force_login(restrito)
        self.assertEqual(self.client.post(url, {"status": "pronta", "versao": 1}).status_code, 403)
        self.client.force_login(self.usuario)
        resposta = self.client.post(url, {"status": "em_producao", "versao": 1, "voltar": "https://externo.test"})
        self.assertRedirects(resposta, reverse("marketing:entregas"), fetch_redirect_response=False)
