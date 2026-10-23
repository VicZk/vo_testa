"""A seleção do menu nasce da rota resolvida, inclusive com prefixo de deploy."""
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.nucleo.templatetags.navegacao_extras import navegacao_ativa


class NavegacaoAtivaTests(SimpleTestCase):
    def test_rotas_especificas_nao_acendem_o_modulo_pai_ao_mesmo_tempo(self):
        for nome, chave in (
            ("conciliacao:painel", "conciliacao"),
            ("comercial:paginas", "comercial_paginas"),
            ("comercial:pagina_nova", "comercial_paginas"),
            ("comercial:respostas", "comercial_respostas"),
            ("comercial:funil", "comercial"),
            ("daypass:painel", "reservas"),
            ("portal:solicitacoes", "appsite"),
            ("caixa_sessoes", "caixa_sessoes"),
            ("tabela_precos", "tabela_precos"),
            ("funcionarios", "funcionarios"),
        ):
            with self.subTest(nome=nome):
                request = SimpleNamespace(resolver_match=resolve(reverse(nome)), path="/prefixo/ignorado/")
                self.assertEqual(navegacao_ativa(request), chave)

    def test_erro_sem_rota_nao_inventa_um_item_ativo(self):
        self.assertEqual(navegacao_ativa(SimpleNamespace(resolver_match=None)), "")
