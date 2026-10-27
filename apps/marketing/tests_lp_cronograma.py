"""Cronograma do mês e Aprovação de LPs (pedidos do Marketing, 27/10/2026)."""
import time
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.comercial.models import PaginaCaptacao
from apps.nucleo.antirrobo import CAMPO_ARMADILHA, CAMPO_CARIMBO, carimbo
from apps.nucleo.models import ModuloContratado, TrilhaAuditoria, Usuario
from apps.nucleo.modulos import Modulo

from .models import AprovacaoLP, Campanha, EtapaCampanha, PecaCampanha

HTML = b"<!doctype html><html><head><title>LP</title></head><body><h1>Primavera na casa</h1></body></html>"


def arquivo(conteudo=HTML, nome="lp.html"):
    return SimpleUploadedFile(nome, conteudo, content_type="text/html")


class CronogramaTests(TestCase):
    def setUp(self):
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.client.force_login(Usuario.objects.create_superuser(username="cron"))
        self.campanha = Campanha.objects.create(nome="Primavera", inicio=date(2026, 11, 3),
                                                fim=date(2026, 11, 20), canais=["Instagram"])

    def test_mes_reune_entrega_tarefa_campanha_e_lp_pela_propria_data(self):
        PecaCampanha.objects.create(campanha=self.campanha, nome="Reel da piscina", tipo="post",
                                    canal="Instagram", data=date(2026, 11, 5))
        EtapaCampanha.objects.create(campanha=self.campanha, texto="Fechar roteiro", prazo=date(2026, 11, 4))
        AprovacaoLP.objects.create(nome="LP Primavera", campanha=self.campanha, prazo=date(2026, 11, 6))
        r = self.client.get(reverse("marketing:cronograma"), {"ano": 2026, "mes": 11})
        self.assertEqual(r.status_code, 200)
        dias = {d["data"]: [i["nome"] for i in d["itens"]] for d in r.context["grade"]["dias"]}
        self.assertEqual(dias[date(2026, 11, 3)], ["Primavera"])          # início
        self.assertEqual(dias[date(2026, 11, 4)], ["Fechar roteiro"])
        self.assertEqual(dias[date(2026, 11, 5)], ["Reel da piscina"])
        self.assertEqual(dias[date(2026, 11, 6)], ["LP Primavera"])
        self.assertEqual(dias[date(2026, 11, 20)], ["Primavera"])         # fim
        self.assertEqual(r.context["grade"]["total"], 5)
        # A grade começa na segunda e cobre semanas inteiras.
        self.assertEqual(r.context["grade"]["dias"][0]["data"], date(2026, 10, 26))
        self.assertContains(r, "?data=2026-11-05&amp;voltar=")

    def test_dia_clicado_preenche_o_prazo_da_nova_entrega(self):
        r = self.client.get(reverse("marketing:nova_entrega"), {"data": "2026-11-05"})
        self.assertEqual(r.context["form"]["data"].value(), date(2026, 11, 5))
        r = self.client.get(reverse("marketing:nova_entrega"), {"data": "lixo"})
        self.assertIsNone(r.context["form"]["data"].value())

    def test_mes_invalido_volta_para_o_atual(self):
        for parametros in ({"mes": 13}, {"ano": "x"}, {"ano": 1}):
            self.assertEqual(self.client.get(reverse("marketing:cronograma"), parametros).status_code, 200)


