"""Operação da comanda no navegador: saldo, rascunho, descontos e estornos."""

import os
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.nucleo.models import (
    CategoriaProduto,
    FormaPagamento,
    LocalEstoque,
    ModuloContratado,
    Produto,
    SessaoCaixa,
    Usuario,
    estornar_movimento,
    registrar_entrada,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.restaurante.services import abrir_comanda, adicionar_item, fechar_comanda

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class RestauranteFluxoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="restaurante-fluxo-qa", password="local-ficticio-123")
        ModuloContratado.objects.update_or_create(codigo=Modulo.RESTAURANTE, defaults={"ativo": True})
        self.forma = FormaPagamento.objects.create(nome="Dinheiro QA", tipo="dinheiro")
        self.caixa = SessaoCaixa.objects.create(operador=self.op, modulo="restaurante", fundo_troco=100)
        self.categoria = CategoriaProduto.objects.create(nome="Bebidas do teste")
        self.produto = Produto.objects.create(
            nome="Água mineral do teste", categoria=self.categoria, preco_venda=Decimal("7.00"))
        self.local = LocalEstoque.objects.create(nome="Cozinha QA", modulo="restaurante")
        registrar_entrada(self.produto, self.local, 20, Decimal("2.00"), self.op)
        self.comanda = abrir_comanda(self.op, self.local, rotulo="Mesa do teste de operação")
        self.client.force_login(self.op)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self):
        self.page.goto(self.url(reverse("restaurante:comanda", args=[self.comanda.pk])))

    def produto_botao(self):
        return self.page.locator(".pdv-produto").filter(has_text=self.produto.nome)

    def adicionar(self, quantidade):
        self.produto_botao().click()
        dialogo = self.page.get_by_role("dialog")
        dialogo.get_by_label("Quantidade", exact=False).fill(str(quantidade))
        dialogo.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(dialogo).to_be_hidden()

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True, animations="disabled")

    def test_saldo_esgota_retorna_e_edicao_atualiza_sem_recarregar(self):
        self.abrir()
        self.adicionar(20)
        expect(self.produto_botao()).to_be_disabled()
        expect(self.produto_botao()).to_contain_text("Esgotado")
        self.assertEqual(saldo(self.produto, self.local), Decimal("0"))
        self.page.get_by_role("button", name=f"Remover {self.produto.nome}", exact=True).click()
        expect(self.produto_botao()).to_be_enabled()
        expect(self.produto_botao()).to_contain_text("Saldo 20")
        self.assertEqual(saldo(self.produto, self.local), Decimal("20"))
        self.adicionar(1)
        self.page.get_by_role("button", name=f"Editar {self.produto.nome}", exact=True).click()
        dialogo = self.page.get_by_role("dialog")
        dialogo.get_by_label("Quantidade", exact=False).fill("2")
        dialogo.get_by_role("button", name="Salvar pedido", exact=True).click()
        expect(dialogo).to_be_hidden()
        expect(self.produto_botao()).to_contain_text("Saldo 18")
        expect(self.page.locator("#comanda-itens")).to_contain_text("14,00")
        self.assertEqual(self.comanda.itens.get().quantidade, Decimal("2"))
        self.assertEqual(saldo(self.produto, self.local), Decimal("18"))

    def test_pedido_nao_salvo_pede_confirmacao_e_preserva_observacao(self):
        self.abrir()
        self.produto_botao().click()
        dialogo = self.page.get_by_role("dialog")
        dialogo.get_by_label("Observações", exact=False).fill("Sem gelo; entregar à mesa depois da entrada.")
        avisos = []

        def manter(dialog):
            avisos.append(dialog.message)
            dialog.dismiss()

        self.page.once("dialog", manter)
        dialogo.get_by_role("button", name="Fechar", exact=True).click()
        self.assertEqual(len(avisos), 1)
        self.assertIn("não", avisos[0])
        expect(dialogo).to_be_visible()
        expect(dialogo.get_by_label("Observações", exact=False)).to_have_value(
            "Sem gelo; entregar à mesa depois da entrada.")
        self.assertFalse(self.comanda.itens.exists())
        dialogo.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(dialogo).to_be_hidden()
        self.assertEqual(self.comanda.itens.get().observacoes, "Sem gelo; entregar à mesa depois da entrada.")

    def test_desconto_total_filtros_e_larguras_uteis(self):
        categoria = CategoriaProduto.objects.create(nome="Pratos do teste")
        Produto.objects.create(nome="Prato indisponível do teste", categoria=categoria, preco_venda=25)
        self.abrir()
        self.adicionar(2)
        self.page.locator('[name="desconto"]').fill("2.50")
        expect(self.page.locator("[data-restaurante-total]")).to_contain_text("11,50")
        expect(self.page.locator('[data-restaurante-sem-cobranca]')).to_be_hidden()
        self.page.get_by_label("Categoria do cardápio", exact=True).select_option(str(categoria.pk))
        expect(self.produto_botao()).to_be_hidden()
        expect(self.page.locator(".pdv-produto").filter(has_text="Prato indisponível")).to_be_visible()
        self.page.get_by_label("Somente disponíveis", exact=True).check()
        expect(self.page.locator("[data-restaurante-vazio]")).to_be_visible()
        self.page.get_by_label("Categoria do cardápio", exact=True).select_option("")
        expect(self.produto_botao()).to_be_visible()
        for largura in (320, 390, 821, 1440):
            self.page.set_viewport_size({"width": largura, "height": 900})
            self.page.evaluate("document.querySelector('.app').classList.remove('recolhida')")
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
            for seletor in (".pdv-painel", ".pdv-produtos", ".pdv-finalizar", "[data-restaurante-total]"):
                caixa = self.page.locator(seletor).bounding_box()
                self.assertGreaterEqual(caixa["x"], -1)
                self.assertLessEqual(caixa["x"] + caixa["width"], largura + 1)
            self.foto(f"restaurante-comanda-{largura}")

    def test_estorno_aparece_na_comanda_historico_e_cupom(self):
        adicionar_item(self.comanda, self.produto, 2, self.op)
        fechar_comanda(self.comanda, self.op, "caixa", self.forma)
        self.comanda.refresh_from_db()
        estornar_movimento(self.comanda.movimento_caixa, self.caixa, self.op, "Revisão fictícia", valor=Decimal("14"))
        self.abrir()
        expect(self.page.locator("[data-restaurante-financeiro]")).to_contain_text("Pagamento estornado")
        expect(self.page.locator("[data-restaurante-financeiro]")).to_contain_text("0,00")
        self.page.goto(self.url(reverse("restaurante:historico")))
        expect(self.page.get_by_role("row").filter(has_text=self.comanda.titulo)).to_contain_text("Pagamento estornado")
        self.page.goto(self.url(reverse("restaurante:cupom", args=[self.comanda.pk])))
        expect(self.page.locator(".cupom-pagamento")).to_have_text("Pagamento estornado")
        expect(self.page.locator(".cupom-soma")).to_contain_text("Estornado")
        expect(self.page.locator(".cupom-soma")).to_contain_text("Recebido líquido")
        self.assertEqual(saldo(self.produto, self.local), Decimal("18"))

    def test_desconto_integral_fecha_sem_inventar_recebimento(self):
        self.abrir()
        self.adicionar(2)
        fechar = self.page.locator("form.comanda-fechar")
        aviso_sem_cobranca = self.page.locator('[data-restaurante-sem-cobranca]')
        expect(aviso_sem_cobranca).to_be_hidden()
        fechar.locator('[name="desconto"]').fill("14")
        expect(self.page.locator('[data-restaurante-total]')).to_contain_text("0,00")
        expect(aviso_sem_cobranca).to_be_visible()
        fechar.locator('[name="desconto"]').fill("7")
        expect(aviso_sem_cobranca).to_be_hidden()
        fechar.locator('[name="desconto"]').fill("14")
        expect(aviso_sem_cobranca).to_be_visible()
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "fechada")
        self.assertIsNone(self.comanda.movimento_caixa_id)
        self.assertIsNone(self.comanda.forma_pagamento_id)
        self.assertEqual(saldo(self.produto, self.local), Decimal("18"))
        self.page.goto(self.url(reverse("restaurante:cupom", args=[self.comanda.pk])))
        expect(self.page.locator(".cupom-pagamento")).to_have_text("Sem valor a receber")
