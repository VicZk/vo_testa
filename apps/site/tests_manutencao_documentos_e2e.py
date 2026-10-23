"""Documentos e histórico da manutenção no navegador, com arquivos fictícios."""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.manutencao import services
from apps.manutencao.models import DocumentoOrdemServico, OrdemServico
from apps.manutencao.tests_documentos import pdf_ficticio
from apps.nucleo.models import UH, ModuloContratado, TipoUH, Usuario

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class ManutencaoDocumentosE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        for codigo in ("manutencao", "reservas", "governanca"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="manutencao-ui", password="senha-qa")
        tipo = TipoUH.objects.create(nome="Suíte para revisão documental", tarifa_base="250")
        self.uh = UH.objects.create(numero="DOC-101", tipo=tipo)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def enviar(self, nome):
        with self.page.expect_navigation():
            self.page.get_by_role("button", name=nome, exact=True).click()

    def foto_e_limites(self, nome, seletor):
        p = self.page
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        for largura in (320, 390, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("() => document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            # Os controles e o texto dos documentos devem continuar dentro do cartão.
            excedentes = p.locator(seletor).evaluate("""el => {
                const limite = el.getBoundingClientRect();
                return [...el.querySelectorAll('input, select, button, a')].filter(item => {
                    const r = item.getBoundingClientRect();
                    return r.width && (r.left < limite.left - 1 || r.right > limite.right + 1);
                }).map(item => item.id || item.textContent.trim());
            }""")
            self.assertEqual(excedentes, [])
            if destino:
                pasta = Path(destino)
                pasta.mkdir(parents=True, exist_ok=True)
                p.evaluate("window.scrollTo(0, 0)")
                p.screenshot(path=str(pasta / f"manutencao-{nome}-{largura}.png"), full_page=True,
                             animations="disabled")
        p.set_viewport_size({"width": 390, "height": 844})

    def baixar(self, nome, conteudo):
        with self.page.expect_download() as espera:
            self.page.get_by_role("link", name=f"Baixar {nome}", exact=True).click()
        arquivo = espera.value
        self.assertEqual(arquivo.suggested_filename, nome)
        self.assertEqual(Path(arquivo.path()).read_bytes(), conteudo)

    def test_abre_inicia_corrige_anexo_conclui_baixa_e_reencontra_no_historico(self):
        p = self.page
        titulo = "Trocar componente do ar-condicionado e conferir funcionamento do quarto"
        resolucao = "Componente substituído, filtro higienizado e funcionamento conferido."
        nota = "NF-QA-DOCUMENTO-001"
        garantia = (timezone.localdate() + timedelta(days=90)).isoformat()
        p.goto(self.url(reverse("manutencao:painel")))
        p.locator("#os-quarto").select_option(str(self.uh.pk))
        p.locator("#os-titulo").fill(titulo)
        p.locator("#os-descricao").fill("Conferência fictícia do fluxo de manutenção e seus documentos.")
        p.get_by_label("Bloquear o quarto durante o reparo", exact=True).check()
        self.enviar("Abrir OS")
        ordem = OrdemServico.objects.get(titulo=titulo)
        expect(p).to_have_url(self.url(reverse("manutencao:detalhe", args=[ordem.pk])))
        self.assertIn(self.uh.pk, services.motivos_bloqueio())
        self.enviar("Iniciar (em andamento)")
        p.locator("#os-custo-maodeobra").fill("123.45")
        p.locator("#os-custo-pecas").fill("35.50")
        p.locator("#os-numero-nota").fill(nota)
        p.locator("#os-garantia").fill(garantia)
        p.locator("#os-resolucao").fill(resolucao)
        p.locator("#os-anexo-conclusao").set_input_files({
            "name": "nota-invalida.pdf", "mimeType": "application/pdf",
            "buffer": b"%PDF-1.4\ntexto sem objetos PDF\n%%EOF",
        })
        with p.expect_response(lambda resposta: resposta.request.method == "POST") as resposta:
            p.get_by_role("button", name="Concluir e liberar quarto", exact=True).click()
        self.assertEqual(resposta.value.status, 422)
        expect(p.locator("[data-erros-envio]")).to_contain_text("documento válido")
        for campo, valor in (("os-custo-maodeobra", "123.45"), ("os-custo-pecas", "35.50"),
                             ("os-numero-nota", nota), ("os-garantia", garantia), ("os-resolucao", resolucao)):
            expect(p.locator(f"#{campo}")).to_have_value(valor)
        self.assertEqual(p.locator("#os-anexo-conclusao").evaluate("el => el.files[0].name"), "nota-invalida.pdf")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.EM_ANDAMENTO)
        self.assertEqual(ordem.custo_total, 0)
        self.assertEqual(ordem.documentos.count(), 0)
        self.assertIn(self.uh.pk, services.motivos_bloqueio())
        self.foto_e_limites("correcao-anexo", "#acoes-os")

        pdf = pdf_ficticio()
        nome_pdf = "nota-fiscal-" + "conferencia-documental-" * 6 + "001.pdf"
        p.locator("#os-anexo-conclusao").set_input_files({
            "name": nome_pdf, "mimeType": "application/pdf", "buffer": pdf,
        })
        self.enviar("Concluir e liberar quarto")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.CONCLUIDA)
        self.assertEqual(ordem.custo_total, Decimal("158.95"))
        self.assertEqual(ordem.resolucao, resolucao)
        self.assertEqual(ordem.nota_fiscal, nota)
        self.assertEqual(ordem.garantia_ate.isoformat(), garantia)
        self.assertEqual(ordem.documentos.count(), 1)
        self.assertNotIn(self.uh.pk, services.motivos_bloqueio())
        expect(p.locator("#acoes-os")).to_have_count(0)
        expect(p.get_by_text("bloqueado por esta OS hoje", exact=True)).to_have_count(0)
        self.baixar(nome_pdf, pdf)

        xml = b'<?xml version="1.0"?><NFe><teste>Documento ficticio de QA</teste></NFe>'
        p.locator("#os-anexo-documento").set_input_files({
            "name": "nota-complementar.xml", "mimeType": "application/xml", "buffer": xml,
        })
        self.enviar("Anexar documento")
        self.assertEqual(ordem.documentos.count(), 2)
        self.baixar("nota-complementar.xml", xml)
        p.locator("#os-anexo-documento").set_input_files({
            "name": "copia-da-nota.xml", "mimeType": "application/xml", "buffer": xml,
        })
        self.enviar("Anexar documento")
        self.assertEqual(DocumentoOrdemServico.objects.filter(ordem=ordem).count(), 2)
        expect(p.get_by_role("link", name="copia-da-nota.xml", exact=True)).to_have_count(0)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.CONCLUIDA)
        self.assertEqual(ordem.custo_total, Decimal("158.95"))
        self.foto_e_limites("concluida-documentos", "#documentos-os")

        p.locator("a.voltar").click()
        expect(p.get_by_role("heading", name="Ordens abertas", exact=True)).to_be_visible()
        expect(p.get_by_role("link", name=titulo, exact=True)).to_have_count(0)
        p.locator("#os-filtro-situacao").select_option("concluidas")
        p.locator("#os-filtro-busca").fill(nota)
        p.get_by_role("button", name="Filtrar", exact=True).click()
        expect(p.get_by_role("heading", name="Ordens concluídas", exact=True)).to_be_visible()
        expect(p.get_by_role("link", name=titulo, exact=True)).to_be_visible()
        self.foto_e_limites("historico-nf", ".manutencao-painel")
        p.get_by_role("link", name="Ver detalhes", exact=False).click()
        expect(p.get_by_role("heading", name="Documentos da OS", exact=True)).to_be_visible()
        self.baixar(nome_pdf, pdf)

    def test_cancela_com_motivo_e_encontra_pelo_numero_no_historico(self):
        p = self.page
        ordem = services.abrir_os(self.usuario, area="Piscina", titulo="Manutenção fictícia da piscina")
        p.goto(self.url(reverse("manutencao:detalhe", args=[ordem.pk])))
        p.locator("summary").filter(has_text="Cancelar OS").click()
        p.locator("#os-motivo-cancelamento").fill("Serviço registrado em duplicidade durante o teste.")
        self.enviar("Cancelar OS")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemServico.Status.CANCELADA)
        p.locator("#os-filtro-situacao").select_option("canceladas")
        p.locator("#os-filtro-busca").fill(f"#{ordem.pk}")
        p.get_by_role("button", name="Filtrar", exact=True).click()
        expect(p.get_by_role("heading", name="Ordens canceladas", exact=True)).to_be_visible()
        expect(p.get_by_role("link", name=ordem.titulo, exact=True)).to_be_visible()
        p.get_by_role("link", name=ordem.titulo, exact=True).click()
        expect(p.get_by_text("Serviço registrado em duplicidade durante o teste.", exact=False)).to_be_visible()
        expect(p.locator("#acoes-os")).to_have_count(0)
        expect(p.get_by_role("button", name="Anexar documento", exact=True)).to_be_visible()
