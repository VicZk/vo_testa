"""Comparador Nginx no Chromium: páginas fictícias, HTMX real, nenhum acesso externo."""

import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.test import SimpleTestCase

from .tests_e2e import _PLAYWRIGHT_OK

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect, sync_playwright


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class ComparadorHistoricoE2ETests(SimpleTestCase):
    """Interceta toda requisição; o teste não usa sessões, servidor ou banco reais."""

    VERSOES = {
        "antiga": {
            "origem": "https://votesta-original.195-200-0-150.sslip.io", "prefixo": "",
            "destino": "https://viczk.cloud/votesta", "rotulo": "Versão atualizada",
        },
        "nova": {
            "origem": "https://viczk.cloud", "prefixo": "/votesta",
            "destino": "https://votesta-original.195-200-0-150.sslip.io", "rotulo": "Versão anterior",
        },
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.htmx = (Path(settings.BASE_DIR) / "static/vendor/htmx-2.0.4.min.js").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    @contextmanager
    def _pagina(self, versao, *, publico=False):
        config = self.VERSOES[versao]
        origem, prefixo = config["origem"], config["prefixo"]
        script = (Path(settings.BASE_DIR) / f"deploy/vps/comparador/{versao}.js").read_text(encoding="utf-8")
        contexto = self.browser.new_context(service_workers="block")
        pedidos, erros = [], []

        def responder(route):
            pedido = route.request
            pedidos.append({"url": pedido.url, "tipo": pedido.resource_type, "headers": pedido.headers})
            partes = urlsplit(pedido.url)
            if partes.path.endswith("/fixture-htmx.js"):
                route.fulfill(body=self.htmx, content_type="text/javascript; charset=utf-8")
                return
            if partes.path.endswith("/_comparar.js"):
                route.fulfill(body=script, content_type="text/javascript; charset=utf-8")
                return
            if partes.netloc != urlsplit(origem).netloc:
                route.fulfill(body="<!doctype html><meta charset='utf-8'><title>Destino fictício</title><h1>Outra versão</h1>",
                              content_type="text/html; charset=utf-8")
                return
            titulo = "Estoque" if "/estoque/" in partes.path else "Painel"
            if publico:
                classe = "site-nav-desktop" if versao == "nova" else "lg:flex"
                corpo = f'''<header><nav class="{classe}"><a href="/">Início</a></nav></header>
                  <div id="mobileMenu"><div class="flex-col"><a class="mobile-link" href="/">Início</a></div></div>
                  <main id="conteudo"><h1>{titulo}</h1></main>'''
            else:
                corpo = f'''<div id="app"><aside class="sidebar"><nav hx-boost="true"
                  hx-target="#conteudo" hx-select="#conteudo" hx-swap="outerHTML show:none">
                  <a id="estoque" href="{prefixo}/crm/estoque/?local=2#saldo">Estoque</a>
                  </nav></aside><main id="conteudo"><h1>{titulo}</h1></main></div>'''
            route.fulfill(body=f'''<!doctype html><html><head><meta charset="utf-8"><title>{titulo}</title>
              <meta name="htmx-config" content='{{"includeIndicatorStyles":false}}'>
              <style>.nav-item {{display:flex;align-items:center;gap:8px;padding:12px}}
                .ico {{width:24px;height:24px}} .sidebar {{width:260px}}</style>
              <script src="{prefixo}/fixture-htmx.js" defer></script>
              <script src="{prefixo}/_comparar.js" defer></script></head><body>{corpo}</body></html>''',
                          content_type="text/html; charset=utf-8")

        # A rota cobre também popups e origens de destino. Nenhum pedido sai à rede.
        contexto.route("**/*", responder)
        contexto.add_init_script("""window.restauracoes = 0;
          document.addEventListener('htmx:historyRestore', () => window.restauracoes++);""")
        pagina = contexto.new_page()
        pagina.on("pageerror", lambda erro: erros.append(str(erro)))
        inicial = origem + prefixo + ("/?aba=chegadas#topo" if publico else "/crm/?aba=chegadas#topo")
        try:
            pagina.goto(inicial)
            pagina.locator("#comparador-mobile" if publico else "#comparador-item").wait_for()
            yield pagina, contexto, config, pedidos
            self.assertEqual(erros, [])
        finally:
            contexto.close()

    def _ir_e_voltar(self, pagina, config):
        inicial = pagina.url
        pagina.evaluate("window.linkAntes = document.getElementById('comparador-item')")
        pagina.locator("#estoque").click()
        pagina.wait_for_url(config["origem"] + config["prefixo"] + "/crm/estoque/?local=2#saldo")
        expect(pagina.locator("#conteudo h1")).to_have_text("Estoque")
        expect(pagina.locator("#comparador-item")).to_have_attribute(
            "href", config["destino"] + "/crm/estoque/?local=2#saldo")
        pagina.go_back()
        pagina.wait_for_url(inicial)
        pagina.wait_for_function("window.restauracoes === 1")
        expect(pagina.locator("#conteudo h1")).to_have_text("Painel")
        # O link foi recriado a partir de HTML serializado; listeners do nó antigo
        # não podem ser a razão de o teste passar.
        self.assertTrue(pagina.evaluate("window.linkAntes !== document.getElementById('comparador-item')"))
        expect(pagina.locator("#comparador-item")).to_have_attribute(
            "href", config["destino"] + "/crm/?aba=chegadas#topo")

    def test_troca_nativa_apos_voltar_e_avancar_no_historico_htmx(self):
        for versao in self.VERSOES:
            with self.subTest(versao=versao), self._pagina(versao) as (pagina, _, config, pedidos):
                self._ir_e_voltar(pagina, config)
                pagina.go_forward()
                pagina.wait_for_function("window.restauracoes === 2")
                expect(pagina.locator("#comparador-item")).to_have_attribute(
                    "href", config["destino"] + "/crm/estoque/?local=2#saldo")
                pagina.go_back()
                pagina.wait_for_function("window.restauracoes === 3")
                pagina.locator("#comparador-item svg").click()
                pagina.wait_for_url(config["destino"] + "/crm/?aba=chegadas#topo")
                expect(pagina.get_by_role("heading", name="Outra versão")).to_be_visible()
                destino = pedidos[-1]
                self.assertEqual(destino["tipo"], "document")
                self.assertNotIn("hx-request", destino["headers"])

    def test_ctrl_meio_e_enter_preservam_navegacao_nativa_apos_restore(self):
        for versao in self.VERSOES:
            for clique in ({"modifiers": ["Control"]}, {"button": "middle"}):
                with self.subTest(versao=versao, clique=clique), self._pagina(versao) as (pagina, contexto, config, _):
                    self._ir_e_voltar(pagina, config)
                    inicial = pagina.url
                    destino = config["destino"] + "/crm/?aba=chegadas#topo"
                    # O Chromium do Windows pode expor o evento da primeira aba
                    # em segundo plano só no gesto seguinte. A requisição document
                    # nativa é emitida imediatamente e comprova o destino aberto.
                    with contexto.expect_event("request", predicate=lambda pedido:
                            pedido.url == destino.split("#", 1)[0]
                            and pedido.resource_type == "document", timeout=5000) as aberto:
                        pagina.locator("#comparador-item svg").click(**clique)
                    self.assertTrue(aberto.value.is_navigation_request())
                    self.assertNotIn("hx-request", aberto.value.headers)
                    self.assertEqual(pagina.url, inicial)
            with self.subTest(versao=versao, gesto="Enter"), self._pagina(versao) as (pagina, _, config, _):
                self._ir_e_voltar(pagina, config)
                pagina.locator("#comparador-item").focus()
                pagina.keyboard.press("Enter")
                pagina.wait_for_url(config["destino"] + "/crm/?aba=chegadas#topo")

    def test_menu_contexto_e_meta_atualizam_href_sem_cancelar_evento(self):
        for versao in self.VERSOES:
            with self.subTest(versao=versao), self._pagina(versao) as (pagina, _, config, _):
                self._ir_e_voltar(pagina, config)
                novo = config["prefixo"] + "/crm/produtos/?q=agua#historico"
                pagina.evaluate("caminho => history.replaceState(history.state, '', caminho)", novo)
                for evento, modificador in (("contextmenu", "metaKey"), ("click", "metaKey"), ("click", "ctrlKey")):
                    estado = pagina.locator("#comparador-item").evaluate("""(link, [nome, modificador]) => {
                      let cancelado;
                      document.addEventListener(nome, evento => {
                        cancelado = evento.defaultPrevented;
                        evento.preventDefault(); // O teste só observa a intenção de abrir.
                      }, {once: true});
                      link.querySelector('svg').dispatchEvent(new MouseEvent(nome, {
                        bubbles: true, cancelable: true, [modificador]: true,
                        button: nome === 'contextmenu' ? 2 : 0
                      }));
                      return {cancelado, href: link.href};
                    }""", [evento, modificador])
                    self.assertFalse(estado["cancelado"])
                    self.assertEqual(estado["href"], config["destino"] + "/crm/produtos/?q=agua#historico")

    def test_links_publicos_e_dicas_se_mantem_apos_nos_serem_recriados(self):
        for versao in self.VERSOES:
            with self.subTest(versao=versao), self._pagina(versao, publico=True) as (pagina, _, config, _):
                destino = config["destino"] + "/?aba=chegadas#topo"
                for id_ in ("comparador-mobile", "comparador-desktop"):
                    expect(pagina.locator("#" + id_)).to_have_attribute("href", destino)
                    expect(pagina.locator("#" + id_)).to_have_attribute("hx-boost", "false")
                pagina.evaluate("""() => {
                  document.body.innerHTML = document.body.innerHTML;
                  document.dispatchEvent(new CustomEvent('htmx:historyRestore'));
                }""")
                expect(pagina.locator("#comparador-mobile")).to_have_count(1)
                expect(pagina.locator("#comparador-desktop")).to_have_count(1)
                pagina.locator("#comparador-mobile").click()
                pagina.wait_for_url(destino)
        with self._pagina("nova") as (pagina, _, config, _):
            self._ir_e_voltar(pagina, config)
            pagina.evaluate("document.getElementById('app').classList.add('recolhida')")
            expect(pagina.locator("#comparador-item")).to_have_attribute("data-dica", "Versão anterior")
            pagina.evaluate("document.getElementById('app').classList.remove('recolhida')")
            expect(pagina.locator("#comparador-item")).not_to_have_attribute("data-dica", "Versão anterior")
