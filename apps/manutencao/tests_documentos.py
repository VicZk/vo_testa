"""Documento privado, envio recuperável e conclusão atômica da manutenção."""

from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.nucleo.models import UH, ModuloContratado, TipoUH, Usuario

from . import anexos, services
from .models import DocumentoOrdemServico, OrdemServico


def pdf_ficticio():
    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"]
    conteudo = b"%PDF-1.4\n"
    posicoes = [0]
    for indice, corpo in enumerate(objetos, 1):
        posicoes.append(len(conteudo))
        conteudo += f"{indice} 0 obj\n".encode() + corpo + b"\nendobj\n"
    inicio = len(conteudo)
    conteudo += b"xref\n0 4\n0000000000 65535 f \n"
    conteudo += b"".join(f"{posicao:010d} 00000 n \n".encode() for posicao in posicoes[1:])
    return conteudo + f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{inicio}\n%%EOF\n".encode()


def arquivo_pdf(nome="nota-ficticia.pdf"):
    return SimpleUploadedFile(nome, pdf_ficticio(), content_type="application/pdf")


class ValidacaoDocumentoTests(SimpleTestCase):
    def test_pdf_xml_png_e_jpeg_validos(self):
        arquivos = [arquivo_pdf(), SimpleUploadedFile("nota.xml", b'<?xml version="1.0"?><NFe><teste>1</teste></NFe>')]
        for formato, extensao in (("PNG", "png"), ("JPEG", "jpg")):
            saida = BytesIO()
            Image.new("RGB", (2, 2), "white").save(saida, format=formato)
            arquivos.append(SimpleUploadedFile(f"nota.{extensao}", saida.getvalue()))
        for arquivo in arquivos:
            with self.subTest(arquivo=arquivo.name):
                documento = anexos.preparar_documento(arquivo)
                self.assertEqual(documento["tamanho"], len(documento["conteudo"]))
                self.assertEqual(len(documento["sha256"]), 64)

    def test_rejeita_vazio_arquivo_disfarcado_svg_xml_com_entidades_e_imagem_incompleta(self):
        for nome, dados in [
            ("vazio.pdf", b""), ("html.pdf", b"<script>alert(1)</script>"),
            ("sem-estrutura.pdf", b"%PDF-1.4\ntexto sem objetos PDF\n%%EOF"),
            ("nota.svg", b"<svg/>"), ("quebrado.xml", b"<NFe>"),
            ("entidade.xml", b'<!DOCTYPE n [<!ENTITY x SYSTEM "file:///etc/passwd">]><n>&x;</n>'),
            ("nota.jpg", b"\xff\xd8\xff"), ("nota.png", b"%PDF-1.4\n%%EOF"),
        ]:
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                anexos.preparar_documento(SimpleUploadedFile(nome, dados))

    def test_limite_tambem_confere_conteudo_quando_tamanho_declarado_e_falso(self):
        arquivo = SimpleUploadedFile("grande.pdf", b"%PDF-1.4\n" + b"x" * anexos.LIMITE_BYTES + b"%%EOF")
        with self.assertRaisesMessage(ValidationError, "10 MB"):
            anexos.preparar_documento(arquivo)
        arquivo.size = 1
        with self.assertRaisesMessage(ValidationError, "10 MB"):
            anexos.preparar_documento(arquivo)


class DocumentosManutencaoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.modulo, _ = ModuloContratado.objects.update_or_create(codigo="manutencao", defaults={"ativo": True})
        ModuloContratado.objects.update_or_create(codigo="governanca", defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="documentos-qa", password="senha-qa")
        tipo = TipoUH.objects.create(nome="Quarto documental", tarifa_base="200")
        self.uh = UH.objects.create(numero="DOC-101", tipo=tipo)
        self.ordem = services.abrir_os(self.usuario, uh=self.uh, titulo="Reparo fictício", bloquear=True)
        self.client.force_login(self.usuario)

    def postar(self, rota, dados):
        return self.client.post(reverse(rota, args=[self.ordem.pk]), dados, HTTP_X_FORM_PRESERVE="1")

    def test_anexa_antes_e_depois_de_concluir_sem_alterar_custo(self):
        resposta = self.postar("manutencao:anexar_documento", {"anexo_nota_fiscal": arquivo_pdf()})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["redirect"].endswith("#documentos-os"))
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, OrdemServico.Status.ABERTA)
        services.concluir_os(self.ordem, self.usuario, custo_pecas="100.00")
        resposta = self.postar("manutencao:anexar_documento", {
            "anexo_nota_fiscal": SimpleUploadedFile("nota.xml", b"<NFe><teste>2</teste></NFe>")})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.ordem.documentos.count(), 2)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.custo_total, 100)

    def test_download_exige_modulo_e_entrega_mesmos_bytes_como_anexo(self):
        anexo = anexos.salvar_documento(self.ordem, self.usuario, anexos.preparar_documento(arquivo_pdf()))
        url = reverse("manutencao:documento", args=[self.ordem.pk, anexo.pk])
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(b"".join(resposta.streaming_content), pdf_ficticio())
        self.assertIn("attachment;", resposta["Content-Disposition"])
        self.assertEqual(resposta["Cache-Control"], "private, no-store")
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        sem_acesso = Usuario.objects.create_user(username="sem-documentos")
        self.client.force_login(sem_acesso)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.postar("manutencao:anexar_documento", {"anexo_nota_fiscal": arquivo_pdf()}).status_code, 403)
        sem_acesso.modulos.add(self.modulo)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.modulo.ativo = False
        self.modulo.save()
        cache.clear()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_documento_nao_e_servido_em_outra_os(self):
        anexo = anexos.salvar_documento(self.ordem, self.usuario, anexos.preparar_documento(arquivo_pdf()))
        outra = services.abrir_os(self.usuario, area="Recepção", titulo="Outro reparo")
        self.assertEqual(self.client.get(reverse("manutencao:documento", args=[outra.pk, anexo.pk])).status_code, 404)

    def test_reenvio_mesmo_arquivo_nao_duplica_nem_sobrescreve(self):
        for nome in ("nota.pdf", "renomeada.pdf"):
            self.assertEqual(self.postar("manutencao:anexar_documento", {"anexo_nota_fiscal": arquivo_pdf(nome)}).status_code, 200)
        self.assertEqual(self.ordem.documentos.count(), 1)
        self.assertEqual(self.ordem.documentos.get().nome, "nota.pdf")

    def test_arquivo_invalido_nao_conclui_nem_libera_quarto(self):
        resposta = self.postar("manutencao:concluir", {"custo_maodeobra": "150.00", "resolucao": "Resolvido",
            "anexo_nota_fiscal": SimpleUploadedFile("falso.pdf", b"nao e um pdf")})
        self.assertEqual(resposta.status_code, 422)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, OrdemServico.Status.ABERTA)
        self.assertEqual(self.ordem.custo_total, 0)
        self.assertEqual(self.ordem.documentos.count(), 0)
        self.assertIn(self.uh.pk, services.motivos_bloqueio())

    def test_conclusao_e_anexo_juntos_com_reenvio_idempotente(self):
        for _ in range(2):
            resposta = self.postar("manutencao:concluir", {"custo_maodeobra": "150.00", "nota_fiscal": "NF teste 123",
                "resolucao": "Resolvido", "anexo_nota_fiscal": arquivo_pdf()})
            self.assertEqual(resposta.status_code, 200)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, OrdemServico.Status.CONCLUIDA)
        self.assertEqual(self.ordem.custo_total, 150)
        self.assertEqual(self.ordem.documentos.count(), 1)
        from apps.governanca.models import TarefaGovernanca
        self.assertEqual(TarefaGovernanca.objects.filter(uh=self.uh, origem="manutencao").count(), 1)

    def test_limite_de_documentos_desfaz_conclusao_e_faxina(self):
        for indice in range(10):
            arquivo = SimpleUploadedFile(f"nota-{indice}.xml", f"<NFe>{indice}</NFe>".encode())
            anexos.salvar_documento(self.ordem, self.usuario, anexos.preparar_documento(arquivo))
        resposta = self.postar("manutencao:concluir", {"custo_pecas": "50", "anexo_nota_fiscal": arquivo_pdf()})
        self.assertEqual(resposta.status_code, 422)
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, OrdemServico.Status.ABERTA)
        self.assertEqual(self.ordem.custo_total, 0)
        self.assertEqual(self.ordem.documentos.count(), 10)
        from apps.governanca.models import TarefaGovernanca
        self.assertFalse(TarefaGovernanca.objects.filter(uh=self.uh, origem="manutencao").exists())

    def test_falha_de_persistencia_desfaz_toda_a_conclusao(self):
        with patch.object(DocumentoOrdemServico.objects, "create", side_effect=RuntimeError("falha simulada")):
            with self.assertRaisesMessage(RuntimeError, "falha simulada"):
                self.postar("manutencao:concluir", {"custo_pecas": "50", "anexo_nota_fiscal": arquivo_pdf()})
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, OrdemServico.Status.ABERTA)
        self.assertEqual(self.ordem.custo_total, 0)
        self.assertEqual(self.ordem.documentos.count(), 0)

    def test_get_nao_anexa_e_ausencia_de_arquivo_exibe_erro(self):
        self.assertEqual(self.client.get(reverse("manutencao:anexar_documento", args=[self.ordem.pk])).status_code, 405)
        self.assertEqual(self.postar("manutencao:anexar_documento", {}).status_code, 422)
        self.assertEqual(self.ordem.documentos.count(), 0)

    def test_historico_reencontra_nota_e_separa_ordens_encerradas(self):
        services.concluir_os(self.ordem, self.usuario, nota_fiscal="NF-2026-ficticia")
        url = reverse("manutencao:painel")
        self.assertNotContains(self.client.get(url), self.ordem.titulo)
        historico = self.client.get(url, {"situacao": "concluidas", "q": "NF-2026-ficticia"})
        self.assertContains(historico, self.ordem.titulo)
        self.assertContains(historico, f'{reverse("manutencao:detalhe", args=[self.ordem.pk])}#documentos-os')
        self.assertNotContains(self.client.get(url, {"situacao": "canceladas"}), self.ordem.titulo)
        self.assertContains(self.client.get(url, {"situacao": "todas", "q": f"#{self.ordem.pk}"}), self.ordem.titulo)

    def test_bloqueio_por_data_conta_hoje_e_futuro_nao_e_anunciado_como_atual(self):
        self.uh.refresh_from_db()
        self.assertEqual(self.uh.status, UH.Status.ATIVA)
        self.assertEqual(self.client.get(reverse("manutencao:painel")).context["bloqueados"], 1)
        services.concluir_os(self.ordem, self.usuario)
        futura = services.abrir_os(self.usuario, uh=self.uh, titulo="Pintura futura", bloquear=True,
            bloqueio_inicio=timezone.localdate() + timedelta(days=20))
        resposta = self.client.get(reverse("manutencao:painel"))
        self.assertEqual(resposta.context["bloqueados"], 0)
        self.assertFalse(futura.bloqueio_ativo_hoje)
        self.assertContains(resposta, futura.bloqueio_inicio.strftime("%d/%m/%Y"))
        self.assertNotContains(resposta, "Quarto bloqueado hoje")
