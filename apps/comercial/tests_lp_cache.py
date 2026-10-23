"""O HTML em memória mantém os recursos da LP no contexto de URL solicitado."""
import re

from django.test import TestCase, override_settings
from django.urls import get_script_prefix, set_script_prefix

from . import views_lp


@override_settings(DEBUG=False)
class CacheContextoLpTests(TestCase):
    URLS = ("/lp/fundador/", "/lp/fundador-2/", "/lp/inauguracao_31_10_2026/")

    def setUp(self):
        self.addCleanup(set_script_prefix, get_script_prefix())
        for cache in (views_lp._LP_CACHE, views_lp._LP2_CACHE, views_lp._LPINAUG_CACHE):
            cache.clear()
            self.addCleanup(cache.clear)

    def test_alternar_prefixo_na_mesma_instancia_preserva_urls_de_cada_lp(self):
        for prefixo in ("/votesta", "", "/votesta", ""):
            with self.settings(FORCE_SCRIPT_NAME=prefixo or None, STATIC_URL=f"{prefixo}/static/"):
                set_script_prefix(prefixo or "/")
                for caminho in self.URLS:
                    with self.subTest(prefixo=prefixo, caminho=caminho):
                        resposta = self.client.get(caminho)
                        self.assertEqual(resposta.status_code, 200)
                        html = resposta.content.decode()
                        self.assertIn(f'src="{prefixo}/static/js/consentimento.js"', html)
                        self.assertIn(f'href="{prefixo}/politica-de-privacidade/"', html)
                        self.assertNotIn("/votesta/votesta/", html)
                        if not prefixo:
                            self.assertNotIn("/votesta/", html)
                        arquivos = re.findall(r"(/(?:votesta/)?lp/arquivo/[0-9a-f]{20}\.[a-z0-9]+)", html)
                        for arquivo in set(arquivos):
                            self.assertTrue(arquivo.startswith(f"{prefixo}/lp/arquivo/"))
                            self.assertEqual(self.client.get(arquivo.removeprefix(prefixo)).status_code, 200)

    def test_alterar_static_url_sem_trocar_prefixo_atualiza_script_de_consentimento(self):
        set_script_prefix("/")
        for static_url in ("/static/", "/assets-site/", "/static/"):
            with self.settings(FORCE_SCRIPT_NAME=None, STATIC_URL=static_url):
                for caminho in self.URLS:
                    with self.subTest(static_url=static_url, caminho=caminho):
                        resposta = self.client.get(caminho)
                        self.assertContains(resposta, f'src="{static_url}js/consentimento.js"')
