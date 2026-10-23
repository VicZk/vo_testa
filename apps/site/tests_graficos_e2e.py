"""Gráficos devem continuar desenhados após menu e histórico HTMX."""

import unittest
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.conciliacao.models import ExtratoBancario, LancamentoExtrato, LoteCartao, TransacaoCartao
from apps.nucleo.models import UH, ModuloContratado, TipoUH, Usuario

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class GraficosNavegacaoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo="reservas", defaults={"ativo": True})
        usuario = Usuario.objects.create_superuser(username="graficos-qa", password="senha-qa")
        UH.objects.create(numero="G01", tipo=TipoUH.objects.create(nome="Suíte QA", tarifa_base="250"))
        hoje = timezone.localdate()
        extrato = ExtratoBancario.objects.create(banco="Banco fictício QA")
        LancamentoExtrato.objects.create(extrato=extrato, data=hoje, valor="100", descricao="Crédito fictício")
        TransacaoCartao.objects.create(
            lote=LoteCartao.objects.create(adquirente="Simulada QA"), data_venda=hoje,
            nsu="QA-01", bruto="200", liquido="195", taxa="5")
        self.client.force_login(usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.route("**/*", lambda route: route.continue_()
            if urlparse(route.request.url).hostname in ("localhost", "127.0.0.1")
            or route.request.url.startswith(("data:", "blob:")) else route.abort())
        self.page.add_init_script("localStorage.setItem('sidebar', 'aberta')")
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.erros = []
        self.page.on("pageerror", lambda error: self.erros.append(str(error)))

    def confirmar_graficos(self, *, fechamento=False):
        self.page.wait_for_function("""() => {
          const canvases = [...document.querySelectorAll('main canvas')];
          return window.Chart && canvases.length > 0 && canvases.every(c => Chart.getChart(c));
        }""")
        estado = self.page.evaluate("""() => {
          const canvases = [...document.querySelectorAll('main canvas')];
          return {count:canvases.length, instances:Object.keys(Chart.instances).length,
            dados:canvases.map(c => ({id:c.id,data:Chart.getChart(c).data.datasets[0].data,
              width:c.getBoundingClientRect().width,height:c.getBoundingClientRect().height}))};
        }""")
        self.assertEqual(estado["instances"], estado["count"], estado)
        for canvas in estado["dados"]:
            self.assertGreater(canvas["width"], 100, estado)
            self.assertGreater(canvas["height"], 100, estado)
        if fechamento:
            self.assertEqual({c["id"] for c in estado["dados"]}, {"g-ext", "g-car"})
            self.assertTrue(all(c["data"] == [0, 1, 0] for c in estado["dados"]), estado)
        self.assertEqual(self.erros, [])

    def navegar_menu(self, nome):
        destino = reverse(nome)
        self.page.locator(f'aside a.nav-item[href="{destino}"]').click()
        self.page.wait_for_url(self.url(destino))
        self.page.wait_for_load_state("networkidle")

    def test_dashboard_e_fechamento_carregam_localmente_sem_overflow_no_celular(self):
        for nome in ("dashboard", "conciliacao:fechamento"):
            for largura in (320, 390, 768, 1440):
                with self.subTest(tela=nome, largura=largura):
                    self.page.set_viewport_size({"width": largura, "height": 900})
                    self.page.goto(self.url(reverse(nome)), wait_until="networkidle")
                    self.confirmar_graficos(fechamento=nome == "conciliacao:fechamento")
                    self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), largura)

    def test_menu_e_voltar_avancar_recriam_graficos_sem_duplicar_instancias(self):
        self.page.goto(self.url(reverse("dashboard")), wait_until="networkidle")
        self.confirmar_graficos()
        self.page.evaluate("window.__marcadorGrafico = 'mesmo documento'")
        self.navegar_menu("conciliacao:painel")
        self.assertEqual(self.page.evaluate("Object.keys(Chart.instances).length"), 0)
        self.navegar_menu("dashboard")
        self.confirmar_graficos()
        self.assertEqual(self.page.evaluate("window.__marcadorGrafico"), "mesmo documento")
        self.page.go_back()
        self.page.wait_for_url(self.url(reverse("conciliacao:painel")))
        self.page.go_back()
        self.page.wait_for_url(self.url(reverse("dashboard")))
        self.confirmar_graficos()
        self.page.go_forward()
        self.page.wait_for_url(self.url(reverse("conciliacao:painel")))
        self.assertEqual(self.page.evaluate("window.__marcadorGrafico"), "mesmo documento")

        # O link interno de fechamento é uma navegação completa. A saída pelo
        # menu e a volta pelo histórico continuam usando o documento recebido.
        self.page.locator(f'main a[href="{reverse("conciliacao:fechamento")}"]').click()
        self.page.wait_for_url(self.url(reverse("conciliacao:fechamento")))
        self.confirmar_graficos(fechamento=True)
        self.page.evaluate("window.__marcadorGrafico = 'mesmo documento'")
        self.navegar_menu("dashboard")
        self.confirmar_graficos()
        self.page.go_back()
        self.page.wait_for_url(self.url(reverse("conciliacao:fechamento")))
        self.confirmar_graficos(fechamento=True)
        self.page.go_forward()
        self.page.wait_for_url(self.url(reverse("dashboard")))
        self.confirmar_graficos()
        self.assertEqual(self.page.evaluate("window.__marcadorGrafico"), "mesmo documento")
