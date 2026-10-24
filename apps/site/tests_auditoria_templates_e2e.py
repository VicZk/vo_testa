"""Conferência dos templates com registros e operações reais no navegador."""
import json
import os
import re
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from .auditoria_fixtures import criar_cenario_templates
from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class AuditoriaTemplatesE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        self.c = criar_cenario_templates()
        self.client.force_login(self.c.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")
        self.erros_js = []
        self.page.on("pageerror", lambda erro: self.erros_js.append(str(erro)))
        self.evidencias = []

    def tearDown(self):
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino and self.evidencias:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{self._testMethodName}.json").write_text(
                json.dumps(self.evidencias, ensure_ascii=False, indent=2), encoding="utf-8")
        super().tearDown()

    def _abrir(self, rota, largura=1440, trilho=False, args=(), query=""):
        self.erros_js.clear()
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse(rota, args=args) + query), wait_until="load")
        self.assertEqual(resposta.status, 200, self.page.url)
        expect(self.page.locator("#conteudo")).to_be_visible()
        self.page.evaluate("document.fonts.ready")
        if largura > 820:
            recolhida = self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')")
            if recolhida != trilho:
                self.page.locator(".sidebar-toggle").click()
        self._esperar_layout()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        self.assertEqual(self.erros_js, [], (rota, largura, self.erros_js))

    def _esperar_layout(self):
        self.page.evaluate("""async () => {
            await document.fonts.ready;
            const app = document.querySelector('.app'), sidebar = document.querySelector('.sidebar');
            const animacoes = [...app.getAnimations(), ...sidebar.getAnimations({subtree: true})]
                .filter(a => Number.isFinite(a.effect?.getComputedTiming().endTime));
            await Promise.all(animacoes.map(a => a.finished.catch(() => {})));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")

    def _foto(self, nome, largura, trilho=False, pagina_inteira=True):
        destino = os.environ.get("EVIDENCIAS_DIR")
        nome = re.sub(r"[^a-z0-9_-]+", "-", nome.lower())
        arquivo = f"templates-{nome}-{largura}-{'trilho' if trilho else 'aberta'}.png"
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / arquivo), full_page=pagina_inteira)
        self.evidencias.append({
            "tela": nome, "largura": largura, "menu": "recolhido" if trilho else "aberto",
            "url": self.page.url.split(self.live_server_url)[-1], "imagem": arquivo,
            "overflow_documento": self.page.evaluate("document.documentElement.scrollWidth - innerWidth"),
            "erros_js": list(self.erros_js),
        })

    def _dentro(self, elemento, pai):
        # As duas caixas precisam pertencer ao mesmo instante: uma transição da
        # sidebar entre chamadas ao navegador misturava aberto e recolhido no CI.
        medidas = elemento.evaluate("""(el, pai) => {
            const medir = no => {
                if (!no || !no.getClientRects().length) return null;
                const {x, y, width, height} = no.getBoundingClientRect();
                return {x, y, width, height};
            };
            return {elemento: medir(el), pai: medir(pai)};
        }""", pai.element_handle())
        a, b = medidas["elemento"], medidas["pai"]
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertGreaterEqual(a["x"], b["x"] - 1, a)
        self.assertLessEqual(a["x"] + a["width"], b["x"] + b["width"] + 1, a)
        return a

    def _tabelas_preenchidas(self):
        tabelas = self.page.locator("#conteudo .tabela-cartoes")
        self.assertGreater(tabelas.count(), 0, self.page.url)
        linhas = tabelas.locator("tbody tr:has(td[data-rotulo])")
        self.assertGreater(linhas.count(), 0, self.page.url)
        medidas = tabelas.evaluate_all("""tabelas => tabelas.flatMap(t => [...t.querySelectorAll('tbody td[data-rotulo]')]
            .filter(e => e.getClientRects().length).map(e => {
                const r=e.getBoundingClientRect(), c=t.closest('.tabela-rol,.quadro') || t;
                const b=c.getBoundingClientRect(), v=e.querySelector('.tabela-valor');
                return {rotulo:e.dataset.rotulo, l:r.left,r:r.right,limiteL:b.left,limiteR:b.right,
                    scroll:e.scrollWidth-e.clientWidth,valor:v ? v.scrollWidth-v.clientWidth : 0,
                    display:getComputedStyle(e).display,antes:getComputedStyle(e,'::before').content};
            }))""")
        for medida in medidas:
            self.assertGreaterEqual(medida["l"], medida["limiteL"] - 1, medida)
            self.assertLessEqual(medida["r"], medida["limiteR"] + 1, medida)
            self.assertLessEqual(medida["scroll"], 1, medida)
            self.assertLessEqual(medida["valor"], 1, medida)
            if medida["display"] == "grid":
                self.assertNotIn(medida["antes"], ("none", "normal", '""'), medida)

    def test_listagens_com_registros_preservam_rotulos_valores_e_acoes(self):
        rotas = [
            ("estoque:produtos", ()), ("estoque:kardex", (self.c.produto.pk,)),
            ("estoque:inventarios", ()), ("estoque:cadastros", ()),
            ("loja:vendas", ()), ("loja:venda", (self.c.venda.pk,)),
            ("lavanderia:servicos", ()), ("lavanderia:rouparia", ()),
            ("lavanderia:historico", ()), ("caixa_sessoes", ()),
            ("caixa_sessao", (self.c.sessao.pk,)), ("auditoria:trilha", ()),
            ("auditoria:fechamentos", ()), ("estrutura", ()),
            ("reservas:restricoes", ()), ("daypass:painel", ()),
            ("nps:painel", ()), ("contas", ()), ("pessoas", ()),
            ("estoque:lotes", ()), ("estoque:produto_suprimentos", (self.c.produto.pk,)),
            ("comercial:email_campanhas", ()), ("comercial:email_templates", ()),
            ("pagamentos:conciliacao", ()),
        ]
        for rota, args in rotas:
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura, trilho, args)
                    self._foto(rota, largura, trilho)
                    self._tabelas_preenchidas()

    def test_formularios_e_fnrh_cabem_no_espaco_util(self):
        rotas = [
            ("pessoa_editar", (self.c.pessoa.pk,)),
            ("funcionario_editar", (self.c.funcionario.pk,)),
            ("uh_editar", (self.c.uh.pk,)),
            ("governanca:configuracao", ()),
            ("daypass:turno", (self.c.turno.pk,)),
            ("reservas:fnrh", (self.c.reserva.pk,)),
            ("comercial:email_campanha_nova", ()),
            ("estoque:compra_receber", ()),
        ]
        for rota, args in rotas:
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura, trilho, args)
                    elementos = self.page.locator('#conteudo input:not([type="hidden"]):visible, #conteudo select:visible, #conteudo textarea:visible')
                    self.assertGreater(elementos.count(), 0)
                    for campo in elementos.all():
                        self._dentro(campo, self.page.locator("#conteudo"))
                    if rota in ("governanca:configuracao", "daypass:turno"):
                        checkbox = self.page.locator('#conteudo input[type="checkbox"]').first
                        self.assertEqual(checkbox.locator("xpath=..").get_attribute("class"), "check-inline")
                    if rota == "reservas:fnrh":
                        titulo = self.page.locator(".fnrh-ficha-titulo").first
                        expect(titulo).to_have_text("Hóspede responsável")
                        self.assertLessEqual(titulo.evaluate("el => el.scrollWidth - el.clientWidth"), 1)
                        medidas = titulo.evaluate("""el => ({
                            altura: el.getBoundingClientRect().height,
                            linha: parseFloat(getComputedStyle(el).lineHeight)
                        })""")
                        self.assertLessEqual(medidas["altura"], medidas["linha"] * 3, medidas)
                    self._foto(rota, largura, trilho)

    def test_governanca_pdv_escala_e_marketing_preservam_contexto(self):
        for rota in ("dashboard", "governanca:quartos", "governanca:painel", "governanca:minha_fila", "loja:pdv",
                     "escala:grade", "marketing:calendario", "marketing:relatorio", "comercial:funil",
                     "manutencao:painel", "estoque:posicao"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura, trilho)
                    self._foto(rota, largura, trilho)
                    if rota == "dashboard":
                        porta = self.page.locator('.corredor .porta[data-dica*="Acomoda"]').first
                        expect(porta).to_be_visible()
                        porta.scroll_into_view_if_needed()
                        self.page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                        self.page.mouse.move(0, 0)
                        porta.hover()
                        dica = self.page.locator("#dica-flutuante")
                        expect(dica).to_be_visible()
                        expect(dica).to_contain_text(re.compile(r"Acomoda \d+ pessoas?"))
                        self.assertNotIn("- acomoda", dica.inner_text())
                        self._foto("dashboard-hover", largura, trilho, pagina_inteira=False)
                    elif rota == "governanca:quartos":
                        self._tabelas_preenchidas()
                        for botao in self.page.locator(".acoes-quarto button:visible").all():
                            medida = self._dentro(botao, botao.locator("xpath=ancestor::td"))
                            self.assertGreaterEqual(medida["height"], 44)
                    elif rota == "loja:pdv":
                        expect(self.page.locator('label[for="pdv-busca"]')).to_be_visible()
                        self.page.get_by_label("Buscar produto", exact=True).fill("Água mineral")
                        expect(self.page.locator(".pdv-produto:visible")).to_have_count(1)
                    elif rota == "marketing:relatorio":
                        expect(self.page.get_by_text("Nenhum gasto registrado nos meses exibidos.")).to_be_visible()
                        expect(self.page.locator(".mk-barras")).to_have_count(0)
                    elif rota == "escala:grade":
                        expect(self.page.locator(".escala-chip").first).to_be_visible()
                        self.assertEqual(self.page.locator(".escala-celula[data-dia]").count(), 7)

    def test_manutencao_com_estados_variados_e_mural_com_texto_longo(self):
        from apps.manutencao.models import OrdemServico
        from apps.nucleo.models import EntradaLogbook

        for estado, prioridade in zip(OrdemServico.Status.values, OrdemServico.Prioridade.values):
            OrdemServico.objects.create(
                titulo=f"Conferência {estado}: manutenção e vistoria da área externa",
                area="Área externa da pousada", status=estado, prioridade=prioridade,
                responsavel=self.c.usuario if estado != "cancelada" else None,
                criado_por=self.c.usuario)
        EntradaLogbook.objects.create(
            autor=self.c.usuario, importante=True,
            texto="Conferir os materiais de limpeza e avisar o próximo turno sobre a reposição dos quartos.")
        EntradaLogbook.objects.create(autor=self.c.usuario, texto="Conferência concluída.")
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self._abrir("manutencao:painel", largura, trilho, query="?situacao=todas")
                linhas = self.page.locator(".manutencao-ordem")
                expect(linhas).to_have_count(5)
                eixos = []
                for linha in linhas.all():
                    responsavel = linha.locator(".manutencao-ordem-responsavel")
                    eixos.append(self._dentro(responsavel, linha)["x"])
                    self._dentro(linha.locator(".manutencao-ordem-acao"), linha)
                self.assertLessEqual(max(eixos) - min(eixos), 1)
                self._foto("manutencao-estados-variados", largura, trilho)
                self._abrir("dashboard", largura, trilho)
                notas = self.page.locator(".mural-nota")
                self.assertGreaterEqual(notas.count(), 2)
                for nota in notas.all():
                    self._dentro(nota, self.page.locator(".mural"))
                    self._dentro(nota.locator(".mural-nota-txt"), nota)
                    alfinete = nota.evaluate("""e => {
                        const s = getComputedStyle(e, '::before');
                        return {top: parseFloat(s.top), left: parseFloat(s.left),
                            width: parseFloat(s.width), limite: e.clientWidth};
                    }""")
                    self.assertGreaterEqual(alfinete["top"], 1)
                    self.assertGreaterEqual(alfinete["left"], 1)
                    self.assertLessEqual(alfinete["left"] + alfinete["width"], alfinete["limite"])
                self._foto("mural-textos-variados", largura, trilho)

    def test_produto_com_virgula_salva_sem_perder_valor_e_previa_da_compra_confere(self):
        self._abrir("estoque:produto_editar", 390, args=(self.c.produto.pk,))
        self.page.locator('[name="preco_venda"]').fill("19,95")
        self.page.locator('[name="estoque_minimo"]').fill("5,125")
        self.page.get_by_role("button", name="Salvar produto", exact=True).click()
        expect(self.page.locator("#conteudo h1")).to_have_text("Produtos")
        self.c.produto.refresh_from_db()
        self.assertEqual(self.c.produto.preco_venda, Decimal("19.95"))
        self.assertEqual(self.c.produto.estoque_minimo, Decimal("5.125"))
        self._abrir("estoque:compra_receber", 390)
        self.page.locator('[name="embalagem"]').select_option(str(self.c.embalagem.pk))
        self.page.locator('[name="quantidade"]').fill("1,5")
        self.page.locator('[name="custo_embalagem"]').fill("2,3456")
        expect(self.page.locator("#compra-quantidade")).to_contain_text("18 un")
        expect(self.page.locator("#compra-total")).to_contain_text("3,52")
        self._foto("compra-decimais", 390)

    def test_reserva_pagina_e_modal_cadastram_hospede_no_formulario_correto(self):
        from apps.nucleo.models import Pessoa
        self._abrir("reservas:nova", 390, query=f"?uh={self.c.uh2.pk}&checkin=2030-05-10&checkout=2030-05-12")
        formulario = self.page.locator("#conteudo form.form-cartao")
        expect(formulario.locator("#tarifa-hint")).not_to_be_empty()
        formulario.get_by_role("button", name="+ Novo", exact=True).click()
        formulario.locator("#nh-nome").fill("Hóspede da página de conferência")
        formulario.get_by_role("button", name="Salvar hóspede", exact=True).click()
        expect(formulario.locator('[name="hospede"]')).not_to_have_value("")
        pessoa_pagina = Pessoa.objects.get(nome="Hóspede da página de conferência")
        expect(formulario.locator('[name="hospede"]')).to_have_value(str(pessoa_pagina.pk))
        self._foto("reserva-pagina-hospede", 390)
        # A abertura oficial via HTMX pode coexistir com a página completa.
        self.page.evaluate("""url => htmx.ajax('GET', url, {target:'#modal-conteudo', swap:'innerHTML'})""", reverse("reservas:nova"))
        modal = self.page.locator("#modal-conteudo form")
        expect(modal).to_be_visible()
        modal.get_by_role("button", name="+ Novo", exact=True).click()
        modal.locator("#nh-nome").fill("Hóspede do modal de conferência")
        modal.get_by_role("button", name="Salvar hóspede", exact=True).click()
        expect(modal.locator('[name="hospede"]')).not_to_have_value("")
        pessoa_modal = Pessoa.objects.get(nome="Hóspede do modal de conferência")
        expect(modal.locator('[name="hospede"]')).to_have_value(str(pessoa_modal.pk))
        expect(formulario.locator('[name="hospede"]')).to_have_value(str(pessoa_pagina.pk))
        self._foto("reserva-modal-sobre-pagina", 390)

    def test_primeira_pintura_e_preco_final_mantem_geometria_e_salvam(self):
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self.page.route("**/js/reserva-acoes.js", lambda rota: rota.abort())
                self._abrir("reservas:detalhe", largura, trilho, (self.c.reserva.pk,))
                regioes = self.page.locator("[data-reserva-acoes] .acao-painel")
                self.assertGreater(regioes.count(), 0)
                for painel in regioes.all():
                    expect(painel).to_be_hidden()
                self._foto("reserva-antes-script", largura, trilho)
                self.page.unroute("**/js/reserva-acoes.js")
                self._abrir("reservas:detalhe", largura, trilho, (self.c.reserva.pk,))
                expect(self.page.locator("[data-reserva-acoes]")).to_have_attribute("data-reserva-pronta", "1")
                botao = self.page.locator('[data-acao="sinal"]')
                grupo = botao.locator("xpath=ancestor::details")
                if grupo.count():
                    grupo.locator("summary").click()
                botao.click()
                expect(self.page.locator("#acao-sinal")).to_be_visible()
                self.page.locator("#acao-sinal [data-fechar-acao]").click()
                expect(self.page.locator("#acao-sinal")).to_be_hidden()
                self.page.route("**/js/tabela-precos.js", lambda rota: rota.abort())
                self._abrir("tabela_precos", largura, trilho)
                filtros = self.page.locator("[data-precos-filtros]")
                inicial = filtros.evaluate("el => ({height: el.getBoundingClientRect().height})")
                self.assertGreater(inicial["height"], 0)
                self.assertEqual(filtros.evaluate("el => getComputedStyle(el).visibility"), "hidden")
                self.page.unroute("**/js/tabela-precos.js")
                self._abrir("tabela_precos", largura, trilho)
                expect(filtros).to_be_visible()
                self.assertAlmostEqual(filtros.bounding_box()["height"], inicial["height"], delta=1)
                self._foto("tabela-precos", largura, trilho)
        campo = self.page.locator(f'input[name="base_{self.c.uh.pk}_baixa"]').first
        if not campo.count():
            campo = self.page.locator('.precos-tabela input[name^="base_"]').first
        campo.fill("389,90")
        self.page.locator('.precos-form > .acoes button[type="submit"]').click()
        expect(self.page.locator('[data-estado-edicao]')).to_have_text("Nenhuma alteração pendente")
        from apps.reservas.models import TarifaUnidade
        self.assertEqual(TarifaUnidade.objects.get(uh=self.c.uh, classificacao="baixa").valor, Decimal("389.90"))
        self.assertEqual(self.erros_js, [])
