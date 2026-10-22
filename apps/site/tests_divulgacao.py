from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import TestCase

from .models import ConfiguracaoSite


class DivulgacaoVerificadaTests(TestCase):
    def test_legado_nao_publica_numeros_sem_fonte_nem_telefone_de_exemplo(self):
        config = ConfiguracaoSite(numero_avaliacoes="19k+", numero_viajantes="5k+",
            numero_quartos="30", whatsapp="5549999999999", telefone="(49) 99999-9999")
        for template in ("site/sections/hero.html", "site/sections/contato.html", "site/sections/cta.html",
                         "site/partials/whatsapp.html", "site/legal/termos_servico.html",
                         "site/legal/politica_privacidade.html", "site/legal/exclusao_dados.html"):
            with self.subTest(template=template):
                html = render_to_string(template, {"config": config})
                for exemplo in ("19k+", "5k+", "wa.me/5549", ">(49) 99999-9999<"):
                    self.assertNotIn(exemplo, html)
        config.contato_verificado = True
        with self.assertRaises(ValidationError):
            config.clean()
        self.assertEqual(config.whatsapp_publico, "")

    def test_publicacao_exige_conferencia_e_fonte(self):
        config = ConfiguracaoSite(numero_quartos="24", numeros_verificados=True,
            whatsapp="554920550005", contato_verificado=True)
        with self.assertRaises(ValidationError):
            config.clean()
        self.assertEqual(config.numeros_publicos, [])
        config.fonte_numeros = "Cadastro físico conferido em 22/10/2026 — cenário fictício"
        config.clean()
        self.assertEqual(config.numeros_publicos, [("24", "Quartos temáticos")])
        html = render_to_string("site/partials/whatsapp.html", {"config": config})
        self.assertIn("https://wa.me/554920550005", html)
