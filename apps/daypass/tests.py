import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    FormaPagamento,
    LocalEstoque,
    ModuloContratado,
    Pessoa,
    SessaoCaixa,
    TipoUH,
    estornar_movimento,
)
from apps.reservas.models import Reserva

from . import services
from .models import TurnoDayPass, VisitaDayPass


class DadosDayPass:
    def setUp(self):
        super().setUp()
        self.op = get_user_model().objects.create_superuser(username="daypass-gerente", password="qa-daypass")
        self.pessoa = Pessoa.objects.create(nome="Visitante QA")
        self.dia = timezone.localdate() + timedelta(days=1)
        for codigo in ("reservas", "restaurante"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        self.turno = TurnoDayPass(dia_id=self.dia, nome="Manhã QA", inicio=time(9), fim=time(13), capacidade=3, contar_hospedes=True, preco_adulto="50", preco_crianca="25", preco_hospede="0", ativo=True)
        services.salvar_turno(self.turno, self.op)

    def reservar(self, **kwargs):
        dados = dict(turno=self.turno, responsavel=self.pessoa, adultos=[self.pessoa.nome], criancas=[], usuario=self.op, chave=uuid.uuid4())
        dados.update(kwargs)
        return services.reservar(**dados)

    def horario(self, hora=10):
        return patch("apps.daypass.services.timezone.localtime", return_value=timezone.make_aware(datetime.combine(self.dia, time(hora))))

    def caixa(self):
        self.sessao = SessaoCaixa.objects.create(operador=self.op, modulo="reservas")
        self.forma = FormaPagamento.objects.create(nome="Dinheiro daypass QA", tipo="dinheiro")


class DayPassTests(DadosDayPass, TestCase):
    def test_lotacao_por_pessoa_preco_e_idempotencia(self):
        chave = uuid.uuid4()
        visita = self.reservar(adultos=[self.pessoa.nome, "Acompanhante QA"], criancas=["Criança QA"], chave=chave)
        self.assertEqual(visita.valor_ingressos, Decimal("125.00"))
        self.assertEqual(visita.vagas, 3)
        self.assertEqual(visita.visitantes.count(), 3)
        self.assertEqual(self.reservar(adultos=[self.pessoa.nome, "Acompanhante QA"], criancas=["Criança QA"], chave=chave).pk, visita.pk)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            self.reservar(chave=chave)
        with self.assertRaisesMessage(ValidationError, "vagas suficientes"):
            self.reservar()
        self.assertEqual(VisitaDayPass.objects.count(), 1)

    def test_turno_pausado_ou_fora_do_horario_nao_vende(self):
        self.turno.ativo = False
        services.salvar_turno(self.turno, self.op)
        with self.assertRaises(ValidationError):
            self.reservar()
        self.turno.ativo = True
        services.salvar_turno(self.turno, self.op)
        with self.horario(14), self.assertRaisesMessage(ValidationError, "já terminou"):
            self.reservar()

    def test_configuracao_impede_sobreposicao_e_reducao_de_vagas(self):
        outro = TurnoDayPass(dia_id=self.dia, nome="Conflitante", inicio=time(12), fim=time(16), capacidade=1, contar_hospedes=False, preco_adulto=0, preco_crianca=0)
        with self.assertRaisesMessage(ValidationError, "sobreporem"):
            services.salvar_turno(outro, self.op)
        self.reservar(adultos=[self.pessoa.nome, "Segundo QA"])
        self.turno.capacidade = 1
        with self.assertRaisesMessage(ValidationError, "abaixo"):
            services.salvar_turno(self.turno, self.op)
        self.turno.capacidade = 3
        self.turno.contar_hospedes = False
        with self.assertRaisesMessage(ValidationError, "Preserve"):
            services.salvar_turno(self.turno, self.op)

    def test_configuracao_sem_numeros_nao_oferece_venda_legada(self):
        TurnoDayPass.objects.all().delete()
        self.client.force_login(self.op)
        r = self.client.get(reverse("daypass:painel"))
        self.assertContains(r, "Nenhum turno configurado")
        self.assertContains(self.client.get(reverse("daypass_publico")), "Agenda em preparação")
        self.assertRedirects(self.client.get(reverse("core:reservar"), {"modalidade": "day_use"}), reverse("daypass_publico"))
        tipo = TipoUH.objects.create(nome="Day use legado QA", modalidade="day_use", tarifa_base=50)
        uh = UH.objects.create(tipo=tipo, numero="DAY-QA")
        from apps.reservas.services import criar_prereserva
        with self.assertRaisesMessage(ValidationError, "Day pass"):
            criar_prereserva(uh=uh, checkin=self.dia, checkout=self.dia+timedelta(days=1), hospede=self.pessoa, usuario=self.op)
        legado = Reserva.objects.create(uh=uh, hospede=self.pessoa, checkin=self.dia, checkout=self.dia+timedelta(days=1), valor_diaria=100, criado_por=self.op)
        with self.assertRaisesMessage(ValidationError, "Day pass"):
            legado.confirmar(self.op)
        with self.assertRaisesMessage(ValidationError, "Day pass"):
            legado.fazer_checkin(self.op)

    def test_recebimento_saida_e_comanda_formam_ciclo_completo(self):
        self.caixa()
        visita = self.reservar(criancas=["Criança QA"])
        pessoa = visita.visitantes.first()
        with self.horario(), self.assertRaisesMessage(ValidationError, "Receba"):
            services.registrar_entrada(pessoa, self.op)
        chave = uuid.uuid4()
        pagamento = services.receber(visita, self.op, self.forma, 75, chave)
        self.assertEqual(services.receber(visita, self.op, self.forma, 75, chave).pk, pagamento.pk)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            services.receber(visita, self.op, self.forma, 50, chave)
        self.assertEqual(visita.total_pago(), Decimal("75"))
        with self.horario():
            for visitante in visita.visitantes.all():
                services.registrar_entrada(visitante, self.op)
        with self.horario(), self.assertRaisesMessage(ValidationError, "já foi registrada"):
            services.registrar_entrada(pessoa, self.op)
        self.assertEqual(services.ocupacao(self.turno)["presentes"], 2)
        local = LocalEstoque.objects.create(nome="Piscina daypass QA", modulo="restaurante")
        comanda = services.abrir_consumo(visita, self.op, local)
        self.assertEqual(services.abrir_consumo(visita, self.op, local).pk, comanda.pk)
        self.assertIsNone(comanda.conta_id)
        for visitante in visita.visitantes.all():
            services.registrar_saida(visitante, self.op)
        self.assertEqual(services.ocupacao(self.turno)["presentes"], 0)
        with self.assertRaisesMessage(ValidationError, "comandas abertas"):
            services.encerrar(visita, self.op)
        from apps.restaurante.services import cancelar_comanda
        cancelar_comanda(comanda, self.op, "Nenhum consumo realizado")
        services.encerrar(visita, self.op)
        visita.refresh_from_db()
        self.assertEqual(visita.status, "encerrada")
        self.assertEqual(services.ocupacao(self.turno)["disponiveis"], 1)

    def test_cancelamento_exige_estorno_real_no_caixa(self):
        self.caixa()
        visita = self.reservar()
        pg = services.receber(visita, self.op, self.forma, 50, uuid.uuid4())
        with self.assertRaisesMessage(ValidationError, "estorno no caixa"):
            services.cancelar(visita, self.op, "Desistência informada")
        estornar_movimento(pg.movimento, self.sessao, self.op, "Devolução realizada")
        self.assertEqual(visita.total_pago(), 0)
        services.cancelar(visita, self.op, "Desistência informada")
        self.assertEqual(services.ocupacao(self.turno)["disponiveis"], 3)
        with self.assertRaises(ValidationError):
            services.cancelar(visita, self.op, "Reenvio duplicado")

    def test_hospedes_contam_conforme_regra_e_exigem_estadia(self):
        tipo = TipoUH.objects.create(nome="Quarto daypass QA", modalidade="hospedagem", tarifa_base=100)
        uh = UH.objects.create(tipo=tipo, numero="DP-QA")
        hospedagem = Reserva.objects.create(uh=uh, hospede=self.pessoa, checkin=self.dia, checkout=self.dia+timedelta(days=1), valor_diaria=100, criado_por=self.op, status="confirmada", adultos=2)
        visita = self.reservar(hospedagem=hospedagem)
        self.assertEqual(visita.vagas, 1)
        self.assertEqual(visita.valor_ingressos, 0)
        with self.horario(), self.assertRaisesMessage(ValidationError, "check-in"):
            services.registrar_entrada(visita.visitantes.first(), self.op)
        with self.assertRaisesMessage(ValidationError, "já tem um grupo"):
            self.reservar(hospedagem=hospedagem)
        services.cancelar(visita, self.op, "Nova programação")
        self.turno.contar_hospedes = False
        # A regra não muda depois de uma reserva; outro turno tem configuração própria.
        self.turno.pk = None
        self.turno.inicio, self.turno.fim = time(14), time(18)
        services.salvar_turno(self.turno, self.op)
        self.assertEqual(self.reservar(hospedagem=hospedagem).vagas, 0)

    def test_formularios_rotas_e_dados_invalidos(self):
        self.client.force_login(self.op)
        visita = self.reservar()
        for url in (reverse("daypass:painel"), reverse("daypass:turno_novo"), reverse("daypass:turno", args=[self.turno.pk]), reverse("daypass:nova_visita", args=[self.turno.pk]), reverse("daypass:visita", args=[visita.pk]), reverse("daypass_publico")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(reverse("daypass:turno_novo"), {"nome": "Inválido", "data": "data-errada", "capacidade": "Infinity"})
        self.assertEqual(r.status_code, 200)
        for campo in ("data", "capacidade"):
            self.assertIn(campo, r.context["form"].errors)
            for erro in r.context["form"].errors[campo]:
                self.assertContains(r, erro)
        self.assertContains(r, 'value="Inválido"')
        self.assertFalse(TurnoDayPass.objects.filter(nome="Inválido").exists())
        self.assertEqual(self.client.get(reverse("daypass:acao", args=[visita.pk, "cancelar"])).status_code, 405)
        comum = get_user_model().objects.create_user(username="daypass-sem-acesso")
        self.client.force_login(comum)
        self.assertEqual(self.client.get(reverse("daypass:painel")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            services.salvar_turno(self.turno, comum)


class ConcorrenciaDayPassTests(DadosDayPass, TransactionTestCase):
    def _ao_mesmo_tempo(self, operacoes):
        barreira = Barrier(len(operacoes))
        def executar(operacao):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return operacao().pk
            except ValidationError:
                return None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(operacoes)) as executor:
            return list(executor.map(executar, operacoes))

    def _outro_turno(self):
        outro = TurnoDayPass(dia_id=self.dia+timedelta(days=1), nome="Outro dia QA",
            inicio=time(9), fim=time(13), capacidade=3, contar_hospedes=True,
            preco_adulto=50, preco_crianca=25, ativo=True)
        services.salvar_turno(outro, self.op)
        return outro

    def test_mesmo_envio_em_dias_distintos_recusa_sem_erro_de_banco(self):
        outro, chave = self._outro_turno(), uuid.uuid4()
        resultados = self._ao_mesmo_tempo([
            lambda: self.reservar(chave=chave),
            lambda: self.reservar(turno=outro, chave=chave)])
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual(VisitaDayPass.objects.count(), 1)

    def test_pagamento_repetido_em_duas_recepcoes_nao_duplica_caixa(self):
        self.caixa()
        visita, chave = self.reservar(), uuid.uuid4()
        resultados = self._ao_mesmo_tempo([
            lambda: services.receber(visita, self.op, self.forma, 50, chave),
            lambda: services.receber(visita, self.op, self.forma, 50, chave)])
        self.assertEqual(len(set(resultados)), 1)
        self.assertNotIn(None, resultados)
        self.assertEqual(visita.total_pago(), Decimal('50'))
        self.assertEqual(visita.pagamentos.count(), 1)

    def test_chave_de_pagamento_repetida_em_dias_distintos_reverte_segunda_entrada(self):
        self.caixa()
        primeira = self.reservar()
        segunda = self.reservar(turno=self._outro_turno())
        chave = uuid.uuid4()
        resultados = self._ao_mesmo_tempo([
            lambda: services.receber(primeira, self.op, self.forma, 50, chave),
            lambda: services.receber(segunda, self.op, self.forma, 50, chave)])
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual(primeira.total_pago()+segunda.total_pago(), Decimal('50'))
        from apps.nucleo.models import MovimentoCaixa
        self.assertEqual(MovimentoCaixa.objects.filter(sessao=self.sessao).count(), 1)

    def test_duas_recepcoes_disputam_a_ultima_vaga(self):
        self.turno.capacidade = 1
        services.salvar_turno(self.turno, self.op)
        barreira = Barrier(2)
        def reservar():
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                return self.reservar().pk
            except ValidationError:
                return None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: reservar(), range(2)))
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual(VisitaDayPass.objects.count(), 1)
        self.assertEqual(services.ocupacao(self.turno)["disponiveis"], 0)
