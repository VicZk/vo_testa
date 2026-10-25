"""Ícones da Lavanderia — peça, serviço, enxoval e estado — inferidos pelo nome.

O balcão lia "Camisa social", "Lençol casal" e "Toalha de banho" só em texto, tudo com o
mesmo peso no cartão. O ícone dá a leitura de relance e **acompanha** o nome: nunca
substitui o texto (ver §7 da especificação e `.ico-peca` no app.css).

Procedência e licença — cada chave guarda `fonte` e `licenca`:

- `lucide@20aef31d…` (5 chaves): Lucide, licença **ISC**, no mesmo commit registrado
  em `static/vendor/lucide/origem.json` (url + sha256 de cada arquivo usado).
- `tabler@3.31.0` (10 chaves): Tabler Icons, licença **MIT** na versão 3.31.0 — texto da
  licença em `static/vendor/tabler/LICENSE`, procedência em `static/vendor/tabler/origem.json`.
- `proprio` (21 chaves): desenhados para este projeto (24×24, traço aberto, mesmo peso
  dos de fora) — sem licença de terceiro.

O campo `arquivo` aponta o SVG de origem dentro da pasta do vendor, para conferir o
traçado contra o sha256 registrado.

`sutia` **não** é chave: o desenho lia como um par de óculos. Os sinônimos dele ("sutiã",
"soutien", "top íntimo") caem em `intima`.
"""
import re
import unicodedata

GRUPOS = (
    ("peca", "Peças"),
    ("servico", "Serviços"),
    ("enxoval", "Enxoval"),
    ("estado", "Estados"),
)