class AprovacaoLPTests(TestCase):
    def setUp(self):
        cache.clear()
        for codigo in (Modulo.MARKETING, Modulo.COMERCIAL):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="mkt", first_name="Ana")
        self.client.force_login(self.usuario)

    def enviar(self):
        r = self.client.post(reverse("marketing:nova_lp"), {"nome": "LP Primavera", "arquivo": arquivo()})
        aprovacao = AprovacaoLP.objects.get()
        self.assertRedirects(r, reverse("marketing:lp_detalhe", args=[aprovacao.pk]))
        return aprovacao

    def comentar_pelo_link(self, aprovacao, tipo, texto="", versao=1):
        with mock.patch("apps.nucleo.antirrobo.time.time", return_value=time.time() - 30):
            campo = carimbo()  # formulário aberto há meio minuto: gente
        return Client().post(reverse("previa_lp:ver", args=[aprovacao.token]), {
            "nome": "Gestor", "texto": texto, "versao": versao, "tipo": tipo, CAMPO_CARIMBO: campo})

    def test_prevista_em_moldura_isolada_e_link_sem_login(self):
        aprovacao = self.enviar()
        self.assertEqual(aprovacao.ultima.numero, 1)
        r = self.client.get(reverse("marketing:lp_detalhe", args=[aprovacao.pk]))
        self.assertContains(r, 'sandbox="allow-scripts')
        anonimo = Client()
        self.assertContains(anonimo.get(reverse("previa_lp:ver", args=[aprovacao.token])), "LP Primavera")
        for url in (reverse("previa_lp:pagina", args=[aprovacao.token, 1]),
                    reverse("marketing:lp_pagina", args=[aprovacao.pk, 1])):
            pagina = (anonimo if "aprovacao" in url else self.client).get(url)
            self.assertContains(pagina, "Primavera na casa")
            # O HTML de fora roda em origem opaca: sem cookie nem sessão do CRM.
            self.assertTrue(pagina["Content-Security-Policy"].startswith("sandbox allow-scripts"))
            self.assertNotIn("allow-same-origin", pagina["Content-Security-Policy"])
            self.assertEqual(pagina["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(anonimo.get(reverse("previa_lp:ver", args=["outro"])).status_code, 404)
        self.assertEqual(anonimo.get(reverse("marketing:lp_pagina", args=[aprovacao.pk, 1])).status_code, 302)
        # O HTML (até megabytes) não vai para a trilha de auditoria.
        self.assertFalse(TrilhaAuditoria.objects.filter(detalhe__icontains="Primavera na casa").exists())

    def test_ajuste_versao_nova_aprovacao_e_publicacao(self):
        aprovacao = self.enviar()
        self.comentar_pelo_link(aprovacao, "ajuste", "Trocar a foto do topo")
        aprovacao.refresh_from_db()
        self.assertEqual(aprovacao.situacao, AprovacaoLP.Situacao.AJUSTES)
        self.client.post(reverse("marketing:lp_versao", args=[aprovacao.pk]),
                         {"arquivo": arquivo(HTML.replace(b"Primavera", b"Outono")), "nota": "Foto nova"})
        aprovacao.refresh_from_db()
        self.assertEqual((aprovacao.situacao, aprovacao.ultima.numero), (AprovacaoLP.Situacao.AGUARDANDO, 2))
        # Quem olhava a v1 não aprova sem ver a v2.
        r = self.comentar_pelo_link(aprovacao, "aprovacao", versao=1)
        self.assertContains(r, "Chegou a versão 2")
        self.comentar_pelo_link(aprovacao, "aprovacao", versao=2)
        aprovacao.refresh_from_db()
        self.assertEqual((aprovacao.situacao, aprovacao.aprovada_versao, aprovacao.aprovada_por),
                         (AprovacaoLP.Situacao.APROVADA, 2, "Gestor"))
        r = self.client.post(reverse("marketing:lp_publicar", args=[aprovacao.pk]), {"slug": "outono"})
        aprovacao.refresh_from_db()
        self.assertEqual(aprovacao.situacao, AprovacaoLP.Situacao.PUBLICADA)
        pagina = PaginaCaptacao.objects.get(slug="outono")
        self.assertEqual(pagina.status, PaginaCaptacao.Status.PUBLICADA)
        no_ar = Client().get(reverse("lp:publicada", args=["outono"]))
        self.assertContains(no_ar, "Outono na casa")
        self.assertRedirects(Client().get(pagina.get_absolute_url()), reverse("lp:publicada", args=["outono"]),
                             fetch_redirect_response=False)

    def test_publicacao_exige_aprovacao_endereco_livre_e_comercial(self):
        aprovacao = self.enviar()
        self.client.post(reverse("marketing:lp_publicar", args=[aprovacao.pk]), {"slug": "primavera"})
        self.assertFalse(PaginaCaptacao.objects.exists())                  # sem aprovação
        self.comentar_pelo_link(aprovacao, "aprovacao")
        self.client.post(reverse("marketing:lp_publicar", args=[aprovacao.pk]), {"slug": "fundador"})
        self.assertFalse(PaginaCaptacao.objects.exists())                  # endereço da casa
        so_marketing = Usuario.objects.create_user(username="so-mkt")
        so_marketing.modulos.add(ModuloContratado.objects.get(codigo=Modulo.MARKETING))
        self.client.force_login(so_marketing)
        r = self.client.get(reverse("marketing:lp_detalhe", args=[aprovacao.pk]))
        self.assertContains(r, "quem tem acesso ao Comercial")
        self.client.post(reverse("marketing:lp_publicar", args=[aprovacao.pk]), {"slug": "primavera"})
        self.assertFalse(PaginaCaptacao.objects.exists())

    def test_arquivo_que_nao_e_html_volta_com_o_motivo(self):
        r = self.client.post(reverse("marketing:nova_lp"), {"nome": "LP", "arquivo": arquivo(b"oi", "lp.txt")})
        self.assertContains(r, "Envie o arquivo .html da LP.")
        r = self.client.post(reverse("marketing:nova_lp"), {"nome": "LP", "arquivo": arquivo(b"oi")})
        self.assertContains(r, "não parece uma página HTML")
        self.assertFalse(AprovacaoLP.objects.exists())

    def test_robo_no_link_nao_comenta_e_link_novo_derruba_o_antigo(self):
        aprovacao = self.enviar()
        Client().post(reverse("previa_lp:ver", args=[aprovacao.token]),
                      {"nome": "Robô", "texto": "spam", "versao": 1, "tipo": "comentario",
                       CAMPO_ARMADILHA: "http://spam.example"})
        self.assertFalse(aprovacao.comentarios.exists())
        antigo = aprovacao.token
        self.client.post(reverse("marketing:lp_novo_link", args=[aprovacao.pk]))
        self.assertEqual(Client().get(reverse("previa_lp:ver", args=[antigo])).status_code, 404)
