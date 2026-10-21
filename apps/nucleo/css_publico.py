"""O CSS das telas públicas (portal do hóspede e página de pagamento): `static/css/base.css`.

Essas telas abrem no celular do hóspede e carregavam o `app.css` inteiro — o CRM todo,
52 KB comprimidos — para usar menos de um quinto dele. O `base.css` é GERADO a partir do
`app.css` com só o que elas usam: os seletores listados em `css_publico.txt`, mais as
@font-face e os @keyframes que essas regras citam.

O `app.css` continua sendo a única fonte (o CRM carrega só ele, como sempre): mudou uma
regra lá, rode `manage.py gerar_base_css`. Dois testes em `nucleo/tests_design.py`
seguram isso: o base.css tem de ser igual ao que este gerador produz, e toda classe que
uma tela pública usa e tem regra no app.css tem de estar no manifesto.
"""
import re
from pathlib import Path

from django.conf import settings

MANIFESTO = Path(__file__).with_name("css_publico.txt")
SEP_MEDIA = " ‖ "

CABECALHO = """\
/* base.css — GERADO por `manage.py gerar_base_css` a partir do app.css. Não edite aqui:
   mude o app.css (e, se uma tela pública ganhou classe nova, o apps/nucleo/css_publico.txt)
   e rode o comando. É o CSS do portal do hóspede e da página de pagamento: só o que elas
   usam do design system Lampião, em vez do CRM inteiro. */
"""


def caminho_app_css() -> Path:
    return Path(settings.BASE_DIR) / "static" / "css" / "app.css"


def caminho_base_css() -> Path:
    return Path(settings.BASE_DIR) / "static" / "css" / "base.css"


# ---------- Leitura do CSS (o mínimo: regras, comentários e at-blocos aninhados) ----------


def _pula_string(s, i):
    aspa = s[i]
    i += 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == aspa:
            return i + 1
        i += 1
    return i


def _fim_do_bloco(s, i):
    """`i` aponta para '{'; devolve o índice logo depois do '}' que fecha."""
    nivel = 0
    while i < len(s):
        c = s[i]
        if c in "\"'":
            i = _pula_string(s, i)
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = len(s) if j == -1 else j + 2
            continue
        if c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                return i + 1
        i += 1
    raise ValueError("CSS com chave sem fechar")


_COM_FILHOS = ("@media", "@supports", "@layer", "@container")


def analisar(s, ini=0, fim=None):
    """Itens do CSS em ordem: {"tipo": "regra"|"at-bloco"|"outro", "prelude", "corpo",
    "filhos"} — comentários e espaços ficam de fora."""
    fim = len(s) if fim is None else fim
    itens, i = [], ini
    while i < fim:
        if s[i].isspace():
            i += 1
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = fim if j == -1 else j + 2
            continue
        j, prof = i, 0
        while j < fim:
            c = s[j]
            if c in "\"'":
                j = _pula_string(s, j)
                continue
            if s.startswith("/*", j):
                k = s.find("*/", j + 2)
                j = fim if k == -1 else k + 2
                continue
            if c == "(":
                prof += 1
            elif c == ")":
                prof -= 1
            elif prof == 0 and c in "{;":
                break
            j += 1
        if j >= fim:
            break
        prelude = re.sub(r"/\*.*?\*/", "", s[i:j], flags=re.S).strip()
        if s[j] == ";":
            itens.append({"tipo": "outro", "prelude": prelude, "texto": s[i:j + 1]})
            i = j + 1
            continue
        k = _fim_do_bloco(s, j)
        if prelude.lower().startswith(_COM_FILHOS):
            itens.append({"tipo": "at-bloco", "prelude": prelude,
                          "filhos": analisar(s, j + 1, k - 1)})
        elif prelude.startswith("@"):
            itens.append({"tipo": "at-bloco", "prelude": prelude, "filhos": None,
                          "texto": s[i:k]})
        else:
            itens.append({"tipo": "regra", "prelude": prelude, "corpo": s[j:k]})
        i = k
    return itens


def dividir_seletores(prelude):
    """Separa a lista de seletores nas vírgulas de fora dos parênteses."""
    out, prof, ini = [], 0, 0
    for i, c in enumerate(prelude):
        if c == "(":
            prof += 1
        elif c == ")":
            prof -= 1
        elif c == "," and prof == 0:
            out.append(prelude[ini:i])
            ini = i + 1
    out.append(prelude[ini:])
    return [x.strip() for x in out if x.strip()]


def normalizar(texto):
    return re.sub(r"\s+", " ", texto).strip()


# ---------- Manifesto e geração ----------


def ler_manifesto(texto=None) -> set:
    """Chaves "seletor" ou "@media (…) ‖ seletor". Linha que começa com "# " (cerquilha e
    espaço) é comentário — seletor de id não tem espaço depois da cerquilha."""
    texto = MANIFESTO.read_text(encoding="utf-8") if texto is None else texto
    return {normalizar(x) for x in texto.splitlines()
            if x.strip() and not x.startswith("# ") and x.strip() != "#"}


def _chave(media, seletor):
    return f"{media}{SEP_MEDIA}{seletor}" if media else seletor


