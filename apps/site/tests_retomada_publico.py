from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import TrilhaAuditoria, Usuario

from .icones_experiencias import ICONES_CORRIGIDOS
from .models import Experiencia


class IconesExperienciasTests(TestCase):
    def test_correcao_simulada_e_idempotente_preserva_conteudo_e_customizacoes(self):
        for ordem, antigo in enumerate(ICONES_CORRIGIDOS):
            Experiencia.objects.create(nome=f"Experiência {ordem}", descricao="Texto editorial",
                                       icone=antigo, ordem=ordem, destaque=False)
        personalizado = Experiencia.objects.create(nome="Personalizado", descricao="Outro texto",
                                                   icone="M1 1h10v10z")
        antes = list(Experiencia.objects.values("id", "nome", "descricao", "ordem", "destaque"))
        auditoria = TrilhaAuditoria.objects.filter(alvo="Experiencia").count()
        call_command("corrigir_icones_experiencias", stdout=StringIO())
        self.assertEqual(Experiencia.objects.filter(icone__in=ICONES_CORRIGIDOS).count(), 5)
        self.assertFalse(Usuario.objects.filter(username="_manutencao_site").exists())
        call_command("corrigir_icones_experiencias", aplicar=True, stdout=StringIO())
        self.assertEqual(Experiencia.objects.filter(icone__in=ICONES_CORRIGIDOS.values()).count(), 5)
        self.assertEqual(list(Experiencia.objects.values("id", "nome", "descricao", "ordem", "destaque")), antes)
        personalizado.refresh_from_db()
        self.assertEqual(personalizado.icone, "M1 1h10v10z")
        self.assertEqual(TrilhaAuditoria.objects.filter(alvo="Experiencia").count(), auditoria + 5)
        call_command("corrigir_icones_experiencias", aplicar=True, stdout=StringIO())
        self.assertEqual(TrilhaAuditoria.objects.filter(alvo="Experiencia").count(), auditoria + 5)

    def test_politica_da_lista_mantem_finalidade_e_contato_no_layout_do_site(self):
        resposta = self.client.get(reverse("privacidade"))
        self.assertEqual(resposta.status_code, 200)
        for texto in ("Como tratamos seus dados quando você entra na nossa lista.",
                      "7. Contato e encarregado (DPO)", "3. Para que usamos", "Neco-Regular.woff2"):
            self.assertContains(resposta, texto)
        self.assertContains(resposta, "<header", html=False)
        self.assertContains(resposta, "<footer", html=False)
        self.assertNotContains(resposta, "Última atualização:")
