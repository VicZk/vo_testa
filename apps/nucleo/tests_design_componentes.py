"""Regras de tema compartilhado: nenhuma tela deve escapar dos tokens."""

import re

from django.test import SimpleTestCase

from .css_publico import analisar, caminho_app_css


class TemaCompartilhadoTests(SimpleTestCase):
    def _regras(self, itens):
        for item in itens:
            if item.get("filhos"):
                yield from self._regras(item["filhos"])
            elif item["tipo"] == "regra" and item["prelude"] != ":root":
                yield item

    def test_cores_e_cantos_dos_componentes_vem_do_tema(self):
        problemas = []
        for regra in self._regras(analisar(caminho_app_css().read_text(encoding="utf-8"))):
            corpo = re.sub(r"/\*.*?\*/", "", regra["corpo"], flags=re.S)
            if re.search(r"#[\da-fA-F]{3,8}\b|\brgba?\(", corpo):
                problemas.append(f"{regra['prelude']}: cor fora do tema")
            for valor in re.findall(r"border-radius:\s*([^;}]+)", corpo):
                if re.search(r"\d(?:px|rem)\b", valor):
                    problemas.append(f"{regra['prelude']}: raio {valor}")
        self.assertEqual(problemas, [])

    def test_texto_da_interface_responde_ao_tamanho_de_fonte_do_usuario(self):
        problemas = []
        for regra in self._regras(analisar(caminho_app_css().read_text(encoding="utf-8"))):
            for tamanho in re.findall(r"font-size:\s*([^;}]+)", regra["corpo"]):
                if re.fullmatch(r"[\d.]+px", tamanho):
                    problemas.append(f"{regra['prelude']}: {tamanho}")
                em_rem = re.fullmatch(r"([\d.]+)rem", tamanho)
                if em_rem and 0 < float(em_rem[1]) < .75:
                    problemas.append(f"{regra['prelude']}: sem piso de legibilidade no toque ({tamanho})")
        self.assertEqual(problemas, [])
