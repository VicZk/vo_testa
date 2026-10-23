"""Fluxos de operação e regressões visuais com dados fictícios.

Testa a tela e o efeito no estoque/caixa, contra PostgreSQL descartável.
Os gateways são simulados; nenhuma mensagem ou pagamento real é enviado.
Roda no CI junto de tests_e2e; sem Playwright, segue o mesmo skip explícito.
"""

import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.templatetags.static import static
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.canais.tests import DadosCanais
from apps.canais.tests_fila import CONFIGURACAO as CONFIGURACAO_CANAIS
from apps.nucleo.models import saldo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E, _FunilComercialMixin

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class CadastrosPrecosOperacaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    _login = _FunilComercialMixin._login

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import UH, ConfiguracaoReservas, Temporada, TipoUH, Usuario
        from apps.reservas.models import TarifaUnidade
        cache.clear()
        Usuario.objects.create_superuser(username="cadastros-ui", password="forte-123-abc")
        self.tipo = TipoUH.objects.create(nome="Suíte QA", capacidade=2, tarifa_base="300")
        self.uh = UH.objects.create(numero="QA-101", tipo=self.tipo)
        self.tarifa = TarifaUnidade.objects.create(uh=self.uh, classificacao="baixa", valor="350")
        self.cfg = ConfiguracaoReservas.carregar()
        self.temporada = Temporada.objects.create(nome="Feriado de teste QA", classificacao="feriado",
            inicio=timezone.localdate()+timedelta(days=10), fim=timezone.localdate()+timedelta(days=13))
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("cadastros-ui", "forte-123-abc")

    def conferir_erro_responsivo(self, nome):
        p = self.page
        for largura in (320, 390, 414, 768, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
            if nome == "tabela-erro" and largura <= 821:
                self.assertFalse(p.evaluate("""() => {
                    const form=document.querySelector('.precos-form').getBoundingClientRect();
                    return [...document.querySelectorAll('.precos-tabela input')].some(campo => {
                        const r=campo.getBoundingClientRect();return r.left<form.left-1||r.right>form.right+1;
                    });
                }"""))
            self.assertFalse(p.evaluate("""() => {
                const box=document.querySelector('[data-erros-envio]');
                const limite=box.getBoundingClientRect();
                const falhas=[];const walker=document.createTreeWalker(box,NodeFilter.SHOW_TEXT);let node;
                while(node=walker.nextNode()){
                    const range=document.createRange();range.selectNodeContents(node);
                    for(const r of range.getClientRects())if(r.width&&(r.left<limite.left-2||r.right>limite.right+2))falhas.push(node.textContent);
                }
                return falhas;
            }"""))
            if largura in (320, 821, 1440):
                OperacaoUsabilidadeE2ETests._foto(self, f"fase9-{nome}-{largura}.png", full_page=True)
        p.set_viewport_size({"width": 390, "height": 844})

    def test_quarto_novo_e_edicao_com_erro_preservam_o_formulario_no_celular(self):
        from apps.nucleo.models import UH, ConfiguracaoUH
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("uh_nova")))
        p.locator('#id_numero').fill("QA-102")
        p.locator('#id_tipo').select_option(str(self.tipo.pk))
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.get_by_role("heading", name="Quarto QA-102", exact=True)).to_be_visible()
        quarto = UH.objects.get(numero="QA-102")
        p.locator('#id_nome_tematico').fill("Nome mantido durante a correção")
        p.locator('#id_sofa_adultos').fill("-1")
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.get_by_text("O menor valor aceito é 0.", exact=True)).to_be_visible()
        # Exercita a resposta do servidor, inclusive para requisições sem validação HTML.
        p.get_by_role("button", name="Salvar", exact=True).evaluate("botao => botao.setAttribute('formnovalidate', '')")
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("adultos")
        expect(p.locator('#id_nome_tematico')).to_have_value("Nome mantido durante a correção")
        quarto.refresh_from_db()
        self.assertEqual(quarto.nome_tematico, "")
        self.assertFalse(ConfiguracaoUH.objects.filter(uh=quarto).exists())
        self.conferir_erro_responsivo("quarto-erro")
        p.locator('#id_sofa_adultos').fill("1")
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p).to_have_url(self.url(reverse("estrutura")))
        quarto.refresh_from_db()
        self.assertEqual(quarto.nome_tematico, "Nome mantido durante a correção")
        self.assertTrue(ConfiguracaoUH.objects.filter(uh=quarto).exists())

    def test_tabela_invalida_nao_apaga_tarifas_e_permite_corrigir_sem_redigitar(self):
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("tabela_precos")))
        base = p.locator(f'input[name="base_{self.uh.pk}_baixa"]')
        base.fill("71235")
        p.locator('input[name="single_pct"]').fill("7025")
        p.locator('input[name="du_ad_alta"]').evaluate("campo => campo.value = 'NaN'")
        p.get_by_role("button", name="Salvar tabela").click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("Day use")
        expect(base).to_have_value("712,35")
        expect(p.locator('input[name="single_pct"]')).to_have_value("70,25")
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.valor, Decimal("350"))
        self.conferir_erro_responsivo("tabela-erro")
        p.locator('input[name="du_ad_alta"]').fill("9500")
        with p.expect_navigation():
            p.get_by_role("button", name="Salvar tabela").click()
        self.tarifa.refresh_from_db()
        self.cfg.refresh_from_db()
        self.assertEqual(self.tarifa.valor, Decimal("712.35"))
        self.assertEqual(self.cfg.single_fator, Decimal("0.7025"))

    def test_temporada_invalida_mantem_nome_datas_e_precos_para_correcao(self):
        from apps.reservas.models import TarifaTemporada
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("temporada_editar", args=[self.temporada.pk])))
        p.locator('#id_nome').fill("Temporada alterada na conferência QA")
        p.locator('#id_fim').fill((self.temporada.inicio-timedelta(days=1)).isoformat())
        p.locator(f'input[name="tbase_{self.uh.pk}"]').fill("123456")
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("data de fim")
        expect(p.locator('#id_nome')).to_have_value("Temporada alterada na conferência QA")
        expect(p.locator(f'input[name="tbase_{self.uh.pk}"]')).to_have_value("1.234,56")
        self.temporada.refresh_from_db()
        self.assertEqual(self.temporada.nome, "Feriado de teste QA")
        self.assertFalse(TarifaTemporada.objects.filter(temporada=self.temporada).exists())
        self.conferir_erro_responsivo("temporada-erro")
        p.locator('#id_fim').fill(self.temporada.fim.isoformat())
        p.get_by_role("button", name="Salvar", exact=True).click()
        expect(p).to_have_url(self.url(reverse("temporadas")))
        self.temporada.refresh_from_db()
        self.assertEqual(self.temporada.nome, "Temporada alterada na conferência QA")
        self.assertEqual(TarifaTemporada.objects.get(temporada=self.temporada, uh=self.uh).valor, Decimal("1234.56"))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class SuprimentosOperacaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    _login = _FunilComercialMixin._login

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import (
            CategoriaProduto,
            EmbalagemProduto,
            FormaPagamento,
            Fornecedor,
            LocalEstoque,
            LoteEstoque,
            ModuloContratado,
            Pessoa,
            Produto,
            SessaoCaixa,
            Usuario,
        )
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="suprimentos-ui", password="forte-123-abc")
        for codigo in ("estoque", "loja", "restaurante"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.local = LocalEstoque.objects.create(nome="Cozinha e balcão de conferência QA", modulo="loja")
        self.forma = FormaPagamento.objects.create(nome="Dinheiro QA", tipo="dinheiro")
        SessaoCaixa.objects.create(operador=self.op, modulo="loja", fundo_troco=0)
        self.fornecedor = Pessoa.objects.create(nome="Fornecedor fictício de alimentos para conferência QA")
        Fornecedor.objects.create(pessoa=self.fornecedor)
        cat = CategoriaProduto.objects.create(nome="Cozinha QA")
        self.leite = Produto.objects.create(nome="Leite integral para o preparo de bebidas e receitas da cozinha QA",
                                            categoria=cat, unidade="l", controla_validade=True)
        self.prato = Produto.objects.create(nome="Café com leite QA", categoria=cat, usa_ficha_tecnica=True,
                                            preco_venda=Decimal("12.00"))
        self.embalagem = EmbalagemProduto.objects.create(produto=self.leite, nome="Caixa com 12 litros", fator=12)
        self.lote = LoteEstoque.objects.create(produto=self.leite, codigo="LOTE"*20,
                      validade=timezone.localdate()+timedelta(days=30), criado_por=self.op)
        outro = Produto.objects.create(nome="Ingrediente de outro lote QA", categoria=cat, controla_validade=True)
        self.errado = LoteEstoque.objects.create(produto=outro, codigo="OUTRO-QA",
                      validade=timezone.localdate()+timedelta(days=30), criado_por=self.op)
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("suprimentos-ui", "forte-123-abc")

    def _foto(self, nome):
        OperacaoUsabilidadeE2ETests._foto(self, nome, full_page=True)

    def test_receber_compra_corrigir_erro_configurar_prato_vender_e_cancelar_no_celular(self):
        from apps.loja.models import Venda
        from apps.nucleo.models import MovimentoEstoque, saldo_vendavel
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("estoque:compra_receber")))
        p.get_by_label("Produto e embalagem", exact=True).select_option(str(self.embalagem.pk))
        p.get_by_label("Local de recebimento", exact=True).select_option(str(self.local.pk))
        p.get_by_label("Quantidade de embalagens", exact=True).fill("2")
        p.get_by_label("Custo por embalagem (R$)", exact=True).fill("60")
        p.get_by_label("Lote recebido", exact=True).select_option(str(self.errado.pk))
        p.get_by_label("Fornecedor", exact=True).select_option(str(self.fornecedor.pk))
        p.get_by_label("Nota fiscal ou documento da compra", exact=True).fill("NF QA preservada")
        p.get_by_label("Observação", exact=True).fill("Recebimento fictício conferido")
        expect(p.locator("#compra-quantidade")).to_contain_text("24 l")
        p.get_by_role("button", name="Registrar recebimento", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("lote deste produto")
        expect(p.get_by_label("Nota fiscal ou documento da compra", exact=True)).to_have_value("NF QA preservada")
        expect(p.get_by_label("Quantidade de embalagens", exact=True)).to_have_value("2")
        self.assertEqual(MovimentoEstoque.objects.count(), 0)
        self._foto("fase8-compra-erro-390.png")
        p.get_by_label("Lote recebido", exact=True).select_option(str(self.lote.pk))
        p.get_by_role("button", name="Registrar recebimento", exact=True).click()
        expect(p.get_by_role("heading", name="Compras recebidas", exact=True)).to_be_visible()
        self.assertEqual(saldo(self.leite), 24)
        p.goto(self.url(reverse("estoque:ficha_editar", args=[self.prato.pk])))
        p.locator('[name="ingredientes-0-ingrediente"]').select_option(str(self.leite.pk))
        p.locator('[name="ingredientes-0-quantidade"]').fill("0.200")
        p.get_by_role("button", name="Adicionar ingrediente", exact=True).click()
        p.locator('[name="ingredientes-3-ingrediente"]').select_option(str(self.leite.pk))
        p.locator('[name="ingredientes-3-quantidade"]').fill("0.100")
        p.get_by_role("button", name="Salvar ficha técnica", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("ingredientes diferentes")
        expect(p.locator('[name="ingredientes-0-quantidade"]')).to_have_value("0.200")
        p.locator('[name="ingredientes-3-DELETE"]').check()
        p.get_by_role("button", name="Salvar ficha técnica", exact=True).click()
        expect(p.get_by_role("heading", name="Ficha técnica", exact=True)).to_be_visible()
        p.goto(self.url(reverse("loja:pdv")))
        produto = p.get_by_role("button", name="Adicionar Café com leite QA ao carrinho", exact=True)
        produto.click()
        produto.click()
        p.locator(".pdv-etapas button").filter(has_text="Carrinho").click()
        p.get_by_label("Forma de pagamento", exact=True).select_option(str(self.forma.pk))
        with p.expect_navigation():
            p.locator(".pdv-finalizar").click()
        venda = Venda.objects.get()
        self.assertEqual(venda.total, Decimal("24"))
        self.assertEqual(saldo(self.leite), Decimal("23.6"))
        p.get_by_text("Cancelar venda (gerência)", exact=True).click()
        p.locator('[name="motivo"]').fill("Cancelamento fictício antes do preparo")
        p.on("dialog", lambda dialog: dialog.accept())
        p.get_by_role("button", name="Cancelar venda", exact=True).click()
        expect(p.get_by_text("Cancelamento fictício antes do preparo", exact=False).first).to_be_visible()
        venda.refresh_from_db()
        self.assertEqual(venda.status, "cancelada")
        self.assertEqual(saldo(self.leite), 24)
        self.assertEqual(saldo_vendavel(self.leite, self.local), 24)
        self._foto("fase8-prato-cancelado-390.png")

    def test_contagem_no_celular_recusa_movimento_posterior_e_permite_nova_conferencia(self):
        from apps.nucleo.models import LoteEstoque, registrar_entrada, registrar_saida
        registrar_entrada(self.leite, self.local, 4, 5, self.op, lote=self.lote)
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("estoque:lote_contar", args=[self.lote.pk, self.local.pk])))
        p.get_by_label("Quantidade contada deste lote", exact=True).fill("4")
        p.get_by_label("Motivo da contagem ou correção", exact=True).fill("Conferência fictícia preservada")
        registrar_saida(self.leite, self.local, 1, self.op)
        p.get_by_role("button", name="Aplicar contagem", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("movimentado depois")
        expect(p.get_by_label("Motivo da contagem ou correção", exact=True)).to_have_value("Conferência fictícia preservada")
        self.assertEqual(saldo(self.leite), 3)
        p.reload()
        p.get_by_label("Quantidade contada deste lote", exact=True).fill("2")
        p.get_by_label("Motivo da contagem ou correção", exact=True).fill("Nova contagem conferida")
        p.get_by_role("button", name="Aplicar contagem", exact=True).click()
        expect(p.get_by_role("heading", name="Saldo por local", exact=True)).to_be_visible()
        self.assertEqual(saldo(self.leite), 2)
        self._foto("fase8-contagem-lote-390.png")
        destino = LoteEstoque.objects.create(produto=self.leite, codigo="ETIQUETA-CORRIGIDA-QA",
                    validade=self.lote.validade, criado_por=self.op)
        p.get_by_role("link", name="Corrigir identificação", exact=True).click()
        p.get_by_label("Lote com a identificação correta", exact=True).select_option(str(destino.pk))
        p.get_by_label("Local", exact=True).select_option(str(self.local.pk))
        p.get_by_label("Quantidade a reidentificar", exact=True).fill("3")
        p.get_by_label("Motivo e evidência da conferência", exact=True).fill("Etiqueta fictícia conferida")
        p.get_by_role("button", name="Confirmar correção", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("insuficiente")
        expect(p.get_by_label("Motivo e evidência da conferência", exact=True)).to_have_value("Etiqueta fictícia conferida")
        p.get_by_label("Quantidade a reidentificar", exact=True).fill("1")
        p.get_by_role("button", name="Confirmar correção", exact=True).click()
        expect(p.get_by_text("ETIQUETA-CORRIGIDA-QA", exact=True)).to_be_visible()
        self.assertEqual(saldo(self.leite), 2)
        self._foto("fase8-correcao-lote-390.png")

    def test_telas_de_suprimentos_cabem_em_seis_larguras_com_textos_longos(self):
        from apps.nucleo.models import registrar_compra, salvar_ficha
        registrar_compra(self.embalagem, self.local, 2, 60, self.op, lote=self.lote,
                          fornecedor=self.fornecedor, documento="NOTAFISCAL"*8)
        salvar_ficha(self.prato, [(self.leite, Decimal("0.200"))], self.op)
        telas = [("compras", []), ("compra_receber", []), ("produto_suprimentos", [self.leite.pk]),
                  ("produto_suprimentos", [self.prato.pk]), ("embalagem_nova", [self.leite.pk]),
                  ("embalagem_editar", [self.leite.pk, self.embalagem.pk]), ("ficha_editar", [self.prato.pk]),
                  ("lotes", []), ("lote_novo", []), ("lote", [self.lote.pk]), ("lote_identificar", []),
                  ("lote_corrigir", [self.lote.pk]),
                  ("lote_contar", [self.lote.pk, self.local.pk]), ("produto_editar", [self.leite.pk]), ("entrada", [])]
        p, erros = self.page, []
        p.on("pageerror", lambda erro: erros.append(str(erro)))
        for largura in (320, 390, 414, 768, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            for nome, args in telas:
                with self.subTest(largura=largura, tela=nome, args=args):
                    resposta = p.goto(self.url(reverse(f"estoque:{nome}", args=args)), wait_until="networkidle")
                    self.assertEqual(resposta.status, 200)
                    p.evaluate("document.fonts.ready")
                    if largura in (320, 821, 1440):
                        self._foto(f"fase8-{nome}-{'-'.join(map(str,args))}-{largura}.png")
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
                    falhas = p.evaluate("""() => {
                        const falhas=[];
                        for(const caixa of document.querySelectorAll('.conteudo .cartao,.conteudo .form-cartao,.conteudo .tabela-cartoes tbody tr')){
                            const limite=caixa.getBoundingClientRect();
                            const walker=document.createTreeWalker(caixa,NodeFilter.SHOW_TEXT);let node;
                            while(node=walker.nextNode()){
                                const pai=node.parentElement;
                                if(!node.textContent.trim()||!pai.getClientRects().length||pai.closest('option,script,style,template'))continue;
                                // Cabeçalho acessível da tabela em cartões é intencionalmente oculto.
                                const cabecalho=pai.closest('thead');
                                if(cabecalho&&getComputedStyle(cabecalho).clipPath!=='none')continue;
                                if(pai.closest('details:not([open])')&&!pai.closest('summary'))continue;
                                const range=document.createRange();range.selectNodeContents(node);
                                for(const r of range.getClientRects())if(r.width&&(r.left<limite.left-2||r.right>limite.right+2||r.bottom>limite.bottom+2)){
                                    falhas.push(node.textContent.trim());break;
                                }
                            }
                        }
                        return falhas;
                    }""")
                    self.assertFalse(falhas, falhas)
        self.assertFalse(erros, erros)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(**CONFIGURACAO_CANAIS)
class CanaisOperacaoE2ETests(DadosCanais, _BaseE2E):
    LOCALE = "pt-BR"
    _login = _FunilComercialMixin._login

    def setUp(self):
        super().setUp()
        cache.clear()
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("canais-qa", "canais-ficticio-qa")

    def _foto(self, nome):
        OperacaoUsabilidadeE2ETests._foto(self, nome, full_page=True)

    def test_telas_e_formularios_cabem_em_seis_larguras_com_texto_extenso(self):
        from apps.canais import services
        item = self.bruto()
        item["attributes"]["customer"].update(name="Hóspede fictício com nome extenso para conferência", surname="Sobrenome"*10)
        rev = self.capturar(item)
        self.mapa.nome = "Categoria de suítes de teste com nome extenso para conferir leitura no celular"
        self.mapa.save()
        envio = services.publicar(self.cfg, self.gateway)
        telas = [("painel", []), ("conexao", [self.cfg.pk]), ("conexao_nova", []),
            ("categorias", [self.cfg.pk]), ("mapeamento", [self.cfg.pk, self.mapa.pk]),
            ("mapeamento_novo", [self.cfg.pk]), ("validacao", [self.cfg.pk]),
            ("disponibilidade", [self.cfg.pk]), ("revisao", [rev.pk]),
            ("envios", [self.cfg.pk]), ("envio", [envio.pk])]
        p, erros = self.page, []
        p.on("pageerror", lambda erro: erros.append(str(erro)))
        for largura in (320, 390, 414, 768, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            for nome, args in telas:
                with self.subTest(largura=largura, tela=nome):
                    resposta = p.goto(self.url(reverse(f"canais:{nome}", args=args)), wait_until="networkidle")
                    self.assertEqual(resposta.status, 200)
                    p.evaluate("document.fonts.ready")
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
                    falhas = p.evaluate("""() => {
                        const falhas=[];
                        for(const caixa of document.querySelectorAll('.conteudo .cartao,.conteudo .form-cartao,.conteudo .kpi,.conteudo .tabela-cartoes tbody tr')){
                            const limite=caixa.getBoundingClientRect();
                            const walker=document.createTreeWalker(caixa,NodeFilter.SHOW_TEXT);let node;
                            while(node=walker.nextNode()){
                                const pai=node.parentElement;
                                if(!node.textContent.trim()||!pai.getClientRects().length||pai.closest('option,script,style'))continue;
                                const range=document.createRange();range.selectNodeContents(node);
                                for(const r of range.getClientRects())if(r.width&&(r.left<limite.left-2||r.right>limite.right+2||r.bottom>limite.bottom+2)){
                                    falhas.push(node.textContent.trim());break;
                                }
                            }
                        }
                        return falhas;
                    }""")
                    self.assertFalse(falhas, falhas)
                    if largura in (320, 821, 1440):
                        self._foto(f"fase7-canais-{nome}-{largura}.png")
        self.assertFalse(erros, erros)

    def test_aplicar_alterar_e_cancelar_reserva_pela_fila_no_celular(self):
        from apps.canais.models import RevisaoCanal
        from apps.reservas.models import Reserva
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        item = self.bruto()
        revisao = self.capturar(item)
        p.goto(self.url(reverse("canais:painel")))
        p.get_by_role("link", name="Conferir", exact=True).click()
        motivo = "Conferência fictícia mantida após vínculo incorreto."
        p.get_by_label("Números das reservas no PMS").fill("999999")
        p.get_by_label("Conferência realizada", exact=True).fill(motivo)
        p.get_by_role("button", name="Concluir conferência").click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("não existe")
        expect(p.get_by_label("Conferência realizada", exact=True)).to_have_value(motivo)
        expect(p.get_by_label("Números das reservas no PMS")).to_have_value("999999")
        self.assertFalse(Reserva.objects.exists())
        p.on("dialog", lambda dialog: dialog.accept())
        p.get_by_role("button", name="Conferir e aplicar revisão").click()
        expect(p.get_by_text("Aplicada no PMS", exact=True)).to_be_visible()
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.valor_hospedagem, Decimal("600"))
        expect(p.get_by_role("link", name=f"Reserva {reserva.pk}", exact=True)).to_be_visible()
        novo = self.nova_versao(item, amount="650.00")
        novo["attributes"]["rooms"][0].update(amount="650.00", days={})
        alteracao = self.capturar(novo)
        p.goto(self.url(reverse("canais:revisao", args=[alteracao.pk])))
        p.get_by_role("button", name="Conferir e aplicar revisão").click()
        expect(p.get_by_text("Aplicada no PMS", exact=True)).to_be_visible()
        reserva.refresh_from_db()
        self.assertEqual(reserva.valor_hospedagem, Decimal("650"))
        cancelado = self.nova_versao(novo, status="cancelled", rooms=[], inserted_at=(timezone.now()+timedelta(minutes=3)).isoformat())
        ultima = self.capturar(cancelado)
        p.goto(self.url(reverse("canais:revisao", args=[ultima.pk])))
        p.get_by_role("button", name="Conferir e aplicar revisão").click()
        expect(p.get_by_text("Aplicada no PMS", exact=True)).to_be_visible()
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.CANCELADA)
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(RevisaoCanal.objects.get(pk=revisao.pk).estado, RevisaoCanal.Estado.APLICADA)
        self._foto("fase7-canais-cancelamento-390.png")

    def test_configurar_mapear_validar_solicitar_e_conferir_envio_pelas_telas(self):
        from apps.canais import services
        p = self.page
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("canais:conexao", args=[self.cfg.pk])))
        p.locator('[name="vendas_abertas"]').uncheck()
        p.get_by_role("button", name="Salvar conexão").click()
        expect(p.get_by_role("heading", name="Canais de venda", exact=True)).to_be_visible()
        p.get_by_role("link", name="Conferir categorias").click()
        p.get_by_role("link", name="Editar", exact=True).click()
        p.locator('[name="nome"]').fill("Suítes para conferência QA")
        p.locator('[name="limite_venda"]').fill("3")
        p.get_by_role("button", name="Salvar categoria").click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("não podem superar")
        expect(p.locator('[name="nome"]')).to_have_value("Suítes para conferência QA")
        expect(p.locator('[name="limite_venda"]')).to_have_value("3")
        self._foto("fase7-canais-mapeamento-erro-390.png")
        p.locator('[name="limite_venda"]').fill("1")
        p.get_by_role("button", name="Salvar categoria").click()
        expect(p.get_by_role("heading", name="Canais de venda", exact=True)).to_be_visible()
        p.get_by_role("link", name="Registrar validação", exact=True).click()
        p.locator('[name="evidencia"]').fill("Conferência fictícia com preços, datas, disponibilidade e reservas no provedor de teste.")
        p.get_by_role("button", name="Registrar validação", exact=True).click()
        expect(p.get_by_text("Registrada para esta configuração", exact=True)).to_be_visible()
        p.get_by_role("button", name="Solicitar atualização").click()
        expect(p.get_by_text("Atualização solicitada, aguardando a rotina agendada.", exact=True)).to_be_visible()
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.sincronizacao_solicitada)
        self.assertEqual(self.mapa.__class__.objects.get(pk=self.mapa.pk).limite_venda, 1)
        envio = services.publicar(self.cfg, self.gateway)
        p.goto(self.url(reverse("canais:envio", args=[envio.pk])))
        p.locator('[name="evidencia"]').fill("Fechamento fictício conferido em todas as categorias e datas do canal de teste.")
        p.get_by_role("button", name="Registrar conferência").click()
        expect(p.get_by_role("heading", name="Histórico de envios", exact=True)).to_be_visible()
        envio.refresh_from_db()
        self.assertIsNotNone(envio.conferido_em)
        self.assertTrue(services._ultimo_envio_fechado(self.cfg))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
