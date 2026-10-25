"""Posição de estoque no navegador: leitura, filtros e ações em telas estreitas."""

import json
import os
import time
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

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
        # Sem JavaScript, o Chromium suspende tanto RAF quanto os timers usados
        # por wait_for_function. Consultar pelo processo de teste mantém a
        # exigência da fonte carregada, mesmo se ela chegar depois da 1ª leitura.
        limite = time.monotonic() + 10
        while self.page.evaluate("document.fonts.status") != "loaded":
            if time.monotonic() >= limite:
                self.fail("As fontes não carregaram em 10 segundos.")
            time.sleep(0.05)

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
            self.page.locator(".est-busca-linha").get_by_role("button", name="Buscar", exact=True).click()
        self.esperar_layout()

    def conferir_parametros(self, **esperados):
        esperados = {chave: [str(valor)] for chave, valor in esperados.items()}
        # Links internos atualizam a URL por HTMX: o documento já carregado
        # continua em "load" enquanto a resposta da navegação ainda chega.
        self.page.wait_for_url(
            lambda url: parse_qs(urlsplit(url).query) == esperados, timeout=10000)
        parametros = parse_qs(urlsplit(self.page.url).query)
        self.assertEqual(parametros, esperados)

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
            # Os destinos do módulo agora quebram em linhas para ficarem todos
            # visíveis. Conserva o espaço útil anterior para filtros/resumos,
            # descontando somente as linhas adicionais da navegação de 44px.
            abas = self.page.locator(".est-posicao .abas-secao").bounding_box()
            linhas_adicionais = max(0, abas["height"] - 44)
            self.assertLess(medidas["primeiro"]["top"] - linhas_adicionais, 800, medidas)
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
                self.foto(str(largura))
                self.conferir_geometria(primeira_tela=True)
                self.page.evaluate("window.scrollTo(0,0)")

    def test_indicadores_compactos_preservam_valores_e_fonte_ampliada(self):
        for largura in (320, 390, 821, 1440):
            self.page.set_viewport_size({"width": largura, "height": 900})
            self.abrir()
            for fonte in (16, 20):
                with self.subTest(largura=largura, fonte=fonte):
                    self.page.evaluate("v => document.documentElement.style.fontSize = `${v}px`", fonte)
                    indicadores = self.page.locator(".est-kpis .kpi").evaluate_all("""els => els.map(e => {
                        const r=e.getBoundingClientRect(), estilo=getComputedStyle(e);
                        return {left:r.left,right:r.right,width:r.width,
                            padding:[parseFloat(estilo.paddingLeft),parseFloat(estilo.paddingRight)],
                            textos:[...e.querySelectorAll('.kpi-rotulo,.kpi-valor,.kpi-nota')].flatMap(t=>{
                                const range=document.createRange();range.selectNodeContents(t);
                                return [...range.getClientRects()].map(b=>({texto:t.textContent,left:b.left,right:b.right}));
                            })};
                    })""")
                    self.assertEqual(len(indicadores), 4)
                    expect(self.page.locator(".est-kpis .kpi-valor").first).to_have_text("R$ 15.241.651,03")
                    for indicador in indicadores:
                        self.assertEqual(indicador["padding"], indicadores[0]["padding"])
                        for texto in indicador["textos"]:
                            self.assertGreaterEqual(texto["left"], indicador["left"] + indicador["padding"][0] - 1, texto)
                            self.assertLessEqual(texto["right"], indicador["right"] - indicador["padding"][1] + 1, texto)
                    if largura <= 390:
                        self.assertGreater(indicadores[0]["width"], indicadores[1]["width"] * 1.9)
                        self.assertAlmostEqual(indicadores[1]["width"], indicadores[2]["width"], delta=1)
                        self.assertAlmostEqual(indicadores[0]["width"], indicadores[3]["width"], delta=1)
                    self.foto(f"indicadores-{largura}-fonte{fonte}")

    def test_quinze_paginas_preservam_abas_antes_do_titulo_em_cinco_estados(self):
        from apps.nucleo.models import Fornecedor, Inventario, ItemInventario, Pessoa
        from apps.nucleo.notas_entrada import cadastrar_nota_entrada

        inventario = Inventario.objects.create(local=self.local, criado_por=self.usuario)
        ItemInventario.objects.create(
            inventario=inventario, produto=self.grande,
            saldo_sistema=Decimal("12345.678"), quantidade_contada=Decimal("12345.678"))
        fornecedor = Pessoa.objects.create(nome="Fornecedor sintético da conferência", tipo=Pessoa.Tipo.JURIDICA)
        Fornecedor.objects.create(pessoa=fornecedor)
        nota = cadastrar_nota_entrada(
            fornecedor=fornecedor, tipo="nfe", numero="90002", serie="1",
            emissao=timezone.localdate(), usuario=self.usuario, chave=uuid.uuid4(),
            observacao="Documento fictício exclusivo do teste de navegação.",
            itens=[{"produto": self.grande, "embalagem": None,
                    "fator_conferido": Decimal("1"), "quantidade": Decimal("5"),
                    "custo_unidade_compra": Decimal("8")}])
        # Uma rota GET canônica por cada um dos 15 templates com a navegação.
        # Novo/editar produto e as quatro movimentações compartilham templates;
        # ações POST, downloads e formulários de modal não são páginas de seção.
        paginas = (
            ("posicao", (), "posicao.html"),
            ("produtos", (), "produtos.html"),
            ("produto_editar", (self.grande.pk,), "produto_form.html"),
            ("produto_suprimentos", (self.grande.pk,), "produto_suprimentos.html"),
            ("entrada", (), "movimentar.html"),
            ("inventarios", (), "inventarios.html"),
            ("inventario", (inventario.pk,), "inventario.html"),
            ("kardex", (self.grande.pk,), "kardex.html"),
            ("cadastros", (), "cadastros.html"),
            ("compras", (), "compras.html"),
            ("lotes", (), "lotes.html"),
            ("notas", (), "notas_lista.html"),
            ("nota_nova", (), "nota_cadastro.html"),
            ("nota", (nota.pk,), "nota_detalhe.html"),
            ("nota_receber", (nota.pk,), "nota_receber.html"),
        )
        destinos = [reverse(f"estoque:{nome}") for nome in (
            "posicao", "produtos", "entrada", "inventarios", "notas", "compras", "lotes", "cadastros")]
        evidencias = []
        for largura, trilho in ((320, False), (390, False), (821, False), (1440, False), (1440, True)):
            eixo_y = None
            for nome, argumentos, template in paginas:
                with self.subTest(pagina=nome, largura=largura, trilho=trilho):
                    self.page.set_viewport_size({"width": largura, "height": 900})
                    caminho = reverse(f"estoque:{nome}", args=argumentos)
                    resposta = self.page.goto(self.url(caminho), wait_until="load")
                    self.assertEqual(resposta.status, 200)
                    self.assertEqual(urlsplit(self.page.url).path, caminho)
                    self.esperar_layout()
                    app = self.page.locator(".app")
                    if largura > 820 and app.evaluate("el => el.classList.contains('recolhida')") != trilho:
                        self.page.locator(".sidebar-toggle").click()
                    if largura > 820:
                        self.page.wait_for_function("""trilho => {
                            const app = document.querySelector('.app'), css = getComputedStyle(app);
                            const alvo = parseFloat(css.getPropertyValue(trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                            return app.classList.contains('recolhida') === trilho &&
                                Math.abs(parseFloat(css.gridTemplateColumns) - alvo) < .1 &&
                                Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width - alvo) < .1;
                        }""", arg=trilho)
                    self.page.evaluate("window.scrollTo(0,0)")
                    abas = self.page.get_by_role("navigation", name="Seções do Estoque", exact=True)
                    expect(abas).to_be_visible()
                    expect(abas.locator("a").first).to_have_text("Posição")
                    self.assertEqual(abas.locator("a").evaluate_all("els => els.map(el => el.getAttribute('href'))"), destinos)
                    medidas = abas.evaluate("""nav => {
                        const caixa = el => {const r=el.getBoundingClientRect(); return {
                            x:r.x, y:r.y+scrollY, right:r.right, bottom:r.bottom+scrollY,
                            width:r.width, height:r.height};};
                        const titulo = document.querySelector('#conteudo h1');
                        return {nav:caixa(nav), titulo:caixa(titulo),
                            antesDoTitulo:!!(nav.compareDocumentPosition(titulo) & Node.DOCUMENT_POSITION_FOLLOWING),
                            viewport:document.documentElement.clientWidth, documento:document.documentElement.scrollWidth,
                            excessoNav:nav.scrollWidth-nav.clientWidth,
                            foraDaLargura:[...document.querySelectorAll('#conteudo *')].filter(el =>
                                el.getBoundingClientRect().right > document.documentElement.clientWidth + 1
                            ).map(el => ({tag:el.tagName, classe:el.className, ...caixa(el)})).slice(0, 20),
                            links:[...nav.querySelectorAll('a')].map(el => ({...caixa(el),
                                texto:el.textContent.trim(), excesso:el.scrollWidth-el.clientWidth}))};
                    }""")
                    evidencias.append({"pagina": nome, "caminho": caminho, "template": template,
                                       "largura": largura, "trilho": trilho, **medidas})
                    if medidas["documento"] > medidas["viewport"] + 1:
                        self.foto(f"t63-overflow-{nome}-{largura}")
                    self.assertTrue(medidas["antesDoTitulo"], medidas)
                    self.assertLessEqual(medidas["nav"]["bottom"], medidas["titulo"]["y"] + 1, medidas)
                    if eixo_y is None:
                        eixo_y = medidas["nav"]["y"]
                    self.assertAlmostEqual(medidas["nav"]["y"], eixo_y, delta=1, msg=medidas)
                    self.assertLessEqual(medidas["documento"], medidas["viewport"] + 1, medidas)
                    self.assertLessEqual(medidas["excessoNav"], 1, medidas)
                    if nome == "kardex":
                        indicadores = self.page.locator(".est-kardex-kpis .kpi-valor")
                        expect(indicadores).to_have_text([
                            "12.345,678 kg", "R$ 1.234,57", "R$ 15.241.576,53", "R$ 0,00"])
                        medidas["indicadores"] = indicadores.evaluate_all("""els => els.map(el => {
                            const caixa=el.getBoundingClientRect(), range=document.createRange();
                            range.selectNodeContents(el);
                            return {texto:el.textContent.trim(), left:caixa.left, right:caixa.right,
                                fonte:parseFloat(getComputedStyle(el).fontSize),
                                partes:[...range.getClientRects()].map(r => ({left:r.left,right:r.right,y:r.y}))};
                        })""")
                        evidencias[-1]["indicadores"] = medidas["indicadores"]
                        # Moeda, dígitos, separadores e unidade conservam a mesma
                        # linha e a fonte de leitura; não basta esconder excesso.
                        for indicador in medidas["indicadores"]:
                            self.assertGreaterEqual(indicador["fonte"], 18, indicador)
                            ys = [parte["y"] for parte in indicador["partes"]]
                            self.assertLessEqual(max(ys) - min(ys), 1, indicador)
                            for parte in indicador["partes"]:
                                self.assertGreaterEqual(parte["left"], indicador["left"] - 1, indicador)
                                self.assertLessEqual(parte["right"], indicador["right"] + 1, indicador)
                    if nome in ("produtos", "inventario", "kardex"):
                        categorias = self.page.locator(
                            ".est-produto-meta .rotulo-dado, .est-kardex-meta .rotulo-dado"
                        ).filter(has_text=self.alimentos.nome)
                        self.assertGreater(categorias.count(), 0)
                        for categoria in categorias.all():
                            expect(categoria).to_have_text(self.alimentos.nome)
                            texto = categoria.evaluate("""el => {
                                const limite = el.closest('.est-produto-meta,.est-kardex-meta').getBoundingClientRect();
                                const range = document.createRange(); range.selectNodeContents(el);
                                return {left:limite.left, right:limite.right, partes:[...range.getClientRects()].map(
                                    r => ({left:r.left, right:r.right}))};
                            }""")
                            for parte in texto["partes"]:
                                self.assertGreaterEqual(parte["left"], texto["left"] - 1, texto)
                                self.assertLessEqual(parte["right"], texto["right"] + 1, texto)
                    for link, caixa in zip(abas.locator("a").all(), medidas["links"], strict=True):
                        self.assertGreaterEqual(caixa["x"], medidas["nav"]["x"] - 1, caixa)
                        self.assertLessEqual(caixa["right"], medidas["nav"]["right"] + 1, caixa)
                        self.assertGreaterEqual(caixa["height"], 44, caixa)
                        self.assertLessEqual(caixa["excesso"], 1, caixa)
                        # Ensaio real de ponteiro e foco: nenhum destino depende
                        # de rolagem lateral ou elemento coberto.
                        link.click(trial=True, timeout=5000)
                        link.focus()
                        expect(link).to_be_focused()
                        self.assertEqual(self.page.evaluate("window.scrollX"), 0)
                        self.assertEqual(abas.evaluate("el => el.scrollLeft"), 0)
                    if largura == 320 or nome == "posicao":
                        self.page.evaluate("window.scrollTo(0,0)")
                        self.foto(f"t63-{nome}-{largura}-{'trilho' if trilho else 'aberta'}")
        self.assertEqual(len(evidencias), 75)
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            Path(destino).mkdir(parents=True, exist_ok=True)
            (Path(destino) / "estoque-t63-15-paginas-5-estados.json").write_text(
                json.dumps(evidencias, ensure_ascii=False, indent=2), encoding="utf-8")

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
        self.clicar_item_menu(f'.sidebar a[href="{reverse("estoque:posicao")}"]')
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
            self.page.locator(".est-filtros-avancados").get_by_role("button", name="Buscar", exact=True).click()
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
