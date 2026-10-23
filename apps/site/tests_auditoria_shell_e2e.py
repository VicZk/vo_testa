"""Regressões do shell: abas, carga fria, gráficos sob demanda e diálogos."""
import json
import os
import unittest
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import ConfiguracaoReservas, ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class AuditoriaShellE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.usuario = Usuario.objects.create_superuser(
            username="shell-auditoria", first_name="Recepção", last_name="Auditoria", password="forte-local-123")
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={"feriados_automaticos": False})
        self.page.set_viewport_size({"width": 1440, "height": 768})
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.erros = []
        self.page.on("pageerror", lambda erro: self.erros.append(str(erro)))

    def abrir(self, nome="estoque:posicao"):
        resposta = self.page.goto(self.url(reverse(nome)), wait_until="load")
        self.assertEqual(resposta.status, 200)
        expect(self.page.locator("#conteudo")).to_be_visible()
        self.page.evaluate("window.__shell = {menu:document.querySelector('#menu-principal'), app:document.querySelector('#app')}")

    def clicar_menu(self, chave):
        item = self.page.locator(f'#menu-principal [data-nav="{chave}"]')
        item.click()

    def registrar(self, nome, dados):
        pasta = os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            (destino / f"shell-{nome}.json").write_text(json.dumps(dados, indent=2), encoding="utf-8")
            self.page.evaluate("""async () => {
              await Promise.all(document.getAnimations().filter(a =>
                a.effect.getTiming().iterations !== Infinity).map(a => a.finished.catch(()=>{})));
            }""")
            self.page.screenshot(path=str(destino / f"shell-{nome}.png"), full_page=True)

    def test_abas_preservam_documento_menu_e_opacidade_tambem_no_historico(self):
        for movimento in ("no-preference", "reduce"):
            with self.subTest(movimento=movimento):
                self.page.emulate_media(reduced_motion=movimento)
                self.abrir()
                self.page.evaluate("""() => {
                  window.__opacidades=[]; window.__estaveis=[]; window.__efeitos=[]; window.__amostrar=true;
                  function medir() {
                    const c=document.querySelector('#conteudo');
                    if(c) window.__opacidades.push(Number(getComputedStyle(c).opacity));
                    document.querySelectorAll('.sidebar,.pagina-cabecalho,.abas-secao').forEach(el=>
                      window.__estaveis.push(Number(getComputedStyle(el).opacity)));
                    document.getAnimations().filter(a=>a.id==='navegacao-conteudo-local').forEach(a=>{
                      const alvo=a.effect.target;
                      window.__efeitos.push({opacidade:Number(getComputedStyle(alvo).opacity),
                        incluiTitulo:!!alvo.querySelector('.pagina-cabecalho,.abas-secao'),
                        global:alvo.id==='conteudo'||alvo.classList.contains('sidebar')});
                    });
                    if(window.__amostrar) requestAnimationFrame(medir);
                  } medir();
                }""")
                destino = reverse("estoque:produtos")
                with self.page.expect_response(lambda r: r.url.endswith(destino) and r.request.headers.get("hx-request") == "true"):
                    self.page.locator(f'.abas-secao a[href="{destino}"]').click()
                expect(self.page).to_have_url(self.url(destino))
                self.assertTrue(self.page.evaluate("window.__shell.menu === document.querySelector('#menu-principal')"))
                self.page.go_back()
                expect(self.page).to_have_url(self.url(reverse("estoque:posicao")))
                self.page.go_forward()
                expect(self.page).to_have_url(self.url(destino))
                self.assertEqual(self.page.locator("#menu-principal details").count(), 0, "grupos do menu são categorias fixas, não recolhíveis")
                expect(self.page.locator('[data-nav="estoque"]')).to_be_visible()
                self.page.evaluate("window.__amostrar=false")
                valores = self.page.evaluate("window.__opacidades")
                self.assertTrue(valores and min(valores) == 1, valores)
                self.assertEqual(min(self.page.evaluate("window.__estaveis")), 1)
                efeitos = self.page.evaluate("window.__efeitos")
                if movimento == "reduce":
                    self.assertEqual(efeitos, [])
                else:
                    self.assertTrue(efeitos, "Conteúdo novo deve manter uma transição localizada")
                    self.assertTrue(all(not e["global"] and not e["incluiTitulo"] for e in efeitos), efeitos)
                    self.assertGreaterEqual(min(e["opacidade"] for e in efeitos), .91)
                self.assertTrue(self.page.evaluate("window.__shell.app === document.querySelector('#app')"))
                self.assertEqual(self.erros, [])
                self.registrar(movimento, {"opacidade_minima": min(valores), "amostras": len(valores), "efeitos_locais": efeitos})

    def test_chart_carrega_so_quando_necessario_e_navegacao_reinicializa(self):
        requisicoes = []
        self.page.on("request", lambda req: requisicoes.append(req.url) if "chart.umd" in req.url else None)
        self.abrir()
        self.assertEqual(requisicoes, [])
        self.assertFalse(self.page.evaluate("!!window.Chart"))
        self.clicar_menu("dashboard")
        expect(self.page).to_have_url(self.url(reverse("dashboard")))
        self.page.wait_for_function("window.Chart && Object.values(Chart.instances).some(c => c.canvas.isConnected)")
        self.assertEqual(len(requisicoes), 1)
        self.clicar_menu("estoque")
        expect(self.page).to_have_url(self.url(reverse("estoque:posicao")))
        self.clicar_menu("dashboard")
        self.page.wait_for_function("Object.values(Chart.instances).some(c => c.canvas.isConnected)")
        self.assertEqual(len(requisicoes), 1)
        self.page.evaluate("""() => {
          window.__canvasReanimados=[];
          const animar=Element.prototype.animate;
          Element.prototype.animate=function(...args) {
            if(this.matches('canvas') || this.querySelector('canvas')) window.__canvasReanimados.push(this.id);
            return animar.apply(this,args);
          };
        }""")
        with self.page.expect_response(lambda r: r.url.endswith(reverse("dashboard")) and r.request.headers.get("hx-request") == "true"):
            self.clicar_menu("dashboard")
        self.page.wait_for_function("Object.values(Chart.instances).some(c => c.canvas.isConnected)")
        self.assertTrue(self.page.evaluate("Object.values(Chart.instances).filter(c=>c.canvas.isConnected).every(c=>c.options.animation===false)"))
        self.assertEqual(self.page.evaluate("window.__canvasReanimados"), [])
        self.assertEqual(self.erros, [])

    def test_somente_blocos_alterados_animam_com_ou_sem_abas(self):
        origem, destino = reverse("estoque:posicao"), reverse("estoque:produtos")
        for com_abas in (True, False):
            with self.subTest(com_abas=com_abas):
                self.page.emulate_media(reduced_motion="no-preference")

                def resposta_controlada(route):
                    resposta = route.fetch()
                    html = resposta.text()
                    novo = route.request.url.endswith(destino)
                    classe = "cenario-destino" if novo else "cenario-origem"
                    html = html.replace('hx-history-elt class="conteudo ', f'hx-history-elt class="conteudo {classe} ', 1)
                    abas = f'<nav class="abas-secao"><a href="{destino}">Produtos</a></nav>' if com_abas else ""
                    profundo = '<div>' * 64 + '<p data-estavel>Configuração preservada</p>' + '</div>' * 64
                    # Cabeçalho sem classe de página: a estabilidade depende do
                    # conteúdo, não de um seletor especial ou de haver abas.
                    trecho = f'''<span hidden data-nav-contexto="estoque"></span><div id="cenario"><h1 data-estavel>Painel da operação</h1>{abas}
                      <section id="resumo"><article data-estavel><strong>12</strong><span>Quartos</span></article>
                        <p data-estavel>Os valores são atualizados pela equipe.</p>
                        <form data-estavel><input type="hidden" name="csrfmiddlewaretoken" value="{'novo' if novo else 'antigo'}"><label>Busca<input name="q"></label></form>
                        <div id="lista"><p>{'Produto novo' if novo else 'Produto antigo'}</p></div>
                      </section>{profundo}<a id="proximo" href="{destino}">Ver produtos</a></div>'''
                    inicio = html.index(">", html.index("<main")) + 1
                    fim = html.index("</main>", inicio)
                    route.fulfill(response=resposta, body=html[:inicio] + trecho + html[fim:])

                self.page.route("**" + origem, resposta_controlada)
                self.page.route("**" + destino, resposta_controlada)
                self.abrir()
                self.page.evaluate("""() => {
                  window.__alvosAlterados=[];
                  const animar=Element.prototype.animate;
                  Element.prototype.animate=function(...args) {
                    if(this.closest('#conteudo'))window.__alvosAlterados.push({
                      id:this.id,estavel:this.matches('[data-estavel]')||!!this.querySelector('[data-estavel]'),
                      incluiLista:this.id==='lista'||!!this.querySelector('#lista')||!!this.closest('#lista')});
                    return animar.apply(this,args);
                  };
                }""")
                self.page.locator("#proximo").click()
                expect(self.page).to_have_url(self.url(destino))
                self.page.wait_for_function("window.__alvosAlterados.length > 0")
                alvos = self.page.evaluate("window.__alvosAlterados")
                self.assertTrue(all(not alvo["estavel"] for alvo in alvos), alvos)
                self.assertTrue(any(alvo["incluiLista"] for alvo in alvos), alvos)
                self.assertFalse(any(alvo["id"] in ("conteudo", "cenario", "resumo") for alvo in alvos), alvos)
                self.assertEqual(self.erros, [])
                self.registrar("diff-" + ("abas" if com_abas else "sem-abas"), {"alvos": alvos})
                self.assertIn("cenario-destino", self.page.locator("#conteudo").get_attribute("class"))
                self.page.go_back()
                expect(self.page).to_have_url(self.url(origem))
                self.assertIn("cenario-origem", self.page.locator("#conteudo").get_attribute("class"))
                self.page.unroute("**" + origem, resposta_controlada)
                self.page.unroute("**" + destino, resposta_controlada)

    def test_chave_ativa_e_identica_no_get_htmx_e_reload(self):
        self.abrir()
        for rota, chave in (("conciliacao:painel", "conciliacao"), ("comercial:paginas", "comercial_paginas"), ("daypass:painel", "reservas")):
            with self.subTest(rota=rota):
                # A primeira visita é GET normal; o reload usa a mesma fonte.
                self.page.goto(self.url(reverse(rota)), wait_until="load")
                expect(self.page.locator("#menu-principal .ativo")).to_have_count(1)
                expect(self.page.locator("#menu-principal .ativo")).to_have_attribute("data-nav", chave)
                self.page.reload(wait_until="load")
                expect(self.page.locator("#menu-principal .ativo")).to_have_attribute("data-nav", chave)
        self.clicar_menu("comercial_paginas")
        expect(self.page).to_have_url(self.url(reverse("comercial:paginas")))
        expect(self.page.locator("#menu-principal .ativo")).to_have_count(1)
        expect(self.page.locator("#menu-principal .ativo")).to_have_attribute("data-nav", "comercial_paginas")
        self.assertEqual(self.erros, [])

    def test_gaveta_foca_item_segura_pagina_e_devolve_rolagem(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir()
        self.page.evaluate("document.querySelector('#conteudo').style.minHeight='2000px'; window.scrollTo(0,300)")
        antes = self.page.evaluate("window.scrollY")
        self.page.evaluate("abrirSidebarMobile()")
        self.assertTrue(self.page.evaluate("document.querySelector('#menu-principal').contains(document.activeElement)"))
        self.assertEqual(self.page.locator("body").evaluate("el=>getComputedStyle(el).position"), "fixed")
        expect(self.page.locator(".busca-global kbd")).to_be_hidden()
        self.page.keyboard.press("Escape")
        self.assertEqual(self.page.evaluate("window.scrollY"), antes)
        self.assertNotEqual(self.page.locator("body").evaluate("el=>getComputedStyle(el).position"), "fixed")
        self.registrar("gaveta", {"scroll_antes": antes, "scroll_depois": self.page.evaluate("window.scrollY")})

    def test_links_nao_boostam_post_download_modal_e_confirmam_edicao(self):
        self.abrir()
        self.page.evaluate("""() => {
          const c=document.querySelector('#conteudo');
          c.insertAdjacentHTML('beforeend', '<form data-edicao-pendente data-dirty="1" method="post"><input name="teste"></form>');
        }""")
        destino = reverse("estoque:produtos")
        self.page.once("dialog", lambda dialogo: dialogo.dismiss())
        self.page.locator(f'.abas-secao a[href="{destino}"]').click()
        expect(self.page).to_have_url(self.url(reverse("estoque:posicao")))
        self.assertEqual(self.page.locator("form[hx-boost='true']").count(), 0)
        self.page.once("dialog", lambda dialogo: dialogo.accept())
        self.page.locator(f'.abas-secao a[href="{destino}"]').click()
        expect(self.page).to_have_url(self.url(destino))
        self.page.evaluate("abrirNovaReserva()")
        expect(self.page.locator("#modal-conteudo form")).to_be_visible()
        self.assertEqual(self.page.locator("#modal-conteudo [data-navegacao-shell]").count(), 0)
        self.page.keyboard.press("Escape")
        self.assertEqual(self.erros, [])

    def test_sessao_expirada_abre_login_como_documento_inteiro(self):
        from django.contrib.sessions.models import Session

        self.abrir()
        # Expira a sessão no servidor; respostas em voo não podem revalidá-la.
        Session.objects.all().delete()
        self.page.locator(f'.abas-secao a[href="{reverse("estoque:produtos")}"]').click()
        expect(self.page.locator("#menu-principal")).to_have_count(0)
        expect(self.page.locator('input[name="password"]')).to_be_visible()

    def test_dependencia_nova_no_head_preserva_execucao_com_documento_completo(self):
        self.abrir()
        destino = reverse("estoque:produtos")

        def pagina_com_dependencia(route):
            resposta = route.fetch()
            html = resposta.text().replace("</head>", "<script>window.__headDaPagina = 42;</script></head>")
            route.fulfill(response=resposta, body=html)

        self.page.route("**" + destino, pagina_com_dependencia)
        self.page.locator(f'.abas-secao a[href="{destino}"]').click()
        self.page.wait_for_function("window.__headDaPagina === 42")
        self.assertFalse(self.page.evaluate("!!window.__shell"))
        expect(self.page).to_have_url(self.url(destino))
        self.assertEqual(self.erros, [])

    def test_csv_por_query_continua_download_nativo(self):
        self.abrir("conciliacao:fechamento")
        exportar = self.page.locator('a[href*="export=csv"]')
        self.assertIsNone(exportar.get_attribute("data-navegacao-shell"))
        with self.page.expect_download() as arquivo:
            exportar.click()
        self.assertTrue(arquivo.value.suggested_filename.endswith(".csv"))
        self.assertTrue(self.page.evaluate("window.__shell.menu === document.querySelector('#menu-principal')"))

    def test_menu_renova_quando_mudam_os_modulos_permitidos(self):
        self.abrir()
        expect(self.page.locator('[data-nav="loja"]')).to_have_count(1)
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=False)
        cache.clear()
        destino = reverse("estoque:produtos")
        self.page.locator(f'.abas-secao a[href="{destino}"]').click()
        expect(self.page).to_have_url(self.url(destino))
        expect(self.page.locator('[data-nav="loja"]')).to_have_count(0)
        self.assertFalse(self.page.evaluate("!!window.__shell"))

    def test_toasts_formam_fila_sem_ocultar_erro_por_timeout(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir()
        self.page.clock.install()
        self.page.evaluate("toast('Erro persistente', 'error'); toast('Segundo aviso', 'info'); toast('Terceiro aviso', 'success')")
        self.page.clock.fast_forward(6000)
        expect(self.page.locator('#toasts .toast:visible')).to_have_count(1)
        expect(self.page.locator('#toasts .toast:visible')).to_contain_text("Erro persistente")
        self.assertAlmostEqual(self.page.locator('#toasts .toast:not([hidden]) .toast-x').bounding_box()["height"], 44, delta=.01)
        self.page.locator('#toasts .toast:visible .toast-x').click()
        expect(self.page.locator('#toasts .toast:visible')).to_contain_text("Segundo aviso")
        self.page.locator('#toasts .toast:visible .toast-x').click()
        expect(self.page.locator('#toasts .toast:visible')).to_contain_text("Terceiro aviso")
        self.registrar("fila-toasts", {"visiveis": self.page.locator('#toasts .toast:visible').count()})

    def test_rolagem_restaurada_antes_da_primeira_pintura(self):
        self.abrir()
        chave = self.page.locator("#menu-principal").get_attribute("data-rolagem-chave")
        codigo = f"""(() => {{
          const chave={json.dumps(chave)};
          sessionStorage.setItem(chave,'350');
          new PerformanceObserver(lista=>{{
            if(lista.getEntries().some(e=>e.name==='first-contentful-paint'))
              window.__primeiraRolagem=document.querySelector('#menu-principal')?.scrollTop;
          }}).observe({{type:'paint',buffered:true}});
        }})()"""
        self.page.add_init_script(codigo)
        cdp = self.page.context.new_cdp_session(self.page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 80,
            "downloadThroughput": 200000, "uploadThroughput": 100000,
        })
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        self.page.reload(wait_until="load")
        self.page.wait_for_function("window.__primeiraRolagem !== undefined")
        self.assertAlmostEqual(self.page.evaluate("window.__primeiraRolagem"), 350, delta=1)
        self.assertAlmostEqual(self.page.locator("#menu-principal").evaluate("el=>el.scrollTop"), 350, delta=1)
        self.registrar("primeira-pintura", {"scroll_primeira_pintura": self.page.evaluate("window.__primeiraRolagem")})
