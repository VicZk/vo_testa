"""Navegação entre os módulos sem perder controles, foco ou inicializadores."""

import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    ConfiguracaoReservas,
    FormaPagamento,
    Hospede,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    TipoUH,
    Usuario,
    registrar_entrada,
)
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class NavegacaoModulosE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        from apps.comercial.models import EtapaFunil
        from apps.governanca.models import StatusLimpeza

        cache.clear()
        self.usuario = Usuario.objects.create_superuser(
            username="navegacao-modulos", password="forte-123-abc")
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={"feriados_automaticos": False})
        self.forma, _ = FormaPagamento.objects.get_or_create(nome="Dinheiro navegação", defaults={"tipo": "dinheiro"})
        EtapaFunil.objects.get_or_create(nome="Atendimento navegação")
        tipo = TipoUH.objects.create(nome="Suíte Navegação", tarifa_base=Decimal("300.00"))
        self.quarto_sujo = UH.objects.create(numero="N01", tipo=tipo)
        self.quarto_pronto = UH.objects.create(numero="N02", tipo=tipo)
        StatusLimpeza.objects.update_or_create(
            uh=self.quarto_sujo, defaults={"situacao": StatusLimpeza.Situacao.SUJA})
        StatusLimpeza.objects.update_or_create(
            uh=self.quarto_pronto, defaults={"situacao": StatusLimpeza.Situacao.INSPECIONADA})
        pessoa = Pessoa.objects.create(nome="Hóspede navegação fictício")
        Hospede.objects.create(pessoa=pessoa)
        self.local = LocalEstoque.objects.create(nome="Loja navegação", modulo="loja")
        self.produto = Produto.objects.create(
            nome="Água navegação", categoria=CategoriaProduto.objects.create(nome="Bebidas navegação"),
            preco_venda=Decimal("7.00"))
        registrar_entrada(self.produto, self.local, Decimal("20.00"), Decimal("2.00"), self.usuario)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.erros = []
        self.page.on("pageerror", lambda erro: self.erros.append(str(erro)))

    def iniciar(self, rota="dashboard"):
        resposta = self.page.goto(self.url(reverse(rota)), wait_until="load")
        expect(self.page.locator("#conteudo")).to_be_visible()
        self.page.evaluate("""() => {
          window.__navReferencias = {
            app:document.querySelector('#app'), menu:document.querySelector('#menu-principal'),
            sidebar:document.querySelector('.sidebar')};
          window.__navTrocas = [];
          document.addEventListener('htmx:afterSwap', ev => {
            if (ev.detail.target.id === 'conteudo') window.__navTrocas.push(location.pathname);
          });
        }""")
        return resposta

    def menu(self):
        return self.page.locator("#menu-principal a.nav-item[href]")

    def abrir_menu(self):
        if self.page.viewport_size["width"] <= 820:
            self.page.locator("#btn-menu-mobile").click()
            expect(self.page.locator("#btn-menu-mobile")).to_have_attribute("aria-expanded", "true")

    def navegar(self, href):
        self.abrir_menu()
        antes = self.page.evaluate("window.__navTrocas.length")
        with self.page.expect_response(
            lambda resposta: urlparse(resposta.url).path == href
            and resposta.request.headers.get("hx-request") == "true"
        ) as recebida:
            self.clicar_item_menu(f'#menu-principal a.nav-item[href="{href}"]')
        self.assertLess(recebida.value.status, 400, (href, recebida.value.status))
        expect(self.page).to_have_url(self.url(href))
        self.page.wait_for_function("!document.querySelector('.htmx-request')")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        self.assertEqual(self.page.evaluate("window.__navTrocas.length"), antes + 1, href)
        return self.conferir_estrutura(href)

    def conferir_estrutura(self, href):
        expect(self.page.locator("#app")).to_have_count(1)
        expect(self.page.locator("#conteudo")).to_have_count(1)
        expect(self.page.locator("#menu-principal .nav-item.ativo")).to_have_count(1)
        expect(self.page.locator("#menu-principal .nav-item.ativo")).to_have_attribute("href", href)
        self.assertTrue(self.page.evaluate("""() => {
          const refs=window.__navReferencias;
          return refs.app===document.querySelector('#app') && refs.menu===document.querySelector('#menu-principal')
            && refs.sidebar===document.querySelector('.sidebar');
        }"""), href)
        self.assertGreater(len(self.page.locator("#conteudo").inner_text().strip()), 15, href)
        self.assertFalse(self.page.locator("body").evaluate("el => el.classList.contains('sem-rolagem')"), href)
        if self.page.viewport_size["width"] <= 820:
            expect(self.page.locator("#btn-menu-mobile")).to_have_attribute("aria-expanded", "false")
            self.assertFalse(self.page.evaluate("document.querySelector('.sidebar').contains(document.activeElement)"), href)
        abas = self.page.locator("#conteudo .abas-secao").evaluate_all("""els => els.map(el => ({
          direita:el.getBoundingClientRect().right, largura:el.clientWidth,
          rolagem:el.scrollWidth, overflow:getComputedStyle(el).overflowX,
          itens:Array.from(el.children).filter(f => f.getClientRects().length).map(f => {
            const r=f.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
              altura:r.height,alvo:f.matches('a,button')};
          })
        }))""")
        for aba in abas:
            self.assertLessEqual(aba["direita"], self.page.viewport_size["width"] + 1, (href, aba))
            for i, item in enumerate(aba["itens"]):
                if item["alvo"]:
                    self.assertGreaterEqual(item["altura"], 44, (href, aba))
                for outro in aba["itens"][i + 1:]:
                    self.assertTrue(item["right"] <= outro["left"] + 1 or
                                    outro["right"] <= item["left"] + 1 or
                                    item["bottom"] <= outro["top"] + 1 or
                                    outro["bottom"] <= item["top"] + 1, (href, aba))
            if aba["rolagem"] > aba["largura"] + 1:
                self.assertIn(aba["overflow"], ("auto", "scroll"), (href, aba))
        return abas

    def registrar(self, nome, dados):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / nome).write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")

    def conferir_busca_e_modal(self):
        self.page.locator(".busca-global").click()
        expect(self.page.get_by_role("dialog", name="Buscar na pousada")).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_role("dialog", name="Buscar na pousada")).to_be_hidden()
        expect(self.page.locator(".busca-global")).to_be_focused()
        self.abrir_menu()
        with self.page.expect_response(lambda r: urlparse(r.url).path == reverse("reservas:nova")):
            self.page.locator(".sidebar .acao-topo").click()
        expect(self.page.locator("#modal-conteudo")).to_be_visible()
        expect(self.page.locator('#modal-conteudo [name="hospede"]')).to_have_count(1)
        combo = self.page.get_by_role("combobox", name="Hóspede", exact=True)
        combo.press("ArrowDown")
        expect(combo).to_have_attribute("aria-expanded", "true")
        self.page.keyboard.press("Escape")
        expect(combo).to_have_attribute("aria-expanded", "false")
        expect(self.page.locator("#modal-reserva")).to_be_visible()
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#modal-reserva")).to_be_hidden()
        if self.page.viewport_size["width"] <= 820:
            self.page.keyboard.press("Escape")
        self.assertFalse(self.page.locator("body").evaluate("el => el.classList.contains('sem-rolagem')"))

    def varrer(self, largura):
        self.page.set_viewport_size({"width": largura, "height": 900})
        self.page.emulate_media(reduced_motion="no-preference" if largura > 820 else "reduce")
        resposta = self.iniciar()
        itens = self.menu().evaluate_all("els => els.map(el => ({nome:el.textContent.trim(), href:el.getAttribute('href')}))")
        self.assertGreaterEqual(len(itens), 35)
        resultados = []
        try:
            for passagem, ordem in enumerate((itens, list(reversed(itens))), start=1):
                for item in ordem:
                    with self.subTest(largura=largura, passagem=passagem, destino=item["nome"]):
                        inicio = len(self.erros)
                        abas = self.navegar(item["href"])
                        resultados.append({**item, "passagem": passagem, "abas": abas, "erros": self.erros[inicio:]})
                self.conferir_busca_e_modal()
        finally:
            self.registrar(f"navegacao-{largura}.json", {
                "csp_report_only": "content-security-policy-report-only" in resposta.headers,
                "destinos": resultados, "erros": self.erros,
            })
        self.assertEqual(self.erros, [])

    def test_todos_os_menus_repetidos_no_desktop(self):
        self.varrer(1440)

    def test_todos_os_menus_repetidos_no_celular(self):
        self.varrer(390)

    def test_alpine_filtros_e_carrinho_reagem_apos_historico(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        etapas = []
        self.iniciar("governanca:quartos")
        etapas.append({"etapa": "entrada_governanca", "erros": list(self.erros)})
        filtro = self.page.get_by_label("Situação dos quartos", exact=True)
        filtro.select_option("suja")
        expect(self.page.locator(f"#quarto-{self.quarto_sujo.pk}")).to_be_visible()
        expect(self.page.locator(f"#quarto-{self.quarto_pronto.pk}")).to_be_hidden()
        self.navegar(reverse("loja:pdv"))
        etapas.append({"etapa": "loja_htmx", "erros": list(self.erros)})
        expect(self.page.get_by_role("button", name=f"Adicionar {self.produto.nome} ao carrinho", exact=True)).to_be_visible()
        self.page.go_back()
        expect(self.page).to_have_url(self.url(reverse("governanca:quartos")))
        expect(filtro).to_have_value("suja")
        expect(self.page.locator(f"#quarto-{self.quarto_pronto.pk}")).to_be_hidden()
        filtro.select_option("todas")
        expect(self.page.locator(f"#quarto-{self.quarto_pronto.pk}")).to_be_visible()
        etapas.append({"etapa": "volta_governanca", "erros": list(self.erros)})
        with self.page.expect_response(lambda r: urlparse(r.url).path == reverse("loja:pdv")
                                       and r.request.headers.get("hx-history-restore-request") == "true"):
            self.page.go_forward()
        expect(self.page).to_have_url(self.url(reverse("loja:pdv")))
        self.page.wait_for_function("document.querySelector('.pdv-shell')._x_dataStack")
        self.page.evaluate("() => new Promise(resolve => setTimeout(resolve, 50))")
        etapas.append({"etapa": "restaura_loja", "erros": list(self.erros)})
        produto = self.page.get_by_role("button", name=f"Adicionar {self.produto.nome} ao carrinho", exact=True)
        expect(produto).to_have_count(1)
        produto.click()
        self.page.locator(".pdv-etapas button").filter(has_text="Carrinho").click()
        expect(self.page.get_by_role("button", name=f"Aumentar {self.produto.nome}", exact=True)).to_be_visible()
        self.page.get_by_role("button", name=f"Aumentar {self.produto.nome}", exact=True).click()
        expect(self.page.locator(".pdv-contador")).to_have_text("2 itens")
        self.page.get_by_role("button", name=f"Remover {self.produto.nome}", exact=True).click()
        expect(self.page.locator(".pdv-vazio")).to_be_visible()
        etapas.append({"etapa": "carrinho_reage", "erros": list(self.erros)})
        self.registrar("navegacao-alpine-historico.json", etapas)
        self.assertEqual(self.produto.saldo(self.local), Decimal("20.00"))
        self.assertEqual(self.erros, [])

    def test_carrinho_preservado_ao_cancelar_saida_ou_falhar_venda(self):
        self.iniciar()
        self.navegar(reverse("loja:pdv"))
        self.page.get_by_role("button", name=f"Adicionar {self.produto.nome} ao carrinho", exact=True).click()
        expect(self.page.locator(".pdv-shell")).to_have_attribute("data-dirty", "1")
        avisos = []

        def cancelar(dialogo):
            avisos.append(dialogo.message)
            dialogo.dismiss()

        self.page.once("dialog", cancelar)
        self.clicar_item_menu(f'#menu-principal a[href="{reverse("dashboard")}"]')
        expect(self.page).to_have_url(self.url(reverse("loja:pdv")))
        expect(self.page.locator(".pdv-contador")).to_have_text("1 item")
        self.assertEqual(len(avisos), 1)
        self.assertIn("Há itens no carrinho", avisos[0])

        self.page.once("dialog", cancelar)
        with self.page.expect_event("dialog"):
            self.page.evaluate("history.back()")
        expect(self.page.locator(".pdv-contador")).to_have_text("1 item")
        self.page.wait_for_function("location.pathname.endsWith('/loja/')")
        self.assertEqual(len(avisos), 2)

        self.page.get_by_label("Forma de pagamento", exact=True).select_option(str(self.forma.pk))
        with self.page.expect_response(lambda r: urlparse(r.url).path == reverse("loja:finalizar")) as resposta:
            self.page.locator(".pdv-finalizar").click()
        self.assertEqual(resposta.value.status, 400)
        expect(self.page.locator(".pdv-finalizar")).to_be_enabled()
        expect(self.page.locator(".pdv-shell")).to_have_attribute("data-dirty", "1")
        expect(self.page.locator(".pdv-contador")).to_have_text("1 item")
        self.assertEqual(self.produto.saldo(self.local), Decimal("20.00"))

        self.page.once("dialog", lambda d: d.accept())
        self.navegar(reverse("dashboard"))
        self.assertEqual(self.erros, [])

    def test_carrinho_protegido_no_historico_sem_navigation_api(self):
        self.page.add_init_script("Object.defineProperty(window, 'navigation', {value: undefined})")
        self.iniciar()
        with self.page.expect_navigation(wait_until="load"):
            self.clicar_item_menu("#menu-principal [data-pdv-entrada]")
        expect(self.page).to_have_url(self.url(reverse("loja:pdv")))
        self.assertTrue(self.page.evaluate("typeof window.__navReferencias === 'undefined'"))
        self.page.get_by_role("button", name=f"Adicionar {self.produto.nome} ao carrinho", exact=True).click()
        expect(self.page.locator(".pdv-shell")).to_have_attribute("data-dirty", "1")
        avisos = []

        def cancelar(dialogo):
            avisos.append(dialogo.type)
            dialogo.dismiss()

        self.page.once("dialog", cancelar)
        with self.page.expect_event("dialog"):
            self.page.evaluate("history.back()")
        expect(self.page).to_have_url(self.url(reverse("loja:pdv")))
        expect(self.page.locator(".pdv-contador")).to_have_text("1 item")
        self.assertEqual(avisos, ["beforeunload"])
        self.assertEqual(self.erros, [])
