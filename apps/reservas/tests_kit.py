"""Kit de contingência — a folha que vale quando a internet cai.

O que estes testes seguram: o hóspede aparece no quarto certo com o saldo certo;
chegada e saída de hoje caem nas suas seções; reserva cancelada/no-show não entra;
day use só aparece ocupado; sem Governança a coluna de limpeza desaparece sem
quebrar a página; o número de consultas não cresce com o número de reservas; e o
e-mail só sai para quem foi configurado.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    ModuloContratado,
    NaturezaFiscal,
    Pessoa,
    SessaoCaixa,
    TipoUH,
)
from apps.nucleo.modulos import Modulo

from . import services
from .models import FichaFNRH, LancamentoConta, Reserva

Usuario = get_user_model()


@override_settings(FNRH_BLOQUEAR_CHECKIN=False, ECA_BLOQUEAR_CHECKIN=False)
class KitBase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_superuser(
            username="recepcao", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(
            nome="Cabana Kit", tarifa_base=Decimal("300.00")
        )
        self.uh = UH.objects.create(numero="K1", tipo=self.tipo, nome_tematico="Lampião")
        self.hospede = Pessoa.objects.create(nome="Maria Kit", telefone="(49) 90000-0001")
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.hoje = timezone.localdate()
        from apps.nucleo.models import ConfiguracaoReservas
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )

    def quarto(self, numero, **kwargs):
        return UH.objects.create(numero=numero, tipo=self.tipo, **kwargs)

    def reserva(self, *, status=Reserva.Status.CONFIRMADA, dias=2, uh=None, offset=0,
                hospede=None, **kwargs):
        checkin = self.hoje + timedelta(days=offset)
        return Reserva.objects.create(
            uh=uh or self.uh,
            hospede=hospede or self.hospede,
            checkin=checkin,
            checkout=checkin + timedelta(days=dias),
            status=status,
            valor_diaria=Decimal("300.00"),
            criado_por=self.usuario,
            **kwargs,
        )

    def hospedar(self, **kwargs):
        """Reserva que entrou ontem e já está em casa (conta aberta)."""
        kwargs.setdefault("offset", -1)
        r = self.reserva(status=Reserva.Status.CONFIRMADA, **kwargs)
        with patch("django.utils.timezone.localdate", return_value=r.checkin):
            r.fazer_checkin(self.usuario)
        return r


class KitDadosTests(KitBase):
    def test_hospedado_no_quarto_certo_com_o_saldo_certo(self):
        r = self.hospedar(dias=3)
        services.lancar_na_conta(
            r.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Cerveja", Decimal("18.50"), self.usuario,
        )
        kit = services.kit_contingencia()
        self.assertEqual(len(kit["hospedados"]), 1)
        linha = kit["hospedados"][0]
        self.assertEqual(linha["quarto"], "K1")
        self.assertEqual(linha["nome_quarto"], "Lampião")
        self.assertEqual(linha["titular"], "Maria Kit")
        self.assertEqual(linha["saldo"], r.conta.saldo())
        self.assertEqual(linha["saldo"], Decimal("918.50"))  # 3 × 300 + 18,50
        self.assertEqual(kit["totais"]["hospedes"], 2)
        self.assertEqual(kit["totais"]["quartos_ocupados"], 1)
        self.assertEqual(kit["totais"]["saldo_total"], Decimal("918.50"))

    def test_acompanhantes_vem_das_fichas(self):
        r = self.hospedar(adultos=2)
        FichaFNRH.objects.create(reserva=r, titular=True, nome="Maria Kit")
        FichaFNRH.objects.create(reserva=r, nome="João Kit")
        kit = services.kit_contingencia()
        self.assertEqual(kit["hospedados"][0]["acompanhantes"], ["João Kit"])

    def test_menor_sem_autorizacao_entra_como_alerta(self):
        """ECA, art. 82: a folha avisa quem está sem os pais nem autorização."""
        r = self.hospedar()
        # Ficha preenchida depois da entrada (a trava do check-in é outro caminho).
        FichaFNRH.objects.create(
            reserva=r, nome="Pedrinho Kit",
            nascimento=self.hoje - timedelta(days=365 * 10),
        )
        kit = services.kit_contingencia()
        self.assertEqual(kit["hospedados"][0]["menores"], ["Pedrinho Kit"])

    def test_chegada_e_saida_de_hoje_nas_secoes_certas(self):
        saindo = self.hospedar(dias=1)  # entrou ontem, sai hoje
        chegando = self.reserva(uh=self.quarto("K2"), status=Reserva.Status.CONFIRMADA)
        amanha = self.reserva(uh=self.quarto("K3"), offset=1)

        kit = services.kit_contingencia()
        self.assertEqual([c["codigo"] for c in kit["chegadas"]], [chegando.pk])
        self.assertEqual([s["quarto"] for s in kit["saidas"]], [saindo.uh.numero])
        self.assertEqual([c["codigo"] for c in kit["chegadas_amanha"]], [amanha.pk])
        # A saída de hoje também segue listada como hospedada (ainda está em casa).
        em_casa = {h["quarto"]: h for h in kit["hospedados"]}
        self.assertTrue(em_casa["K1"]["saida_hoje"])
        self.assertFalse(em_casa["K1"]["saida_atrasada"])

    def test_saida_vencida_vem_marcada(self):
        self.hospedar(dias=1, offset=-3)  # devia ter saído há 2 dias
        kit = services.kit_contingencia()
        self.assertTrue(kit["saidas"][0]["atrasada"])
        self.assertTrue(kit["hospedados"][0]["saida_atrasada"])

    def test_chegada_mostra_telefone_total_e_o_que_foi_pago(self):
        r = self.reserva(dias=2)
        SessaoCaixa.objects.create(
            operador=self.usuario, modulo="reservas", fundo_troco=Decimal("0.00")
        )
        services.receber_adiantamento(r, self.usuario, self.dinheiro, Decimal("200.00"))
        chegada = services.kit_contingencia()["chegadas"][0]
        self.assertEqual(chegada["telefone"], "(49) 90000-0001")
        self.assertEqual(chegada["total"], r.total_previsto())
        self.assertEqual(chegada["pago"], Decimal("200.00"))
        self.assertEqual(chegada["noites"], 2)

    def test_cancelada_e_no_show_ficam_fora(self):
        cancelada = self.reserva()
        cancelada.cancelar(self.usuario, "Hóspede desistiu")
        no_show = self.reserva(uh=self.quarto("K2"))
        no_show.marcar_no_show(self.usuario)
        orcamento = self.reserva(uh=self.quarto("K3"), status=Reserva.Status.ORCAMENTO)

        kit = services.kit_contingencia()
        codigos = [c["codigo"] for c in kit["chegadas"] + kit["chegadas_amanha"]]
        self.assertNotIn(cancelada.pk, codigos)
        self.assertNotIn(no_show.pk, codigos)
        # Orçamento é cotação: não segura quarto, não é chegada prevista.
        self.assertNotIn(orcamento.pk, codigos)
        self.assertEqual(kit["hospedados"], [])

    def test_day_use_vazio_nao_lista(self):
        tipo_day = TipoUH.objects.create(
            nome="Dia na Pousada Kit", tarifa_base=Decimal("90.00"),
            modalidade=TipoUH.Modalidade.DAY_USE, preco_day_use=Decimal("90.00"),
        )
        UH.objects.create(numero="DAYK-01", tipo=tipo_day)
        quartos = services.kit_contingencia()["quartos"]
        self.assertNotIn("DAYK-01", [q["numero"] for q in quartos])

        # Com gente dentro hoje, ele aparece — a recepção precisa saber.
        day = UH.objects.get(numero="DAYK-01")
        r = Reserva.objects.create(
            uh=day, hospede=self.hospede, checkin=self.hoje,
            checkout=self.hoje + timedelta(days=1), status=Reserva.Status.CONFIRMADA,
            valor_diaria=Decimal("90.00"), criado_por=self.usuario,
        )
        # Registro histórico: novas entradas nesse modelo estão bloqueadas.
        Reserva.objects.filter(pk=r.pk).update(status=Reserva.Status.HOSPEDADA)
        from apps.reservas.models import ContaHospedagem
        ContaHospedagem.objects.create(reserva=r)
        quartos = services.kit_contingencia()["quartos"]
        linha = [q for q in quartos if q["numero"] == "DAYK-01"]
        self.assertEqual(len(linha), 1)
        self.assertTrue(linha[0]["day_use"])
        self.assertEqual(linha[0]["situacao"], "ocupada")

    def test_quarto_bloqueado_aparece_como_bloqueado(self):
        self.quarto("K9", status=UH.Status.BLOQUEADA)
        por_numero = {q["numero"]: q for q in services.kit_contingencia()["quartos"]}
        self.assertEqual(por_numero["K9"]["situacao"], "bloqueada")
        self.assertEqual(por_numero["K1"]["situacao"], "livre")

    def test_com_governanca_a_limpeza_entra(self):
        from apps.governanca.models import StatusLimpeza
        from apps.governanca.services import definir_status

        definir_status(self.uh, StatusLimpeza.Situacao.SUJA, self.usuario)
        kit = services.kit_contingencia()
        self.assertTrue(kit["mostrar_limpeza"])
        por_numero = {q["numero"]: q for q in kit["quartos"]}
        self.assertEqual(por_numero["K1"]["limpeza"], "Sujo")
        self.assertEqual(por_numero["K1"]["situacao"], "a_limpar")

    def test_sem_governanca_a_coluna_de_limpeza_some(self):
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        kit = services.kit_contingencia()
        self.assertFalse(kit["mostrar_limpeza"])
        self.assertEqual({q["limpeza"] for q in kit["quartos"]}, {""})

    def test_consultas_nao_crescem_com_o_numero_de_reservas(self):
        """2 ou 10 reservas: o mesmo número de consultas (a folha é um retrato, não
        um laço). Com as taxas LIGADAS, que é o caminho de produção."""
        def consultas():
            with CaptureQueriesContext(connection) as ctx:
                services.kit_contingencia()
            return len(ctx.captured_queries)

        for n in range(2):
            self.hospedar(uh=self.quarto(f"P{n}"), dias=4)
            self.reserva(uh=self.quarto(f"C{n}"))
        with override_settings(PRECO_TAXAS_ATIVAS=True):
            consultas()          # aquece (nada de cache aqui, mas evita surpresa)
            com_duas = consultas()
            for n in range(2, 10):
                self.hospedar(uh=self.quarto(f"P{n}"), dias=4)
                self.reserva(uh=self.quarto(f"C{n}"))
            com_dez = consultas()
        self.assertEqual(com_duas, com_dez)


class KitPaginaTests(KitBase):
    def test_pagina_sai_com_as_secoes_e_os_dados(self):
        r = self.hospedar(dias=2)
        services.lancar_na_conta(
            r.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Refrigerante", Decimal("9.00"), self.usuario,
        )
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("reservas:kit"))
        self.assertEqual(resposta.status_code, 200)
        html = resposta.content.decode()
        for titulo in ("Kit de contingência", "Hospedados agora", "Chegadas de hoje",
                       "Saídas de hoje", "Situação dos quartos", "Chegadas de amanhã"):
            self.assertIn(titulo, html)
        self.assertIn("Maria Kit", html)
        self.assertIn("R$ 609,00", html)          # 2 × 300 + 9,00
        self.assertIn("Limpeza", html)            # Governança ativa → coluna existe
        self.assertIn("window.print()", html)     # botão Imprimir
        # Sem sidebar no papel: as regras de impressão são do app.css, não do template.
        self.assertIn("kit-folha", html)

    def test_pagina_sem_governanca_nao_quebra_e_perde_a_coluna(self):
        self.hospedar()
        ModuloContratado.objects.filter(codigo=Modulo.GOVERNANCA).update(ativo=False)
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("reservas:kit"))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotIn("<th>Limpeza</th>", resposta.content.decode())

    def test_pagina_vazia_nao_quebra(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("reservas:kit"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Nenhum hóspede em casa.", resposta.content.decode())

    def test_sem_o_modulo_atribuido_da_403(self):
        Usuario.objects.create_user(username="sem-acesso", password="senha-forte-123")
        self.client.login(username="sem-acesso", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("reservas:kit")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("reservas:kit")).status_code, 404)

    def test_link_no_cabecalho_da_lista_e_do_mapa_de_quartos(self):
        self.client.force_login(self.usuario)
        destino = reverse("reservas:kit")
        for tela in ("reservas:lista", "reservas:mapa_quartos"):
            self.assertIn(destino, self.client.get(reverse(tela)).content.decode(), tela)


class KitEmailTests(KitBase):
    @override_settings(KIT_CONTINGENCIA_EMAILS=[])
    def test_sem_variavel_nao_envia_nada(self):
        self.hospedar()
        call_command("enviar_kit_contingencia")
        self.assertEqual(mail.outbox, [])

    @override_settings(KIT_CONTINGENCIA_EMAILS=["gerencia@exemplo.com.br",
                                                "recepcao@exemplo.com.br"])
    def test_envia_para_os_enderecos_configurados(self):
        r = self.hospedar(dias=2)
        services.lancar_na_conta(
            r.conta, LancamentoConta.Tipo.CONSUMO, NaturezaFiscal.CONSUMO,
            "Água", Decimal("6.00"), self.usuario,
        )
        call_command("enviar_kit_contingencia")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["gerencia@exemplo.com.br", "recepcao@exemplo.com.br"])
        self.assertIn("Kit de contingência", msg.subject)
        self.assertIn("Maria Kit", msg.body)             # texto puro
        self.assertIn("R$ 606,00", msg.body)
        html = msg.alternatives[0][0]
        self.assertIn("Hospedados agora", html)
        self.assertIn("Maria Kit", html)

    @override_settings(KIT_CONTINGENCIA_EMAILS=[])
    def test_para_na_linha_de_comando_vence_o_settings(self):
        call_command("enviar_kit_contingencia", "--para", "eu@exemplo.com.br")
        self.assertEqual(mail.outbox[0].to, ["eu@exemplo.com.br"])

    @override_settings(KIT_CONTINGENCIA_EMAILS=["gerencia@exemplo.com.br"])
    def test_modulo_reservas_inativo_nao_envia(self):
        ModuloContratado.objects.filter(codigo=Modulo.RESERVAS).update(ativo=False)
        call_command("enviar_kit_contingencia")
        self.assertEqual(mail.outbox, [])

    @override_settings(KIT_CONTINGENCIA_EMAILS=["gerencia@exemplo.com.br"])
    def test_html_do_email_nao_depende_de_css_externo(self):
        """Cliente de e-mail ignora folha externa: o estilo vai inline."""
        self.hospedar()
        call_command("enviar_kit_contingencia")
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<link", html)
        self.assertNotIn(".css", html)
        self.assertIn('style="', html)

    def test_a_rotina_diaria_chama_o_comando(self):
        from apps.nucleo.management.commands.rotinas import GRUPOS

        self.assertIn("enviar_kit_contingencia", GRUPOS["diarias"])
