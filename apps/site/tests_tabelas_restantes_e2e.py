"""Leitura integral das listas restantes, ações reais e relatório amplo impresso."""
import json
import os
import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .auditoria_fixtures import criar_cenario_templates
from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class TabelasRestantesE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        from apps.comercial.models import AtividadeComercial
        from apps.conciliacao.models import (
            ExtratoBancario,
            LancamentoExtrato,
            LoteCartao,
            TransacaoCartao,
        )
        from apps.fiscal.models import DocumentoFiscal
        from apps.portal.models import SolicitacaoPortal
        from apps.reservas.models import (
            ContaHospedagem,
            FichaFNRH,
            GrupoReserva,
            LancamentoConta,
            Reserva,
        )

        self.c = c = criar_cenario_templates()
        c.reserva.checkin = c.hoje
        c.reserva.checkout = c.hoje + timedelta(days=2)
        c.reserva.save(update_fields=["checkin", "checkout"])
        self.grupo = GrupoReserva.objects.create(
            rotulo="Grupo de conferência das tabelas", titular=c.pessoa,
            checkin=c.reserva.checkin, checkout=c.reserva.checkout, criado_por=c.usuario)
        ContaHospedagem.objects.create(grupo=self.grupo)
        c.reserva.grupo = self.grupo
        c.reserva.save(update_fields=["grupo"])
        self.conta = ContaHospedagem.objects.create(reserva=c.reserva)
        self.servico = LancamentoConta.objects.create(
            conta=self.conta, tipo="servico", natureza="servico", valor="1234.56",
            descricao="Serviço de conferência fiscal com descrição completa",
            codigo_servico_fiscal="090101", criado_por=c.usuario)
        self.tarefa = AtividadeComercial.objects.create(
            oportunidade=c.oportunidade, tipo="tarefa", quando=timezone.now(),
            descricao="Conferir os dados completos da hospedagem em família",
            responsavel=c.usuario, criado_por=c.usuario, concluida=False)
        DocumentoFiscal.objects.create(
            tipo="nfse", natureza="servico", descricao="Documento da conferência das tabelas",
            valor="1234567.89", criado_por=c.usuario, numero="202600000012345")
        SolicitacaoPortal.objects.create(
            reserva_id=c.reserva.pk, uh_numero=c.uh.numero, tipo="limpeza",
            detalhe="Limpeza extra para preparar o quarto da família de conferência")
        extrato = ExtratoBancario.objects.create(importado_por=c.usuario)
        self.extrato_pendente = LancamentoExtrato.objects.create(
            extrato=extrato, data=c.hoje, valor="37.80",
            descricao="Pagamento da conferência com descrição integral")
        LancamentoExtrato.objects.create(
            extrato=extrato, data=c.hoje, valor="37.80", status="conciliado",
            movimento_caixa=c.sessao.movimentos.first(), conciliado_em=timezone.now(),
            descricao="Referência conciliada com descrição suficientemente longa para verificar que permanece integral")
        lote = LoteCartao.objects.create(importado_por=c.usuario)
        for status in ("pendente", "conciliado"):
            TransacaoCartao.objects.create(
                lote=lote, data_venda=c.hoje, nsu=f"QA-20261023-{status}", bruto="37.80",
                liquido="35.80", taxa="2.00", status=status,
                conciliado_em=timezone.now() if status == "conciliado" else None)
        hospedada = Reserva.objects.create(
            uh=c.uh2, hospede=c.pessoa, checkin=c.hoje, checkout=c.hoje + timedelta(days=1),
            status="hospedada", valor_diaria="348.90", criado_por=c.usuario)
        for pais, uf in (("Brasil", "SC"), ("Portugal", "")):
            FichaFNRH.objects.create(
                reserva=hospedada, nome=f"Hóspede sintético de {pais}", nascimento=date(1990, 1, 1),
                documento_tipo="PASSAPORTE", documento_numero="QA12345",
                cidade="Cidade da conferência", uf=uf, pais=pais,
                motivo_viagem="LAZER_FERIAS", meio_transporte="AUTOMOVEL", sexo="MULHER")
        self.client.force_login(c.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")
        self.erros = []
        self.page.on("pageerror", lambda erro: self.erros.append(str(erro)))
        self.evidencias = []

    def tearDown(self):
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / f"{self._testMethodName}.json").write_text(
                json.dumps(self.evidencias, ensure_ascii=False, indent=2), encoding="utf-8")
        super().tearDown()

    def _abrir(self, rota, largura, trilho=False, args=(), query=""):
        self.erros.clear()
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse(rota, args=args) + query), wait_until="load")
        self.assertEqual(resposta.status, 200, self.page.url)
        self.page.evaluate("document.fonts.ready")
        if largura > 820:
            recolhida = self.page.locator(".app").evaluate("el => el.classList.contains('recolhida')")
            if recolhida != trilho:
                self.page.locator(".sidebar-toggle").click()
            self.page.wait_for_function("""trilho => {
                const app = document.querySelector('.app'), estilo = getComputedStyle(app);
                const alvo = parseFloat(estilo.getPropertyValue(trilho ? '--trilho-w' : '--sidebar-w-aberta'));
                return app.classList.contains('recolhida') === trilho &&
                    Math.abs(parseFloat(estilo.gridTemplateColumns) - alvo) < .1 &&
                    Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width - alvo) < .1;
            }""", arg=trilho)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        self.assertEqual(self.erros, [], (rota, largura))

    def _conferir(self, rota, largura, trilho=False, seletor="#conteudo .tabela-rol > .tabela-cartoes:not(.tabela-registros)", sempre_tabela=False):
        tabelas = self.page.locator(seletor)
        self.assertGreater(tabelas.count(), 0, rota)
        medidas = tabelas.evaluate_all("""tabelas => tabelas.map(t => {
            const b = t.closest('.tabela-rol').getBoundingClientRect();
            const cells = [...t.querySelectorAll('tbody td[data-rotulo]')];
            return {display:getComputedStyle(t).display, largura:b.width, celulas:cells.map(e => {
                const r=e.getBoundingClientRect(), v=e.querySelector('.tabela-valor');
                const controls=[...e.querySelectorAll('button,input:not([type=hidden]),select,a')]
                    .filter(c=>c.getClientRects().length).map(c=>{
                        const box=c.getBoundingClientRect(); return {l:box.left, r:box.right};
                    });
                return {rotulo:e.dataset.rotulo, texto:v.innerText, l:r.left, r:r.right,
                    limiteL:b.left, limiteR:b.right, scroll:e.scrollWidth-e.clientWidth,
                    valor:v.scrollWidth-v.clientWidth, antes:getComputedStyle(e,'::before').content, controls,
                    moeda: v.classList.contains('rel-valor-monetario'),
                    linhasMoeda: v.classList.contains('rel-valor-monetario') ? (() => {
                        const range = document.createRange(); range.selectNodeContents(v);
                        return [...new Set([...range.getClientRects()].map(r => Math.round(r.top)))].length;
                    })() : 0};
            })};
        })""")
        for tabela in medidas:
            self.assertGreater(len(tabela["celulas"]), 0, (rota, tabela))
            if sempre_tabela:
                self.assertEqual(tabela["display"], "table", (rota, tabela))
            elif tabela["largura"] <= 768:
                self.assertEqual(tabela["display"], "block", (rota, tabela))
            for celula in tabela["celulas"]:
                self.assertTrue(celula["rotulo"], celula)
                self.assertLessEqual(celula["scroll"], 1, (rota, celula))
                self.assertLessEqual(celula["valor"], 1, (rota, celula))
                if celula["moeda"]:
                    self.assertEqual(celula["linhasMoeda"], 1, (rota, celula))
                self.assertGreaterEqual(celula["l"], celula["limiteL"] - 1, (rota, celula))
                self.assertLessEqual(celula["r"], celula["limiteR"] + 1, (rota, celula))
                if tabela["display"] == "block":
                    self.assertNotIn(celula["antes"], ("none", "normal", '""'), celula)
                for controle in celula["controls"]:
                    self.assertGreaterEqual(controle["l"], celula["limiteL"] - 1, (rota, celula))
                    self.assertLessEqual(controle["r"], celula["limiteR"] + 1, (rota, celula))
        nome = re.sub(r"[^a-z0-9_-]+", "-", rota.lower())
        foto = f"{nome}-{largura}-{'trilho' if trilho else 'aberta'}.png"
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            self.page.screenshot(path=str(Path(destino) / foto), full_page=True)
            if rota.startswith("relatorio-"):
                tabelas.locator("tbody tr").first.screenshot(
                    path=str(Path(destino) / foto.replace(".png", "-primeiro-registro.png")))
        self.evidencias.append({"rota": rota, "largura": largura, "trilho": trilho,
                               "imagem": foto, "tabelas": medidas})

    def test_listas_preenchidas_nos_cinco_estados(self):
        rotas = [
            ("comercial:tarefas", (), ""), ("conciliacao:painel", (), ""),
            ("conciliacao:manual", (), ""), ("escala:minha", (), ""),
            ("fiscal:painel", (), ""), ("fiscal:produtos", (), ""),
            ("fiscal:preparar_conta", (self.conta.pk,), ""), ("governanca:quartos", (), ""),
            ("caixa", (), "?modulo=loja"), ("temporadas", (), ""),
            ("pagamentos:painel", (), ""), ("portal:solicitacoes", (), ""),
            ("reservas:grupos", (), ""), ("reservas:grupo_detalhe", (self.grupo.pk,), ""),
            ("reservas:painel_colchoes", (), "?dias=7"), ("reservas:boh", (), ""),
            ("restaurante:mesas", (), ""),
        ]
        for rota, args, query in rotas:
            for largura, trilho in self.ESTADOS:
                with self.subTest(rota=rota, largura=largura, trilho=trilho):
                    self._abrir(rota, largura, trilho, args, query)
                    seletor = ".montagem-camas .tabela-cartoes" if rota == "governanca:quartos" else "#conteudo .tabela-rol > .tabela-cartoes:not(.tabela-registros)"
                    if rota == "pagamentos:painel":
                        # O resumo tem três colunas curtas e cabe como tabela inclusive no celular.
                        seletor = "#conteudo .tabela-rol > .tabela:not(.tabela-cartoes)"
                    self._conferir(rota, largura, trilho, seletor, sempre_tabela=rota == "pagamentos:painel")

    def test_acoes_dos_cartoes_enviam_os_registros_corretos(self):
        self._abrir("comercial:tarefas", 320)
        self.page.get_by_role("button", name="Concluir", exact=True).click()
        expect(self.page.get_by_text("Tarefa concluída.")).to_be_visible()
        self.tarefa.refresh_from_db()
        self.assertTrue(self.tarefa.concluida)
        self._abrir("comercial:tarefas", 320)
        expect(self.page.get_by_text("Nenhuma tarefa pendente.")).to_be_visible()
        self._abrir("conciliacao:manual", 390)
        linha = self.page.locator("tr").filter(has_text=self.extrato_pendente.descricao)
        linha.get_by_role("button", name="Ignorar", exact=True).click()
        expect(self.page.get_by_text("Linha marcada como ignorada.")).to_be_visible()
        self.extrato_pendente.refresh_from_db()
        self.assertEqual(self.extrato_pendente.status, "ignorado")
        self._abrir("fiscal:preparar_conta", 320, args=(self.conta.pk,))
        self.page.locator(f'#codigo-{self.servico.pk}').fill("090102")
        self.page.locator('input[name="conferido"]').check()
        self.page.get_by_role("button", name="Salvar classificação").click()
        expect(self.page.get_by_text("Classificação registrada.", exact=False)).to_be_visible()
        self.servico.refresh_from_db()
        self.assertEqual(self.servico.codigo_servico_fiscal, "090102")

    def test_fechamento_preserva_os_totais_nos_cinco_estados(self):
        for largura, trilho in self.ESTADOS:
            self._abrir("conciliacao:fechamento", largura, trilho)
            resumos = self.page.locator(".resumo-valores")
            expect(resumos).to_have_count(2)
            expect(resumos.locator("dt")).to_have_count(14)
            expect(resumos.locator("dd")).to_have_count(14)
            medidas = resumos.locator("dd").evaluate_all("els => els.map(e => e.scrollWidth-e.clientWidth)")
            self.assertTrue(all(m <= 1 for m in medidas), medidas)
            expect(resumos.first.locator("div").filter(has_text="Créditos conciliados (R$)")).to_contain_text("37,80")
            expect(resumos.last.locator("div").filter(has_text="Taxa total (R$)")).to_contain_text("4,00")

    def test_relatorio_amplo_preserva_dados_csv_e_impressao(self):
        from apps.relatorios.services import RELATORIOS

        colunas = ["Categoria", "Quartos-noite", "Receita bruta", "Custo do canal", "Receita líquida",
                   "Diária média", "Cancelamentos", "Receita cancelada", "Participação"]
        dados = {"kpis": [("Total", "R$ 1.234.567,89")], "colunas": colunas,
                 "linhas": [[f"Categoria completa da conferência {n}", "1234", "R$ 1.234.567,89",
                              "R$ 123.456,78", "R$ 1.111.111,11", "R$ 349,90", "12",
                              "R$ 4.198,80", "12,34%"] for n in range(1, 31)]}
        with patch.dict(RELATORIOS["reservas"], {"builder": lambda inicio, fim: dados}):
            for largura, trilho in self.ESTADOS:
                self._abrir("relatorios:relatorio", largura, trilho, ("reservas",))
                self._conferir("relatorio-amplo", largura, trilho)
                self.assertEqual(self.page.locator(".rel-tabela").evaluate("el=>getComputedStyle(el).display"),
                                 "table" if largura == 1440 else "block")
                expect(self.page.locator(".rel-tabela tbody tr")).to_have_count(30)
                expect(self.page.locator(".rel-tabela tbody tr").last).to_contain_text("Categoria completa da conferência 30")
            csv = self.client.get(reverse("relatorios:relatorio", args=["reservas"]) + "?export=csv")
            self.assertEqual(csv.status_code, 200)
            texto = csv.content.decode("utf-8-sig")
            for coluna in colunas:
                self.assertIn(coluna, texto)
            self.assertIn("Categoria completa da conferência 30", texto)
            self.assertIn("R$ 1.234.567,89", texto)
            self._abrir("relatorios:relatorio", 390, args=("reservas",))
        self.page.emulate_media(media="print")
        expect(self.page.locator("h1")).to_be_visible()
        expect(self.page.locator(".rel-filtro")).not_to_be_visible()
        expect(self.page.locator(".rolagem-indicador")).not_to_be_visible()
        tabela = self.page.locator(".rel-tabela")
        self.assertEqual(tabela.evaluate("el=>getComputedStyle(el).display"), "table")
        self.assertEqual(tabela.locator("thead").evaluate("el=>getComputedStyle(el).display"), "table-header-group")
        self.assertEqual(tabela.locator("thead").evaluate("el=>getComputedStyle(el).clipPath"), "none")
        expect(tabela.locator("thead th")).to_have_count(9)
        expect(tabela.locator("tbody td")).to_have_count(270)
        moedas = tabela.locator(".rel-valor-monetario").evaluate_all("""els => els.map(el => {
            const range = document.createRange(); range.selectNodeContents(el);
            return [...new Set([...range.getClientRects()].map(r => Math.round(r.top)))].length;
        })""")
        self.assertEqual(len(moedas), 150)
        self.assertTrue(all(linhas == 1 for linhas in moedas), moedas)
        destino = os.environ.get("EVIDENCIAS_DIR")
        if destino:
            self.page.pdf(path=str(Path(destino) / "relatorio-amplo.pdf"), prefer_css_page_size=True, print_background=True)

    def test_relatorios_financeiros_calculados_com_reservas(self):
        query = f"?mes={self.c.hoje.month}&ano={self.c.hoje.year}"
        for chave in ("carteira", "pickup", "distribuicao"):
            for largura, trilho in self.ESTADOS:
                with self.subTest(relatorio=chave, largura=largura, trilho=trilho):
                    self._abrir("relatorios:relatorio", largura, trilho, (chave,), query)
                    self._conferir(f"relatorio-{chave}", largura, trilho)
