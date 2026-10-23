"""Posição de estoque no navegador: leitura, filtros e ações em telas estreitas."""

import os
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    ModuloContratado,
    Produto,
    Usuario,
    registrar_entrada,
    registrar_saida,
)
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class EstoqueMobileE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        ModuloContratado.objects.update_or_create(codigo=Modulo.ESTOQUE, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(
            username="estoque-mobile-e2e", password="forte-123-abc")
        LocalEstoque.objects.update(ativo=False)
        self.local = LocalEstoque.objects.create(
            nome="Almoxarifado central de alimentos e materiais de reposição", modulo="nucleo")
        self.outro_local = LocalEstoque.objects.create(nome="Bar e restaurante", modulo="restaurante")
        self.local_vazio = LocalEstoque.objects.create(nome="Cozinha e café da manhã", modulo="restaurante")
        LocalEstoque.objects.create(nome="Governança e limpeza dos quartos", modulo="governanca")
        self.alimentos = CategoriaProduto.objects.create(nome="Alimentos e bebidas para o café da manhã")
        self.limpeza = CategoriaProduto.objects.create(nome="Limpeza e materiais de uso diário")
        self.grande = Produto.objects.create(
            nome="Arroz integral orgânico de grãos selecionados para refeições e eventos da pousada — embalagem econômica",
            categoria=self.alimentos, unidade=Produto.Unidade.KG,
            estoque_minimo=Decimal("10000.000"), codigo_barras="7890000000001")
        self.baixo = Produto.objects.create(
            nome="Café premium torrado e moído", categoria=self.alimentos,
            estoque_minimo=Decimal("10"), codigo_barras="7890000000002")
        self.zerado = Produto.objects.create(
            nome="Detergente neutro concentrado", categoria=self.limpeza,
            estoque_minimo=Decimal("3"))
        self.fora = Produto.objects.create(
            nome="Guardanapo de papel para o restaurante", categoria=self.limpeza,
            estoque_minimo=Decimal("5"))
        registrar_entrada(self.grande, self.local, Decimal("12345.678"), Decimal("1234.5678"), self.usuario)
        registrar_entrada(self.baixo, self.local, Decimal("5"), Decimal("12.50"), self.usuario)
        registrar_entrada(self.zerado, self.local, Decimal("2"), Decimal("4.50"), self.usuario)
        registrar_saida(self.zerado, self.local, Decimal("2"), self.usuario)
        registrar_entrada(self.fora, self.outro_local, Decimal("8"), Decimal("1.50"), self.usuario)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def abrir(self, **filtros):
        caminho = reverse("estoque:posicao")
        if filtros:
            caminho += "?" + urlencode(filtros)
        self.page.goto(self.url(caminho), wait_until="load")
        expect(self.page.get_by_role("heading", name="Posição de estoque", exact=True)).to_be_visible()
        self.esperar_layout()

    def esperar_layout(self):
        self.page.wait_for_load_state("load")
        # RAF fica suspenso no contexto sem JavaScript. A fonte e o layout real
        # bastam para estas medidas; a espera precisa ter um limite de falha.
        self.page.wait_for_function("document.fonts.status === 'loaded'", polling=100, timeout=10000)

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / f"estoque-{nome}.png"), full_page=True)

    def linha(self, produto):
        return self.page.locator(f'.est-posicao tr[data-produto-id="{produto.pk}"]')

    def selecionar(self, rotulo, valor):
        campo = self.page.get_by_label(rotulo, exact=True)
        if not campo.is_visible():
            campo.locator("xpath=ancestor::details[1]/summary").click()
        with self.page.expect_navigation(wait_until="load"):
            campo.select_option(str(valor))
        self.esperar_layout()

    def buscar(self, texto):
        self.page.get_by_label("Buscar produto", exact=True).fill(texto)
        with self.page.expect_navigation(wait_until="load"):
            self.page.get_by_role("button", name="Buscar", exact=True).click()
        self.esperar_layout()

    def conferir_parametros(self, **esperados):
        parametros = parse_qs(urlsplit(self.page.url).query)
        self.assertEqual(parametros, {chave: [str(valor)] for chave, valor in esperados.items()})

    def conferir_geometria(self, *, primeira_tela=False):
        medidas = self.page.locator(".est-posicao").evaluate("""painel => {
            const caixa = el => {const r=el.getBoundingClientRect(); return {
                left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
            const linhas = [...painel.querySelectorAll('[data-produto-id]')];
            return {largura:document.documentElement.clientWidth,
                documento:document.documentElement.scrollWidth,
                painel:caixa(painel),primeiro:caixa(linhas[0]),
                rolagens:[...painel.querySelectorAll('.tabela-rol,.est-tabela')].map(el => ({
                    largura:el.clientWidth,conteudo:el.scrollWidth})),
                linhas:linhas.map(el => ({caixa:caixa(el),
                    partes:[...el.children].map(caixa),
                    textos:[...el.querySelectorAll('.est-produto-nome,.est-produto-meta .rotulo-dado,.est-saldo,.selo')].flatMap(texto => {
                        const range=document.createRange();range.selectNodeContents(texto);
                        return [...range.getClientRects()].map(r => ({left:r.left,right:r.right}));
                    })}))};
        }""")
        self.assertLessEqual(medidas["documento"], medidas["largura"] + 1, medidas)
        self.assertGreaterEqual(medidas["painel"]["left"], -1, medidas)
        self.assertLessEqual(medidas["painel"]["right"], medidas["largura"] + 1, medidas)
        if primeira_tela:
            # Com quatro depósitos, o primeiro produto já começa no primeiro viewport.
            self.assertLess(medidas["primeiro"]["top"], 800, medidas)
        for rolagem in medidas["rolagens"]:
            self.assertLessEqual(rolagem["conteudo"], rolagem["largura"] + 1, rolagem)
        for linha in medidas["linhas"]:
            for parte in [*linha["partes"], *linha["textos"]]:
                self.assertGreaterEqual(parte["left"], linha["caixa"]["left"] - 1, linha)
                self.assertLessEqual(parte["right"], linha["caixa"]["right"] + 1, linha)
            for indice, primeira in enumerate(linha["partes"]):
                for segunda in linha["partes"][indice + 1:]:
                    x = min(primeira["right"], segunda["right"]) - max(primeira["left"], segunda["left"])
                    y = min(primeira["bottom"], segunda["bottom"]) - max(primeira["top"], segunda["top"])
                    self.assertFalse(x > 1 and y > 1, linha)
        for linha in self.page.locator(".est-posicao [data-produto-id]").all():
            # Só rola verticalmente: um alvo fora da lateral não ganha ajuda do Playwright.
            linha.evaluate("el => window.scrollTo(0,scrollY+el.getBoundingClientRect().top-90)")
            # afterSettle pode preceder o fim da transição visual do HTMX.
            # O ensaio espera o alvo ficar interativo, sem disparar navegação.
            for acao in linha.locator(".est-acoes a").all():
                acao.click(trial=True, timeout=5000)
            self.assertEqual(self.page.evaluate("window.scrollX"), 0)
            self.assertEqual(linha.evaluate("el => el.closest('.tabela-rol')?.scrollLeft || 0"), 0)
            acoes = linha.locator(".est-acoes a").evaluate_all("""els => els.map(el => {
                const r=el.getBoundingClientRect(), alvo=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                return {nome:el.getAttribute('aria-label') || el.textContent.trim(),
                    largura:r.width,altura:r.height,atingivel:el === alvo || el.contains(alvo),
                    alvo:alvo ? alvo.tagName + '.' + alvo.className : null};
            })""")
            self.assertEqual(len(acoes), 4)
            for acao in acoes:
                if self.page.viewport_size["width"] <= 1024:
                    self.assertGreaterEqual(acao["altura"], 43, acao)
                    self.assertGreaterEqual(acao["largura"], 43, acao)
                self.assertTrue(acao["atingivel"], acao)

    def test_produto_saldo_status_e_acoes_cabem_sem_rolagem_horizontal(self):
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                self.page.set_viewport_size({"width": largura, "height": 900})
                self.abrir()
                if largura > 820:
                    self.assertFalse(self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')"))
                    self.assertGreater(self.page.locator(".main").bounding_box()["x"], 200)
                expect(self.linha(self.grande).locator(".est-produto-nome")).to_have_text(self.grande.nome)
                expect(self.linha(self.grande).locator(".est-saldo")).to_have_text("12.345,678 kg")
                expect(self.linha(self.grande)).to_contain_text("R$ 15.241.576,53")
                expect(self.linha(self.baixo)).to_contain_text("Abaixo do mínimo")
                expect(self.linha(self.zerado)).to_contain_text("Sem saldo")
                self.conferir_geometria(primeira_tela=True)
                self.page.evaluate("window.scrollTo(0,0)")
                self.foto(str(largura))

    def test_busca_categoria_situacao_e_limpar_preservam_deposito(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.abrir()
        self.selecionar("Depósito", self.local.pk)
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(3)
        expect(self.linha(self.fora)).to_have_count(0)
        indicadores = self.page.locator(".est-posicao .kpi-valor").all_text_contents()
        self.buscar(self.baixo.codigo_barras)
        self.selecionar("Categoria", self.alimentos.pk)
        self.selecionar("Situação", "alerta")
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(1)
        expect(self.linha(self.baixo)).to_be_visible()
        self.conferir_parametros(local=self.local.pk, q=self.baixo.codigo_barras,
                                categoria=self.alimentos.pk, situacao="alerta")
        # Os números continuam descrevendo o depósito completo após filtrar a lista.
        self.assertEqual(self.page.locator(".est-posicao .kpi-valor").all_text_contents(), indicadores)
        self.selecionar("Depósito", self.outro_local.pk)
        self.conferir_parametros(local=self.outro_local.pk, q=self.baixo.codigo_barras,
                                categoria=self.alimentos.pk, situacao="alerta")
        expect(self.page.locator(".est-tabela .vazio")).to_contain_text("Nenhum produto com esses filtros.")
        self.page.get_by_role("link", name="Limpar", exact=True).click()
        self.esperar_layout()
        self.conferir_parametros(local=self.outro_local.pk)
        expect(self.linha(self.fora)).to_be_visible()
        self.selecionar("Depósito", self.local.pk)
        self.selecionar("Categoria", self.limpeza.pk)
        self.selecionar("Situação", "zerado")
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(1)
        expect(self.linha(self.zerado)).to_be_visible()
        self.buscar("produto inexistente fictício")
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(0)
        self.page.get_by_role("link", name="Ver todos", exact=True).click()
        self.esperar_layout()
        self.conferir_parametros(local=self.local.pk)
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(3)

    def test_acoes_abrem_produto_e_local_e_historico_tem_nome_legivel(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        for operacao, rotulo, campo_local in (
            ("entrada", f"Registrar entrada de {self.baixo.nome}", "local"),
            ("saida", f"Registrar saída de {self.baixo.nome}", "local"),
            ("transferencia", f"Transferir {self.baixo.nome}", "origem"),
        ):
            with self.subTest(operacao=operacao):
                self.abrir(local=self.local.pk)
                acao = self.linha(self.baixo).get_by_role("link", name=rotulo, exact=True)
                destino = urlsplit(acao.get_attribute("href"))
                self.assertEqual(destino.path, reverse(f"estoque:{operacao}"))
                self.assertEqual(parse_qs(destino.query), {
                    "produto": [str(self.baixo.pk)], "local": [str(self.local.pk)]})
                acao.click()
                expect(self.page.get_by_role("heading", name="Movimentar estoque", exact=True)).to_be_visible()
                self.esperar_layout()
                expect(self.page.locator('input[name="produto"]')).to_have_value(str(self.baixo.pk))
                expect(self.page.locator(f'input[name="{campo_local}"][value="{self.local.pk}"]')).to_be_checked()
                self.page.go_back(wait_until="load")
                expect(self.linha(self.baixo)).to_be_visible()
                self.esperar_layout()
                self.conferir_parametros(local=self.local.pk)
                self.conferir_geometria()
        self.linha(self.baixo).get_by_role("link", name="Movimentações", exact=True).click()
        self.esperar_layout()
        expect(self.page).to_have_title(f"Movimentações | {self.baixo.nome}")
        expect(self.page.get_by_role("heading", name=self.baixo.nome, exact=True)).to_be_visible()
        self.assertNotIn("Kardex", self.page.locator("#conteudo").inner_text())

    def test_catalogo_e_deposito_vazio_nao_confundem_produtos_fora_do_local(self):
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.abrir(local=self.local.pk)
        expect(self.linha(self.fora)).to_have_count(0)
        self.page.get_by_role("link", name="Ver o catálogo inteiro aqui", exact=True).click()
        self.esperar_layout()
        self.conferir_parametros(local=self.local.pk, catalogo=1)
        expect(self.linha(self.fora).locator(".est-saldo")).to_have_text("0 un")
        expect(self.page.locator(".est-nota-catalogo")).to_contain_text("produtos sem movimentação neste local")
        self.buscar("Guardanapo")
        self.conferir_parametros(local=self.local.pk, catalogo=1, q="Guardanapo")
        expect(self.linha(self.fora)).to_be_visible()
        self.page.get_by_role("link", name="Limpar", exact=True).click()
        self.esperar_layout()
        self.conferir_parametros(local=self.local.pk)
        expect(self.linha(self.fora)).to_have_count(0)
        self.selecionar("Depósito", self.local_vazio.pk)
        expect(self.page.locator(".est-tabela .vazio")).to_contain_text("Nenhum produto movimentado neste depósito ainda.")
        expect(self.page.locator(".est-posicao .est-acoes")).to_have_count(0)
        entrada = self.page.get_by_role("link", name="Registrar uma entrada", exact=True)
        self.assertEqual(entrada.get_attribute("href"), reverse("estoque:entrada") + f"?local={self.local_vazio.pk}")

    def test_entrada_pelo_menu_htmx_reconstroi_lista_sem_rolagem_horizontal(self):
        self.page.goto(self.url(reverse("dashboard")), wait_until="load")
        self.page.evaluate("""() => {
            window.estoqueEstavel=false;
            document.addEventListener('htmx:afterSettle', event => {
                if (event.target.id === 'conteudo') window.estoqueEstavel=true;
            });
        }""")
        self.page.locator(f'.sidebar a[href="{reverse("estoque:posicao")}"]').click()
        self.page.wait_for_function("window.estoqueEstavel === true")
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.esperar_layout()
        expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(4)
        self.conferir_geometria()

    def test_busca_filtros_e_limpar_funcionam_sem_javascript(self):
        original = self.page
        contexto = self._browser.new_context(
            java_script_enabled=False, reduced_motion="reduce", locale="pt-BR",
            viewport={"width": 390, "height": 900})
        contexto.add_cookies(original.context.cookies())
        self.page = contexto.new_page()
        try:
            self.abrir(local=self.local.pk)
            self.conferir_geometria(primeira_tela=True)
            self.page.locator(".est-filtros-avancados > summary").click()
            self.page.get_by_label("Categoria", exact=True).select_option(str(self.limpeza.pk))
            self.page.get_by_label("Situação", exact=True).select_option("zerado")
            self.page.get_by_role("button", name="Aplicar", exact=True).click()
            self.esperar_layout()
            self.conferir_parametros(local=self.local.pk, categoria=self.limpeza.pk, situacao="zerado")
            expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(1)
            expect(self.linha(self.zerado)).to_be_visible()
            self.buscar("produto inexistente fictício")
            expect(self.page.locator(".est-tabela .vazio")).to_contain_text("Nenhum produto com esses filtros.")
            self.page.get_by_role("link", name="Limpar", exact=True).click()
            self.esperar_layout()
            self.conferir_parametros(local=self.local.pk)
            expect(self.page.locator(".est-posicao [data-produto-id]")).to_have_count(3)
            self.foto("390-sem-javascript")
        finally:
            contexto.close()
            self.page = original
