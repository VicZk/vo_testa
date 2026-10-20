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

    def _token(self, nome):
        achado = re.search(rf"--{nome}:\s*(#[0-9A-Fa-f]{{6}})", self.css)
        self.assertIsNotNone(achado, f"token --{nome} não encontrado")
        return achado.group(1)

    def test_contorno_do_foco_tem_contraste_de_sobra(self):
        """O contorno é --madeira; precisa de ≥ 3:1 sobre as superfícies claras.

        Lê os tokens do CSS: antes os hexes estavam escritos à mão aqui, então
        o teste passava mesmo que a cor da marca mudasse no `:root`."""
        madeira = self._token("madeira")
        for fundo in ("canvas", "superficie", "superficie-2"):
            self.assertGreaterEqual(_contraste(madeira, self._token(fundo)), 3.0, fundo)
        # Na sidebar noturna o contorno vira dourado claro.
        self.assertGreaterEqual(
            _contraste(self._token("lampiao-claro"), self._token("noturno")), 3.0
        )
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
        for classe in (".cartao-el {", ".quadro {", ".vazio-el {", ".kpi-val {"):
            self.assertIn(classe, self.css, classe)
        # .selo-pub virou uma linha na lista de cores do selo (ver SelosDiscretosTests).
        self.assertIn(".selo-pub", self.css)

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


class SelosDiscretosTests(TestCase):
    """A pílula é recurso escasso.

    O dono relatou saturação ("pills demais em tudo") e a medição confirmou:
    71 cápsulas preenchidas só na tela de Pessoas, nenhuma delas um status que
    pedisse ação. A regra agora mora na classe-base: `.selo` nasce bolinha +
    texto; cápsula é modificador; rótulo de dado é texto; filtro é controle.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.raizes = [
            Path(settings.BASE_DIR) / "templates",
            Path(settings.BASE_DIR) / "apps" / "site" / "templates",
        ]

    def _base_do_selo(self):
        achado = re.search(r"\n\.selo \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(achado, "regra-base .selo não encontrada")
        return achado.group(1)

    def test_selo_nasce_sem_capsula(self):
        base = self._base_do_selo()
        self.assertIn("background: none", base)
        self.assertIn("border: 0", base)
        self.assertIn("border-radius: 0", base)
        self.assertIn("text-transform: none", base)

    def test_selo_tem_bolinha_na_cor_do_estado(self):
        self.assertIn(".selo::before", self.css)
        self.assertIn("background: var(--selo-cor)", self.css)

    def test_capsula_existe_como_modificador(self):
        self.assertIn(".selo--acao", self.css)

    def test_rotulo_de_dado_e_filtro_tem_classe_propria(self):
        self.assertIn(".rotulo-dado {", self.css)
        self.assertIn(".filtro-chip {", self.css)
        # O filtro precisa anunciar o estado marcado para quem usa leitor de tela.
        self.assertIn('.filtro-chip[aria-pressed="true"]', self.css)

    def test_estado_so_troca_a_cor(self):
        """Estado novo = uma linha (`--selo-cor`), nunca um bloco com fundo."""
        for estado in (".selo-limpa", ".selo-pendente", ".selo-pg-pago", ".selo-enc"):
            linha = re.search(rf"^[^\n]*{re.escape(estado)}[^\n]*$", self.css, re.M)
            self.assertIsNotNone(linha, estado)
        self.assertNotIn(".selo-limpa, .selo-concluida { color:", self.css)

    def test_templates_nao_usam_mais_capsula_para_rotulo(self):
        """`.selo-contador` (pílula dentro de pílula) e `.selo-tipo-*`
        (PF/PJ repetido linha a linha) saíram de cena."""
        restos = []
        for raiz in self.raizes:
            for p in raiz.rglob("*.html"):
                texto = p.read_text(encoding="utf-8")
                if "selo-contador" in texto or "selo-tipo-" in texto:
                    restos.append(str(p.relative_to(settings.BASE_DIR)))
        self.assertEqual(restos, [])


class GradeResponsivaTests(TestCase):
    """Cinco telas rolavam para o lado no celular.

    Um item de grid nasce `min-width: auto` e não encolhe abaixo do conteúdo:
    a tabela larga empurrava a PÁGINA em vez de rolar dentro do cartão.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_filhos_de_grade_podem_encolher(self):
        achado = re.search(r"([^\n]*\{ min-width: 0; \})", self.css)
        self.assertIsNotNone(achado, "regra de min-width:0 das grades sumiu")
        for grade in (".colunas-2-1 > *", ".painel-2col > *", ".pdv > *",
                      ".graficos-grid > *", ".boh-resumo > *", ".ficha-cols > *",
                      ".rc-cols > *"):
            self.assertIn(grade, self.css, grade)

    def test_barras_de_acao_quebram_linha(self):
        for regra in (".acoes {", ".pagina-acoes {"):
            bloco = re.search(rf"{re.escape(regra)}([^}}]*)}}", self.css)
            self.assertIsNotNone(bloco, regra)
            self.assertIn("flex-wrap: wrap", bloco.group(1), regra)

    def test_altura_da_topbar_e_token(self):
        """Quem gruda abaixo da barra calculava a partir de um "76px" solto."""
        self.assertIn("--topbar-h:", self.css)
        self.assertNotIn("top: 76px", self.css)

    def test_alvo_de_toque_de_44px_para_dedo(self):
        self.assertIn("@media (pointer: coarse), (max-width: 820px)", self.css)
        bloco = self.css[self.css.index("@media (pointer: coarse), (max-width: 820px)"):]
        self.assertIn("min-height: 44px", bloco)


