"""Organização por entrega, vínculos existentes e preservação do fluxo de campanhas."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.comercial.models import PaginaCaptacao
from apps.comercial.services import paginas_para_marketing
from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from . import services, services_entregas
from .models import Campanha, ItemChecklist, PecaCampanha


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class EntregasTests(TestCase):
    def setUp(self):
        cache.clear()
        for modulo in (Modulo.MARKETING, Modulo.COMERCIAL):
            ModuloContratado.objects.update_or_create(codigo=modulo, defaults={"ativo": True})
        self.user = Usuario.objects.create_superuser(username="entregas", password="teste-local")
        self.client.force_login(self.user)
        self.campanha = Campanha.objects.create(nome="Inauguração", fase=Campanha.Fase.PRODUCAO)
        self.outra = Campanha.objects.create(nome="Campanha antiga", fase=Campanha.Fase.ENCERRADA)
        self.lista = reverse("marketing:entregas")

    def dados(self, **alteracoes):
        return {"campanha": str(self.campanha.pk), "nome": "Flyer da pousada", "tipo": "impresso",
                "canal": "Recepção", "data": "", "status": "a_fazer", "url_material": "",
                "material_checklist": "", "pagina_captacao": "", "versao": "1", **alteracoes}

    def criar(self, **alteracoes):
        resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(**alteracoes))
        self.assertEqual(resposta.status_code, 302)
        return PecaCampanha.objects.latest("pk")

    def anexo(self, campanha=None):
        return ItemChecklist.objects.create(
            campanha=campanha or self.campanha, chave="arte_final",
            arquivo=SimpleUploadedFile("arte-final.pdf", b"%PDF-1.4\narte ficticia", "application/pdf"))

    def pagina(self):
        return PaginaCaptacao.objects.create(nome="Página reservada do Comercial QA", slug="lp-qa", criado_por=self.user)

    def test_lista_inclui_concluidas_sem_data_e_campanhas_encerradas(self):
        antiga = PecaCampanha.objects.create(campanha=self.outra, nome="Arte antiga pronta", status="pronta")
        pendente = self.criar()
        resposta = self.client.get(self.lista)
        self.assertEqual({p.pk for p in resposta.context["pagina"]}, {antiga.pk, pendente.pk})
        self.assertContains(resposta, "Data de conclusão não registrada")
        self.assertContains(resposta, "Não classificado")
        self.assertContains(resposta, "Campanhas")

    def test_filtros_combinam_tipo_situacao_campanha_e_busca(self):
        alvo = self.criar(nome="Flyer primavera", status="em_producao")
        self.criar(nome="Flyer pronto", status="pronta")
        self.criar(nome="Carrossel primavera", tipo="post")
        resposta = self.client.get(self.lista, {
            "tipo": "impresso", "situacao": "pendentes", "campanha": self.campanha.pk, "q": "primavera"})
        self.assertEqual([p.pk for p in resposta.context["pagina"]], [alvo.pk])
        resumo = {linha["tipo"]: linha for linha in resposta.context["resumo_tipos"]}
        self.assertEqual(resumo["impresso"]["pendentes"], 1)
        self.assertEqual(resumo["post"]["pendentes"], 1)

    def test_paginacao_preserva_filtros_sem_esconder_excedentes(self):
        PecaCampanha.objects.bulk_create([
            PecaCampanha(campanha=self.campanha, nome=f"Post {i:02}", tipo="post") for i in range(35)])
        primeira = self.client.get(self.lista, {"tipo": "post", "situacao": "pendentes"})
        segunda = self.client.get(self.lista, {"tipo": "post", "situacao": "pendentes", "pagina": 2})
        self.assertEqual(primeira.context["pagina"].paginator.count, 35)
        ids = [p.pk for resposta in (primeira, segunda) for p in resposta.context["pagina"]]
        self.assertEqual(len(set(ids)), 35)
        self.assertContains(primeira, "tipo=post")

    def test_conclusao_reenvio_reabertura_e_fase_da_campanha(self):
        peca = self.criar(status="em_producao")
        instante = datetime(2026, 10, 23, 14, tzinfo=UTC)
        with patch("apps.marketing.services_entregas.timezone.now", return_value=instante):
            services_entregas.alterar_estado(peca, "pronta", self.user)
        peca.refresh_from_db()
        self.assertEqual(peca.concluida_em, instante)
        self.assertEqual(peca.concluida_por, self.user)
        with patch("apps.marketing.services_entregas.timezone.now", return_value=instante + timedelta(hours=1)):
            services_entregas.alterar_estado(peca, "pronta", self.user)
        peca.refresh_from_db()
        self.assertEqual(peca.concluida_em, instante)
        services_entregas.alterar_estado(peca, "a_fazer", self.user)
        peca.refresh_from_db()
        self.assertIsNone(peca.concluida_em)
        self.assertIsNone(peca.concluida_por)
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.fase, Campanha.Fase.PRODUCAO)
        self.assertIsNone(self.campanha.aprovada_em)

    def test_editar_legado_pronto_nao_inventa_data_de_conclusao(self):
        peca = PecaCampanha.objects.create(campanha=self.campanha, nome="Legado", status="pronta")
        resposta = self.client.post(reverse("marketing:editar_entrega", args=[peca.pk]),
                                   self.dados(nome="Legado revisado", status="pronta"))
        self.assertEqual(resposta.status_code, 302)
        peca.refresh_from_db()
        self.assertEqual(peca.nome, "Legado revisado")
        self.assertEqual(peca.tipo, "impresso")
        self.assertIsNone(peca.concluida_em)

    def test_duas_fichas_nao_sobrescrevem_alteracao_mais_recente(self):
        peca = self.criar()
        url = reverse("marketing:editar_entrega", args=[peca.pk])
        self.assertEqual(self.client.post(url, self.dados(nome="Revisão da primeira ficha")).status_code, 302)
        resposta = self.client.post(url, self.dados(nome="Nome antigo", status="pronta"))
        self.assertContains(resposta, "mudou em outra tela")
        peca.refresh_from_db()
        self.assertEqual(peca.nome, "Revisão da primeira ficha")
        self.assertEqual(peca.status, "a_fazer")
        self.assertIsNone(peca.concluida_em)

    def test_novas_entregas_nao_podem_ficar_sem_tipo(self):
        for tipo in ("", "nao_classificado"):
            resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(tipo=tipo))
            self.assertIn("tipo", resposta.context["form"].errors)
        self.client.post(reverse("marketing:adicionar_peca", args=[self.campanha.pk]), {"nome": "Sem tipo"})
        self.assertFalse(PecaCampanha.objects.exists())

    def test_rejeita_urls_executaveis_e_protocolos_de_arquivo(self):
        for url in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                    "file:///etc/passwd", "ftp://example.com/material.pdf"):
            with self.subTest(url=url):
                resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(url_material=url))
                self.assertEqual(resposta.status_code, 200)
                self.assertIn("url_material", resposta.context["form"].errors)
        self.assertFalse(PecaCampanha.objects.exists())

    def test_nome_escapado_e_link_invalido_importado_nao_vira_href(self):
        PecaCampanha.objects.create(campanha=self.campanha, nome='<script>window.injetado=1</script>',
                                   url_material="javascript:alert(1)")
        resposta = self.client.get(self.lista)
        self.assertNotContains(resposta, "<script>window.injetado")
        self.assertContains(resposta, "&lt;script&gt;")
        self.assertNotContains(resposta, 'href="javascript:')

    def test_reutiliza_anexo_sem_copia_e_rejeita_material_de_outra_campanha(self):
        proprio, alheio = self.anexo(), self.anexo(self.outra)
        peca = self.criar(material_checklist=str(proprio.pk))
        self.assertEqual(peca.material_checklist_id, proprio.pk)
        self.assertEqual(ItemChecklist.objects.count(), 2)
        resposta = self.client.post(reverse("marketing:editar_entrega", args=[peca.pk]),
                                   self.dados(material_checklist=str(alheio.pk)))
        self.assertIn("material_checklist", resposta.context["form"].errors)
        peca.refresh_from_db()
        self.assertEqual(peca.material_checklist_id, proprio.pk)
        with self.assertRaises(ValidationError):
            peca.material_checklist = alheio
            peca.full_clean()

    def test_download_e_autorizado_como_anexo_sem_cache(self):
        material = self.anexo()
        url = reverse("marketing:abrir_material", args=[material.pk])
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("attachment", resposta["Content-Disposition"])
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", resposta["Cache-Control"])
        self.assertTrue(b"%PDF" in b"".join(resposta.streaming_content))
        sem_acesso = Usuario.objects.create_user(username="sem-marketing")
        sem_acesso.modulos.add(ModuloContratado.objects.get(codigo=Modulo.COMERCIAL))
        self.client.force_login(sem_acesso)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(self.lista).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_lp_reutiliza_cadastro_sem_publicar_e_sem_status_enganoso(self):
        pagina = self.pagina()
        peca = self.criar(nome="Entrega da LP", tipo="lp", pagina_captacao=str(pagina.pk), status="pronta")
        pagina.refresh_from_db()
        self.assertEqual(PaginaCaptacao.objects.count(), 1)
        self.assertEqual(pagina.status, "rascunho")
        self.assertEqual(peca.pagina_captacao_id, pagina.pk)
        self.assertNotIn("status", paginas_para_marketing(usuario=self.user, ids=[pagina.pk])[0])
        self.assertContains(self.client.get(self.lista), "Abrir LP")
        self.assertRedirects(self.client.get(reverse("marketing:abrir_lp", args=[peca.pk])),
                             pagina.get_absolute_url(), fetch_redirect_response=False)

    def test_apenas_marketing_nao_consulta_ou_escolhe_lp_do_comercial(self):
        pagina = self.pagina()
        peca = self.criar(tipo="lp", pagina_captacao=str(pagina.pk))
        analista = Usuario.objects.create_user(username="apenas-marketing")
        analista.modulos.add(ModuloContratado.objects.get(codigo=Modulo.MARKETING))
        self.client.force_login(analista)
        self.assertEqual(paginas_para_marketing(usuario=analista), [])
        self.assertNotContains(self.client.get(self.lista), "Abrir LP")
        self.assertEqual(self.client.get(reverse("marketing:abrir_lp", args=[peca.pk])).status_code, 403)
        formulario = self.client.get(reverse("marketing:nova_entrega"))
        self.assertNotContains(formulario, pagina.nome)
        # A edição dos dados do Marketing mantém o vínculo que o usuário não pode editar.
        resposta = self.client.post(reverse("marketing:editar_entrega", args=[peca.pk]),
                                   self.dados(nome="LP revisada", tipo="lp", pagina_captacao="999999"))
        self.assertEqual(resposta.status_code, 302)
        peca.refresh_from_db()
        self.assertEqual(peca.pagina_captacao_id, pagina.pk)

    def test_rejeita_lp_em_tipo_incompativel_e_redirect_externo(self):
        pagina = self.pagina()
        resposta = self.client.post(reverse("marketing:nova_entrega"),
                                   self.dados(tipo="post", pagina_captacao=str(pagina.pk)))
        self.assertIn("pagina_captacao", resposta.context["form"].errors)
        resposta = self.client.post(reverse("marketing:nova_entrega"),
                                   self.dados(voltar="https://example.com/externo"))
        self.assertRedirects(resposta, self.lista, fetch_redirect_response=False)

    def test_copiar_campanha_preserva_tipo_e_reinicia_entrega(self):
        pagina, material = self.pagina(), self.anexo()
        self.criar(tipo="lp", pagina_captacao=str(pagina.pk), material_checklist=str(material.pk),
                   url_material="https://example.com/arte", status="pronta")
        copia = services.duplicar(self.campanha, self.user)
        peca = copia.pecas.get()
        self.assertEqual(peca.tipo, "lp")
        self.assertEqual(peca.status, "a_fazer")
        self.assertIsNone(peca.concluida_em)
        self.assertIsNone(peca.pagina_captacao_id)
        self.assertIsNone(peca.material_checklist_id)
        self.assertEqual(peca.url_material, "")


class LegadoEntregasMigrationTests(TransactionTestCase):
    def test_migracao_preserva_prontas_canais_datas_e_anexos_sem_inferencia(self):
        anterior = [("marketing", "0008_revisar_textos_da_interface")]
        atual = [("marketing", "0010_versao_entregas")]
        executor = MigrationExecutor(connection)
        restaurar = executor.loader.graph.leaf_nodes()
        executor.migrate(anterior)
        try:
            antigas = executor.loader.project_state(anterior).apps
            CampanhaAntiga = antigas.get_model("marketing", "Campanha")
            PecaAntiga = antigas.get_model("marketing", "PecaCampanha")
            ChecklistAntigo = antigas.get_model("marketing", "ItemChecklist")
            campanha = CampanhaAntiga.objects.create(nome="Histórico preservado", fase="encerrada")
            peca = PecaAntiga.objects.create(campanha=campanha, nome="Arte pronta", canal="Instagram",
                                            status="pronta", data="2026-09-10")
            anexo = ChecklistAntigo.objects.create(campanha=campanha, chave="arte_final",
                                                    arquivo="marketing/checklist/existente.pdf")
            executor = MigrationExecutor(connection)
            executor.migrate(atual)
            novas = executor.loader.project_state(atual).apps
            preservada = novas.get_model("marketing", "PecaCampanha").objects.get(pk=peca.pk)
            self.assertEqual((preservada.nome, preservada.canal, preservada.status),
                             ("Arte pronta", "Instagram", "pronta"))
            self.assertEqual(str(preservada.data), "2026-09-10")
            self.assertEqual(preservada.tipo, "nao_classificado")
            self.assertIsNone(preservada.concluida_em)
            self.assertIsNone(preservada.concluida_por_id)
            self.assertIsNone(preservada.pagina_captacao_id)
            self.assertEqual(novas.get_model("marketing", "ItemChecklist").objects.get(pk=anexo.pk).arquivo.name,
                             "marketing/checklist/existente.pdf")
        finally:
            MigrationExecutor(connection).migrate(restaurar)
            cache.clear()
