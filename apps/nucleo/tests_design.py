"""Invariantes do design system (Lampião) que dá para checar sem navegador.

Não é teste de aparência: é de contrato. Cada caso aqui nasceu de um achado de
auditoria que voltaria sozinho na próxima tela nova.
"""

import re
from pathlib import Path
from types import SimpleNamespace

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
        """Sobraram 4 casos. Três de campo SEM borda própria dentro de um pill:
        o anel fica no contêiner (:focus-within), e isso está escrito ali. O
        quarto é o link do usuário no trilho, cuja caixa encolhe até 0px (só o
        avatar aparece): o anel vai para o avatar."""
        ocorrencias = self.css.count("outline: none")
        self.assertEqual(ocorrencias, 4, "apareceu um `outline:none` novo sem anel")
        self.assertIn(".paleta-busca:focus-within", self.css)
        self.assertIn(".input-reais:focus-within", self.css)
        self.assertIn(".quarto-card input:focus-visible", self.css)
        self.assertIn(".app.recolhida .usuario-mini:focus-visible .avatar", self.css)

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

    def test_cores_de_aviso_tem_o_mesmo_valor_do_site(self):
        """Os avisos do site usavam o vermelho e o âmbar genéricos do Tailwind; agora usam
        as semânticas da casa, com o valor do CRM."""
        tw = (Path(settings.BASE_DIR) / "tailwind.config.js").read_text(encoding="utf-8")
        for nome in ("perigo", "perigo-bg", "alerta", "alerta-bg", "sucesso", "sucesso-bg",
                     "info", "info-bg"):
            no_css = re.search(rf"--{nome}:\s*(#[0-9A-Fa-f]{{6}})", self.css)
            no_site = re.search(rf"\"?{nome}\"?:\s*\"(#[0-9A-Fa-f]{{6}})\"", tw)
            self.assertIsNotNone(no_css, nome)
            self.assertIsNotNone(no_site, nome)
            self.assertEqual(no_css.group(1).upper(), no_site.group(1).upper(), nome)

    def test_site_sem_vermelho_e_ambar_genericos(self):
        site = Path(settings.BASE_DIR) / "apps" / "site" / "templates"
        achados = [str(t.relative_to(site)) for t in site.rglob("*.html")
                   if re.search(r"\b(bg|text|border)-(red|amber)-\d", t.read_text(encoding="utf-8"))]
        self.assertEqual(achados, [])

    def test_tokens_usados_existem(self):
        """Variável sem definição cai no fallback em silêncio — `--fonte-corpo`,
        `--musgo-bg`, `--alerta-claro` e outras quatro estavam nesse estado."""
        usadas = set(re.findall(r"var\((--[a-z0-9-]+)", self.css))
        definidas = set(re.findall(r"(--[a-z0-9-]+)\s*:", self.css))
        # Tokens definidos fora do CSS: no próprio elemento pelo template (cor
        # da etapa do funil) ou em tempo de execução pelo JS (índice do toast).
        for raiz, padrao in ((Path(settings.BASE_DIR) / "templates", "*.html"),
                             (Path(settings.BASE_DIR) / "static" / "js", "*.js")):
            for p in raiz.rglob(padrao):
                texto = p.read_text(encoding="utf-8")
                definidas |= set(re.findall(r"(--[a-z0-9-]+)\s*:", texto))
                definidas |= set(re.findall(r"setProperty\(\s*['\"](--[a-z0-9-]+)", texto))
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


