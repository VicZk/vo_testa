"""Cronograma do mês e Aprovação de LPs (pedidos do Marketing, 27/10/2026)."""
import time
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
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


class AprovacaoOpcionalTests(TestCase):
    """Nem toda campanha passa pelo gestor (pedido do Marketing, 27/10)."""

    def setUp(self):
        from decimal import Decimal

        from django.utils import timezone

        from apps.marketing import services
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.analista = Usuario.objects.create_user(username="analista-mkt")
        self.analista.modulos.add(ModuloContratado.objects.get(codigo=Modulo.MARKETING))
        hoje = timezone.localdate()
        services.definir_teto(hoje.strftime("%Y-%m"), "1000")
        self.campanha = Campanha.objects.create(
            nome="Flyer do feriado", objetivo="obj", publico="pub", inicio=hoje, fim=hoje,
            verba_prevista=Decimal("600"), objetivo_tipo=Campanha.Objetivo.LEADS,
            meta_valor=Decimal("10"))
        services.avancar(self.campanha, self.analista)  # Ideia → Proposta
        services.garantir_itens(self.campanha)
        for chave in ("publico_delimitado", "verba_base"):
            services.marcar_item(self.campanha.checks.get(chave=chave), self.analista)

    def test_sem_aprovacao_pula_a_fase_e_trava_a_verba_no_teto(self):
        from decimal import Decimal

        from apps.marketing import services
        self.client.force_login(self.analista)
        self.client.post(reverse("marketing:definir_aprovacao", args=[self.campanha.pk]), {"exige": "0"})
        self.campanha.refresh_from_db()
        self.assertFalse(self.campanha.exige_aprovacao)
        self.assertEqual(services.portao_da(self.campanha)["avancar_label"], "Avançar para Estruturação")
        services.avancar(self.campanha, self.analista)  # analista, sem gerência
        self.assertEqual(self.campanha.fase, Campanha.Fase.ESTRUTURACAO)
        self.assertEqual(self.campanha.verba_travada, Decimal("600"))
        self.assertIsNone(self.campanha.aprovada_por)
        # Depois de travar a verba, a escolha não muda mais.
        with self.assertRaises(ValidationError):
            services.definir_aprovacao(self.campanha, True)

    def test_sem_aprovacao_o_teto_do_mes_continua_valendo(self):
        from decimal import Decimal

        from apps.marketing import services
        self.campanha.exige_aprovacao = False
        self.campanha.verba_prevista = Decimal("1500")
        self.campanha.save()
        with self.assertRaises(ValidationError):
            services.avancar(self.campanha, self.analista)
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.fase, Campanha.Fase.PROPOSTA)

    def test_com_aprovacao_segue_parando_no_gestor(self):
        from apps.marketing import services
        services.avancar(self.campanha, self.analista)  # Proposta → Aprovação
        self.assertEqual(self.campanha.fase, Campanha.Fase.APROVACAO)
        with self.assertRaises(ValidationError):
            services.avancar(self.campanha, self.analista)


class ValorDaEntregaTests(TestCase):
    def setUp(self):
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.client.force_login(Usuario.objects.create_superuser(username="valor-mkt"))

    def test_valor_em_reais_entra_no_relatorio_por_tipo(self):
        from decimal import Decimal
        r = self.client.post(reverse("marketing:nova_entrega"), {
            "versao": 1, "tipo": "impresso", "nome": "Flyer", "data": "2026-11-05",
            "valor": "1.234,50", "status": "a_fazer"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PecaCampanha.objects.get().valor, Decimal("1234.50"))
        PecaCampanha.objects.create(nome="Rádio", tipo="midia_off", data=date(2026, 11, 9), valor=Decimal("400"))
        PecaCampanha.objects.create(nome="Fora do mês", tipo="midia_off", data=date(2026, 12, 1), valor=Decimal("99"))
        r = self.client.get(reverse("marketing:relatorio"), {"mes": 11, "ano": 2026})
        midias = r.context["dados"]["midias"]
        self.assertEqual([(m["nome"], m["valor"]) for m in midias["linhas"]],
                         [("Impressão", Decimal("1234.50")), ("Mídia off", Decimal("400"))])
        self.assertEqual(midias["total"], Decimal("1634.50"))
        self.assertContains(r, "Investimento por tipo de mídia")
        csv = self.client.get(reverse("marketing:relatorio"), {"mes": 11, "ano": 2026, "export": "csv"})
        self.assertIn("Mídia off", csv.content.decode())
