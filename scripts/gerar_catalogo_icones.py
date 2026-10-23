"""Monta o sprite local a partir dos SVGs Lucide, preservando os originais.

Executar na raiz: python scripts/gerar_catalogo_icones.py
Origem e hashes: static/vendor/lucide/origem.json. Licença no mesmo diretório.
"""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "static/vendor/lucide"
NS = "http://www.w3.org/2000/svg"


def main():
    ET.register_namespace("", NS)
    manifesto = json.loads((BASE / "origem.json").read_text(encoding="utf-8"))
    sprite = ET.Element(f"{{{NS}}}svg")
    sprite.append(ET.Comment(" Lucide Icons; ISC/MIT. See LICENSE and origem.json in this directory. "))
    for nome, dados in sorted(manifesto["arquivos"].items()):
        arquivo = (BASE / nome).read_bytes()
        assert hashlib.sha256(arquivo).hexdigest() == dados["sha256"], nome
        if not nome.endswith(".svg"):
            continue
        origem = ET.fromstring(arquivo)
        simbolo = ET.SubElement(sprite, f"{{{NS}}}symbol", {
            "id": Path(nome).stem,
            **{chave: origem.attrib[chave] for chave in (
                "viewBox", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"
            )},
        })
        for filho in origem:
            simbolo.append(filho)
    ET.indent(sprite, space="  ")
    (BASE / "catalogo.svg").write_bytes(ET.tostring(sprite, encoding="utf-8", xml_declaration=True) + b"\n")
    print(f"Sprite local: {len(sprite) - 1} ícones.")


if __name__ == "__main__":
    main()
