"""Filtros compactos continuam operáveis e não confundem o contexto da operação."""

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
    MovimentoCaixa,
    Produto,
    SessaoCaixa,
    Usuario,
    registrar_entrada,
)

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class ControlesCompactosE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.usuario = Usuario.objects.create_superuser(username="controles-ui", password="forte-123-abc")
        for codigo in ("reservas", "loja", "estoque", "restaurante", "lavanderia", "marketing"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.sessoes = {}
        for codigo in ("nucleo", "reservas", "loja", "restaurante", "lavanderia"):
            self.sessoes[codigo] = SessaoCaixa.objects.create(
                operador=self.usuario, modulo=codigo, fundo_troco=Decimal("100.00"))
        self.forma = FormaPagamento.objects.create(nome="Dinheiro fictício", tipo="dinheiro")
        self.local = LocalEstoque.objects.create(nome="Balcão de teste", modulo="loja")
        self.produtos = []
        for nome in ("Bebidas", "Alimentos", "Doces", "Lembranças", "Higiene", "Outros"):
            categoria = CategoriaProduto.objects.create(nome=nome)
            produto = Produto.objects.create(
                nome=f"Produto fictício {nome}", categoria=categoria, preco_venda=Decimal("12.50"))
            registrar_entrada(produto, self.local, 10, Decimal("2.00"), self.usuario)
            self.produtos.append(produto)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(pasta / f"{nome}.png"))

    def test_relatorio_aplica_mes_e_ano_juntos_e_exporta_o_mes_exibido(self):
        p = self.page
        p.goto(self.url(reverse("marketing:relatorio")))
        p.get_by_label("Mês", exact=True).select_option("9")
        p.get_by_label("Ano", exact=True).select_option("2025")
        p.get_by_role("button", name="Aplicar período", exact=True).click()
        expect(p.get_by_label("Mês", exact=True)).to_have_value("9")
        expect(p.get_by_label("Ano", exact=True)).to_have_value("2025")
        expect(p.locator(".mk-periodo")).to_contain_text("Setembro/2025")
        expect(p.get_by_role("link", name="Exportar CSV", exact=True)).to_have_attribute(
            "href", "?mes=9&ano=2025&export=csv")
        with p.expect_download() as download:
            p.get_by_role("link", name="Exportar CSV", exact=True).click()
        self.assertIsNone(download.value.failure())
        p.evaluate("window.__impresso = false; window.print = () => { window.__impresso = true; }")
        p.get_by_role("button", name="Imprimir", exact=True).click()
        self.assertTrue(p.evaluate("window.__impresso"))
        for largura in (320, 390, 768, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            caixas = p.locator(".mkt-abas a").evaluate_all(
                "els => els.map(el => {const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height};})")
            self.assertTrue(all(c["h"] >= 44 and c["x"] >= 0 and c["x"] + c["w"] <= largura + 1 for c in caixas))
            for indice, caixa in enumerate(caixas):
                for outra in caixas[indice + 1:]:
                    self.assertTrue(caixa["x"] + caixa["w"] <= outra["x"] + 1
                                    or outra["x"] + outra["w"] <= caixa["x"] + 1
                                    or caixa["y"] + caixa["h"] <= outra["y"] + 1
                                    or outra["y"] + outra["h"] <= caixa["y"] + 1,
                                    (caixa, outra))
            self.foto(f"marketing-relatorio-{largura}")

    def test_trocar_caixa_muda_destino_e_registro_vai_ao_caixa_escolhido(self):
        p = self.page
        p.goto(self.url(reverse("caixa") + "?modulo=lavanderia"))
        p.get_by_label("Caixa em atendimento", exact=True).select_option("loja")
        p.get_by_role("button", name="Trocar caixa", exact=True).click()
        expect(p.get_by_label("Caixa em atendimento", exact=True)).to_have_value("loja")
        form = p.locator('form[aria-labelledby="caixa-registrar-titulo"]')
        expect(form.locator('[name="modulo"]')).to_have_value("loja")
        form.locator('[name="tipo"]').select_option("reforco")
        form.locator('[name="valor"]').fill("25.00")
        form.locator('[name="descricao"]').fill("Troco de teste no caixa escolhido")
        form.get_by_role("button", name="Registrar", exact=True).click()
        expect(p.locator(".caixa-historico")).to_contain_text("Troco de teste no caixa escolhido")
        movimento = MovimentoCaixa.objects.get(descricao="Troco de teste no caixa escolhido")
        self.assertEqual(movimento.sessao_id, self.sessoes["loja"].pk)
        self.assertEqual(movimento.valor, Decimal("25.00"))
        self.assertFalse(self.sessoes["lavanderia"].movimentos.exists())
        for largura in (320, 390, 768, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            self.foto(f"caixa-{largura}")

    def test_categorias_da_loja_rolam_sem_rolar_pagina_e_preservam_carrinho(self):
        p = self.page
        p.goto(self.url(reverse("loja:pdv")))
        expect(p.locator(".pdv-produto")).to_have_count(6)
        categorias = p.locator(".pdv-categorias")
        for largura in (320, 390, 768, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            if largura in (320, 390):
                linhas = categorias.locator("button").evaluate_all("els => els.map(el => el.getBoundingClientRect().top)")
                self.assertLess(max(linhas) - min(linhas), 2)
                self.assertTrue(categorias.evaluate("el => el.scrollWidth > el.clientWidth"))
            self.foto(f"loja-{largura}")
        p.set_viewport_size({"width": 390, "height": 900})
        categoria = categorias.get_by_role("button", name="Outros 1", exact=True)
        categoria.focus()
        categoria.press("Enter")
        expect(categoria).to_have_attribute("aria-pressed", "true")
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_role("button", name="Adicionar Produto fictício Outros ao carrinho", exact=True).click()
        p.get_by_label("Buscar produto", exact=True).fill("nao existe")
        expect(p.locator(".pdv-lista-vazia")).to_be_visible()
        p.get_by_role("button", name="Limpar filtros", exact=True).click()
        expect(p.locator(".pdv-produto")).to_have_count(6)
        p.locator(".pdv-etapas button").filter(has_text="Carrinho").click()
        expect(p.locator(".pdv-item-nome")).to_have_text("Produto fictício Outros")
        expect(p.locator(".pdv-total strong")).to_have_text("R$ 12,50")
