"""Notas de entrada: cadastro, conferência de entregas e leitura no celular."""

import os
import re
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    CategoriaProduto,
    EmbalagemProduto,
    Fornecedor,
    LocalEstoque,
    ModuloContratado,
    MovimentoEstoque,
    NotaEntrada,
    Pessoa,
    Produto,
    Usuario,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.nucleo.notas_entrada import cadastrar_nota_entrada, receber_nota_entrada

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class NotasEntradaE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    XML = b'<?xml version="1.0" encoding="UTF-8"?><nota><numero>90001</numero></nota>'

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        ModuloContratado.objects.update_or_create(codigo=Modulo.ESTOQUE, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="notas-entrada-e2e", password="forte-123-abc")
        self.fornecedor = Pessoa.objects.create(
            nome="Fornecedor de alimentos e bebidas para os testes da pousada", tipo=Pessoa.Tipo.JURIDICA)
        Fornecedor.objects.create(pessoa=self.fornecedor)
        LocalEstoque.objects.update(ativo=False)
        self.local = LocalEstoque.objects.create(nome="Almoxarifado central de alimentos e bebidas", modulo="nucleo")
        categoria = CategoriaProduto.objects.create(nome="Alimentos e bebidas para testes")
        self.agua = Produto.objects.create(
            nome="Água mineral natural para atendimento dos quartos e eventos da pousada",
            unidade=Produto.Unidade.UNIDADE, categoria=categoria)
        self.arroz = Produto.objects.create(
            nome="Arroz integral de grãos selecionados para o restaurante", unidade=Produto.Unidade.KG,
            categoria=categoria)
        self.caixa = EmbalagemProduto.objects.create(produto=self.agua, nome="Caixa com 12 garrafas", fator=12)
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def abrir(self, nome, *args, pagina=None):
        pagina = pagina or self.page
        pagina.goto(self.url(reverse("estoque:" + nome, args=args)), wait_until="load")
        pagina.wait_for_function("document.fonts.status === 'loaded'", polling=100, timeout=10000)

    def foto(self, nome):
        pasta = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"notas-{nome}.png"), full_page=True)

    def nota(self, *, caixas="3"):
        return cadastrar_nota_entrada(
            fornecedor=self.fornecedor, tipo="nfe", numero="90002", serie="1",
            emissao=timezone.localdate(), chave_acesso="", usuario=self.usuario, chave=uuid.uuid4(),
            observacao="Documento fictício para conferência do fluxo.",
            itens=[
                {"produto": self.agua, "embalagem": self.caixa, "fator_conferido": Decimal("12"),
                 "quantidade": Decimal(caixas), "custo_unidade_compra": Decimal("60")},
                {"produto": self.arroz, "embalagem": None, "fator_conferido": Decimal("1"),
                 "quantidade": Decimal("5"), "custo_unidade_compra": Decimal("8")},
            ])

    def preencher_parcela(self, indice, quantidade, *, pagina=None):
        pagina = pagina or self.page
        pagina.locator(f'[name="parcelas-{indice}-quantidade"]').fill(quantidade)
        pagina.locator(f'[name="parcelas-{indice}-local"]').select_option(str(self.local.pk))

    def receber(self, *, pagina=None):
        pagina = pagina or self.page
        pagina.locator('#nota-receber-form button[type="submit"]').click()

    def test_cadastro_com_anexo_duas_unidades_e_entregas_parcial_e_completa(self):
        self.abrir("nota_nova")
        self.page.locator('[name="fornecedor"]').select_option(str(self.fornecedor.pk))
        self.page.locator('[name="numero"]').fill("90001")
        self.page.locator('[name="serie"]').fill("1")
        self.page.locator('[name="emissao"]').fill(timezone.localdate().isoformat())
        self.page.locator('[name="itens-0-produto"]').select_option(str(self.agua.pk))
        self.page.locator('[name="itens-0-embalagem"]').select_option(str(self.caixa.pk))
        self.page.locator('[name="itens-0-quantidade"]').fill("2")
        self.page.locator('[name="itens-0-custo_unidade_compra"]').fill("60")
        self.page.get_by_role("button", name="Adicionar item", exact=True).click()
        self.page.locator('[name="itens-1-produto"]').select_option(str(self.arroz.pk))
        self.page.locator('[name="itens-1-quantidade"]').fill("5")
        self.page.locator('[name="itens-1-custo_unidade_compra"]').fill("8")
        self.page.locator('[name="documentos"]').set_input_files({
            "name": "nota-teste.xml", "mimeType": "application/xml", "buffer": self.XML})
        self.page.locator('#nota-form button[type="submit"]').click()
        self.page.wait_for_url(re.compile(r"/notas/\d+/$"))
        nota = NotaEntrada.objects.get(numero="90001")
        self.assertEqual(nota.itens.count(), 2)
        self.assertEqual(nota.valor_total, Decimal("160"))
        self.assertEqual(MovimentoEstoque.objects.count(), 0)
        self.assertEqual(nota.documentos.count(), 1)
        expect(self.page.locator('.est-nota-status[data-status="pendente"]')).to_be_visible()
        self.foto("cadastrada-390")

        anexo = nota.documentos.get()
        with self.page.expect_download() as transferencia:
            self.page.locator(f'a[href="{reverse("estoque:nota_documento", args=[nota.pk, anexo.pk])}"]').click()
        arquivo = transferencia.value
        self.assertEqual(arquivo.suggested_filename, "nota-teste.xml")
        self.assertEqual(Path(arquivo.path()).read_bytes(), self.XML)

        self.abrir("nota_receber", nota.pk)
        self.preencher_parcela(0, "1")
        self.preencher_parcela(1, "2")
        self.receber()
        self.page.wait_for_url(self.url(reverse("estoque:nota", args=[nota.pk])))
        nota.refresh_from_db()
        self.assertEqual(nota.status, "parcial")
        self.assertEqual(saldo(self.agua, self.local), Decimal("12"))
        self.assertEqual(saldo(self.arroz, self.local), Decimal("2"))
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        expect(self.page.get_by_text("Parcial", exact=True)).to_be_visible()
        self.foto("parcial-390")

        self.abrir("nota_receber", nota.pk)
        self.preencher_parcela(0, "1")
        self.preencher_parcela(1, "3")
        self.receber()
        self.page.wait_for_url(self.url(reverse("estoque:nota", args=[nota.pk])))
        nota.refresh_from_db()
        self.assertEqual(nota.status, "concluida")
        self.assertEqual(saldo(self.agua, self.local), Decimal("24"))
        self.assertEqual(saldo(self.arroz, self.local), Decimal("5"))
        self.assertEqual(MovimentoEstoque.objects.count(), 4)
        expect(self.page.get_by_text("Concluída", exact=True)).to_be_visible()
        self.foto("concluida-390")

    def test_duas_abas_nao_recebem_a_mesma_conferencia_duas_vezes(self):
        nota = self.nota()
        self.abrir("nota_receber", nota.pk)
        contexto = self._browser.new_context(storage_state=self.page.context.storage_state(), locale="pt-BR")
        outra = contexto.new_page()
        try:
            self.abrir("nota_receber", nota.pk, pagina=outra)
            self.preencher_parcela(0, "1")
            self.preencher_parcela(0, "1", pagina=outra)
            self.receber()
            self.page.wait_for_url(self.url(reverse("estoque:nota", args=[nota.pk])))
            self.receber(pagina=outra)
            expect(outra.locator("[data-erros-envio]")).to_contain_text("Atualize")
            self.assertEqual(saldo(self.agua, self.local), Decimal("12"))
            self.assertEqual(nota.recebimentos.count(), 1)
        finally:
            contexto.close()

    def test_lista_detalhe_cadastro_e_recebimento_cabem_em_telas_estreitas(self):
        nota = self.nota()
        receber_nota_entrada(nota, usuario=self.usuario, chave=uuid.uuid4(), versao_conferida=0,
                            parcelas=[{"item": nota.itens.get(produto=self.agua), "quantidade": Decimal("1"),
                                       "local": self.local, "lote": None}])
        for largura in (320, 390, 821, 1440):
            self.page.set_viewport_size({"width": largura, "height": 900})
            for nome, args in (("notas", ()), ("nota", (nota.pk,)), ("nota_nova", ()),
                               ("nota_receber", (nota.pk,))):
                with self.subTest(largura=largura, tela=nome):
                    self.abrir(nome, *args)
                    if largura == 821:
                        self.assertNotIn("recolhida", self.page.locator("#app").get_attribute("class"))
                    medidas = self.page.evaluate("""() => ({
                      largura:document.documentElement.clientWidth, documento:document.documentElement.scrollWidth,
                      campos:[...document.querySelectorAll('#conteudo input:not([type=hidden]),#conteudo select,#conteudo textarea')]
                        .filter(el => el.getClientRects().length).map(el => {
                          const r=el.getBoundingClientRect(); return {nome:el.name,left:r.left,right:r.right};
                        })
                    })""")
                    self.assertLessEqual(medidas["documento"], medidas["largura"] + 1, medidas)
                    for campo in medidas["campos"]:
                        self.assertGreaterEqual(campo["left"], -1, campo)
                        self.assertLessEqual(campo["right"], medidas["largura"] + 1, campo)
                    if largura <= 1024:
                        cortes = self.page.locator(".est-notas-tabela").evaluate_all("""tabelas => tabelas.flatMap(tabela => {
                          const quadro = tabela.closest('.quadro').getBoundingClientRect();
                          return [tabela, ...tabela.querySelectorAll('tbody td, tbody td a, tbody td > div, tbody td > span')]
                            .filter(el => el.getClientRects().length).map(el => {
                              const r=el.getBoundingClientRect();
                              return {texto:el.textContent.trim().slice(0,80), left:r.left, right:r.right,
                                      quadroLeft:quadro.left, quadroRight:quadro.right};
                            }).filter(r => r.left < r.quadroLeft-1 || r.right > r.quadroRight+1);
                        })""")
                        self.assertEqual(cortes, [], cortes)
                    if nome == "nota_nova":
                        expect(self.page.locator("#nota-limite-itens")).not_to_be_visible()
                    self.foto(f"{nome}-{largura}")
