"""Listas operacionais: leitura no celular e controles com o mesmo efeito real."""

import os
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.governanca import services
from apps.governanca.models import ConferenciaOcupacao, StatusLimpeza
from apps.nucleo.models import UH, ModuloContratado, Pessoa, TipoUH, Usuario
from apps.reservas.models import Reserva

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class ListagensMobileE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        for codigo in ("reservas", "governanca", "manutencao"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="listas-qa", password="senha-qa")
        self.camareira = Usuario.objects.create_user(username="camareira-qa", first_name="Maria", last_name="da Governança")
        self.camareira.modulos.add(ModuloContratado.objects.get(codigo="governanca"))
        tipo = TipoUH.objects.create(nome="Suíte QA", tarifa_base="300")
        self.uh = UH.objects.create(numero="QA-101", tipo=tipo)
        self.outra = UH.objects.create(numero="QA-102", tipo=tipo)
        self.tarefa = services.abrir_faxina(self.uh, usuario=self.usuario)
        services.inspecionar(self.outra, self.usuario)
        hoje = timezone.localdate()
        self.reserva = Reserva.objects.create(
            uh=self.uh, hospede=Pessoa.objects.create(nome="Maria Aparecida de Albuquerque e Silva — hóspede fictícia"),
            checkin=hoje + timedelta(days=10), checkout=hoje + timedelta(days=13),
            valor_diaria="300", status=Reserva.Status.CONFIRMADA, criado_por=self.usuario)
        Reserva.objects.create(
            uh=self.outra, hospede=Pessoa.objects.create(nome="Carlos Teste — hóspede fictício"),
            checkin=hoje + timedelta(days=10), checkout=hoje + timedelta(days=12),
            valor_diaria="200", status=Reserva.Status.ORCAMENTO, criado_por=self.usuario)
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.emulate_media(reduced_motion="reduce")
        self.page.set_viewport_size({"width": 390, "height": 844})

    def abrir(self, nome):
        self.page.goto(self.url(reverse(nome)), wait_until="networkidle")

    def foto(self, nome):
        destino = os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / nome), full_page=True)

    def test_reserva_mostra_hospede_datas_status_e_link_completo_em_todas_as_larguras(self):
        self.abrir("reservas:lista")
        linha = self.page.locator(".reservas-listagem-tabela tr").filter(has_text=self.reserva.hospede.nome)
        for largura in (320, 390, 768, 1440, 2560):
            with self.subTest(largura=largura):
                self.page.set_viewport_size({"width": largura, "height": 900})
                expect(linha.get_by_role("link", name=f"Abrir reserva #{self.reserva.pk} de")).to_be_visible()
                expect(linha).to_contain_text(self.reserva.checkin.strftime("%d/%m/%Y"))
                expect(linha).to_contain_text(self.reserva.checkout.strftime("%d/%m/%Y"))
                expect(linha).to_contain_text("Confirmada")
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura)
                if largura <= 768:
                    medidas = linha.evaluate("""el => {
                      const r=el.getBoundingClientRect();
                      return [...el.children].map(c=>{const b=c.getBoundingClientRect();return {left:b.left,right:b.right,parentLeft:r.left,parentRight:r.right};});
                    }""")
                    for m in medidas:
                        self.assertGreaterEqual(m["left"], m["parentLeft"])
                        self.assertLessEqual(m["right"], m["parentRight"])
                self.foto(f"lista-reservas-{largura}.png")

    def test_busca_status_utilitarios_e_nova_reserva_funcionam_no_celular(self):
        self.abrir("reservas:lista")
        self.page.get_by_role("searchbox", name="Buscar por hóspede ou quarto").fill("Maria")
        self.page.get_by_role("combobox", name="Situação da reserva").select_option("confirmada")
        self.page.get_by_role("button", name="Filtrar", exact=True).click()
        expect(self.page.locator(".reservas-listagem-tabela tbody tr")).to_have_count(1)
        expect(self.page.locator(".reservas-listagem-tabela")).to_contain_text(self.reserva.hospede.nome)
        summary = self.page.locator(".reservas-listagem-opcoes > summary")
        summary.focus()
        summary.press("Enter")
        expect(self.page.get_by_role("link", name="Kit de contingência", exact=True)).to_be_visible()
        summary.press("Enter")
        expect(self.page.get_by_role("link", name="Kit de contingência", exact=True)).not_to_be_visible()
        self.page.locator(".reservas-listagem-acoes").get_by_role("link", name="Nova reserva", exact=True).click()
        expect(self.page.locator("#modal-conteudo")).to_contain_text("Nova reserva")
        expect(self.page.locator("#modal-conteudo form")).to_be_visible()

    def test_filtro_persiste_apos_iniciar_concluir_e_aprovar_limpeza(self):
        self.abrir("governanca:quartos")
        filtro = self.page.get_by_role("combobox", name="Situação dos quartos", exact=True)
        filtro.select_option("suja")
        linha = self.page.locator(f"#quarto-{self.uh.pk}")
        expect(linha).to_be_visible()
        expect(self.page.locator(f"#quarto-{self.outra.pk}")).not_to_be_visible()
        linha.get_by_role("button", name="Iniciar limpeza", exact=True).click()
        expect(filtro).to_have_value("suja")
        expect(linha).not_to_be_visible()
        filtro.select_option("em_limpeza")
        linha.get_by_role("button", name="Concluir limpeza", exact=True).click()
        expect(filtro).to_have_value("em_limpeza")
        filtro.select_option("limpa")
        linha.get_by_role("button", name="Aprovar limpeza", exact=True).click()
        expect(filtro).to_have_value("limpa")
        filtro.select_option("inspecionada")
        expect(linha).to_contain_text("Pronto para receber o hóspede")
        self.assertEqual(StatusLimpeza.objects.get(uh=self.uh).situacao, "inspecionada")

    def test_conferencia_atribuicao_e_divergencia_continuam_acessiveis(self):
        self.abrir("governanca:quartos")
        linha = self.page.locator(f"#quarto-{self.uh.pk}")
        expect(linha.get_by_text("Atribuição pendente", exact=True)).to_be_visible()
        summary = linha.locator("summary")
        summary.focus()
        summary.press("Enter")
        select = linha.get_by_role("combobox", name=f"Responsável pelo quarto {self.uh.numero}")
        select.select_option(str(self.camareira.pk))
        self.tarefa.refresh_from_db()
        self.assertIsNone(self.tarefa.camareira_id)
        linha.get_by_role("button", name="Salvar", exact=True).click()
        expect(linha.locator(".governanca-operacao-atual")).to_contain_text("Maria da Governança")
        self.tarefa.refresh_from_db()
        self.assertEqual(self.tarefa.camareira_id, self.camareira.pk)
        linha.locator("summary").click()
        linha.get_by_role("button", name=f"{self.uh.numero}: Ocupado (com bagagem)", exact=True).click()
        expect(linha.locator(".governanca-operacao-atual")).to_contain_text("Ocupado (com bagagem)")
        expect(linha.get_by_text("Hóspede não lançado", exact=True)).to_be_visible()
        expect(linha.locator("details")).not_to_have_attribute("open", "")
        self.assertEqual(ConferenciaOcupacao.objects.get(uh=self.uh).visto, "ocupado")
        for largura in (320, 390, 768, 1440):
            self.page.set_viewport_size({"width": largura, "height": 900})
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura)
            self.foto(f"governanca-divergencia-{largura}.png")

    def test_os_de_area_comum_nao_envia_quarto_oculto_e_conclui_atendimento(self):
        from apps.manutencao.models import OrdemServico
        self.abrir("manutencao:painel")
        self.page.get_by_role("link", name="Nova ordem de serviço", exact=True).click()
        form = self.page.locator(".manutencao-nova")
        form.get_by_role("combobox", name="Quarto", exact=True).select_option(str(self.uh.pk))
        form.get_by_role("checkbox", name="Bloquear o quarto durante o reparo").check()
        form.get_by_role("button", name="Área comum", exact=True).click()
        form.get_by_role("textbox", name="Área comum", exact=True).fill("Piscina — área fictícia")
        form.get_by_role("textbox", name="Título", exact=False).fill("Revisar iluminação da piscina e da passagem para as cabanas")
        form.get_by_role("combobox", name="Prioridade", exact=True).select_option("urgente")
        form.get_by_role("combobox", name="Responsável (interno)", exact=True).select_option(str(self.usuario.pk))
        form.get_by_role("button", name="Abrir OS", exact=True).click()
        expect(self.page.get_by_role("heading", name="OS #", exact=False)).to_be_visible()
        ordem = OrdemServico.objects.get(titulo__startswith="Revisar iluminação")
        self.assertIsNone(ordem.uh_id)
        self.assertFalse(ordem.bloqueia_uh)
        self.assertEqual(ordem.area, "Piscina — área fictícia")
        self.page.get_by_role("button", name="Iniciar (em andamento)", exact=True).click()
        expect(self.page.get_by_role("button", name="Iniciar (em andamento)", exact=True)).not_to_be_visible()
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "em_andamento")
        self.page.locator('input[name="custo_maodeobra"]').fill("100.50")
        self.page.locator('input[name="custo_pecas"]').fill("20")
        self.page.locator('textarea[name="resolucao"]').fill("Luminárias revisadas e testadas — dados fictícios.")
        self.page.get_by_role("button", name="Concluir", exact=True).click()
        expect(self.page.locator(".pagina-cabecalho")).to_contain_text("Concluída")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "concluida")
        self.assertEqual(str(ordem.custo_total), "120.50")

    def test_ordem_longa_mostra_prioridade_responsavel_prazo_e_acao_sem_rolagem_lateral(self):
        from apps.manutencao.services import abrir_os
        prazo = timezone.localdate() + timedelta(days=2)
        ordem = abrir_os(self.usuario, uh=self.uh,
            titulo="Revisar ar-condicionado e vazamento junto à entrada da varanda da suíte",
            prioridade="alta", responsavel=self.camareira, previsto_para=prazo,
            bloquear=True)
        self.abrir("manutencao:painel")
        item = self.page.locator(".manutencao-ordem").filter(has_text=ordem.titulo)
        for largura in (320,390,768,1440,2560):
            self.page.set_viewport_size({"width": largura, "height": 900})
            expect(item).to_contain_text("Prioridade alta")
            expect(item).to_contain_text("Maria da Governança")
            expect(item).to_contain_text(prazo.strftime("%d/%m/%Y"))
            expect(item).to_contain_text("Quarto bloqueado")
            expect(item.get_by_role("link", name="Ver e iniciar", exact=False)).to_be_visible()
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura)
            self.foto(f"manutencao-ordens-{largura}.png")
        item.get_by_role("link", name="Ver e iniciar", exact=False).click()
        expect(self.page.get_by_role("button", name="Iniciar (em andamento)", exact=True)).to_be_visible()

    def test_precos_preservam_edicoes_entre_quartos_e_revelam_erro_em_quarto_oculto(self):
        from apps.reservas.models import TarifaUnidade
        primeira = TarifaUnidade.objects.create(uh=self.uh, classificacao="baixa", valor="300")
        segunda = TarifaUnidade.objects.create(uh=self.outra, classificacao="baixa", valor="450")
        self.abrir("tabela_precos")
        filtro = self.page.get_by_role("combobox", name="Quarto", exact=True)
        primeiro = self.page.locator(f'input[name="base_{self.uh.pk}_baixa"]')
        segundo = self.page.locator(f'input[name="base_{self.outra.pk}_baixa"]')
        expect(filtro).to_have_value("")
        expect(primeiro).to_be_visible()
        expect(segundo).to_be_visible()
        filtro.select_option(str(self.uh.pk))
        expect(segundo).not_to_be_visible()
        self.assertNotEqual(self.page.locator('.precos-form').get_attribute('data-dirty'), '1')
        primeiro.fill("71235")
        filtro.select_option(str(self.outra.pk))
        segundo.fill("88888")
        expect(self.page.locator('[data-estado-edicao]')).to_contain_text("não salvas")
        filtro.select_option(str(self.uh.pk))
        expect(primeiro).to_have_value("712,35")
        segundo.evaluate("el => { el.value='NaN'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
        self.page.locator("#precos-salvar").get_by_role("button", name="Salvar tabela", exact=True).click()
        expect(self.page.locator('[data-erros-envio]')).to_contain_text(self.outra.numero)
        expect(segundo).to_be_visible()
        expect(primeiro).to_have_value("712,35")
        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(str(primeira.valor), "300.00")
        self.assertEqual(str(segunda.valor), "450.00")
        segundo.fill("88888")
        filtro.select_option(str(self.uh.pk))
        for largura in (320,390,1440):
            self.page.set_viewport_size({"width":largura,"height":900})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),largura)
            self.foto(f"precos-filtrados-{largura}.png")
        self.page.locator("#precos-salvar").get_by_role("button", name="Salvar tabela", exact=True).click()
        expect(self.page.locator('[data-estado-edicao]')).to_contain_text("Nenhuma alteração pendente")
        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual(str(primeira.valor), "712.35")
        self.assertEqual(str(segunda.valor), "888.88")
