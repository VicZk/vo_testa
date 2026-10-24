"""Comanda preenchida: leitura, pedidos, fechamento e permissões em largura útil."""

import json
import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    FormaPagamento,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    SessaoCaixa,
    TipoUH,
    Usuario,
    registrar_entrada,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.reservas.models import ContaHospedagem, Reserva
from apps.restaurante.models import GrupoOpcaoCardapio, Mesa, OpcaoCardapio
from apps.restaurante.services import abrir_comanda, adicionar_item, alterar_preparo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class ComandaOrganizacaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        cache.clear()
        self.gerente = Usuario.objects.create_superuser(username="gerente-comanda-qa", password="local-ficticio-123")
        self.garcom = Usuario.objects.create_user(
            username="garcom-comanda-qa", password="local-ficticio-123")
        for codigo in (Modulo.RESTAURANTE, Modulo.RESERVAS):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.garcom.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESTAURANTE))
        self.forma = FormaPagamento.objects.create(nome="Dinheiro da conferência", tipo="dinheiro")
        for usuario in (self.gerente, self.garcom):
            SessaoCaixa.objects.create(operador=usuario, modulo="restaurante", fundo_troco=100)
        self.local = LocalEstoque.objects.create(nome="Cozinha da conferência", modulo="restaurante")
        bebidas = CategoriaProduto.objects.create(nome="Bebidas da conferência")
        pratos = CategoriaProduto.objects.create(nome="Pratos e porções")
        self.produtos = []
        for nome, preco, categoria in (
            ("Porção de peixe crocante com molho especial da casa", "68.90", pratos),
            ("Hambúrguer artesanal com queijo e salada", "32.50", pratos),
            ("Água mineral da conferência", "7.00", bebidas),
            ("Suco natural de laranja sem açúcar", "12.00", bebidas),
            ("Caipirinha de limão", "22.00", bebidas),
            ("Batatas rústicas com ervas", "24.00", pratos),
        ):
            produto = Produto.objects.create(nome=nome, preco_venda=preco, categoria=categoria)
            registrar_entrada(produto, self.local, 20, Decimal("1.00"), self.gerente)
            self.produtos.append(produto)
        self.peixe, self.hamburguer, self.agua = self.produtos[:3]
        grupo = GrupoOpcaoCardapio.objects.create(produto=self.peixe, nome="Acompanhamento")
        opcao = OpcaoCardapio.objects.create(grupo=grupo, nome="Molho de ervas separado", adicional="4.50")
        self.mesa = Mesa.objects.create(nome="Guarda-sol 4 · Família da conferência")
        self.outra_mesa = Mesa.objects.create(nome="Bar da piscina")
        self.comanda = abrir_comanda(self.gerente, self.local, mesa=self.mesa)
        self.observacao = "Sem pimenta. Servir primeiro para as crianças; o molho deve vir em recipiente separado."
        adicionar_item(self.comanda, self.peixe, 2, self.gerente, opcoes=[opcao.pk], observacoes=self.observacao)
        self.em_preparo = adicionar_item(
            self.comanda, self.hamburguer, 1, self.gerente,
            observacoes="Carne ao ponto, sem cebola; entregar no guarda-sol próximo à piscina infantil.")
        alterar_preparo(self.em_preparo, "preparando", self.gerente, versao=self.em_preparo.versao)
        adicionar_item(self.comanda, self.agua, 3, self.gerente, observacoes="Uma garrafa sem gelo.")
        tipo = TipoUH.objects.create(nome="Suíte da conferência", tarifa_base="300.00")
        quarto = UH.objects.create(numero="QA 01", tipo=tipo)
        pessoa = Pessoa.objects.create(nome="Ana Clara da Conferência")
        hoje = timezone.localdate()
        reserva = Reserva.objects.create(
            uh=quarto, hospede=pessoa, status="hospedada", checkin=hoje,
            checkout=hoje + timedelta(days=2), valor_diaria="300.00", criado_por=self.gerente)
        self.conta = ContaHospedagem.objects.create(reserva=reserva)
        self.entrar(self.gerente)
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")
        self.erros = []
        self.page.on("pageerror", lambda erro: self.erros.append(str(erro)))
        self.evidencias = []

    def tearDown(self):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            Path(pasta).mkdir(parents=True, exist_ok=True)
            (Path(pasta) / f"{self._testMethodName}.json").write_text(
                json.dumps(self.evidencias, ensure_ascii=False, indent=2), encoding="utf-8")
        super().tearDown()

    def entrar(self, usuario):
        self.client.force_login(usuario)
        self.page.context.clear_cookies()
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME, "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])

    def abrir(self, largura=390, trilho=False):
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse("restaurante:comanda", args=[self.comanda.pk])))
        self.assertEqual(resposta.status, 200)
        self.page.evaluate("document.fonts.ready")
        expect(self.page.locator(".pdv-restaurante")).to_have_class("pdv pdv-restaurante comanda-navegavel")
        if largura > 820:
            if self.page.locator(".app").evaluate("el=>el.classList.contains('recolhida')") != trilho:
                self.page.locator(".sidebar-toggle").click()
            self.page.wait_for_function("""trilho => {
                const el = document.querySelector('.app'), s = getComputedStyle(el);
                const alvo = parseFloat(s.getPropertyValue(trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                return el.classList.contains('recolhida') === trilho &&
                    Math.abs(parseFloat(s.gridTemplateColumns) - alvo) < .1;
            }""", arg=trilho)

    def painel(self, nome):
        link = self.page.locator(f'.restaurante-atalhos [data-comanda-abrir="{nome}"]')
        if link.is_visible():
            link.click()
            menu = self.page.locator(".restaurante-atalhos").bounding_box()
            alvo = self.page.locator("#restaurante-" + nome).bounding_box()
            self.assertGreaterEqual(alvo["y"], menu["y"] + menu["height"] - 1)
        expect(self.page.locator("#restaurante-" + nome)).to_be_visible()

    def conferir_geometria(self, nome, largura, trilho):
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        medidas = self.page.locator(
            ".comanda-cabecalho, .restaurante-atalhos, .pdv-produtos, .pdv-painel, .pdv-item, "
            ".pdv-finalizar, .comanda-extras, .comanda-extra-bloco, .pedido-observacao, "
            ".comanda-fechar input, .comanda-fechar select"
        ).evaluate_all("""els => els.filter(el => el.checkVisibility()).map(el => {
            const r = el.getBoundingClientRect();
            return {classe:el.className, left:r.left, right:r.right,
                    horizontal:el.scrollWidth-el.clientWidth};
        })""")
        for medida in medidas:
            self.assertGreaterEqual(medida["left"], -1, medida)
            self.assertLessEqual(medida["right"], largura + 1, medida)
            self.assertLessEqual(medida["horizontal"], 1, medida)
        self.assertEqual(self.erros, [])
        self.evidencias.append({"painel": nome, "largura": largura, "trilho": trilho, "medidas": medidas})
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            arquivo = f"{self._testMethodName}-{nome}-{largura}-{'trilho' if trilho else 'aberta'}"
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(Path(pasta) / f"{arquivo}.png"), full_page=True)

    def test_comanda_preenchida_organiza_itens_cardapio_e_fechamento_em_cinco_estados(self):
        for largura, trilho in self.ESTADOS:
            self.abrir(largura, trilho)
            expect(self.page.locator(".pdv-painel")).to_be_visible()
            expect(self.page.locator(".pdv-item")).to_have_count(3)
            expect(self.page.locator(".pdv-item").first).to_contain_text(self.observacao)
            expect(self.page.locator(".pdv-item").first).to_contain_text("Molho de ervas separado")
            expect(self.page.locator("[data-restaurante-total]")).to_contain_text("200,30")
            self.assertTrue(self.page.locator(".pdv-carrinho").evaluate("el=>el.scrollHeight<=el.clientHeight+1"))
            expect(self.page.get_by_role("button", name="Conta do quarto", exact=True)).to_be_visible()
            self.conferir_geometria("conta", largura, trilho)
            self.painel("cardapio")
            expect(self.page.locator("[data-restaurante-produto]")).to_have_count(6)
            self.conferir_geometria("cardapio", largura, trilho)
            if largura <= 820:
                expect(self.page.locator(".comanda-barra-toque")).to_be_visible()
                self.page.locator(".comanda-barra-toque").click()
                expect(self.page.locator(".pdv-painel")).to_be_visible()
                expect(self.page.locator(".pdv-produtos")).to_be_hidden()
            self.painel("conta")
            self.page.locator(".comanda-extras > summary").click()
            expect(self.page.get_by_label("Estadia vinculada", exact=True)).to_be_visible()
            expect(self.page.get_by_label("Mesa, guarda-sol ou bar", exact=True)).to_be_visible()
            self.conferir_geometria("mais-acoes", largura, trilho)

    def test_adicionar_editar_e_remover_preserva_observacao_estoque_e_total(self):
        self.abrir()
        self.painel("cardapio")
        self.page.locator(".pdv-produto").filter(has_text=self.agua.nome).click()
        dialogo = self.page.get_by_role("dialog")
        dialogo.get_by_label("Quantidade", exact=False).fill("2")
        observacao = "Entregar depois do prato principal, com dois copos separados."
        dialogo.get_by_label("Observações", exact=False).fill(observacao)
        dialogo.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(dialogo).to_be_hidden()
        self.page.locator(".comanda-barra-toque").click()
        pedido = self.page.locator(".pdv-item").filter(has_text=observacao)
        expect(pedido).to_contain_text("14,00")
        expect(self.page.locator("[data-restaurante-total]")).to_contain_text("214,30")
        self.assertEqual(saldo(self.agua, self.local), Decimal("15"))
        pedido.get_by_role("button", name=f"Editar {self.agua.nome}", exact=True).click()
        expect(dialogo.get_by_label("Observações", exact=False)).to_have_value(observacao)
        dialogo.get_by_label("Quantidade", exact=False).fill("3")
        dialogo.get_by_role("button", name="Salvar pedido", exact=True).click()
        expect(dialogo).to_be_hidden()
        expect(self.page.locator("[data-restaurante-total]")).to_contain_text("221,30")
        expect(self.page.locator("[data-barra-total]")).to_contain_text("221,30")
        pedido.get_by_role("button", name=f"Remover {self.agua.nome}", exact=True).click()
        expect(pedido).to_have_count(0)
        expect(self.page.locator("[data-restaurante-total]")).to_contain_text("200,30")
        self.assertEqual(saldo(self.agua, self.local), Decimal("17"))
        self.assertEqual(self.comanda.itens.count(), 3)
        self.conferir_geometria("pedido-conferido", 390, False)

    def test_fechamento_quarto_mantem_destino_e_desconto_ao_corrigir_erro(self):
        self.abrir()
        fechar = self.page.locator("form.comanda-fechar")
        fechar.get_by_role("button", name="Conta do quarto", exact=True).click()
        fechar.locator('[name="desconto"]').fill("2.50")
        expect(self.page.locator("[data-barra-total]")).to_contain_text("197,80")
        fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        expect(fechar.locator('[data-erros-envio]')).to_be_visible()
        expect(fechar.locator('[name="desconto"]')).to_have_value("2.50")
        expect(fechar.locator('[name="destino"]')).to_have_value("conta")
        expect(fechar.get_by_label("Quarto / hóspede", exact=True)).to_be_visible()
        self.comanda.refresh_from_db()
        self.assertTrue(self.comanda.aberta)
        self.conferir_geometria("erro-fechamento", 390, False)
        fechar.get_by_label("Quarto / hóspede", exact=True).select_option(str(self.conta.pk))
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "fechada")
        self.assertEqual(self.comanda.destino, "conta")
        self.assertEqual(self.comanda.conta_id, self.conta.pk)
        self.assertEqual(self.comanda.desconto, Decimal("2.50"))
        self.assertIsNone(self.comanda.movimento_caixa_id)
        self.assertEqual(self.comanda.total(), Decimal("197.80"))

    def test_garcom_tem_fechamento_sem_acoes_gerenciais_nos_cinco_estados(self):
        self.entrar(self.garcom)
        for largura, trilho in self.ESTADOS:
            self.abrir(largura, trilho)
            expect(self.page.get_by_role("button", name="Conta do quarto", exact=True)).to_have_count(0)
            expect(self.page.get_by_text("Cancelar este item", exact=True)).to_have_count(0)
            expect(self.page.get_by_text("Cancelar comanda", exact=True)).to_have_count(0)
            expect(self.page.get_by_text("Venda de produto sem NFC-e:", exact=False)).to_have_count(0)
            expect(self.page.get_by_text("Para cancelar após o preparo, solicite à gerência.", exact=True)).to_be_visible()
            self.conferir_geometria("garcom", largura, trilho)
        self.assertEqual(self.client.post(reverse("restaurante:cancelar", args=[self.comanda.pk]),
                                          {"motivo": "Não autorizado"}).status_code, 403)
        self.abrir()
        fechar = self.page.locator("form.comanda-fechar")
        fechar.locator('[name="desconto"]').fill("2.50")
        fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        expect(fechar.locator('[data-erros-envio]')).to_contain_text("forma de pagamento")
        expect(fechar.locator('[name="desconto"]')).to_have_value("2.50")
        fechar.get_by_label("Forma de pagamento", exact=True).select_option(str(self.forma.pk))
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "fechada")
        self.assertEqual(self.comanda.movimento_caixa.valor, Decimal("197.80"))
        self.assertEqual(self.comanda.movimento_caixa.sessao.operador, self.garcom)

    def test_mais_acoes_vincula_transfere_e_cancela_com_motivo(self):
        self.abrir()
        extras = self.page.locator(".comanda-extras")
        extras.locator(":scope > summary").click()
        extras.get_by_label("Estadia vinculada", exact=True).select_option(str(self.conta.pk))
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            extras.get_by_role("button", name="Vincular à estadia", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.conta_id, self.conta.pk)
        extras.locator(":scope > summary").click()
        extras.get_by_label("Mesa, guarda-sol ou bar", exact=True).select_option(str(self.outra_mesa.pk))
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            extras.get_by_role("button", name="Transferir", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.mesa_id, self.outra_mesa.pk)
        expect(self.page.get_by_role("heading", name=self.outra_mesa.nome, exact=True)).to_be_visible()
        extras.locator(":scope > summary").click()
        extras.get_by_text("Cancelar comanda", exact=True).click()
        extras.get_by_label("Motivo", exact=True).fill("Família solicitou encerramento; conferência com gerência.")
        self.conferir_geometria("cancelamento-preenchido", 390, False)
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            extras.get_by_role("button", name="Confirmar cancelamento", exact=True).click()
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "cancelada")
        self.assertIn("gerência", self.comanda.motivo_cancelamento)

    def test_comanda_vazia_inicia_no_cardapio_e_nao_permite_fechar(self):
        self.comanda = abrir_comanda(self.gerente, self.local, rotulo="Nova comanda vazia")
        self.abrir(320)
        expect(self.page.locator(".pdv-produtos")).to_be_visible()
        expect(self.page.locator(".pdv-painel")).to_be_hidden()
        self.page.locator(".comanda-barra-toque").click()
        expect(self.page.locator(".pdv-vazio")).to_contain_text("Comanda vazia")
        expect(self.page.get_by_role("button", name="Fechar comanda", exact=True)).to_be_disabled()
        self.conferir_geometria("vazia", 320, False)
