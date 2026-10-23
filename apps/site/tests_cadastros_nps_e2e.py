"""Cadastro e relacionamento: erros reais, dados preservados e acesso utilizável."""

import os
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from apps.nps.models import RespostaNPS
from apps.nucleo.models import UH, Agencia, Funcionario, ModuloContratado, Pessoa, TipoUH, Usuario
from apps.portal.services import get_acesso
from apps.reservas.models import Reserva

from .tests_e2e import _PLAYWRIGHT_OK, _BaseE2E

if _PLAYWRIGHT_OK:
    from playwright.sync_api import expect


@unittest.skipUnless(_PLAYWRIGHT_OK, "playwright não instalado")
class CadastrosRelacionamentoE2ETests(_BaseE2E):
    LOCALE = "pt-BR"

    def setUp(self):
        super().setUp()
        cache.clear()
        for codigo in ("reservas", "appsite", "pagamentos"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="cadastros-qa", password="senha-qa")
        self.client.force_login(self.usuario)
        self.page.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page.route("**/*", lambda route: route.continue_()
            if urlparse(route.request.url).hostname in ("localhost", "127.0.0.1")
            or route.request.url.startswith(("data:", "blob:")) else route.abort())
        self.page.set_viewport_size({"width": 390, "height": 900})
        self.page.emulate_media(reduced_motion="reduce")

    def abrir(self, nome, args=None):
        self.page.goto(self.url(reverse(nome, args=args)), wait_until="networkidle")

    def foto(self, nome):
        destino = os.environ.get("E2E_EVIDENCIAS")
        if destino:
            pasta = Path(destino)
            pasta.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(pasta / nome), full_page=True)
            self.page.screenshot(path=str(pasta / nome.replace('.png', '-viewport.png')))
            aviso = self.page.locator("[data-erros-envio]")
            if aviso.count():
                aviso.first.screenshot(path=str(pasta / nome.replace('.png', '-mensagem.png')))

    def test_agencia_e_empresa_preservam_dados_no_erro_e_persistem_papel(self):
        p = self.page
        for papel in ("agencia", "empresa"):
            with self.subTest(papel=papel):
                p.goto(self.url(reverse("pessoa_nova") + "?papel=" + papel))
                p.get_by_role("link", name="Cancelar", exact=True).click()
                self.assertEqual(Pessoa.objects.count(), 0)
                p.goto(self.url(reverse("pessoa_nova") + "?papel=" + papel))
                nome = f"{papel.title()} fictícia com nome completo para conferir no celular"
                p.locator('[name="nome"]').fill(nome)
                p.locator('[name="telefone"]').fill("123")
                p.locator('[name="email"]').fill(f"{papel}@example.invalid")
                p.locator('[name="agencia-comissao_padrao"]').fill("10.50")
                p.get_by_role("button", name="Salvar", exact=True).click()
                expect(p.locator('[name="nome"]')).to_have_value(nome)
                expect(p.locator('[name="eh_agencia"]')).to_be_checked()
                self.assertFalse(Pessoa.objects.filter(nome=nome).exists())
                self.foto(f"cadastro-{papel}-erro-390.png")
                p.locator('[name="telefone"]').fill("49999990000")
                p.get_by_role("button", name="Salvar", exact=True).click()
                p.wait_for_url(self.url(reverse("pessoas")))
                agencia = Agencia.objects.get(pessoa__nome=nome)
                self.assertEqual(agencia.categoria, papel)
                self.assertEqual(str(agencia.comissao_padrao), "10.50")
                self.abrir("pessoa_editar", [agencia.pessoa_id])
                expect(p.locator('[name="nome"]')).to_have_value(nome)
                expect(p.locator('[name="email"]')).to_have_value(f"{papel}@example.invalid")
                # A contagem da segunda passagem considera a pessoa já salva.
                agencia.pessoa.delete()

    def test_login_duplicado_nao_cria_funcionario_parcial_e_correcao_cria_acesso(self):
        p = self.page
        self.abrir("funcionario_novo")
        p.locator('[name="nome"]').fill("Cadastro fictício cancelado")
        dialogos = []
        requisicoes = []
        p.on("request", lambda request: requisicoes.append(request.url)
             if request.url == self.url(reverse("funcionarios")) else None)
        p.once("dialog", lambda dialog: (dialogos.append(dialog.message), dialog.dismiss()))
        p.get_by_role("link", name="Cancelar", exact=True).click()
        self.assertEqual(len(dialogos), 1, "Cancelar dentro do formulário precisa confirmar o descarte")
        self.assertEqual(requisicoes, [], "Recusar o descarte não pode iniciar a navegação HTMX")
        expect(p).to_have_url(self.url(reverse("funcionario_novo")))
        expect(p.locator('[name="nome"]')).to_have_value("Cadastro fictício cancelado")
        p.once("dialog", lambda dialog: dialog.accept())
        p.get_by_role("link", name="Cancelar", exact=True).click()
        p.wait_for_url(self.url(reverse("funcionarios")))
        self.assertFalse(Funcionario.objects.exists())
        self.abrir("funcionario_novo")
        p.locator('[name="nome"]').fill("Funcionária fictícia QA")
        p.locator('[name="cargo"]').fill("Recepção")
        p.locator('[name="username"]').fill(self.usuario.username)
        p.locator('[name="password"]').fill("Senha-ficticia-123")
        p.locator('[name="modulos"][value="reservas"]').check()
        p.get_by_role("button", name="Criar funcionário").click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("Já existe um usuário com esse login.")
        expect(p.locator("[data-erros-envio]")).to_be_visible()
        self.assertTrue(p.locator("[data-erros-envio]").evaluate("""el => {
            const caixa = el.getBoundingClientRect();
            const alvo = document.elementFromPoint(caixa.left + caixa.width / 2, caixa.top + caixa.height / 2);
            return alvo === el || el.contains(alvo);
        }"""), "A mensagem precisa aparecer abaixo da barra fixa, sem ficar coberta.")
        self.assertFalse(Funcionario.objects.filter(pessoa__nome="Funcionária fictícia QA").exists())
        expect(p.locator('[name="nome"]')).to_have_value("Funcionária fictícia QA")
        expect(p.locator('[name="username"]')).to_have_value(self.usuario.username)
        expect(p.locator('[name="modulos"][value="reservas"]')).to_be_checked()
        for checkbox in p.locator('.campo input[type="checkbox"]').all():
            self.assertLessEqual(checkbox.bounding_box()["width"], 22)
            self.assertLessEqual(checkbox.bounding_box()["height"], 22)
        self.foto("funcionario-login-duplicado-390.png")
        p.locator('[name="username"]').fill("recepcao-ficticia-qa")
        p.locator('[name="password"]').fill("Senha-ficticia-123")
        p.get_by_role("button", name="Criar funcionário").click()
        p.wait_for_url(self.url(reverse("funcionarios")))
        funcionario = Funcionario.objects.get(pessoa__nome="Funcionária fictícia QA")
        self.assertTrue(funcionario.usuario.is_active)
        self.foto("funcionario-login-criado-390.png")
        self.assertTrue(funcionario.usuario.check_password("Senha-ficticia-123"))
        self.assertTrue(funcionario.usuario.modulos.filter(codigo="reservas").exists())

    def test_conceder_login_no_painel_cria_usuario_ativo_e_permite_entrar(self):
        funcionario = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="Equipe fictícia sem login"))
        self.abrir("funcionarios")
        p = self.page
        p.locator(".func-linha").filter(has_text=funcionario.pessoa.nome).click()
        painel = p.locator(f"#painel-{funcionario.pk}")
        painel.get_by_role("button", name="Acesso Sistema").click()
        painel.locator('[name="username"]').fill(self.usuario.username)
        painel.locator('[name="password"]').fill("Senha-ficticia-123")
        painel.get_by_role("button", name="Salvar ficha").click()
        expect(painel.locator("[data-erros-envio]")).to_contain_text("Já existe um usuário")
        expect(painel.locator('[name="username"]')).to_have_value(self.usuario.username)
        funcionario.refresh_from_db()
        self.assertIsNone(funcionario.usuario_id)
        painel.locator('[name="username"]').fill("equipe-ficticia-qa")
        painel.locator('[name="password"]').fill("Senha-ficticia-123")
        painel.locator('[name="modulos"][value="reservas"]').check()
        painel.get_by_role("button", name="Salvar ficha").click()
        expect(painel.get_by_text("Ficha salva ✓", exact=True)).to_be_visible()
        funcionario.refresh_from_db()
        self.assertIsNotNone(funcionario.usuario_id)
        self.assertTrue(funcionario.usuario.is_active)
        contexto = self._browser.new_context(locale="pt-BR")
        try:
            visitante = contexto.new_page()
            visitante.goto(self.url("/crm/entrar/"))
            visitante.locator('[name="username"]').fill("equipe-ficticia-qa")
            visitante.locator('[name="password"]').fill("Senha-ficticia-123")
            visitante.locator('[name="password"]').press("Enter")
            expect(visitante.get_by_role("heading", name="Visão geral", exact=True)).to_be_visible()
        finally:
            contexto.close()

    def reserva_encerrada(self):
        hoje = timezone.localdate()
        uh = UH.objects.create(numero="NPS-QA", tipo=TipoUH.objects.create(nome="Suíte QA", tarifa_base="200"))
        return Reserva.objects.create(uh=uh, hospede=Pessoa.objects.create(nome="Hóspede fictícia NPS"),
            checkin=hoje-timedelta(days=4), checkout=hoje-timedelta(days=1),
            checkout_real=timezone.now()-timedelta(days=1), status=Reserva.Status.CHECKOUT,
            valor_diaria="200", criado_por=self.usuario)

    def test_modulos_validam_dependencia_cancelam_desativacao_e_persistem_estado(self):
        ModuloContratado.objects.update(ativo=False)
        ModuloContratado.objects.filter(codigo="reservas").update(ativo=True)
        self.abrir("modulos_central")
        p = self.page
        governanca = p.locator('.modulo-card').filter(has=p.locator('input[name="codigo"][value="governanca"]'))
        reservas = p.locator('.modulo-card').filter(has=p.locator('input[name="codigo"][value="reservas"]'))
        governanca.get_by_role("button", name="Ativar", exact=True).click()
        expect(governanca.get_by_role("button", name="Desativar", exact=True)).to_be_visible()
        self.assertTrue(ModuloContratado.objects.get(codigo="governanca").ativo)
        expect(reservas.get_by_role("button", name="Desativar", exact=True)).to_be_disabled()
        p.once("dialog", lambda dialog: dialog.dismiss())
        governanca.get_by_role("button", name="Desativar", exact=True).click()
        self.assertTrue(ModuloContratado.objects.get(codigo="governanca").ativo)
        p.once("dialog", lambda dialog: dialog.accept())
        governanca.get_by_role("button", name="Desativar", exact=True).click()
        expect(governanca.get_by_role("button", name="Ativar", exact=True)).to_be_visible()
        self.assertFalse(ModuloContratado.objects.get(codigo="governanca").ativo)
        p.once("dialog", lambda dialog: dialog.accept())
        reservas.get_by_role("button", name="Desativar", exact=True).click()
        expect(reservas.get_by_role("button", name="Ativar", exact=True)).to_be_visible()
        governanca.get_by_role("button", name="Ativar", exact=True).click()
        expect(p.get_by_role("alert")).to_contain_text("O módulo Governança depende de: Reservas.")
        self.assertFalse(ModuloContratado.objects.get(codigo="governanca").ativo)

    def test_nps_publico_corrige_falta_consentimento_preserva_comentario_e_registra_uma_vez(self):
        reserva = self.reserva_encerrada()
        caminho = reverse("portal:nps", args=[get_acesso(reserva.pk).token])
        p = self.page
        p.context.clear_cookies()
        p.goto(self.url(caminho))
        comentario = "Comentário fictício: quarto agradável, demora no atendimento."
        p.locator('[name="nota"][value="7"]').check()
        p.locator('[name="comentario"]').fill(comentario)
        # Confere também a validação do servidor se o cliente não aplicar required.
        p.locator('[name="consentimento"]').evaluate("el => el.required = false")
        p.get_by_role("button", name="Enviar minha avaliação").click()
        expect(p.locator('[name="comentario"]')).to_have_value(comentario)
        expect(p.locator('[name="nota"][value="7"]')).to_be_checked()
        self.assertFalse(RespostaNPS.objects.filter(reserva=reserva).exists())
        p.locator('[name="consentimento"]').check()
        p.get_by_role("button", name="Enviar minha avaliação").click()
        expect(p.get_by_role("status")).to_have_text("Obrigado! Sua avaliação foi registrada.")
        resposta = RespostaNPS.objects.get(reserva=reserva)
        self.assertEqual((resposta.nota, resposta.comentario), (7, comentario))
        p.reload()
        expect(p.get_by_role("status")).to_have_text("Obrigado! Sua avaliação foi registrada.")
        self.assertEqual(RespostaNPS.objects.filter(reserva=reserva).count(), 1)
        self.foto("nps-publico-registrado-390.png")

    def test_nps_acompanhamento_rejeita_espacos_preserva_texto_e_salva_autoria(self):
        from apps.nps.services import responder
        resposta, _ = responder(self.reserva_encerrada().pk, 2, "Demora fictícia no atendimento", consentimento=True)
        self.abrir("nps:painel")
        p = self.page
        p.get_by_text("Registrar acompanhamento", exact=True).click()
        campo = p.get_by_label("Contato realizado e providências")
        campo.fill("   ")
        p.get_by_role("button", name="Salvar acompanhamento").click()
        expect(p.locator("[data-erros-envio]")).to_contain_text("Descreva o acompanhamento")
        expect(campo).to_have_value("   ")
        self.foto("nps-acompanhamento-erro-390.png")
        resposta.refresh_from_db()
        self.assertIsNone(resposta.tratada_em)
        campo.fill("Contato fictício realizado; providência registrada pela recepção.")
        p.get_by_role("button", name="Salvar acompanhamento").click()
        expect(p.get_by_text("Ver acompanhamento", exact=True)).to_be_visible()
        p.get_by_text("Ver acompanhamento", exact=True).click()
        expect(p.get_by_label("Contato realizado e providências")).to_have_value(
            "Contato fictício realizado; providência registrada pela recepção.")
        resposta.refresh_from_db()
        self.assertEqual(resposta.tratada_por_id, self.usuario.pk)
        self.assertIsNotNone(resposta.tratada_em)
        self.foto("nps-acompanhamento-salvo-390.png")
