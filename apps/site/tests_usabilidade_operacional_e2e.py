"""Operações reais no navegador e no banco, inclusive correção após recusa.

Todos os dados são fictícios; pagamentos usam somente o gateway simulado.
"""

import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.conciliacao.models import LancamentoExtrato, TransacaoCartao
from apps.conciliacao.tests import CSV_CARTAO, OFX_EXEMPLO
from apps.lavanderia.models import ItemEnxoval, MovimentoEnxoval
from apps.lavanderia.services import saldo_enxoval
from apps.nucleo.models import (
    CategoriaFinanceira,
    CategoriaProduto,
    ContaPagarReceber,
    FormaPagamento,
    LancamentoFinanceiro,
    LocalEstoque,
    ModuloContratado,
    MovimentoCaixa,
    Produto,
    SessaoCaixa,
    Usuario,
    registrar_entrada,
    saldo,
)
from apps.nucleo.modulos import Modulo
from apps.pagamentos.models import Cobranca, EventoPagamento
from apps.restaurante.services import abrir_comanda

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(PAGAMENTOS_GATEWAY="simulado", PIX_DIRETO=False)
class UsabilidadeOperacionalE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="operacoes-reais", password="forte-123-abc")
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.receita = CategoriaFinanceira.objects.create(nome="Receita fictícia", tipo="receita")
        self.despesa = CategoriaFinanceira.objects.create(nome="Despesa fictícia", tipo="despesa")
        self.dinheiro = FormaPagamento.objects.create(nome="Dinheiro fictício", tipo="dinheiro")
        for codigo in ("nucleo", "loja", "restaurante", "lavanderia"):
            SessaoCaixa.objects.create(operador=self.op, modulo=codigo, fundo_troco=Decimal("100"))
        categoria = CategoriaProduto.objects.create(nome="Bebidas fictícias")
        self.produto = Produto.objects.create(nome="Água da auditoria", categoria=categoria, preco_venda=Decimal("7"))
        self.loja = LocalEstoque.objects.create(nome="Loja fictícia", modulo="loja")
        self.cozinha = LocalEstoque.objects.create(nome="Cozinha fictícia", modulo="restaurante")
        for local in (self.loja, self.cozinha):
            registrar_entrada(self.produto, local, 20, Decimal("2"), self.op)
        self.client.force_login(self.op)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.emulate_media(reduced_motion="reduce")

    def foto(self, nome):
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(pasta / f"{nome}.png"), full_page=True, animations="disabled")

    def enviar(self, botao):
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            botao.click()

    def test_conta_com_descricao_maxima_corrige_categoria_e_baixa_uma_vez(self):
        p = self.page
        descricao = "Recebimento de hospedagem de grupo fictício " + "a" * 156
        self.assertEqual(len(descricao), 200)
        p.goto(self.url(reverse("conta_nova")))
        p.locator("#id_tipo").select_option("receber")
        p.locator("#id_categoria").select_option(str(self.despesa.pk))
        p.locator("#id_centro").select_option("nucleo")
        p.locator("#id_descricao").fill(descricao)
        p.locator("#id_valor").fill("99.50")
        p.locator("#id_vencimento").fill(timezone.localdate().isoformat())
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.get_by_text("Conta a pagar usa categoria de despesa; a receber, de receita.", exact=True)).to_be_visible()
        expect(p.locator("#id_descricao")).to_have_value(descricao)
        self.assertFalse(ContaPagarReceber.objects.exists())
        p.locator("#id_categoria").select_option(str(self.receita.pk))
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p).to_have_url(self.url(reverse("contas")))
        conta = ContaPagarReceber.objects.get()
        p.on("dialog", lambda dialog: dialog.accept())
        with p.expect_response(lambda r: r.url.endswith(reverse("conta_baixar", args=[conta.pk]))) as resposta:
            p.get_by_role("button", name="Baixar", exact=True).click()
        self.assertEqual(resposta.value.status, 200)
        expect(p.get_by_text("Nenhuma conta aberta no momento.", exact=True)).to_be_visible()
        self.foto("financeiro-baixa-descricao-maxima")
        conta.refresh_from_db()
        self.assertEqual(conta.status, "baixada")
        self.assertEqual(conta.lancamento.valor, Decimal("99.50"))
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)
        self.client.post(reverse("conta_baixar", args=[conta.pk]))
        self.assertEqual(LancamentoFinanceiro.objects.count(), 1)

    def test_cobranca_corrige_valor_e_liquidacao_recusa_liquido_invalido(self):
        p = self.page
        p.goto(self.url(reverse("pagamentos:painel")))
        form = p.locator("#nova-cobranca form")
        form.locator('[name="descricao"]').fill("Pagamento fictício da auditoria")
        form.locator('[name="valor"]').fill("0")
        form.get_by_role("button", name="Gerar cobrança", exact=True).evaluate(
            "botao=>botao.setAttribute('formnovalidate','')")
        form.get_by_role("button", name="Gerar cobrança", exact=True).click()
        expect(form.locator("[data-erros-envio]")).to_contain_text("0.01")
        expect(form.locator('[name="descricao"]')).to_have_value("Pagamento fictício da auditoria")
        self.assertFalse(Cobranca.objects.exists())
        form.locator('[name="valor"]').fill("100")
        form.get_by_role("button", name="Gerar cobrança", exact=True).click()
        expect(p.get_by_role("button", name="Simular pagamento (sandbox)", exact=True)).to_be_visible()
        cobranca = Cobranca.objects.get()
        expect(p).to_have_url(self.url(reverse("pagamentos:detalhe", args=[cobranca.pk])))
        p.get_by_role("button", name="Simular pagamento (sandbox)", exact=True).click()
        expect(p.get_by_text("Pagamento confirmado (sandbox).", exact=True)).to_be_visible()
        p.goto(self.url(reverse("pagamentos:conciliacao")))
        p.get_by_role("button", name="Liquidar", exact=True).click()
        liquidar = p.locator('form.conc-acao-painel')
        liquidar.get_by_label("Valor líquido (R$)", exact=True).fill("-5")
        liquidar.get_by_label("Data da liquidação", exact=True).fill(timezone.localdate().isoformat())
        liquidar.get_by_label("ID do depósito", exact=True).fill("DEPOSITO-FICTICIO-01")
        with p.expect_response(lambda r: r.url.endswith(reverse("pagamentos:liquidar", args=[cobranca.pk]))) as resposta:
            liquidar.get_by_role("button", name="Confirmar", exact=True).click()
        self.assertEqual(resposta.value.status, 422)
        expect(liquidar.locator("[data-erros-envio]")).to_be_visible()
        for largura in (390, 1440):
            p.set_viewport_size({"width": largura, "height": 844 if largura == 390 else 1000})
            for rotulo, valor in (("Valor líquido (R$)", "-5"),
                                  ("Data da liquidação", timezone.localdate().isoformat()),
                                  ("ID do depósito", "DEPOSITO-FICTICIO-01")):
                campo = liquidar.get_by_label(rotulo, exact=True)
                expect(campo).to_be_visible()
                expect(campo).to_have_value(valor)
                self.assertNotEqual(campo.evaluate("el=>getComputedStyle(el).borderRadius"), "0px")
            limites = p.locator(".reveal-liquidar").bounding_box()
            confirmar = liquidar.get_by_role("button", name="Confirmar", exact=True).bounding_box()
            self.assertLessEqual(confirmar["y"] + confirmar["height"], limites["y"] + limites["height"] + 1)
            self.foto(f"pagamento-liquidacao-invalida-{largura}")
        p.set_viewport_size({"width": 390, "height": 844})
        cobranca.refresh_from_db()
        self.assertFalse(cobranca.liquidado)
        liquidar.locator('[name="valor_liquido"]').fill("98")
        liquidar.get_by_role("button", name="Confirmar", exact=True).click()
        expect(p.get_by_text("Cobrança marcada como liquidada.", exact=True)).to_be_visible()
        cobranca.refresh_from_db()
        self.assertEqual(cobranca.valor_liquido, Decimal("98"))
        self.assertEqual(cobranca.taxa, Decimal("2"))
        self.assertEqual(EventoPagamento.objects.filter(cobranca=cobranca, tipo="liquidada").count(), 1)

    def test_rouparia_ciclo_completo_recusa_saldo_insuficiente_e_preserva_campos(self):
        p = self.page
        p.goto(self.url(reverse("lavanderia:rouparia")))
        cadastro = p.locator(f'form[action="{reverse("lavanderia:rouparia_item")}"]')
        cadastro.locator('[name="nome"]').fill("Toalha fictícia da auditoria")
        cadastro.locator('[name="minimo"]').fill("3")
        cadastro.locator('[name="por_faxina"]').fill("2")
        self.enviar(cadastro.get_by_role("button", name="Cadastrar", exact=True))
        item = ItemEnxoval.objects.get()
        self.assertEqual(item.por_faxina, 2)
        movimento = p.locator(f'form[action="{reverse("lavanderia:rouparia_mover")}"]')
        movimento.locator('[name="quantidade"]').fill("10")
        self.enviar(movimento.get_by_role("button", name="Registrar", exact=True))
        self.assertEqual(saldo_enxoval(item, "limpa"), 10)
        movimento.locator('[name="acao"]').select_option("distribuir")
        movimento.locator('[name="quantidade"]').fill("11")
        movimento.get_by_role("button", name="Registrar", exact=True).click()
        expect(movimento.locator("[data-erros-envio]")).to_contain_text("Saldo insuficiente")
        expect(movimento.locator('[name="acao"]')).to_have_value("distribuir")
        expect(movimento.locator('[name="quantidade"]')).to_have_value("11")
        self.assertEqual(MovimentoEnxoval.objects.count(), 1)
        self.foto("rouparia-saldo-insuficiente")
        for acao, destino in (("distribuir", "em_uso"), ("coletar", "suja"),
                              ("enviar", "lavando"), ("receber", "limpa")):
            movimento.locator('[name="acao"]').select_option(acao)
            movimento.locator('[name="quantidade"]').fill("4")
            self.enviar(movimento.get_by_role("button", name="Registrar", exact=True))
            self.assertEqual(saldo_enxoval(item, destino), 10 if destino == "limpa" else 4)
        movimento.locator('[name="acao"]').select_option("baixar")
        movimento.locator('[name="estado"]').select_option("limpa")
        movimento.locator('[name="motivo"]').fill("Rasgo confirmado na conferência")
        movimento.locator('[name="quantidade"]').fill("1")
        self.enviar(movimento.get_by_role("button", name="Registrar", exact=True))
        self.assertEqual(saldo_enxoval(item, "limpa"), 9)
        self.assertEqual(MovimentoEnxoval.objects.count(), 10)
        for estado in ("em_uso", "suja", "lavando"):
            self.assertEqual(saldo_enxoval(item, estado), 0)
        expect(p.get_by_role("row").filter(has_text=item.nome)).to_contain_text("9")
        self.foto("rouparia-ciclo-concluido")

    def test_restaurante_recusa_desconto_maior_corrige_e_fecha_uma_vez(self):
        comanda = abrir_comanda(self.op, self.cozinha, rotulo="Balcão fictício da auditoria")
        p = self.page
        p.goto(self.url(reverse("restaurante:comanda", args=[comanda.pk])))
        p.locator(".pdv-produto").filter(has_text=self.produto.nome).click()
        dialogo = p.get_by_role("dialog")
        dialogo.get_by_label("Quantidade", exact=False).fill("2")
        dialogo.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(dialogo).to_be_hidden()
        p.get_by_role("link", name="Itens e fechamento", exact=True).click()
        expect(p.locator("#comanda-itens .comanda-total-linha")).to_contain_text("14,00")
        fechar = p.locator("form.comanda-fechar")
        fechar.locator('[name="forma"]').select_option(str(self.dinheiro.pk))
        fechar.locator('[name="desconto"]').fill("15")
        fechar.get_by_role("button", name="Fechar comanda", exact=True).click()
        expect(fechar.locator("[data-erros-envio]")).to_contain_text("Desconto inválido")
        expect(fechar.locator('[name="forma"]')).to_have_value(str(self.dinheiro.pk))
        expect(fechar.locator('[name="desconto"]')).to_have_value("15")
        comanda.refresh_from_db()
        self.assertEqual(comanda.status, "aberta")
        self.assertIsNone(comanda.movimento_caixa_id)
        self.assertEqual(saldo(self.produto, self.cozinha), Decimal("18"))
        self.foto("restaurante-desconto-invalido")
        fechar.locator('[name="desconto"]').fill("2")
        self.enviar(fechar.get_by_role("button", name="Fechar comanda", exact=True))
        comanda.refresh_from_db()
        self.assertEqual(comanda.status, "fechada")
        self.assertEqual(comanda.movimento_caixa.valor, Decimal("12"))
        self.assertEqual(saldo(self.produto, self.cozinha), Decimal("18"))
        self.client.post(reverse("restaurante:fechar", args=[comanda.pk]), {
            "destino": "caixa", "forma": self.dinheiro.pk, "desconto": "2",
        })
        self.assertEqual(MovimentoCaixa.objects.count(), 1)
        self.foto("restaurante-fechado-com-desconto")

    def test_conciliacao_importa_sem_duplicar_concilia_desfaz_e_recasa(self):
        contas = []
        for tipo, categoria, valor, dia in (("receber", self.receita, "150", 10),
                                            ("pagar", self.despesa, "80", 11)):
            conta = ContaPagarReceber.objects.create(
                tipo=tipo, categoria=categoria, descricao=f"Conta fictícia {tipo}",
                valor=Decimal(valor), vencimento=date(2026, 9, dia),
            )
            conta.baixar(self.op, data=date(2026, 9, dia))
            contas.append(conta)
        cartao = FormaPagamento.objects.create(nome="Cartão fictício", tipo="cartao_credito")
        recebimento = MovimentoCaixa.objects.create(
            sessao=SessaoCaixa.objects.get(operador=self.op, modulo="nucleo"),
            tipo="recebimento", forma_pagamento=cartao, valor=Decimal("200"),
            autorizacao="NSU123", descricao="Venda fictícia conciliada", criado_por=self.op,
        )
        p = self.page
        p.goto(self.url(reverse("conciliacao:painel")))
        p.locator("#conta-ofx").fill("AUDITORIA-123")
        p.locator("#arq-ofx").set_input_files({
            "name": "extrato-invalido.txt", "mimeType": "text/plain", "buffer": b"nao e OFX",
        })
        p.get_by_role("button", name="Importar OFX", exact=True).click()
        form_ofx = p.locator(f'form[action="{reverse("conciliacao:importar_ofx")}"]')
        expect(form_ofx.locator("[data-erros-envio]")).to_contain_text("Envie um arquivo .ofx")
        expect(p.locator("#conta-ofx")).to_have_value("AUDITORIA-123")
        self.assertEqual(p.locator("#arq-ofx").evaluate("el=>el.files[0].name"), "extrato-invalido.txt")
        self.assertFalse(LancamentoExtrato.objects.exists())
        self.foto("conciliacao-importacao-recusada")
        for _ in range(2):
            p.locator("#conta-ofx").fill("AUDITORIA-123")
            p.locator("#arq-ofx").set_input_files({
                "name": "extrato-ficticio.ofx", "mimeType": "application/x-ofx",
                "buffer": OFX_EXEMPLO.encode("utf-8"),
            })
            self.enviar(p.get_by_role("button", name="Importar OFX", exact=True))
            self.assertEqual(LancamentoExtrato.objects.count(), 2)
            p.locator("#arq-csv").set_input_files({
                "name": "cartao-ficticio.csv", "mimeType": "text/csv",
                "buffer": CSV_CARTAO.encode("utf-8"),
            })
            self.enviar(p.get_by_role("button", name="Importar cartão", exact=True))
            self.assertEqual(TransacaoCartao.objects.count(), 1)
        self.enviar(p.get_by_role("button", name="Conciliar agora", exact=True))
        self.assertEqual(LancamentoExtrato.objects.filter(status="conciliado").count(), 2)
        transacao = TransacaoCartao.objects.get()
        self.assertEqual(transacao.data_liquidacao, date(2026, 9, 11))
        self.assertEqual(transacao.movimento_caixa_id, recebimento.pk)
        self.assertEqual(transacao.lancamento_taxa.valor, Decimal("5"))
        taxa_id = transacao.lancamento_taxa_id
        p.get_by_role("link", name="Revisar pendências", exact=True).click()
        expect(p.get_by_role("heading", name="Conciliação manual", exact=True)).to_be_visible()
        linha_cartao = p.get_by_role("row").filter(has_text="NSU NSU123")
        self.enviar(linha_cartao.get_by_role("button", name="Desfazer", exact=True))
        transacao.refresh_from_db()
        self.assertEqual(transacao.status, "pendente")
        self.assertFalse(LancamentoFinanceiro.objects.filter(pk=taxa_id).exists())
        linha_cartao = p.get_by_role("row").filter(has_text="NSU123")
        linha_cartao.locator('[name="escolha"]').select_option(f"mc:{recebimento.pk}")
        self.enviar(linha_cartao.get_by_role("button", name="Casar", exact=True))
        transacao.refresh_from_db()
        self.assertEqual(transacao.status, "conciliado")
        self.assertEqual(transacao.lancamento_taxa.valor, Decimal("5"))
        linha_banco = p.get_by_role("row").filter(has_text="PIX RECEBIDO")
        self.enviar(linha_banco.get_by_role("button", name="Desfazer", exact=True))
        credito = LancamentoExtrato.objects.get(fitid="ABC1")
        self.assertEqual(credito.status, "pendente")
        linha_banco.locator('[name="escolha"]').select_option(f"cpr:{contas[0].pk}")
        self.enviar(linha_banco.get_by_role("button", name="Casar", exact=True))
        credito.refresh_from_db()
        self.assertEqual(credito.status, "conciliado")
        self.assertEqual(credito.confianca, "manual")
        self.assertEqual(LancamentoFinanceiro.objects.count(), 3)
        self.foto("conciliacao-conferida-e-recuperada")
