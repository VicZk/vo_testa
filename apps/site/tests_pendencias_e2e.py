"""Lista correspondente ao badge, atualização real e permissões no navegador."""

import os
import re
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.governanca import services as governanca
from apps.governanca.models import StatusLimpeza
from apps.nucleo.models import UH, ModuloContratado, TipoUH, Usuario
from apps.nucleo.modulos import Modulo
from apps.nucleo.retorno_pendencias import com_retorno

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class PendenciasOperacionaisE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update(ativo=False)
        gov, _ = ModuloContratado.objects.update_or_create(codigo=Modulo.GOVERNANCA, defaults={"ativo": True})
        cache.clear()
        self.usuario = Usuario.objects.create_user(username="pendencias-e2e", password="qa-pendencias-123")
        self.usuario.modulos.add(gov)
        tipo = TipoUH.objects.create(nome="Governança QA", tarifa_base=Decimal("100"))
        self.tarefas = []
        for n in range(1, 5):
            quarto = UH.objects.create(numero=f"QA {n:02}", tipo=tipo)
            self.tarefas.append(governanca.abrir_faxina(quarto, usuario=self.usuario))
        governanca.iniciar_tarefa(self.tarefas[3], self.usuario)
        pronto = UH.objects.create(numero="QA pronto", tipo=tipo)
        StatusLimpeza.objects.create(uh=pronto, situacao=StatusLimpeza.Situacao.INSPECIONADA)
        inspecao = UH.objects.create(numero="QA inspeção", tipo=tipo)
        StatusLimpeza.objects.create(uh=inspecao, situacao=StatusLimpeza.Situacao.LIMPA)
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")

    def _abrir_central(self):
        self.page.goto(self.url(reverse("pendencias") + "?origem=governanca&estado=pendente"), wait_until="load")
        expect(self.page.get_by_role("heading", name="Pendências", exact=True)).to_be_visible()
        expect(self.page.locator("[data-pendencia-id]")).to_have_count(3)

    def _foto(self, nome, pagina=None):
        destino = os.environ.get("EVIDENCIAS_DIR") or os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            (pagina or self.page).screenshot(path=str(pasta / f"pendencias-{nome}.png"), full_page=True)

    def _conferir_contraste_badge(self, pagina, contexto):
        badge = pagina.locator("[data-governanca-avisos]")
        self.abrir_grupo_menu(badge)
        pagina.mouse.move(0, 0)
        badge.evaluate("el => el.blur()")
        for estado in ("normal", "hover", "foco"):
            with self.subTest(contexto=contexto, estado=estado):
                if estado == "hover":
                    badge.hover()
                    self.assertTrue(badge.evaluate("el => el.matches(':hover')"))
                elif estado == "foco":
                    pagina.mouse.move(0, 0)
                    pagina.locator(".nav-item-principal").focus()
                    pagina.keyboard.press("Tab")
                    expect(badge).to_be_focused()
                    self.assertTrue(badge.evaluate("el => el.matches(':focus-visible')"))
                # No toque o fundo verde está no número, dentro do alvo de 44px;
                # no desktop ele está no link. Medir o fundo pintado em ambos.
                cores = badge.locator(".nav-badge-numero").evaluate("""numero => {
                  const rgba = cor => cor.match(/[\\d.]+/g).map(Number);
                  let fundo = numero, canais;
                  do {
                    canais = rgba(getComputedStyle(fundo).backgroundColor);
                    if (canais.length === 3 || canais[3] > 0) break;
                    fundo = fundo.parentElement;
                  } while (fundo);
                  return {texto: rgba(getComputedStyle(numero).color), fundo: canais};
                }""")
                for canais in cores.values():
                    self.assertEqual(canais[3] if len(canais) == 4 else 1, 1, cores)

                def luminancia(canais):
                    srgb = [canal / 255 for canal in canais[:3]]
                    linear = [canal / 12.92 if canal <= .04045 else ((canal + .055) / 1.055) ** 2.4
                              for canal in srgb]
                    return sum(canal * peso for canal, peso in zip(linear, (.2126, .7152, .0722)))

                luminancias = [luminancia(canais) for canais in cores.values()]
                contraste = (max(luminancias) + .05) / (min(luminancias) + .05)
                self.assertGreaterEqual(contraste, 4.5, f"{contexto}/{estado}: {contraste:.2f}:1, {cores}")
                if estado == "hover":
                    self._foto(f"badge-{contexto}-hover", pagina)

    def _conferir_atualizacoes(self, badge, central, pendentes):
        # Cada endpoint tem seu próprio fetch. Esperar o corpo completo também
        # impede que uma resposta inicial ainda em voo seja confundida com o poll.
        for resposta, campo in ((badge.value, "pendentes"), (central.value, "total")):
            self.assertEqual(resposta.status, 200)
            self.assertIsNone(resposta.finished())
            self.assertEqual(resposta.json()[campo], pendentes)

    def _avancar_polling(self, pendentes):
        p = self.page
        with (
            p.expect_response(lambda r: reverse("governanca:atualizacoes") in r.url) as badge,
            p.expect_response(lambda r: reverse("pendencias_atualizacoes") in r.url) as central,
        ):
            p.clock.run_for(60001)
        self._conferir_atualizacoes(badge, central, pendentes)

    def test_badge_abre_lista_exata_polling_preserva_filtro_e_limpa_zero(self):
        p = self.page
        p.clock.install()
        with p.expect_response(lambda r: reverse("governanca:atualizacoes") in r.url) as inicial:
            p.goto(self.url(reverse("governanca:quartos")), wait_until="load")
        self.assertIsNone(inicial.value.finished())
        self.assertEqual(inicial.value.json()["pendentes"], 3)
        badge = p.get_by_role("link", name="3 serviços de limpeza pendentes", exact=True)
        expect(badge).to_be_visible()
        expect(badge).to_have_attribute("href", reverse("pendencias") + "?origem=governanca&estado=pendente")
        # A navegação HTMX inicia os dois fetches no afterSettle. Concluí-los
        # antes de mudar os dados evita adiantar 60s virtuais com o badge ocupado.
        with (
            p.expect_response(lambda r: reverse("governanca:atualizacoes") in r.url) as aviso,
            p.expect_response(lambda r: reverse("pendencias_atualizacoes") in r.url) as central,
        ):
            badge.click()
        self._conferir_atualizacoes(aviso, central, 3)
        expect(p.get_by_role("heading", name="Pendências", exact=True)).to_be_visible()
        expect(p.locator("[data-pendencia-id]")).to_have_count(3)
        expect(p.locator("[data-pendencias-total]")).to_have_text("3 pendências")
        expect(p.locator("#pendencias-resultados")).not_to_contain_text("QA 04")
        expect(p.locator("#pendencias-resultados")).not_to_contain_text("QA pronto")
        expect(p.locator("#pendencias-resultados")).not_to_contain_text("QA inspeção")

        governanca.iniciar_tarefa(self.tarefas[0], self.usuario)
        self._avancar_polling(2)
        expect(p.locator("[data-pendencia-id]")).to_have_count(2)
        expect(p.locator("[data-governanca-avisos]")).to_have_text("2")
        expect(p.get_by_role("combobox", name="Origem das pendências")).to_have_value("governanca")
        expect(p.get_by_role("combobox", name="Situação das pendências")).to_have_value("pendente")

        # O link em foco some com o serviço resolvido; o foco permanece no bloco.
        p.locator("[data-pendencia-id] a").first.focus()
        governanca.concluir_tarefa(self.tarefas[1], self.usuario)
        governanca.concluir_tarefa(self.tarefas[2], self.usuario)
        self._avancar_polling(0)
        expect(p.locator("[data-pendencia-id]")).to_have_count(0)
        expect(p.locator("[data-pendencias-total]")).to_have_text("0 pendências")
        expect(p.locator("[data-pendencias-vazio]")).to_be_visible()
        expect(p.locator("[data-governanca-avisos]")).to_be_hidden()
        self.assertTrue(p.evaluate("document.querySelector('#pendencias-resultados').contains(document.activeElement)"))
        self.assertIn("origem=governanca&estado=pendente", p.url)
        self._foto("zero-apos-polling")

        p.get_by_role("link", name="Em andamento 2", exact=True).click()
        expect(p.locator("[data-pendencia-id]")).to_have_count(2)
        expect(p.locator('[data-pendencia-estado="em_andamento"]')).to_have_count(2)
        self.clicar_item_menu(".nav-item-principal", pagina=p)
        expect(p).to_have_url(self.url(reverse("governanca:painel")))

    def test_link_para_quartos_preserva_recorte_de_servicos_e_ignora_filtro_antigo(self):
        self.page.add_init_script("localStorage.setItem('gov-filtro', 'inspecionada'); localStorage.setItem('gov-meus', '1')")
        self._abrir_central()
        self.page.get_by_role("link", name="Abrir quartos com serviços pendentes", exact=True).click()
        central = reverse("pendencias") + "?origem=governanca&estado=pendente"
        expect(self.page).to_have_url(self.url(com_retorno(reverse("governanca:quartos") + "?servico=pendente", central)))
        expect(self.page.get_by_role("link", name="Voltar para Pendências", exact=True)).to_have_attribute("href", central)
        linhas = self.page.locator(".governanca-listagem tbody tr:visible")
        expect(linhas).to_have_count(3)
        for n in (1, 2, 3):
            expect(linhas.get_by_role("link", name=f"QA {n:02}", exact=True)).to_be_visible()
        expect(linhas.get_by_role("link", name="QA 04", exact=True)).to_have_count(0)
        self._foto("quartos-filtrados")

    def test_layout_da_central_e_acesso_por_toque_em_quatro_larguras(self):
        self._abrir_central()
        p = self.page
        self._conferir_contraste_badge(p, "desktop")
        for largura in (320, 390, 821, 1440):
            with self.subTest(largura=largura):
                p.set_viewport_size({"width": largura, "height": 900})
                p.evaluate("document.activeElement?.blur()")
                self._foto(f"central-{largura}")
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), largura + 1)
                fora = p.locator("#conteudo select, #conteudo button, #conteudo .botao-neutro").evaluate_all("""els => els.filter(e => {
                  const r=e.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth+1);
                }).map(e => e.textContent.trim())""")
                self.assertEqual(fora, [])
                selos_cortados = p.locator(".pendencias-lista .registro-status .selo").evaluate_all("""els => els.filter(e => {
                  const r=e.getBoundingClientRect(), c=e.closest('td').getBoundingClientRect();
                  return r.left < c.left-1 || r.right > c.right+1 || e.scrollWidth > e.clientWidth+1;
                }).map(e => e.textContent.trim())""")
                self.assertEqual(selos_cortados, [])
        contexto = self._browser.new_context(locale="pt-BR", has_touch=True, viewport={"width": 390, "height": 844})
        contexto.add_cookies(p.context.cookies())
        toque = contexto.new_page()
        toque.emulate_media(reduced_motion="reduce")
        try:
            toque.goto(self.url(reverse("governanca:quartos")), wait_until="load")
            toque.locator("#btn-menu-mobile").click()
            badge = toque.locator("[data-governanca-avisos]")
            expect(badge).to_be_visible()
            badge.scroll_into_view_if_needed()
            toque.locator(".sidebar").evaluate("async el => await Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})))")
            medidas = badge.evaluate("""el => {
              const r=el.getBoundingClientRect(), alvo=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
              return {width:r.width,height:r.height,acertou:alvo?.closest('[data-governanca-avisos]')===el};
            }""")
            self.assertGreaterEqual(medidas["width"], 44)
            self.assertGreaterEqual(medidas["height"], 44)
            self.assertTrue(medidas["acertou"])
            self._conferir_contraste_badge(toque, "toque")
            badge.click()
            expect(toque.get_by_role("heading", name="Pendências", exact=True)).to_be_visible()
            expect(toque.locator("[data-pendencia-id]")).to_have_count(3)
        finally:
            contexto.close()

    def test_usuario_sem_governanca_nao_recebe_badge_origem_ou_lista_por_parametro(self):
        restaurante, _ = ModuloContratado.objects.update_or_create(codigo=Modulo.RESTAURANTE, defaults={"ativo": True})
        usuario = Usuario.objects.create_user(username="garcom-pendencias-e2e", password="qa-garcom-123")
        usuario.modulos.add(restaurante)
        cache.clear()
        self.client.force_login(usuario)
        self.page.context.clear_cookies()
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        requisicoes = []
        self.page.on("request", lambda r: requisicoes.append(r.url))
        self.page.goto(self.url(reverse("pendencias")), wait_until="load")
        expect(self.page.locator("[data-governanca-avisos]")).to_have_count(0)
        expect(self.page.locator('select[name="origem"] option[value="governanca"]')).to_have_count(0)
        expect(self.page.locator('select[name="origem"] option[value="financeiro"]')).to_have_count(0)
        self.assertFalse(any(reverse("governanca:atualizacoes") in url for url in requisicoes))
        for rota in ("pendencias", "pendencias_atualizacoes"):
            for origem in ("governanca", "financeiro", "caixa"):
                resposta = self.page.request.get(self.url(reverse(rota) + "?origem=" + origem))
                self.assertEqual(resposta.status, 403)
                self.assertNotRegex(resposta.text(), re.compile(r"QA 0[1-4]"))