class TokensUnicosTests(TestCase):
    """Uma cor da marca = um valor.

    Conviviam três ouros e dois noturnos no mesmo arquivo, e 84% dos usos de
    ouro com transparência no CRM eram do ouro antigo do site. Agora o token
    é a verdade e a transparência sai dele por `color-mix`.
    """

    def setUp(self):
        bruto = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.css = bruto
        # Comentário não é regra: o texto explicando o que foi trocado não pode
        # fazer o teste acusar a própria explicação.
        self.css_sem_comentario = re.sub(r"/\*.*?\*/", "", bruto, flags=re.S)

    def test_nenhum_rgba_de_cor_da_marca(self):
        """rgba(215,160,72,…) e companhia não voltam: use color-mix do token."""
        proibidos = {
            "(215, 160, 72)": "--lampiao", "(226, 168, 74)": "--lampiao",
            "(200, 145, 47)": "--lampiao", "(5, 28, 44)": "--noturno",
            "(4, 21, 31)": "--noturno", "(79, 44, 29)": "--madeira",
            "(239, 219, 178)": "--pergaminho", "(46, 72, 62)": "--musgo",
        }
        achados = []
        sem_espaco = self.css_sem_comentario.replace(" ", "")
        for rgb, token in proibidos.items():
            alvo = "rgba" + rgb[:-1] + ","
            if alvo.replace(" ", "") in sem_espaco:
                achados.append(f"{alvo}…) deveria ser color-mix de var({token})")
        self.assertEqual(achados, [])

    def test_marca_tem_o_mesmo_valor_do_site(self):
        """O site (tailwind.config.js) e o CRM (:root) divergiam nas 5 cores."""
        tw = (Path(settings.BASE_DIR) / "tailwind.config.js").read_text(encoding="utf-8")
        for nome in ("noturno", "madeira", "lampiao", "pergaminho", "musgo"):
            no_css = re.search(rf"--{nome}:\s*(#[0-9A-Fa-f]{{6}})", self.css)
            no_site = re.search(rf"{nome}:\s*\"(#[0-9A-Fa-f]{{6}})\"", tw)
            self.assertIsNotNone(no_css, nome)
            self.assertIsNotNone(no_site, nome)
            self.assertEqual(no_css.group(1).upper(), no_site.group(1).upper(), nome)

    def test_tokens_usados_existem(self):
        """Variável sem definição cai no fallback em silêncio — `--fonte-corpo`,
        `--musgo-bg`, `--alerta-claro` e outras quatro estavam nesse estado."""
        usadas = set(re.findall(r"var\((--[a-z0-9-]+)", self.css))
        definidas = set(re.findall(r"(--[a-z0-9-]+)\s*:", self.css))
        # Tokens que o template define no próprio elemento (cor da etapa do funil).
        for raiz in (Path(settings.BASE_DIR) / "templates",):
            for p in raiz.rglob("*.html"):
                definidas |= set(re.findall(r"(--[a-z0-9-]+)\s*:", p.read_text(encoding="utf-8")))
        self.assertEqual(sorted(usadas - definidas), [])

    def test_um_unico_bloco_por_componente(self):
        """`.kpi`, `.kpi-valor`, `.kpi-rotulo`, `.num` e `.mapa-hoje` tinham
        duas declarações cada; a segunda vencia e desfazia o desenho."""
        for classe in (".kpi", ".kpi-valor", ".kpi-rotulo", ".num", ".mapa-hoje"):
            blocos = re.findall(rf"^{re.escape(classe)}\s*(?:,[^{{]*)?\{{", self.css, re.M)
            self.assertLessEqual(len(blocos), 1, f"{classe} declarada {len(blocos)}x")

    def test_botoes_compartilham_a_mesma_forma(self):
        base = re.search(
            r"\.botao-primario, \.botao-neutro, \.botao-perigo \{([^}]*)\}", self.css
        )
        self.assertIsNotNone(base, "base compartilhada dos botões sumiu")
        self.assertIn("min-height: 40px", base.group(1))
        self.assertIn("inline-flex", base.group(1))
        # Foco visível nos quatro, não só no primário.
        foco = re.search(r"([^\n]*):focus-visible,\n([^\n]*),\n([^\n]*) \{", self.css)
        self.assertIn(".botao-mini:focus-visible", self.css)

    def test_link_sem_classe_nao_fica_azul(self):
        self.assertRegex(self.css, r"\na \{[^}]*color: var\(--madeira\)")


class MovimentoTests(TestCase):
    """Havia 18 durações diferentes e ~12 hovers com `transform` sem guarda de
    `prefers-reduced-motion`. Agora são quatro degraus, e zerar os tokens
    apaga tudo de uma vez."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_tokens_de_movimento_existem(self):
        for token in ("--mov-toque", "--mov-rapido", "--mov-padrao", "--mov-lento",
                      "--curva", "--desloca"):
            self.assertIn(f"{token}:", self.css, token)

    def test_reduced_motion_zera_os_tokens(self):
        bloco = re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{\s*:root \{([^}]*)\}", self.css
        )
        self.assertIsNotNone(bloco, "falta o bloco que zera os tokens de movimento")
        for token in ("--mov-toque", "--mov-rapido", "--mov-padrao", "--mov-lento"):
            self.assertIn(f"{token}: 1ms", bloco.group(1), token)
        self.assertIn("--desloca: 0px", bloco.group(1))
