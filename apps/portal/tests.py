from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    CategoriaProduto,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    Produto,
    TipoUH,
    registrar_entrada,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import SolicitacaoPortal

Usuario = get_user_model()


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class PortalBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="rec", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Std", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 07", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="Maria Turista")
        self.reserva = self._hospedar()
        self.estadia = services.resolver(services.get_acesso(self.reserva.pk).token)

    def _hospedar(self):
        from apps.reservas.models import Reserva
        hoje = timezone.localdate()
        r = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede, checkin=hoje, checkout=hoje + timedelta(days=2),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"), criado_por=self.op,
        )
        r.fazer_checkin(self.op)
        return r


class AcessoTests(PortalBase):
    def test_token_resolve_estadia(self):
        acesso = services.get_acesso(self.reserva.pk)
        estadia = services.resolver(acesso.token)
        self.assertEqual(estadia["uh"], "Quarto 07")
        self.assertEqual(estadia["hospede"], "Maria Turista")

    def test_token_invalido(self):
        import uuid
        self.assertIsNone(services.resolver(uuid.uuid4()))

    def test_home_publica_abre_sem_login(self):
        token = services.get_acesso(self.reserva.pk).token
        r = self.client.get(reverse("portal:home", args=[token]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quarto 07")

    def test_modulo_inativo_esconde_portal(self):
        ModuloContratado.objects.filter(codigo=Modulo.APPSITE).update(ativo=False)
        token = services.get_acesso(self.reserva.pk).token
        self.assertEqual(self.client.get(reverse("portal:home", args=[token])).status_code, 404)


class PedidoTests(PortalBase):
    def _estoque_restaurante(self):
        cat = CategoriaProduto.objects.create(nome="Bebidas")
        p = Produto.objects.create(nome="Suco", categoria=cat, preco_venda=Decimal("9.00"))
        local = LocalEstoque.objects.create(nome="Cozinha", modulo="restaurante")
        registrar_entrada(p, local, 10, Decimal("3.00"), self.op)
        return p

    def test_pedido_cria_comanda_e_baixa_estoque(self):
        from apps.nucleo.models import saldo
        from apps.restaurante.models import Comanda
        p = self._estoque_restaurante()
        local = LocalEstoque.objects.get(modulo="restaurante")
        services.pedir_restaurante(self.estadia, [(p.pk, 2)])
        self.assertTrue(Comanda.objects.filter(rotulo="Quarto 07 · app").exists())
        self.assertEqual(saldo(p, local), Decimal("8"))
        self.assertTrue(
            SolicitacaoPortal.objects.filter(tipo="restaurante").exists()
        )


class SolicitacaoTests(PortalBase):
    def test_limpeza_gera_faxina(self):
        services.solicitar_limpeza(self.estadia)
        self.assertTrue(SolicitacaoPortal.objects.filter(tipo="limpeza").exists())
        if ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA, ativo=True).exists():
            from apps.governanca.models import TarefaGovernanca
            self.assertTrue(TarefaGovernanca.objects.filter(uh=self.uh, origem="portal").exists())

    def test_manutencao_abre_os(self):
        services.solicitar_manutencao(self.estadia, "Chuveiro frio")
        self.assertTrue(SolicitacaoPortal.objects.filter(tipo="manutencao").exists())
        if ModuloContratado.objects.filter(codigo=Modulo.MANUTENCAO, ativo=True).exists():
            from apps.manutencao.models import OrdemServico
            self.assertTrue(OrdemServico.objects.filter(uh=self.uh).exists())


class CheckoutTests(PortalBase):
    def test_cobrar_saldo_gera_cobranca(self):
        from apps.reservas import services as reservas
        conta = self.reserva.conta
        reservas.lancar_na_conta(conta, "consumo", "consumo", "Item", Decimal("50.00"), self.op)
        estadia = services.resolver(services.get_acesso(self.reserva.pk).token)
        cobranca = services.cobrar_saldo(estadia, "pix")
        # diárias (2×200) já lançadas no check-in + consumo de 50 = 450
        self.assertEqual(cobranca.valor, Decimal("450.00"))
        self.assertEqual(cobranca.reserva_id, self.reserva.pk)
        self.assertEqual(cobranca.finalidade, "saldo_conta")


class RecepcaoTests(PortalBase):
    def test_qr_exige_modulo_e_hospedada(self):
        self.client.login(username="rec", password="senha-forte-123")
        r = self.client.get(reverse("portal:qr", args=[self.reserva.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "svg")


@override_settings(FNRH_BLOQUEAR_CHECKIN=True)
class FNRHPortalTests(TestCase):
    """Pré check-in: o hóspede responsável preenche a FNRH de todos por um token."""

    def setUp(self):
        from apps.reservas.models import Reserva
        ModuloContratado.objects.update_or_create(
            codigo=Modulo.APPSITE, defaults={"ativo": True}
        )
        self.op = Usuario.objects.create_superuser(username="rec2", password="senha-forte-123")
        self.tipo = TipoUH.objects.create(nome="Std2", tarifa_base=Decimal("200"))
        self.uh = UH.objects.create(numero="Quarto 09", tipo=self.tipo)
        self.hospede = Pessoa.objects.create(nome="João Viajante")
        hoje = timezone.localdate()
        self.reserva = Reserva.objects.create(
            uh=self.uh, hospede=self.hospede,
            checkin=hoje + timedelta(days=1), checkout=hoje + timedelta(days=3),
            status=Reserva.Status.CONFIRMADA, valor_diaria=Decimal("200"),
            criado_por=self.op,
        )
        self.token = services.get_acesso(self.reserva.pk).token

    def _post_data(self):
        fichas = list(self.reserva.fichas_fnrh.all())
        data = {
            "form-TOTAL_FORMS": str(len(fichas)),
            "form-INITIAL_FORMS": str(len(fichas)),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for i, f in enumerate(fichas):
            data.update({
                f"form-{i}-id": str(f.pk),
                f"form-{i}-nome": f.nome or f"Acompanhante {i}",
                f"form-{i}-nascimento": "1990-01-01",
                f"form-{i}-documento_tipo": "CPF",
                f"form-{i}-documento_numero": "123456",
                f"form-{i}-cidade": "Itá",
                f"form-{i}-motivo_viagem": "LAZER_FERIAS",
                f"form-{i}-nacionalidade": "Brasileira",
            })
        return data

    def test_pagina_abre_e_cria_fichas(self):
        resp = self.client.get(reverse("portal:checkin", args=[self.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.reserva.fichas_fnrh.count(), 2)  # titular + 1 acompanhante

    def test_envio_completa_fnrh_e_libera_checkin(self):
        from apps.reservas.models import Reserva
        from apps.reservas.services import garantir_fichas_fnrh
        garantir_fichas_fnrh(self.reserva)
        resp = self.client.post(
            reverse("portal:checkin", args=[self.token]), self._post_data()
        )
        self.assertEqual(resp.status_code, 302)
        self.reserva.refresh_from_db()
        self.assertTrue(self.reserva.fnrh_pronta)
        # preenchida via portal
        self.assertTrue(
            self.reserva.fichas_fnrh.filter(origem="portal").exists()
        )
        # e o check-in agora passa
        self.reserva.fazer_checkin(self.op)
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.status, Reserva.Status.HOSPEDADA)


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class TokenPosCheckoutTests(PortalBase):
    """TM-003: o token do portal deixa de dar acesso após o check-out."""

    def _checkout(self):
        from apps.nucleo.models import FormaPagamento, SessaoCaixa
        from apps.reservas import services as rsv
        conta = self.reserva.conta
        if conta.saldo():
            SessaoCaixa.objects.create(operador=self.op, modulo="reservas",
                                       fundo_troco=Decimal("0"))
            dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
            rsv.receber_pagamento(conta, self.op, dinheiro, conta.saldo())
        self.reserva.fazer_checkout(self.op)

    def test_home_404_apos_checkout(self):
        token = services.get_acesso(self.reserva.pk).token
        self.assertEqual(self.client.get(reverse("portal:home", args=[token]),
                                         SERVER_NAME="localhost").status_code, 200)
        self._checkout()
        self.assertEqual(self.client.get(reverse("portal:home", args=[token]),
                                         SERVER_NAME="localhost").status_code, 404)

    def test_fnrh_checkin_404_apos_checkout(self):
        self._checkout()
        token = services.get_acesso(self.reserva.pk).token
        self.assertEqual(self.client.get(reverse("portal:checkin", args=[token]),
                                         SERVER_NAME="localhost").status_code, 404)

    def test_referrer_policy_header(self):
        token = services.get_acesso(self.reserva.pk).token
        r = self.client.get(reverse("portal:home", args=[token]), SERVER_NAME="localhost")
        self.assertEqual(r.headers.get("Referrer-Policy"), "same-origin")


class AparenciaPortalTests(PortalBase):
    """A tela que o hóspede abre no celular: fonte da marca, fora da busca e
    alvos de toque de 44px."""

    def html(self):
        token = services.get_acesso(self.reserva.pk).token
        return self.client.get(reverse("portal:home", args=[token])).content.decode()

    def test_carrega_as_fontes_da_marca(self):
        """O portal usava o app.css sem nenhuma @font-face carregada e caía em
        Georgia/system — a tela do hóspede não parecia da pousada."""
        html = self.html()
        self.assertIn("HankenGrotesk-400-latin.woff2", html)
        self.assertIn("Fraunces-600-latin.woff2", html)

    def test_fora_de_indice_de_busca(self):
        """URL com token: não pode ser indexada nem vazar no Referer."""
        html = self.html()
        self.assertIn('name="robots" content="noindex, nofollow"', html)
        self.assertIn('name="referrer" content="same-origin"', html)

    def test_sem_token_de_cor_inexistente(self):
        """`var(--brasa, …)` nunca existiu: o ícone caía sempre no valor de reserva."""
        self.assertNotIn("--brasa", self.html())

    def test_alvo_de_toque_minimo(self):
        self.assertIn("min-height: 44px", self.html())


class PedidoValidacaoTests(PedidoTests):
    """Pedido do quarto: só itens do cardápio, quantidades de quarto, sem erro 500."""

    def test_item_fora_do_cardapio_e_recusado_sem_abrir_comanda(self):
        from apps.restaurante.models import Comanda
        p = self._estoque_restaurante()
        Produto.objects.filter(pk=p.pk).update(ativo=False)
        with self.assertRaisesMessage(ValidationError, "não está mais no cardápio"):
            services.pedir_restaurante(self.estadia, [(p.pk, 1)])
        self.assertFalse(Comanda.objects.exists())

    def test_quantidade_invalida_ou_grande_demais(self):
        p = self._estoque_restaurante()
        with self.assertRaisesMessage(ValidationError, "Pedido inválido"):
            services.pedir_restaurante(self.estadia, [(p.pk, "dois")])
        with self.assertRaisesMessage(ValidationError, "Até 20 unidades"):
            services.pedir_restaurante(self.estadia, [(p.pk, 21)])

    def test_post_com_lixo_volta_com_mensagem_e_nao_500(self):
        self._estoque_restaurante()
        token = services.get_acesso(self.reserva.pk).token
        r = self.client.post(reverse("portal:pedir", args=[token]), {"qtd_abc": "1"})
        self.assertEqual(r.status_code, 302)


class NovoQRTests(PortalBase):
    def test_novo_qr_invalida_o_antigo(self):
        antigo = services.get_acesso(self.reserva.pk).token
        self.client.force_login(self.op)
        r = self.client.post(reverse("portal:qr_novo", args=[self.reserva.pk]))
        self.assertRedirects(r, reverse("portal:qr", args=[self.reserva.pk]))
        novo = services.get_acesso(self.reserva.pk).token
        self.assertNotEqual(antigo, novo)
        self.assertIsNone(services.resolver(antigo))
        self.assertEqual(self.client.get(reverse("portal:home", args=[antigo])).status_code, 404)
        self.assertEqual(self.client.get(reverse("portal:home", args=[novo])).status_code, 200)

    def test_get_nao_troca(self):
        antigo = services.get_acesso(self.reserva.pk).token
        self.client.force_login(self.op)
        self.client.get(reverse("portal:qr_novo", args=[self.reserva.pk]))
        self.assertEqual(services.get_acesso(self.reserva.pk).token, antigo)


class LinkDoQRTests(PortalBase):
    """O QR serve quem está no balcão. Quem já subiu para o quarto — ou ainda nem
    chegou, no caso do pré check-in — recebe o mesmo endereço por mensagem."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.op)
        Pessoa.objects.filter(pk=self.hospede.pk).update(telefone="(49) 99964-8702")

    def test_qr_do_portal_copia_o_link_e_manda_no_whatsapp_do_hospede(self):
        html = self.client.get(reverse("portal:qr", args=[self.reserva.pk])).content.decode()
        token = services.get_acesso(self.reserva.pk).token
        self.assertIn(f'data-copiar="http://testserver/hospede/{token}/"', html)
        self.assertIn("https://wa.me/5549999648702?text=", html)
        self.assertIn("Enviar pelo WhatsApp", html)

    def test_tela_do_pre_checkin_fala_de_ficha_e_nao_de_estadia(self):
        """Mesma tela, dois links: o contexto mandava `finalidade` e o template
        ignorava — o QR da FNRH dizia "acessa a própria estadia"."""
        html = self.client.get(reverse("portal:qr_fnrh", args=[self.reserva.pk])).content.decode()
        self.assertIn("Pré check-in (FNRH)", html)
        self.assertIn("preenche a ficha de todos", html)
        self.assertNotIn("acessa a própria estadia", html)
        token = services.get_acesso(self.reserva.pk).token
        self.assertIn(f'data-copiar="http://testserver/hospede/{token}/checkin/"', html)

    def test_voltar_leva_para_a_reserva_e_nao_so_para_tras(self):
        html = self.client.get(reverse("portal:qr", args=[self.reserva.pk])).content.decode()
        self.assertIn(reverse("reservas:detalhe", args=[self.reserva.pk]), html)
