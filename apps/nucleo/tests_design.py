"""Invariantes do design system (Lampião) que dá para checar sem navegador.

Não é teste de aparência: é de contrato. Cada caso aqui nasceu de um achado de
auditoria que voltaria sozinho na próxima tela nova.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

CSS = Path(settings.BASE_DIR) / "static" / "css" / "app.css"


def _contraste(hex_a, hex_b):
    """Razão de contraste WCAG entre duas cores #RRGGBB."""
    def luminancia(h):
        h = h.lstrip("#")
        canais = []
        for i in (0, 2, 4):
            c = int(h[i:i + 2], 16) / 255
            canais.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        r, g, b = canais
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    a, b = luminancia(hex_a), luminancia(hex_b)
    maior, menor = max(a, b), min(a, b)
    return (maior + 0.05) / (menor + 0.05)


class FocoVisivelTests(TestCase):
    """WCAG 2.4.7: `outline:none` só é aceitável com um anel no lugar."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_existe_regra_global_de_foco_visivel(self):
        self.assertIn(":focus-visible {", self.css)
        self.assertIn("--foco-contorno", self.css)

    def test_todo_outline_none_tem_substituto_documentado(self):
        """Sobraram 3 casos, todos de campo SEM borda própria dentro de um pill:
        o anel fica no contêiner (:focus-within), e isso está escrito ali."""
        ocorrencias = self.css.count("outline: none")
        self.assertEqual(ocorrencias, 3, "apareceu um `outline:none` novo sem anel")
        self.assertIn(".paleta-busca:focus-within", self.css)
        self.assertIn(".input-reais:focus-within", self.css)
        self.assertIn(".quarto-card input:focus-visible", self.css)

    def test_contorno_do_foco_tem_contraste_de_sobra(self):
        """O contorno é --madeira; precisa de ≥ 3:1 sobre as superfícies claras."""
        for fundo in ("#FFFFFF", "#F7F5F1", "#FBF8F2"):
            self.assertGreaterEqual(_contraste("#3E2418", fundo), 3.0, fundo)
        # Na sidebar noturna o contorno vira dourado claro.
        self.assertGreaterEqual(_contraste("#F0C97A", "#04151F"), 3.0)
        self.assertIn("--foco-contorno-claro", self.css)


class ContrasteDeTextoTests(TestCase):
    """WCAG 1.4.3: texto semântico sobre o próprio fundo precisa de 4,5:1."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def _token(self, nome):
        achado = re.search(rf"--{nome}:\s*(#[0-9A-Fa-f]{{6}})", self.css)
        self.assertIsNotNone(achado, f"token --{nome} não encontrado")
        return achado.group(1)

    def test_pares_semanticos_passam(self):
        for nome in ("sucesso", "alerta", "perigo", "info", "andamento"):
            cor, fundo = self._token(nome), self._token(f"{nome}-bg")
            self.assertGreaterEqual(
                _contraste(cor, fundo), 4.5,
                f"--{nome} ({cor}) sobre --{nome}-bg ({fundo}) não passa 4,5:1",
            )


class TabelaResponsivaTests(TestCase):
    """A rolagem é do invólucro, não do <table> (`display:block` num <table>
    desmonta o layout e briga com as colunas grudadas)."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_tabela_nao_vira_block(self):
        self.assertNotIn(".tabela {\n    display: block;", self.css.replace("\r\n", "\n"))
        self.assertIn(".tabela-rol {", self.css)

    def test_um_unico_ponto_de_corte_para_a_tabela(self):
        """Antes havia 640px (rolagem) e 820px (colunas grudadas): entre as duas
        larguras a tabela rolava sem referência de linha."""
        corte_errado = re.search(
            r"@media \(max-width: 640px\) \{\s*\.tabela \{", self.css
        )
        self.assertIsNone(corte_errado)

    def test_involucro_criado_pelo_js(self):
        js = Path(settings.BASE_DIR) / "static" / "js" / "tabela-rol.js"
        self.assertTrue(js.exists())
        self.assertIn("tabela-rol", js.read_text(encoding="utf-8"))


class KitEleganteTests(TestCase):
    """O kit do Comercial redefinia `.botao-primario` com outra cor e sombra —
    duas verdades para o mesmo botão. Virou design system no app.css."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")
        self.partial = (
            Path(settings.BASE_DIR) / "templates" / "comercial" / "_estilo_elegante.html"
        ).read_text(encoding="utf-8")

    def test_classes_promovidas(self):
        for classe in (".cartao-el {", ".quadro {", ".vazio-el {", ".selo-pub {", ".kpi-val {"):
            self.assertIn(classe, self.css, classe)

    def test_partial_nao_redefine_mais_botao(self):
        self.assertNotIn(".eleg .botao-primario", self.partial)
        self.assertNotIn("<style>", self.partial)   # virou só comentário

    def test_nenhum_template_inclui_mais_o_kit(self):
        raiz = Path(settings.BASE_DIR) / "templates"
        usos = [
            p for p in raiz.rglob("*.html")
            if p.name != "_estilo_elegante.html"
            and "_estilo_elegante.html" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(usos, [])
