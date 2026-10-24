"""A tipografia de tela deve acompanhar a preferência de fonte do navegador."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class TipografiaDosTemplatesTests(SimpleTestCase):
    def test_estilos_dos_templates_nao_fixam_fontes_em_pixels(self):
        raiz = Path(settings.BASE_DIR)
        arquivos = [*(raiz / "templates").rglob("*.html"),
                    *(raiz / "apps").glob("*/templates/**/*.html")]
        problemas = []
        for arquivo in arquivos:
            texto = arquivo.read_text(encoding="utf-8")
            for bloco in re.finditer(r"<style\b[^>]*>(.*?)</style\s*>", texto, re.S | re.I):
                css = re.sub(r"/\*.*?\*/", "", bloco[1], flags=re.S)
                for tamanho in re.findall(r"font-size\s*:\s*([^;{}]+)", css, re.I):
                    if re.search(r"[\d.]\s*px\b", tamanho, re.I):
                        problemas.append(f"{arquivo.relative_to(raiz)}: {tamanho}")
        self.assertEqual(problemas, [], "Use rem/tokens também nos limites de clamp().")
