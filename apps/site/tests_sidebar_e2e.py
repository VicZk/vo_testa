"""Geometria e continuidade da sidebar, medidas no navegador com dados fictícios."""

import os
import unittest
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class SidebarOperacaoE2ETests(_BaseE2E):
    """Compara caixas reais; não exige uma técnica de CSS ou largura do trilho."""

    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import ModuloContratado, Usuario
        from apps.nucleo.modulos import Modulo

        cache.clear()
        self.usuario = Usuario.objects.create_superuser(
            username="sidebar-operacao", password="forte-123-abc")
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.pendentes = 1
        self.page.route("**/crm/governanca/atualizacoes/", self._responder_avisos)
        self.page.set_viewport_size({"width": 1440, "height": 760})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("""if (localStorage.getItem('sidebar') === null) {
          localStorage.setItem('sidebar', 'aberta');
        }""")
        # A autenticação não é o objeto desta regressão; usa a sessão Django real.
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.goto(self.url(reverse("restaurante:comandas")), wait_until="load")
        self.page.locator(".sidebar").wait_for()
        self._esperar_layout()

    def _responder_avisos(self, route):
        route.fulfill(json={
            "pendentes": self.pendentes, "total": 1000,
            "ultima": None, "quartos_atualizados_em": None,
        })

    def _esperar_layout(self):
        self.page.evaluate("""async () => {
          await document.fonts.ready;
          const app = document.querySelector('.app'), sidebar = document.querySelector('.sidebar');
          const animacoes = [...app.getAnimations(), ...sidebar.getAnimations({subtree: true})];
          await Promise.all(animacoes.map(a => a.finished.catch(() => {})));
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")

    def _estado(self, recolhida):
        atual = self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')")
        if atual != recolhida:
            self.page.locator("#btn-recolher").click()
        self._esperar_layout()

    def _contagem(self, numero):
        self.pendentes = numero
        with self.page.expect_response("**/crm/governanca/atualizacoes/"):
            self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        badge = self.page.locator("[data-governanca-avisos]")
        if numero:
            expect(badge).to_be_visible()
            expect(badge).to_have_text("99+" if numero > 99 else str(numero))
        else:
            expect(badge).to_be_hidden()
        self._esperar_layout()

    def _foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / ("sidebar-" + nome + ".png")))

    @contextmanager
    def _ponteiro(self, toque):
        if not toque:
            yield
            return
        original = self.page
        contexto = self._browser.new_context(
            locale="pt-BR", has_touch=True, is_mobile=False,
            viewport={"width": 1440, "height": 760})
        contexto.add_cookies(original.context.cookies())
        self.page = contexto.new_page()
        self.page.route("**/crm/governanca/atualizacoes/", self._responder_avisos)
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        try:
            self.page.goto(self.url(reverse("restaurante:comandas")), wait_until="load")
            self._esperar_layout()
            self.assertTrue(self.page.evaluate("matchMedia('(pointer:coarse)').matches"))
            yield
        finally:
            contexto.close()
            self.page = original

    def _conferir_badge(self, numero):
        medidas = self.page.evaluate("""() => {
          const badge = document.querySelector('[data-governanca-avisos]');
          const item = badge.closest('.nav-item'), rotulo = item.querySelector('.rotulo');
          const r = el => { const x = el.getBoundingClientRect(); return {
            left:x.left, right:x.right, top:x.top, bottom:x.bottom,
            cx:x.left+x.width/2, cy:x.top+x.height/2}; };
          const faixa = document.createRange(); faixa.selectNodeContents(badge);
          const texto = faixa.getBoundingClientRect();
          return {badge:r(badge), item:r(item), ico:r(item.querySelector('.ico')),
            rotulo:r(rotulo), opacidade:Number(getComputedStyle(rotulo).opacity),
            texto:{cx:texto.left+texto.width/2, cy:texto.top+texto.height/2},
            acessivel:[badge.getAttribute('aria-label'), badge.title,
              item.getAttribute('aria-label'), item.title].filter(Boolean).join(' ')};
        }""")
        b, item = medidas["badge"], medidas["item"]
        self.assertLessEqual(abs(b["cy"] - item["cy"]), 1, medidas)
        self.assertLessEqual(abs(medidas["texto"]["cx"] - b["cx"]), 1, medidas)
        self.assertLessEqual(abs(medidas["texto"]["cy"] - b["cy"]), 2, medidas)
        self.assertGreaterEqual(b["left"], medidas["ico"]["right"] + 1, medidas)
        if medidas["opacidade"] > .9:
            self.assertGreaterEqual(b["left"], medidas["rotulo"]["right"] + 1, medidas)
        self.assertGreaterEqual(b["left"], item["left"], medidas)
        self.assertLessEqual(b["right"], item["right"] + .5, medidas)
        if numero > 99:
            self.assertIn(str(numero), medidas["acessivel"], medidas)
        expect(self.page.locator("[data-governanca-avisos]")).to_have_accessible_name(
            f"{numero} serviço(s) de limpeza pendente(s)")

    def test_icones_centrados_no_realce_com_e_sem_espaco_da_barra(self):
        self._estado(True)
        self._contagem(999)
        self.page.set_viewport_size({"width": 1024, "height": 600})
        for modo, largura in (("classica14", 14), ("classica17", 17), ("sobreposta", 0)):
            with self.subTest(barra=modo):
                estilo = self.page.add_style_tag(content=f"""
                  .sidebar nav {{ scrollbar-width: {'auto' if largura else 'none'} !important; }}
                  .sidebar nav::-webkit-scrollbar {{ width: {largura}px !important; }}
                """)
                self._esperar_layout()
                for posicao in (0, 10_000):
                    self.page.locator("#menu-principal").evaluate("(el, y) => { el.scrollTop = y; }", posicao)
                    self._esperar_layout()
                    medidas = self.page.evaluate("""() => {
                      const nav = document.querySelector('#menu-principal'), nr = nav.getBoundingClientRect();
                      const itens = [...nav.querySelectorAll('.nav-item')].map(el => {
                        const caixa = el.getBoundingClientRect(), ico = el.querySelector('.ico').getBoundingClientRect();
                        return {nome: el.textContent.trim(), visivel: caixa.top >= nr.top && caixa.bottom <= nr.bottom,
                          dx: (ico.left + ico.width / 2) - (caixa.left + caixa.width / 2),
                          dy: (ico.top + ico.height / 2) - (caixa.top + caixa.height / 2)};
                      }).filter(el => el.visivel);
                      return {gutter: nav.offsetWidth - nav.clientWidth,
                        rola: nav.scrollHeight > nav.clientHeight, itens};
                    }""")
                    self.assertTrue(medidas["rola"], medidas)
                    if largura:
                        self.assertGreater(medidas["gutter"], 0, "o caso precisa de scrollbar que ocupe espaço")
                    else:
                        self.assertEqual(medidas["gutter"], 0)
                    self.assertGreater(len(medidas["itens"]), 1)
                    for item in medidas["itens"]:
                        self.assertLessEqual(abs(item["dx"]), 1, item)
                        self.assertLessEqual(abs(item["dy"]), 1, item)
                self._foto("trilho-" + modo)
                self._conferir_badge(999)
                estilo.evaluate("el => el.remove()")

    def test_badges_centrados_sem_cobrir_icone_ou_rotulo_em_todos_os_estados(self):
        p = self.page
        for largura in (320, 390, 768, 820, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 844})
            estados = ("mobile",) if largura <= 820 else ("aberta", "recolhida")
            for estado in estados:
                with self.subTest(largura=largura, estado=estado):
                    if estado == "mobile":
                        p.locator("#btn-menu-mobile").click()
                    else:
                        self._estado(estado == "recolhida")
                    self._esperar_layout()
                    p.locator("[data-governanca-avisos]").locator("..").scroll_into_view_if_needed()
                    for numero in (0, 1, 10, 99, 999):
                        with self.subTest(contagem=numero):
                            self._contagem(numero)
                            if numero:
                                self._conferir_badge(numero)
                    self._foto(f"badge-{estado}-{largura}")
                    if estado == "mobile":
                        p.keyboard.press("Escape")
                        self._esperar_layout()

    def test_transicoes_e_reversao_rapida_nao_sobrepoem_nem_movem_itens_verticalmente(self):
        for toque in (False, True):
            with self.subTest(ponteiro="toque" if toque else "mouse"), self._ponteiro(toque):
                if toque:
                    alvos = self.page.locator(".sidebar .nav-item, .sidebar-toggle, .sidebar button.link").evaluate_all(
                        "els => els.map(el => ({nome:el.textContent.trim(), altura:el.getBoundingClientRect().height}))")
                    for alvo in alvos:
                        self.assertGreaterEqual(alvo["altura"], 44, alvo)
                self._conferir_transicoes("toque" if toque else "mouse")

    def _conferir_transicoes(self, ponteiro):
        self._contagem(999)
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.locator("#menu-principal").evaluate("el => { el.scrollTop = 0; }")
        self._esperar_layout()
        resultado = self.page.evaluate("""async () => {
          const app = document.querySelector('.app'), sb = document.querySelector('.sidebar');
          const itens = [...sb.querySelectorAll('.nav-item')];
          const origemY = itens.map(el => el.querySelector('.ico').getBoundingClientRect().top);
          const falhas = new Set(), detalhes = {}, larguras = [], inicio = performance.now();
          let quadros = 0, maiorDy = 0, proxima = 0;
          const alternancias = [0, 90, 180, 520];
          function visivel(el) {
            if (!el) return null;
            let r = el.getBoundingClientRect();
            let caixa = {left:r.left, right:r.right, top:r.top, bottom:r.bottom};
            for (let atual = el; atual; atual = atual.parentElement) {
              const css = getComputedStyle(atual);
              if (css.display === 'none' || css.visibility === 'hidden' || Number(css.opacity) < .05) return null;
              if (atual !== el) {
                r = atual.getBoundingClientRect();
                if (/(hidden|clip|auto|scroll)/.test(css.overflowX)) {
                  caixa.left = Math.max(caixa.left, r.left); caixa.right = Math.min(caixa.right, r.right);
                }
                if (/(hidden|clip|auto|scroll)/.test(css.overflowY)) {
                  caixa.top = Math.max(caixa.top, r.top); caixa.bottom = Math.min(caixa.bottom, r.bottom);
                }
              }
            }
            return caixa.right > caixa.left && caixa.bottom > caixa.top ? caixa : null;
          }
          function colide(a, b, nome) {
            const x = visivel(a), y = visivel(b);
            if (x && y && Math.min(x.right,y.right)-Math.max(x.left,y.left) > .5 &&
                Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top) > .5) {
              falhas.add(nome);
              if (!detalhes[nome]) detalhes[nome] = {ms:Math.round(performance.now()-inicio),
                largura:sb.getBoundingClientRect().width, a:x, b:y,
                opacidade:getComputedStyle(a).opacity};
            }
          }
          await new Promise(resolve => {
            function quadro(agora) {
              while (proxima < alternancias.length && agora-inicio >= alternancias[proxima]) {
                document.querySelector('#btn-recolher').click(); proxima++;
              }
              quadros++; larguras.push(sb.getBoundingClientRect().width);
              itens.forEach((el, i) => {
                maiorDy = Math.max(maiorDy, Math.abs(el.querySelector('.ico').getBoundingClientRect().top-origemY[i]));
                const badge = el.querySelector('.nav-badge');
                colide(badge, el.querySelector('.ico'), 'badge/ícone');
                colide(badge, el.querySelector('.rotulo'), 'badge/rótulo');
              });
              colide(sb.querySelector('.marca-full'), sb.querySelector('.sidebar-toggle'), 'logo/botão');
              colide(sb.querySelector('.marca-icone'), sb.querySelector('.sidebar-toggle'), 'símbolo/botão');
              colide(sb.querySelector('.avatar'), sb.querySelector('button.link'), 'avatar/sair');
              colide(sb.querySelector('.usuario-texto'), sb.querySelector('button.link'), 'nome/sair');
              if (agora-inicio < 950) requestAnimationFrame(quadro); else resolve();
            }
            requestAnimationFrame(quadro);
          });
          return {quadros, maiorDy, falhas:[...falhas], detalhes,
            variacao:Math.max(...larguras)-Math.min(...larguras)};
        }""")
        self.assertGreaterEqual(resultado["quadros"], 6, resultado)
        self.assertGreater(resultado["variacao"], 30, "o teste precisa observar a transição real")
        self.assertLessEqual(resultado["maiorDy"], 1, resultado)
        self.assertEqual(resultado["falhas"], [], resultado)
        self._foto("apos-transicoes-" + ponteiro)

    def _posicao_restaurante(self):
        return self.page.locator("#menu-principal").evaluate("""(nav, href) => ({
          scroll:nav.scrollTop,
          y:nav.querySelector(`a[href="${href}"]`).getBoundingClientRect().top
        })""", reverse("restaurante:comandas"))

    def test_restaurante_pontos_reload_e_historico_preservam_a_posicao_do_menu(self):
        p = self.page
        p.set_viewport_size({"width": 1280, "height": 640})
        for recolhida in (False, True):
            with self.subTest(recolhida=recolhida):
                p.goto(self.url(reverse("restaurante:comandas")), wait_until="load")
                self._estado(recolhida)
                p.locator("#menu-principal").evaluate("""(nav, href) => {
                  const item = nav.querySelector(`a[href="${href}"]`);
                  nav.scrollTop += item.getBoundingClientRect().top-nav.getBoundingClientRect().top-45;
                }""", reverse("restaurante:comandas"))
                self._esperar_layout()
                antes = self._posicao_restaurante()
                self.assertGreater(antes["scroll"], 40, antes)
                p.evaluate("window.__documentoSidebar = true")
                p.get_by_role("navigation", name="Seções do Restaurante").get_by_role(
                    "link", name="Pontos", exact=True).click()
                expect(p).to_have_url(self.url(reverse("restaurante:mesas")))
                self._esperar_layout()
                self.assertFalse(p.evaluate("Boolean(window.__documentoSidebar)"),
                                 "Pontos deve exercitar navegação completa")
                for etapa in ("pontos", "reload", "voltar", "avancar"):
                    if etapa == "reload":
                        p.reload(wait_until="load")
                    elif etapa == "voltar":
                        p.go_back(wait_until="load")
                        expect(p).to_have_url(self.url(reverse("restaurante:comandas")))
                    elif etapa == "avancar":
                        p.go_forward(wait_until="load")
                        expect(p).to_have_url(self.url(reverse("restaurante:mesas")))
                    self._esperar_layout()
                    depois = self._posicao_restaurante()
                    with self.subTest(etapa=etapa):
                        self.assertLessEqual(abs(depois["scroll"] - antes["scroll"]), 1, (antes, depois))
                        self.assertLessEqual(abs(depois["y"] - antes["y"]), 1, (antes, depois))
                # O runner não garante BFCache nativo. Exercita sua ramificação
                # com o evento real, simulando outra página que mudou a posição
                # da aba enquanto este documento permanecia congelado.
                recente = p.evaluate("""() => {
                  const nav = document.querySelector('#menu-principal');
                  const top = Math.min(nav.scrollTop + 47, nav.scrollHeight-nav.clientHeight);
                  sessionStorage.setItem(nav.dataset.rolagemChave, String(top));
                  window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));
                  return top;
                }""")
                self._esperar_layout()
                self.assertLessEqual(abs(self._posicao_restaurante()["scroll"] - recente), 1,
                                     "pageshow.persisted usou a memória antiga em vez da posição atual da aba")
                self._foto("pontos-" + ("recolhida" if recolhida else "aberta"))

    def test_gaveta_ao_cruzar_breakpoint_libera_foco_e_rolagem(self):
        p = self.page
        self._estado(True)
        p.set_viewport_size({"width": 820, "height": 844})
        p.locator("#btn-menu-mobile").click()
        self._esperar_layout()
        expect(p.locator("#btn-menu-mobile")).to_have_attribute("aria-expanded", "true")
        self.assertTrue(p.evaluate("document.querySelector('.sidebar').contains(document.activeElement)"))
        # ResizeObserver/matchMedia precisam desfazer a modalidade, mesmo sem clique para fechar.
        p.set_viewport_size({"width": 821, "height": 844})
        self._esperar_layout()
        self.assertFalse(p.locator("body").evaluate("el => el.classList.contains('sem-rolagem')"))
        self.assertNotEqual(p.locator("body").evaluate("el => getComputedStyle(el).overflowY"), "hidden")
        pontos = p.get_by_role("navigation", name="Seções do Restaurante").get_by_role("link", name="Pontos", exact=True)
        pontos.focus()
        p.keyboard.press("Tab")
        self.assertTrue(p.evaluate("document.querySelector('#conteudo').contains(document.activeElement)"),
                        "Tab continua preso na antiga gaveta")
        p.set_viewport_size({"width": 820, "height": 844})
        self._esperar_layout()
        expect(p.locator("#btn-menu-mobile")).to_have_attribute("aria-expanded", "false")
        expect(p.locator(".sidebar")).to_be_hidden()
        p.locator("#btn-menu-mobile").click()
        self._esperar_layout()
        p.keyboard.press("Escape")
        self._esperar_layout()
        expect(p.locator(".sidebar")).to_be_hidden()
        expect(p.locator("#btn-menu-mobile")).to_be_focused()
        self.assertFalse(p.locator("body").evaluate("el => el.classList.contains('sem-rolagem')"))
        self._foto("gaveta-fechada")

    def test_historico_htmx_mantem_menu_conectado_e_controles_funcionais(self):
        p = self.page
        erros = []
        p.on("pageerror", lambda erro: erros.append(str(erro)))
        p.set_viewport_size({"width": 1280, "height": 640})
        # Simula a primeira visita depois do deploy: o histórico legado continha
        # body/APP, enquanto as preferências existentes precisam sobreviver.
        p.evaluate("""href => {
          const chave = document.querySelector('#menu-principal').dataset.rolagemChave;
          localStorage.removeItem(chave + ':historico');
          localStorage.setItem('htmx-history-cache', JSON.stringify([
            {url:href, content:'<div id="app">Menu da versão anterior</div>', title:'Legado', scroll:0}
          ]));
          localStorage.setItem('sidebar', 'aberta');
          localStorage.setItem('gov-filtro', 'limpar');
        }""", reverse("restaurante:comandas"))
        p.reload(wait_until="load")
        self._esperar_layout()
        self.assertIsNone(p.evaluate("localStorage.getItem('htmx-history-cache')"),
                          "a migração deixou o snapshot legado de body disponível")
        self.assertEqual(p.evaluate("localStorage.getItem('sidebar')"), "aberta")
        self.assertEqual(p.evaluate("localStorage.getItem('gov-filtro')"), "limpar")
        p.locator("#menu-principal").evaluate("""(nav, href) => {
          const item = nav.querySelector(`a[href="${href}"]`);
          nav.scrollTop += item.getBoundingClientRect().top-nav.getBoundingClientRect().top-45;
        }""", reverse("restaurante:comandas"))
        self._esperar_layout()
        antes = self._posicao_restaurante()
        self.assertGreater(antes["scroll"], 40)
        p.evaluate("""() => {
          window.__appSidebarOriginal = document.querySelector('#app');
          window.__sidebarHistoryReady = false;
          document.addEventListener('htmx:historyRestore', () => {
            window.__sidebarHistoryReady = true;
          }, {once:true});
        }""")
        p.locator(f'#menu-principal a[href="{reverse("loja:pdv")}"]').click()
        expect(p).to_have_url(self.url(reverse("loja:pdv")))
        self._esperar_layout()
        expect(p.locator("#menu-principal .nav-item.ativo")).to_have_attribute("href", reverse("loja:pdv"))
        p.go_back(wait_until="load")
        expect(p).to_have_url(self.url(reverse("restaurante:comandas")))
        p.wait_for_function("window.__sidebarHistoryReady === true")
        self._esperar_layout()
        self.assertEqual(erros, [], {"erros_de_pagina_apos_historico": erros})
        self.assertTrue(p.evaluate("window.__appSidebarOriginal === document.querySelector('#app')"),
                        "o histórico deve preservar a aplicação à qual os controles pertencem")
        expect(p.locator("#menu-principal .nav-item.ativo")).to_have_attribute("href", reverse("restaurante:comandas"))
        depois = self._posicao_restaurante()
        self.assertLessEqual(abs(depois["scroll"] - antes["scroll"]), 1, (antes, depois))
        self.assertLessEqual(abs(depois["y"] - antes["y"]), 1, (antes, depois))
        self._estado(True)
        self.assertTrue(p.locator("#app").evaluate("el => el.classList.contains('recolhida')"))
        self._estado(False)
        self.assertFalse(p.locator("#app").evaluate("el => el.classList.contains('recolhida')"))
        cache_novo = p.evaluate("localStorage.getItem('htmx-history-cache')")
        self.assertTrue(cache_novo, "a navegação precisa produzir snapshots do conteúdo novo")
        p.reload(wait_until="load")
        self._esperar_layout()
        self.assertEqual(p.evaluate("localStorage.getItem('htmx-history-cache')"), cache_novo,
                         "a migração voltou a apagar o histórico já compatível")
        self.assertEqual(p.evaluate("localStorage.getItem('sidebar')"), "aberta")
        self.assertEqual(p.evaluate("localStorage.getItem('gov-filtro')"), "limpar")
        p.set_viewport_size({"width": 390, "height": 844})
        p.locator("#btn-menu-mobile").click()
        self._esperar_layout()
        expect(p.locator(".sidebar")).to_be_visible()
        expect(p.locator("#btn-menu-mobile")).to_have_attribute("aria-expanded", "true")
        p.keyboard.press("Escape")
        self._esperar_layout()
        expect(p.locator(".sidebar")).to_be_hidden()
        expect(p.locator("#btn-menu-mobile")).to_be_focused()
        self.assertEqual(erros, [])
        self._foto("historico-htmx")