ICONES = {
    "camisa": {
        "rotulo": "Camisa social",
        "grupo": "peca",
        "fonte": "lucide@20aef31db93fe4d9f398dbb15b120d99c48eef95",
        "licenca": "ISC",
        "arquivo": "icons/shirt.svg",
        "sinonimos": ("camisa", "camisa social", "social", "camisaria", "camisa manga longa",),
        "svg": '<path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"/>',
    },
    "camiseta": {
        "rotulo": "Camiseta",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/shirt.svg",
        "sinonimos": (
            "camiseta", "camisetas", "polo", "camisa polo", "blusa", "blusinha", "t-shirt",
            "tshirt", "regata", "top",
        ),
        "svg": '<path d="M15 4l6 2v5h-3v8a1 1 0 0 1 -1 1h-10a1 1 0 0 1 -1 -1v-8h-3v-5l6 -2a3 3 0 0 0 6 0"/>',
    },
    "blazer": {
        "rotulo": "Blazer / paletó",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/jacket.svg",
        "sinonimos": ("blazer", "paleto", "paletó", "terno", "terno completo", "smoking", "colete",),
        "svg": (
            '<path d="M16 3l-4 5l-4 -5"/>'
            '<path d="M12 19a2 2 0 0 1 -2 2h-4a2 2 0 0 1 -2 -2v-8.172a2 2 0 0 1 .586 -1.414l.828 -.828a2 2 0 0 0 .586 -1.414v-2.172a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v2.172a2 2 0 0 0 .586 1.414l.828 .828a2 2 0 0 1 .586 1.414v8.172a2 2 0 0 1 -2 2h-4a2 2 0 0 1 -2 -2z"/>'
            '<path d="M20 13h-3a1 1 0 0 0 -1 1v2a1 1 0 0 0 1 1h3"/>'
            '<path d="M4 17h3a1 1 0 0 0 1 -1v-2a1 1 0 0 0 -1 -1h-3"/>'
            '<path d="M12 19v-11"/>'
        ),
    },
    "casaco": {
        "rotulo": "Casaco / jaqueta",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "casaco", "jaqueta", "moletom", "blusa de frio", "agasalho", "sueter", "suéter",
            "capuz",
        ),
        "svg": (
            '<path d="M15.2 5.6 20.6 7.8v4.6h-2.8v7.1a1.5 1.5 0 0 1-1.5 1.5H7.7a1.5 1.5 0 0 1-1.5-1.5v-7.1H3.4V7.8L8.8 5.6"/>'
            '<path d="M8.8 5.6H10V3.4h4v2.2h1.2"/>'
            '<path d="M12 5.6v15.6"/>'
            '<path d="M8.1 16.4h2.4"/>'
            '<path d="M13.5 16.4h2.4"/>'
        ),
    },
    "calca": {
        "rotulo": "Calça",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "calca", "calça", "calcas", "calças", "jeans", "calca social", "calça social",
            "legging",
        ),
        "svg": (
            '<path d="M5.4 3.6h13.2l-1 17.4h-4.6L12 10 11 21H6.4z"/>'
            '<path d="M5.6 7h12.8"/>'
        ),
    },
    "bermuda": {
        "rotulo": "Bermuda / calção",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("bermuda", "calcao", "calção", "short", "shorts", "bermudas",),
        "svg": (
            '<path d="M5 6h14l-1 12h-4.6L12 10.8 10.6 18H6z"/>'
            '<path d="M5.25 9h13.5"/>'
        ),
    },
    "saia": {
        "rotulo": "Saia",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("saia", "saias", "saia longa", "saia midi",),
        "svg": (
            '<path d="M8.5 4h7l3.7 14.8c-3.2 1.8-11.2 1.8-14.4 0z"/>'
            '<path d="M8.6 6.6h6.8"/>'
        ),
    },
    "vestido": {
        "rotulo": "Vestido",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("vestido", "vestidos", "vestido longo", "vestido de festa",),
        "svg": (
            '<path d="M8.5 3 12 5.5 15.5 3l2 2.5-3 5.5 4.5 8.8c-3 1.5-11 1.5-14 0L9.5 11l-3-5.5z"/>'
            '<path d="M9.5 11h5"/>'
        ),
    },
    "intima": {
        "rotulo": "Roupa íntima",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "intima", "íntima", "roupa intima", "roupa íntima", "cueca", "calcinha", "lingerie",
            "sutia", "sutiã", "top intimo", "soutien",
        ),
        "svg": (
            '<path d="M6 7.6h12a1 1 0 0 1 1 1.1l-.6 3.8c-2.3.9-4.2 2.6-5.4 4.9-.4.7-1.6.7-2 0-1.2-2.3-3.1-4-5.4-4.9L5 8.7a1 1 0 0 1 1-1.1z"/>'
            '<path d="M5.15 10h13.7"/>'
        ),
    },
    "meia": {
        "rotulo": "Meia",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/sock.svg",
        "sinonimos": ("meia", "meias", "par de meias", "meia calca", "meia-calça",),
        "svg": (
            '<path d="M13 3v6l4.798 5.142a4 4 0 0 1 -5.441 5.86l-6.736 -6.41a2 2 0 0 1 -.621 -1.451v-9.141h8z"/>'
            '<path d="M7.895 15.768c.708 -.721 1.105 -1.677 1.105 -2.768a4 4 0 0 0 -4 -4"/>'
        ),
    },
    "pijama": {
        "rotulo": "Pijama",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("pijama", "pijamas", "camisola", "roupa de dormir",),
        "svg": (
            '<path d="M14.8 5 20.4 7.2V12h-2.8v6.4a1.5 1.5 0 0 1-1.5 1.5H7.9a1.5 1.5 0 0 1-1.5-1.5V12H3.6V7.2L9.2 5"/>'
            '<path d="M9.2 5c.8 1.5 5 1.5 5.6 0"/>'
            '<path d="M10.4 13v5.8"/>'
            '<path d="M13.6 13v5.8"/>'
        ),
    },
    "banho": {
        "rotulo": "Roupa de banho",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "maio", "maiô", "biquini", "biquíni", "sunga", "roupa de banho", "moda praia",
            "traje de banho", "roupa de piscina",
        ),
        "svg": '<path d="M8.8 3.6c.6 2.4 1.7 3.6 3.2 3.6s2.6-1.2 3.2-3.6l2.2 6.4c0 3.6-1.4 6.4-3.2 8.8-1.4 1.6-3 1.6-4.4 0C8 16.4 6.6 13.6 6.6 10z"/>',
    },
    "sapato": {
        "rotulo": "Sapato / tênis",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/shoe.svg",
        "sinonimos": (
            "sapato", "sapatos", "tenis", "tênis", "calcado", "calçado", "sandalia", "sandália",
            "bota",
        ),
        "svg": (
            '<path d="M4 6h5.426a1 1 0 0 1 .863 .496l1.064 1.823a3 3 0 0 0 1.896 1.407l4.677 1.114a4 4 0 0 1 3.074 3.89v2.27a1 1 0 0 1 -1 1h-16a1 1 0 0 1 -1 -1v-10a1 1 0 0 1 1 -1z"/>'
            '<path d="M14 13l1 -2"/>'
            '<path d="M8 18v-1a4 4 0 0 0 -4 -4h-1"/>'
            '<path d="M10 12l1.5 -3"/>'
        ),
    },
    "gravata": {
        "rotulo": "Gravata",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/tie.svg",
        "sinonimos": ("gravata", "gravatas", "gravata borboleta",),
        "svg": (
            '<path d="M12 22l4 -4l-2.5 -11l.993 -2.649a1 1 0 0 0 -.936 -1.351h-3.114a1 1 0 0 0 -.936 1.351l.993 2.649l-2.5 11l4 4z"/>'
            '<path d="M10.5 7h3l5 5.5"/>'
        ),
    },
    "bone": {
        "rotulo": "Boné / chapéu",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("bone", "boné", "chapeu", "chapéu", "vizeira", "viseira",),
        "svg": (
            '<path d="M5.2 16.4a6.6 6.6 0 0 1 13.2 0z"/>'
            '<path d="M18.4 16.4c2 .1 3.4.6 3.4 1.5 0 .8-1.2 1.3-3.1 1.3H6a1.4 1.4 0 0 1 0-2.8"/>'
        ),
    },
    "bebe": {
        "rotulo": "Roupa de bebê",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "bebe", "bebê", "roupa de bebe", "roupa de bebê", "body", "infantil", "crianca",
            "criança", "macacao", "macacão",
        ),
        "svg": (
            '<path d="M14.8 4.6 20 6.6V11h-2.6v3.6c0 3.8-2.4 6.2-5.4 6.2s-5.4-2.4-5.4-6.2V11H4V6.6l5.2-2"/>'
            '<path d="M9.2 4.6c.7 1.4 5.1 1.4 5.6 0"/>'
            '<path d="M10.3 18.6h1.1"/>'
            '<path d="M12.6 18.6h1.1"/>'
        ),
    },
    "toalha_praia": {
        "rotulo": "Toalha de praia",
        "grupo": "peca",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "toalha de praia", "toalha praia", "toalha de piscina", "canga", "toalhao",
            "toalha grande",
        ),
        "svg": (
            '<path d="M6.6 4.4h10.8a1.6 1.6 0 0 1 1.6 1.6v11.8c-1.75 0-1.75 2.2-3.5 2.2s-1.75-2.2-3.5-2.2-1.75 2.2-3.5 2.2-1.75-2.2-3.5-2.2V6a1.6 1.6 0 0 1 1.6-1.6z"/>'
            '<path d="M9.6 4.4v13.4"/>'
            '<path d="M14.4 4.4v13.4"/>'
        ),
    },
    "lavar_passar": {
        "rotulo": "Lavar e passar",
        "grupo": "servico",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/wash.svg",
        "sinonimos": ("lavar e passar", "lavar", "lavagem", "lavagem comum", "lavar + passar", "lavado",),
        "svg": (
            '<path d="M3.486 8.965c.168 .02 .34 .033 .514 .035c.79 .009 1.539 -.178 2 -.5c.461 -.32 1.21 -.507 2 -.5c.79 -.007 1.539 .18 2 .5c.461 .322 1.21 .509 2 .5c.79 .009 1.539 -.178 2 -.5c.461 -.32 1.21 -.507 2 -.5c.79 -.007 1.539 .18 2 .5c.461 .322 1.21 .509 2 .5c.17 0 .339 -.014 .503 -.034"/>'
            '<path d="M3 6l1.721 10.329a2 2 0 0 0 1.973 1.671h10.612a2 2 0 0 0 1.973 -1.671l1.721 -10.329"/>'
        ),
    },
    "passar": {
        "rotulo": "Passar (ferro)",
        "grupo": "servico",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/ironing.svg",
        "sinonimos": (
            "passar", "passar (peca)", "passar (peça)", "passadoria", "ferro", "so passar",
            "só passar", "passar a ferro",
        ),
        "svg": '<path d="M9 6h7.459a3 3 0 0 1 2.959 2.507l.577 3.464l.81 4.865a1 1 0 0 1 -.985 1.164h-16.82a7 7 0 0 1 7 -7h9.8"/>',
    },
    "seco": {
        "rotulo": "Lavagem a seco",
        "grupo": "servico",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("seco", "a seco", "lavagem a seco", "dry clean", "lavar a seco",),
        "svg": (
            '<path d="M12 5.6c-1.2-.9-1.8-1.9-1.8-3a1.8 1.8 0 0 1 3.6 0"/>'
            '<path d="M12 5.6 7.8 8.6a2.8 2.8 0 0 0-1.2 2.3v8.9a1.8 1.8 0 0 0 1.8 1.8h7.2a1.8 1.8 0 0 0 1.8-1.8v-8.9a2.8 2.8 0 0 0-1.2-2.3z"/>'
            '<path d="M12 5.6v16"/>'
        ),
    },
    "quilo": {
        "rotulo": "Por quilo",
        "grupo": "servico",
        "fonte": "lucide@20aef31db93fe4d9f398dbb15b120d99c48eef95",
        "licenca": "ISC",
        "arquivo": "icons/weight.svg",
        "sinonimos": ("quilo", "kg", "por quilo", "roupa por quilo", "a quilo", "peso", "pesagem",),
        "svg": (
            '<circle cx="12" cy="5" r="3"/>'
            '<path d="M6.5 8a2 2 0 0 0-1.905 1.46L2.1 18.5A2 2 0 0 0 4 21h16a2 2 0 0 0 1.925-2.54L19.4 9.5A2 2 0 0 0 17.48 8Z"/>'
        ),
    },
    "mancha": {
        "rotulo": "Remoção de mancha",
        "grupo": "servico",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "mancha", "manchas", "remocao de mancha", "remoção de mancha", "tira manchas",
            "tira-manchas", "nodoa", "nódoa",
        ),
        "svg": (
            '<path d="M9.6 7.4c2.4-1.7 5.4-.4 5.8 2.3.3 2 2.3 2.2 2.5 4.1.3 2.5-2 4.6-5.1 4.6-3.4 0-6.1-1.9-6.1-4.6 0-2.5 1.3-4.4 2.9-6.4z"/>'
            '<path d="M19 3.4v3.2"/>'
            '<path d="M17.4 5h3.2"/>'
        ),
    },
    "expresso": {
        "rotulo": "Urgente / expresso",
        "grupo": "servico",
        "fonte": "lucide@20aef31db93fe4d9f398dbb15b120d99c48eef95",
        "licenca": "ISC",
        "arquivo": "icons/zap.svg",
        "sinonimos": (
            "expresso", "urgente", "urgencia", "urgência", "rapido", "rápido", "mesmo dia",
            "prioritario", "prioritário",
        ),
        "svg": '<path d="M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z"/>',
    },
    "lencol": {
        "rotulo": "Lençol",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": (
            "lencol", "lençol", "lencois", "lençóis", "lencol casal", "lençol casal",
            "lencol solteiro", "lençol solteiro", "virol", "roupa de cama",
        ),
        "svg": (
            '<path d="M3 7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v10.5c-1.5 0-1.5 1.8-3 1.8s-1.5-1.8-3-1.8-1.5 1.8-3 1.8-1.5-1.8-3-1.8-1.5 1.8-3 1.8-1.5-1.8-3-1.8z"/>'
            '<path d="M3 8.8h18"/>'
        ),
    },
    "fronha": {
        "rotulo": "Fronha / travesseiro",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("fronha", "fronhas", "travesseiro", "travesseiros", "almofada",),
        "svg": (
            '<path d="M3.4 9.4A2.6 2.6 0 0 1 6 6.8h12a2.6 2.6 0 0 1 2.6 2.6v5.2A2.6 2.6 0 0 1 18 17.2H6a2.6 2.6 0 0 1-2.6-2.6z"/>'
            '<path d="M16.8 7c-.9 1.5-1.4 3.2-1.4 5.1s.5 3.6 1.4 5.1"/>'
        ),
    },
    "toalha_banho": {
        "rotulo": "Toalha de banho",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("toalha de banho", "toalha banho", "toalha de corpo", "toalha",),
        "svg": (
            '<path d="M3.5 5h17"/>'
            '<path d="M7 5v14.8A1.2 1.2 0 0 0 8.2 21h7.6a1.2 1.2 0 0 0 1.2-1.2V5"/>'
            '<path d="M7 16h10"/>'
        ),
    },
    "toalha_rosto": {
        "rotulo": "Toalha de rosto",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("toalha de rosto", "toalha rosto", "toalha de mao", "toalha de mão", "rosto",),
        "svg": (
            '<path d="M6 7h12"/>'
            '<path d="M8 7v8.6a1.4 1.4 0 0 0 1.4 1.4h5.2a1.4 1.4 0 0 0 1.4-1.4V7"/>'
            '<path d="M8 13.6h8"/>'
        ),
    },
    "tapete": {
        "rotulo": "Tapete de banheiro",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("tapete", "tapetes", "piso", "piso de banheiro", "tapete de banheiro", "capacho",),
        "svg": (
            '<path d="M7.6 8.2h8.8l3.8 7.4H3.8z"/>'
            '<path d="M5.6 15.6v1.8"/>'
            '<path d="M9 15.6v1.8"/>'
            '<path d="M12 15.6v1.8"/>'
            '<path d="M15 15.6v1.8"/>'
            '<path d="M18.4 15.6v1.8"/>'
        ),
    },
    "edredom": {
        "rotulo": "Edredom / cobertor",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("edredom", "edredon", "cobertor", "colcha", "manta", "duvet", "acolchoado",),
        "svg": (
            '<path d="M3.6 9.8A2.8 2.8 0 0 1 6.4 7h11.2a2.8 2.8 0 0 1 2.8 2.8v4.4a2.8 2.8 0 0 1-2.8 2.8H6.4a2.8 2.8 0 0 1-2.8-2.8z"/>'
            '<path d="M5.2 14.2 7.9 10.8l2.7 3.4 2.7-3.4 2.7 3.4 2.7-3.4"/>'
        ),
    },
    "roupao": {
        "rotulo": "Roupão",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("roupao", "roupão", "roupoes", "roupões",),
        "svg": (
            '<path d="M14.8 4 20.4 6.2V11h-2.8v8.4a1.5 1.5 0 0 1-1.5 1.5H7.9a1.5 1.5 0 0 1-1.5-1.5V11H3.6V6.2L9.2 4"/>'
            '<path d="M9.6 4.2c.4 2.6 1.2 4.4 2.4 5.8 1.2-1.4 2-3.2 2.4-5.8"/>'
            '<path d="M6.4 12.8h11.2"/>'
        ),
    },
    "cortina": {
        "rotulo": "Cortina",
        "grupo": "enxoval",
        "fonte": "proprio",
        "licenca": "propria",
        "sinonimos": ("cortina", "cortinas", "persiana", "voal", "black out", "blackout",),
        "svg": (
            '<path d="M2.6 4.4h18.8"/>'
            '<path d="M3.4 4.4h6.2c.8 1.6 1 3.6 1 6 0 5.1-2.2 9.1-6.2 10.7-.8.3-2-.2-2-1.1z"/>'
            '<path d="M6.4 4.8c-.4 4.4-.6 10.2-.2 14.8"/>'
            '<path d="M20.6 4.4h-6.2c-.8 1.6-1 3.6-1 6 0 5.1 2.2 9.1 6.2 10.7.8.3 2-.2 2-1.1z"/>'
            '<path d="M17.6 4.8c.4 4.4.6 10.2.2 14.8"/>'
        ),
    },
    "estado_limpa": {
        "rotulo": "Limpa (na rouparia)",
        "grupo": "estado",
        "fonte": "lucide@20aef31db93fe4d9f398dbb15b120d99c48eef95",
        "licenca": "ISC",
        "arquivo": "icons/sparkles.svg",
        "sinonimos": ("limpa", "limpo", "rouparia", "disponivel", "disponível", "em estoque",),
        "svg": (
            '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/>'
            '<path d="M20 2v4"/>'
            '<path d="M22 4h-4"/>'
            '<circle cx="4" cy="20" r="2"/>'
        ),
    },
    "estado_em_uso": {
        "rotulo": "Em uso (no quarto)",
        "grupo": "estado",
        "fonte": "lucide@20aef31db93fe4d9f398dbb15b120d99c48eef95",
        "licenca": "ISC",
        "arquivo": "icons/bed.svg",
        "sinonimos": ("em uso", "no quarto", "em_uso", "uso", "ocupada",),
        "svg": (
            '<path d="M2 4v16"/>'
            '<path d="M2 8h18a2 2 0 0 1 2 2v10"/>'
            '<path d="M2 17h20"/>'
            '<path d="M6 8v9"/>'
        ),
    },
    "estado_suja": {
        "rotulo": "Suja (cesto)",
        "grupo": "estado",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/basket.svg",
        "sinonimos": ("suja", "sujo", "cesto", "recolhida", "a lavar",),
        "svg": (
            '<path d="M10 14a2 2 0 1 0 4 0a2 2 0 0 0 -4 0"/>'
            '<path d="M5.001 8h13.999a2 2 0 0 1 1.977 2.304l-1.255 7.152a3 3 0 0 1 -2.966 2.544h-9.512a3 3 0 0 1 -2.965 -2.544l-1.255 -7.152a2 2 0 0 1 1.977 -2.304z"/>'
            '<path d="M17 10l-2 -6"/>'
            '<path d="M7 10l2 -6"/>'
        ),
    },
    "estado_lavando": {
        "rotulo": "Lavando (máquina)",
        "grupo": "estado",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/wash-machine.svg",
        "sinonimos": ("lavando", "em lavagem", "maquina", "máquina", "na lavanderia", "processando",),
        "svg": (
            '<path d="M5 3m0 2a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v14a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2z"/>'
            '<path d="M12 14m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0"/>'
            '<path d="M8 6h.01"/>'
            '<path d="M11 6h.01"/>'
            '<path d="M14 6h2"/>'
            '<path d="M8 14c1.333 -.667 2.667 -.667 4 0c1.333 .667 2.667 .667 4 0"/>'
        ),
    },
    "generico": {
        "rotulo": "Genérico (peça)",
        "grupo": "peca",
        "fonte": "tabler@3.31.0",
        "licenca": "MIT",
        "arquivo": "icons/hanger.svg",
        "sinonimos": ("peca", "peça", "item", "outro", "outros", "diversos", "cabide",),
        "svg": '<path d="M14 6a2 2 0 1 0 -4 0c0 1.667 .67 3 2 4h-.008l7.971 4.428a2 2 0 0 1 1.029 1.749v.823a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-.823a2 2 0 0 1 1.029 -1.749l7.971 -4.428"/>',
    },
}

