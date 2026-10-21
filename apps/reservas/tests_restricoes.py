"""
Restrições de venda — estadia mínima, fechado para chegada/saída, parada de vendas.

Regra de disponibilidade nesta casa é sempre testada. Cada caso aqui é uma venda que
hoje escaparia: a noite solta do 31/12, a saída no meio do feriado, a regra de um tipo
pegando outro. A semântica está no docstring de `RestricaoVenda`.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.nucleo.areas import Area
from apps.nucleo.models import UH, ModuloContratado, Pessoa, TipoUH, TrilhaAuditoria
from apps.nucleo.modulos import Modulo

from . import services
from .models import Reserva, RestricaoVenda

Usuario = get_user_model()


@override_settings(FNRH_BLOQUEAR_CHECKIN=False)
class RestricaoBase(TestCase):
    """Um Réveillon de mentira: as noites 29/12, 30/12, 31/12 e 01/01 do próximo ano."""

    def setUp(self):
        from apps.nucleo.models import ConfiguracaoReservas
        ConfiguracaoReservas.objects.update_or_create(
            pk=1, defaults={"feriados_automaticos": False}
        )
        self.usuario = Usuario.objects.create_superuser(
            username="gerencia-restr", password="senha-forte-123"
        )
        self.tipo = TipoUH.objects.create(
            nome="Cabana Restr", tarifa_base=Decimal("300.00"), capacidade=4
        )
        self.outro_tipo = TipoUH.objects.create(
            nome="Chalé Restr", tarifa_base=Decimal("400.00"), capacidade=4
        )
        self.uh = UH.objects.create(numero="R1", tipo=self.tipo)
        self.uh2 = UH.objects.create(numero="R2", tipo=self.tipo)
        self.uh_outro = UH.objects.create(numero="R3", tipo=self.outro_tipo)
        self.hospede = Pessoa.objects.create(nome="Hóspede Restrição")
        # Datas fixas e longe de hoje: a regra é de calendário, não de "hoje + n".
        ano = date.today().year + 1
        self.n29 = date(ano - 1, 12, 29)   # primeira noite do intervalo
        self.n01 = date(ano, 1, 1)         # última noite do intervalo
        self.d02 = date(ano, 1, 2)         # dia seguinte à última noite (saída livre)

    def regra(self, **campos):
        padrao = {
            "descricao": "Réveillon", "inicio": self.n29, "fim": self.n01,
            "criado_por": self.usuario,
        }
        padrao.update(campos)
        return RestricaoVenda.objects.create(**padrao)

    def violacoes(self, checkin, checkout, **escopo):
        return services.restricoes_da_estadia(checkin, checkout, **escopo)

    def tipos(self, checkin, checkout, **escopo):
        return [v["tipo"] for v in self.violacoes(checkin, checkout, **escopo)]


class EstadiaMinimaTests(RestricaoBase):
    """`min_noites` é "min stay through": basta UMA noite da estadia cair no intervalo."""

    def test_noite_solta_no_meio_do_intervalo_e_barrada(self):
        self.regra(min_noites=3)
        # Só a noite de 31/12 — o caso que hoje vende e deixa as noites ao redor vazias.
        entrada = date(self.n01.year - 1, 12, 31)
        v = self.violacoes(entrada, self.n01, uh=self.uh)
        self.assertEqual([x["tipo"] for x in v], ["min_noites"])
        self.assertIn("estadia mínima é de 3 noites", v[0]["mensagem"])

    def test_estadia_longa_que_atravessa_o_intervalo_passa(self):
        self.regra(min_noites=3)
        entrada = date(self.n29.year, 12, 27)
        self.assertEqual(self.violacoes(entrada, self.d02, uh=self.uh), [])

    def test_estadia_que_so_toca_a_borda_tambem_conta(self):
        """Entrar antes e sair no primeiro dia do intervalo usa a noite de 28/12 e a de
        29/12: a de 29 está no intervalo, então o mínimo vale."""
        self.regra(min_noites=3)
        entrada = date(self.n29.year, 12, 28)
        saida = date(self.n29.year, 12, 30)      # noites 28 e 29 → 2 < 3
        self.assertEqual(self.tipos(entrada, saida, uh=self.uh), ["min_noites"])

    def test_estadia_inteira_fora_do_intervalo_nao_e_tocada(self):
        self.regra(min_noites=3)
        entrada = date(self.n29.year, 12, 20)
        self.assertEqual(self.violacoes(entrada, entrada + timedelta(days=1),
                                        uh=self.uh), [])

    def test_vale_o_maior_minimo_entre_as_regras(self):
        self.regra(descricao="Feriadão", min_noites=2)
        self.regra(descricao="Réveillon", min_noites=4)
        entrada = date(self.n29.year, 12, 30)
        v = self.violacoes(entrada, self.d02, uh=self.uh)   # 3 noites
        self.assertEqual([x["tipo"] for x in v], ["min_noites"])
        self.assertEqual(v[0]["regra"].min_noites, 4)
        self.assertEqual(v[0]["regra"].descricao, "Réveillon")
        # Uma violação só: duas mensagens de mínimo para a mesma estadia confundem.
        self.assertEqual(len(v), 1)

    def test_mensagem_sugere_a_data_de_saida_que_resolve(self):
        self.regra(min_noites=3)
        entrada = date(self.n01.year - 1, 12, 31)
        mensagem = self.violacoes(entrada, self.n01, uh=self.uh)[0]["mensagem"]
        self.assertIn("31/12", mensagem)
        self.assertIn("03/01", mensagem)   # 31/12 + 3 noites


class ChegadaESaidaFechadasTests(RestricaoBase):
    def test_chegada_fechada_barra_quem_entra_no_intervalo(self):
        self.regra(fechado_chegada=True)
        entrada = date(self.n01.year - 1, 12, 31)
        self.assertEqual(self.tipos(entrada, self.d02, uh=self.uh),
                         ["fechado_chegada"])

    def test_chegada_fechada_deixa_atravessar(self):
        """Quem já entrou antes do intervalo passa por dentro dele sem problema."""
        self.regra(fechado_chegada=True)
        entrada = date(self.n29.year, 12, 27)
        self.assertEqual(self.violacoes(entrada, self.d02, uh=self.uh), [])

    def test_chegada_no_dia_seguinte_ao_fim_do_intervalo_e_livre(self):
        self.regra(fechado_chegada=True)
        self.assertEqual(
            self.violacoes(self.d02, self.d02 + timedelta(days=2), uh=self.uh), [])

    def test_saida_fechada_barra_quem_sai_dentro_do_intervalo(self):
        """Sair em 01/01 deixa a noite de 01/01 vaga — é o que a regra evita."""
        self.regra(fechado_saida=True)
        entrada = date(self.n29.year, 12, 27)
        self.assertEqual(self.tipos(entrada, self.n01, uh=self.uh), ["fechado_saida"])

    def test_saida_no_dia_seguinte_ao_fim_do_intervalo_e_permitida(self):
        """A fronteira do off-by-one: a saída é o dia SEGUINTE à última noite, então
        sair em 02/01 vendeu a noite de 01/01 e está liberado."""
        self.regra(fechado_saida=True)
        entrada = date(self.n29.year, 12, 27)
        self.assertEqual(self.violacoes(entrada, self.d02, uh=self.uh), [])

    def test_saida_no_primeiro_dia_do_intervalo_e_barrada(self):
        self.regra(fechado_saida=True)
        entrada = date(self.n29.year, 12, 26)
        self.assertEqual(self.tipos(entrada, self.n29, uh=self.uh), ["fechado_saida"])


class PararVendasTests(RestricaoBase):
    def test_casa_inteira_barra_qualquer_quarto(self):
        self.regra(parar_vendas=True)
        for uh in (self.uh, self.uh2, self.uh_outro):
            self.assertEqual(self.tipos(self.n29, self.d02, uh=uh), ["parar_vendas"],
                             uh.numero)

    def test_escopo_de_tipo_nao_pega_outro_tipo(self):
        self.regra(parar_vendas=True, tipo_uh=self.tipo)
        self.assertEqual(self.tipos(self.n29, self.d02, uh=self.uh), ["parar_vendas"])
        self.assertEqual(self.violacoes(self.n29, self.d02, uh=self.uh_outro), [])
        # E pela consulta por TIPO (venda por tipo / day use), o mesmo.
        self.assertEqual(self.tipos(self.n29, self.d02, tipo_uh=self.tipo),
                         ["parar_vendas"])
        self.assertEqual(self.violacoes(self.n29, self.d02, tipo_uh=self.outro_tipo), [])

    def test_escopo_de_quarto_nao_pega_o_vizinho(self):
        self.regra(parar_vendas=True, uh=self.uh)
        self.assertEqual(self.tipos(self.n29, self.d02, uh=self.uh), ["parar_vendas"])
        self.assertEqual(self.violacoes(self.n29, self.d02, uh=self.uh2), [])

    def test_regra_de_quarto_nao_barra_a_consulta_por_tipo(self):
        """Vender "qualquer quarto do tipo" com UM quarto bloqueado continua possível:
        a trava daquela unidade é conferida quando o quarto é escolhido."""
        self.regra(parar_vendas=True, uh=self.uh)
        self.assertEqual(self.violacoes(self.n29, self.d02, tipo_uh=self.tipo), [])

    def test_fora_do_intervalo_nao_barra(self):
        self.regra(parar_vendas=True)
        self.assertEqual(
            self.violacoes(self.d02, self.d02 + timedelta(days=2), uh=self.uh), [])


class RegraInativaTests(RestricaoBase):
    def test_regra_desativada_e_ignorada(self):
        regra = self.regra(min_noites=5, parar_vendas=True, ativa=False)
        self.assertEqual(self.violacoes(self.n29, self.d02, uh=self.uh), [])
        regra.ativa = True
        regra.save(update_fields=["ativa"])
        self.assertTrue(self.violacoes(self.n29, self.d02, uh=self.uh))


class DayUseTests(RestricaoBase):
    """Dia na Pousada não tem noite: estadia mínima e chegada/saída não se aplicam, e
    regra de casa inteira não o atinge — só a que aponta o tipo/unidade de day use."""

    def setUp(self):
        super().setUp()
        self.tipo_day = TipoUH.objects.create(
            nome="Dia na Pousada Restr", tarifa_base=Decimal("120.00"),
            modalidade=TipoUH.Modalidade.DAY_USE, capacidade=4,
        )
        self.uh_day = UH.objects.create(numero="DAY-R1", tipo=self.tipo_day)
        self.saida_day = self.n29 + timedelta(days=1)   # day use = um dia só

    def test_estadia_minima_nao_vale_para_day_use(self):
        self.regra(min_noites=3)
        self.assertEqual(
            self.violacoes(self.n29, self.saida_day, uh=self.uh_day), [])

    def test_chegada_e_saida_fechadas_nao_valem_para_day_use(self):
        self.regra(fechado_chegada=True, fechado_saida=True)
        self.assertEqual(
            self.violacoes(self.n29, self.saida_day, uh=self.uh_day), [])

    def test_parar_vendas_de_casa_inteira_nao_atinge_day_use(self):
        self.regra(parar_vendas=True)
        self.assertEqual(
            self.violacoes(self.n29, self.saida_day, uh=self.uh_day), [])
        # Mas a hospedagem no mesmo dia continua barrada.
        self.assertEqual(self.tipos(self.n29, self.d02, uh=self.uh), ["parar_vendas"])

    def test_parar_vendas_com_escopo_do_day_use_barra(self):
        self.regra(parar_vendas=True, tipo_uh=self.tipo_day)
        self.assertEqual(self.tipos(self.n29, self.saida_day, uh=self.uh_day),
                         ["parar_vendas"])
        self.assertEqual(self.tipos(self.n29, self.saida_day, tipo_uh=self.tipo_day),
                         ["parar_vendas"])


class ModeloRestricaoTests(RestricaoBase):
    def test_escopo_duplo_nao_entra_no_banco(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RestricaoVenda.objects.create(
                    descricao="Errada", inicio=self.n29, fim=self.n01,
                    tipo_uh=self.tipo, uh=self.uh, parar_vendas=True,
                )

    def test_fim_antes_do_inicio_nao_entra_no_banco(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RestricaoVenda.objects.create(
                    descricao="Invertida", inicio=self.n01, fim=self.n29,
                    parar_vendas=True,
                )

    def test_clean_exige_ao_menos_uma_regra(self):
        regra = RestricaoVenda(descricao="Vazia", inicio=self.n29, fim=self.n01)
        with self.assertRaises(ValidationError):
            regra.clean()

    def test_clean_recusa_escopo_duplo_antes_do_banco(self):
        regra = RestricaoVenda(descricao="Dupla", inicio=self.n29, fim=self.n01,
                               tipo_uh=self.tipo, uh=self.uh, parar_vendas=True)
        with self.assertRaises(ValidationError):
            regra.clean()

    def test_escopo_em_texto(self):
        self.assertEqual(self.regra(parar_vendas=True).escopo, "Casa inteira")
        self.assertEqual(
            self.regra(parar_vendas=True, tipo_uh=self.tipo).escopo, self.tipo.nome)
        self.assertEqual(
            self.regra(parar_vendas=True, uh=self.uh).escopo, f"Quarto {self.uh.numero}")

    def test_regras_em_texto(self):
        regra = self.regra(min_noites=3, fechado_chegada=True, parar_vendas=True)
        self.assertEqual(regra.regras,
                         ["mínimo 3 noites", "sem chegada", "vendas paradas"])

    def test_auditoria_automatica_registra_a_criacao(self):
        """Nada de `registrar_auditoria` à mão: o signal da auto-auditoria pega."""
        self.client.force_login(self.usuario)
        self.client.post(reverse("reservas:restricao_nova"), {
            "descricao": "Réveillon", "inicio": self.n29.isoformat(),
            "fim": self.n01.isoformat(), "min_noites": 3, "ativa": "on",
        })
        regra = RestricaoVenda.objects.get()
        self.assertTrue(TrilhaAuditoria.objects.filter(
            alvo="RestricaoVenda", alvo_id=str(regra.pk), acao="criar").exists())


class PreReservaRespeitaRestricaoTests(RestricaoBase):
    """A trava do canal direto: `criar_prereserva` com canal de autoatendimento recusa;
    canal interno (balcão, Comercial) passa, porque lá a regra é aviso."""

    def test_canal_site_e_recusado_com_o_motivo(self):
        self.regra(min_noites=3)
        entrada = date(self.n01.year - 1, 12, 31)
        with self.assertRaises(ValidationError) as ctx:
            services.criar_reserva_site_unidade(
                uh=self.uh, checkin=entrada, checkout=self.n01,
                hospede=self.hospede, usuario=self.usuario,
            )
        self.assertIn("estadia mínima", " ".join(ctx.exception.messages))
        self.assertEqual(Reserva.objects.count(), 0)

    def test_canal_site_por_tipo_tambem_e_recusado(self):
        self.regra(min_noites=3, tipo_uh=self.tipo)
        entrada = date(self.n01.year - 1, 12, 31)
        with self.assertRaises(ValidationError):
            services.criar_reserva_site(
                tipo_uh=self.tipo, checkin=entrada, checkout=self.n01,
                hospede=self.hospede, usuario=self.usuario,
            )

    def test_canal_balcao_passa(self):
        self.regra(min_noites=3)
        entrada = date(self.n01.year - 1, 12, 31)
        reserva = services.criar_prereserva(
            uh=self.uh, checkin=entrada, checkout=self.n01,
            hospede=self.hospede, usuario=self.usuario,
        )
        self.assertEqual(reserva.canal, Reserva.Canal.BALCAO)

    def test_flag_explicita_vence_o_canal(self):
        self.regra(min_noites=3)
        entrada = date(self.n01.year - 1, 12, 31)
        with self.assertRaises(ValidationError):
            services.criar_prereserva(
                uh=self.uh, checkin=entrada, checkout=self.n01,
                hospede=self.hospede, usuario=self.usuario,
                respeitar_restricoes=True,
            )
        # E ao contrário: o Comercial converte um lead que VEIO do site (canal "site")
        # e isso é venda negociada — a regra não pode travar a conversão.
        reserva = services.criar_prereserva(
            uh=self.uh, checkin=entrada, checkout=self.n01,
            hospede=self.hospede, usuario=self.usuario,
            canal=Reserva.Canal.SITE, respeitar_restricoes=False,
        )
        self.assertEqual(reserva.canal, Reserva.Canal.SITE)

    def test_alocacao_por_tipo_pula_o_quarto_bloqueado(self):
        """Regra apontando um quarto só: o canal direto aloca o vizinho, não recusa."""
        self.regra(parar_vendas=True, uh=self.uh)
        reserva = services.criar_reserva_site(
            tipo_uh=self.tipo, checkin=self.n29, checkout=self.d02,
            hospede=self.hospede, usuario=self.usuario,
        )
        self.assertEqual(reserva.uh, self.uh2)


class RecepcaoAvisaMasNaoBarraTests(RestricaoBase):
    """Na recepção a regra é aviso — quem atende negocia. Só "parar vendas" barra, e
    nem para a gerência: ela passa, e a trilha guarda."""

    def operador(self):
        usuario = Usuario.objects.create_user(
            username="recepcao-restr", password="senha-forte-123")
        usuario.modulos.add(ModuloContratado.objects.get(codigo=Modulo.RESERVAS))
        return usuario

    def _post(self, usuario, **extra):
        self.client.force_login(usuario)
        dados = {
            "hospede": self.hospede.pk, "uh": self.uh.pk,
            "checkin": date(self.n01.year - 1, 12, 31).isoformat(),
            "checkout": self.n01.isoformat(),
            "adultos": 2, "criancas": 0, "canal": "balcao",
            "faturamento": "particular", "observacoes": "",
            "cobra_iss": "on", "cobra_taxa_turismo": "on",
        }
        dados.update(extra)
        dados = {k: v for k, v in dados.items() if v is not None}
        return self.client.post(reverse("reservas:nova"), dados, follow=True)

    def test_estadia_minima_vira_aviso_e_a_reserva_entra(self):
        self.regra(min_noites=3)
        resposta = self._post(self.operador())
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertContains(resposta, "estadia mínima é de 3 noites")

    def test_parar_vendas_barra_o_operador(self):
        self.regra(parar_vendas=True)
        resposta = self._post(self.operador())
        self.assertEqual(Reserva.objects.count(), 0)
        self.assertContains(resposta, "Só a gerência pode liberar")

    def test_parar_vendas_nao_barra_orcamento(self):
        """Orçamento é cotação: não prende data, então nem a parada de vendas o impede."""
        self.regra(parar_vendas=True)
        self._post(self.operador(), orcamento="1")
        self.assertEqual(Reserva.objects.get().status, Reserva.Status.ORCAMENTO)

    def test_gerencia_passa_e_fica_na_trilha(self):
        self.regra(parar_vendas=True)
        self._post(self.usuario)       # superusuário = gerência
        reserva = Reserva.objects.get()
        registro = TrilhaAuditoria.objects.get(acao="restricao_dispensada")
        self.assertEqual(registro.alvo, "Reserva")
        self.assertEqual(registro.alvo_id, str(reserva.pk))
        self.assertEqual(registro.usuario, self.usuario)
        self.assertIn("não estão abertas para venda", registro.detalhe["motivo"])

    def test_trilha_mostra_a_frase_em_portugues(self):
        from apps.auditoria.formatacao import frase
        self.regra(parar_vendas=True)
        self._post(self.usuario)
        registro = TrilhaAuditoria.objects.get(acao="restricao_dispensada")
        self.assertIn("Vendeu com as vendas paradas", frase(registro))

    def test_aviso_ao_vivo_no_modal(self):
        """A recepção lê o motivo antes de salvar (tarifa_preview alimenta o hint)."""
        self.regra(min_noites=3)
        self.client.force_login(self.usuario)
        entrada = date(self.n01.year - 1, 12, 31)
        resposta = self.client.get(reverse("reservas:tarifa_preview"), {
            "uh": self.uh.pk, "checkin": entrada.isoformat(),
            "checkout": self.n01.isoformat(), "adultos": 2,
        })
        dados = resposta.json()
        self.assertEqual([r["tipo"] for r in dados["restricoes"]], ["min_noites"])
        # E o modal tem onde mostrar.
        html = self.client.get(reverse("reservas:nova"),
                               headers={"hx-request": "true"}).content.decode()
        self.assertIn('id="restricao-hint"', html)


class TelaDeGestaoTests(RestricaoBase):
    def test_sem_a_area_temporadas_nao_entra(self):
        usuario = Usuario.objects.create_user(
            username="sem-area-restr", password="senha-forte-123")
        self.client.force_login(usuario)
        for nome, args in (("reservas:restricoes", []),
                           ("reservas:restricao_nova", []),
                           ("reservas:restricao_editar", [self.regra(min_noites=2).pk])):
            resposta = self.client.get(reverse(nome, args=args))
            self.assertEqual(resposta.status_code, 403, nome)

    def test_com_a_area_temporadas_entra(self):
        usuario = Usuario.objects.create_user(
            username="com-area-restr", password="senha-forte-123",
            areas=[Area.TEMPORADAS])
        self.client.force_login(usuario)
        self.regra(min_noites=3, parar_vendas=True)
        resposta = self.client.get(reverse("reservas:restricoes"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Réveillon")
        self.assertContains(resposta, "mínimo 3 noites")

    def test_cria_pela_tela_e_marca_quem_criou(self):
        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse("reservas:restricao_nova"), {
            "descricao": "Carnaval", "inicio": self.n29.isoformat(),
            "fim": self.n01.isoformat(), "min_noites": 4, "ativa": "on",
        })
        self.assertRedirects(resposta, reverse("reservas:restricoes"))
        regra = RestricaoVenda.objects.get()
        self.assertEqual(regra.min_noites, 4)
        self.assertEqual(regra.criado_por, self.usuario)

    def test_formulario_sem_regra_marcada_nao_salva(self):
        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse("reservas:restricao_nova"), {
            "descricao": "Nada", "inicio": self.n29.isoformat(),
            "fim": self.n01.isoformat(), "ativa": "on",
        })
        self.assertEqual(RestricaoVenda.objects.count(), 0)
        self.assertContains(resposta, "Marque ao menos uma regra")

    def test_desativar_e_reativar_pela_tela(self):
        regra = self.regra(parar_vendas=True)
        self.client.force_login(self.usuario)
        url = reverse("reservas:restricao_alternar", args=[regra.pk])
        self.client.post(url)
        regra.refresh_from_db()
        self.assertFalse(regra.ativa)
        self.client.post(url)
        regra.refresh_from_db()
        self.assertTrue(regra.ativa)

    def test_lista_poe_o_que_vale_na_frente(self):
        passada = self.regra(descricao="Réveillon passado", parar_vendas=True,
                             inicio=date(2024, 12, 29), fim=date(2025, 1, 1))
        futura = self.regra(descricao="Réveillon futuro", min_noites=3)
        self.client.force_login(self.usuario)
        html = self.client.get(reverse("reservas:restricoes")).content.decode()
        self.assertLess(html.index(futura.descricao), html.index(passada.descricao))
        self.assertIn("Encerrada", html)

    def test_link_a_partir_das_temporadas(self):
        self.client.force_login(self.usuario)
        html = self.client.get(reverse("temporadas")).content.decode()
        self.assertIn(reverse("reservas:restricoes"), html)
