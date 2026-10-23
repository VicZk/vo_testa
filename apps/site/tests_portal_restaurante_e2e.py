"""Pedido real no portal: ficha visível, erro preservado e retransmissão segura."""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    TipoUH,
    Usuario,
    registrar_entrada,
    saldo,
    salvar_ficha,
)
from apps.nucleo.modulos import Modulo
from apps.portal.services import get_acesso
from apps.reservas.models import Reserva
from apps.restaurante.models import Comanda, GrupoOpcaoCardapio, OpcaoCardapio

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class PortalRestauranteE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        for codigo in (Modulo.RESERVAS, Modulo.RESTAURANTE, Modulo.APPSITE):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.op = Usuario.objects.create_superuser(username="portal-restaurante-e2e", password="local-ficticio-123")
        tipo = TipoUH.objects.create(nome="Quarto do teste", tarifa_base=200)
        uh = UH.objects.create(numero="PORTAL-01", tipo=tipo)
        hospede = Pessoa.objects.create(nome="Hóspede fictício do teste")
        hoje = timezone.localdate()
        self.reserva = Reserva.objects.create(uh=uh, hospede=hospede, checkin=hoje,
            checkout=hoje + timedelta(days=1), valor_diaria=200, status="confirmada", criado_por=self.op)
        self.reserva.fazer_checkin(self.op)
        self.token = get_acesso(self.reserva.pk).token
        categoria = CategoriaProduto.objects.create(nome="Pratos do teste")
        self.local = LocalEstoque.objects.create(nome="Cozinha do teste", modulo="restaurante")
        self.ingrediente = Produto.objects.create(nome="Ingrediente do teste", categoria=categoria, unidade="kg")
        registrar_entrada(self.ingrediente, self.local, 1, 30, self.op)
        self.prato = Produto.objects.create(nome="Prato do teste", categoria=categoria, preco_venda=28, usa_ficha_tecnica=True)
        salvar_ficha(self.prato, [(self.ingrediente, Decimal("0.200"))], self.op)
        grupo = GrupoOpcaoCardapio.objects.create(produto=self.prato, nome="Ponto", minimo=1)
        self.opcao = OpcaoCardapio.objects.create(grupo=grupo, nome="Ao ponto")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True, animations="disabled")

    def test_formulario_real_preserva_chave_no_erro_e_reenvio_nao_duplica(self):
        self.page.goto(self.url(reverse("portal:home", args=[self.token])))
        formulario = self.page.locator("form").filter(has=self.page.locator('[name="chave_pedido"]'))
        chave = formulario.locator('[name="chave_pedido"]').input_value()
        self.assertEqual(str(UUID(chave)), chave)
        formulario.get_by_label(f"Quantidade de {self.prato.nome}", exact=True).fill("2")
        formulario.get_by_text(f"Preparo e observações · {self.prato.nome}", exact=True).click()
        formulario.get_by_label("Observações para a cozinha", exact=True).fill("Molho à parte")
        formulario.get_by_role("button", name="Enviar pedido ao quarto", exact=True).click()
        expect(self.page.get_by_text("Ponto: escolha entre 1 e 1 opção(ões).", exact=True)).to_be_visible()
        expect(formulario.locator('[name="chave_pedido"]')).to_have_value(chave)
        expect(formulario.get_by_label(f"Quantidade de {self.prato.nome}", exact=True)).to_have_value("2")
        expect(formulario.get_by_label("Observações para a cozinha", exact=True)).to_have_value("Molho à parte")
        self.assertFalse(Comanda.objects.exists())
        self.foto("portal-restaurante-erro-preservado-390")
        formulario.get_by_label("Ao ponto", exact=True).check()
        dados_enviados = formulario.evaluate("form => Object.fromEntries(new FormData(form))")
        formulario.get_by_role("button", name="Enviar pedido ao quarto", exact=True).click()
        expect(self.page.get_by_text("Pedido enviado!", exact=False)).to_be_visible()
        comanda = Comanda.objects.get()
        item = comanda.itens.get()
        self.assertEqual((item.quantidade, item.preco_unitario, comanda.total()), (2, 28, 56))
        self.assertEqual(item.observacoes, "Molho à parte")
        self.assertIn("Ao ponto", item.detalhe_preparo)
        self.assertEqual(saldo(self.ingrediente, self.local), Decimal("0.600"))
        self.assertNotEqual(formulario.locator('[name="chave_pedido"]').input_value(), chave)
        # Retransmite exatamente o corpo do formulário já enviado, com o mesmo CSRF,
        # para reproduzir a perda de resposta sem inventar uma nova intenção.
        resposta = self.page.request.post(self.url(reverse("portal:pedir", args=[self.token])), form=dados_enviados)
        self.assertEqual(resposta.status, 200)
        self.assertEqual(Comanda.objects.count(), 1)
        self.assertEqual(saldo(self.ingrediente, self.local), Decimal("0.600"))
        self.foto("portal-restaurante-pedido-enviado-390")
