"""Preferência de fonte e filtros GET preservados nas larguras operacionais."""

import json
import os
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.comercial.models import EtapaFunil, Oportunidade, PaginaCaptacao
from apps.nucleo.models import Funcionario, ModuloContratado, Pessoa, Usuario
from apps.nucleo.modulos import Modulo

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class TipografiaFiltrosE2ETests(_BaseE2E):
    LOCALE = "pt-BR"
    ESTADOS = ((320, False), (390, False), (821, False), (1440, False), (1440, True))

    def setUp(self):
        super().setUp()
        cache.clear()
        self.usuario = Usuario.objects.create_superuser(username="qa-tipografia", password="senha-ficticia-123")
        for codigo in Modulo.values:
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.emulate_media(reduced_motion="reduce")
        self.evidencias = []

    def tearDown(self):
        if pasta := os.environ.get("E2E_EVIDENCIAS"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            (destino / f"{self._testMethodName}.json").write_text(
                json.dumps(self.evidencias, ensure_ascii=False, indent=2), encoding="utf-8")
        super().tearDown()

    def abrir(self, rota, largura, trilho=False, args=()):
        self.page.set_viewport_size({"width": largura, "height": 900})
        resposta = self.page.goto(self.url(reverse(rota, args=args)), wait_until="load")
        self.assertEqual(resposta.status, 200)
        self.page.evaluate("document.fonts.ready")
        if largura > 820 and self.page.locator(".app").count():
            app = self.page.locator(".app")
            if app.evaluate("el => el.classList.contains('recolhida')") != trilho:
                self.page.locator(".sidebar-toggle").click()
            self.page.wait_for_function("""trilho => {
                const app = document.querySelector('.app'), s = getComputedStyle(app);
                const esperado = parseFloat(s.getPropertyValue('--sidebar-w'));
                return app.classList.contains('recolhida') === trilho &&
                    Math.abs(document.querySelector('.sidebar').getBoundingClientRect().width - esperado) < 1;
            }""", arg=trilho)

    def foto(self, nome):
        if pasta := os.environ.get("E2E_EVIDENCIAS"):
            destino = Path(pasta)
            destino.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(destino / f"{nome}.png"), full_page=True)

    def test_setor_filtra_por_teclado_e_restaura_todos_nos_cinco_estados(self):
        setores = ("Recepção", "Governança", "Atendimento e organização de eventos e confraternizações")
        for numero, setor in enumerate(setores):
            Funcionario.objects.create(
                pessoa=Pessoa.objects.create(nome=f"Pessoa fictícia {numero}"), cargo="Atendimento", setor=setor)
        for largura, trilho in self.ESTADOS:
            with self.subTest(largura=largura, trilho=trilho):
                self.abrir("funcionarios", largura, trilho)
                formulario = self.page.get_by_role("form", name="Filtrar funcionários por setor")
                self.assertEqual(formulario.locator(".est-aba, [aria-current], nav").count(), 0)
                self.assertEqual(formulario.locator('[aria-pressed="true"]').count(), 1)
                for indice in (0, 2):
                    botao = formulario.get_by_role("button", name=setores[indice], exact=True)
                    botao.focus()
                    self.page.keyboard.press("Tab")
                    self.page.keyboard.press("Shift+Tab")
                    self.assertTrue(botao.evaluate("el => el.matches(':focus-visible')"))
                    self.assertGreater(float(botao.evaluate("el => parseFloat(getComputedStyle(el).outlineWidth)")), 0)
                    self.page.keyboard.press("Enter")
                    expect(formulario.get_by_role("button", name=setores[indice], exact=True)).to_have_attribute("aria-pressed", "true")
                    self.assertEqual(parse_qs(urlsplit(self.page.url).query)["setor"], [setores[indice]])
                    expect(self.page.locator(".func-linha")).to_have_count(1)
                    expect(self.page.locator(".func-linha")).to_contain_text(f"Pessoa fictícia {indice}")
                    self.assertEqual(formulario.locator('[aria-pressed="true"]').count(), 1)
                formulario.get_by_role("button", name="Todos").click()
                expect(self.page.locator(".func-linha")).to_have_count(3)
                expect(formulario.get_by_role("button", name="Todos")).to_have_attribute("aria-pressed", "true")
                medidas = formulario.evaluate("""form => {
                    const limite = form.getBoundingClientRect();
                    return [...form.querySelectorAll('button')].map(el => {
                        const r = el.getBoundingClientRect();
                        return {texto:el.innerText, altura:r.height, esquerda:r.left-limite.left,
                            direita:r.right-limite.right, excesso:el.scrollWidth-el.clientWidth};
                    });
                }""")
                for medida in medidas:
                    self.assertGreaterEqual(medida["altura"], 44 if largura <= 820 else 36, medida)
                    self.assertGreaterEqual(medida["esquerda"], -1, medida)
                    self.assertLessEqual(medida["direita"], 1, medida)
                    self.assertLessEqual(medida["excesso"], 1, medida)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura + 1)
                self.evidencias.append({"largura": largura, "trilho": trilho, "chips": medidas,
                    "filtrou_por_teclado": True, "todos_restaurou": True})
                self.foto(f"funcionarios-filtros-{largura}-{'trilho' if trilho else 'aberta'}")

    def test_textos_e_rotulos_acompanham_a_fonte_raiz_no_crm_e_no_publico(self):
        pessoa = Pessoa.objects.create(nome="Cliente fictício da tipografia", email="tipografia@example.test")
        etapa, _ = EtapaFunil.objects.get_or_create(nome="Contato de tipografia", defaults={"ordem": 1})
        oportunidade = Oportunidade.objects.create(pessoa=pessoa, titulo="Estadia fictícia", etapa=etapa,
            criado_por=self.usuario)
        paginas = [PaginaCaptacao.objects.create(nome=f"Captação {tema}", slug=f"qa-tipografia-{tema}",
            tema=tema, status="publicada", criado_por=self.usuario) for tema in ("fundador", "blueprint")]
        rotas = (
            ("comercial:funil", (), ".card-nome", ".card-novo"),
            ("comercial:oportunidade", (oportunidade.pk,), ".wpp-av", ".wpp-topo-dir .selo"),
            ("comercial:enviar_email_lead", (oportunidade.pk,), ".em-topo h1", ".em-campo > label"),
            ("captacao:publica", (paginas[0].slug,), ".kicker", ".hero .selo"),
            ("captacao:publica", (paginas[1].slug,), ".sub", ".cue"),
            ("privacidade", (), "h1", ".marca"),
        )
        for rota, args, texto, rotulo in rotas:
            for largura in (390, 1440):
                with self.subTest(rota=rota, args=args, largura=largura):
                    self.abrir(rota, largura, args=args)
                    medidas = []
                    for fonte in (16, 20):
                        self.page.evaluate("valor => document.documentElement.style.fontSize = `${valor}px`", fonte)
                        tamanhos = [self.page.locator(seletor).first.evaluate(
                            "el => parseFloat(getComputedStyle(el).fontSize)") for seletor in (texto, rotulo)]
                        medidas.append(tamanhos)
                        self.assertGreaterEqual(tamanhos[1], fonte * (0.75 if largura <= 820 or not rota.startswith("comercial:") else 0.7) - 0.01)
                    for antes, depois in zip(*medidas, strict=True):
                        self.assertAlmostEqual(depois / antes, 1.25, places=3)
                    self.evidencias.append({"rota": rota, "args": args, "largura": largura,
                        "seletores": [texto, rotulo], "fontes_16_20": medidas})
                    self.foto(f"tipografia-{rota.replace(':', '-')}-{'-'.join(map(str,args))}-{largura}-raiz20")
