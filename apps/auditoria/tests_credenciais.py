import importlib
import json
from unittest import mock

import pyotp
from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.audit import definir_contexto, limpar_contexto
from apps.nucleo.models import ModuloContratado, TrilhaAuditoria, Usuario, registrar_auditoria
from apps.nucleo.modulos import Modulo


class CredenciaisNaTrilhaTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_superuser(username="qa_admin", password=None)
        self.gerente = Usuario.objects.create_user(username="qa_gerente", password=None, is_staff=True)
        self.auditor = Usuario.objects.create_user(username="qa_auditor", password=None)
        modulo, _ = ModuloContratado.objects.update_or_create(
            codigo=Modulo.AUDITORIA, defaults={"ativo": True})
        self.gerente.modulos.add(modulo)
        self.auditor.modulos.add(modulo)
        self.addCleanup(limpar_contexto)

    def test_ativacao_real_nao_grava_segredo_ou_hashes_de_recuperacao(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("mfa_ativar"))
        seed = self.client.session["mfa_secret_novo"]
        resposta = self.client.post(reverse("mfa_ativar"), {"codigo": pyotp.TOTP(seed).now()})
        self.assertEqual(resposta.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.mfa_ativo)
        detalhes = json.dumps(list(TrilhaAuditoria.objects.values_list("detalhe", flat=True)))
        self.assertNotIn(seed, detalhes)
        for codigo in self.admin.mfa_backup_codes:
            self.assertNotIn(codigo, detalhes)
        self.assertTrue(TrilhaAuditoria.objects.filter(
            alvo="Usuario", detalhe__alteracoes__has_key="mfa_ativo").exists())

    def test_criacao_edicao_exclusao_e_registro_explicito_nao_copiam_credenciais(self):
        definir_contexto(self.admin)
        usuario = Usuario.objects.create_user(username="qa_mfa", mfa_secret="SEED_FICTICIA_ANTIGA")
        usuario.mfa_secret = "SEED_FICTICIA_NOVA"
        usuario.mfa_backup_codes = ["HASH_FICTICIO"]
        usuario.save(update_fields=["mfa_secret", "mfa_backup_codes"])
        registrar_auditoria(self.admin, "configuracao", usuario, {
            "itens": [{"Authorization": "TOKEN_FICTICIO", "mfa_secret": "SEED_FICTICIA_NOVA"}],
            "nome": "Preservar contexto",
        })
        usuario.delete()
        detalhes = json.dumps(list(TrilhaAuditoria.objects.values_list("detalhe", flat=True)))
        for valor in ("SEED_FICTICIA_ANTIGA", "SEED_FICTICIA_NOVA", "HASH_FICTICIO", "TOKEN_FICTICIO"):
            self.assertNotIn(valor, detalhes)
        self.assertIn("Preservar contexto", detalhes)

    def _legado(self):
        registro = TrilhaAuditoria.objects.create(acao="editar", alvo="Usuario", alvo_id="1")
        # Simula dado anterior à proteção sem passar pelo save atual.
        TrilhaAuditoria.objects.filter(pk=registro.pk).update(detalhe={
            "alteracoes": {"mfa_secret": ["SEGREDO_ANTIGO", "SEGREDO_NOVO"],
                           "mfa_backup_codes": [[], ["HASH_LEGADO"]],
                           "nome": ["Anterior", "Nome visível"]},
            "itens": [{"api_key": "CHAVE_LEGADA"}],
        })
        return registro

    def test_legado_nao_sai_em_tela_csv_ou_descricao_para_qualquer_perfil(self):
        registro = self._legado()
        from apps.auditoria.formatacao import frase
        registro.refresh_from_db()
        self.assertNotIn("SEGREDO_NOVO", frase(registro))
        for usuario in (self.admin, self.gerente, self.auditor):
            self.client.force_login(usuario)
            for parametros in ({}, {"export": "csv"}):
                with self.subTest(usuario=usuario.username, parametros=parametros):
                    resposta = self.client.get(reverse("auditoria:trilha"), parametros)
                    if usuario == self.auditor and parametros:
                        self.assertEqual(resposta.status_code, 403)
                        continue
                    self.assertEqual(resposta.status_code, 200)
                    for segredo in ("SEGREDO_ANTIGO", "SEGREDO_NOVO", "HASH_LEGADO", "CHAVE_LEGADA"):
                        self.assertNotContains(resposta, segredo)
                    self.assertContains(resposta, "Nome visível")

        self.client.force_login(self.admin)
        resposta = self.client.get(reverse("admin:nucleo_trilhaauditoria_change", args=[registro.pk]))
        self.assertEqual(resposta.status_code, 200)
        for segredo in ("SEGREDO_ANTIGO", "SEGREDO_NOVO", "HASH_LEGADO", "CHAVE_LEGADA"):
            self.assertNotContains(resposta, segredo)
        self.assertContains(resposta, "Nome visível")

    def test_migracao_saneia_legado_preservando_evento_e_e_idempotente(self):
        registro = self._legado()
        antes = TrilhaAuditoria.objects.values("pk", "acao", "alvo", "alvo_id", "criado_em").get(pk=registro.pk)
        migracao = importlib.import_module("apps.nucleo.migrations.0052_remover_credenciais_da_trilha")
        editor = mock.Mock(connection=connection)
        migracao.sanear(apps, editor)
        registro.refresh_from_db()
        self.assertEqual(registro.detalhe["alteracoes"]["mfa_secret"], "•••")
        self.assertEqual(registro.detalhe["itens"][0]["api_key"], "•••")
        self.assertEqual(registro.detalhe["alteracoes"]["nome"], ["Anterior", "Nome visível"])
        depois = TrilhaAuditoria.objects.values(*antes).get(pk=registro.pk)
        self.assertEqual(antes, depois)
        migracao.sanear(apps, editor)
        self.assertEqual(TrilhaAuditoria.objects.get(pk=registro.pk).detalhe, registro.detalhe)