def gerar(app_css: str, chaves: set) -> str:
    """O base.css: as regras do app.css cujos seletores estão no manifesto, na ordem do
    app.css (a cascata entre elas fica igual), mais @font-face e os @keyframes citados."""
    itens = analisar(app_css.replace("\r\n", "\n"))  # checkout no Windows vem com CRLF
    citados = set()

    def escolher(itens, media):
        """Lista de (tipo, ...) já filtrada, para a segunda passada imprimir."""
        saida = []
        for it in itens:
            if it["tipo"] == "regra":
                sels = [normalizar(x) for x in dividir_seletores(it["prelude"])]
                usados = [x for x in sels if _chave(media, x) in chaves]
                if usados:
                    saida.append(("regra", usados, it["corpo"]))
                    for m in re.finditer(r"animation(?:-name)?\s*:\s*([^;}]+)", it["corpo"]):
                        citados.update(re.findall(r"[A-Za-z_][\w-]*", m.group(1)))
            elif it["tipo"] == "at-bloco" and it["filhos"] is not None:
                dentro = escolher(it["filhos"], normalizar(it["prelude"]))
                saida.append(("bloco", normalizar(it["prelude"]), dentro))
            elif it["tipo"] == "at-bloco":
                saida.append(("at", it["prelude"], it["texto"]))
        return saida

    escolhidos = escolher(itens, "")

    def imprimir(lista, recuo=""):
        partes = []
        for item in lista:
            if item[0] == "regra":
                _, usados, corpo = item
                partes.append(recuo + (",\n" + recuo).join(usados) + " " + corpo)
            elif item[0] == "bloco":
                dentro = imprimir(item[2], recuo + "  ")
                if dentro:
                    partes.append(f"{recuo}{item[1]} {{\n" + "\n".join(dentro) + f"\n{recuo}}}")
            else:
                _, prelude, texto = item
                nome = re.match(r"@(?:-webkit-)?keyframes\s+([\w-]+)", prelude)
                if prelude.lower().startswith("@font-face") or (nome and nome.group(1) in citados):
                    partes.append(recuo + texto)
        return partes

    return CABECALHO + "\n" + "\n\n".join(imprimir(escolhidos)) + "\n"


def gerar_do_app() -> str:
    return gerar(caminho_app_css().read_text(encoding="utf-8"), ler_manifesto())


# ---------- Cobertura: o que as telas públicas podem usar ----------

# Tudo o que monta o HTML do portal do hóspede e da página de pagamento.
TEMPLATES_PUBLICOS = (
    "portal/base.html", "portal/home.html", "portal/checkin.html", "portal/checkout.html",
    "portal/nps.html", "pagamentos/pagar.html", "pagamentos/_confianca.html",
    "reservas/partials/fnrh_fichas.html", "componentes/fontes.html",
)


def classes_das_telas_publicas():
    """(classes, prefixos): toda classe que esses templates podem pôr num elemento — no
    `class=`, no `:class` do Alpine e no `classList` do JS. `selo-pg-{{ status }}` vira o
    prefixo `selo-pg-`."""
    raiz = Path(settings.BASE_DIR) / "templates"
    classes, prefixos = {"errorlist", "helptext"}, set()  # o que o form do Django põe
    for nome in TEMPLATES_PUBLICOS:
        s = (raiz / nome).read_text(encoding="utf-8")
        for valor in re.findall(r'\bclass="([^"]*)"', s) + re.findall(r"\bclass='([^']*)'", s):
            for tok in re.split(r"\s+", re.sub(r"{%.*?%}", " ", valor)):
                if "{{" in tok:
                    if tok.split("{{")[0]:
                        prefixos.add(tok.split("{{")[0])
                elif re.match(r"^[\w-]+$", tok):
                    classes.add(tok)
        for valor in re.findall(r':class="([^"]*)"', s):
            classes.update(re.findall(r"'([\w-]+)'", valor))
        classes.update(re.findall(r"classList\.(?:add|toggle|remove)\('([\w-]+)'", s))
    return classes, prefixos


def seletores_sem_cobertura(app_css=None, chaves=None):
    """Seletores do app.css que uma tela pública pode casar (todas as classes deles
    existem nela) e que o manifesto não leva — cada um é um estado que ia sair sem estilo."""
    app_css = caminho_app_css().read_text(encoding="utf-8") if app_css is None else app_css
    chaves = ler_manifesto() if chaves is None else chaves
    classes, prefixos = classes_das_telas_publicas()

    def possivel(cl):
        return cl in classes or any(cl.startswith(p) for p in prefixos)

    faltam = []

    def andar(itens, media):
        for it in itens:
            if it["tipo"] == "regra":
                for sel in (normalizar(x) for x in dividir_seletores(it["prelude"])):
                    cls = re.findall(r"\.([\w-]+)", re.sub(r"\([^)]*\)", "", sel))
                    if cls and all(possivel(c) for c in cls) and _chave(media, sel) not in chaves:
                        faltam.append(_chave(media, sel))
            elif it["tipo"] == "at-bloco" and it["filhos"] is not None:
                andar(it["filhos"], normalizar(it["prelude"]))

    andar(analisar(app_css.replace("\r\n", "\n")), "")
    return faltam
