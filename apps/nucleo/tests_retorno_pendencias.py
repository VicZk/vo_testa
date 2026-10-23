"""Retorno contextual: destinos reais, permissões, prefixo e resolução da operação."""

import json
from datetime import timedelta
from html import escape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import get_script_prefix, path, reverse, set_script_prefix
from django.utils import timezone

from apps.comercial.models import EtapaFunil, Oportunidade
from apps.fiscal.models import DocumentoFiscal
from apps.governanca import services as governanca
from apps.lavanderia.models import OrdemLavanderia
from apps.manutencao.models import OrdemServico
from apps.reservas.models import Reserva
from apps.restaurante.models import Comanda

from .models import (
    UH,
    CategoriaFinanceira,
    CategoriaProduto,
    ContaPagarReceber,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    SessaoCaixa,
    TipoUH,
    Usuario,
)
from .modulos import Modulo
from .pendencias import url_pendencias
from .retorno_pendencias import PARAMETRO, RetornoPendenciasMiddleware, com_retorno, validar_retorno


class _UrlsSemCentral:
    urlpatterns = [path("crm/", lambda request: HttpResponse("CRM"), name="dashboard")]


class RetornoPendenciasEscopoTests(SimpleTestCase):
    def _preserva_resposta(self, caminho):
        request = RequestFactory().post(caminho, {PARAMETRO: "/crm/pendencias/", "rascunho": "QA"})
        request.user = SimpleNamespace(is_authenticated=True)
        resposta = HttpResponse("Contrato original", status=302,
            headers={"Location": "/mensagens/", "HX-Redirect": "/crm/destino/"})
        resultado = RetornoPendenciasMiddleware(lambda _: resposta)(request)
        self.assertIs(resultado, resposta)
        self.assertEqual(request.retorno_pendencias, "")
        self.assertEqual(resultado.status_code, 302)
        self.assertEqual(resultado.content, b"Contrato original")
        self.assertEqual(resultado["Location"], "/mensagens/")
        self.assertEqual(resultado["HX-Redirect"], "/crm/destino/")

    @override_settings(ROOT_URLCONF="apps.nucleo.tests_formularios")
    def test_urlconf_sem_crm_preserva_resposta_e_helpers_ignoram_retorno(self):
        self._preserva_resposta("/enviar/")
        self.assertEqual(validar_retorno("/crm/pendencias/", None), "")
        self.assertEqual(com_retorno("/crm/destino/", "/crm/pendencias/"), "/crm/destino/")

    @override_settings(ROOT_URLCONF=_UrlsSemCentral)
    def test_crm_sem_rota_da_central_tambem_preserva_resposta(self):
        self._preserva_resposta("/crm/")
        self.assertEqual(validar_retorno("/crm/pendencias/", None), "")
        self.assertEqual(com_retorno("/crm/destino/", "/crm/pendencias/"), "/crm/destino/")

    def test_pagina_fora_do_crm_ignora_contexto_mesmo_com_rotas_disponiveis(self):
        self._preserva_resposta(reverse("core:politica_privacidade"))


def criar_cenario_retorno():
    """Uma pendência real de cada origem, sem integração externa nem dados pessoais."""
    cache.clear()
    for codigo in Modulo.values:
        ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
    cache.clear()
    c = SimpleNamespace()
    c.usuario = Usuario.objects.create_superuser(username="retorno-qa", password="qa-retorno-local-123")
    c.tipo = TipoUH.objects.create(nome="Quarto retorno QA", tarifa_base="100")
    c.uh = UH.objects.create(numero="RET 01", tipo=c.tipo)
    c.tarefa = governanca.abrir_faxina(c.uh, usuario=c.usuario)
    c.os = OrdemServico.objects.create(uh=c.uh, titulo="Janela retorno QA", criado_por=c.usuario)
    OrdemServico.objects.filter(pk=c.os.pk).update(aberta_em=timezone.now() - timedelta(days=9))
    pessoa = Pessoa.objects.create(nome="Hóspede fictício retorno")
    Reserva.objects.create(
        uh=UH.objects.create(numero="RET 02", tipo=c.tipo), hospede=pessoa,
        checkin=timezone.localdate() - timedelta(days=3), checkout=timezone.localdate() - timedelta(days=1),
        status=Reserva.Status.CONFIRMADA, valor_diaria="100", criado_por=c.usuario,
    )
    c.sessao = SessaoCaixa.objects.create(operador=c.usuario, modulo="nucleo", fundo_troco="0")
    SessaoCaixa.objects.filter(pk=c.sessao.pk).update(aberta_em=timezone.now() - timedelta(days=2))
    categoria = CategoriaFinanceira.objects.create(nome="Retorno QA", tipo="despesa")
    ContaPagarReceber.objects.create(tipo="pagar", categoria=categoria, descricao="Conta retorno QA",
        valor="10", vencimento=timezone.localdate() - timedelta(days=1))
    produto_categoria = CategoriaProduto.objects.create(nome="Retorno QA")
    Produto.objects.create(nome="Produto retorno QA", categoria=produto_categoria, preco_venda="10", estoque_minimo="1")
    local = LocalEstoque.objects.create(nome="Retorno QA", modulo="restaurante")
    comanda = Comanda.objects.create(local=local, criado_por=c.usuario, rotulo="Retorno QA")
    Comanda.objects.filter(pk=comanda.pk).update(aberta_em=timezone.now() - timedelta(days=1))
    OrdemLavanderia.objects.create(rotulo="Retorno QA", criado_por=c.usuario,
        prazo=timezone.localdate() - timedelta(days=1))
    DocumentoFiscal.objects.create(tipo="nfse", natureza="servico", status="rejeitada",
        descricao="Documento fictício retorno QA", criado_por=c.usuario)
    Oportunidade.objects.create(pessoa=pessoa, etapa=EtapaFunil.objects.create(nome="Retorno QA", ordem=1),
        titulo="Oportunidade retorno QA", criado_por=c.usuario, responsavel=c.usuario)
    return c


