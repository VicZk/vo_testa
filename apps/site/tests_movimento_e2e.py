"""Transições de navegação preservam a casca, o histórico e o último destino."""

import json
import os
import unittest
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class MovimentoNavegacaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        for modulo in Modulo:
            ModuloContratado.objects.update_or_create(codigo=modulo, defaults={"ativo": True})
        usuario = Usuario.objects.create_user(
            username="movimento-e2e", password="forte-123-abc", is_superuser=True, is_staff=True)
        self.client.force_login(usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.set_viewport_size({"width": 1440, "height": 900})

    def abrir(self):
        self.page.goto(self.url(reverse("dashboard")), wait_until="networkidle")
        self.page.evaluate("document.fonts.ready")
        self.page.evaluate("""() => {
          window.__navegacao={nativas:0,entradas:[],frames:[],finalizado:true};
          const original=document.startViewTransition?.bind(document);
          if(original)document.startViewTransition=callback=>{
            window.__navegacao.nativas++;
            return original(callback);
          };
          const animar=Element.prototype.animate;
          Element.prototype.animate=function(...args){
            if(this.id==='conteudo')window.__navegacao.entradas.push({id:this.id,frames:args[0]});
            return animar.apply(this,args);
          };
          document.addEventListener('htmx:beforeRequest',e=>{
            if(e.detail.target?.id!=='conteudo')return;
            const menu=document.getElementById('menu-principal'),sidebar=menu.closest('.sidebar');
            const referencia=menu.querySelector('a[href*=governanca]');
            const pos=referencia.getBoundingClientRect(), topo=menu.scrollTop;
            const fim=performance.now()+800;
            window.__navegacao.finalizado=false;
            const medir=()=>{
              const p=referencia.getBoundingClientRect();
              const animacoes=document.getAnimations().map(a=>({
                nome:a.animationName,pseudo:a.effect?.pseudoElement,
                alvo:a.effect?.target?.id,
              }));
              window.__navegacao.frames.push({dx:p.x-pos.x,dy:p.y-pos.y,scroll:menu.scrollTop-topo,
                conectado:menu.isConnected,menus:document.querySelectorAll('#menu-principal').length,
                topo:getComputedStyle(document.querySelector('.topbar')).transform,
                sidebar:getComputedStyle(sidebar).transform,
                old:getComputedStyle(document.documentElement,'::view-transition-old(menu)').display,
                atual:getComputedStyle(document.documentElement,'::view-transition-new(menu)').opacity,
                animacoes});
              if(performance.now()<fim)requestAnimationFrame(medir);
              else window.__navegacao.finalizado=true;
            };requestAnimationFrame(medir);
          });
        }""")

    def ir(self, rota):
        self.page.locator(f'#menu-principal a[href="{reverse(rota)}"]').click()
        self.page.wait_for_url("**" + reverse(rota))
        self.page.wait_for_function("window.__navegacao.finalizado")

    def test_menu_aberto_e_recolhido_ficam_parados_durante_troca_real(self):
        self.abrir()
        for recolhido in (False, True):
            if recolhido:
                self.page.get_by_role("button", name="Recolher menu", exact=True).click()
                self.page.wait_for_timeout(350)
            self.page.locator("#menu-principal").evaluate("el=>el.scrollTop=100")
            for rota in ("governanca:painel", "manutencao:painel", "estoque:posicao"):
                self.ir(rota)
        medidas = self.page.evaluate("window.__navegacao")
        self.assertEqual(medidas["nativas"], 6)
        self.assertGreater(len(medidas["frames"]), 60)
        self.assertTrue(any(
            a.get("pseudo") == "::view-transition-new(conteudo)"
            for f in medidas["frames"] for a in f["animacoes"]))
        self.assertTrue(all(
            abs(f["dx"]) < 1 and abs(f["dy"]) < 1 and abs(f["scroll"]) < 1
            and f["conectado"] and f["menus"] == 1 and f["topo"] == "none"
            and f["sidebar"] == "none" and f["old"] == "none" and f["atual"] == "1"
            for f in medidas["frames"]), medidas["frames"])
        # O fade de página não roda duas vezes (snapshot + animação do elemento).
        self.assertEqual(medidas["entradas"], [])
        destino = os.environ.get("MOVIMENTO_E2E_SCREENSHOTS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / "frames-menu.json").write_text(json.dumps(medidas), encoding="utf-8")

    def test_historico_anima_so_conteudo_e_preserva_scroll_do_menu(self):
        self.abrir()
        self.ir("governanca:painel")
        self.ir("manutencao:painel")
        self.page.locator("#menu-principal").evaluate("el=>el.scrollTop=100")
        self.page.wait_for_timeout(40)
        self.page.go_back()
        self.page.wait_for_url("**" + reverse("governanca:painel"))
        self.page.wait_for_function("window.__navegacao.entradas.length===1")
        self.assertEqual(self.page.locator("#menu-principal").evaluate("el=>el.scrollTop"), 100)
        self.page.go_forward()
        self.page.wait_for_url("**" + reverse("manutencao:painel"))
        self.page.wait_for_function("window.__navegacao.entradas.length===2")
        self.assertEqual(self.page.locator("#menu-principal").evaluate("el=>el.scrollTop"), 100)
        self.assertEqual(self.page.locator("#menu-principal").count(), 1)
        entradas = self.page.evaluate("window.__navegacao.entradas")
        self.assertTrue(all(e["id"] == "conteudo" for e in entradas))

    def test_reduced_motion_fallback_e_modal_nao_animam_a_casca(self):
        self.abrir()
        self.page.emulate_media(reduced_motion="reduce")
        self.ir("governanca:painel")
        self.assertEqual(self.page.evaluate("window.__navegacao.nativas"), 0)
        self.assertEqual(self.page.evaluate("window.__navegacao.entradas"), [])
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.evaluate("document.startViewTransition=undefined")
        self.ir("manutencao:painel")
        self.assertEqual(self.page.evaluate("window.__navegacao.entradas.length"), 1)
        self.page.locator(".acao-topo").click()
        expect(self.page.locator("#modal-reserva")).to_be_visible()
        self.assertEqual(self.page.evaluate("window.__navegacao.entradas.length"), 1)
        self.assertEqual(self.page.evaluate("window.__navegacao.nativas"), 0)
        self.assertEqual(self.page.locator("#conteudo").evaluate("el=>getComputedStyle(el).opacity"), "1")

    def test_ultimo_clique_vence_resposta_anterior_lenta(self):
        pendentes = []
        rota_lenta = reverse("governanca:painel")
        conteudo_lento = self.client.get(rota_lenta).content.decode()
        self.page.route("**" + rota_lenta, lambda route: pendentes.append(route))
        self.abrir()
        with self.page.expect_request(lambda req: req.url.endswith(rota_lenta)):
            self.page.locator(f'#menu-principal a[href="{rota_lenta}"]').click()
        self.page.locator(f'#menu-principal a[href="{reverse("manutencao:painel")}"]').click()
        self.page.wait_for_url("**" + reverse("manutencao:painel"))
        self.assertEqual(len(pendentes), 1)
        pendentes[0].fulfill(content_type="text/html", body=conteudo_lento)
        self.page.wait_for_timeout(300)
        self.assertTrue(self.page.url.endswith(reverse("manutencao:painel")))
        expect(self.page.locator("#menu-principal .nav-item.ativo")).to_have_attribute(
            "href", reverse("manutencao:painel"))
        self.assertEqual(self.page.locator("#menu-principal").count(), 1)

    def test_gaveta_mobile_fecha_sem_congelar_snapshot_do_menu(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir()
        self.page.get_by_role("button", name="Abrir menu", exact=True).click()
        self.page.locator("#menu-principal").evaluate("el=>el.scrollTop=100")
        self.ir("governanca:painel")
        expect(self.page.locator(".sidebar")).to_be_hidden()
        expect(self.page.get_by_role("button", name="Abrir menu", exact=True)).to_be_focused()
        self.assertEqual(self.page.evaluate("window.__navegacao.nativas"), 0)
        self.assertEqual(self.page.evaluate("window.__navegacao.entradas.length"), 1)
        self.assertNotEqual(self.page.evaluate("getComputedStyle(document.body).overflow"), "hidden")
        medidas = self.page.evaluate("window.__navegacao.frames")
        self.assertTrue(all(f["conectado"] and f["menus"] == 1 for f in medidas))
        posicao = self.page.locator("#menu-principal").evaluate("el=>el.scrollTop")
        self.page.get_by_role("button", name="Abrir menu", exact=True).click()
        expect(self.page.locator(".sidebar")).to_be_visible()
        self.assertEqual(self.page.locator("#menu-principal").evaluate("el=>el.scrollTop"), posicao)

    def test_abas_mostram_destino_ativo_e_navegam_por_teclado(self):
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        for largura in (320, 390, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 844})
            p.goto(self.url(reverse("estoque:cadastros")))
            p.evaluate("document.fonts.ready")
            p.wait_for_function("""() => {
              const faixa=document.querySelector('.abas-secao').getBoundingClientRect();
              const ativo=document.querySelector('.abas-secao [aria-current=page]').getBoundingClientRect();
              return ativo.left>=faixa.left-1 && ativo.right<=faixa.right+1;
            }""")
            abas = p.locator(".abas-secao a").evaluate_all(
                "els=>els.map(el=>({y:el.getBoundingClientRect().top,h:el.getBoundingClientRect().height}))")
            self.assertLess(max(a["y"] for a in abas) - min(a["y"] for a in abas), 1)
            self.assertTrue(all(a["h"] >= 44 for a in abas))
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
        p.set_viewport_size({"width": 390, "height": 600})
        compras = p.locator('.abas-secao a').first
        compras.focus()
        expect(compras).to_be_in_viewport(ratio=1)
        compras.press("Enter")
        expect(p).to_have_url(self.url(reverse("estoque:compras")))
        expect(p.locator('.abas-secao [aria-current="page"]')).to_have_text("Compras")
        p.locator('.abas-secao a').last.focus()
        p.keyboard.press("Enter")
        expect(p).to_have_url(self.url(reverse("estoque:cadastros")))
        p.wait_for_load_state("load")
        p.evaluate("document.fonts.ready")
        expect(p.locator('.abas-secao [aria-current="page"]')).to_have_text("Cadastros")
        rolagem = 180
        p.evaluate("window.scrollTo(0, 180)")
        p.wait_for_function("esperado => Math.abs(window.scrollY-esperado)<2", arg=rolagem)
        p.evaluate("""rotas => {
          window.__trocaAbas={concluida:false,restaurada:false};
          document.addEventListener('htmx:afterSettle',e=>{
            if(e.detail.target?.id==='conteudo' && location.pathname===rotas.governanca)
              window.__trocaAbas.concluida=true;
          });
          document.addEventListener('htmx:historyRestore',()=>{
            if(location.pathname===rotas.cadastros)window.__trocaAbas.restaurada=true;
          });
        }""", {"governanca": reverse("governanca:painel"), "cadastros": reverse("estoque:cadastros")})
        p.get_by_role("button", name="Abrir menu", exact=True).click()
        p.locator(f'#menu-principal a[href="{reverse("governanca:painel")}"]').click()
        expect(p).to_have_url(self.url(reverse("governanca:painel")))
        p.wait_for_function("window.__trocaAbas.concluida && window.scrollY===0")
        p.go_back()
        expect(p).to_have_url(self.url(reverse("estoque:cadastros")))
        p.wait_for_function("window.__trocaAbas.restaurada")
        expect(p.locator('.abas-secao [aria-current="page"]')).to_have_text("Cadastros")
        p.wait_for_function("""() => {
          const faixa=document.querySelector('.abas-secao').getBoundingClientRect();
          const ativo=document.querySelector('.abas-secao [aria-current=page]').getBoundingClientRect();
          return ativo.left>=faixa.left-1 && ativo.right<=faixa.right+1;
        }""")
        p.wait_for_function("esperado => Math.abs(window.scrollY-esperado)<2", arg=rolagem)

    def test_voltar_antes_de_concluir_troca_preserva_rolagem_restaurada(self):
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        p.set_viewport_size({"width": 390, "height": 600})
        p.goto(self.url(reverse("estoque:cadastros")))
        p.evaluate("document.fonts.ready")
        p.evaluate("window.scrollTo(0, 180)")
        p.wait_for_function("Math.abs(window.scrollY-180)<2")
        p.evaluate("""() => {
          htmx.config.defaultSettleDelay=300;
          window.__retornoAntesSettle={sequencia:[],concluido:false};
          document.addEventListener('htmx:afterSwap',e=>{
            if(e.detail.target?.id!=='conteudo')return;
            // O nó sai do documento no Voltar; observar nele garante que o
            // callback antigo terminou antes de medir a rolagem restaurada.
            document.getElementById('conteudo').addEventListener('htmx:afterSettle',()=>{
              window.__retornoAntesSettle.sequencia.push('settle');
              requestAnimationFrame(()=>{
                window.__retornoAntesSettle.rolagem=window.scrollY;
                window.__retornoAntesSettle.concluido=true;
              });
            },{once:true});
            history.back();
          },{once:true});
          document.addEventListener('htmx:historyRestore',()=>{
            window.__retornoAntesSettle.sequencia.push('historico');
          },{once:true});
        }""")
        p.get_by_role("button", name="Abrir menu", exact=True).click()
        p.locator(f'#menu-principal a[href="{reverse("governanca:painel")}"]').click()
        p.wait_for_function("window.__retornoAntesSettle.concluido")
        expect(p).to_have_url(self.url(reverse("estoque:cadastros")))
        expect(p.locator('.abas-secao [aria-current="page"]')).to_have_text("Cadastros")
        resultado = p.evaluate("window.__retornoAntesSettle")
        self.assertEqual(resultado["sequencia"], ["historico", "settle"])
        self.assertAlmostEqual(resultado["rolagem"], 180, delta=1)
