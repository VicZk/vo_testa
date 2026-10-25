"""Regressões confirmadas na retomada da revisão de interface de outubro."""
import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import MovimentoCaixa, TrilhaAuditoria
from apps.pagamentos.models import Cobranca
from apps.reservas.models import ContaHospedagem, Reserva

from .auditoria_fixtures import criar_cenario_templates
from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class RetomadaFrontE2ETests(_BaseE2E):
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
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")

    def abrir(self, rota, largura, trilho=False, args=()):
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse(rota, args=args)))
        self.assertEqual(resposta.status, 200, rota)
        self.page.evaluate("document.fonts.ready")
        if largura > 820:
            app = self.page.locator(".app")
            if app.evaluate("e => e.classList.contains('recolhida')") != trilho:
                self.page.locator(".sidebar-toggle").click()
        self.page.evaluate("""async () => {
            const elementos = [document.querySelector('.app'), document.querySelector('.sidebar')];
            await Promise.all(elementos.flatMap(e => e.getAnimations({subtree:true}))
                .filter(a => Number.isFinite(a.effect?.getComputedTiming().endTime))
                .map(a => a.finished.catch(() => {})));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True)

    def test_selects_preservam_seta_e_espaco_para_a_opcao_em_cinco_estados(self):
        rotas = (("reservas:fnrh", (self.c.reserva.pk,)), ("caixa", ()),
                 ("tabela_precos", ()), ("estoque:compra_receber", ()))
        for rota, args in rotas:
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho, args)
                    medidas = self.page.locator("#conteudo select:visible").evaluate_all("""campos => campos
                        .filter(e => !e.multiple).map(e => {
                            const s=getComputedStyle(e);
                            return {id:e.id, seta:s.backgroundImage, recuo:parseFloat(s.paddingRight)};
                        })""")
                    self.assertTrue(medidas, rota)
                    for medida in medidas:
                        self.assertNotEqual(medida["seta"], "none", medida)
                        self.assertGreaterEqual(medida["recuo"], 28, medida)

    def test_previa_da_compra_aparece_calcula_e_some_ao_limpar_a_embalagem(self):
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self.abrir("estoque:compra_receber", largura, trilho)
                previa = self.page.locator("#compra-previa")
                expect(previa).to_be_hidden()
                self.page.locator("#id_embalagem").select_option(str(self.c.embalagem.pk))
                self.page.locator("#id_quantidade").fill("3")
                self.page.locator("#id_custo_embalagem").fill("27,90")
                expect(previa).to_be_visible()
                expect(self.page.locator("#compra-quantidade")).to_contain_text("36")
                expect(self.page.locator("#compra-total")).to_contain_text("83,70")
                self.page.locator("#id_embalagem").select_option("")
                expect(previa).to_be_hidden()

    def test_quarto_com_saida_hoje_mantem_o_saldo_inteiro_ao_lado_do_aviso(self):
        reserva = self.c.reserva
        reserva.status = Reserva.Status.HOSPEDADA
        reserva.checkin = self.c.hoje - timedelta(days=1)
        reserva.checkout = self.c.hoje
        reserva.valor_diaria = "2649.50"
        reserva.save()
        reserva.refresh_from_db()
        conta = ContaHospedagem.objects.create(reserva=reserva)
        conta.lancar_diarias(self.c.usuario)
        for rota in ("dashboard", "reservas:mapa_quartos"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho)
                    saldo = self.page.locator(".porta-saldo").first
                    expect(saldo).to_be_visible()
                    expect(saldo).to_contain_text("2.650")
                    expect(saldo.locator("..").locator(".porta-flag")).to_contain_text("saída hoje")
                    medida = saldo.evaluate("""e => {
                        const r=e.getBoundingClientRect(), p=e.closest('.porta-rodape').getBoundingClientRect();
                        return {excesso:e.scrollWidth-e.clientWidth, esquerda:r.left-p.left,
                                direita:r.right-p.right, baixo:r.bottom-p.bottom};
                    }""")
                    self.assertLessEqual(medida["excesso"], 1, medida)
                    self.assertGreaterEqual(medida["esquerda"], -1, medida)
                    self.assertLessEqual(medida["direita"], 1, medida)
                    self.assertLessEqual(medida["baixo"], 1, medida)
                    if largura in (320, 1440):
                        self.foto(f"retomada-saldo-{rota.replace(':', '-')}-{largura}-{trilho}")

    def test_filtros_crescem_e_datas_preservam_o_ano(self):
        for largura, trilho in self.ESTADOS:
            for rota in ("estoque:compras", "estoque:lotes", "estoque:notas", "manutencao:painel",
                         "pagamentos:conciliacao"):
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho)
                    if rota == "manutencao:painel":
                        expect(self.page.locator(".manutencao-filtros")).to_have_css("display", "grid")
                    if rota == "pagamentos:conciliacao":
                        for campo in self.page.locator('.filtro-periodo input[type="date"]').all():
                            self.assertGreaterEqual(campo.bounding_box()["width"], 136)
                            self.assertTrue(campo.input_value())
                    if largura == 1440 and rota in ("estoque:compras", "estoque:lotes", "estoque:notas"):
                        campos = self.page.locator('form.filtros > .campo input, form.filtros > .campo select')
                        self.assertGreater(campos.count(), 0)
                        for campo in campos.all():
                            self.assertGreater(campo.bounding_box()["width"], 220)
                        alturas = self.page.locator('form.filtros :is(button, a.botao-neutro)').evaluate_all(
                            "es => es.map(e => e.getBoundingClientRect().height)")
                        self.assertTrue(all(altura >= 44 for altura in alturas), alturas)
                    if largura in (390, 1440):
                        self.foto(f"retomada-filtro-{rota.replace(':', '-')}-{largura}-{trilho}")

    def test_colunas_e_ciclo_da_limpeza_usam_a_largura_do_conteudo(self):
        for largura in (821, 1024):
            self.abrir("comercial:oportunidade", largura, args=(self.c.oportunidade.pk,))
            colunas = self.page.locator(".op-layout").evaluate("e => getComputedStyle(e).gridTemplateColumns")
            self.assertEqual(len(colunas.split()), 1, colunas)
        self.abrir("governanca:quartos", 821)
        setas = self.page.locator(".gov-ciclo-seta")
        self.assertGreater(setas.count(), 0)
        for seta in setas.all():
            expect(seta).to_be_hidden()
        self.abrir("reservas:detalhe", 821, args=(self.c.reserva.pk,))
        colunas = self.page.locator(".painel-financeiro .kpi-grade").evaluate(
            "e => getComputedStyle(e).gridTemplateColumns")
        self.assertEqual(len(colunas.split()), 2, colunas)
        self.foto("retomada-financeiro-821")

    def test_abas_preservam_largura_dos_rotulos_e_indicadores_nao_partem_dinheiro(self):
        for largura, trilho in self.ESTADOS:
            self.abrir("pessoas", largura, trilho)
            abas = self.page.locator(".abas-secao .est-aba")
            self.assertGreater(abas.count(), 0)
            for aba in abas.all():
                medida = aba.evaluate("""e => ({cresce:getComputedStyle(e).flexGrow,
                    excesso:e.scrollWidth-e.clientWidth, altura:e.getBoundingClientRect().height})""")
                self.assertEqual(medida["cresce"], "0", medida)
                self.assertLessEqual(medida["excesso"], 1, medida)
                self.assertGreaterEqual(medida["altura"], 44, medida)
            self.abrir("relatorios:relatorio", largura, trilho, args=("distribuicao",))
            indicadores = self.page.locator(".cartoes-indicadores").first
            if largura <= 390:
                colunas = indicadores.evaluate("e => getComputedStyle(e).gridTemplateColumns")
                self.assertEqual(len(colunas.split()), 2, colunas)
            # Reproduz o valor monetário que quebrava entre o prefixo e os algarismos.
            valor = indicadores.locator(".indicador-valor").first
            valor.evaluate("e => { e.textContent='R$ 61.310,00'; }")
            medida = valor.evaluate("""e => {
                const r=document.createRange(); r.selectNodeContents(e);
                return {linhas:r.getClientRects().length, excesso:e.scrollWidth-e.clientWidth};
            }""")
            self.assertEqual(medida["linhas"], 1, medida)
            self.assertLessEqual(medida["excesso"], 1, medida)
            self.foto(f"retomada-indicadores-{largura}-{trilho}")

    def test_caixas_de_marcacao_e_campos_url_seguem_os_demais_formularios(self):
        for largura, trilho in self.ESTADOS:
            for rota, args in (("pessoa_nova", ()), ("funcionario_novo", ()),
                               ("estoque:produto_editar", (self.c.produto.pk,))):
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self.abrir(rota, largura, trilho, args)
                    caixas = self.page.locator('#conteudo input[type="checkbox"]:visible')
                    self.assertGreater(caixas.count(), 0)
                    for caixa in caixas.all():
                        medida = caixa.bounding_box()
                        self.assertAlmostEqual(medida["width"], 18, delta=1)
                        self.assertAlmostEqual(medida["height"], 18, delta=1)
                        if largura <= 820:
                            alvo = caixa.evaluate("e => e.closest('label').getBoundingClientRect().height")
                            self.assertGreaterEqual(alvo, 44)
                    if rota == "estoque:produto_editar" and largura == 1440:
                        self.foto(f"retomada-produto-{largura}-{trilho}")
                        topos = self.page.locator(".est-produto-opcoes .check-inline").evaluate_all(
                            "es => es.map(e => e.getBoundingClientRect().top)")
                        self.assertLessEqual(max(topos) - min(topos), 1)
            self.abrir("comercial:pagina_nova", largura, trilho)
            for campo in self.page.locator('input[type="url"]:visible').all():
                medida = campo.evaluate("""e => ({campo:e.getBoundingClientRect().width,
                    pai:e.parentElement.getBoundingClientRect().width})""")
                self.assertGreaterEqual(medida["campo"], medida["pai"] - 2, medida)

    def test_menu_indica_mais_opcoes_e_remove_a_pista_ao_chegar_ao_fim(self):
        for trilho in (False, True):
            self.abrir("dashboard", 1440, trilho)
            menu = self.page.locator("#menu-principal")
            menu.evaluate("e => { e.scrollTop=0; e.dispatchEvent(new Event('scroll')); }")
            expect(menu).to_have_attribute("data-mais-abaixo", "")
            self.assertNotEqual(menu.evaluate("e => getComputedStyle(e).maskImage"), "none")
            menu.evaluate("e => { e.scrollTop=e.scrollHeight; e.dispatchEvent(new Event('scroll')); }")
            expect(menu).not_to_have_attribute("data-mais-abaixo", "")
            self.assertEqual(menu.evaluate("e => getComputedStyle(e).maskImage"), "none")

    def test_lotes_suprimentos_e_anexos_tem_controles_utilizaveis(self):
        for largura, trilho in self.ESTADOS:
            self.abrir("estoque:lotes", largura, trilho)
            select = self.page.locator("#situacao-lote")
            self.assertEqual(select.locator("option").evaluate_all("es => es.map(e => e.value)"),
                             ["", "com_saldo", "vencidos"])
            select.select_option("com_saldo")
            self.page.get_by_role("button", name="Filtrar", exact=True).click()
            expect(self.page.locator("#situacao-lote")).to_have_value("com_saldo")
            self.abrir("estoque:compra_receber", largura, trilho)
            expect(self.page.locator(".est-abas")).to_be_visible()
            expect(self.page.locator(".pagina-acoes")).to_be_visible()
            self.abrir("estoque:nota_nova", largura, trilho)
            expect(self.page.locator("#id_fornecedor option").first).to_have_text("Selecione…")
            arquivos = self.page.locator('input[name="documentos"]')
            arquivos.set_input_files([{"name": "conferencia.txt", "mimeType": "text/plain", "buffer": b"QA"}])
            expect(self.page.locator("#nota-anexos-status")).to_have_text("1 arquivo selecionado")
            arquivos.set_input_files([])
            expect(self.page.locator("#nota-anexos-status")).to_have_text("Nenhum arquivo selecionado")

    def test_estorno_preenchido_grava_valor_exato_e_movimento_inverso(self):
        movimento = self.c.sessao.movimentos.get(tipo=MovimentoCaixa.Tipo.RECEBIMENTO)
        for largura, trilho in self.ESTADOS:
            self.abrir("caixa_sessao", largura, trilho, (self.c.sessao.pk,))
            self.page.locator(".acao-sensivel summary").click()
            valor = self.page.get_by_role("textbox", name="Valor do estorno")
            expect(valor).to_have_value("37,80")
            self.assertTrue(valor.evaluate("e => e.validity.valid"))
            self.assertEqual(valor.get_attribute("type"), "text")
        self.page.locator('input[name="motivo"]').fill("Conferência visual do estorno")
        self.page.get_by_role("button", name="Confirmar", exact=True).click()
        expect(self.page.get_by_text("Estorno registrado no histórico de auditoria.")).to_be_visible()
        movimento.refresh_from_db()
        self.assertEqual(movimento.valor, Decimal("37.80"))
        self.assertEqual(movimento.estornos.get().valor, Decimal("37.80"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="estorno", usuario=self.c.usuario).exists())

    def test_cobranca_expirada_tem_alerta_e_nao_oferece_compartilhamento(self):
        cobranca = Cobranca.objects.create(
            valor="764.80", metodo="pix", descricao="Cobrança vencida da conferência",
            expira_em=timezone.now() - timedelta(minutes=1), criado_por=self.c.usuario,
            pix_copia_cola="PIX-FICTICIO-PARA-TESTE",
        )
        for largura, trilho in self.ESTADOS:
            self.abrir("pagamentos:detalhe", largura, trilho, (cobranca.pk,))
            expect(self.page.locator(".selo-pg-expirado")).to_have_text("Expirado")
            self.assertEqual(self.page.locator("[data-copiar]").count(), 0)
            self.page.goto(self.url(reverse("pagamentos:pagar", args=[cobranca.token])))
            selo = self.page.locator(".pay .selo-pg-expirado")
            expect(selo).to_have_text("Expirado")
            self.assertNotEqual(selo.evaluate("e => getComputedStyle(e).backgroundColor"), "rgba(0, 0, 0, 0)")
            cores = self.page.locator(".pay .valor").evaluate("""e => ({atual:getComputedStyle(e).color,
                esperado:getComputedStyle(e.parentElement).color})""")
            self.assertEqual(cores["atual"], cores["esperado"])
            expect(self.page.get_by_text("Este link de pagamento expirou")).to_be_visible()
            self.foto(f"retomada-pagamento-expirado-{largura}-{trilho}")

    def test_nove_relatorios_preservam_titulos_valores_e_largura(self):
        for chave in ("ocupacao", "faturamento_modulos", "carteira", "comercial", "distribuicao",
                      "estoque", "reservas", "producao", "caixa"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(relatorio=chave, largura=largura, trilho=trilho):
                    self.abrir("relatorios:relatorio", largura, trilho, (chave,))
                    for tabela in self.page.locator('.rel-tabela').all():
                        medidas = tabela.locator('tbody td').evaluate_all("""es => es.map(e => ({
                            texto:e.textContent.trim(), excesso:e.scrollWidth-e.clientWidth
                        }))""")
                        self.assertTrue(all(m['excesso'] <= 1 for m in medidas), (chave, medidas))
                        if tabela.evaluate("e => getComputedStyle(e).display") == "table":
                            linhas = tabela.locator('th.col-numero').evaluate_all("""es => es.map(e => {
                                const r=document.createRange(); r.selectNodeContents(e);
                                return new Set([...r.getClientRects()].map(c => Math.round(c.top))).size;
                            })""")
                            self.assertTrue(all(n == 1 for n in linhas), (chave, linhas))
                    if chave in ("ocupacao", "carteira") and largura in (320, 1440):
                        self.foto(f"retomada-relatorio-{chave}-{largura}-{trilho}")

    def test_dica_de_categorias_responde_ao_conteudo_e_ao_redimensionamento(self):
        self.abrir("loja:pdv", 1440)
        busca = self.page.locator('#pdv-busca').bounding_box()
        local = self.page.locator('.pdv-local select').bounding_box()
        self.assertAlmostEqual(busca['height'], local['height'], delta=1)
        self.assertAlmostEqual(busca['y'], local['y'], delta=1)
        dica = self.page.locator('[data-categorias-rolagem]')
        expect(dica).to_be_hidden()
        self.page.locator('[data-categorias-lista]').evaluate("""e => {
            for(let n=0;n<16;n++){
                const b=document.createElement('button'); b.className='filtro-chip';
                b.textContent='Categoria de teste '+n; b.dataset.teste='sim'; e.append(b);
            }
        }""")
        # No monitor as categorias quebram linha; só no celular há faixa rolante.
        expect(dica).to_be_hidden()
        self.page.set_viewport_size({"width": 390, "height": 900})
        expect(dica).to_be_visible()
        self.page.locator('[data-categorias-lista] [data-teste]').evaluate_all("es => es.forEach(e=>e.remove())")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        expect(dica).to_be_hidden()
        self.page.evaluate("document.body.dispatchEvent(new Event('htmx:afterSwap'))")
        expect(dica).to_be_hidden()

    def test_painel_de_quartos_disponiveis_nao_recorta_linhas_e_kardex_cabe(self):
        for largura, trilho in self.ESTADOS:
            self.abrir("comercial:oportunidade", largura, trilho, (self.c.oportunidade.pk,))
            lista = self.page.locator('.pq-lista:not(.pq-ocupados-titulo + .pq-lista)').first
            if lista.count():
                self.assertLessEqual(lista.evaluate("e => e.scrollHeight-e.clientHeight"), 1)
            self.abrir("estoque:kardex", largura, trilho, (self.c.produto.pk,))
            for linha in self.page.locator('.est-kardex-tabela tbody tr').all():
                self.assertLessEqual(linha.evaluate("e => e.scrollWidth-e.clientWidth"), 1)
            self.foto(f"retomada-kardex-{largura}-{trilho}")

    def test_mapa_e_paleta_preservam_cabecalho_e_piso_de_leitura(self):
        self.abrir("reservas:mapa", 821)
        mapa = self.page.locator('.mapa-rolagem')
        mapa.evaluate("e => e.scrollLeft=200")
        self.page.evaluate("() => new Promise(r => requestAnimationFrame(r))")
        limite = mapa.bounding_box()['x'] + 110
        celulas = self.page.locator('.mapa-meses th:has(span)').evaluate_all("""es => es.map(e => ({
            direita:e.getBoundingClientRect().right,
            rotulo:e.querySelector('span').getBoundingClientRect().left
        }))""")
        visiveis = [c for c in celulas if c['direita'] > limite + 110]
        self.assertTrue(visiveis)
        self.assertTrue(all(c['rotulo'] >= limite - 1 for c in visiveis), visiveis)
        self.foto("retomada-mapa-821-rolado")
        self.page.keyboard.press("Control+k")
        expect(self.page.locator('.paleta')).to_be_visible()
        tamanhos = self.page.locator('.paleta-rodape, .paleta-rodape kbd').evaluate_all(
            "es => es.map(e => parseFloat(getComputedStyle(e).fontSize))")
        self.assertTrue(tamanhos)
        self.assertTrue(all(t >= 11.2 for t in tamanhos), tamanhos)