# Grupos que a TABELA DE PREÇOS oferece: "estado" (limpa, suja, lavando, em uso) é do
# enxoval interno — é a cor da barra da rouparia, não um serviço que o hóspede compra.
GRUPOS_DA_TABELA = ("peca", "servico", "enxoval")

# O `<select>` e a grade de desenhos da tabela de preços, agrupados: 36 ícones numa
# fileira só não se procuram. A opção vazia ("Automático pelo nome") é escrita na tela,
# fora dos grupos.
ESCOLHAS_ICONES_LAV = tuple(
    (rotulo, tuple((chave, dados["rotulo"]) for chave, dados in ICONES.items()
                   if dados["grupo"] == codigo))
    for codigo, rotulo in GRUPOS if codigo in GRUPOS_DA_TABELA
)
PADRAO = "generico"


def _normalizar(texto: str) -> str:
    """"Lençóis casal" → "lencois casal": sem acento, minúsculo, só letra e número."""
    cru = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in cru if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.casefold()).strip()


# Sinônimo MAIS LONGO primeiro, cercado de espaço: a fronteira de palavra é o que separa
# "Toalha de banho" (toalha_banho) de "banho" (maiô) e "Calção" (bermuda) de "calça".
_INDICE = tuple(sorted(
    {(f" {_normalizar(sin)} ", chave)
     for chave, dados in ICONES.items() for sin in dados["sinonimos"]},
    key=lambda par: (-len(par[0]), par[0]),
))


def icone_de(nome: str, escolha: str = "") -> str:
    """Chave do ícone: a escolha manual vence; senão infere pelo nome; senão `generico`."""
    if escolha in ICONES:
        return escolha
    alvo = f" {_normalizar(nome)} "
    for sinonimo, chave in _INDICE:
        if sinonimo in alvo:
            return chave
    return PADRAO


def svg_de(chave: str) -> str:
    """Miolo do SVG (sem a casca `<svg>`), já com a chave corrigida se vier inválida."""
    return ICONES.get(chave, ICONES[PADRAO])["svg"]


def rotulo_de(chave: str) -> str:
    return ICONES.get(chave, ICONES[PADRAO])["rotulo"]
