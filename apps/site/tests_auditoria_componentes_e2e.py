"""Regressões da auditoria visual: espaço útil, ações alcançáveis e leitura."""

import os
import unittest
from datetime import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.escala.models import Turno
from apps.marketing.models import Campanha
from apps.nucleo.models import UH, EntradaLogbook, ModuloContratado, TipoUH, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class AuditoriaComponentesE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        self.usuario = Usuario.objects.create_superuser(
            username="auditoria-componentes", password="qa-componentes-123",
            first_name="Operador da conferência visual",
        )
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        cache.clear()
        self.tipo = TipoUH.objects.create(nome="Suíte de conferência visual", tarifa_base="300")
        self.uh = UH.objects.create(numero="QA 01", tipo=self.tipo)
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")
        self.page.set_viewport_size({"width": 1440, "height": 900})

    def _abrir(self, rota, *, largura=1440, trilho=False, altura=900, query=""):
        self.page.set_viewport_size({"width": largura, "height": altura})
        self.page.goto(self.url(reverse(rota) + query), wait_until="load")
        expect(self.page.locator("#conteudo")).to_be_visible()
        self.page.evaluate("document.fonts.ready")
        recolhida = self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')")
        if largura > 820 and recolhida != trilho:
            self.page.locator(".sidebar-toggle").click()
        if largura > 820:
            # Reduced motion ainda usa uma transição de 1 ms. A classe muda
            # antes da grade; compare telas apenas no modo efetivamente pedido.
            self.page.wait_for_function("""trilho => {
                const app = document.querySelector('.app');
                const estilo = getComputedStyle(app);
                const alvo = parseFloat(estilo.getPropertyValue(
                    trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                return app.classList.contains('recolhida') === trilho &&
                    Math.abs(parseFloat(estilo.gridTemplateColumns) - alvo) < .1 &&
                    Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width - alvo) < .1;
            }""", arg=trilho)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)

    def _foto(self, nome, *, pagina_inteira=True):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / f"auditoria-{nome}.png"), full_page=pagina_inteira)

    def test_relatorio_imprime_colunas_e_cabecalho_mesmo_aberto_no_celular(self):
        from apps.relatorios.services import RELATORIOS

        dados = {"kpis": [], "colunas": ["Categoria", "Quantidade", "Total"],
                 "linhas": [[f"Linha de conferência {n}", str(n), f"R$ {n},00"] for n in range(1, 31)]}
        with patch.dict(RELATORIOS["reservas"], {"builder": lambda inicio, fim: dados}):
            self.page.set_viewport_size({"width": 390, "height": 844})
            self.page.goto(self.url(reverse("relatorios:relatorio", args=["reservas"])))
        tabela = self.page.locator(".tabela-cartoes")
        self.assertEqual(tabela.evaluate("el => getComputedStyle(el).display"), "block")
        self.page.emulate_media(media="print")
        self.assertEqual(tabela.evaluate("el => getComputedStyle(el).display"), "table")
        cabecalho = tabela.locator("thead").evaluate("""el => {
            const c = getComputedStyle(el);
            return {display:c.display, position:c.position, clip:c.clipPath};
        }""")
        self.assertEqual(cabecalho, {"display": "table-header-group", "position": "static", "clip": "none"})
        expect(tabela.locator("tbody tr")).to_have_count(30)
        for linha in tabela.locator("tbody tr").all():
            medidas = linha.locator("td").evaluate_all("""els => els.map(el => {
                const r = el.getBoundingClientRect(); return {x:r.x, right:r.right, y:r.y};
            })""")
            self.assertLessEqual(max(x["y"] for x in medidas) - min(x["y"] for x in medidas), 1)
            self.assertTrue(all(a["right"] <= b["x"] + 1 for a, b in zip(medidas, medidas[1:])))
        self._foto("relatorio-impressao-390")

    def _conferir_dentro(self, elemento, limite, *, vertical=False):
        a = elemento.bounding_box()
        b = limite.bounding_box()
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertGreaterEqual(a["x"], b["x"] - 1, a)
        self.assertLessEqual(a["x"] + a["width"], b["x"] + b["width"] + 1, a)
        if vertical:
            self.assertGreaterEqual(a["y"], b["y"] - 1, a)
            self.assertLessEqual(a["y"] + a["height"], b["y"] + b["height"] + 1, a)

    def test_resolver_recado_cabe_no_cartao_e_funciona_no_celular(self):
        recado = EntradaLogbook.objects.create(autor=self.usuario, texto="Conferir a chave do quarto QA.")
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self._abrir("logbook", largura=largura, trilho=trilho)
                artigo = self.page.locator(f"#occ-{recado.pk}")
                artigo.locator(".lb-resolver > summary").click()
                confirmar = artigo.get_by_role("button", name="Confirmar", exact=True)
                self._conferir_dentro(confirmar, artigo)
                self._conferir_dentro(artigo.locator('input[name="nota"]'), artigo)
                self.assertGreaterEqual(confirmar.bounding_box()["height"], 44)
                self._foto(f"recado-{largura}-{'trilho' if trilho else 'aberta'}")
        self._abrir("logbook", largura=320)
        artigo = self.page.locator(f"#occ-{recado.pk}")
        artigo.locator(".lb-resolver > summary").click()
        artigo.locator('input[name="nota"]').fill("Chave conferida.")
        artigo.get_by_role("button", name="Confirmar", exact=True).click()
        expect(artigo).to_contain_text("Chave conferida.")
        recado.refresh_from_db()
        self.assertEqual(recado.status, EntradaLogbook.RESOLVIDA)
        self.assertEqual(recado.resolvida_por_id, self.usuario.pk)

    def test_modal_reserva_expandido_mantem_acoes_visiveis_e_corpo_rolavel(self):
        for largura, altura in ((1440, 900), (1440, 640), (390, 844), (320, 640)):
            with self.subTest(largura=largura, altura=altura):
                self._abrir("reservas:lista", largura=largura, altura=altura)
                self.page.locator('#conteudo [hx-target="#modal-conteudo"]').filter(
                    has_text="Nova reserva").first.click()
                modal = self.page.locator(".modal-caixa")
                expect(modal).to_be_visible()
                modal.locator(".mais-opcoes > summary").click()
                expect(modal.locator(".mais-opcoes")).to_have_attribute("open", "")
                corpo = modal.locator(".modal-corpo")
                acao = modal.get_by_role("button", name="Criar pré-reserva", exact=True)
                caixa = modal.bounding_box()
                self.assertGreaterEqual(caixa["y"], 0)
                self.assertLessEqual(caixa["y"] + caixa["height"], altura + 1)
                self._conferir_dentro(acao, modal, vertical=True)
                self.assertEqual(corpo.evaluate("el => getComputedStyle(el).overflowY"), "auto")
                if altura <= 640:
                    self.assertTrue(corpo.evaluate("el => el.scrollHeight > el.clientHeight"))
                modal.locator('textarea[name="observacoes"]').scroll_into_view_if_needed()
                self._foto(f"modal-reserva-{largura}-{altura}", pagina_inteira=False)
                expect(modal.locator('textarea[name="observacoes"]')).to_be_in_viewport()
                expect(acao).to_be_in_viewport(ratio=1)
                self._conferir_dentro(acao, modal, vertical=True)

    def test_abas_dos_modulos_expoem_todos_os_destinos_sem_cortar_palavras(self):
        for rota in ("estoque:posicao", "governanca:painel", "pessoas", "restaurante:comandas"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura=largura, trilho=trilho)
                    abas = self.page.locator(".abas-secao").first
                    expect(abas).to_be_visible()
                    self.assertLessEqual(abas.evaluate("el => el.scrollWidth - el.clientWidth"), 1)
                    for link in abas.locator("a").all():
                        self._conferir_dentro(link, abas)
                        self.assertLessEqual(link.evaluate("el => el.scrollWidth - el.clientWidth"), 1)
                        self.assertGreaterEqual(link.bounding_box()["height"], 44)
                    if rota == "estoque:posicao":
                        self._foto(f"abas-estoque-{largura}-{'trilho' if trilho else 'aberta'}")

    def test_titulos_dos_formularios_mantem_eixo_da_listagem(self):
        def medir_eixos():
            return self.page.locator("#conteudo").evaluate("""conteudo => ({
                titulo: conteudo.querySelector('h1').getBoundingClientRect().x,
                formulario: conteudo.querySelector('.form-cartao')?.getBoundingClientRect().x,
                trilho: document.querySelector('.app').classList.contains('recolhida'),
            })""")

        for largura, trilho in ((821, False), (1440, False), (1440, True), (2560, False)):
            with self.subTest(largura=largura, trilho=trilho):
                self._abrir("pessoas", largura=largura, trilho=trilho)
                eixo = medir_eixos()["titulo"]
                for rota in ("pessoa_nova", "caixa", "governanca:configuracao"):
                    with self.subTest(rota=rota):
                        self._abrir(rota, largura=largura, trilho=trilho)
                        medidas = medir_eixos()
                        self.assertEqual(medidas["trilho"], trilho)
                        self.assertAlmostEqual(medidas["titulo"], eixo, delta=1)
                        if medidas.get("formulario") is not None:
                            self.assertAlmostEqual(medidas["formulario"], eixo, delta=1)

    def test_quadro_de_compras_e_lotes_nao_oculta_os_valores_em_cartoes(self):
        for rota in ("estoque:compras", "estoque:lotes"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura=largura, trilho=trilho)
                    for quadro in self.page.locator(".quadro:has(table)").all():
                        self.assertLessEqual(quadro.evaluate("el => el.scrollWidth - el.clientWidth"), 1)
                        self._conferir_dentro(quadro.locator("table"), quadro)
                        for valor in quadro.locator("tbody td").all():
                            self._conferir_dentro(valor, quadro)

    def test_indicadores_alinham_valores_e_rotulos_sao_legiveis(self):
        for rota, minimo in (("dashboard", 5), ("estoque:posicao", 4)):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura=largura, trilho=trilho)
                    medidas = self.page.locator(".kpis .kpi").evaluate_all("""cards => cards.map(c => {
                        const titulo = c.querySelector('.kpi-rotulo'), valor = c.querySelector('.kpi-valor');
                        return {linha: c.getBoundingClientRect().top, valor: valor.getBoundingClientRect().top,
                                fonte: parseFloat(getComputedStyle(titulo).fontSize)};
                    })""")
                    self.assertGreaterEqual(len(medidas), minimo)
                    linhas = {}
                    for medida in medidas:
                        linhas.setdefault(round(medida["linha"]), []).append(medida["valor"])
                        self.assertGreaterEqual(medida["fonte"], 12 if largura <= 820 else 11)
                    for valores in linhas.values():
                        self.assertLessEqual(max(valores) - min(valores), 1)
                    self._foto(f"indicadores-{rota.replace(':', '-')}-{largura}-{'trilho' if trilho else 'aberta'}")

    def test_matrizes_indicam_rolagem_e_preservam_identidade_da_linha(self):
        Turno.objects.create(nome="Recepção da manhã", inicio=time(7), fim=time(13))
        hoje = timezone.localdate()
        Campanha.objects.create(nome="Campanha de conferência", inicio=hoje, fim=hoje)
        for rota, regiao, coluna in (
            ("escala:grade", ".escala-grade-wrap", ".escala-turno"),
            ("marketing:calendario", ".cal-scroll", ".mk-cal-nome"),
        ):
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura=largura, trilho=trilho,
                                query="?vista=mes" if rota == "marketing:calendario" else "")
                    caixa = self.page.locator(regiao)
                    if rota == "marketing:calendario" and not caixa.is_visible():
                        # O calendário estreito virou agenda vertical; a campanha
                        # continua identificada e alcançável, sem matriz escondida.
                        campanha = self.page.locator(".mkt-agenda-campanha").filter(
                            has_text="Campanha de conferência")
                        expect(campanha).to_be_visible()
                        self._conferir_dentro(campanha, self.page.locator("#conteudo"))
                        self._foto(f"matriz-marketing-calendario-{largura}-{'trilho' if trilho else 'aberta'}")
                        continue
                    identidade = caixa.locator(coluna).first
                    expect(identidade).to_be_visible()
                    sobra = caixa.evaluate("el => el.scrollWidth - el.clientWidth")
                    dica = caixa.locator("xpath=preceding-sibling::p[1]")
                    if sobra > 2:
                        expect(dica).to_be_visible()
                        expect(dica).to_contain_text("demais colunas")
                        esquerda = identidade.bounding_box()["x"]
                        caixa.evaluate("el => el.scrollLeft = el.scrollWidth")
                        expect(dica).to_contain_text("primeiras colunas")
                        self.assertAlmostEqual(identidade.bounding_box()["x"], esquerda, delta=1)
                    elif rota != "marketing:calendario":
                        expect(dica).to_be_hidden()
                    self._foto(f"matriz-{rota.replace(':','-')}-{largura}-{'trilho' if trilho else 'aberta'}")

    def test_grupo_mantem_quartos_de_altura_igual_e_acoes_alcancaveis(self):
        simples = TipoUH.objects.create(nome="Casal", tarifa_base="200")
        for i in range(2, 16):
            UH.objects.create(numero=f"QA {i:02}", tipo=simples if i % 2 else self.tipo)
        for largura, altura in ((320, 640), (390, 844), (821, 900), (1440, 640)):
            with self.subTest(largura=largura):
                self._abrir("reservas:grupos", largura=largura, altura=altura)
                self.page.get_by_role("button", name="Novo grupo", exact=True).click()
                modal = self.page.locator(".modal-caixa")
                expect(modal).to_be_visible()
                quartos = modal.locator(".quarto-card")
                expect(quartos).to_have_count(15)
                alturas = quartos.evaluate_all("els => els.map(el => el.getBoundingClientRect().height)")
                self.assertLessEqual(max(alturas) - min(alturas), 1)
                self.assertGreaterEqual(min(alturas), 44)
                expect(modal.get_by_role("button", name="Criar grupo", exact=True)).to_be_in_viewport(ratio=1)
                quartos.first.scroll_into_view_if_needed()
                quartos.first.click()
                expect(quartos.first.locator('input[type="checkbox"]')).to_be_checked()
                self._foto(f"modal-grupo-{largura}", pagina_inteira=False)
