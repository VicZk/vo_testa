"""Entregas sem campanha: vínculos explícitos, produção, acesso e concorrência."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.comercial.models import PaginaCaptacao
from apps.nucleo.models import ModuloContratado, TrilhaAuditoria, Usuario
from apps.nucleo.modulos import Modulo

from . import services, services_entregas
from .forms_entregas import EntregaForm
from .models import Campanha, ItemChecklist, PecaCampanha


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class EntregasAvulsasTests(TestCase):
    def setUp(self):
        cache.clear()
        for codigo in (Modulo.MARKETING, Modulo.COMERCIAL):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="avulsas")
        self.client.force_login(self.usuario)
        self.campanha = Campanha.objects.create(nome="Campanha existente", fase="producao")
        self.outra = Campanha.objects.create(nome="Outra campanha", fase="ideia")
        self.lista = reverse("marketing:entregas")

    def dados(self, **alteracoes):
        return {"nome": "Material avulso", "campanha": "", "tipo": "post", "canal": "Instagram",
                "data": "", "status": "a_fazer", "versao": "1", "url_material": "",
                "material_checklist": "", "pagina_captacao": "", **alteracoes}

    def criar(self, **alteracoes):
        resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(**alteracoes))
        self.assertEqual(resposta.status_code, 302)
        return PecaCampanha.objects.latest("pk")

    def formulario(self, peca=None, **alteracoes):
        form = EntregaForm(self.dados(**alteracoes), usuario=self.usuario, peca=peca)
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data

    def test_nova_avulsa_nao_escolhe_campanha_e_nova_vinculada_exige_escolha(self):
        inicial = self.client.get(reverse("marketing:nova_entrega"))
        self.assertIsNone(inicial.context["form"]["campanha"].value())
        self.assertFalse(inicial.context["form"].fields["campanha"].required)
        avulsa = self.criar()
        vinculada = self.criar(campanha=str(self.campanha.pk), nome="Material da campanha")
        self.assertIsNone(avulsa.campanha_id)
        self.assertEqual(vinculada.campanha_id, self.campanha.pk)
        resposta = self.client.get(self.lista, {"vinculo": "sem"})
        self.assertContains(resposta, "Sem campanha")
        self.assertEqual(list(resposta.context["pagina"]), [avulsa])
        self.assertNotContains(resposta, f"&amp;campanha={self.campanha.pk}")

    def test_avulsa_edita_conclui_reabre_e_audita_sem_publicar(self):
        peca = self.criar()
        for estado, versao in (("em_producao", 1), ("pronta", 2), ("em_producao", 3)):
            resposta = self.client.post(reverse("marketing:estado_entrega", args=[peca.pk]), {
                "status": estado, "versao": versao, "voltar": self.lista + "?vinculo=sem"})
            self.assertRedirects(resposta, self.lista + "?vinculo=sem", fetch_redirect_response=False)
            peca.refresh_from_db()
            self.assertEqual(peca.status, estado)
            self.assertIsNone(peca.campanha_id)
            self.assertEqual(peca.concluida_por_id, self.usuario.pk if estado == "pronta" else None)
        self.assertTrue(TrilhaAuditoria.objects.filter(
            usuario=self.usuario, alvo="PecaCampanha", alvo_id=str(peca.pk), acao="estado_entrega").exists())
        self.campanha.refresh_from_db()
        self.assertEqual(self.campanha.fase, "producao")
        self.assertIsNone(self.campanha.aprovada_em)

    def test_vinculo_explicito_com_anexo_preserva_producao_e_nao_pode_ser_trocado(self):
        peca = self.criar(status="em_producao")
        material = ItemChecklist.objects.create(campanha=self.campanha, chave="arte_final",
            arquivo=SimpleUploadedFile("material.pdf", b"material sintetico", "application/pdf"))
        url = reverse("marketing:editar_entrega", args=[peca.pk])
        resposta = self.client.post(url, self.dados(campanha=str(self.campanha.pk),
            material_checklist=str(material.pk), status="em_producao"))
        self.assertEqual(resposta.status_code, 302)
        peca.refresh_from_db()
        self.assertEqual((peca.campanha_id, peca.material_checklist_id, peca.versao),
                         (self.campanha.pk, material.pk, 2))
        self.assertTrue(TrilhaAuditoria.objects.filter(
            alvo="PecaCampanha", alvo_id=str(peca.pk), acao="vinculo_entrega").exists())
        for destino in (None, self.outra):
            with self.assertRaisesMessage(ValidationError, "não pode ser removido ou trocado"):
                services_entregas.salvar_entrega(peca=peca, usuario=self.usuario,
                    dados={**self.formulario(peca, versao="2"), "campanha": destino})
        resposta = self.client.post(url, self.dados(campanha=str(self.outra.pk), versao="2"))
        self.assertEqual(resposta.status_code, 302)
        peca.refresh_from_db()
        self.assertEqual(peca.campanha_id, self.campanha.pk)
        self.assertTrue(self.client.get(url).context["form"].fields["campanha"].disabled)

    def test_edicao_antiga_nao_vincula_nem_sobrescreve_avulsa(self):
        peca = self.criar()
        services_entregas.alterar_estado(peca, "em_producao", self.usuario, versao=1)
        resposta = self.client.post(reverse("marketing:editar_entrega", args=[peca.pk]),
                                   self.dados(campanha=str(self.campanha.pk)))
        self.assertContains(resposta, "mudou em outra tela")
        peca.refresh_from_db()
        self.assertEqual((peca.campanha_id, peca.status, peca.versao), (None, "em_producao", 2))

    def test_avulsa_rejeita_anexo_de_campanha_e_id_inexistente(self):
        material = ItemChecklist.objects.create(campanha=self.campanha, chave="arte_final", arquivo="qa.pdf")
        resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(material_checklist=material.pk))
        self.assertIn("material_checklist", resposta.context["form"].errors)
        resposta = self.client.post(reverse("marketing:nova_entrega"), self.dados(campanha="999999"))
        self.assertIn("campanha", resposta.context["form"].errors)
        self.assertFalse(PecaCampanha.objects.exists())
        with self.assertRaises(ValidationError):
            PecaCampanha(nome="Avulsa", material_checklist=material).full_clean()

    def test_filtros_resumos_paginacao_e_links_incluem_avulsas(self):
        self.criar(nome="Vinculada", campanha=str(self.campanha.pk))
        PecaCampanha.objects.bulk_create([
            PecaCampanha(nome=f"Avulsa {i:02}", tipo="post", canal="Instagram") for i in range(35)])
        todas = self.client.get(self.lista)
        self.assertEqual(todas.context["pagina"].paginator.count, 36)
        avulsas = self.client.get(self.lista, {"vinculo": "sem", "canal": "Instagram", "tipo": "post"})
        segunda = self.client.get(self.lista, {"vinculo": "sem", "canal": "Instagram", "tipo": "post", "pagina": 2})
        self.assertEqual(avulsas.context["pagina"].paginator.count, 35)
        self.assertEqual(len(segunda.context["pagina"]), 5)
        resumo = next(r for r in avulsas.context["resumo_tipos"] if r["tipo"] == "post")
        self.assertEqual(resumo["total"], 35)
        self.assertIn("vinculo=sem", resumo["url_pendentes"])
        self.assertContains(avulsas, "vinculo=sem")
        vinculadas = self.client.get(self.lista, {"vinculo": "com"})
        self.assertEqual(vinculadas.context["pagina"].paginator.count, 1)
        especifica = self.client.get(self.lista, {"campanha": self.campanha.pk})
        self.assertEqual(especifica.context["pagina"].paginator.count, 1)
        self.assertEqual(next(i["valor"] for i in especifica.context["vinculos"] if i["ativo"]), "com")
        busca = self.client.get(self.lista, {"q": "Avulsa 03"})
        self.assertEqual(busca.context["pagina"].paginator.count, 1)

    def test_agenda_e_urgencias_sem_campanha_preservam_prazo_e_canal(self):
        hoje = timezone.localdate()
        proxima = self.criar(data=hoje.isoformat())
        atrasada = self.criar(nome="Avulsa atrasada", data=(hoje - timedelta(days=1)).isoformat())
        self.assertEqual(services.banda_proximos()[0]["entrega_id"], proxima.pk)
        self.assertEqual(services.banda_atrasados()[0]["entrega_id"], atrasada.pk)
        self.assertEqual(services.banda_proximos()[0]["campanha"], "Sem campanha")
        quadro = self.client.get(reverse("marketing:quadro"), {"canal": "Instagram"})
        for entrega in (proxima, atrasada):
            self.assertContains(quadro, reverse("marketing:editar_entrega", args=[entrega.pk]))
        self.assertNotContains(quadro, "/campanha/None/")
        for vista in ("semana", "mes", "ano"):
            resposta = self.client.get(reverse("marketing:calendario"), {
                "vista": vista, "data": hoje.isoformat(), "ano": hoje.year, "mes": hoje.month,
                "canal": "Instagram"})
            self.assertContains(resposta, proxima.nome)
            self.assertContains(resposta, "Sem campanha")
            self.assertNotContains(resposta, "/campanha/None/")

    def test_avulsa_lp_exige_acesso_e_sobrevive_ao_apagamento_da_referencia(self):
        pagina = PaginaCaptacao.objects.create(nome="LP sintética", slug="avulsa-qa", criado_por=self.usuario)
        peca = self.criar(tipo="lp", pagina_captacao=str(pagina.pk))
        self.assertContains(self.client.get(self.lista), "Abrir LP")
        self.assertRedirects(self.client.get(reverse("marketing:abrir_lp", args=[peca.pk])),
                             pagina.get_absolute_url(), fetch_redirect_response=False)
        restrito = Usuario.objects.create_user(username="so-marketing-avulsa")
        restrito.modulos.add(ModuloContratado.objects.get(codigo=Modulo.MARKETING))
        self.client.force_login(restrito)
        self.assertNotContains(self.client.get(self.lista), "Abrir LP")
        self.assertEqual(self.client.get(reverse("marketing:abrir_lp", args=[peca.pk])).status_code, 403)
        pagina.delete()
        peca.refresh_from_db()
        self.assertIsNone(peca.pagina_captacao_id)
        self.assertIsNone(peca.campanha_id)

    def test_excluir_campanha_preserva_entrega_sem_anexo_orfao(self):
        material = ItemChecklist.objects.create(campanha=self.campanha, chave="arte_final", arquivo="qa.pdf")
        peca = self.criar(campanha=str(self.campanha.pk), material_checklist=str(material.pk))
        self.campanha.delete()
        peca.refresh_from_db()
        self.assertIsNone(peca.campanha_id)
        self.assertIsNone(peca.material_checklist_id)
        self.assertEqual(peca.nome, "Material avulso")
        self.assertContains(self.client.get(self.lista), peca.nome)
        services_entregas.alterar_estado(peca, "em_producao", self.usuario, versao=1)

    def test_csrf_permissao_modulo_e_metodo_protegem_avulsa(self):
        peca = self.criar()
        estado = reverse("marketing:estado_entrega", args=[peca.pk])
        remover = reverse("marketing:remover_peca", args=[peca.pk])
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.usuario)
        for url in (reverse("marketing:nova_entrega"), estado, remover):
            self.assertEqual(protegido.post(url, self.dados(status="pronta")).status_code, 403)
        self.assertEqual(self.client.get(estado).status_code, 405)
        self.assertEqual(self.client.get(remover).status_code, 405)
        restrito = Usuario.objects.create_user(username="sem-marketing-avulsa")
        self.client.force_login(restrito)
        for url in (self.lista, reverse("marketing:editar_entrega", args=[peca.pk])):
            self.assertEqual(self.client.get(url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            services_entregas.alterar_estado(peca, "pronta", restrito, versao=1)
        ModuloContratado.objects.filter(codigo=Modulo.MARKETING).update(ativo=False)
        cache.clear()
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(estado, {"status": "pronta", "versao": 1}).status_code, 404)
        with self.assertRaises(PermissionDenied):
            services_entregas.salvar_entrega(dados={"campanha": None}, usuario=self.usuario)
        peca.refresh_from_db()
        self.assertEqual(peca.status, "a_fazer")

    def test_remocao_e_rota_legada_exigem_versao_e_suportam_avulsa(self):
        peca = self.criar()
        resposta = self.client.post(reverse("marketing:marcar_peca", args=[peca.pk]),
                                   {"status": "em_producao", "versao": 1})
        self.assertRedirects(resposta, self.lista, fetch_redirect_response=False)
        remover = reverse("marketing:remover_peca", args=[peca.pk])
        self.client.post(remover, {"versao": 1})
        self.assertTrue(PecaCampanha.objects.filter(pk=peca.pk).exists())
        resposta = self.client.post(remover, {"versao": 2})
        self.assertRedirects(resposta, self.lista, fetch_redirect_response=False)
        self.assertFalse(PecaCampanha.objects.filter(pk=peca.pk).exists())


class AvulsasConcorrenciaTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="avulsa-concorrencia")
        self.peca = PecaCampanha.objects.create(nome="Material concorrente", tipo="post")
        self.campanhas = [Campanha.objects.create(nome=f"Campanha {i}", fase="producao") for i in range(2)]

    def disputar(self, operacoes):
        barreira = Barrier(2)

        def gravar(operacao):
            close_old_connections()
            try:
                usuario = Usuario.objects.get(pk=self.usuario.pk)
                peca = PecaCampanha.objects.get(pk=self.peca.pk)
                barreira.wait(timeout=10)
                try:
                    operacao(peca, usuario)
                except ValidationError:
                    return "conflito"
                return "gravou"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(gravar, operacoes, timeout=25))
        self.assertCountEqual(resultados, ["gravou", "conflito"])
        self.peca.refresh_from_db()
        self.assertEqual(self.peca.versao, 2)

    def test_duas_acoes_rapidas_na_avulsa_gravam_uma_versao(self):
        self.disputar([
            lambda p, u: services_entregas.alterar_estado(p, "em_producao", u, versao=1),
            lambda p, u: services_entregas.alterar_estado(p, "pronta", u, versao=1),
        ])
        self.assertIsNone(self.peca.campanha_id)

    def test_dois_vinculos_simultaneos_nao_trocam_campanha_nem_travam_em_ciclo(self):
        def vincular(campanha):
            def operacao(peca, usuario):
                services_entregas.salvar_entrega(peca=peca, usuario=usuario, dados={
                    "campanha": campanha, "nome": peca.nome, "tipo": "post", "canal": "",
                    "data": None, "status": "a_fazer", "url_material": "", "material_checklist": None,
                    "pagina_captacao": None, "versao": 1})
            return operacao
        self.disputar([vincular(campanha) for campanha in self.campanhas])
        self.assertIn(self.peca.campanha_id, [c.pk for c in self.campanhas])
        self.assertEqual(TrilhaAuditoria.objects.filter(
            alvo="PecaCampanha", alvo_id=str(self.peca.pk), acao="vinculo_entrega").count(), 1)
        self.assertTrue(all(c.fase == "producao" for c in Campanha.objects.all()))


class AvulsasMigrationTests(TransactionTestCase):
    def test_migracao_preserva_vinculos_e_dados_e_reverte_sem_avulsas(self):
        anterior = [("marketing", "0010_versao_entregas")]
        novo = [("marketing", "0011_entregas_avulsas")]
        executor = MigrationExecutor(connection)
        restaurar = executor.loader.graph.leaf_nodes()
        executor.migrate(anterior)
        try:
            historico = executor.loader.project_state(anterior).apps
            campanha = historico.get_model("marketing", "Campanha").objects.create(nome="Campanha preservada")
            peca = historico.get_model("marketing", "PecaCampanha").objects.create(
                campanha_id=campanha.pk, nome="Entrega preservada", tipo="impresso", status="pronta",
                canal="Recepção", versao=7, url_material="https://example.com/qa.pdf")
            executor = MigrationExecutor(connection)
            executor.migrate(novo)
            Modelo = executor.loader.project_state(novo).apps.get_model("marketing", "PecaCampanha")
            preservada = Modelo.objects.get(pk=peca.pk)
            self.assertEqual((preservada.campanha_id, preservada.nome, preservada.tipo, preservada.status,
                              preservada.canal, preservada.versao, preservada.url_material),
                             (campanha.pk, "Entrega preservada", "impresso", "pronta", "Recepção", 7,
                              "https://example.com/qa.pdf"))
            avulsa = Modelo.objects.create(nome="Avulsa sintética", tipo="post", campanha=None)
            self.assertIsNone(avulsa.campanha_id)
            # Reversão do NOT NULL só é possível sem avulsas; nunca inferir vínculos.
            avulsa.delete()
            MigrationExecutor(connection).migrate(anterior)
            self.assertEqual(historico.get_model("marketing", "PecaCampanha").objects.get(pk=peca.pk).campanha_id,
                             campanha.pk)
        finally:
            MigrationExecutor(connection).migrate(restaurar)
            cache.clear()
