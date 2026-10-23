"""Contratos visuais públicos: conteúdo, controles e valores cabem nas quatro larguras."""
import os
import unittest
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import UH, FormaPagamento, ModuloContratado, Pessoa, SessaoCaixa, Usuario
from apps.nucleo.modulos import Modulo
from apps.portal.services import get_acesso
from apps.reservas.models import Reserva
from apps.reservas.services import receber_pagamento
from apps.site.models import VitrineQuarto

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E, _UnidadeVendavelMixin

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
@override_settings(FNRH_BLOQUEAR_CHECKIN=False, ECA_BLOQUEAR_CHECKIN=False, HOME_MODO="site")
class AuditoriaPublicoE2ETests(_UnidadeVendavelMixin, _BaseE2E):
    LOCALE = "pt-BR"
    LARGURAS = (320, 390, 821, 1440)

    def setUp(self):
        super().setUp()
        cache.clear()
        for codigo in (Modulo.RESERVAS, Modulo.APPSITE, Modulo.RESTAURANTE):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.uh = self._semear_unidade(capacidade=4)
        for n, descricao in enumerate(("Quarto com uma descrição longa e acessível para toda a família.", "Quarto tranquilo."), 2):
            uh = UH.objects.create(numero=f"E2E-{n}", tipo=self.uh.tipo, nome_tematico=f"Quarto público {n}")
            VitrineQuarto.objects.create(uh=uh, publicar=True, destaque=True, descricao_curta=descricao)
        self.page.close()
        self.context = self._browser.new_context(locale="pt-BR", has_touch=True, viewport={"width": 390, "height": 844})
        self.context.add_init_script("localStorage.setItem('votesta-consentimento', 'recusado')")
        self.page = self.context.new_page()
        self.page.emulate_media(reduced_motion="reduce")
        self.erros = []
        self.http_erros = []
        self.page.on("pageerror", lambda e: self.erros.append(str(e)))
        self.page.on("response", lambda r: self.http_erros.append((r.status, r.url)) if r.status >= 400 and r.url.startswith(self.live_server_url) else None)

    def tearDown(self):
        self.context.close()
        super().tearDown()

    def abrir(self, nome, largura, args=None):
        self.page.set_viewport_size({"width": largura, "height": 640 if largura == 320 else 900})
        resposta = self.page.goto(self.url(reverse(nome, args=args)), wait_until="load")
        self.assertEqual(resposta.status, 200)
        self.page.evaluate("() => document.fonts.ready")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
        self.assertEqual(self.erros, [])
        self.assertEqual(self.http_erros, [])

    def foto(self, nome, largura):
        if pasta := os.environ.get("EVIDENCIAS_DIR"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"publico-{nome}-{largura}.png"),
                full_page=nome not in ("menu", "cookies", "lp-fundador", "lp-inauguracao", "portal-fnrh"), animations="disabled")

    def cabe_no_pai(self, seletor):
        problemas = self.page.locator(seletor).evaluate_all("""els => els.filter(e => {
          const r=e.getBoundingClientRect(), p=e.parentElement.getBoundingClientRect();
          return r.width && (r.left < p.left-1 || r.right > p.right+1);
        }).map(e => e.outerHTML.slice(0,180))""")
        self.assertEqual(problemas, [])

    def test_home_formularios_divisorias_cartoes_e_menu(self):
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                self.abrir("core:home", largura)
                self.cabe_no_pai(".site-divisoria > div > *")
                botao = self.page.get_by_role("button", name="Buscar datas", exact=True)
                self.assertGreaterEqual(botao.bounding_box()["height"], 44)
                self.assertTrue(botao.evaluate("e => e.scrollWidth <= e.clientWidth"))
                self.page.locator("#hero-checkin-visivel").click()
                popup = self.page.locator(".flatpickr-calendar.open")
                expect(popup).to_be_visible()
                popup.locator(".flatpickr-next-month").click()
                for controle in popup.locator(".flatpickr-monthDropdown-months, .cur-year, .flatpickr-next-month, .flatpickr-prev-month").all():
                    self.assertGreaterEqual(controle.bounding_box()["height"], 44)
                    self.assertTrue(controle.evaluate("""e => {
                      const r=e.getBoundingClientRect(), h=document.elementFromPoint(r.left+r.width/2,r.bottom-3);
                      return h===e || e.contains(h);
                    }"""))
                self.page.keyboard.press("Escape")
                for nome in ("eventos", "contato"):
                    campo = self.page.locator(f"#{nome}-nome")
                    campo.focus()
                    self.assertEqual(campo.evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(255, 255, 255)")
                    self.assertNotEqual(campo.evaluate("e => getComputedStyle(e).boxShadow"), "none")
                    self.assertEqual(self.page.locator(f'label[for="{nome}-nome"]').count(), 1)
                    self.assertEqual(self.page.locator(f"#{nome}-checkin-visivel").count(), 1)
                self.page.locator("#quartos").scroll_into_view_if_needed()
                if largura >= 821:
                    precos = self.page.locator("#quartos a.group .mt-auto").evaluate_all("els => els.map(e => e.getBoundingClientRect().top)")
                    self.assertLessEqual(max(precos)-min(precos), 1)
                self.foto("home", largura)
                if largura < 1440:
                    self.page.evaluate("window.scrollTo(0,0)")
                    self.page.get_by_role("button", name="Abrir menu", exact=True).click()
                    cta = self.page.locator("#mobileMenu > a")
                    expect(cta).to_be_visible()
                    caixa = cta.bounding_box()
                    self.assertGreaterEqual(caixa["y"], self.page.locator("header").bounding_box()["height"])
                    self.assertLessEqual(caixa["y"] + caixa["height"], self.page.viewport_size["height"])
                    self.page.locator(".mobile-menu-links a").last.scroll_into_view_if_needed()
                    self.assertLessEqual(self.page.locator(".mobile-menu-links a").last.bounding_box()["y"] + 44, self.page.viewport_size["height"])
                    self.foto("menu", largura)
                    self.page.keyboard.press("Escape")

    def test_calendario_toque_cabecalho_avanco_e_etapas(self):
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                self.abrir("core:reservar", largura)
                cal = self.page.locator(".flatpickr-calendar.inline")
                expect(cal).to_be_visible()
                # O mês atual desabilita a seta anterior por minDate=today.
                cal.locator(".flatpickr-next-month").click()
                for sel in (".flatpickr-monthDropdown-months", ".cur-year", ".flatpickr-next-month", ".flatpickr-prev-month"):
                    controle = cal.locator(sel)
                    self.assertGreaterEqual(controle.bounding_box()["height"], 44)
                    self.assertTrue(controle.evaluate("""e => {
                      const r=e.getBoundingClientRect(), hit=document.elementFromPoint(r.left+r.width/2,r.bottom-3);
                      return hit===e || e.contains(hit);
                    }"""), sel)
                botoes = self.page.locator("#btn-ver-quartos")
                expect(botoes).to_be_disabled()
                contraste = botoes.evaluate("""e => {
                  const rgb=s => s.match(/[\\d.]+/g).map(Number);
                  const mix=(c,b) => c.slice(0,3).map((v,i) => v*(c[3]??1)+b[i]*(1-(c[3]??1)));
                  const lum=c => c.map(v => v/255).map(v => v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                    .reduce((a,v,i) => a+v*[.2126,.7152,.0722][i],0);
                  const s=getComputedStyle(e), bg=mix(rgb(s.backgroundColor),[255,255,255]), fg=mix(rgb(s.color),bg);
                  return (Math.max(lum(bg),lum(fg))+.05)/(Math.min(lum(bg),lum(fg))+.05);
                }""")
                self.assertGreaterEqual(contraste, 4.5)
                posicoes = cal.locator(".flatpickr-day").evaluate_all("els => els.slice(0,8).map(e => ({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))")
                self.assertLessEqual(max(p["y"] for p in posicoes[:7])-min(p["y"] for p in posicoes[:7]), 1)
                self.assertGreater(posicoes[7]["y"], posicoes[6]["y"])
                self.assertAlmostEqual(posicoes[0]["x"], posicoes[7]["x"], delta=1)
                self.cabe_no_pai(".reserva-passo > .relative, #btn-ver-quartos > svg")
                if largura >= 768:
                    cartoes = self.page.locator("#form-datas > div").evaluate_all("els => els.map(e => e.getBoundingClientRect().bottom)")
                    self.assertLessEqual(max(cartoes)-min(cartoes), 1)
                self.foto("calendario", largura)
                dias = cal.locator(".flatpickr-day:not(.prevMonthDay):not(.nextMonthDay):not(.flatpickr-disabled)")
                dias.nth(2).click()
                dias.nth(4).click()
                expect(botoes).to_be_enabled()
                botoes.click()
                expect(self.page.get_by_role("heading", name="Quartos Disponíveis", exact=True)).to_be_visible()

    def test_titulos_publicos_filtros_precos_e_fotos(self):
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                for nome in ("core:politica_privacidade", "core:termos_servico", "core:exclusao_dados", "daypass_publico"):
                    self.abrir(nome, largura)
                    topo = self.page.locator("header").bounding_box()
                    titulo = self.page.locator("main > p").first.bounding_box()
                    self.assertGreaterEqual(titulo["y"], topo["y"] + topo["height"] + 16)
                    self.foto(nome.split(":")[-1], largura)
                self.abrir("core:quarto_detalhe", largura, [self.uh.pk])
                self.cabe_no_pai(".qd__price, .qd__cta")
                preco = self.page.locator(".qd__price")
                self.assertEqual(preco.evaluate("e => getComputedStyle(e).whiteSpace"), "nowrap")
                self.assertEqual(self.page.locator(".foto-ausente").count(), 3)
                self.assertGreaterEqual(self.page.locator(".qd__back").bounding_box()["height"], 44)
                self.foto("quarto", largura)
                self.abrir("core:quartos_todos", largura)
                if largura < 640:
                    larguras = self.page.locator("[data-vitrine-filtros] select").evaluate_all("els => els.map(e => e.getBoundingClientRect().width)")
                    self.assertLessEqual(max(larguras)-min(larguras), 1)
                self.cabe_no_pai(".sticky p, .sticky a")
                self.assertGreaterEqual(self.page.locator(".sticky a").bounding_box()["height"], 44)
                self.foto("vitrine", largura)

    def test_portal_valores_e_extrato_com_creditos(self):
        usuario = Usuario.objects.create_superuser(username="publico-auditoria", password="ficticio-local-123")
        hoje = timezone.localdate()
        reserva = Reserva.objects.create(uh=self.uh, hospede=Pessoa.objects.create(nome="Hóspede fictício de teste"),
            checkin=hoje, checkout=hoje + timedelta(days=3), valor_diaria=510, criado_por=usuario, status="confirmada")
        reserva.fazer_checkin(usuario)
        SessaoCaixa.objects.create(operador=usuario, modulo="reservas")
        dinheiro, _ = FormaPagamento.objects.get_or_create(tipo="dinheiro", defaults={"nome": "Dinheiro"})
        receber_pagamento(reserva.conta, usuario, dinheiro, 100, observacao="Pagamento fictício de teste")
        token = get_acesso(reserva.pk).token
        self.client.force_login(usuario)
        self.context.add_cookies([{"name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}])
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                for nome in ("portal:home", "portal:checkout"):
                    self.abrir(nome, largura, [token])
                    valores = self.page.locator(".pt-linha > :last-child")
                    self.assertGreater(valores.count(), 0)
                    self.assertTrue(valores.evaluate_all("els => els.every(e => getComputedStyle(e).whiteSpace==='nowrap' && getComputedStyle(e).textAlign==='right')"))
                    self.cabe_no_pai(".pt-linha > :last-child")
                    self.foto(nome.replace(":", "-"), largura)
                self.abrir("reservas:extrato", largura, [reserva.pk])
                if largura < 640:
                    expect(self.page.locator(".extrato-dica-rol")).to_have_count(2)
                    self.assertTrue(self.page.locator(".extrato-dica-rol").first.is_visible())
                    regiao = self.page.locator(".extrato-tabela-rol").nth(1)
                    regiao.evaluate("e => e.scrollLeft = e.scrollWidth")
                    valor = regiao.locator("tbody td.num").first
                    expect(valor).to_have_text("R$ 100,00")
                    self.assertLessEqual(valor.bounding_box()["x"] + valor.bounding_box()["width"], regiao.bounding_box()["x"] + regiao.bounding_box()["width"] + 1)
                else:
                    self.assertAlmostEqual(self.page.locator(".extrato-acoes").bounding_box()["x"], self.page.locator(".extrato").bounding_box()["x"], delta=1)
                self.foto("extrato", largura)
                self.abrir("portal:checkin", largura, [token])
                for titulo in self.page.locator(".fnrh-ficha-titulo").all():
                    self.assertLessEqual(titulo.evaluate("e => e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight)"), 3.1)
                self.cabe_no_pai(".fnrh-ficha-cab > *, .fnrh-ficha-cab h3 > *")
                self.foto("portal-fnrh", largura)

    def test_lps_nav_central_e_barra_sem_corte(self):
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                self.abrir("lp:fundador_2", largura)
                if largura > 760:
                    rotulo = self.page.locator(".nav .date").bounding_box()
                    self.assertAlmostEqual(rotulo["x"]+rotulo["width"]/2, largura/2, delta=1)
                self.page.locator(".banda-lugar .inner2").scroll_into_view_if_needed()
                expect(self.page.locator(".banda-lugar .inner2")).to_have_css("opacity", "1")
                self.assertIn("0.72", self.page.locator(".banda-lugar .grad").evaluate("e => getComputedStyle(e).backgroundImage"))
                self.foto("lp-fundador", largura)
                self.abrir("lp:inauguracao", largura)
                self.page.locator(".cta-fixo").evaluate("e => e.classList.add('on')")
                self.cabe_no_pai(".cta-fixo > *")
                self.foto("lp-inauguracao", largura)

    def test_descadastro_publico_confirma_apenas_no_envio(self):
        pessoa = Pessoa.objects.create(nome="Pessoa fictícia", email="publico@example.com", aceita_email=True)
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                self.abrir("email_publico:descadastrar", largura, [pessoa.unsub_token])
                botao = self.page.get_by_role("button", name="Confirmar descadastro", exact=True)
                self.assertGreaterEqual(botao.bounding_box()["height"], 44)
                self.cabe_no_pai(".descadastro, .descadastro button")
                pessoa.refresh_from_db()
                self.assertTrue(pessoa.aceita_email)
                self.foto("descadastro", largura)
        botao.click()
        expect(self.page.get_by_role("heading", name="Pronto, você foi descadastrado")).to_be_visible()
        pessoa.refresh_from_db()
        self.assertFalse(pessoa.aceita_email)

    def test_codigo_da_reserva_preserva_exemplo_em_caixa_normal(self):
        for largura in self.LARGURAS:
            with self.subTest(largura=largura):
                self.abrir("core:minha_reserva", largura)
                campo = self.page.locator("#codigo")
                self.assertEqual(campo.evaluate("e => getComputedStyle(e, '::placeholder').textTransform"), "none")
                self.assertEqual(campo.evaluate("e => getComputedStyle(e).textTransform"), "uppercase")
                self.foto("minha-reserva", largura)

    def test_cookies_em_320_cabem_sem_esconder_metade_da_tela(self):
        self.context.clear_cookies()
        self.abrir("core:home", 320)
        self.page.evaluate("localStorage.removeItem('votesta-consentimento')")
        # O init script também roda no reload; removê-lo não é necessário:
        # o componente público possui API de reabertura no rodapé.
        self.page.locator("#consentimento").evaluate("e => { e.hidden=false; e.removeAttribute('aria-hidden'); }")
        aviso = self.page.locator("#consentimento")
        self.assertLessEqual(aviso.bounding_box()["height"], 180)
        self.cabe_no_pai(".aviso-cookies-btn")
        for botao in aviso.locator("button").all():
            self.assertGreaterEqual(botao.bounding_box()["height"], 44)
        self.foto("cookies", 320)
