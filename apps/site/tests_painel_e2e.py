"""Recepção no navegador real: saldo legível e ação preservando as etapas da estadia."""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    ConfiguracaoReservas,
    ModuloContratado,
    NaturezaFiscal,
    Pessoa,
    TipoUH,
    Usuario,
)
from apps.nucleo.modulos import Modulo
from apps.reservas.models import (
    Adiantamento,
    ContaHospedagem,
    GrupoReserva,
    LancamentoConta,
    PagamentoConta,
    Reserva,
)

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(FNRH_BLOQUEAR_CHECKIN=False, ECA_BLOQUEAR_CHECKIN=False)
class PainelOperacionalE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        reservas, _ = ModuloContratado.objects.update_or_create(
            codigo=Modulo.RESERVAS, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_user(
            username="recepcao-painel-e2e", password="forte-123-abc")
        self.usuario.modulos.add(reservas)
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={
            "feriados_automaticos": False, "iss_aliquota": Decimal("0.00"),
            "taxa_turismo_diaria": Decimal("0.00"),
        })
        self.tipo = TipoUH.objects.create(
            nome="Suíte com varanda e vista para o lago", tarifa_base=Decimal("300.00"))
        self.hoje = timezone.localdate()
        self.sequencia = 0
        self.chegada = self.reserva(nome="Maria Aparecida de Albuquerque e Silva — Teste fictício")
        Adiantamento.objects.create(reserva=self.chegada, valor=Decimal("125.00"))
        self.chegada_credito = self.reserva(nome="Ana Crédito — Teste fictício")
        Adiantamento.objects.create(reserva=self.chegada_credito, valor=Decimal("650.00"))
        self.saida = self.reserva(saida=True, nome="João Saldo — Teste fictício")
        LancamentoConta.objects.create(
            conta=self.saida.conta, tipo=LancamentoConta.Tipo.CONSUMO,
            natureza=NaturezaFiscal.CONSUMO, descricao="Consumo fictício",
            valor=Decimal("128.50"), criado_por=self.usuario)
        self.saida_zerada = self.reserva(saida=True, nome="Carlos Sem saldo — Teste fictício")
        self.saida_credito = self.reserva(saida=True, nome="Beatriz Crédito — Teste fictício")
        PagamentoConta.objects.create(conta=self.saida_credito.conta, valor=Decimal("45.00"))
        titular = Pessoa.objects.create(nome="Titular do Grupo — Teste fictício")
        grupo = GrupoReserva.objects.create(
            rotulo="Grupo Teste fictício", titular=titular, checkin=self.hoje,
            checkout=self.hoje + timedelta(days=2), criado_por=self.usuario)
        ContaHospedagem.objects.create(grupo=grupo)
        self.chegada_grupo = self.reserva(nome="Lúcia Grupo — Teste fictício", grupo=grupo)
        self.saida_grupo = self.reserva(saida=True, nome="Pedro Grupo — Teste fictício", grupo=grupo)
        self.saida_sem_conta = self.reserva(saida=True, com_conta=False, nome="Conferir Conta — Teste fictício")
        self.page.set_viewport_size({"width": 1440, "height": 1000})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def reserva(self, *, nome, saida=False, com_conta=True, **kwargs):
        self.sequencia += 1
        uh = UH.objects.create(numero=f"P{self.sequencia:02d}", tipo=self.tipo)
        reserva = Reserva.objects.create(
            uh=uh, hospede=Pessoa.objects.create(nome=nome),
            checkin=self.hoje - timedelta(days=2) if saida else self.hoje,
            checkout=self.hoje if saida else self.hoje + timedelta(days=2),
            status=Reserva.Status.HOSPEDADA if saida else Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("300.00"), criado_por=self.usuario, **kwargs)
        if saida and com_conta:
            ContaHospedagem.objects.create(reserva=reserva)
        return reserva

    def abrir(self):
        self.page.goto(self.url(reverse("dashboard")), wait_until="load")
        expect(self.page.get_by_role("region", name="Chegadas de hoje")).to_be_visible()
        self.page.evaluate("() => document.fonts.ready")

    def linha(self, reserva):
        return self.page.locator(f'li[data-reserva-id="{reserva.pk}"]')

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.locator(".painel-estadias").screenshot(path=str(pasta / f"painel-{nome}.png"))
            if nome in ("320", "390"):
                # O recorte longo de elemento pode capturar a barra fixa no meio.
                # Conserva também página e viewports reais, sem ocultar controles.
                self.page.evaluate("window.scrollTo(0, 0)")
                self.page.screenshot(path=str(pasta / f"painel-{nome}-pagina.png"), full_page=True)
                for secao in ("chegadas", "saidas"):
                    self.page.locator(f"#{secao}-hoje").evaluate("el => el.scrollIntoView({block: 'start'})")
                    self.page.screenshot(path=str(pasta / f"painel-{nome}-{secao}.png"))

    def test_identidade_saldo_e_acoes_cabem_de_320_a_2560_pixels(self):
        self.abrir()
        expect(self.linha(self.chegada)).to_contain_text(self.chegada.hospede.nome)
        expect(self.linha(self.chegada)).to_contain_text("R$ 475,00")
        expect(self.linha(self.saida)).to_contain_text("R$ 128,50")
        expect(self.linha(self.saida_zerada)).to_contain_text("Sem saldo")
        expect(self.linha(self.chegada_credito)).to_contain_text("Crédito")
        expect(self.linha(self.chegada_credito)).to_contain_text("R$ 50,00")
        expect(self.linha(self.saida_credito)).to_contain_text("R$ 45,00")
        expect(self.linha(self.chegada_grupo)).to_contain_text("Cobrança no grupo")
        expect(self.linha(self.saida_grupo)).to_contain_text("Consumos do quarto")
        expect(self.linha(self.saida_grupo)).to_contain_text("Diárias na conta do grupo")
        expect(self.linha(self.saida_sem_conta)).to_contain_text("Conferir conta")
        expect(self.page.locator(".painel-estadias")).not_to_contain_text("Quitado")

        for largura in (320, 390, 768, 820, 821, 1440, 2560):
            with self.subTest(largura=largura):
                self.page.set_viewport_size({"width": largura, "height": 1000})
                medidas = self.page.locator(".painel-estadias").evaluate("""painel => {
                  const rect = el => { const r=el.getBoundingClientRect(); return {
                    left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}; };
                  return {largura:document.documentElement.clientWidth,
                    documento:document.documentElement.scrollWidth,
                    painel:rect(painel), linhas:[...painel.querySelectorAll('[data-reserva-id]')].map(el => ({
                      caixa:rect(el), partes:[...el.children].map(rect),
                      botoes:[...el.querySelectorAll('a')].map(rect)
                    }))};
                }""")
                self.assertLessEqual(medidas["documento"], largura + 1, medidas)
                self.assertGreaterEqual(medidas["painel"]["left"], -1, medidas)
                self.assertLessEqual(medidas["painel"]["right"], largura + 1, medidas)
                for linha in medidas["linhas"]:
                    for parte in linha["partes"]:
                        self.assertGreaterEqual(parte["left"], linha["caixa"]["left"] - 1, linha)
                        self.assertLessEqual(parte["right"], linha["caixa"]["right"] + 1, linha)
                    for botao in linha["botoes"]:
                        self.assertGreaterEqual(botao["height"], 43, linha)
                    for indice, primeira in enumerate(linha["partes"]):
                        for segunda in linha["partes"][indice + 1:]:
                            sobrepoe_x = min(primeira["right"], segunda["right"]) - max(primeira["left"], segunda["left"])
                            sobrepoe_y = min(primeira["bottom"], segunda["bottom"]) - max(primeira["top"], segunda["top"])
                            self.assertFalse(sobrepoe_x > 1 and sobrepoe_y > 1, linha)
                if largura in (320, 390, 1440, 2560):
                    self.foto(str(largura))

    def test_checkin_e_checkout_abrem_confirmacao_e_concluem_fluxos_existentes(self):
        self.abrir()
        self.page.set_viewport_size({"width": 390, "height": 844})
        acao = self.linha(self.chegada).get_by_role("link", name="Check-in", exact=True)
        expect(acao).to_have_accessible_description(self.chegada.hospede.nome)
        acao.focus()
        acao.press("Enter")
        expect(self.page).to_have_url(self.url(reverse("reservas:detalhe", args=[self.chegada.pk])) + "#acoes-estadia")
        self.chegada.refresh_from_db()
        self.assertEqual(self.chegada.status, Reserva.Status.CONFIRMADA)
        with patch("apps.reservas.services.enviar_fnrh") as envio:
            self.page.get_by_role("button", name="Fazer entrada (check-in)", exact=True).click()
            expect(self.page.get_by_role("button", name="Fazer saída (check-out)", exact=True)).to_be_visible()
            envio.assert_called_once()
        self.chegada.refresh_from_db()
        self.assertEqual(self.chegada.status, Reserva.Status.HOSPEDADA)

        self.abrir()
        expect(self.linha(self.chegada)).to_have_count(0)
        self.linha(self.saida_zerada).get_by_role("link", name="Check-out", exact=True).click()
        self.saida_zerada.refresh_from_db()
        self.assertEqual(self.saida_zerada.status, Reserva.Status.HOSPEDADA)
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Fazer saída (check-out)", exact=True).click()
        expect(self.page.get_by_role("button", name="Fazer saída (check-out)", exact=True)).to_have_count(0)
        self.saida_zerada.refresh_from_db()
        self.assertEqual(self.saida_zerada.status, Reserva.Status.CHECKOUT)
        self.abrir()
        expect(self.linha(self.saida_zerada)).to_have_count(0)

    def test_checkout_sem_saldo_lancado_mostra_e_preserva_pendencia_de_consumo(self):
        from apps.nucleo.models import CategoriaProduto, LocalEstoque, Produto
        from apps.restaurante.models import Comanda, ItemComanda

        local = LocalEstoque.objects.create(nome="Restaurante Painel", modulo="restaurante")
        produto = Produto.objects.create(
            nome="Água Teste", categoria=CategoriaProduto.objects.create(nome="Bebidas Teste"))
        comanda = Comanda.objects.create(
            local=local, conta=self.saida_zerada.conta, criado_por=self.usuario)
        ItemComanda.objects.create(
            comanda=comanda, produto=produto, descricao="Água Teste",
            natureza=NaturezaFiscal.CONSUMO, quantidade=Decimal("1.000"),
            preco_unitario=Decimal("8.00"))
        self.abrir()
        expect(self.linha(self.saida_zerada)).to_contain_text("Sem saldo")
        self.linha(self.saida_zerada).get_by_role("link", name="Check-out", exact=True).click()
        expect(self.page.get_by_text("Consumos pendentes antes da saída", exact=True)).to_be_visible()
        expect(self.page.get_by_role("button", name="Fazer saída (check-out)", exact=True)).to_be_disabled()
        self.saida_zerada.refresh_from_db()
        self.assertEqual(self.saida_zerada.status, Reserva.Status.HOSPEDADA)

    def test_totais_limite_e_acesso_a_lista_completa(self):
        for indice in range(6):
            self.reserva(nome=f"Chegada extra {indice} — Teste fictício")
        self.abrir()
        secao = self.page.get_by_role("region", name="Chegadas de hoje")
        expect(secao.locator("[data-reserva-id]")).to_have_count(8)
        expect(secao).to_contain_text("Mostrando 8 de 9 reservas previstas para hoje.")
        expect(secao.locator(".painel-estadias-total")).to_have_text("9")
        secao.get_by_role("link", name="Ver reservas").click()
        expect(self.page).to_have_url(self.url(reverse("reservas:lista")))

    def test_estados_vazios_nao_exibem_acoes_de_estadias(self):
        Reserva.objects.all().update(status=Reserva.Status.CHECKOUT)
        self.abrir()
        expect(self.page.get_by_role("region", name="Chegadas de hoje")).to_contain_text("Sem chegadas previstas para hoje.")
        expect(self.page.get_by_role("region", name="Saídas de hoje")).to_contain_text("Sem saídas previstas para hoje.")
        expect(self.page.locator(".painel-estadias [data-reserva-id]")).to_have_count(0)
        expect(self.page.locator(".painel-estadia-acao")).to_have_count(0)