@override_settings(MFA_OBRIGATORIO=False)
class RetornoPendenciasTests(TestCase):
    def setUp(self):
        self.c = criar_cenario_retorno()
        self.client.force_login(self.c.usuario)
        self.addCleanup(set_script_prefix, get_script_prefix())

    def test_todas_as_dez_origens_oferecem_ida_e_volta_em_destinos_reais(self):
        central = reverse("pendencias") + "?pagina=1"
        resposta = self.client.get(central)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual({item["origem"] for item in resposta.context["itens"]}, {
            "governanca", "manutencao", "reservas", "restaurante", "lavanderia",
            "fiscal", "comercial", "estoque", "caixa", "financeiro",
        })
        for item in resposta.context["itens"]:
            if not item.get("url"):
                continue
            with self.subTest(origem=item["origem"], destino=item["url"]):
                self.assertEqual(parse_qs(urlsplit(item["url_acao"]).query)[PARAMETRO], [central])
                destino = self.client.get(item["url_acao"])
                self.assertContains(destino, "Voltar para Pendências")
                self.assertContains(destino, f'href="{escape(central)}" class="botao-neutro" data-retorno-pendencias-link')
                self.assertNotContains(self.client.get(item["url"]), "data-retorno-pendencias-link")

    def test_governanca_preserva_filtros_pagina_polling_e_post_nativo(self):
        central = url_pendencias("governanca", "pendente") + "&pagina=1"
        resposta = self.client.get(central)
        destino = resposta.context["itens"][0]["url_acao"]
        for chave in ("url_governanca_painel", "url_governanca_quartos"):
            atalho = resposta.context[chave]
            self.assertEqual(parse_qs(urlsplit(atalho).query)[PARAMETRO], [central])
            self.assertContains(self.client.get(atalho), "Voltar para Pendências")
        polling = self.client.get(reverse("pendencias_atualizacoes"), {
            "origem": "governanca", "estado": "pendente", "pagina": "1",
        }).json()
        self.assertIn(escape(destino), polling["html"])
        acao = self.client.post(reverse("governanca:tarefa_acao", args=[self.c.tarefa.pk]),
            {"acao": "iniciar", PARAMETRO: central})
        self.assertEqual(acao.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(acao["Location"]).query)[PARAMETRO], [central])
        self.assertContains(self.client.get(acao["Location"]), "Voltar para Pendências")
        self.assertEqual(self.client.get(central).context["total"], 0)

    def test_manutencao_json_de_formulario_preserva_retorno_depois_da_resolucao(self):
        central = url_pendencias("manutencao", "atencao")
        destino = self.client.get(central).context["itens"][0]["url_acao"]
        acao = self.client.post(reverse("manutencao:concluir", args=[self.c.os.pk]),
            {"resolucao": "Vedação conferida", PARAMETRO: central}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(acao.status_code, 200)
        voltar = acao.json()["redirect"]
        self.assertEqual(parse_qs(urlsplit(voltar).query)[PARAMETRO], [central])
        self.assertEqual(urlsplit(voltar).path, urlsplit(destino).path)
        self.assertContains(self.client.get(voltar), "Voltar para Pendências")
        self.c.os.refresh_from_db()
        self.assertEqual(self.c.os.status, OrdemServico.Status.CONCLUIDA)
        self.assertEqual(self.client.get(central).context["total"], 0)

    def test_post_sem_js_reusa_apenas_referer_do_mesmo_host(self):
        central = url_pendencias("manutencao")
        origem = com_retorno(reverse("manutencao:detalhe", args=[self.c.os.pk]), central)
        for host, espera_retorno in (("externo.invalid", False), ("testserver", True)):
            with self.subTest(host=host):
                resposta = self.client.post(reverse("manutencao:concluir", args=[self.c.os.pk]),
                    {"custo_maodeobra": "inválido"}, HTTP_REFERER=f"http://{host}{origem}")
                self.assertEqual(PARAMETRO in parse_qs(urlsplit(resposta["Location"]).query), espera_retorno)

    def test_retorno_invalido_nunca_cria_link_e_nao_muda_permissoes(self):
        rota = reverse("governanca:quarto", args=[self.c.uh.pk])
        central = reverse("pendencias")
        valores = ["https://externo.invalid" + central, "//externo.invalid" + central,
            "/outro/pendencias/", central + "?next=https://externo.invalid",
            central + "?estado=inexistente", central + "?pagina=0", central + "?pagina=-1",
            central + "?origem=governanca&origem=caixa", central + "#fim", central + "\\malicioso",
            central + "?estado=pendente\n", central + "?pagina=" + "9" * 100]
        for valor in valores:
            with self.subTest(valor=valor):
                resposta = self.client.get(rota, {PARAMETRO: valor})
                self.assertNotContains(resposta, "data-retorno-pendencias-link")
        restrito = Usuario.objects.create_user(username="retorno-restrito", password="qa-local-123")
        restrito.modulos.add(ModuloContratado.objects.get(codigo=Modulo.GOVERNANCA))
        self.client.force_login(restrito)
        self.assertNotContains(self.client.get(rota, {PARAMETRO: url_pendencias("financeiro")}), "data-retorno-pendencias-link")
        self.assertEqual(self.client.get(reverse("manutencao:detalhe", args=[self.c.os.pk]),
            {PARAMETRO: url_pendencias("governanca")}).status_code, 403)

    @override_settings(FORCE_SCRIPT_NAME="/votesta", STATIC_URL="/votesta/static/")
    def test_prefixo_e_ancora_do_destino_sao_preservados(self):
        set_script_prefix("/votesta/")
        central = url_pendencias("financeiro", "atencao") + "&pagina=1"
        resposta = self.client.get(central.removeprefix("/votesta"))
        destino = resposta.context["itens"][0]["url_acao"]
        partes = urlsplit(destino)
        self.assertTrue(partes.path.startswith("/votesta/"))
        self.assertTrue(partes.fragment.startswith("conta-"))
        self.assertEqual(parse_qs(partes.query)["situacao"], ["abertas"])
        self.assertEqual(parse_qs(partes.query)[PARAMETRO], [central])
        self.assertContains(self.client.get(destino.removeprefix("/votesta")), escape(central))
        acao = self.client.post(reverse("manutencao:concluir", args=[self.c.os.pk]).removeprefix("/votesta"),
            {PARAMETRO: url_pendencias("manutencao"), "resolucao": "Conferida"})
        self.assertTrue(acao["Location"].startswith("/votesta/"))
        self.assertEqual(parse_qs(urlsplit(acao["Location"]).query)[PARAMETRO], [url_pendencias("manutencao")])

    def test_headers_htmx_locais_preservam_origem_sem_vazar_para_url_externa(self):
        central = url_pendencias("manutencao")
        local = reverse("manutencao:painel") + "?situacao=todas#lista"
        request = RequestFactory().get(reverse("manutencao:painel"), {PARAMETRO: central})
        request.user = self.c.usuario
        response = HttpResponse(headers={"HX-Redirect": local, "HX-Push-Url": local,
            "HX-Location": json.dumps({"path": local, "target": "#conteudo"}),
            "Location": "https://externo.invalid/retorno"})
        result = RetornoPendenciasMiddleware(lambda _: response)(request)
        for nome in ("HX-Redirect", "HX-Push-Url"):
            self.assertEqual(result[nome], com_retorno(local, central))
        self.assertEqual(json.loads(result["HX-Location"])["path"], com_retorno(local, central))
        self.assertEqual(result["Location"], "https://externo.invalid/retorno")
        self.assertEqual(com_retorno("//externo.invalid/retorno", central), "//externo.invalid/retorno")