class FormularioEmPortuguesTests(TestCase):
    """Padrões do Django vazando na interface.

    `Nome:` com dois-pontos ao lado de rótulos escritos à mão sem eles,
    `---------` como opção vazia, e o balão de validação do Chrome em inglês
    — na tela de cadastro mais usada do produto.
    """

    def setUp(self):
        self.raiz = Path(settings.BASE_DIR) / "templates"

    def test_nenhum_template_usa_label_tag_cru(self):
        """`label_tag` acrescenta o ":"; o filtro `|rotulo` não."""
        usos = []
        for p in self.raiz.rglob("*.html"):
            texto = p.read_text(encoding="utf-8")
            if re.search(r"\{\{\s*[\w.]+\.label_tag\s*\}\}", texto):
                usos.append(str(p.relative_to(settings.BASE_DIR)))
        self.assertEqual(usos, [])

    def test_opcao_vazia_tem_texto_de_gente(self):
        from apps.nucleo.forms import SELECIONE, MovimentoCaixaForm
        from apps.reservas.forms import ReservaForm

        for form in (MovimentoCaixaForm(), ReservaForm()):
            for nome, campo in form.fields.items():
                vazio = getattr(campo, "empty_label", None)
                if vazio is not None:
                    self.assertEqual(vazio, SELECIONE, f"{form.__class__.__name__}.{nome}")
                for valor, texto in getattr(campo, "choices", []) or []:
                    if valor in ("", None):
                        self.assertNotIn("---", str(texto), f"{form.__class__.__name__}.{nome}")

    def test_validacao_em_portugues_esta_carregada(self):
        js = Path(settings.BASE_DIR) / "static" / "js" / "form-pt.js"
        self.assertTrue(js.exists())
        conteudo = js.read_text(encoding="utf-8")
        self.assertIn("novalidate", conteudo)
        self.assertIn("Preencha o campo", conteudo)
        base = (self.raiz / "base.html").read_text(encoding="utf-8")
        self.assertIn("js/form-pt.js", base)
        portal = (self.raiz / "portal" / "base.html").read_text(encoding="utf-8")
        self.assertIn("js/form-pt.js", portal)

    def test_textarea_nao_redimensiona_para_os_lados(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("textarea { resize: vertical; }", css)


class CorredorLegivelTests(TestCase):
    """A recepção lê o corredor o dia inteiro — ali o nome do hóspede é o dado.

    Em doze colunas, 11 dos 24 cartões truncavam o nome no desktop e 22 dos 24
    no tablet. E "Chegada hoje" saía em ouro sobre branco: 2,11:1.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_oito_portas_por_fileira(self):
        bloco = re.search(r"\n\.corredor \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("repeat(8, minmax(0, 1fr))", bloco.group(1))

    def test_nome_do_hospede_cabe_em_duas_linhas(self):
        bloco = re.search(r"\n\.porta-nome \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("-webkit-line-clamp: 2", bloco.group(1))
        self.assertIn("clamp(", bloco.group(1))
        tpl = (Path(settings.BASE_DIR) / "templates" / "reservas" / "partials"
               / "corredor.html").read_text(encoding="utf-8")
        self.assertNotIn("hospede.nome|truncatechars", tpl)

    def test_no_toque_a_porta_tem_a_altura_do_conteudo(self):
        """A proporção 4/5 é gesto de tela grande. No dedo ela virava vão morto:
        26px entre a data e o dinheiro num cartão de 130px a 390px, e 66px num
        de 169px no tablet de 1024px — 39% do cartão vazio, com 24 quartos para
        rolar. No mouse a porta continua porta."""
        coarse = "\n".join(
            re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                       self.css))
        bloco = re.search(r"\.corredor:not\(\.corredor-gov\) \.porta \{([^}]*)\}", coarse)
        self.assertIsNotNone(bloco, "a porta ficou sem a regra de toque")
        self.assertIn("aspect-ratio: auto", bloco.group(1))
        # e a proporção segue valendo fora dali
        fora = re.search(r"\n\.porta \{([^}]*)\}", self.css)
        self.assertIn("aspect-ratio: 4 / 5", fora.group(1))

    def test_a_regra_de_toque_nao_mexe_no_corredor_da_governanca(self):
        """As duas telas usam as mesmas classes (`class="corredor corredor-gov"`)
        e a Governança já resolveu isto à sua maneira, em qualquer largura:
        `aspect-ratio: auto` com `min-height: 94px`, porque lá o bloco mostra
        menos coisa. Sem a exceção, a regra de toque vem depois no arquivo e
        zeraria aquele piso justamente no dedo, que é onde aquela tela vive."""
        coarse = "\n".join(
            re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                       self.css))
        for regra in re.findall(r"([^\n{}]*\.porta[^\n{}]*)\{", coarse):
            if ".corredor" not in regra:
                continue
            self.assertIn(":not(.corredor-gov)", regra,
                          f"{regra.strip()} também pega o corredor da Governança")
        gov = re.search(r"\n\.corredor-gov \.porta \{([^}]*)\}", self.css)
        self.assertIsNotNone(gov)
        self.assertIn("min-height: 94px", gov.group(1))

    def test_ouro_nao_vira_texto_sobre_claro(self):
        """--lampiao sobre branco dá 2,11:1; como texto, usa-se --lampiao-tinta."""
        for regra in (".sit-chegada", ".pdv-contador"):
            bloco = re.search(rf"{re.escape(regra)} \{{([^}}]*)\}}", self.css)
            self.assertIsNotNone(bloco, regra)
            self.assertNotIn("color: var(--lampiao)", bloco.group(1), regra)
        achado = re.search(r"--lampiao-tinta:\s*(#[0-9A-Fa-f]{6})", self.css)
        self.assertIsNotNone(achado)
        self.assertGreaterEqual(_contraste(achado.group(1), "#FFFFFF"), 4.5)


class DesenhadoParaODedoTests(TestCase):
    """A Governança é usada quase toda no tablet e no celular.

    Alvo de 44px já havia; faltava o resto do que o dedo precisa: FOLGA entre os
    alvos (as abas e os três botões da ronda ficavam a 6px), texto que se leia a
    um braço de distância (rótulo de dado a 11,8px em maiúsculas) e a
    sobreposição encostada embaixo, onde a mão já está.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        # O bloco grande de toque é o que traz os alvos do menu (há outro, menor,
        # só para o mapa de reservas).
        marca = "@media (pointer: coarse), (max-width: 820px) {"
        inicio = self.css.index(marca, self.css.index(".sidebar .nav-item") - 3000)
        # O bloco vai até o fechamento da media query (o "\n}" na coluna 0).
        self.toque = self.css[inicio:self.css.index("\n}\n", inicio)]

    def test_folga_entre_alvos_vizinhos(self):
        """44px de alvo colado em 44px de alvo ainda erra: o dedo cobre os dois."""
        bloco = re.search(r"\n  \.filtros, \.subnav[^{]*\{([^}]*)\}", self.toque)
        self.assertIsNotNone(bloco, "regra de folga entre alvos não encontrada")
        self.assertIn("gap: 10px", bloco.group(1))
        for alvo in (".subnav", ".gov-ciclo", ".ronda-grupo", ".acoes-quarto",
                     ".gov-fila-acoes"):
            self.assertIn(alvo, self.toque, alvo)

    def test_texto_de_dado_legivel_sem_zoom(self):
        """O rótulo de dado carrega o nome do hóspede; a frase de apoio, o porquê.

        Escopo em `.conteudo`: o portal e a página de pagamento ficam fora da
        casca do CRM e têm o próprio recorte de CSS (base.css) — a regra não pode
        atravessar para lá de carona.
        """
        for regra in (".conteudo .rotulo-dado",
                      ".conteudo .ajuda, .conteudo .bloco-subtitulo"):
            bloco = re.search(rf"\n  {re.escape(regra)} \{{([^}}]*)\}}", self.toque)
            self.assertIsNotNone(bloco, regra)
            tamanho = re.search(r"font-size: ([\d.]+)rem", bloco.group(1))
            self.assertIsNotNone(tamanho, regra)
            self.assertGreaterEqual(float(tamanho.group(1)), .8, regra)

    def test_sobreposicao_encosta_embaixo_no_toque(self):
        """O modal nasce a 6vh do TOPO: no celular as ações dele caem longe do
        polegar e disputam altura com o teclado."""
        overlay = re.search(r"\n  \.modal-overlay \{([^}]*)\}", self.toque)
        self.assertIsNotNone(overlay)
        self.assertIn("align-items: flex-end", overlay.group(1))
        caixa = re.search(r"\n  \.modal-caixa \{([^}]*)\}", self.toque)
        self.assertIsNotNone(caixa)
        self.assertIn("max-height", caixa.group(1))

    def test_a_altura_da_gaveta_e_a_tela_que_existe_agora(self):
        """`vh` no iPhone é a viewport GRANDE (barra do Safari escondida): com a
        barra à vista, 88vh encostado embaixo sobe além do topo e o título some.
        `dvh` com o `vh` antes, como plano B."""
        caixa = re.search(r"\n  \.modal-caixa \{([^}]*)\}", self.toque)
        self.assertIsNotNone(caixa)
        alturas = re.findall(r"max-height: (\d+)(dvh|vh)", caixa.group(1))
        self.assertEqual([u for _, u in alturas], ["vh", "dvh"],
                         "o dvh tem de vir DEPOIS do vh (plano B primeiro)")

    def test_a_linha_do_plano_e_o_alvo_inteiro(self):
        """O alvo é a LINHA, não o número: como link de texto ele encolhia ao
        conteúdo (43 px de largura a 390 px) e o dedo tinha de acertar a palavra."""
        bloco = re.search(r"\n\.gov-chegada-quarto \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("display: flex", bloco.group(1))
        altura = re.search(r"min-height: (\d+)px", bloco.group(1))
        self.assertIsNotNone(altura, "a linha do plano precisa de piso de altura")
        self.assertGreaterEqual(int(altura.group(1)), 44)
        # O conteúdo da linha é que divide o espaço; o link ocupa a largura toda.
        tpl = (Path(settings.BASE_DIR) / "templates" / "governanca"
               / "visao.html").read_text(encoding="utf-8")
        self.assertIn("gov-chegada-nome", tpl)

    def test_so_quem_e_alvo_cresce_para_44px(self):
        """A legenda do corredor da Governança filtra (é botão); a do painel do
        núcleo é `<span>`. Inchar texto que ninguém toca é espaço perdido."""
        alvos = re.search(r"\n  \.botao-primario, [^{]*\{[^}]*min-height: 44px;[^}]*\}",
                          self.toque)
        self.assertIsNotNone(alvos)
        self.assertIn(".chip-legenda-link", alvos.group(0))
        self.assertNotIn("\n  .chip-legenda {", self.toque)

    def test_o_botao_da_gaveta_nao_foge_da_tela(self):
        acoes = re.search(r"\n  \.modal-acoes \{([^}]*)\}", self.toque)
        self.assertIsNotNone(acoes)
        self.assertIn("position: sticky", acoes.group(1))
        self.assertIn("bottom: 0", acoes.group(1))

    def test_o_aviso_sobe_para_o_topo_no_toque(self):
        """Embaixo ele caía exatamente sobre o botão da gaveta (e sobre o polegar)."""
        toasts = re.search(r"\n  \.toasts \{([^}]*)\}", self.toque)
        self.assertIsNotNone(toasts)
        self.assertIn("bottom: auto", toasts.group(1))
        self.assertIn("top:", toasts.group(1))


class CorredorDaGovernancaTests(TestCase):
    """O painel escuro da Governança é lido de longe — e dizia a coisa errada.

    O ESTADO do quarto saía num rótulo de 9 px em maiúsculas (o "Pronto" azul
    quase desaparecia no fundo azul-noite), o maior texto do bloco era o TIPO do
    quarto, e "a limpar" e "em limpeza" tinham o mesmo fundo. Esta seção é a
    paleta noturna por tokens: o contrato é que todo estado
    passe 4,5:1 nas DUAS pontas do gradiente do seu bloco.
    """

    # Fundo de cada estado (topo, base do gradiente) e a cor do texto do estado.
    ESTADOS = {
        "limp-suja": ("#4A2E22", "#2E1A14"),
        "limp-em_limpeza": ("#4A3C1E", "#2C2310"),
        "limp-limpa": ("#1B3B33", "#102722"),
        "limp-inspecionada": ("#1C3A4E", "#112636"),
        "limp-bloqueada": ("#2A343A", "#1B2328"),
    }

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")

    def _resolver_cores(self, valor):
        tokens = dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", self.css))
        return re.sub(r"var\((--[\w-]+)\)", lambda m: tokens[m.group(1)], valor)

    def _cor(self, seletor, propriedade="color"):
        achado = re.search(rf"{re.escape(seletor)} \{{\s*{propriedade}: ([^;]+);", self.css)
        self.assertIsNotNone(achado, seletor)
        return self._resolver_cores(achado.group(1))

    def test_cada_estado_passa_contraste_nas_duas_pontas_do_gradiente(self):
        for classe in self.ESTADOS:
            cor = self._cor(f".corredor-gov .{classe} .porta-estado")
            fundo_declarado = self._cor(f".corredor-gov .porta.{classe}", "background")
            fundos = re.findall(r"#[0-9A-Fa-f]{6}", fundo_declarado)
            self.assertEqual(len(fundos), 2, classe)
            for fundo in fundos:
                self.assertGreaterEqual(
                    _contraste(cor, fundo), 4.5,
                    f"{classe}: {cor} sobre {fundo} não passa 4,5:1")

    def test_o_indicador_de_estado_tem_a_cor_do_texto_do_estado(self):
        """Porta com trinco de uma cor e texto de outra dava dois sinais."""
        for classe in self.ESTADOS:
            texto = self._cor(f".corredor-gov .{classe} .porta-estado")
            trinco = self._cor(f".corredor-gov .{classe} .porta-fecho", "background")
            self.assertEqual(trinco, texto, classe)

    def test_a_limpar_e_em_limpeza_nao_compartilham_o_fundo(self):
        fundos = {}
        for classe in ("limp-suja", "limp-em_limpeza"):
            achado = re.search(
                rf"\.corredor-gov \.porta\.{re.escape(classe)} \{{ background: ([^;]+);",
                self.css)
            self.assertIsNotNone(achado, classe)
            fundos[classe] = achado.group(1)
        self.assertNotEqual(fundos["limp-suja"], fundos["limp-em_limpeza"])

    def test_quarto_bloqueado_nao_e_desbotado(self):
        """`opacity` no bloco inteiro apaga o texto junto: quarto em reparo é
        informação, não enfeite."""
        bloco = re.search(r"\.corredor-gov \.porta\.limp-bloqueada \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertNotIn("opacity", bloco.group(1))
        self.assertNotIn("grayscale", bloco.group(1))

    def test_o_estado_e_mais_forte_que_o_rotulo_de_9px_que_substituiu(self):
        bloco = re.search(r"\n\.porta-estado \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("font-weight: 700", bloco.group(1))
        self.assertIn("clamp(", bloco.group(1))
        self.assertNotIn("text-transform: uppercase", bloco.group(1))

    def test_o_bloco_da_governanca_e_mais_baixo_que_a_porta_da_recepcao(self):
        """Lá cabem nome, período e saldo; aqui a proporção 4/5 só deixava a
        metade de baixo vazia."""
        bloco = re.search(r"\n\.corredor-gov \.porta \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("aspect-ratio: auto", bloco.group(1))


class MovimentoDaNavegacaoTests(TestCase):
    """Havia 43 pontos de troca HTMX e nenhum com transição: clicar no menu
    trocava a página de estalo e a lista da comanda piscava."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

    def test_so_o_conteudo_anima_na_troca_de_pagina(self):
        """Abas mantêm shell/cabeçalho estáveis e animam somente os blocos novos.
        O E2E mede opacidade, alvos e presença de movimento quadro a quadro."""
        self.assertNotIn('"globalViewTransitions": true', self.base)
        nav = re.search(r'<nav id="menu-principal"[^>]*>', self.base).group(0)
        self.assertNotIn("transition:true", nav)
        self.assertIn('hx-target="#conteudo"', nav)
        navegacao = (Path(settings.BASE_DIR) / "static/js/navegacao.js").read_text(encoding="utf-8")
        self.assertNotIn("conteudo.animate(", navegacao)
        self.assertIn("navegacao-conteudo-local", navegacao)
        self.assertIn("prefers-reduced-motion: reduce", navegacao)
        self.assertRegex(self.css, r"@view-transition \{ navigation: auto; \}")
        for seletor, nome in ((".sidebar", "menu"), (".topbar", "topo"), (".conteudo", "conteudo")):
            self.assertIn(f"{seletor} {{ view-transition-name: {nome}; }}", self.css)
        parados = re.search(r"::view-transition-group\(root\)[^{]*\{\s*animation: none;", self.css)
        self.assertIsNotNone(parados)
        for nome in ("menu", "topo"):
            self.assertIn(f"::view-transition-old({nome})", parados.group(0))
            self.assertIn(f"::view-transition-new({nome})", parados.group(0))
        self.assertIn("::view-transition-new(conteudo)", self.css)

    def test_existe_plano_b_sem_view_transitions(self):
        self.assertIn(".htmx-swapping", self.css)
        self.assertIn(".htmx-settling", self.css)

    def test_toast_nao_cobre_os_botoes_da_pagina(self):
        bloco = re.search(r"\n\.toasts \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("bottom:", bloco.group(1))
        self.assertNotIn("top: 1rem", bloco.group(1))

    def test_toast_tem_icone_e_erro_persistente(self):
        self.assertIn("toast-ico", self.css)
        self.assertIn("TOAST_ICO", self.base)
        # O erro não some sozinho: quem perde a mensagem perde o motivo.
        self.assertIn("toast-error", self.base)
        self.assertRegex(self.base, r"else if \(!el\.classList\.contains\('toast-error'\)[^{]*\{\s*"
                         r"temporizadoresToast\.set\(el, setTimeout")
        self.assertIn("if (el.hidden)", self.base)
        self.assertIn("clearTimeout(temporizadoresToast.get(el))", self.base)

    def test_largura_da_sidebar_anima(self):
        bloco = re.search(r"\n\.app \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("transition: grid-template-columns", bloco.group(1))


class MenuLateralTests(TestCase):
    """O trilho recolhido é o estado PADRÃO do sistema, e era o menos cuidado:
    32 itens sem nome nenhum para leitor de tela, o rodapé do usuário vazando
    27px para fora da sidebar e o topo saltando 52px ao recolher."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

    def _itens_do_menu(self):
        """Item inteiro, inclusive o contêiner com dois links da Governança."""
        return re.findall(r"<(?:a|button|div)\s[^>]*class=\"(?:nav-item|acao-topo)(?:\s[^\"]*)?\"[^>]*>",
                          self.base)

    def test_item_do_menu_tem_dica_quando_recolhido(self):
        """Recolhido, o rótulo sai da vista: sem `title` o item vira um ícone
        anônimo, sem nome e sem dica ao passar o mouse."""
        sem = [t[:70] for t in self._itens_do_menu() if "title=" not in t]
        self.assertEqual(sem, [], "item do menu sem title")

    def test_rotulo_recolhido_some_da_vista_mas_nao_da_leitura(self):
        """`display:none` tirava o rótulo da árvore de acessibilidade — era por
        isso que os 32 itens ficavam sem nome. Ele também não pode sair do
        FLUXO: tirado do fluxo (posição absoluta + clip), o item encolhia 2px e
        os títulos de grupo sumiam — o 34º ícone subia 313px ao recolher.
        Agora o rótulo só esmaece (opacidade), no mesmo lugar."""
        bloco = re.search(
            r"\.app\.recolhida \.nav-item \.rotulo,\n[^{]*\{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco, "regra do rótulo recolhido sumiu")
        corpo = bloco.group(1)
        self.assertIn("opacity: 0", corpo)
        for proibido in ("display: none", "visibility: hidden", "position: absolute"):
            self.assertNotIn(proibido, corpo)

    def test_rotulo_nao_quebra_linha_durante_a_animacao(self):
        bloco = re.search(r"\n\.nav-item \.rotulo, [^{]*\{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("white-space: nowrap", bloco.group(1))

    def test_topo_da_sidebar_tem_altura_fixa_nos_dois_estados(self):
        """Sem ela, trocar o logotipo (86px) pelo símbolo (34px) empurrava todo
        o menu 52px para cima num quadro só."""
        self.assertIn("--sidebar-topo-h:", self.css)
        bloco = re.search(r"\n\.sidebar-topo \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("height: var(--sidebar-topo-h)", bloco.group(1))
        self.assertNotIn(".app.recolhida .sidebar-topo", self.css,
                         "o topo não muda de desenho no trilho — só o que está dentro dele")

    def test_nav_nao_rola_de_lado_e_prende_o_posicionado(self):
        """Sem `position: relative` na <nav>, o ancestral posicionado mais
        próximo de quem é absoluto lá dentro passa a ser a própria `.sidebar`:
        escapa da rolagem do menu e estica o DOCUMENTO (a Visão geral já foi de
        900 para 1546px). E com só `overflow-y: auto` o x vira `auto`: abrindo
        o menu, um rótulo mais largo que o trilho acendia uma barra de rolagem
        lateral por 50ms."""
        bloco = re.search(r"\n\.sidebar nav \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("position: relative", bloco.group(1))
        self.assertIn("overflow-y: auto", bloco.group(1))
        self.assertIn("overflow-x: hidden", bloco.group(1))

    def test_marca_continua_clicavel_no_trilho(self):
        """Os dois logotipos saíram do fluxo para o topo não saltar; sem tamanho
        explícito, a <a> da marca fica com 0px — o símbolo aparece e o link para
        a Visão geral some. No trilho o link é a área acima do botão de expandir
        (altura pelos tokens: topo menos o recuo e o alvo do botão), e o símbolo
        mora DENTRO dele."""
        bloco = re.search(r"\n\s*\.app\.recolhida \.marca \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("width: 100%", bloco.group(1))
        self.assertIn("height: calc(var(--sidebar-topo-h) - .7rem - var(--alvo) - .5rem)", bloco.group(1))
        self.assertRegex(self.base, r'class="marca">[\s\S]{0,400}class="marca-icone"[\s\S]{0,40}</a>')

    def test_trilho_so_existe_no_desktop(self):
        """Toda regra do trilho (`.recolhida`) mora no `@media (width > 820px)`.
        Fora dele, a gaveta do celular herdava o trilho e tinha de repor
        propriedade por propriedade — e no estado PADRÃO (recolhido) sobravam o
        logotipo cortado a 44px de altura e a cápsula do MFA sem forma."""
        from apps.nucleo.css_publico import analisar, dividir_seletores

        soltas = []

        def andar(itens, media):
            for item in itens:
                if item["tipo"] == "regra":
                    for sel in dividir_seletores(item["prelude"]):
                        if ".recolhida" in sel and media != "@media (width > 820px)":
                            soltas.append(f"{media or 'fora de @media'} → {sel}")
                elif item["tipo"] == "at-bloco" and item["filhos"] is not None:
                    andar(item["filhos"], re.sub(r"\s+", " ", item["prelude"]))

        andar(analisar(self.css), "")
        self.assertEqual(soltas, [], "regra do trilho que vale também na gaveta")

    # ── O trilho é o menu aberto, recortado ─────────────────────────────
    # Medido quadro a quadro (de 20 em 20ms, pausando a transição): abrindo,
    # a cápsula "MFA off" saía 75px por cima da página, os rótulos 21px fora
    # das pílulas e a <nav> acendia barra lateral; recolhendo, os ícones
    # pulavam para o meio e voltavam, e o 34º item subia 313px.

    def _regras_do_trilho(self):
        from apps.nucleo.css_publico import analisar, dividir_seletores

        regras = []

        def andar(itens):
            for item in itens:
                if item["tipo"] == "regra":
                    if any(".recolhida" in sel for sel in dividir_seletores(item["prelude"])):
                        regras.append((re.sub(r"\s+", " ", item["prelude"]), item["corpo"]))
                elif item["tipo"] == "at-bloco" and item["filhos"] is not None:
                    andar(item["filhos"])

        andar(analisar(self.css))
        return regras

    def test_trilho_nao_redesenha_so_esconde_e_desliza(self):
        """No trilho só pode mudar o que não reflui: opacidade, cor, giro e o
        que é posicionado (e desliza). Padding, margem, flex-direction,
        justify-content, posição, display e clip mudavam o desenho num quadro
        só — era daí que vinham os saltos."""
        proibidas = ("position", "display", "flex-direction", "justify-content",
                     "align-items", "padding", "margin", "gap", "clip-path",
                     "font-size", "overflow", "flex")
        achados = []
        regras = self._regras_do_trilho()
        self.assertTrue(regras)
        for prelude, corpo in regras:
            corpo = re.sub(r"/\*.*?\*/", "", corpo, flags=re.S).strip().strip("{}")
            for decl in corpo.split(";"):
                prop = decl.split(":")[0].strip()
                if prop and any(prop == p or prop.startswith(p + "-") for p in proibidas):
                    achados.append(f"{prelude} → {prop}")
        self.assertEqual(achados, [], "o trilho voltou a redesenhar o menu")

    def test_borda_da_sidebar_recorta_e_cada_janela_tambem(self):
        """A borda direita é a cortina: nada passa dela para cima da página. E
        cada coisa que pode encontrar outra no caminho tem a sua janela: o
        logotipo termina antes do botão de recolher; o nome e a cápsula, antes
        do Sair; o rótulo, dentro da pílula."""
        for seletor in (r"\n\.sidebar \{", r"\n\.nav-item \{", r"\n\.acao-topo \{",
                        r"\n\.marca-janela \{", r"\n\.usuario-texto \{", r"\n\.nav-titulo \{"):
            bloco = re.search(seletor + r"([^}]*)\}", self.css)
            self.assertIsNotNone(bloco, seletor)
            self.assertIn("overflow: hidden", bloco.group(1), seletor)
        self.assertRegex(self.base, r'<span class="marca-janela"><img[^>]*class="marca-full"')
        self.assertRegex(self.base,
                         r'<span class="usuario-texto">[\s\S]{0,200}usuario-nome')
        rodape = self.base.split('<div class="sidebar-rodape">', 1)[1].split('</aside>', 1)[0]
        self.assertNotIn('selo-alerta', rodape)
        self.assertNotIn('Verificação em duas etapas desativada', rodape)
        self.assertIn("{% url 'mfa_config' %}", rodape)

    def test_o_que_muda_de_lugar_desliza_com_os_tokens(self):
        """O Sair muda de lugar entre os estados e o rodapé muda de altura: os
        dois deslizam junto com a largura (mesmo token e curva), em vez de pular
        no primeiro quadro. O botão de recolher é a exceção deliberada: do canto
        (menu aberto) ao centro do trilho, embaixo do símbolo, a reta é uma
        diagonal — ele não desliza, some e surge no destino pelos mesmos tokens
        (`.menu-alternando`, posta por `alternarSidebar()`)."""
        casos = {
            r"\n\.sidebar-rodape \{": ("height var(--mov-padrao)",),
            r"\n\.sidebar-rodape button\.link \{": ("right var(--mov-padrao)",
                                                     "bottom var(--mov-padrao)"),
            r"\n\.app \{": ("grid-template-columns var(--mov-padrao)",),
        }
        for seletor, trechos in casos.items():
            bloco = re.search(seletor + r"([^}]*)\}", self.css)
            self.assertIsNotNone(bloco, seletor)
            for trecho in trechos:
                self.assertIn(trecho, bloco.group(1), seletor)
        botao = re.search(r"\n\.sidebar-toggle \{([^}]*)\}", self.css)
        self.assertIsNotNone(botao)
        for trecho in ("top var(", "right var("):
            self.assertNotIn(trecho, botao.group(1),
                             "o botão de recolher não desliza: do canto ao centro do trilho a reta é diagonal")
        self.assertIn("top: .7rem; right: .7rem;", botao.group(1))
        self.assertIn("\n.menu-alternando .sidebar-toggle { animation: botao-recolher-surge "
                      "var(--mov-padrao) var(--curva) both; }", self.css)
        self.assertRegex(self.css, r"\n@keyframes botao-recolher-surge \{ 0%, \d+% \{ opacity: 0; \} "
                                   r"100% \{ opacity: 1; \} \}")
        self.assertIn("APP.classList.add('menu-alternando')", self.base)

    def test_icones_moram_no_x_do_trilho(self):
        """Aberto, o ícone ficava a 30px; no trilho, a 35,5px — 5px de pulo a
        cada alternância. Todos agora partem do mesmo token."""
        self.assertIn("--sidebar-ico-x: calc(var(--trilho-centro) - 9.5px)", self.css)
        for seletor in (r"\n\.nav-item \{", r"\n\.acao-topo \{", r"\n\.nav-titulo \{"):
            bloco = re.search(seletor + r"([^}]*)\}", self.css)
            self.assertIsNotNone(bloco, seletor)
            self.assertIn("var(--sidebar-ico-x)", bloco.group(1), seletor)

    def test_dica_do_item_so_no_trilho(self):
        """Aberto (ou na gaveta), o nome já está escrito ao lado do ícone: o
        `title` repetiria a mesma palavra num balão. Ele só volta no trilho."""
        self.assertRegex(self.base, r"const trilho = recolhida && !GAVETA\.matches")
        self.assertIn("el.removeAttribute('title')", self.base)
        self.assertIn("GAVETA.addEventListener('change', rotularSidebar)", self.base)

    def test_botao_de_recolher_diz_o_que_vai_fazer(self):
        """O rótulo era fixo em "Recolher menu" mesmo já recolhido, e o title
        mostrava a barra invertida dobrada do template."""
        self.assertIn("rotularSidebar", self.base)
        self.assertIn("Expandir menu", self.base)
        self.assertIn('aria-controls="menu-principal"', self.base)
        self.assertNotIn("Recolher (⌘\\\\)", self.base)

    def test_gaveta_fechada_sai_da_ordem_de_tabulacao(self):
        """Fora da tela por `translateX(-100%)`, os 39 links do menu continuavam
        tabuláveis: no celular o Tab passava por todos antes do conteúdo."""
        bloco = re.search(r"\n  \.sidebar \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco, "regra da gaveta sumiu")
        self.assertIn("visibility: hidden", bloco.group(1))

    def test_gaveta_usa_os_tokens_de_movimento(self):
        """Era `.2s ease` cru: ignorava `prefers-reduced-motion`."""
        bloco = re.search(r"\n  \.sidebar \{([^}]*)\}", self.css)
        self.assertIn("var(--mov-padrao)", bloco.group(1))
        self.assertNotIn(".2s ease", bloco.group(1))

    def test_gaveta_aberta_prende_o_foco_e_trava_a_rolagem(self):
        self.assertRegex(self.base, r"caixaAberta[\s\S]{0,500}sidebar-aberta")
        self.assertIn("sem-rolagem", self.base)
        self.assertIn("body.sem-rolagem { overflow: hidden; }", self.css)

    def test_alvo_de_44px_tambem_no_menu(self):
        """O menu é o controle mais tocado no celular e tinha os alvos mais
        apertados do sistema (item de 37px)."""
        blocos = re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                            self.css)
        self.assertTrue(blocos)
        self.assertTrue(any(".sidebar .nav-item" in b for b in blocos),
                        "item do menu sem alvo de 44px no dedo")


class DentroDoContainerTests(TestCase):
    """O que vaza e o que é cortado calado.

    Cada caso nasceu de uma medida no navegador a 320px: caixa de filho maior
    que a do pai, ou conteúdo maior que a caixa com `overflow:hidden` e sem
    reticências — o pior dos dois, porque não avisa que falta coisa.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_grade_elastica_cede_em_tela_estreita(self):
        """`minmax(300px, 1fr)` não encolhe: num celular de 320px a coluna mede
        282px e o cartão vaza 18px. A faixa mínima tem de ser `min(Npx, 100%)`
        sempre que N passar da largura útil do celular."""
        duras = re.findall(r"minmax\((\d+)px,", self.css)
        self.assertEqual([n for n in duras if int(n) > 260], [],
                         "faixa mínima maior que a coluna do celular sem min()")

    def test_porta_do_corredor_nao_cresce_pela_proporcao(self):
        """`aspect-ratio` vale nos dois sentidos: com o `min-height` mandando na
        altura, a LARGURA voltava pela proporção e a porta vazava da coluna."""
        bloco = re.search(r"\n\.porta \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("width: 100%", bloco.group(1))

    def test_coluna_do_quarto_no_mapa_poe_reticencias(self):
        """Nome de ala longo saía da célula e levava a TABELA junto: 26px que a
        .mapa-rolagem não alcançava."""
        for regra in (r"\n\.mapa-uh \{", r"\n\.mapa-meses th \{"):
            bloco = re.search(regra + r"([^}]*)\}", self.css)
            self.assertIsNotNone(bloco, regra)
            self.assertIn("text-overflow: ellipsis", bloco.group(1), regra)

    def test_painel_lateral_empilha_pelo_espaco_e_nao_pela_janela(self):
        """A largura que sobra depende de o menu estar aberto ou recolhido, e
        `@media` só enxerga a JANELA: a 821px com o menu aberto a coluna lateral
        virava 154px e a ficha inteira estourava 121px para fora dela. Quem
        decide tem de ser o espaço — por isso flex-wrap, não grid + breakpoint."""
        for regra in (r"\n\.colunas-2-1 \{([^}]*)\}", r"\n\.ficha-cols \{([^}]*)\}"):
            bloco = re.search(regra, self.css)
            self.assertIsNotNone(bloco, regra)
            self.assertIn("flex-wrap: wrap", bloco.group(1), regra)
            self.assertNotIn("grid-template-columns", bloco.group(1), regra)
        # O `min-width` dessas colunas é o que dispara a quebra — e tem de ceder
        # no celular: em px puro ele empurrava a página 100px para o lado em
        # sete telas a 320px.
        duros = re.findall(r"\.(?:colunas-2-1|ficha-cols) > :(?:first|last)-child \{[^}]*"
                           r"min-width: (\d+px)", self.css)
        self.assertEqual(duros, [], "mínimo em px não cede em tela estreita")

    def test_tabela_quebra_na_palavra_e_nao_na_letra(self):
        """`overflow-wrap: anywhere` entra no cálculo da largura MÍNIMA da
        coluna: o navegador espremia a coluna até caber uma letra e saía
        quebrando tudo ("Revisã/o do/ar-condi/ciona/do")."""
        bloco = re.search(r"\n\.tabela td \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("overflow-wrap: break-word", bloco.group(1))

    def test_periodo_personalizado_empilha_no_celular(self):
        """Os dois campos de data pedem 316px e a coluna do celular dá 164: com
        `overflow:hidden` no pill, a segunda data não existia."""
        self.assertRegex(
            self.css,
            r"@media \(max-width: 560px\) \{\s*\n\s*\.filtro-periodo \{[^}]*flex-direction: column")
        # O @media vem DEPOIS da regra do `.sep`: mesma especificidade, quem vem
        # depois vence — antes dela, o `padding` do celular nunca valia.
        sep = self.css.index("\n.filtro-periodo .sep {")
        celular = self.css.index("@media (max-width: 560px) {\n  .filtro-periodo {")
        self.assertLess(sep, celular, "o @media do período ficou antes da regra que ele ajusta")

    def test_colunas_do_corredor_olham_a_largura_do_corredor(self):
        """A 821px com o menu aberto o corredor mede ~486px: em seis colunas as
        portas ficavam com 70px, as 24 cortavam data e saldo ("R$ 2.6…") e o
        selo PCD subia em cima da situação. O número de colunas tem de olhar o
        corredor (container query), não só a janela — e a regra vem ANTES dos
        @media do celular, que seguem mandando abaixo de 720px."""
        heroi = re.search(r"\n\.corredor-hero \{([^}]*)\}", self.css)
        self.assertIsNotNone(heroi)
        self.assertIn("container-type: inline-size", heroi.group(1))
        cont = self.css.index("@container (max-width: 540px) {\n  .corredor { grid-template-columns: repeat(4,")
        cel = self.css.index("@media (max-width: 720px) {", self.css.index("\n.corredor {"))
        self.assertLess(cont, cel)

    def test_tabela_de_pessoas_esconde_colunas_pela_largura_da_tabela(self):
        """A 821px com o menu aberto a tabela de Pessoas tinha 486px — menos que
        no celular — e as seis colunas não cabiam: cabeçalhos uns por cima dos
        outros, "SITUAÇÃO" cortado 23px pela própria tabela e "Ati/va" em duas
        linhas. Quem decide é a largura da tabela (container query), e a coluna
        Situação precisa de 12% para o cabeçalho caber a partir de 610px."""
        self.assertIn(".tabela-rol:has(> .tabela-pessoas) { container-type: inline-size; }",
                      self.css)
        bloco = re.search(r"@container \(max-width: 609px\) \{([\s\S]*?)\n\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn(".tabela-pessoas .c-sit { display: none; }", bloco.group(1))
        sit = re.search(r"\.tabela-pessoas col\.c-sit \{ width: (\d+)%; \}", self.css)
        self.assertIsNotNone(sit)
        self.assertGreaterEqual(int(sit.group(1)), 12)

    def test_quadro_com_tabela_simples_rola_em_qualquer_largura(self):
        """A 821px com o menu aberto, a lista de Páginas (tabela simples num
        `.quadro`) pedia 516px numa coluna de 486 e o `overflow:hidden` do
        quadro cortava calado a coluna das ações. O `@media (max-width: 820px)`
        que fazia o quadro rolar só enxerga a janela, não o menu aberto."""
        self.assertIn(
            ".quadro:has(> table:not(.tabela)) { overflow-x: auto; overflow-y: hidden; }",
            self.css)

    def test_enviar_do_whatsapp_nao_estica_no_desktop(self):
        """Com `flex: 1 1 auto` o botão dividia a sobra da linha com o campo: no
        desktop o "Enviar" ficava com 363px e o campo de texto perdia 280px. Ele
        só ocupa a linha inteira no celular, quando já desceu sozinho."""
        tpl = (Path(settings.BASE_DIR) / "templates" / "comercial" / "oportunidade.html"
               ).read_text(encoding="utf-8")
        self.assertIn(".wpp-form .botao-primario{flex:none;margin-left:auto}", tpl)
        celular = re.search(r"@media \(max-width: 640px\)\{([\s\S]*?)\n  \}", tpl)
        self.assertIsNotNone(celular)
        self.assertIn(".wpp-form .botao-primario{min-height:44px;flex:1 1 auto}", celular.group(1))


class FlutuantesTests(TestCase):
    """Sobreposições: lista de combo, gaveta, bottom sheet.

    Duas regras: a caixa que flutua tem de caber na TELA (não no pai), e o
    movimento sai dos tokens — senão não some sob `prefers-reduced-motion`.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

    def test_lista_do_combo_cabe_na_tela(self):
        """Com o campo perto do fim da tela, a lista abria 31px para FORA —
        e ela chega a 320px de altura."""
        bloco = re.search(r"\n\.combo-lista \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("max-height: min(", bloco.group(1))
        self.assertIn(".combo.combo-acima .combo-lista", self.css)
        self.assertIn("posicionar()", self.base)

    def test_ficha_do_marketing_reutiliza_modal_sem_reanimar_ao_salvar(self):
        """A animação pertence à abertura do modal, não a cada resposta de salvar."""
        self.assertNotRegex(self.css, r"\.fx-gaveta\s*\{[^}]*animation:")
        quadro = (Path(settings.BASE_DIR) / "templates" / "marketing" / "quadro.html").read_text(encoding="utf-8")
        self.assertIn('hx-target="#modal-conteudo"', quadro)

    def test_mover_no_funil_usa_modal_compartilhado(self):
        funil = (Path(settings.BASE_DIR) / "templates" / "comercial" / "funil.html"
                 ).read_text(encoding="utf-8")
        self.assertNotIn("cubic-bezier(.22,.61,.36,1)", funil)
        self.assertIn('hx-target="#modal-conteudo"', funil)
        self.assertNotIn('class="sheet-overlay"', funil)

    def test_alvo_de_44px_nas_telas_fora_da_casca(self):
        """Portal, pagamento e login não vivem dentro de `.conteudo`: a regra de
        44px do CRM não os alcançava, e são as que só abrem no celular."""
        blocos = re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                            self.css)
        corpo = "\n".join(blocos)
        for sel in (".pt-wrap input", ".pay input", ".voltar-site"):
            self.assertIn(sel, corpo, sel)

    def test_o_modal_tambem_fica_fora_do_conteudo(self):
        """O `.modal-caixa` é filho do `.modal-overlay`, que é `position: fixed`
        fora do `.conteudo` — e ali está a ação mais repetida da recepção. Medido
        a 390px, a janela de "Nova reserva" saía com campos de 40 a 42px e os
        rótulos de "Usa o sofá-cama"/"Cobrar ISS" com 19px de altura.

        A caixa de marcar fica FORA da regra de altura de propósito: com largura
        e altura fixas, o `min-height` esticaria o desenho em vez da área de
        toque — quem aciona ali é o rótulo."""
        corpo = "\n".join(
            re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                       self.css))
        campos = re.search(
            r"(\.modal-caixa input:not\(\[type=\"checkbox\"\]\):not\(\[type=\"radio\"\]\),"
            r"[^}]*\})", corpo)
        self.assertIsNotNone(campos, "o campo do modal ficou sem a regra de toque")
        self.assertIn("min-height: 44px", campos.group(1))
        self.assertIn(".modal-caixa .check-inline", corpo,
                      "o rótulo da caixa de marcar do modal ficou sem alvo")
        # O <summary> entrou junto quando o modal virou gaveta encostada embaixo:
        # o "Mais opções" da nova reserva media 39px, e a regra do `.conteudo`
        # não alcança quem mora fora dele.
        self.assertIn(".modal-caixa summary", corpo,
                      "o <summary> da gaveta ficou sem alvo de toque")


class MenuDoSiteTests(TestCase):
    """O menu do celular do site tinha os mesmos buracos do menu do CRM: fechado
    seguia tabulável, aberto não prendia o foco e o botão não dizia o estado."""

    def setUp(self):
        base = Path(settings.BASE_DIR) / "apps" / "site" / "static" / "site"
        self.css = (base / "css" / "animations.css").read_text(encoding="utf-8")
        self.js = (base / "js" / "main.js").read_text(encoding="utf-8")
        self.header = (Path(settings.BASE_DIR) / "apps" / "site" / "templates" / "site"
                       / "partials" / "header.html").read_text(encoding="utf-8")

    def test_menu_fechado_sai_da_tabulacao(self):
        bloco = re.search(r"\n\.mobile-menu \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("visibility: hidden", bloco.group(1))

    def test_menu_aberto_e_dialogo(self):
        self.assertIn("'Escape'", self.js)
        self.assertIn("e.preventDefault(); ultimo.focus();", self.js)
        self.assertIn("aria-expanded", self.js)

    def test_botao_do_menu_tem_alvo_de_toque(self):
        self.assertRegex(self.header, r'id="menuBtn"[^>]*class="[^"]*\bp-3\b')
        self.assertIn('aria-controls="mobileMenu"', self.header)

    def test_movimento_do_menu_cede_a_quem_pede_menos(self):
        self.assertRegex(self.css,
                         r"@media \(prefers-reduced-motion: reduce\) \{[^}]*\.mobile-menu")


class PortalDoHospedeTests(TestCase):
    """É a primeira experiência digital do hóspede — e era a tela mais fraca.

    Um formulário de quase 4.000 px com ~40 campos, grade de atalhos de três
    colunas com um item, campo sem rótulo entre dois botões e o saldo DEVEDOR
    em verde (o mesmo valor saía vermelho no CRM).
    """

    def setUp(self):
        self.raiz = Path(settings.BASE_DIR) / "templates" / "portal"
        self.base = (self.raiz / "base.html").read_text(encoding="utf-8")
        self.home = (self.raiz / "home.html").read_text(encoding="utf-8")

    def test_saldo_devedor_nao_fica_verde(self):
        self.assertIn(".pt-saldo.devendo", self.base)
        self.assertIn("devendo", self.home)

    def test_grade_de_atalhos_e_elastica(self):
        self.assertIn("repeat(auto-fit, minmax(96px, 1fr))", self.base)
        self.assertNotIn("grid-template-columns: repeat(3, 1fr)", self.base)

    def test_campo_de_manutencao_tem_rotulo_e_foco(self):
        self.assertIn('for="pt-descricao"', self.home)
        self.assertIn(".pt-wrap input:focus", self.base)

    def test_sem_emoji_nos_titulos(self):
        """O resto do produto usa SVG; emoji muda de desenho a cada aparelho."""
        import unicodedata
        achados = [c for c in self.home
                   if unicodedata.category(c) == "So" or 0x1F300 <= ord(c) <= 0x1FAFF]
        self.assertEqual(achados, [])

    def test_fnrh_e_uma_ficha_por_vez(self):
        fichas = (Path(settings.BASE_DIR) / "templates" / "reservas" / "partials"
                  / "fnrh_fichas.html").read_text(encoding="utf-8")
        self.assertIn('<details class="fnrh-ficha" name="fnrh"', fichas)
        self.assertIn("<summary", fichas)

    def test_numeracao_do_acompanhante_bate_com_o_circulo(self):
        """O círculo dizia \"2\" e o título, \"Acompanhante 1\"."""
        fichas = (Path(settings.BASE_DIR) / "templates" / "reservas" / "partials"
                  / "fnrh_fichas.html").read_text(encoding="utf-8")
        self.assertNotIn("{{ forloop.counter }}", fichas)
        self.assertIn("Acompanhante {{ forloop.counter0 }}", fichas)


class UmJeitoSoTests(TestCase):
    """Um componente por papel, um formatador por tipo de dado."""

    def setUp(self):
        bruto = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.css = bruto
        # O comentário que explica a limpeza cita os nomes removidos.
        self.css_sem_comentario = re.sub(r"/\*.*?\*/", "", bruto, flags=re.S)
        self.raizes = [Path(settings.BASE_DIR) / "templates"]

    def test_dinheiro_sempre_pelo_filtro_unico(self):
        """`R$ {{ x }}` imprime o Decimal cru — a tela do Comercial mostrava
        `R$ 690000,00`. O único lugar com o prefixo escrito à mão é o e-mail de
        proposta, cujas variáveis já chegam formatadas do Python."""
        sobras = []
        for raiz in self.raizes:
            for p in raiz.rglob("*.html"):
                if p.match("comercial/email/proposta.html"):
                    continue
                if re.search(r"R\$\s*\{\{", p.read_text(encoding="utf-8")):
                    sobras.append(str(p.relative_to(settings.BASE_DIR)))
        self.assertEqual(sobras, [])

    def test_sem_duplo_rs(self):
        """`R$ {{ x|intcomma_brl }}` sairia como "R$ R$ 1.234,56"."""
        sobras = []
        for raiz in self.raizes:
            for p in raiz.rglob("*.html"):
                if re.search(r"R\$\s*\{\{[^}]*intcomma_brl", p.read_text(encoding="utf-8")):
                    sobras.append(str(p.relative_to(settings.BASE_DIR)))
        self.assertEqual(sobras, [])

    def test_impressao_esconde_as_classes_que_existem(self):
        """O @media print escondia `.app-sidebar`/`.app-topbar`, que não
        existem: imprimir um relatório saía com o menu na folha."""
        rel = (Path(settings.BASE_DIR) / "templates" / "relatorios"
               / "relatorio.html").read_text(encoding="utf-8")
        bloco = re.search(r'<style media="print">(.*?)</style>', rel, re.S)
        self.assertIsNotNone(bloco)
        for classe in (".sidebar", ".topbar", ".conteudo"):
            self.assertIn(classe, bloco.group(1), classe)
        self.assertNotIn(".app-sidebar", bloco.group(1))

    def test_css_do_mapa_de_portas_antigo_sumiu(self):
        """~60 linhas que nenhum template usava desde que o corredor virou
        cartões."""
        for morta in (".quartos-grid", ".quarto-porta", ".porta-circulo",
                      ".porta-badge", ".porta-legenda", ".porta-dot", ".porta-ico"):
            self.assertNotIn(morta, self.css_sem_comentario, morta)


class EstiloForaDoAtributoTests(TestCase):
    """O desenho mora no CSS, não no `style=` da tag.

    As telas do Marketing e do Comercial nasceram como transcrição de protótipo:
    439 `style="…"` estáticos, a mesma cápsula escrita à mão em quatro arquivos e
    nenhuma chance de reuso ou de tema. Agora cada papel tem classe; o atributo só
    fica onde o valor é DADO (largura em %, posição calculada, cor vinda do banco)
    ou onde o estilo é a única linguagem possível (corpo de e-mail).
    """

    # Corpo de e-mail precisa de estilo inline: cliente de e-mail ignora CSS externo.
    EMAILS = {"comercial/email/proposta.html", "comercial/email/campanha.html",
              "reservas/email/kit_contingencia.html"}

    def setUp(self):
        self.raiz = Path(settings.BASE_DIR) / "templates"

    def _estaticos(self, caminho):
        """style="…" sem variável de template dentro (o dinâmico é dado, não estilo).
        O `:style` do Alpine é ligação dinâmica e fica de fora."""
        texto = caminho.read_text(encoding="utf-8")
        return [v for v in re.findall(r'(?<![:\w-])style="([^"]*)"', texto)
                if "{{" not in v and "{%" not in v]

    def test_marketing_e_comercial_sem_style_estatico(self):
        sobras = []
        for pasta in ("marketing", "comercial"):
            for p in (self.raiz / pasta).rglob("*.html"):
                rel = p.relative_to(self.raiz).as_posix()
                if rel in self.EMAILS:
                    continue
                for valor in self._estaticos(p):
                    sobras.append(f"{rel}: {valor[:60]}")
        self.assertEqual(sobras, [])

    def test_nenhuma_tela_com_style_estatico(self):
        """Valeu para o sistema todo: o CRM, o portal e o pagamento. Sobra só o
        `display:none` que o JS liga e desliga (é estado, não desenho)."""
        sobras = []
        for p in self.raiz.rglob("*.html"):
            rel = p.relative_to(self.raiz).as_posix()
            if rel in self.EMAILS or rel.startswith("site/"):  # o site é Tailwind, à parte
                continue
            for valor in self._estaticos(p):
                if valor.replace(" ", "").rstrip(";") != "display:none":
                    sobras.append(f"{rel}: {valor[:60]}")
        self.assertEqual(sobras, [])

    def test_funil_sem_capsula_de_enfeite(self):
        """`.mchip` eram quatro cápsulas por cartão (origem, reativação, campanha,
        temperatura). Dado virou `.rotulo-dado`; estado, `.selo`."""
        funil = (self.raiz / "comercial" / "funil.html").read_text(encoding="utf-8")
        self.assertNotIn("mchip", funil)
        self.assertIn("rotulo-dado", funil)
        self.assertIn("selo temp-", funil)

    def test_fchip_morto_nao_volta(self):
        """Classe sem nenhum template usando — saiu junto com as cápsulas."""
        self.assertNotIn(".fchip", CSS.read_text(encoding="utf-8"))


class CssDasTelasPublicasTests(TestCase):
    """O portal do hóspede e a página de pagamento abrem no celular do hóspede, muitas
    vezes no 4G, e baixavam o app.css inteiro (52 KB comprimidos, o CRM todo) para usar
    menos de um quinto dele. Agora carregam o base.css: o recorte que usam, GERADO do
    app.css (`manage.py gerar_base_css`). O CRM segue só com o app.css."""

    def setUp(self):
        self.raiz = Path(settings.BASE_DIR) / "templates"

    def test_telas_publicas_carregam_o_recorte_e_nao_o_crm_inteiro(self):
        for nome in ("portal/base.html", "pagamentos/pagar.html"):
            html = (self.raiz / nome).read_text(encoding="utf-8")
            self.assertIn("css/base.css", html, nome)
            self.assertNotIn("css/app.css", html, nome)

    def test_crm_segue_com_o_app_css(self):
        html = (self.raiz / "base.html").read_text(encoding="utf-8")
        self.assertIn("css/app.css", html)
        self.assertNotIn("css/base.css", html)

    def test_base_css_em_dia_com_o_app_css(self):
        from apps.nucleo import css_publico

        no_disco = css_publico.caminho_base_css().read_text(encoding="utf-8")
        self.assertEqual(no_disco.splitlines(), css_publico.gerar_do_app().splitlines(),
                         "base.css desatualizado: rode manage.py gerar_base_css")

    def test_toda_classe_das_telas_publicas_tem_estilo(self):
        """Classe nova numa tela pública, com regra no app.css, tem de entrar no manifesto
        (apps/nucleo/css_publico.txt) — senão aquele estado sai sem estilo para o hóspede."""
        from apps.nucleo import css_publico

        self.assertEqual(css_publico.seletores_sem_cobertura(), [])

    def test_recorte_leva_fontes_tokens_e_movimento(self):
        from apps.nucleo import css_publico

        base = css_publico.caminho_base_css().read_text(encoding="utf-8")
        self.assertIn("@font-face", base)
        self.assertIn("--lampiao:", base)
        self.assertIn("prefers-reduced-motion", base)  # os tokens de movimento vão a 1 ms
        self.assertLess(len(base.encode("utf-8")), 40_000)  # passou disto, o CRM vazou

    def test_gerador_mantem_a_ordem_e_leva_so_o_citado(self):
        from apps.nucleo import css_publico

        css = (
            "@font-face { font-family: X; src: url(x.woff2); }"
            ".a, .b { color: red; }"
            ".c { animation: piscar 1s; }"
            "@keyframes piscar { to { opacity: 0; } }"
            "@keyframes outro { to { opacity: 1; } }"
            "@media (max-width: 600px) { .a { color: blue; } .z { color: green; } }"
        )
        saida = css_publico.gerar(css, {".b", ".c", "@media (max-width: 600px) ‖ .a"})
        self.assertIn("@font-face", saida)
        self.assertIn(".b {", saida)
        self.assertNotIn(".a, .b", saida)
        self.assertIn("@keyframes piscar", saida)
        self.assertNotIn("@keyframes outro", saida)
        self.assertIn("@media (max-width: 600px) {", saida)
        self.assertNotIn(".z", saida)
        self.assertLess(saida.index(".b {"), saida.index(".c {"))


class CorSoPorTokenTests(TestCase):
    """O `<style>` das telas do CRM pinta só com os tokens do app.css. A tela do lead
    tinha 33 cores escritas à mão (hex, rgba e "fallbacks" de tokens que não existem,
    como `--info-suave` — a casa usa `--info-bg`); mudar a paleta não chegava lá.

    Fora da regra, de propósito: e-mails (cor inline é o que o cliente de e-mail lê),
    o site e as páginas públicas de captação (paleta própria, sem o app.css), o aviso
    de cookies (também serve o site: precisa do fallback) e o branco puro atrás do QR
    do Pix (contraste máximo para o leitor do banco)."""

    FORA = {"comercial/captacao_publica.html", "comercial/captacao_blueprint.html",
            "lp/privacidade.html", "componentes/consentimento.html"}
    PERMITIDO = {"pagamentos/pagar.html": ["#fff"]}

    def test_style_das_telas_sem_cor_escrita_a_mao(self):
        raiz = Path(settings.BASE_DIR) / "templates"
        achados = []
        for arq in sorted(raiz.rglob("*.html")):
            rel = arq.relative_to(raiz).as_posix()
            if rel in {"comercial/email/proposta.html", "comercial/email/campanha.html", "reservas/email/kit_contingencia.html"} or rel.startswith("site/") or rel in self.FORA:
                continue
            css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", arq.read_text(encoding="utf-8"), re.S))
            literais = re.findall(r"#[0-9A-Fa-f]{3,8}\b|rgba?\([^)]*\)", css)
            sobra = [c for c in literais if c not in self.PERMITIDO.get(rel, [])]
            if sobra:
                achados.append(f"{rel}: {sobra[:4]}")
        self.assertEqual(achados, [], "cor escrita à mão no <style> de tela do CRM")

class SemEmojiNoCrmTests(TestCase):
    """Tela do CRM não usa emoji. Eram 73 em 22 telas — rótulo de cartão ("⏱ Tempo de
    casa"), filtro ("🌅 Vista lago"), estado vazio ("Nada pendente. 🎉"), status
    ("🟢 janela 24h aberta") e até botão ("📎", "🎤"). Emoji muda de desenho em cada
    aparelho e briga com os ícones da casa; o que era decorativo saiu, status ficou na
    cor/selo, e botão de ícone é SVG (`.ico`).

    Fora, de propósito: e-mails, o site e as páginas públicas de captação (têm
    linguagem de campanha própria). Glifos de texto (✓ ✕ ★ setas) seguem valendo."""

    FORA = {"comercial/captacao_publica.html", "comercial/captacao_blueprint.html"}
    # pictogramas (U+1F300…), símbolos (☀…➿), estrela e os de mídia/relógio (⏩…⏺).
    EMOJI = re.compile("[\\U0001F300-\\U0001FAFF\\u2600-\\u27BF\\u2B50\\u23E9-\\u23FA]\\uFE0F?")
    GLIFOS = {"✓", "✕", "★", "✔"}   # ✓ ✕ ★ ✔

    def test_telas_do_crm_sem_emoji(self):
        raiz = Path(settings.BASE_DIR) / "templates"
        achados = []
        for arq in sorted(raiz.rglob("*.html")):
            rel = arq.relative_to(raiz).as_posix()
            if rel.startswith(("site/", "lp/")) or rel in {"comercial/email/proposta.html", "comercial/email/campanha.html", "reservas/email/kit_contingencia.html"} or rel in self.FORA:
                continue
            emojis = [e for e in self.EMOJI.findall(arq.read_text(encoding="utf-8"))
                      if e not in self.GLIFOS]
            if emojis:
                achados.append(f"{rel}: {''.join(emojis[:6])}")
        self.assertEqual(achados, [], "emoji em tela do CRM")


class CupomTermicoTests(TestCase):
    """O cupom de 80 mm (componentes/cupom.html) tem página própria. Sem `size` na
    `@page cupom`, valeria o A4 do `@page` geral (o do kit de contingência) e o driver da
    térmica encolheria a folha A4 inteira para caber na bobina — cupom ilegível."""

    def test_pagina_do_cupom_tem_tamanho_e_margem_proprios(self):
        regra = re.search(r"@page cupom\s*\{([^}]*)\}", CSS.read_text(encoding="utf-8"))
        self.assertIsNotNone(regra)
        self.assertIn("size: 80mm", regra.group(1))
        self.assertIn("margin: 0", regra.group(1))

    def test_altura_da_pagina_vem_do_proprio_cupom(self):
        modelo = (Path(settings.BASE_DIR) / "templates" / "componentes" / "cupom.html")
        texto = modelo.read_text(encoding="utf-8")
        self.assertIn("'@page cupom { size: 80mm ' + mm + 'mm; margin: 0; }'", texto)
        self.assertIn("addEventListener('beforeprint', ajustar)", texto)



class DicasTests(TestCase):
    """As caixinhas de hover eram um ::after dentro de cada elemento: centradas na
    caixa inteira (longe do que se via numa célula larga), cortadas por contêiner com
    overflow (a tabela do mapa, a coluna de Pessoas) e soltas na borda da tela; o
    Marketing e a ficha tinham motores próprios, e o menu recolhido usava o `title`
    do navegador. Agora é um balão só (static/js/dicas.js), fixo por cima de tudo."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")

    def test_motor_unico_carregado_no_base(self):
        self.assertIn("js/dicas.js", self.base)
        motor = (Path(settings.BASE_DIR) / "static" / "js" / "dicas.js").read_text(encoding="utf-8")
        self.assertIn("dica-flutuante", motor)
        bloco = re.search(r"\n\.dica-flutuante \{([^}]*)\}", self.css)
        self.assertIsNotNone(bloco)
        self.assertIn("position: fixed", bloco.group(1))

    def test_nenhuma_dica_desenhada_dentro_do_elemento(self):
        self.assertNotIn(".dica::after", self.css)
        self.assertNotIn(".porta.dica::after", self.css)
        self.assertNotIn(".mk-dica", self.css)
        self.assertNotIn("#fx-tip", self.css)
        marketing = Path(settings.BASE_DIR) / "templates" / "marketing"
        for arq in ("_dica.html", "_ficha_drawer.html"):
            texto = (marketing / arq).read_text(encoding="utf-8")
            self.assertNotIn("addEventListener", texto, arq)
        self.assertNotIn("data-tip=", (marketing / "_ficha_drawer.html").read_text(encoding="utf-8"))

    def test_menu_recolhido_usa_o_balao_da_casa(self):
        """O `title` do template fica (vale sem JavaScript); com JS ele vira data-dica
        à direita do ícone, na hora."""
        funcao = self.base[self.base.index("function rotularSidebar()"):]
        funcao = funcao[:funcao.index("rotularSidebar();")]
        self.assertIn("el.removeAttribute('title')", funcao)
        self.assertIn("el.setAttribute('data-dica-lado', 'direita')", funcao)


class TelaGrandeTests(TestCase):
    """Num monitor grande o conteúdo esticava até a borda: a 2560 px o detalhe da
    reserva tinha 2.300 px de largura, com o valor do financeiro lá na ponta. O
    conteúdo para em --conteudo-max e centra; o mapa de reservas sai do limite."""

    def test_conteudo_tem_limite_e_centra(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertRegex(css, r"--conteudo-max: \d+px;")
        self.assertIn(".conteudo { max-width: var(--conteudo-max); margin-inline: auto; }", css)
        self.assertIn(".conteudo.conteudo-largo { max-width: none; }", css)

    def test_mapa_de_reservas_usa_a_largura_toda(self):
        mapa = (Path(settings.BASE_DIR) / "templates" / "reservas" / "mapa.html").read_text(encoding="utf-8")
        self.assertIn("conteudo-largo", mapa)


class ComentarioQueNaoVazaTests(TestCase):
    """`{# … #}` do Django é de UMA LINHA: o lexer casa `{#.*?#}` SEM re.DOTALL.
    Escrito em duas linhas ele não é comentário — o texto cru aparece na tela do
    usuário. Aconteceu num comentário de três linhas no PDV da Loja, que saiu
    impresso em cima do seletor de cliente. Comentário longo = `{% comment %}`."""

    def test_nenhum_comentario_de_uma_linha_atravessa_a_quebra(self):
        raiz = Path(settings.BASE_DIR)
        vazando = []
        for arq in sorted(raiz.rglob("*.html")):
            if "node_modules" in arq.parts or ".venv" in arq.parts:
                continue
            texto = arq.read_text(encoding="utf-8")
            for achado in re.finditer(r"\{#", texto):
                resto = texto[achado.start():]
                fim = resto.find("#}")
                if fim != -1 and "\n" in resto[:fim]:
                    linha = texto[:achado.start()].count("\n") + 1
                    vazando.append(f"{arq.relative_to(raiz).as_posix()}:{linha}")
        self.assertEqual(vazando, [], "comentário {# #} em várias linhas vaza na tela")


class AlvoDeToqueTests(TestCase):
    """Controle pequeno que vive DENTRO de outra coisa (um chip, uma célula) não
    aparecia na regra geral de 44px, e era onde o dedo mais errava: 56 alvos de
    14–16px só na grade da Escala, medidos em 390×844 com toque emulado.

    O contrato é a receita, não o número solto: a CAIXA DE TOQUE cresce e o
    DESENHO fica. O "+" da hora extra é o caso-limite — 44px de caixa com o
    círculo de 16px pintado só no conteúdo (`background-clip`)."""

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.coarse = "\n".join(
            re.findall(r"@media \(pointer: coarse\), \(max-width: 820px\) \{([\s\S]*?)\n\}",
                       self.css))

    def test_controles_pequenos_entram_na_regra_de_toque(self):
        for sel in (".escala-chip", ".chip-x", ".he-selo .he-x", ".pdv-seg a",
                    ".lb-btn-ghost", ".mk-pil-acao", "a.est-produto-nome",
                    # botões do kit da ficha de campanha (Marketing) e o "×" dos
                    # carrinhos — Loja, Restaurante e Lavanderia usam a mesma classe
                    ".fx-chip", ".fx-btn-n", ".fx-dispensar", ".fx-x", ".mkt-btn-ghost",
                    ".pdv-x"):
            self.assertIn(sel, self.coarse, f"{sel} ficou fora do alvo de toque")

    def test_caixinha_da_etapa_cresce_a_area_sem_crescer_o_quadrado(self):
        """`.fx-chk` é um quadrado de 20px dentro de um cartão de linha: com 44px
        de lado ele dominaria a linha. A área de toque vem de um pseudo-elemento
        transparente (18px de caixa de preenchimento + 13 de cada lado = 44), e o
        desenho fica. As linhas ficam a 67px uma da outra, então as áreas de duas
        etapas vizinhas não se encostam."""
        bloco = re.search(r"\.fx-chk::before \{([^}]*)\}", self.coarse)
        self.assertIsNotNone(bloco, "a caixinha da etapa ficou sem área de toque")
        self.assertIn("inset: -13px", bloco.group(1))
        self.assertIn("position: absolute", bloco.group(1))
        # sem `position` no próprio botão o inset se mede no ancestral errado
        self.assertRegex(self.coarse, r"\.fx-chk \{[^}]*position: relative")

    def test_mais_da_hora_extra_cresce_a_caixa_sem_inchar_o_desenho(self):
        bloco = re.search(r"\.escala-chip \.he-add \{([^}]*)\}", self.coarse)
        self.assertIsNotNone(bloco, "o '+' da escala saiu da regra de toque")
        corpo = bloco.group(1)
        self.assertIn("width: 44px", corpo)
        self.assertIn("padding", corpo)
        self.assertIn("background-clip: content-box", corpo,
                      "sem background-clip o círculo de 16px vira uma bola de 44px")

    def test_botao_de_um_simbolo_so_tem_largura_de_alvo(self):
        """Altura já vinha da regra de cima; o '‹' da semana da Escala tinha 35px
        de largura porque `.escala-semana .botao-neutro` fixa 2.2rem e vence pela
        especificidade — por isso a exceção é repetida com o mesmo peso."""
        self.assertRegex(self.coarse, r"\.botao-mini, \.mk-pil \{ min-width: 44px; \}")
        self.assertIn(".escala-semana .botao-neutro { min-width: 44px; }", self.coarse)


class IniciaisNaBolinhaTests(TestCase):
    """A bolinha de iniciais tem 34px e o conteúdo tem de caber nela.

    `get_short_name` devolve o primeiro nome, e quem é cadastrado só com login
    não tem um. Aí o `|default:` caía no OBJETO `Usuario` — e `|slice:":2"` num
    objeto não fatia nada (o filtro engole o erro e devolve o que recebeu): a
    bolinha saía escrita "AUDITOR", vazando por cima do cartão. Foi o "ícone com
    overlap" que o dono viu no celular. O default agora é o `username`, que é
    texto, e o CSS corta o que passar."""

    def test_bolinha_mostra_duas_letras_quando_nao_ha_primeiro_nome(self):
        from django.template import engines

        from apps.nucleo.models import Usuario

        u = Usuario(username="auditor")
        self.assertEqual(u.get_short_name(), "", "o caso só existe sem primeiro nome")
        tpl = (Path(settings.BASE_DIR) / "templates" / "nucleo" / "partials"
               / "logbook_ocorrencia.html").read_text(encoding="utf-8")
        dono = SimpleNamespace(autor=u)
        achados = re.findall(r"\{\{ [ce]\.autor\.get_short_name[^}]*\}\}", tpl)
        self.assertEqual(len(achados), 2, "as duas bolinhas do recado têm de estar lá")
        for trecho in achados:
            saida = engines["django"].from_string(trecho).render({"e": dono, "c": dono})
            self.assertEqual(saida, "AU", f"{trecho} não virou iniciais")

    def test_a_bolinha_corta_o_que_passar(self):
        css = CSS.read_text(encoding="utf-8").replace("\r\n", "\n")
        bloco = re.search(r"\n\.lb-avatar, \.lb-av, \.fx-av, \.avatar \{([^}]*)\}", css)
        self.assertIsNotNone(bloco, "as bolinhas de iniciais precisam recortar o conteúdo")
        self.assertIn("overflow: hidden", bloco.group(1))
