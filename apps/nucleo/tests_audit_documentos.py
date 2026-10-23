"""Anexos privados têm trilha de metadados, nunca cópias dos arquivos na auditoria."""

import json

from django.test import TestCase

from apps.estoque.tests_notas import NotasFixture
from apps.manutencao.anexos import preparar_documento, salvar_documento
from apps.manutencao.models import OrdemServico
from apps.nucleo import audit
from apps.nucleo.models import TrilhaAuditoria


class AuditoriaDocumentosPrivadosTests(NotasFixture, TestCase):
    def setUp(self):
        super().setUp()
        audit.definir_contexto(self.user, "127.0.0.1")
        self.addCleanup(audit.limpar_contexto)

    def conferir_metadados_sem_conteudo(self, documento, marcador):
        registros = TrilhaAuditoria.objects.filter(
            alvo=type(documento).__name__, alvo_id=str(documento.pk))
        criado = registros.get(acao="criar")
        valores = criado.detalhe["valores"]
        self.assertEqual(valores["nome"], documento.nome)
        self.assertEqual(valores["tamanho"], documento.tamanho)
        self.assertEqual(valores["sha256"], documento.sha256)
        self.assertNotIn("conteudo", valores)
        texto = json.dumps(list(registros.values_list("detalhe", flat=True)))
        self.assertNotIn(marcador, texto)
        self.assertNotIn("conteudo", texto)
        self.assertNotIn("memory at", texto)
        self.assertEqual(criado.usuario_id, self.user.pk)

    def test_nota_anexa_arquivo_sem_copiar_bytes_a_trilha_e_mascara_emitente(self):
        marcador = "TRECHO_PRIVADO_FICTICIO_NOTA_AUDIT"
        nota = self.nota(documentos=[self.xml(marcador=marcador)])
        anexo = nota.documentos.get()
        self.assertIn(marcador.encode(), bytes(anexo.conteudo))
        self.conferir_metadados_sem_conteudo(anexo, marcador)
        registro = TrilhaAuditoria.objects.get(acao="criar", alvo="NotaEntrada", alvo_id=str(nota.pk))
        self.assertEqual(registro.detalhe["valores"]["documento_numero"], "•••")
        self.assertEqual(registro.detalhe["valores"]["fornecedor_nome"], self.fornecedor.nome)
        detalhes = list(TrilhaAuditoria.objects.filter(alvo="NotaEntrada", alvo_id=str(nota.pk))
                        .values_list("detalhe", flat=True))
        self.assertNotIn(nota.documento_numero, json.dumps(detalhes))
        self.assertNotIn(marcador, json.dumps(detalhes))

    def test_manutencao_anexa_arquivo_sem_copiar_bytes_a_trilha(self):
        ordem = OrdemServico.objects.create(
            area="Área fictícia", titulo="Serviço fictício de teste", criado_por=self.user)
        marcador = "TRECHO_PRIVADO_FICTICIO_MANUTENCAO_AUDIT"
        documento = salvar_documento(ordem, self.user, preparar_documento(self.xml(marcador=marcador)))
        self.assertIn(marcador.encode(), bytes(documento.conteudo))
        self.conferir_metadados_sem_conteudo(documento, marcador)

    def test_chave_fiscal_nao_reexpoe_documento_do_emitente_na_trilha(self):
        documento_emitente = "12345678000195"
        chave_ficticia = f"422610{documento_emitente}550010000000421123456780"
        self.assertEqual(len(chave_ficticia), 44)
        nota = self.nota(chave_acesso=chave_ficticia)

        registro = TrilhaAuditoria.objects.get(acao="criar", alvo="NotaEntrada", alvo_id=str(nota.pk))
        self.assertEqual(registro.detalhe["valores"]["chave_acesso"], "•••")
        detalhes = list(TrilhaAuditoria.objects.filter(alvo="NotaEntrada", alvo_id=str(nota.pk))
                        .values_list("detalhe", flat=True))
        self.assertNotIn(documento_emitente, json.dumps(detalhes))
        self.assertNotIn(chave_ficticia, json.dumps(detalhes))
        nota.refresh_from_db()
        self.assertEqual(nota.chave_acesso, chave_ficticia)

    def test_edicao_e_exclusao_do_documento_legado_tambem_nao_copiam_binario(self):
        ordem = OrdemServico.objects.create(
            area="Área fictícia", titulo="Documento legado fictício", criado_por=self.user)
        marcador = "TRECHO_PRIVADO_FICTICIO_LEGADO_AUDIT"
        documento = salvar_documento(ordem, self.user, preparar_documento(self.xml(marcador=marcador)))
        documento.refresh_from_db()  # O PostgreSQL pode devolver o campo como memoryview.
        documento.nome = "nome-posterior-ficticio.xml"
        documento.save()
        alvo_id = str(documento.pk)
        editado = TrilhaAuditoria.objects.get(acao="editar", alvo="DocumentoOrdemServico", alvo_id=alvo_id)
        self.assertEqual(set(editado.detalhe["alteracoes"]), {"nome"})
        documento.delete()
        excluido = TrilhaAuditoria.objects.get(acao="excluir", alvo="DocumentoOrdemServico", alvo_id=alvo_id)
        self.assertEqual(excluido.detalhe["valores"]["nome"], "nome-posterior-ficticio.xml")
        detalhes = list(TrilhaAuditoria.objects.filter(alvo="DocumentoOrdemServico", alvo_id=alvo_id)
                        .values_list("detalhe", flat=True))
        texto = json.dumps(detalhes)
        self.assertNotIn("conteudo", texto)
        self.assertNotIn(marcador, texto)
        self.assertNotIn("memory at", texto)
