from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import Funcionario, Pessoa, Usuario

from . import services
from .models import ConfiguracaoEscala, Turno


class EscalaOperacionalTests(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="escala-regras")
        self.func = Funcionario.objects.create(pessoa=Pessoa.objects.create(nome="QA Escala"), cargo="Recepção")
        self.inicio = services.inicio_da_semana()

    def turno(self, inicio, fim):
        return Turno.objects.create(nome=f"{inicio}-{fim}", inicio=time(inicio), fim=time(fim), min_pessoas=0)

    def test_noite_atravessa_data_e_descanso_configuravel(self):
        noite, dia = self.turno(22, 6), self.turno(8, 16)
        services.atribuir(noite, self.func, self.inicio, self.op)
        services.atribuir(dia, self.func, self.inicio + timedelta(days=1), self.op)
        self.assertIn("interjornada <11h", services.analisar_semana(self.inicio)["bloqueios"])
        ConfiguracaoEscala.objects.filter(pk=1).update(descanso_horas=2)
        self.assertNotIn("interjornada <2h", services.analisar_semana(self.inicio)["bloqueios"])

    def test_sobreposicao_impede_publicacao_mesmo_com_justificativa(self):
        services.atribuir(self.turno(8, 16), self.func, self.inicio, self.op)
        services.atribuir(self.turno(12, 20), self.func, self.inicio, self.op)
        self.assertIn("horários sobrepostos", services.analisar_semana(self.inicio)["bloqueios"])
        with self.assertRaisesMessage(ValidationError, "sobrepostos"):
            services.publicar_semana(self.inicio, None, self.op, "Não resolve a sobreposição")

    def test_regra_pelo_formulario_e_numeros_invalidos(self):
        self.client.force_login(self.op)
        for valor in ("0", "49", "NaN", "1e999999"):
            self.client.post(reverse("escala:turnos"), {"acao": "descanso", "descanso_horas": valor})
            self.assertEqual(ConfiguracaoEscala.atual().descanso_horas, 11)
        self.client.post(reverse("escala:turnos"), {"acao": "descanso", "descanso_horas": "12"})
        self.assertEqual(ConfiguracaoEscala.atual().descanso_horas, 12)

    def test_filtrar_setor_nao_esconde_conflito_da_mesma_pessoa_em_outro_setor(self):
        recepcao = self.turno(22, 6)
        outro = self.turno(5, 13)
        outro.setor = "governanca"
        outro.save()
        services.atribuir(recepcao, self.func, self.inicio, self.op)
        services.atribuir(outro, self.func, self.inicio+timedelta(days=1), self.op)
        self.assertIn("horários sobrepostos", services.analisar_semana(self.inicio, recepcao.setor)["bloqueios"])
        with self.assertRaisesMessage(ValidationError, "sobrepostos"):
            services.publicar_semana(self.inicio, recepcao.setor, self.op, "Justificativa não elimina conflito")
