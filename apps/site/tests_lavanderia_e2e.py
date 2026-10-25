"""Balcão da Lavanderia no navegador, ponta a ponta.

Receber roupa pelo chip «Amanhã» → lançar 2 peças → lançar 1,5 kg pelo campo de peso
→ avançar duas vezes PELO CARTÃO DA FILA → entregar no caixa → conferir o cupom.
Sem isto, a regra nova («só entrega o que está pronto») e o lançamento a granel não são
exercitados em navegador nenhum. Depois, o lote da rouparia (uma transação, tudo ou
nada) e as quatro larguras com o menu ABERTO.

Todos os dados são fictícios; a cobrança usa o caixa do próprio setor.
"""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.lavanderia.models import ItemEnxoval, MovimentoEnxoval, OrdemLavanderia, ServicoLavanderia
from apps.lavanderia.services import adquirir, saldo_enxoval
from apps.nucleo.models import FormaPagamento, ModuloContratado, SessaoCaixa, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class LavanderiaBalcaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="lavanderia-balcao-qa",
                                                   password="local-ficticio-123")
        for codigo in (Modulo.ESTOQUE, Modulo.LAVANDERIA):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.dinheiro = FormaPagamento.objects.create(nome="Dinheiro fictício", tipo="dinheiro")
        SessaoCaixa.objects.create(operador=self.op, modulo="lavanderia",
                                   fundo_troco=Decimal("100"))
        self.camisa = ServicoLavanderia.objects.create(nome="Camisa social QA",
                                                       preco=Decimal("8.00"))
        self.quilo = ServicoLavanderia.objects.create(
            nome="Roupa por quilo QA", preco=Decimal("22.00"),
            unidade=ServicoLavanderia.Unidade.KG)
        self.lencol = ItemEnxoval.objects.create(nome="Lençol fictício QA", minimo=10,
                                                 por_faxina=1)
        self.toalha = ItemEnxoval.objects.create(nome="Toalha fictícia QA", minimo=10,
                                                 por_faxina=2)
        for item in (self.lencol, self.toalha):
            adquirir(item, 12, self.op)
        self.client.force_login(self.op)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")

    def foto(self, nome):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True,
                                 animations="disabled")

    def enviar(self, alvo):
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            alvo.click()

    def test_recebe_lanca_peso_avanca_pela_fila_e_cobra_no_caixa(self):
        p = self.page
        p.goto(self.url(reverse("lavanderia:painel")))

        # 1 — receber roupa: identificação + chip «Amanhã» (o caminho comum não
        # passa pelo <input type=date>, que o Chrome em inglês mostra mm/dd/yyyy).
        receber = p.locator(".lav-receber")
        if receber.get_by_role("button", name="Cliente avulso", exact=True).count():
            receber.get_by_role("button", name="Cliente avulso", exact=True).click()
        receber.locator('[name="rotulo"]').fill("Quarto 9 QA")
        receber.get_by_role("button", name="Amanhã", exact=True).click()
        amanha = timezone.localdate() + timedelta(days=1)
        expect(receber.locator('[name="prazo"]')).to_have_value(amanha.isoformat())
        self.foto("lavanderia-receber-390")
        self.enviar(receber.get_by_role("button", name="Receber roupa", exact=True))

        ordem = OrdemLavanderia.objects.get(rotulo="Quarto 9 QA")
        self.assertEqual(ordem.prazo, amanha)
        self.assertIn(reverse("lavanderia:ordem", args=[ordem.pk]), p.url)

        # 2 — duas peças: um toque no cartão lança uma.
        cartao = p.locator(".pdv-produto").filter(has_text=self.camisa.nome)
        cartao.click()
        cartao.click()
        expect(p.locator("#ordem-itens")).to_contain_text("16,00")

        # 3 — serviço a granel não soma 1: abre o campo de peso (com vírgula).
        granel = p.locator(".lav-granel").filter(has_text=self.quilo.nome)
        granel.locator(".pdv-produto").click()
        granel.locator('[name="quantidade"]').fill("1,5")
        granel.get_by_role("button", name="Lançar", exact=True).click()
        expect(p.locator("#ordem-itens")).to_contain_text("33,00")
        self.assertEqual(ordem.itens.get(servico=self.quilo).quantidade, Decimal("1.500"))

        # 4 — o resumo da aba «Cesta» acompanha mesmo com a cesta fora da tela.
        expect(p.locator("#lav-resumo")).to_contain_text("2 peças")
        expect(p.locator("#lav-resumo")).to_contain_text("49,00")

        # 5 — o stepper DEFINE a quantidade (não soma).
        p.locator('.pdv-etapas button:has-text("Cesta")').click()
        linha = p.locator(".pdv-item").filter(has_text=self.camisa.nome)
        linha.get_by_role("button", name=f"Aumentar {self.camisa.nome}", exact=True).click()
        expect(p.locator("#ordem-itens .pdv-total")).to_contain_text("57,00")
        self.assertEqual(ordem.itens.get(servico=self.camisa).quantidade, Decimal("3"))

        # 6 — cobrar antes de ficar pronta é exceção: fica atrás do disclosure.
        expect(p.locator('#lav-cobrar [name="confirmar"]')).to_have_count(1)

        # 7 — avançar DUAS vezes pelo cartão da fila, SEM SAIR da fila: o segundo toque
        # é dado na página em que o primeiro caiu (é isso que rende no tablet).
        p.goto(self.url(reverse("lavanderia:painel") + "?etapa=recebida"))
        for passo, status in (("Enviar para lavagem", OrdemLavanderia.Status.LAVANDO),
                              ("Marcar como pronta", OrdemLavanderia.Status.PRONTA)):
            if passo == "Marcar como pronta":
                p.goto(self.url(reverse("lavanderia:painel")))
            fila = p.locator(".lav-ordem").filter(has_text="Quarto 9 QA")
            self.enviar(fila.get_by_role("button", name=passo, exact=True))
            ordem.refresh_from_db()
            self.assertEqual(ordem.status, status, passo)
            # O cartão volta para a FILA (com o filtro de etapa), não para a ordem.
            self.assertNotIn(reverse("lavanderia:ordem", args=[ordem.pk]), p.url, passo)
            self.assertIn(reverse("lavanderia:painel"), p.url, passo)

        # 8 — pronta: a cobrança abre sozinha e não pede mais confirmação.
        p.goto(self.url(reverse("lavanderia:ordem", args=[ordem.pk])))
        cobrar = p.locator("#lav-cobrar")
        expect(cobrar.locator('[name="confirmar"]')).to_have_count(0)
        expect(p.locator(".lav-aviso-pronta")).to_contain_text("Aviso de roupa pronta")
        cobrar.locator('[name="forma"]').select_option(str(self.dinheiro.pk))
        self.foto("lavanderia-cobranca-390")
        self.enviar(cobrar.get_by_role("button", name="Entregar e cobrar", exact=True))

        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.ENTREGUE)
        self.assertEqual(ordem.total(), Decimal("57.00"))
        self.assertEqual(ordem.movimento_caixa.valor, Decimal("57.00"))

        # 9 — o cupom de 80 mm é o único recibo da casa.
        p.goto(self.url(reverse("lavanderia:cupom", args=[ordem.pk])))
        expect(p.locator(".cupom")).to_contain_text("57,00")
        expect(p.locator(".cupom")).to_contain_text("Dinheiro fictício")
        self.foto("lavanderia-cupom-390")

    def test_lote_da_rouparia_move_as_linhas_marcadas_numa_transacao(self):
        p = self.page
        p.goto(self.url(reverse("lavanderia:rouparia")))
        caixas = p.locator('.lav-rouparia input[type="checkbox"]')
        caixas.nth(0).check()
        caixas.nth(1).check()
        lote = p.locator(".lav-lote")
        expect(lote).to_be_visible()
        expect(lote).to_contain_text("2 itens selecionados")
        lote.locator('[name="quantidade"]').fill("4")
        self.foto("lavanderia-lote-390")
        self.enviar(lote.get_by_role("button", name="Distribuir", exact=True))
        for item in (self.lencol, self.toalha):
            self.assertEqual(saldo_enxoval(item, MovimentoEnxoval.Estado.EM_USO), 4)

        # Saldo insuficiente em QUALQUER linha derruba o lote inteiro — e a recusa
        # VOLTA COM AS LINHAS MARCADAS (`data-preservar-erros`): antes o redirect
        # limpava as caixas e a quantidade, e era preciso remarcar tudo.
        antes = MovimentoEnxoval.objects.count()
        caixas = p.locator('.lav-rouparia input[type="checkbox"]')
        caixas.nth(0).check()
        caixas.nth(1).check()
        lote = p.locator(".lav-lote")
        lote.locator('[name="quantidade"]').fill("999")
        lote.get_by_role("button", name="Distribuir", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("Saldo insuficiente")
        self.assertEqual(MovimentoEnxoval.objects.count(), antes)
        expect(lote).to_contain_text("2 itens selecionados")
        expect(lote.locator('[name="quantidade"]')).to_have_value("999")
        p.locator(".lav-lote").get_by_role("button", name="Limpar seleção",
                                           exact=True).click()

        # Tocar no número de um estado prepara o movimento que SAI dele.
        p.locator(".lav-cel-acao").filter(has_text="4").first.click()
        expect(p.locator("#form-mover [name=acao]")).to_have_value("coletar")
        expect(p.locator("#form-mover [name=quantidade]")).to_have_value("4")

    def test_as_cinco_telas_cabem_em_320_390_821_e_1440_com_o_menu_aberto(self):
        p = self.page
        telas = ("lavanderia:painel", "lavanderia:rouparia", "lavanderia:extrato",
                 "lavanderia:servicos", "lavanderia:historico")
        for nome in telas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 900})
                    p.goto(self.url(reverse(nome)))
                    # A largura útil muda com o menu: a conferência é com ele ABERTO.
                    p.evaluate("document.querySelector('.app')?.classList.remove('recolhida')")
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),
                                         largura + 1, f"{nome} rolou de lado")
                    limite = p.locator(".conteudo").bounding_box()
                    for seletor in (".quadro", ".lav-fila", ".kpis", ".painel-bloco"):
                        alvo = p.locator(seletor).first
                        if not alvo.count():
                            continue
                        caixa = alvo.bounding_box()
                        self.assertGreaterEqual(caixa["x"], limite["x"] - 1, seletor)
                        self.assertLessEqual(caixa["x"] + caixa["width"],
                                             limite["x"] + limite["width"] + 1, seletor)
                    self.foto(f"{nome.split(':')[1]}-{largura}")
