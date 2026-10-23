"""Ilustrações locais do catálogo; só identificadores conhecidos geram SVG."""

import re
import unicodedata

ICONES_CATALOGO = (
    ("cup-soda", "Refrigerante", "bebida"),
    ("glass-water", "Água", "bebida"),
    ("bubbles", "Água com gás", "bebida"),
    ("coffee", "Café e bebidas quentes", "cafe"),
    ("milk", "Leite e laticínios", "bebida"),
    ("citrus", "Suco", "fruta"),
    ("beer", "Cerveja", "lanche"),
    ("wine", "Vinho", "doce"),
    ("martini", "Drinque", "doce"),
    ("utensils", "Prato e refeição", "refeicao"),
    ("sandwich", "Sanduíche e lanche", "lanche"),
    ("pizza", "Pizza", "lanche"),
    ("beef", "Carne e porção", "refeicao"),
    ("fish", "Peixe e frutos do mar", "bebida"),
    ("salad", "Salada", "fruta"),
    ("soup", "Sopa e caldo", "refeicao"),
    ("cake", "Bolo e sobremesa", "doce"),
    ("cookie", "Biscoito", "lanche"),
    ("croissant", "Pão e padaria", "lanche"),
    ("popcorn", "Salgadinho e pipoca", "lanche"),
    ("candy", "Chocolate e doce", "doce"),
    ("apple", "Fruta", "fruta"),
    ("wheat", "Grãos e ingredientes", "lanche"),
    ("spray-can", "Higiene e limpeza", "bebida"),
    ("shirt", "Roupas e acessórios", "doce"),
    ("shopping-bag", "Presente e lembrança", "cafe"),
    ("package", "Produto", "neutro"),
)
ESCOLHAS_ICONES = (("", "Automático pelo nome e categoria"),) + tuple(
    (icone, rotulo) for icone, rotulo, _ in ICONES_CATALOGO
)
_ICONES = {icone: {"icone": icone, "rotulo": rotulo, "tom": tom} for icone, rotulo, tom in ICONES_CATALOGO}

# O nome tem prioridade sobre a categoria; o primeiro alimento nomeado vence
# ingredientes posteriores: "Bolo de café" é bolo e "Café com leite" é café.
_REGRAS = (
    (r"\b(cafe|cappuccino|capuccino|expresso|espresso|macchiato|mocha|cha)\b", "coffee"),
    (r"\b(leite|iogurte|yogurt|achocolatado)\b", "milk"),
    (r"\b(agua|aguas)\b", "glass-water"),
    (r"\b(coca(?: cola)?|pepsi|guarana|fanta|sprite|refrigerante|refrigerantes|refri|tonica|soda|energetico)\b", "cup-soda"),
    (r"\b(suco|sucos|limonada|laranjada|nectar)\b", "citrus"),
    (r"\b(cerveja|cervejas|chopp|chope|heineken|brahma|budweiser|skol|stella|corona)\b", "beer"),
    (r"\b(vinho|vinhos|espumante|prosecco)\b", "wine"),
    (r"\b(drink|drinque|drinks|drinques|coquetel|caipirinha|caipiroska|gin|vodka|whisky|whiskey)\b", "martini"),
    (r"\b(pizza|pizzas)\b", "pizza"),
    (r"\b(sanduiche|sanduiches|hamburguer|hamburgueres|burger|misto|bauru|hot dog|cachorro quente|lanche|lanches)\b", "sandwich"),
    (r"\b(salada|saladas|vegetais|legumes)\b", "salad"),
    (r"\b(sopa|sopas|caldo|caldos)\b", "soup"),
    (r"\b(peixe|peixes|tilapia|salmao|camarao|camaroes|frutos do mar)\b", "fish"),
    (r"\b(carne|carnes|bife|picanha|frango|file|churrasco|linguica)\b", "beef"),
    (r"\b(bolo|bolos|torta|tortas|pudim|sobremesa|sobremesas|sorvete|picole|acai)\b", "cake"),
    (r"\b(biscoito|biscoitos|bolacha|bolachas|cookie|cookies)\b", "cookie"),
    (r"\b(pao|paes|croissant|torrada|padaria|salgado|salgados)\b", "croissant"),
    (r"\b(pipoca|salgadinho|salgadinhos|chips|doritos|ruffles|lays|cheetos|amendoim|castanha)\b", "popcorn"),
    (r"\b(chocolate|chocolates|bombom|bombons|bala|balas|doce|doces|chiclete|trident)\b", "candy"),
    (r"\b(fruta|frutas|maca|banana|laranja|mamao|melancia|abacaxi)\b", "apple"),
    (r"\b(arroz|feijao|aveia|farinha|graos|cereal|cereais|ingrediente|ingredientes)\b", "wheat"),
    (r"\b(sabonete|shampoo|xampu|protetor|repelente|creme|higiene|limpeza|detergente|alcool)\b", "spray-can"),
    (r"\b(camiseta|camisetas|camisa|roupa|roupas|bone|chinelo|moda)\b", "shirt"),
    (r"\b(presente|presentes|lembranca|lembrancas|souvenir|artesanato)\b", "shopping-bag"),
    (r"\b(alimento|alimentos|refeicao|refeicoes|prato|pratos|porcao|porcoes|almoco|jantar|restaurante)\b", "utensils"),
    (r"\b(bebida|bebidas)\b", "glass-water"),
)
_PADROES = tuple((re.compile(padrao), icone) for padrao, icone in _REGRAS)


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def ilustracao_produto(nome, categoria="", escolha=""):
    """A escolha explícita vale primeiro; nomes desconhecidos usam embalagem."""
    if escolha in _ICONES:
        return dict(_ICONES[escolha])
    for texto in (_normalizar(nome), _normalizar(categoria)):
        for grupo in (_PADROES[:-2], _PADROES[-2:]):
            encontrados = [(match.start(), ordem, icone) for ordem, (padrao, icone) in enumerate(grupo)
                           if (match := padrao.search(texto))]
            if encontrados:
                _, _, icone = min(encontrados)
                if icone == "glass-water" and re.search(r"\b(gas|gasosa)\b", texto) and not re.search(r"\b(sem|s) gas\b", texto):
                    icone = "bubbles"
                return dict(_ICONES[icone])
    return dict(_ICONES["package"])


def configuracao_ilustracoes():
    """A prévia usa o mesmo catálogo e regras do servidor, sem busca externa."""
    return {"icones": _ICONES, "regras": _REGRAS, "prioritarias": len(_REGRAS) - 2}
