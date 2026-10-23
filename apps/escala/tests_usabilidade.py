"""Entradas incompletas e solicitações envelhecidas não corrompem a escala."""

from datetime import time, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import Funcionario, ModuloContratado, Pessoa, Usuario

from . import services
from .models import Atribuicao, Ausencia, HoraExtra, SemanaPublicada, TrocaTurno, Turno


class EscalaEntradasUsabilidadeTests(TestCase):
    def setUp(self):
        cache.clear()
        ModuloContratado.objects.update_or_create(codigo="escala", defaults={"ativo": True})
        self.usuario = Usuario.objects.create_superuser(username="escala-uso", password="senha-qa")
        self.funcionarios = [Funcionario.objects.create(pessoa=Pessoa.objects.create(nome=f"Equipe fictícia {n}"), cargo="Recepção") for n in range(3)]
        self.turno = Turno.objects.create(nome="Turno fictício", inicio=time(8), fim=time(16))
        self.dia = timezone.localdate() + timedelta(days=7)
        self.client.force_login(self.usuario)
        self.client.raise_request_exception = False

    def post(self, rota, dados):
        return self.client.post(reverse(rota), dados, HTTP_X_FORM_PRESERVE="1")

    def test_ausencia_sem_data_nao_da_500(self):
        r = self.post("escala:ausencias", {"funcionario": self.funcionarios[0].pk, "tipo": "folga", "inicio": "2026-02-30", "fim": self.dia})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(Ausencia.objects.count(), 0)

    def test_ausencia_com_tipo_desconhecido_nao_e_gravada(self):
        r = self.post("escala:ausencias", {"funcionario": self.funcionarios[0].pk, "tipo": "inexistente", "inicio": self.dia, "fim": self.dia})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(Ausencia.objects.count(), 0)

    def test_ids_invalidos_nos_formularios_exibem_erro_recuperavel(self):
        for rota, dados in [
            ("escala:ausencias", {"funcionario": "nao-informado"}),
            ("escala:atribuir", {"turno": "nao-informado", "funcionario": self.funcionarios[0].pk, "data": self.dia}),
            ("escala:trocas", {"atribuicao": "nao-informado", "substituto": self.funcionarios[1].pk}),
        ]:
            with self.subTest(rota=rota):
                r = self.post(rota, dados)
                self.assertEqual(r.status_code, 422)

    def test_editor_recusa_acao_desconhecida_e_ids_invalidos(self):
        for dados in ({"acao": "desconhecida"}, {"acao": "add", "turno": "abc", "funcionario": self.funcionarios[0].pk, "data": str(self.dia)}):
            with self.subTest(dados=dados):
                resposta = self.post("escala:editar", dados)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("erro", resposta.json())

    def test_hora_extra_incompleta_ou_tipo_invalido_nao_persiste(self):
        for dados in ({"he_inicio": "", "he_fim": "18:00", "tipo": "banco"},
                      {"he_inicio": "16:00", "he_fim": "18:00", "tipo": "xxxxx"}):
            with self.subTest(dados=dados):
                r = self.post("escala:editar", {"acao": "he_add", "funcionario": self.funcionarios[0].pk, "data": self.dia, **dados})
                self.assertEqual(r.status_code, 400)
                self.assertEqual(HoraExtra.objects.count(), 0)

    def test_relatorio_colaborador_invalido_nao_da_500(self):
        r = self.client.get(reverse("escala:relatorio"), {"funcionario": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["func"])

    def test_troca_com_falha_na_gravacao_nao_muda_atribuicao(self):
        atrib = services.atribuir(self.turno, self.funcionarios[0], self.dia, self.usuario)
        troca = services.solicitar_troca(atrib, self.funcionarios[1], "Troca fictícia")
        with patch.object(TrocaTurno, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaisesMessage(RuntimeError, "falha simulada"):
                services.decidir_troca(troca, self.usuario, True)
        atrib.refresh_from_db()
        troca.refresh_from_db()
        self.assertEqual(atrib.funcionario_id, self.funcionarios[0].pk)
        self.assertEqual(troca.status, TrocaTurno.Status.PENDENTE)

    def test_troca_antiga_nao_sobrescreve_substituicao_ja_aprovada(self):
        atrib = services.atribuir(self.turno, self.funcionarios[0], self.dia, self.usuario)
        primeira = services.solicitar_troca(atrib, self.funcionarios[1], "Primeira")
        antiga = services.solicitar_troca(atrib, self.funcionarios[2], "Alternativa anterior")
        services.decidir_troca(primeira, self.usuario, True)
        with self.assertRaises(ValidationError):
            services.decidir_troca(antiga, self.usuario, True)
        atrib.refresh_from_db()
        self.assertEqual(atrib.funcionario_id, self.funcionarios[1].pk)

    def test_atribuicao_de_turno_inativo_e_recusada(self):
        self.turno.ativo = False
        self.turno.save()
        with self.assertRaises(ValidationError):
            services.atribuir(self.turno, self.funcionarios[0], self.dia, self.usuario)
        self.assertEqual(Atribuicao.objects.count(), 0)

    def test_gerar_ou_publicar_com_data_invalida_nao_altera_semana_atual(self):
        for rota, campo in (("escala:gerar", "semana"), ("escala:publicar", "inicio")):
            with self.subTest(rota=rota):
                r = self.post(rota, {campo: "data-invalida", "setor": "geral"})
                self.assertEqual(r.status_code, 422)
        self.assertEqual(Atribuicao.objects.count(), 0)
        self.assertEqual(SemanaPublicada.objects.count(), 0)

    def test_decisao_desconhecida_nao_recusa_troca(self):
        atrib = services.atribuir(self.turno, self.funcionarios[0], self.dia, self.usuario)
        troca = services.solicitar_troca(atrib, self.funcionarios[1], "Troca")
        r = self.client.post(reverse("escala:decidir_troca", args=[troca.pk]),
                             {"acao": "inexistente"}, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(r.status_code, 422)
        troca.refresh_from_db()
        self.assertEqual(troca.status, TrocaTurno.Status.PENDENTE)