@override_settings(
    PAGAMENTOS_GATEWAY="simulado",
    EMAIL_GATEWAY="simulado",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_ENVIO_ASSINCRONO=False,
)
class OperacaoUsabilidadeE2ETests(_FunilComercialMixin, _BaseE2E):
    LOCALE = "pt-BR"

    def test_safrapay_configuracao_expandida_cabe_nos_cartoes(self):
        p = self.page
        for largura in (320, 390, 414, 768, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 900})
                p.goto(self.url(reverse("pagamentos:safrapay")), wait_until="networkidle")
                p.get_by_text("Referência de configuração", exact=True).click()
                expect(p.get_by_role("button", name="Baixar exemplos de integração")).to_be_visible()
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                vazamentos = p.evaluate("""() => {
                    const falhas=[];
                    document.querySelectorAll('.conteudo .cartao').forEach(caixa=>{
                        const limite=caixa.getBoundingClientRect();
                        const walker=document.createTreeWalker(caixa,NodeFilter.SHOW_TEXT);
                        let node;
                        while(node=walker.nextNode()){
                            if(!node.textContent.trim()||!node.parentElement.getClientRects().length)continue;
                            const range=document.createRange();range.selectNodeContents(node);
                            for(const r of range.getClientRects()){
                                if(r.width&&(r.left<limite.left-2||r.right>limite.right+2||r.bottom>limite.bottom+2)){
                                    falhas.push(node.textContent.trim());break;
                                }
                            }
                        }
                    });return falhas;
                }""")
                self.assertFalse(vazamentos, vazamentos)
                if largura in (320, 821, 1440):
                    self._foto(f"fase6-safrapay-{largura}.png", full_page=True)

    def test_contagem_invalida_preserva_valor_e_filtros_ate_corrigir(self):
        from apps.nucleo.models import Inventario, ItemInventario

        self.product.nome = "Água mineral com gás em garrafa retornável de 500 mililitros QA"
        self.product.save(update_fields=["nome"])
        inv = Inventario.objects.create(local=self.shop, criado_por=self.op)
        item = ItemInventario.objects.create(
            inventario=inv, produto=self.product, saldo_sistema=20,
            quantidade_contada=20,
        )
        p = self.page
        for largura in (320, 390, 414, 768, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(reverse("estoque:inventario", args=[inv.pk])))
                entrada = p.get_by_role("spinbutton", name=f"Contagem de {self.product.nome}", exact=True)
                limites = entrada.bounding_box()
                self.assertGreaterEqual(limites["x"], 0)
                self.assertLessEqual(limites["x"] + limites["width"], largura)
                self.assertGreaterEqual(limites["width"], 80)
                self.assertTrue(p.locator(".est-tabela-contagem").evaluate("el=>el.scrollWidth<=el.clientWidth+1"))
                if largura in (320, 821):
                    p.locator(".est-tabela-contagem").scroll_into_view_if_needed()
                    self._foto(f"fase6-inventario-campos-{largura}.png")
        p.set_viewport_size({"width": 390, "height": 844})
        p.goto(self.url(reverse("estoque:inventario", args=[inv.pk])))
        campo = p.get_by_role("spinbutton", name=f"Contagem de {self.product.nome}", exact=True)
        p.get_by_label("Buscar na lista").fill("Água")
        campo.fill("1000000000")
        p.get_by_role("button", name="Salvar contagem", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("Contagem inválida")
        expect(campo).to_have_value("1000000000")
        expect(p.get_by_label("Buscar na lista")).to_have_value("Água")
        item.refresh_from_db()
        self.assertFalse(item.contado)
        self.assertEqual(saldo(self.product, self.shop), Decimal("20"))
        self._foto("fase6-inventario-erro-390.png")
        campo.fill("18")
        p.get_by_role("button", name="Salvar contagem", exact=True).click()
        expect(p.locator("[data-erros-envio]")).to_have_count(0)
        expect(p.get_by_label("Buscar na lista")).to_have_value("")
        item.refresh_from_db()
        self.assertTrue(item.contado)
        self.assertEqual(item.quantidade_contada, Decimal("18"))
        self.assertEqual(saldo(self.product, self.shop), Decimal("20"))

    def test_daypass_configuracao_reserva_recebimento_acesso_e_consumo(self):
        from apps.daypass.models import TurnoDayPass, VisitaDayPass
        from apps.restaurante.models import Comanda

        p = self.page
        p.emulate_media(reduced_motion="reduce")
        p.goto(self.url(reverse("daypass:painel")))
        expect(p.get_by_text("Nenhum turno configurado", exact=True)).to_be_visible()
        p.get_by_role("link", name="Configurar turno").click()
        for nome, valor in {"data": self.today.isoformat(), "nome": "Piscina QA", "inicio": "00:00", "fim": "23:59", "capacidade": "4", "preco_adulto": "5000", "preco_crianca": "2500", "preco_hospede": "0"}.items():
            p.locator(f'[name="{nome}"]').fill(valor)
        p.locator('[name="contar_hospedes"]').select_option("sim")
        p.locator('[name="ativo"]').check()
        p.get_by_role("button", name="Salvar turno").click()
        expect(p.get_by_role("heading", name="Day pass", exact=True)).to_be_visible()
        turno = TurnoDayPass.objects.get(nome="Piscina QA")
        self.assertEqual(turno.preco_adulto, Decimal("50"))
        p.get_by_role("link", name="Cadastrar grupo", exact=True).click()
        p.locator('[name="responsavel"]').select_option(str(self.guest.pk))
        p.locator('[name="adultos"]').fill(self.guest.nome)
        p.locator('[name="criancas"]').fill("Criança visitante QA")
        p.get_by_role("button", name="Reservar vagas").click()
        expect(p.get_by_role("heading", name=self.guest.nome, exact=True, level=1)).to_be_visible()
        visita = VisitaDayPass.objects.get(turno=turno)
        self.assertEqual(visita.valor_ingressos, Decimal("75"))
        for largura in (320, 390, 821, 1440, 2560, 3440):
            p.set_viewport_size({"width": largura, "height": 900})
            for nome, args in (("daypass:painel", []), ("daypass:turno", [turno.pk]), ("daypass:nova_visita", [turno.pk]), ("daypass:visita", [visita.pk]), ("daypass_publico", [])):
                with self.subTest(largura=largura, tela=nome):
                    resposta = p.goto(self.url(reverse(nome, args=args)), wait_until="networkidle")
                    self.assertEqual(resposta.status, 200)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
                    if largura in (320, 1440):
                        self._foto(f"fase5-{nome.replace(':','-')}-{largura}.png", full_page=True)
        p.set_viewport_size({"width":390,"height":900})
        p.goto(self.url(reverse("daypass:visita", args=[visita.pk])))
        p.locator('[name="forma"]').select_option(str(self.cash.pk))
        p.locator('[name="valor"]').fill("8000")
        p.get_by_role("button", name="Registrar recebimento").click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("supera o saldo")
        expect(p.locator('[name="valor"]')).to_have_value("80,00")
        expect(p.locator('[name="forma"]')).to_have_value(str(self.cash.pk))
        self.assertEqual(visita.total_pago(), 0)
        self._foto("fase5-pagamento-erro-preservado.png")
        p.locator('[name="valor"]').fill("7500")
        pagamento_url = "**" + reverse("daypass:acao", args=[visita.pk, "receber"])
        p.route(pagamento_url, lambda rota: rota.abort("failed"))
        p.get_by_role("button", name="Registrar recebimento").click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("conexão")
        expect(p.locator('[name="valor"]')).to_have_value("75,00")
        self.assertEqual(visita.total_pago(), 0)
        p.unroute(pagamento_url)
        p.get_by_role("button", name="Registrar recebimento").click()
        expect(p.get_by_role("button", name="Registrar recebimento")).to_have_count(0)
        self.assertEqual(visita.total_pago(), Decimal("75"))
        for restantes in (1, 0):
            p.get_by_role("button", name="Registrar entrada", exact=True).first.click()
            expect(p.get_by_role("button", name="Registrar entrada", exact=True)).to_have_count(restantes)
        p.locator('[name="local"]').select_option(str(self.kitchen.pk))
        p.get_by_role("button", name="Abrir comanda", exact=True).click()
        expect(p.locator('.pdv-produto').filter(has_text=self.product.nome)).to_be_visible()
        comanda = Comanda.objects.get(visita_daypass=visita)
        p.locator('.pdv-produto').filter(has_text=self.product.nome).click()
        expect(p.get_by_role("dialog")).to_be_visible()
        p.get_by_role("dialog").get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(p.get_by_role("dialog")).to_be_hidden()
        p.locator('.comanda-fechar [name="forma"]').select_option(str(self.cash.pk))
        p.get_by_role("button", name="Fechar comanda", exact=True).click()
        expect(p.get_by_role("button", name="Fechar comanda", exact=True)).to_have_count(0)
        comanda.refresh_from_db()
        self.assertEqual(comanda.status, "fechada")
        p.goto(self.url(reverse("daypass:visita", args=[visita.pk])))
        for restantes in (1, 0):
            p.get_by_role("button", name="Registrar saída", exact=True).first.click()
            expect(p.get_by_role("button", name="Registrar saída", exact=True)).to_have_count(restantes)
        p.get_by_role("button", name="Encerrar visita", exact=True).click()
        expect(p.get_by_role("button", name="Encerrar visita", exact=True)).to_have_count(0)
        visita.refresh_from_db()
        self.assertEqual(visita.status, "encerrada")

    def test_formulario_preserva_texto_selecao_arquivo_e_erro_de_rede(self):
        from apps.escala.models import Turno

        p = self.page
        p.goto(self.url(reverse("escala:turnos")))
        nome = "Nome de turno que excede o limite de quarenta caracteres QA"
        p.locator('[name="nome"]').evaluate("campo => campo.removeAttribute('maxlength')")
        p.locator('[name="nome"]').fill(nome)
        p.locator('[name="inicio"]').fill("09:00")
        p.locator('[name="fim"]').fill("17:00")
        p.get_by_role("button", name="Salvar turno", exact=True).click()
        expect(p.locator('[data-erros-envio]')).to_be_visible()
        expect(p.locator('[name="nome"]')).to_have_value(nome)
        expect(p.locator('[name="inicio"]')).to_have_value("09:00")
        self.assertFalse(Turno.objects.filter(nome=nome).exists())
        p.locator('[name="nome"]').fill("Turno preservado QA")
        p.get_by_role("button", name="Salvar turno", exact=True).click()
        expect(p.get_by_text("Turno cadastrado.", exact=True)).to_be_visible()
        self.assertEqual(Turno.objects.filter(nome="Turno preservado QA").count(), 1)
        p.goto(self.url(reverse("conciliacao:painel")))
        p.locator('#arq-ofx').set_input_files({"name":"extrato-qa.ofx","mimeType":"application/x-ofx","buffer":b"conteudo invalido QA"})
        p.locator('#conta-ofx').fill("Conta ficticia QA")
        with p.expect_response(lambda r: r.request.method == "POST" and "importar" in r.url):
            p.get_by_role("button", name="Importar OFX", exact=True).click()
        expect(p.locator('[data-erros-envio]')).to_be_visible()
        expect(p.locator('#conta-ofx')).to_have_value("Conta ficticia QA")
        self.assertEqual(p.locator('#arq-ofx').evaluate("el => el.files[0].name"), "extrato-qa.ofx")
        p.route("**/conciliacao/importar-ofx/", lambda rota: rota.abort("failed"))
        p.get_by_role("button", name="Importar OFX", exact=True).click()
        expect(p.locator('[data-erros-envio]')).to_contain_text("conexão")
        expect(p.get_by_role("button", name="Importar OFX", exact=True)).to_be_enabled()
        self.assertEqual(p.locator('#arq-ofx').evaluate("el => el.files[0].name"), "extrato-qa.ofx")
        self._foto("fase5-arquivo-erro-preservado.png")
        p.evaluate("EdicaoPendente.limpar(document)")

    def test_htmx_preserva_resposta_recusada_e_modal_nao_fecha_no_erro(self):
        from django.core.exceptions import ValidationError

        from apps.governanca import services as governanca
        from apps.nucleo import logbook_services

        entrada = logbook_services.registrar_ocorrencia(self.op, "Recado fictício QA")
        p = self.page
        p.goto(self.url(reverse("logbook")))
        form = p.locator(f'#occ-{entrada.pk} .lb-replybox')
        form.locator('[name="texto"]').fill("Minha resposta ainda não foi salva QA")
        logbook_services.resolver(self.op, entrada, "Resolvido em outra estação")
        form.get_by_role("button", name="Enviar", exact=True).click()
        expect(p.locator(f'#occ-{entrada.pk} .lb-erro')).to_contain_text("já foi resolvida")
        expect(p.locator(f'#occ-{entrada.pk} [name="texto"]')).to_have_value("Minha resposta ainda não foi salva QA")
        tarefa = governanca.abrir_faxina(self.room, usuario=self.op)
        governanca.iniciar_tarefa(tarefa, self.op)
        governanca.concluir_tarefa(tarefa, self.op)
        p.goto(self.url(reverse("governanca:quartos")))
        p.locator(f'[hx-get="{reverse("governanca:devolver", args=[self.room.pk])}"]').first.click()
        expect(p.get_by_role("dialog")).to_be_visible()
        p.get_by_role("dialog").locator('[name="motivo"]').fill("Conferir o banheiro QA")
        with patch("apps.governanca.services.reprovar_inspecao", side_effect=ValidationError("Revisão recusada para teste QA")):
            with p.expect_response(lambda r: r.request.method == "POST" and "governanca" in r.url):
                p.get_by_role("button", name="Solicitar nova limpeza", exact=True).click()
            expect(p.get_by_role("dialog").locator('[data-erros-envio]')).to_contain_text("Revisão recusada para teste QA")
        expect(p.get_by_role("dialog")).to_be_visible()
        expect(p.get_by_role("dialog").locator('[name="motivo"]')).to_have_value("Conferir o banheiro QA")
        self._foto("fase5-modal-erro-preservado.png")
        p.get_by_role("button", name="Solicitar nova limpeza", exact=True).click()
        expect(p.get_by_role("dialog")).to_be_hidden()

    def test_fiscal_integracoes_e_devolucao_nas_seis_larguras(self):
        from apps.fiscal.models import ConfigFiscalProduto, DocumentoFiscal
        from apps.pagamentos import services as pagamentos
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        self.product.natureza = "consumo"
        self.product.save(update_fields=["natureza"])
        self.cobranca.gateway, self.cobranca.gateway_ambiente = "pix_direto", "manual"
        self.cobranca.save(update_fields=["gateway", "gateway_ambiente"])
        pagamentos.confirmar_pagamento(self.cobranca, self.op)
        rotas = [("integracoes", []), ("fiscal:painel", []), ("fiscal:produtos", []),
                 ("fiscal:produto", [self.product.pk]), ("fiscal:preparar_conta", [self.conta.pk]),
                 ("pagamentos:detalhe", [self.cobranca.pk]), ("pessoa_editar", [self.guest.pk])]
        for largura in (320, 390, 821, 1440, 2560, 3440):
            p.set_viewport_size({"width":largura,"height":900})
            for nome, args in rotas:
                with self.subTest(largura=largura, tela=nome):
                    resposta = p.goto(self.url(reverse(nome, args=args)), wait_until="networkidle")
                    self.assertEqual(resposta.status, 200)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
                    if largura in (320, 1440):
                        self._foto("fase4-"+nome.replace(":","-")+f"-{largura}.png", full_page=True)
        p.set_viewport_size({"width":390,"height":900})
        p.goto(self.url(reverse("fiscal:produto", args=[self.product.pk])))
        for nome, valor in {"ncm":"22021000", "cfop":"5102", "cst_csosn":"00", "origem":"0", "pis":"01", "cofins":"01", "tributos":"{}"}.items():
            p.locator(f'[name="{nome}"]').fill(valor)
        p.locator('[name="conferido"]').check()
        p.get_by_role("button", name="Salvar cadastro fiscal", exact=True).click()
        expect(p.get_by_role("heading", name="Cadastro fiscal de produtos", exact=True)).to_be_visible()
        self.assertEqual(ConfigFiscalProduto.objects.get(produto=self.product).ncm, "22021000")
        p.goto(self.url(reverse("fiscal:preparar_conta", args=[self.conta.pk])))
        with override_settings(FISCAL_GATEWAY="simulado"):
            p.get_by_role("button", name="Emitir NFS-e", exact=True).click()
            expect(p.get_by_text("Documento de teste", exact=False)).to_be_visible()
        self.assertEqual(DocumentoFiscal.objects.get(referencia=f"conta:{self.conta.pk}").status, "autorizada")
        p.goto(self.url(reverse("pagamentos:detalhe", args=[self.cobranca.pk])))
        p.locator('[name="referencia_devolucao"]').fill("COMPROVANTE-QA-0001")
        p.locator('[name="devolucao_confirmada"]').check()
        with patch("apps.pagamentos.services.get_gateway") as gateway:
            p.get_by_role("button", name="Registrar devolução do Pix", exact=True).click()
            expect(p.get_by_text("Devolução manual registrada.", exact=True)).to_be_visible()
        gateway.assert_not_called()
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, "estornado")

    def test_checkout_cartao_coleta_endereco_e_sessao_sem_gravar_cartao(self):
        from apps.pagamentos import services as pagamentos
        from apps.pagamentos.models import Cobranca
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        cartao = Cobranca.objects.create(valor="20", metodo="link", descricao="Pagamento QA",
            gateway="safrapay", gateway_ambiente="ambiente-ficticio", criado_por=self.op, pagador=self.guest)
        p.route("https://safrastatic-a.akamaihd.net/**", lambda rota: rota.fulfill(
            content_type="application/javascript", body="window.onSafrapayAntifraudReady({setCredentials:function(){},getSessionId:function(){return 'sessao-qa';}});"))
        with override_settings(SAFRAPAY_ID="estabelecimento-qa", SAFRAPAY_ENV="hml"):
            for largura in (320, 390, 821, 1440, 2560, 3440):
                p.set_viewport_size({"width":largura,"height":900})
                p.goto(self.url(reverse("pagamentos:pagar", args=[cartao.token])))
                expect(p.locator('[name="session_id"]')).to_have_value("sessao-qa")
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
                self.assertEqual(p.locator('.pay-confianca').count(), 1)
                for linha in p.locator('.card-form .linha').all():
                    bases = linha.locator('input').evaluate_all('els => els.map(e => e.getBoundingClientRect().bottom)')
                    self.assertLessEqual(max(bases)-min(bases), 1)
                if largura in (320, 1440):
                    self._foto(f"fase4-cartao-{largura}.png", full_page=True)
            p.set_viewport_size({"width":390,"height":900})
            dados = {"nome":"Pessoa QA", "numero":"4111111111111111", "validade":"1230", "cvv":"123", "documento":"11144477735", "logradouro":"Rua de Teste", "numero_endereco":"10", "bairro":"Bairro QA", "cidade":"Itá", "uf":"SC", "cep":"89760000"}
            for nome, valor in dados.items():
                p.locator(f'[name="{nome}"]').fill(valor)
            with patch("apps.pagamentos.services.autorizar_cartao_online", return_value=(False, "Recusa fictícia QA")):
                p.get_by_role("button", name="Pagar R$ 20,00", exact=True).click()
                expect(p.locator('[data-erros-envio]')).to_contain_text("Não foi possível confirmar")
            expect(p.locator('[name="logradouro"]')).to_have_value("Rua de Teste")
            expect(p.locator('[name="numero"]')).to_have_value("4111 1111 1111 1111")
            expect(p.locator('[name="cvv"]')).to_have_value("123")
            self.assertFalse(p.evaluate("Object.values(sessionStorage).some(v=>v.includes('4111111111111111'))"))
            self.assertFalse(p.evaluate("Object.values(localStorage).some(v=>v.includes('4111111111111111'))"))
            def confirmar(cobranca, card, **kwargs):
                self.assertEqual(kwargs["session_id"], "sessao-qa")
                self.assertEqual(card["billingAddress"]["street"], "Rua de Teste")
                pagamentos.confirmar_pagamento(cobranca, self.op)
                return True, "Pagamento aprovado."
            with patch("apps.pagamentos.services.autorizar_cartao_online", side_effect=confirmar) as autorizar:
                p.get_by_role("button", name="Pagar R$ 20,00", exact=True).click()
                expect(p.get_by_text("Pagamento confirmado. Obrigado!", exact=False)).to_be_visible()
                self.assertEqual(autorizar.call_count, 1)
        cartao.refresh_from_db()
        self.assertNotIn("4111111111111111", str(cartao.payload))

    def test_pesquisa_pos_estadia_recebe_opiniao_e_equipe_registra_acompanhamento(self):
        from apps.nps.models import RespostaNPS
        from apps.reservas.models import Reserva

        Reserva.objects.filter(pk=self.hospedagem.pk).update(
            status=Reserva.Status.CHECKOUT, checkout_real=timezone.now())
        p = self.page
        p.goto(self.url(reverse("portal:nps", args=[self.acesso.token])))
        for largura in (320, 390, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura+1)
            alvos = p.locator(".pt-nps-escolha").evaluate_all("els => els.map(e=>e.getBoundingClientRect().height)")
            self.assertEqual(len(alvos), 11)
            self.assertTrue(all(h >= 44 for h in alvos))
            self._foto(f"pesquisa-nps-{largura}.png")
        p.locator('input[name="nota"][value="9"]').check()
        p.locator('[name="comentario"]').fill("Atendimento da recepção muito bom.")
        p.locator('[name="consentimento"]').check()
        p.get_by_role("button", name="Enviar minha avaliação").click()
        expect(p.get_by_text("Obrigado! Sua avaliação foi registrada.", exact=True)).to_be_visible()
        self.assertEqual(RespostaNPS.objects.get(reserva=self.hospedagem).nota, 9)
        p.goto(self.url(reverse("nps:painel")))
        expect(p.get_by_text("Atendimento da recepção muito bom.", exact=True)).to_be_visible()
        p.get_by_text("Registrar acompanhamento", exact=True).click()
        p.locator('[name="tratativa"]').fill("Agradecimento registrado pela equipe.")
        p.get_by_role("button", name="Salvar acompanhamento").click()
        expect(p.get_by_text("Acompanhamento registrado.", exact=True)).to_be_visible()
        self.assertEqual(RespostaNPS.objects.get(reserva=self.hospedagem).tratativa,
                         "Agradecimento registrado pela equipe.")
        self._foto("nps-painel-acompanhamento.png")

    def test_governanca_avisa_fila_nova_e_respeita_preferencia_do_hospede(self):
        from apps.governanca import services
        from apps.governanca.models import TarefaGovernanca
        from apps.reservas.models import Reserva

        Reserva.objects.filter(pk=self.hospedagem.pk).update(checkin_real=timezone.now()-timedelta(days=1))
        p = self.page
        p.clock.install()
        p.set_viewport_size({"width": 390, "height": 900})
        p.goto(self.url(reverse("governanca:quartos")), wait_until="networkidle")
        self.assertEqual(services.gerar_arrumacoes_do_dia(), 1)
        tarefa = TarefaGovernanca.objects.get(uh=self.hospedagem.uh)
        services.atribuir_tarefa(tarefa, self.op.pk, self.op)
        p.clock.fast_forward(61000)
        expect(p.locator('[data-governanca-atualizacao]')).to_be_visible()
        p.get_by_role("link", name="Atualizar esta página").click()
        p.goto(self.url(reverse("governanca:quarto", args=[self.hospedagem.uh_id])))
        p.get_by_text("Preferência de limpeza do hóspede", exact=True).click()
        p.locator('[name="tipo"]').select_option("dispensa")
        p.get_by_role("button", name="Salvar preferência").click()
        expect(p.get_by_role("button", name="Iniciar limpeza", exact=True)).to_have_count(0)
        p.goto(self.url(reverse("governanca:minha_fila")))
        expect(p.get_by_text("Limpeza dispensada hoje", exact=True)).to_be_visible()
        self._foto("governanca-preferencia-390.png")
        p.emulate_media(reduced_motion="reduce")
        for nome in ("governanca:painel", "governanca:quartos", "governanca:minha_fila"):
            for largura in (320, 390, 414, 768, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 900})
                    p.goto(self.url(reverse(nome)), wait_until="networkidle")
                    if nome == "governanca:painel":
                        p.locator(".corredor-gov").scroll_into_view_if_needed()
                    self._foto(f"fase6-limpeza-dispensada-{nome.split(':')[-1]}-{largura}.png")
                    excedentes = p.evaluate("""() => {
                        const problemas=[];
                        for (const caixa of document.querySelectorAll('.porta-gov,.gov-fila-item,.tabela-cartoes tbody tr')) {
                            const limite=caixa.getBoundingClientRect();
                            if (!limite.width || !limite.height) continue;
                            for (const el of caixa.querySelectorAll('*')) {
                                const r=el.getBoundingClientRect();
                                if (!r.width || !r.height || getComputedStyle(el).position==='fixed') continue;
                                if (r.right>limite.right+1 || r.left<limite.left-1)
                                    problemas.push({classe:el.className,texto:el.textContent.trim().slice(0,100),largura:r.width,limite:limite.width});
                                if (el.matches('.porta-flag,.acao-pronta,.aviso')) {
                                    const texto=document.createRange(); texto.selectNodeContents(el);
                                    for (const t of texto.getClientRects()) {
                                        if(t.right>limite.right+1 || t.left<limite.left-1 || t.bottom>limite.bottom+1)
                                            problemas.push({classe:el.className,texto:el.textContent.trim(),textoDireita:t.right,cartaoDireita:limite.right,textoAbaixo:t.bottom,cartaoAbaixo:limite.bottom});
                                    }
                                }
                            }
                        }
                        return problemas;
                    }""")
                    self.assertFalse(excedentes, excedentes)

    def test_menu_mantem_centro_e_transicao_sem_deslocamento(self):
        p = self.page
        p.set_viewport_size({"width": 1440, "height": 900})
        p.emulate_media(reduced_motion="no-preference")
        p.goto(self.url(reverse("estoque:posicao")), wait_until="networkidle")
        p.evaluate("""() => {
            window.framesNavegacao=[];
            document.addEventListener('htmx:beforeSwap',()=>{
                const fim=performance.now()+600;
                function medir() {
                    const main=document.querySelector('.main').getBoundingClientRect();
                    const c=document.querySelector('.conteudo').getBoundingClientRect();
                    const deformacoes=document.getAnimations().flatMap(a=>{
                        const pseudo=a.effect?.pseudoElement || '';
                        if(!pseudo.includes('conteudo'))return [];
                        return a.effect.getKeyframes().filter(f=>f.transform && f.transform!=='none');
                    });
                    window.framesNavegacao.push({delta:c.x+c.width/2-main.x-main.width/2,
                                                transform:getComputedStyle(document.querySelector('.conteudo')).transform,
                                                deformacoes:deformacoes.length});
                    if(performance.now()<fim)requestAnimationFrame(medir);
                }
                requestAnimationFrame(medir);
            });
        }""")
        for rota in ("governanca:painel", "marketing:entregas", "escala:grade", "estoque:posicao"):
            p.locator(f'#menu-principal a[href="{reverse(rota)}"]').click()
            p.wait_for_url("**"+reverse(rota))
            p.wait_for_function("!document.querySelector('.htmx-request')")
            p.evaluate("async () => { if(document.activeViewTransition)await document.activeViewTransition.finished; }")
        medidas = p.evaluate("window.framesNavegacao")
        self.assertGreater(len(medidas), 5)
        self.assertTrue(all(abs(m["delta"]) <= 1 and m["transform"] == "none" and not m["deformacoes"] for m in medidas), medidas)
        abas = p.locator('.est-abas .est-aba')
        self.assertGreaterEqual(abas.count(), 4)
        self.assertEqual(p.locator('.est-abas [aria-current="page"]').count(), 1)
        self.assertEqual(p.locator('.est-abas [aria-current="page"]').evaluate("e=>getComputedStyle(e).borderBottomWidth"), "2px")

    def test_arrastar_reserva_entre_linhas_muda_quarto_e_preserva_conta(self):
        from apps.nucleo.models import UH

        p = self.page
        p.set_viewport_size({"width": 1440, "height": 1000})
        p.goto(self.url(reverse("reservas:mapa")))
        destino = UH.objects.get(numero="QA-02")
        barra = p.locator(f'.mapa-barra[data-reserva="{self.hospedagem.pk}"]')
        linha = p.locator(f'.mapa-linha[data-uh="{destino.pk}"]')
        barra.scroll_into_view_if_needed()
        origem = barra.bounding_box()
        alvo = linha.bounding_box()
        x = origem["x"] + origem["width"] / 2
        y = origem["y"] + origem["height"] / 2
        p.once("dialog", lambda dialog: dialog.accept())
        with p.expect_response(lambda response: response.url.endswith(
            reverse("reservas:trocar_quarto", args=[self.hospedagem.pk])
        ), timeout=7000) as resposta:
            p.mouse.move(x, y)
            p.mouse.down()
            p.mouse.move(x, alvo["y"] + alvo["height"] / 2, steps=12)
            p.mouse.up()
        self.assertTrue(resposta.value.json()["ok"])
        self.hospedagem.refresh_from_db()
        self.assertEqual(self.hospedagem.uh_id, destino.pk)
        self.assertEqual(self.hospedagem.conta.pk, self.conta.pk)
        expect(linha.locator(f'[data-reserva="{self.hospedagem.pk}"]')).to_be_visible()
        self._foto("reserva-arraste-concluido.png")

    def test_caixa_alinha_paineis_e_dashboard_contem_identificacao_do_quarto(self):
        from apps.reservas.models import Reserva

        chegada = Reserva.objects.create(
            uh=self.room, hospede=self.guest, criado_por=self.op,
            checkin=self.today, checkout=self.today + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=300,
        )
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        for largura in (320, 390, 1024, 1440, 2560, 3440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 900})
                p.goto(self.url(reverse("caixa")))
                medidas = p.evaluate("""() => {
                    const box=s=>document.querySelector(s).getBoundingClientRect();
                    const main=box('.main'), painel=box('.caixa-operacao');
                    const forms=[...document.querySelectorAll('.caixa-formulario')].map(el=>{
                        const r=el.getBoundingClientRect(), t=el.querySelector('h2').getBoundingClientRect();
                        return {x:r.x,y:r.y,right:r.right,ty:t.y,tr:t.right};
                    });
                    return {centro:main.x+main.width/2, painel:painel.x+painel.width/2,
                            largura:document.documentElement.scrollWidth, forms};
                }""")
                self.assertAlmostEqual(medidas["centro"], medidas["painel"], delta=1)
                self.assertLessEqual(medidas["largura"], largura + 1)
                for form in medidas["forms"]:
                    self.assertGreater(form["ty"], form["y"])
                    self.assertLess(form["tr"], form["right"])
                if largura >= 1440:
                    self.assertAlmostEqual(medidas["forms"][0]["y"], medidas["forms"][1]["y"], delta=1)
                self._foto(f"caixa-alinhado-{largura}.png")
                p.goto(self.url(reverse("dashboard")))
                expect(p.get_by_role("heading", name="Visão geral", exact=True)).to_be_visible()
                linha = p.locator(f'#chegadas-hoje li[data-reserva-id="{chegada.pk}"]')
                expect(linha).to_contain_text(self.guest.nome)
                detalhe = reverse("reservas:detalhe", args=[chegada.pk])
                expect(linha.locator(".painel-estadia-identidade")).to_have_attribute("href", detalhe)
                expect(linha.get_by_role("link", name="Check-in", exact=True)).to_have_attribute(
                    "href", detalhe + "#acoes-estadia")
                badge = linha.locator(".painel-estadia-quarto")
                expect(badge).to_contain_text("QA-01")
                texto = badge.evaluate("""el => {
                    const r=el.getBoundingClientRect(), range=document.createRange();
                    range.selectNodeContents(el);const t=range.getBoundingClientRect();
                    return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
                            textLeft:t.left,textRight:t.right,textTop:t.top,textBottom:t.bottom};
                }""")
                self.assertGreaterEqual(texto["textLeft"], texto["left"])
                self.assertLessEqual(texto["textRight"], texto["right"])
                self.assertGreaterEqual(texto["textTop"], texto["top"])
                self.assertLessEqual(texto["textBottom"], texto["bottom"])
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                self._foto(f"dashboard-identificacao-{largura}.png")

    def test_busca_titulo_e_formulario_compartilham_o_centro_da_area_util(self):
        p = self.page
        p.emulate_media(reduced_motion="reduce")
        rotas = [reverse("mfa_config"), reverse("uh_editar", args=[self.room.pk]),
                 reverse("tipo_uh_novo"), reverse("pessoa_nova")]
        for largura in (320, 390, 1024, 1440, 2560, 3440):
            p.set_viewport_size({"width": largura, "height": 900})
            for rota in rotas:
                for recolhido in ((False, True) if largura > 820 else (False,)):
                    with self.subTest(largura=largura, rota=rota, recolhido=recolhido):
                        p.goto(self.url(rota))
                        if recolhido:
                            p.get_by_role("button", name="Recolher menu", exact=True).click()
                            expect(p.get_by_role("button", name="Expandir menu", exact=True)).to_be_visible()
                        medidas = p.evaluate("""() => {
                            const box = selector => document.querySelector(selector).getBoundingClientRect();
                            const main = box('.main');
                            const cartao = box('.conteudo > .form-cartao, .conteudo-compacto > .cartao-estreito');
                            const busca = box('.busca-global');
                            return {centro: main.x + main.width / 2,
                                    cartao: cartao.x + cartao.width / 2,
                                    busca: busca.x + busca.width / 2,
                                    titulo: box('main h1').x, borda: cartao.x,
                                    documento: document.documentElement.scrollWidth};
                        }""")
                        self.assertAlmostEqual(medidas["busca"], medidas["centro"], delta=1)
                        self.assertAlmostEqual(medidas["cartao"], medidas["centro"], delta=1)
                        self.assertAlmostEqual(medidas["titulo"], medidas["borda"], delta=1)
                        self.assertLessEqual(medidas["documento"], largura + 1)
        p.locator('.busca-global').click()
        expect(p.get_by_role("dialog", name="Buscar na pousada", exact=True)).to_be_visible()
        p.locator('#paleta-input').press("Escape")
        expect(p.get_by_role("dialog", name="Buscar na pousada", exact=True)).to_be_hidden()

    def test_conciliacao_alinha_controles_mesmo_com_nome_de_arquivo_longo(self):
        p = self.page
        for largura in (320, 390, 821, 1024, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 900})
                p.goto(self.url(reverse("conciliacao:painel")))
                for com_arquivo in (False, True):
                    if com_arquivo:
                        for formato in ("ofx", "csv"):
                            p.locator(f"#arq-{formato}").set_input_files({
                                "name": "extrato_conta_da_pousada_" + "outubro_" * 12 + f".{formato}",
                                "mimeType": "application/octet-stream", "buffer": b"arquivo ficticio QA",
                            })
                    for linha in p.locator(".conciliacao-campos").all():
                        controles = linha.locator(".escolher-arquivo, input[type=text], button").evaluate_all(
                            "els => els.map(el => {const r=el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom};})"
                        )
                        self.assertTrue(controles)
                        for controle in controles:
                            self.assertGreaterEqual(controle["h"], 40)
                            self.assertGreaterEqual(controle["x"], 0)
                            self.assertLessEqual(controle["x"] + controle["w"], largura + 1)
                        if largura >= 821:
                            self.assertLessEqual(max(c["b"] for c in controles) - min(c["b"] for c in controles), 1)
                    if largura >= 1440:
                        bases = p.locator(".conciliacao-campos > button").evaluate_all(
                            "els => els.map(el => el.getBoundingClientRect().bottom)")
                        self.assertLessEqual(max(bases) - min(bases), 1)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    self._foto(f"conciliacao-{largura}-{'arquivo' if com_arquivo else 'vazio'}.png", full_page=True)
                p.locator("#arq-ofx").focus()
                self.assertEqual(p.locator("label.escolher-arquivo").first.evaluate(
                    "el => getComputedStyle(el).outlineStyle"), "solid")

    def test_cabecalhos_indicadores_e_paineis_tem_espaco_entre_blocos(self):
        p = self.page
        paginas = [
            ("comercial:pagina_detalhe", [self.pagina.pk],
             [(".pagina-cabecalho", ".kpis"), (".kpis", ".detalhe-2col")]),
            ("comercial:email_campanha_detalhe", [self.email.pk],
             [(".pagina-cabecalho", ".kpis-el"), (".kpis-el", ".cartao-el")]),
            ("loja:pdv", [], [(".pagina-cabecalho", ".pdv-shell")]),
            ("caixa", [], [(".caixa-indicadores", ".caixa-operacao")]),
            ("lancamentos", [], [(".cartoes-indicadores", ".filtros")]),
        ]
        for nome in ("pagina_nova", "pagina_editar", "resposta_nova", "email_campanha_nova", "email_template_novo"):
            paginas.append((f"comercial:{nome}", [self.pagina.pk] if nome == "pagina_editar" else [],
                            [(".pagina-cabecalho", ".eleg-form")]))
        for nome, argumentos, pares in paginas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(nome, args=argumentos)))
                    p.evaluate("document.fonts.ready")
                    for anterior, seguinte in pares:
                        a = p.locator(anterior).first.bounding_box()
                        b = p.locator(seguinte).first.bounding_box()
                        self.assertGreaterEqual(b["y"] - a["y"] - a["height"],
                                                16 if largura <= 820 else 20, (anterior, seguinte))
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    if nome == "comercial:pagina_detalhe":
                        hierarquia = p.locator(".kpi").first.evaluate("""el => {
                            const valor=getComputedStyle(el.querySelector('.kpi-valor'));
                            const rotulo=getComputedStyle(el.querySelector('.kpi-rotulo'));
                            return {valor:parseFloat(valor.fontSize),
                                    proporcao:parseFloat(valor.fontSize) / parseFloat(rotulo.fontSize)};
                        }""")
                        self.assertGreaterEqual(hierarquia["valor"], 18)
                        self.assertGreaterEqual(hierarquia["proporcao"], 1.5 if largura <= 820 else 2)
                    if nome == "comercial:email_campanha_detalhe":
                        larguras = p.locator(".kpis-el .kpi").evaluate_all(
                            "els => els.map(el => el.getBoundingClientRect().width)")
                        self.assertLessEqual(max(larguras) - min(larguras), 1)

    def test_navegacao_dos_modulos_mantem_opcoes_acessiveis_sem_cortar_rotulos(self):
        p = self.page
        for rota in ("escala:grade", "comercial:funil", "marketing:quadro", "estoque:posicao"):
            for largura in (320, 390, 821, 1440):
                with self.subTest(rota=rota, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(rota)))
                    p.evaluate("document.fonts.ready")
                    grupos = p.locator(".seg-filtro, .segmentado, .est-abas").evaluate_all("""els => els.map(el => {
                        const r = el.getBoundingClientRect();
                        return {largura:el.clientWidth, conteudo:el.scrollWidth,
                            faixa:el.classList.contains('abas-secao'), overflow:getComputedStyle(el).overflowX,
                            itens:[...el.querySelectorAll('a,button')].map(a=>({
                                y:a.getBoundingClientRect().top,h:a.getBoundingClientRect().height,
                                cortado:a.scrollWidth>a.clientWidth+1})),
                            fora:[...el.querySelectorAll('a,button')].filter(a => {
                                const b=a.getBoundingClientRect();
                                return b.left<r.left-1 || b.right>r.right+1 || b.top<r.top-1 || b.bottom>r.bottom+1;
                            }).map(a=>a.textContent.trim())};
                    })""")
                    self.assertTrue(grupos)
                    for grupo in grupos:
                        if grupo["faixa"]:
                            self.assertIn(grupo["overflow"], ("auto", "scroll"))
                            self.assertLess(max(a["y"] for a in grupo["itens"]) - min(a["y"] for a in grupo["itens"]), 1)
                            self.assertTrue(all(a["h"] >= 44 and not a["cortado"] for a in grupo["itens"]))
                        else:
                            self.assertLessEqual(grupo["conteudo"], grupo["largura"] + 1)
                            self.assertFalse(grupo["fora"], grupo)
                    for faixa in p.locator(".abas-secao").all():
                        for link in (faixa.locator("a").first, faixa.locator("a").last):
                            link.focus()
                            limites, item = faixa.bounding_box(), link.bounding_box()
                            self.assertGreaterEqual(item["x"], limites["x"] - 1)
                            self.assertLessEqual(item["x"] + item["width"], limites["x"] + limites["width"] + 1)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)

    def test_telas_acesso_mostram_formulario_com_e_sem_sessao(self):
        p = self.page
        paginas = [("login", [], "Entrar no sistema"),
                   ("senha_esqueci", [], "Esqueci minha senha"),
                   ("senha_enviada", [], "Confira seu e-mail"),
                   ("senha_trocada", [], "Senha trocada"),
                   ("password_reset_confirm", ["invalido", "invalido"], "Link expirado")]
        for conectado in (True, False):
            if not conectado:
                p.context.clear_cookies()
            for nome, args, titulo in paginas:
                for largura in (320, 390, 821, 1440):
                    with self.subTest(conectado=conectado, pagina=nome, largura=largura):
                        p.set_viewport_size({"width": largura, "height": 844})
                        p.goto(self.url(reverse(nome, args=args)))
                        expect(p.get_by_role("heading", name=titulo, exact=True)).to_be_visible()
                        p.wait_for_function("['.login-pagina', '.login-cartao'].every(s => getComputedStyle(document.querySelector(s)).opacity === '1')", timeout=6000)
                        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                        if nome == "senha_esqueci" and largura in (390, 1440) and conectado:
                            self._foto(f"senha-recuperacao-{largura}.png")

    def test_lps_so_confirmam_apos_gravar_e_permitem_corrigir_falha(self):
        from apps.comercial.models import Oportunidade, PaginaCaptacao

        p = self.page
        p.context.clear_cookies()
        paginas = [("fundador", "fundador"), ("fundador_2", "fundador-2"),
                   ("inauguracao", "inauguracao_31_10_2026")]
        for numero, (nome, slug) in enumerate(paginas):
            pagina = PaginaCaptacao.objects.create(
                nome=f"LP fictícia QA {numero}", slug=slug, status="publicada", criado_por=self.op
            )
            for largura in (320, 390, 1440):
                with self.subTest(pagina=nome, largura=largura):
                    cache.clear()
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(f"lp:{nome}")), wait_until="domcontentloaded")
                    if p.get_by_role("button", name="Recusar", exact=True).is_visible():
                        p.get_by_role("button", name="Recusar", exact=True).click()
                    form = p.locator("#formInaug" if nome == "inauguracao" else "#form-lista")
                    identidade = f"Contato LP QA {nome} {largura}"
                    telefone = f"49999{numero}{largura:04d}1"
                    form.locator("input[name=nome]").fill(identidade)
                    form.locator("input[name=whats]").fill(telefone)
                    if nome == "fundador":
                        form.locator("input[name=email]").fill(f"qa-{largura}@example.invalid")
                    form.locator("input[type=checkbox]").check()
                    enviar = form.locator("button").first
                    erro = form.locator("#formAlert" if nome == "inauguracao" else ".lp-captacao-erro")
                    endpoint = self.url(reverse(f"lp:{nome}_lead"))
                    # Tempo mínimo real do antirrobô; não desliga a defesa para o teste.
                    p.wait_for_timeout(1700)
                    with patch("apps.comercial.services.capturar_lead_site", side_effect=RuntimeError), p.expect_response(endpoint, timeout=6000) as resposta:
                        enviar.click()
                    self.assertEqual(resposta.value.status, 503)
                    expect(erro).to_be_visible()
                    expect(erro).to_be_focused()
                    expect(form.locator("input[name=nome]")).to_have_value(identidade)
                    expect(enviar).to_be_enabled()
                    self.assertFalse(Oportunidade.objects.filter(pessoa__nome=identidade).exists())
                    self._foto(f"lp-{nome}-erro-{largura}.png")
                    # HTTP 200 sem confirmação do CRM também deve manter o formulário.
                    p.route(endpoint, lambda rota: rota.fulfill(status=200, json={"ok": False}))
                    with p.expect_response(endpoint):
                        enviar.click()
                    expect(erro).to_be_visible()
                    expect(enviar).to_be_enabled()
                    p.unroute(endpoint)
                    form.locator("input[name=whats]").fill("20999990000")
                    with p.expect_response(endpoint) as invalido:
                        enviar.click()
                    self.assertEqual(invalido.value.status, 400)
                    expect(erro).to_contain_text("DDD 20 inválido")
                    expect(enviar).to_be_enabled()
                    self.assertFalse(Oportunidade.objects.filter(pessoa__nome=identidade).exists())
                    if largura == 390:
                        self._foto(f"lp-{nome}-dados-invalidos-390.png")
                    form.locator("input[name=whats]").fill(telefone)
                    with p.expect_response(endpoint):
                        enviar.click(click_count=2)
                    sucesso = p.locator("#ticketTitle" if nome == "inauguracao" else "#sucesso")
                    if nome == "inauguracao":
                        p.wait_for_function("document.querySelector('#card3d').classList.contains('flipped') && document.body.classList.contains('confirmado')", timeout=6000)
                    expect(sucesso).to_be_visible()
                    expect(sucesso).to_be_focused()
                    if nome == "inauguracao":
                        caixa = sucesso.bounding_box()
                        self.assertGreaterEqual(caixa["y"], 80)
                        self.assertLessEqual(caixa["y"] + caixa["height"], 844)
                    lead = Oportunidade.objects.get(pessoa__nome=identidade)
                    self.assertEqual(lead.pagina_captacao, pagina)
                    self.assertEqual("".join(c for c in lead.pessoa.telefone if c.isdigit()), telefone)
                    self.assertTrue(lead.pessoa.aceita_whatsapp)
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    self._foto(f"lp-{nome}-sucesso-{largura}.png")
                    p.evaluate("localStorage.removeItem('vt_inaug_conf')")

    def setUp(self):
        super().setUp()
        from apps.comercial import services as comercial
        from apps.comercial.models import CampanhaEmail, EtapaFunil, PaginaCaptacao, TemplateEmail
        from apps.lavanderia import services as lavanderia
        from apps.lavanderia.models import ServicoLavanderia
        from apps.manutencao import services as manutencao
        from apps.nucleo.models import (
            UH,
            CategoriaProduto,
            ConfiguracaoReservas,
            FormaPagamento,
            Hospede,
            LocalEstoque,
            ModuloContratado,
            Pessoa,
            PosicaoCama,
            Produto,
            SessaoCaixa,
            TipoUH,
            Usuario,
            registrar_entrada,
        )
        from apps.nucleo.modulos import Modulo
        from apps.pagamentos.services import criar_cobranca
        from apps.portal.services import get_acesso
        from apps.reservas import services as reservas
        from apps.restaurante import services as restaurante

        cache.clear()
        self.op = Usuario.objects.create_superuser(
            username="operacao-e2e", password="forte-123-abc"
        )
        for codigo, _ in Modulo.choices:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )
        self.kind = TipoUH.objects.create(
            nome="QA Standard", tarifa_base=Decimal("300"), capacidade=4
        )
        self.room = UH.objects.create(numero="QA-01", tipo=self.kind)
        UH.objects.create(numero="QA-02", tipo=self.kind)
        quarto_hospedado = UH.objects.create(numero="QA-03", tipo=self.kind)
        for quarto in UH.objects.filter(tipo=self.kind):
            PosicaoCama.objects.create(uh=quarto, nome="Quarto", montagem_padrao="casal")
        self.guest = Pessoa.objects.create(
            nome="Hóspede fictício QA", email="guest@example.invalid"
        )
        Hospede.objects.create(pessoa=self.guest)
        self.cash, _ = FormaPagamento.objects.get_or_create(
            nome="QA Dinheiro", defaults={"tipo": "dinheiro"}
        )
        categoria = CategoriaProduto.objects.create(nome="QA Bebidas")
        self.shop = LocalEstoque.objects.create(nome="QA Loja", modulo="loja")
        self.kitchen = LocalEstoque.objects.create(nome="QA Restaurante", modulo="restaurante")
        self.product = Produto.objects.create(
            nome="QA Água", categoria=categoria, preco_venda=Decimal("7")
        )
        for local in (self.shop, self.kitchen):
            registrar_entrada(self.product, local, Decimal("20"), Decimal("2"), self.op)
        for modulo in ("reservas", "loja", "restaurante", "lavanderia", "nucleo"):
            SessaoCaixa.objects.create(operador=self.op, modulo=modulo, fundo_troco=Decimal("100"))
        self.today = timezone.localdate()
        self.hospedagem = reservas.criar_prereserva(
            uh=quarto_hospedado,
            checkin=self.today,
            checkout=self.today + timedelta(days=2),
            hospede=self.guest,
            usuario=self.op,
            valor_diaria=Decimal("300"),
        )
        reservas.confirmar_reserva(self.hospedagem.pk, self.op)
        self.hospedagem.refresh_from_db()
        with override_settings(FNRH_BLOQUEAR_CHECKIN=False):
            self.conta = self.hospedagem.fazer_checkin(self.op)
        self.acesso = get_acesso(self.hospedagem.pk)
        self.comanda = restaurante.abrir_comanda(self.op, self.kitchen, rotulo="Mesa da família QA")
        restaurante.adicionar_item(self.comanda, self.product, 2, self.op)
        self.ordem = lavanderia.abrir_ordem(self.op, cliente=self.guest)
        servico = ServicoLavanderia.objects.create(nome="Lavagem de camisa QA", preco=Decimal("12"))
        lavanderia.adicionar_item(self.ordem, servico, 1, self.op)
        self.chamado = manutencao.abrir_os(
            self.op, area="Piscina QA", titulo="Verificar iluminação da piscina QA"
        )
        etapa, _ = EtapaFunil.objects.get_or_create(nome="Atendimento QA")
        self.lead = comercial.criar_oportunidade(
            usuario=self.op,
            pessoa=self.guest,
            titulo="Fim de semana em família QA",
            etapa=etapa,
            checkin_previsto=self.today + timedelta(days=5),
            checkout_previsto=self.today + timedelta(days=7),
            adultos=2,
            hospedes=2,
            disparar_crm=False,
        )
        self.pagina = PaginaCaptacao.objects.create(
            nome="Campanha de férias QA", slug="ferias-qa", status="publicada", criado_por=self.op
        )
        self.template = TemplateEmail.objects.create(
            nome="Proposta QA",
            assunto="Sua estadia",
            corpo="Olá, {primeiro_nome}.",
            criado_por=self.op,
        )
        self.email = CampanhaEmail.objects.create(
            nome="Férias QA",
            assunto="Sua próxima estadia",
            corpo="Mensagem fictícia.",
            criado_por=self.op,
        )
        self.cobranca = criar_cobranca(
            self.op, valor=Decimal("150"), metodo="pix", descricao="Cobrança fictícia de teste"
        )
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("operacao-e2e", "forte-123-abc")

    def _foto(self, nome, full_page=False):
        destino = os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.evaluate("""async () => {
                await document.fonts.ready;
                if (document.activeViewTransition) await document.activeViewTransition.finished;
                const transicoes = document.getAnimations().filter(a => {
                    const tempo = a.effect?.getComputedTiming();
                    return tempo && Number.isFinite(tempo.endTime) && tempo.endTime <= 3000;
                });
                await Promise.all(transicoes.map(a => a.finished.catch(() => {})));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }""")
            if full_page:
                self.page.evaluate("window.scrollTo(0, 0)")
            self.page.screenshot(path=str(pasta / nome), full_page=full_page)

    def abrir(self, nome, *args):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.url(reverse(nome, args=args)))

    def test_grupo_adiciona_quarto_faz_checkin_e_recebe_pelas_telas(self):
        from apps.reservas.models import PagamentoConta, Reserva
        from apps.reservas.services import criar_grupo

        grupo = criar_grupo(
            rotulo="Família QA", titular=self.guest, checkin=self.today,
            checkout=self.today + timedelta(days=2), usuario=self.op,
        )
        p = self.page
        self.abrir("reservas:grupo_detalhe", grupo.pk)
        p.get_by_label("Quarto", exact=True).select_option(str(self.room.pk))
        p.get_by_label("Hóspede do quarto", exact=True).fill(self.guest.nome)
        p.get_by_role("option", name=self.guest.nome, exact=True).click()
        self.enviar("Adicionar quarto")
        reserva = Reserva.objects.get(grupo=grupo)
        self.assertEqual(reserva.uh_id, self.room.pk)
        self.enviar("Confirmar grupo")
        with override_settings(FNRH_BLOQUEAR_CHECKIN=False):
            self.enviar("Check-in do grupo")
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.HOSPEDADA)
        receber = p.get_by_role("form", name="Receber pagamento do grupo")
        receber.get_by_label("Forma de pagamento").select_option(str(self.cash.pk))
        receber.get_by_label("Valor recebido (R$)").fill("120,00")
        receber.get_by_label("Observação (opcional)").fill("Recebimento fictício QA")
        self.enviar("Registrar recebimento")
        self._foto("grupo-recebimento-390.png", full_page=True)
        expect(p.get_by_text("Recebimento do folio registrado.", exact=True)).to_be_visible()
        pagamento = PagamentoConta.objects.get(conta=grupo.folio)
        self.assertEqual(pagamento.valor, Decimal("120"))
        self.assertEqual(pagamento.movimento_caixa.valor, Decimal("120"))
        self.assertEqual(grupo.folio.saldo(), Decimal("480"))

    def test_grupo_fiscal_e_captacao_cabem_com_campos_utilizaveis(self):
        from apps.fiscal.models import DocumentoFiscal
        from apps.reservas.services import criar_grupo

        grupo = criar_grupo(
            rotulo="Famílias QA", titular=self.guest,
            checkin=self.today + timedelta(days=20),
            checkout=self.today + timedelta(days=22), usuario=self.op,
        )
        fiscal = DocumentoFiscal.objects.create(
            tipo="nfse", natureza="servico", descricao="Documento fictício QA",
            valor="300", gateway="simulado", chave="1234567890" * 4 + "1234", criado_por=self.op,
        )
        p = self.page
        rotas = (("reservas:grupo_detalhe", grupo.pk, "grupo"),
                 ("fiscal:detalhe", fiscal.pk, "fiscal"),
                 ("captacao:publica", self.pagina.slug, "captacao"))
        for rota, chave, nome in rotas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(rota, args=[chave])), wait_until="networkidle")
                    self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                    if nome == "grupo":
                        for campo in p.locator(".grupo-form input:visible, .grupo-form select").all():
                            caixa = campo.bounding_box()
                            self.assertGreaterEqual(caixa["width"], 180)
                            self.assertLessEqual(caixa["x"] + caixa["width"], largura)
                    if nome == "fiscal":
                        chave_fiscal = p.get_by_text(fiscal.chave, exact=True).bounding_box()
                        self.assertLessEqual(chave_fiscal["x"] + chave_fiscal["width"], largura)
                    if nome == "captacao":
                        aceitar = p.locator("input[name=consent]").bounding_box()
                        self.assertLessEqual(aceitar["width"], 24)
                        self.assertGreaterEqual(aceitar["width"], 18)
                        for campo in p.locator(".datas input").all():
                            self.assertGreaterEqual(campo.bounding_box()["width"], 180)
                    self._foto(f"{nome}-final-{largura}.png", full_page=True)

    def test_captacao_publica_corrige_datas_preserva_campos_e_atribui_campanha(self):
        from apps.comercial.models import Campanha, Oportunidade

        campanha = Campanha.objects.create(
            nome="Férias de novembro QA", codigo="novembro-qa", provedor="outro",
            pagina_captacao=self.pagina, criado_por=self.op,
        )
        p = self.page
        p.context.clear_cookies()
        p.set_viewport_size({"width": 320, "height": 844})
        url = self.url(reverse("captacao:publica", args=[self.pagina.slug])) + "?utm_campaign=novembro-qa&utm_source=qa"
        p.goto(url, wait_until="networkidle")
        p.get_by_role("button", name="Recusar", exact=True).click()
        p.get_by_label("Seu nome", exact=True).fill("Contato público fictício QA")
        p.get_by_label("WhatsApp (com DDD)", exact=True).fill("(49) 99999-1234")
        p.get_by_label("E-mail (opcional)", exact=True).fill("publico-qa@example.invalid")
        inicio = self.today + timedelta(days=14)
        p.get_by_label("Entrada", exact=True).fill(inicio.isoformat())
        p.get_by_label("Saída", exact=True).fill((inicio - timedelta(days=1)).isoformat())
        p.get_by_label("Quantas pessoas?", exact=True).select_option("4")
        p.locator("input[name=consent]").check()
        # O antirrobô de produção exige dois segundos de preenchimento real.
        p.wait_for_timeout(2100)
        with p.expect_navigation():
            p.locator(".form button[type=submit]").click()
        expect(p.get_by_text("A saída precisa ser depois da entrada.", exact=True)).to_be_visible()
        expect(p.get_by_label("Seu nome", exact=True)).to_have_value("Contato público fictício QA")
        expect(p.locator("input[name=consent]")).to_be_checked()
        self.assertFalse(Oportunidade.objects.filter(pagina_captacao=self.pagina).exists())
        self._foto("captacao-erro-320.png", full_page=True)
        p.get_by_label("Saída", exact=True).fill((inicio + timedelta(days=2)).isoformat())
        p.wait_for_timeout(2100)
        with p.expect_navigation():
            p.locator(".form button[type=submit]").click()
        expect(p.get_by_role("heading", name="Recebemos o seu contato! 🥂")).to_be_visible()
        lead = Oportunidade.objects.get(pagina_captacao=self.pagina)
        self.assertEqual(lead.campanha_id, campanha.pk)
        self.assertEqual(lead.hospedes, 4)
        self.assertEqual(lead.checkin_previsto, inicio)
        self.assertEqual(lead.checkout_previsto, inicio + timedelta(days=2))
        self.assertTrue(lead.pessoa.aceita_email)
        self.assertTrue(lead.pessoa.aceita_whatsapp)

    def enviar(self, nome):
        with self.page.expect_navigation():
            self.page.get_by_role("button", name=nome, exact=True).click()

    def test_estoque_recusa_excesso_preserva_campos_e_transfere(self):
        p = self.page
        self.abrir("estoque:transferencia")
        p.locator("#id_produto").fill("QA Água")
        p.get_by_role("option", name="QA Água", exact=False).click()
        p.get_by_role("radiogroup", name="2. Sai de").locator("label").filter(
            has_text="QA Loja"
        ).click()
        p.get_by_role("radiogroup", name="3. Vai para").locator("label").filter(
            has_text="QA Restaurante"
        ).click()
        p.locator("#id_quantidade").fill("25")
        self.enviar("Transferir")
        expect(p.locator(".mensagem.error").filter(has_text="Saldo insuficiente")).to_be_visible()
        self._foto("estoque-recusa-390.png", full_page=True)
        expect(p.locator("#id_quantidade")).to_have_value("25")
        expect(p.locator("input[name=produto]")).to_have_value(str(self.product.pk))
        expect(p.locator(f'input[name=origem][value="{self.shop.pk}"]')).to_be_checked()
        expect(p.locator(f'input[name=destino][value="{self.kitchen.pk}"]')).to_be_checked()
        self.assertEqual(saldo(self.product, self.shop), Decimal("20"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("18"))
        p.locator("#id_quantidade").fill("3")
        self.enviar("Transferir")
        self.assertEqual(saldo(self.product, self.shop), Decimal("17"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("21"))

    def test_loja_cobra_uma_vez_e_baixa_estoque(self):
        from apps.loja.models import Venda

        p = self.page
        self.abrir("loja:pdv")
        produto = p.locator(".pdv-produto").filter(has_text="QA Água")
        produto.click()
        produto.click()
        p.get_by_role("button", name="Carrinho (2) R$ 14,00", exact=True).click()
        p.locator(".pdv-finalizar").click()
        expect(p.get_by_text("Escolha a forma de pagamento.", exact=True)).to_be_visible()
        self.assertEqual(Venda.objects.count(), 0)
        p.locator("select[x-model=forma_id]").select_option(str(self.cash.pk))
        with p.expect_navigation():
            p.locator(".pdv-finalizar").click(click_count=2)
        venda = Venda.objects.get()
        self.assertEqual(venda.total, Decimal("14"))
        self.assertEqual(venda.movimento_caixa.valor, Decimal("14"))
        self.assertEqual(saldo(self.product, self.shop), Decimal("18"))
        total = p.get_by_text("Total da venda: R$ 14,00", exact=True)
        expect(total).to_be_visible()
        medidas = total.bounding_box()
        self.assertLessEqual(medidas["x"] + medidas["width"], 390)
        self._foto("loja-venda-390.png", full_page=True)

    def test_ajuste_zero_mostra_o_saldo_e_registra_a_diferenca(self):
        from apps.nucleo.models import MovimentoEstoque

        p = self.page
        self.abrir("estoque:ajuste")
        p.locator("#id_produto").fill("QA Água")
        p.get_by_role("option", name="QA Água", exact=False).click()
        p.locator("label.est-local-opt").filter(has_text="QA Loja").click()
        p.locator("#id_quantidade").fill("0")
        p.locator("#id_motivo").fill("Contagem fictícia: prateleira vazia.")
        expect(p.locator(".est-previa-destaque dd")).to_have_text("0 un")
        self.enviar("Registrar ajuste")
        self.assertEqual(saldo(self.product, self.shop), Decimal("0"))
        movimento = MovimentoEstoque.objects.filter(produto=self.product, local=self.shop).latest(
            "pk"
        )
        self.assertEqual(movimento.tipo, MovimentoEstoque.Tipo.AJUSTE)
        self.assertEqual(movimento.quantidade, Decimal("-20"))

    def test_restaurante_fecha_comanda_com_saldo_e_caixa_corretos(self):
        p = self.page
        self.abrir("restaurante:comanda", self.comanda.pk)
        p.locator(".pdv-produto").filter(has_text="QA Água").click()
        p.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(p.get_by_role("dialog")).to_be_hidden()
        expect(p.locator("#comanda-itens .comanda-total-linha")).to_contain_text("21,00")
        p.locator("select[name=forma]").select_option(str(self.cash.pk))
        self.enviar("Fechar comanda")
        self.comanda.refresh_from_db()
        self.assertEqual(self.comanda.status, "fechada")
        self.assertEqual(self.comanda.total(), Decimal("21"))
        self.assertEqual(self.comanda.movimento_caixa.valor, Decimal("21"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("17"))
        expect(p.get_by_role("button", name="Fechar comanda")).to_have_count(0)
        self._foto("restaurante-fechada-390.png", full_page=True)

    def test_pedido_com_ponto_adicional_e_observacao_chega_a_cozinha_e_extrato(self):
        from apps.restaurante.models import GrupoOpcaoCardapio, OpcaoCardapio

        self.product.nome = "Bife acebolado QA"
        self.product.save()
        ponto = GrupoOpcaoCardapio.objects.create(produto=self.product, nome="Ponto da carne", minimo=1)
        OpcaoCardapio.objects.create(grupo=ponto, nome="Ao ponto")
        OpcaoCardapio.objects.create(grupo=ponto, nome="Bem passada")
        extras = GrupoOpcaoCardapio.objects.create(produto=self.product, nome="Adicionais", maximo=2)
        OpcaoCardapio.objects.create(grupo=extras, nome="Batata extra", adicional=Decimal("5"))
        p = self.page
        self.abrir("restaurante:comanda", self.comanda.pk)
        p.locator(".pdv-produto").filter(has_text="Bife acebolado QA").click()
        dialogo = p.get_by_role("dialog")
        dialogo.get_by_label("Quantidade", exact=False).fill("2")
        dialogo.get_by_label("Ao ponto", exact=True).check()
        dialogo.get_by_label("Batata extra", exact=False).check()
        dialogo.get_by_label("Observações para a cozinha", exact=False).fill("Sem cebola; molho à parte")
        self._foto("pedido-preparo-390.png")
        dialogo.get_by_role("button", name="Adicionar à comanda", exact=True).click()
        expect(dialogo).to_be_hidden()
        expect(p.locator("#comanda-itens")).to_contain_text("Sem cebola; molho à parte")
        expect(p.locator(".comanda-total-linha")).to_contain_text("38,00")
        p.get_by_role("button", name="Editar Bife acebolado QA", exact=True).click()
        expect(dialogo.get_by_label("Ao ponto", exact=True)).to_be_checked()
        expect(dialogo.get_by_label("Batata extra", exact=False)).to_be_checked()
        dialogo.get_by_label("Quantidade", exact=False).fill("1")
        dialogo.get_by_label("Bem passada", exact=True).check()
        dialogo.get_by_role("button", name="Salvar pedido", exact=True).click()
        expect(dialogo).to_be_hidden()
        expect(p.locator(".comanda-total-linha")).to_contain_text("26,00")
        p.get_by_role("button", name="Conta do quarto", exact=True).click()
        p.locator(".comanda-fechar select[name=conta_id]").select_option(str(self.conta.pk))
        self.enviar("Fechar comanda")
        lancamento = self.conta.lancamentos.get(descricao="Restaurante: Bife acebolado QA")
        self.assertEqual(lancamento.quantidade, 1)
        self.assertEqual(lancamento.preco_unitario, 12)
        self.assertIn("Bem passada", lancamento.observacoes)
        self.assertIn("Sem cebola", lancamento.observacoes)
        self.abrir("restaurante:cozinha")
        pedido = p.locator(".cozinha-pedido").filter(has_text="Bife acebolado QA")
        expect(pedido).to_contain_text("Bem passada")
        expect(pedido).to_contain_text("Sem cebola; molho à parte")
        self._foto("cozinha-pedido-390.png", full_page=True)
        for acao in ("Iniciar preparo", "Marcar pronto", "Confirmar entrega"):
            pedido.get_by_role("button", name=acao, exact=True).click()
            p.wait_for_load_state("domcontentloaded")
        expect(pedido).to_have_count(0)
        self.abrir("reservas:extrato", self.hospedagem.pk)
        expect(p.locator(".extrato")).to_contain_text("Sem cebola; molho à parte")
        expect(p.locator(".extrato")).to_contain_text("Bem passada")
        self._foto("extrato-item-personalizado-390.png", full_page=True)

    def test_extrato_confere_conta_imprime_a4_e_continua_disponivel_apos_checkout(self):
        from apps.lavanderia.services import cancelar_ordem
        from apps.reservas import services

        cancelar_ordem(self.ordem, self.op, "Cancelamento de fixture para conferência final")
        for numero in range(1, 46):
            services.lancar_na_conta(self.conta, "consumo", "consumo", f"Consumo de conferência {numero:02}",
                                    Decimal("12.50"), self.op, quantidade=1, preco_unitario=Decimal("12.50"))
        services.receber_pagamento(self.conta, self.op, self.cash, Decimal("100"), observacao="Pagamento parcial QA")
        p = self.page
        self.abrir("reservas:detalhe", self.hospedagem.pk)
        with p.expect_popup() as aberta:
            p.get_by_role("link", name="Conferir e imprimir conta", exact=True).click()
        extrato = aberta.value
        extrato.wait_for_load_state("networkidle")
        expect(extrato.get_by_role("heading", name="Conferência da hospedagem", exact=True)).to_be_visible()
        expect(extrato.locator(".extrato-saldo dd")).to_have_text("R$ 1.062,50")
        for largura in (320, 390, 1440, 2560, 3440):
            extrato.set_viewport_size({"width": largura, "height": 900})
            self.assertLessEqual(extrato.evaluate("document.documentElement.scrollWidth"), largura + 1)
        extrato.emulate_media(media="print")
        expect(extrato.locator(".extrato-acoes")).to_be_hidden()
        self.assertEqual(extrato.locator("thead").first.evaluate("el => getComputedStyle(el).display"), "table-header-group")
        pasta = os.environ.get("E2E_EVIDENCIAS")
        if pasta:
            extrato.pdf(path=str(Path(pasta) / "conferencia-hospedagem-a4.pdf"), prefer_css_page_size=True, print_background=True)
        services.receber_pagamento(self.conta, self.op, self.cash, self.conta.saldo(), observacao="Quitação no check-out")
        self.hospedagem.fazer_checkout(self.op)
        extrato.reload()
        expect(extrato.get_by_role("heading", name="Extrato de encerramento", exact=True)).to_be_visible()
        expect(extrato.locator(".extrato-saldo dd")).to_have_text("R$ 0,00")
        expect(extrato.locator(".extrato")).to_contain_text("Quitação no check-out")
        if pasta:
            extrato.pdf(path=str(Path(pasta) / "encerramento-hospedagem-a4.pdf"), prefer_css_page_size=True, print_background=True)
        extrato.close()

    def test_portal_retem_observacoes_no_erro_e_envia_escolhas_para_cozinha(self):
        from apps.restaurante.models import Comanda, GrupoOpcaoCardapio, OpcaoCardapio

        grupo = GrupoOpcaoCardapio.objects.create(produto=self.product, nome="Temperatura", minimo=1)
        OpcaoCardapio.objects.create(grupo=grupo, nome="Gelada")
        self.abrir("portal:home", self.acesso.token)
        p = self.page
        p.get_by_label("Quantidade de QA Água", exact=True).fill("2")
        p.get_by_text("Preparo e observações · QA Água", exact=True).click()
        p.get_by_label("Observações para a cozinha", exact=True).fill("Sem gelo, por favor")
        self.enviar("Enviar pedido ao quarto")
        expect(p.get_by_label("Quantidade de QA Água", exact=True)).to_have_value("2")
        expect(p.get_by_label("Observações para a cozinha", exact=True)).to_have_value("Sem gelo, por favor")
        p.get_by_label("Gelada", exact=True).check()
        self._foto("portal-pedido-personalizado-390.png", full_page=True)
        self.enviar("Enviar pedido ao quarto")
        pedido = Comanda.objects.filter(conta=self.conta).latest("pk")
        self.assertEqual(pedido.itens.get().observacoes, "Sem gelo, por favor")
        self.assertEqual(pedido.itens.get().resumo_opcoes, "Temperatura: Gelada")
        self.assertEqual(pedido.itens.get().quantidade, 2)

    def test_lavanderia_avanca_e_cobra_as_pecas(self):
        p = self.page
        self.abrir("lavanderia:ordem", self.ordem.pk)
        p.locator(".pdv-produto").filter(has_text="Lavagem de camisa QA").click()
        expect(p.locator("#ordem-itens .comanda-total-linha")).to_contain_text("24,00")
        self.enviar("Enviar para lavagem")
        self.enviar("Marcar como pronta")
        p.locator("select[name=forma]").select_option(str(self.cash.pk))
        self.enviar("Entregar e cobrar")
        self.ordem.refresh_from_db()
        self.assertEqual(self.ordem.status, "entregue")
        self.assertEqual(self.ordem.total(), Decimal("24"))
        self.assertEqual(self.ordem.movimento_caixa.valor, Decimal("24"))
        self._foto("lavanderia-entregue-390.png", full_page=True)

    def test_manutencao_registra_resolucao_e_custo(self):
        p = self.page
        self.abrir("manutencao:detalhe", self.chamado.pk)
        self.enviar("Iniciar (em andamento)")
        p.locator("input[name=custo_maodeobra]").fill("25.50")
        p.locator("input[name=custo_pecas]").fill("10")
        p.locator("textarea[name=resolucao]").fill("Lâmpada substituída e funcionamento conferido.")
        self.enviar("Concluir")
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, "concluida")
        self.assertEqual(self.chamado.custo_total, Decimal("35.50"))
        self.assertIn("funcionamento conferido", self.chamado.resolucao)
        self._foto("manutencao-concluida-390.png", full_page=True)

    def test_portal_envia_pedido_limpeza_e_manutencao(self):
        from apps.governanca.models import TarefaGovernanca
        from apps.manutencao.models import OrdemServico
        from apps.portal.models import SolicitacaoPortal
        from apps.restaurante.models import Comanda

        p = self.page
        p.context.clear_cookies()
        self.abrir("portal:home", self.acesso.token)
        self.enviar("Enviar pedido ao quarto")
        expect(p.get_by_text("Escolha ao menos um item.", exact=True)).to_be_visible()
        self.assertEqual(SolicitacaoPortal.objects.count(), 0)
        p.locator(f"input[name=qtd_{self.product.pk}]").fill("2")
        self.enviar("Enviar pedido ao quarto")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="restaurante").count(), 1)
        pedido = Comanda.objects.exclude(pk=self.comanda.pk).get()
        self.assertEqual(pedido.total(), Decimal("14"))
        self.assertEqual(saldo(self.product, self.kitchen), Decimal("16"))
        self.enviar("Pedir limpeza extra")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="limpeza").count(), 1)
        self.assertTrue(
            TarefaGovernanca.objects.filter(uh_id=self.hospedagem.uh_id, origem="portal").exists()
        )
        p.locator("#pt-descricao").fill("Ar-condicionado sem resfriar no quarto QA.")
        self.enviar("Chamar a manutenção")
        self.assertEqual(SolicitacaoPortal.objects.filter(tipo="manutencao").count(), 1)
        self.assertTrue(
            OrdemServico.objects.filter(
                uh_id=self.hospedagem.uh_id, descricao__contains="sem resfriar"
            ).exists()
        )
        self._foto("portal-pedidos-390.png", full_page=True)

    def test_pagamento_publico_aceita_formulario_local_e_barra_origem_externa(self):
        p = self.page
        p.context.clear_cookies()
        self.abrir("pagamentos:pagar", self.cobranca.token)
        token = p.locator("input[name=csrfmiddlewaretoken]").input_value()
        resposta = p.request.post(
            self.url(reverse("pagamentos:pagar_simular", args=[self.cobranca.token])),
            form={"csrfmiddlewaretoken": token},
            headers={"Origin": "https://origem-invalida.example"},
        )
        self.assertEqual(resposta.status, 403)
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, "pendente")
        self.enviar("Já paguei")
        expect(p.locator(".pay-ok")).to_contain_text("Pagamento confirmado")
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, "pago")
        self._foto("pagamento-simulado-390.png", full_page=True)

    def test_comparacao_de_quartos_fecha_com_escape(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(reverse("comercial:oportunidade", args=[self.lead.pk])))
                p.locator(".pq-cmp-check input").nth(0).check()
                p.locator(".pq-cmp-check input").nth(1).check()
                p.get_by_role("button", name="Comparar ⇄", exact=True).click()
                p.locator("#modal-conteudo .comparacao-quartos").wait_for()
                self._conferir_modal(largura)
                for caixa in p.locator(".pq-cmp-bar button").all():
                    medidas = caixa.bounding_box()
                    self.assertGreaterEqual(medidas["x"], 0)
                    self.assertLessEqual(medidas["x"] + medidas["width"], largura)
                p.get_by_role("dialog").get_by_role("button", name="Fechar", exact=True).last.click(
                    trial=True
                )
                self._foto(f"comparador-aberto-{largura}.png")
                p.keyboard.press("Escape")
                expect(p.locator("#modal-conteudo .comparacao-quartos")).to_be_hidden(timeout=2000)
                expect(p.get_by_role("button", name="Comparar ⇄", exact=True)).to_be_focused()
                self.assertFalse(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def test_confirmacao_email_mantem_foco_dentro_e_devolve_ao_fechar(self):
        p = self.page
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                p.goto(self.url(reverse("comercial:enviar_email_lead", args=[self.lead.pk])))
                p.locator("#id_destinatario").fill("guest@example.invalid")
                p.get_by_role("button", name="Enviar ao lead", exact=True).click()
                expect(p.get_by_role("dialog")).to_be_visible()
                self._conferir_modal(largura)
                p.get_by_role("dialog").get_by_role(
                    "button", name="Enviar agora", exact=True
                ).click(trial=True)
                self._foto(f"confirmacao-email-{largura}.png")
                for _ in range(8):
                    p.keyboard.press("Tab")
                    self.assertTrue(
                        p.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                    )
                p.keyboard.press("Escape")
                expect(p.get_by_role("dialog")).to_be_hidden()
                expect(p.get_by_role("button", name="Enviar ao lead", exact=True)).to_be_focused()
                self.assertFalse(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def _conferir_modal(self, largura):
        p = self.page
        p.wait_for_function(
            "getComputedStyle(document.querySelector('.modal-caixa')).transform === 'none' && getComputedStyle(document.querySelector('.modal-caixa')).opacity === '1'"
        )
        caixa = p.get_by_role("dialog").bounding_box()
        self.assertGreaterEqual(caixa["x"], 0)
        self.assertGreaterEqual(caixa["y"], 0)
        self.assertLessEqual(caixa["x"] + caixa["width"], largura + 1)
        self.assertLessEqual(caixa["y"] + caixa["height"], 845)
        self.assertTrue(p.evaluate("document.body.classList.contains('sem-rolagem')"))

    def test_listas_vazias_mostram_a_mensagem_sem_arrastar(self):
        from apps.comercial.models import CampanhaEmail

        CampanhaEmail.objects.all().delete()
        p = self.page
        nomes = [
            "loja:vendas",
            "comercial:tarefas",
            "contas",
            "conciliacao:manual",
            "lavanderia:historico",
            "lavanderia:rouparia",
            "reservas:grupos",
            "reservas:restricoes",
            "temporadas",
            "comercial:email_campanhas",
        ]
        for nome in nomes:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    p.set_viewport_size({"width": largura, "height": 844})
                    p.goto(self.url(reverse(nome)))
                    vazios = p.locator("td.vazio[colspan],td.vazio-el[colspan]")
                    self.assertGreater(vazios.count(), 0, nome)
                    for i in range(vazios.count()):
                        medidas = vazios.nth(i).evaluate("""el => {
                            const r=el.getBoundingClientRect();
                            const texto=document.createRange();texto.selectNodeContents(el);
                            const t=texto.getBoundingClientRect();
                            return {left:r.left,right:r.right,textLeft:t.left,textRight:t.right};
                        }""")
                        self.assertGreaterEqual(medidas["left"], 0, medidas)
                        self.assertLessEqual(medidas["right"], largura + 1, medidas)
                        self.assertGreaterEqual(medidas["textLeft"], 0, medidas)
                        self.assertLessEqual(medidas["textRight"], largura + 1, medidas)
                    if largura == 320:
                        self._foto(f"vazio-{nome.replace(':', '-')}-320.png")

    def test_campos_de_busca_e_dias_da_semana_cabem_no_celular(self):
        p = self.page
        p.set_viewport_size({"width": 320, "height": 844})
        p.goto(self.url(reverse("loja:pdv")))
        self.assertGreaterEqual(p.locator(".pdv-busca").bounding_box()["width"], 220)
        self._foto("pdv-campos-320.png")
        p.goto(self.url(reverse("reservas:lista")))
        self.assertGreaterEqual(p.get_by_role("searchbox").bounding_box()["width"], 220)
        self._foto("reservas-busca-320.png")
        p.goto(self.url(reverse("temporada_nova")))
        label = p.get_by_label("Segunda", exact=True).locator("..")
        self.assertGreaterEqual(label.bounding_box()["height"], 44)
        self.assertLessEqual(label.bounding_box()["height"], 50)
        label.click()
        expect(p.get_by_label("Segunda", exact=True)).to_be_checked()
        self._foto("temporada-dias-320.png")
        p.goto(self.url(reverse("marketing:calendario")))
        caixa = p.locator(".mk-cal-vazio").bounding_box()
        self.assertLessEqual(caixa["x"] + caixa["width"], 320)
        self._foto("calendario-vazio-320.png")

    def test_email_captacao_e_paginas_publicas_cabem_nas_quatro_larguras(self):
        p = self.page
        erros = []
        p.on("pageerror", lambda erro: erros.append(str(erro)))
        paginas = [
            ("comercial:pagina_detalhe", [self.pagina.pk]),
            ("comercial:enviar_email_lead", [self.lead.pk]),
            ("portal:home", [self.acesso.token]),
            ("portal:nps", [self.acesso.token]),
            ("pagamentos:pagar", [self.cobranca.token]),
            ("nps:painel", []),
            ("fiscal:painel", []),
        ]
        for nome, argumentos in paginas:
            for largura in (320, 390, 821, 1440):
                with self.subTest(tela=nome, largura=largura):
                    erros.clear()
                    p.set_viewport_size({"width": largura, "height": 844})
                    resposta = p.goto(
                        self.url(reverse(nome, args=argumentos)), wait_until="networkidle"
                    )
                    self.assertEqual(resposta.status, 200)
                    self.assertLessEqual(
                        p.evaluate("document.documentElement.scrollWidth"), largura + 1
                    )
                    self.assertFalse(erros, erros)
                    if largura in (320, 1440):
                        self._foto(f"operacao-{nome.replace(':', '-')}-{largura}.png")

    def test_email_invalido_nao_envia_e_confirmacao_envia_uma_vez(self):
        from django.core import mail

        from apps.comercial.models import EnvioEmail

        p = self.page
        self.abrir("comercial:enviar_email_lead", self.lead.pk)
        p.locator("#id_destinatario").fill("email-invalido")
        p.get_by_role("button", name="Enviar ao lead", exact=True).click()
        expect(p.get_by_role("dialog")).to_be_hidden()
        expect(p.locator("#id_destinatario")).to_be_focused()
        self.assertEqual(EnvioEmail.objects.count(), 0)
        p.locator("#id_destinatario").fill("guest@example.invalid")
        p.locator("#id_assunto").fill("Proposta fictícia QA")
        p.get_by_role("button", name="Enviar ao lead", exact=True).click()
        with p.expect_navigation():
            p.get_by_role("button", name="Enviar agora", exact=True).click(click_count=2)
        expect(p).to_have_url(self.url(reverse("comercial:oportunidade", args=[self.lead.pk])))
        envio = EnvioEmail.objects.get(oportunidade=self.lead)
        self.assertEqual(envio.status, "enviado")
        self.assertEqual(envio.email, "guest@example.invalid")
        self.assertEqual(envio.assunto, "Proposta fictícia QA")
        self.assertEqual(len(mail.outbox), 1)


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class PdvVisualE2ETests(_FunilComercialMixin, _BaseE2E):
    """Catálogo e carrinho reais, incluindo arraste, toque e reenvio da venda."""

    def setUp(self):
        super().setUp()
        from apps.nucleo.models import (
            CategoriaProduto,
            FormaPagamento,
            LocalEstoque,
            ModuloContratado,
            Produto,
            SessaoCaixa,
            Usuario,
            registrar_entrada,
        )
        cache.clear()
        self.op = Usuario.objects.create_superuser(username="pdv-ui", password="forte-123-abc")
        for codigo in ("estoque", "loja"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.local = LocalEstoque.objects.create(nome="Balcão QA", modulo="loja")
        self.forma = FormaPagamento.objects.create(nome="Dinheiro QA", tipo="dinheiro")
        SessaoCaixa.objects.create(operador=self.op, modulo="loja", fundo_troco=0)
        bebidas = CategoriaProduto.objects.create(nome="Bebidas")
        lanches = CategoriaProduto.objects.create(nome="Lanches")
        self.agua = Produto.objects.create(nome="Água mineral com gás", categoria=bebidas, preco_venda="5.50")
        self.lanche = Produto.objects.create(
            nome="Hambúrguer artesanal com cebola caramelizada e queijo colonial",
            categoria=lanches, preco_venda="34.90",
        )
        Produto.objects.create(nome="Suco esgotado", categoria=bebidas, preco_venda="9.00")
        registrar_entrada(self.agua, self.local, 2, Decimal("1"), self.op)
        registrar_entrada(self.lanche, self.local, 12, Decimal("8"), self.op)
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self._login("pdv-ui", "forte-123-abc")

    def abrir(self, largura=390):
        self.page.set_viewport_size({"width": largura, "height": 844})
        self.page.goto(self.url(reverse("loja:pdv")))
        expect(self.page.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)).to_be_visible()

    def carrinho(self):
        self.page.locator(".pdv-etapas button").filter(has_text="Carrinho").click()

    def icone_url(self, icone):
        return f"{static('vendor/lucide/catalogo.svg')}#{icone}"

    def conferir_catalogo_ilustrado(self, nome):
        p = self.page
        p.wait_for_function("""() => [...document.querySelectorAll('.pdv-produto .produto-ilustracao use')]
            .every(el => el.getBBox().width > 0 && el.getBBox().height > 0)""")
        for largura in (320, 390, 414, 768, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            p.evaluate("document.fonts.ready")
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            self.assertFalse(p.evaluate("""() => [...document.querySelectorAll('.pdv-produto')].filter(el => {
                if (!el.getClientRects().length) return false;
                const box=el.getBoundingClientRect();
                return [...el.querySelectorAll('.produto-ilustracao,.pdv-produto-nome,.pdv-produto-meta')].some(filho => {
                    const r=filho.getBoundingClientRect();return r.left<box.left-1||r.right>box.right+1;
                });
            }).map(el => el.textContent)"""))
            if largura in (320, 390, 821, 1440):
                OperacaoUsabilidadeE2ETests._foto(self, f"fase10-{nome}-{largura}.png", full_page=True)

    def test_catalogo_ilustrado_preserva_nome_preco_busca_e_carrinho(self):
        from apps.nucleo.models import Produto, registrar_entrada
        p = self.page
        exemplos = {"Coca-Cola lata 350 ml": "cup-soda", "Pepsi zero": "cup-soda",
                    "Café c/ leite": "coffee", "Chocolate ao leite": "candy", "Bolo de café": "cake"}
        for nome in exemplos:
            produto = Produto.objects.create(nome=nome, categoria=self.agua.categoria, preco_venda="8.50")
            registrar_entrada(produto, self.local, 3, Decimal("2"), self.op)
        respostas = []
        p.on("response", lambda r: respostas.append(r.status) if "/vendor/lucide/catalogo" in r.url else None)
        self.abrir(1440)
        for nome, icone in exemplos.items():
            botao = p.get_by_role("button", name=f"Adicionar {nome} ao carrinho", exact=True)
            expect(botao.locator("use")).to_have_attribute("href", self.icone_url(icone))
            expect(botao.locator(".pdv-preco")).to_have_text("R$ 8,50")
        self.conferir_catalogo_ilustrado("loja")
        self.assertTrue(respostas)
        self.assertTrue(all(status == 200 for status in respostas))
        p.get_by_label("Buscar produto", exact=True).fill("cafe leite")
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_role("button", name="Adicionar Café c/ leite ao carrinho", exact=True).click()
        expect(p.locator(".pdv-item-nome")).to_have_text("Café c/ leite")
        expect(p.locator(".pdv-total strong")).to_have_text("R$ 8,50")

    def test_previa_automatica_e_escolha_manual_sobrevivem_a_erro_no_cadastro(self):
        p = self.page
        p.set_viewport_size({"width": 390, "height": 900})
        p.goto(self.url(reverse("estoque:produto_editar", args=[self.agua.pk])))
        nome = p.locator("#id_nome")
        escolha = p.locator("#id_icone_catalogo")
        for texto, icone in (("Café c/ leite", "coffee"), ("Bolo de café", "cake"),
                             ("Chocolate ao leite", "candy"), ("Água s/ gás", "glass-water")):
            nome.fill(texto)
            expect(p.locator("[data-catalogo-previa] use")).to_have_attribute("href", self.icone_url(icone))
        nome.fill(self.agua.nome)
        escolha.select_option("glass-water")
        p.locator("#id_preco_venda").fill("-1")
        salvar = p.get_by_role("button", name="Salvar produto", exact=True)
        salvar.evaluate("el => el.setAttribute('formnovalidate', '')")
        salvar.click()
        expect(p.locator(".mensagem.error")).to_be_visible()
        expect(escolha).to_have_value("glass-water")
        expect(nome).to_have_value(self.agua.nome)
        expect(p.locator(".est-previa")).to_contain_text("R$ 5,50")
        self.agua.refresh_from_db()
        self.assertEqual(self.agua.icone_catalogo, "")
        p.wait_for_function("document.querySelector('[data-catalogo-previa] use').getBBox().width > 0")
        for largura in (320, 390, 821, 1440):
            p.set_viewport_size({"width": largura, "height": 900})
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
            OperacaoUsabilidadeE2ETests._foto(self, f"fase10-cadastro-erro-{largura}.png", full_page=True)
        p.locator("#id_preco_venda").fill("5.50")
        salvar.click()
        expect(p).to_have_url(self.url(reverse("estoque:produtos")))
        self.agua.refresh_from_db()
        self.assertEqual(self.agua.icone_catalogo, "glass-water")
        self.abrir()
        expect(p.get_by_role("button", name=f"Adicionar {self.agua.nome} ao carrinho", exact=True).locator("use")).to_have_attribute("href", self.icone_url("glass-water"))

    def test_restaurante_compartilha_ilustracao_e_abre_pedido_correto(self):
        from apps.nucleo.models import LocalEstoque, ModuloContratado, registrar_entrada
        from apps.restaurante.services import abrir_comanda
        ModuloContratado.objects.update_or_create(codigo="restaurante", defaults={"ativo": True})
        local = LocalEstoque.objects.create(nome="Restaurante QA", modulo="restaurante")
        registrar_entrada(self.agua, local, 2, Decimal("1"), self.op)
        comanda = abrir_comanda(self.op, local, rotulo="Ícones no cardápio QA")
        p = self.page
        p.goto(self.url(reverse("restaurante:comanda", args=[comanda.pk])))
        self.conferir_catalogo_ilustrado("restaurante")
        agua = p.get_by_role("button").filter(has_text=self.agua.nome)
        expect(agua.locator("use")).to_have_attribute("href", self.icone_url("bubbles"))
        agua.click()
        expect(p.locator("#modal-conteudo")).to_contain_text(self.agua.nome)
        self.assertEqual(saldo(self.agua, local), Decimal("2"))

    def test_categoria_busca_sem_acento_e_limite_do_estoque(self):
        p = self.page
        self.abrir()
        p.get_by_role("button", name="Lanches 1", exact=True).click()
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_label("Buscar produto", exact=True).fill("hamburguer queijo")
        expect(p.locator(".pdv-produto")).to_have_count(1)
        p.get_by_role("button", name="Limpar filtros", exact=True).click()
        expect(p.locator(".pdv-produto")).to_have_count(3)
        p.get_by_label("Buscar produto", exact=True).fill("agua gas")
        agua = p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)
        agua.click()
        agua.click()
        expect(agua).to_be_disabled()
        expect(p.get_by_label("Local de estoque", exact=True)).to_be_disabled()
        self.carrinho()
        expect(p.get_by_role("button", name="Aumentar Água mineral com gás", exact=True)).to_be_disabled()
        p.get_by_role("button", name="Diminuir Água mineral com gás", exact=True).click()
        p.get_by_role("button", name="Produtos", exact=True).click()
        expect(agua).to_be_enabled()
        self.assertEqual(saldo(self.agua, self.local), Decimal("2"))

    def test_carrinho_cabe_no_celular_e_menu_aberto_sem_perder_itens(self):
        p = self.page
        self.abrir(1440)
        p.get_by_role("button", name=f"Adicionar {self.lanche.nome} ao carrinho", exact=True).click()
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 844})
                if p.locator(".pdv-etapas").is_visible():
                    self.carrinho()
                expect(p.locator(".pdv-item-nome")).to_have_text(self.lanche.nome)
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                medidas = p.locator(".pdv-item").evaluate("""el => ({
                    largura: el.clientWidth, conteudo: el.scrollWidth,
                    botoes: [...el.querySelectorAll('button')].map(b => ({w:b.offsetWidth,h:b.offsetHeight})),
                    nome: getComputedStyle(el.querySelector('.pdv-item-nome')).whiteSpace
                })""")
                self.assertLessEqual(medidas["conteudo"], medidas["largura"] + 1)
                self.assertEqual(medidas["nome"], "normal")
                self.assertTrue(all(b["w"] >= 44 and b["h"] >= 44 for b in medidas["botoes"]))
                if os.environ.get("E2E_EVIDENCIAS"):
                    p.screenshot(path=str(Path(os.environ["E2E_EVIDENCIAS"]) / f"pdv-carrinho-{largura}.png"))
        expect(p.locator(".pdv-etapas")).to_be_hidden()
        expect(p.locator(".pdv-produtos")).to_be_visible()
        expect(p.locator(".pdv-painel")).to_be_visible()
        self.assertEqual(p.locator(".pdv-item").count(), 1)

    def test_arraste_real_adiciona_so_o_produto_conhecido_e_nao_cobra(self):
        from apps.loja.models import Venda
        p = self.page
        self.abrir(1440)
        origem = p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True)
        origem.drag_to(p.locator(".pdv-painel"))
        expect(p.locator(".pdv-item-nome")).to_have_text(self.agua.nome)
        expect(p.locator(".pdv-qtd span")).to_have_text("1")
        p.locator(".pdv-painel").evaluate("""el => {
            const dt = new DataTransfer();
            dt.setData('text/plain', '9999');
            el.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:dt}));
        }""")
        expect(p.locator(".pdv-qtd span")).to_have_text("1")
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(saldo(self.agua, self.local), Decimal("2"))

    def test_falha_de_conexao_mantem_carrinho_e_reenvia_mesma_chave(self):
        from apps.loja.models import Venda
        p = self.page
        self.abrir()
        p.get_by_role("button", name="Adicionar Água mineral com gás ao carrinho", exact=True).click()
        self.carrinho()
        p.get_by_label("Forma de pagamento", exact=True).select_option(str(self.forma.pk))
        requisicoes = []
        url = self.url(reverse("loja:finalizar"))

        def perder_resposta(route):
            requisicoes.append(route.request.post_data_json)
            route.fetch()  # o servidor gravou, mas a resposta se perdeu
            route.abort()

        p.route(url, perder_resposta)
        p.locator(".pdv-finalizar").click()
        expect(p.get_by_text("Falha de conexão. Tente de novo: a venda não sai em dobro.", exact=True)).to_be_visible()
        expect(p.locator(".pdv-item-nome")).to_have_text(self.agua.nome)
        p.unroute(url, perder_resposta)
        p.on("request", lambda req: requisicoes.append(req.post_data_json) if req.url == url else None)
        with p.expect_navigation():
            p.locator(".pdv-finalizar").click()
        self.assertEqual(len(requisicoes), 2)
        self.assertEqual(requisicoes[0]["chave"], requisicoes[1]["chave"])
        self.assertEqual(Venda.objects.count(), 1)
        self.assertEqual(saldo(self.agua, self.local), Decimal("1"))


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado (ver tests_e2e)")
class GaleriaVisualE2ETests(_BaseE2E):
    def setUp(self):
        super().setUp()
        from apps.site.models import FotoGaleria
        cache.clear()
        FotoGaleria.objects.create(imagem="", legenda="Foto indisponível", categoria="pousada", ordem=0)
        for numero in range(1, 12):
            FotoGaleria.objects.create(
                imagem=f"galeria/qa-{numero}.svg", legenda=f"Paisagem de teste {numero}",
                categoria="natureza", ordem=numero,
            )
        self.page.route("**/media/galeria/*", lambda r: r.fulfill(
            content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#2E483E"/></svg>'
        ))

    def test_galeria_na_top_layer_cabe_em_telas_pequenas_e_paisagem(self):
        p = self.page
        for largura, altura in ((320, 568), (390, 844), (821, 844), (844, 390), (1440, 900)):
            with self.subTest(largura=largura, altura=altura):
                p.set_viewport_size({"width": largura, "height": altura})
                p.goto(self.url(reverse("core:home")))
                if p.get_by_role("button", name="Recusar", exact=True).is_visible():
                    p.get_by_role("button", name="Recusar", exact=True).click()
                origem = p.locator('[data-galeria-item][data-src$="qa-11.svg"]')
                origem.click()
                dialog = p.get_by_role("dialog", name="Galeria de fotos", exact=True)
                expect(dialog).to_be_visible()
                expect(dialog.locator("[data-gl-legenda]")).to_have_text("Paisagem de teste 11")
                expect(dialog.locator("[data-gl-contador]")).to_have_text("11 / 11")
                geometria = dialog.evaluate("""el => ({
                    modal:el.matches(':modal'), largura:el.scrollWidth, altura:el.scrollHeight,
                    botoes:[...el.querySelectorAll('button,a')].map(b => {
                        const r=b.getBoundingClientRect();
                        return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height};
                    }), imagem:getComputedStyle(el.querySelector('img')).objectFit
                })""")
                self.assertTrue(geometria["modal"])
                self.assertEqual(geometria["imagem"], "contain")
                self.assertLessEqual(geometria["largura"], largura + 1)
                self.assertLessEqual(geometria["altura"], altura + 1)
                for botao in geometria["botoes"]:
                    self.assertGreaterEqual(botao["x"], 0)
                    self.assertGreaterEqual(botao["y"], 0)
                    self.assertLessEqual(botao["right"], largura)
                    self.assertLessEqual(botao["bottom"], altura)
                    self.assertGreaterEqual(botao["w"], 44)
                    self.assertGreaterEqual(botao["h"], 44)
                dialog.get_by_role("button", name="Próxima foto", exact=True).click()
                expect(dialog.locator("[data-gl-legenda]")).to_have_text("Paisagem de teste 1")
                p.keyboard.press("ArrowLeft")
                expect(dialog.locator("[data-gl-contador]")).to_have_text("11 / 11")
                p.keyboard.press("Escape")
                expect(dialog).to_be_hidden()
                expect(origem).to_be_focused()
                p.wait_for_function("document.body.style.overflow !== 'hidden'")
                self.assertNotEqual(p.evaluate("document.body.style.overflow"), "hidden")
