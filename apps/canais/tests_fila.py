"""Fila durável, repetição do provedor e autenticação de avisos externos."""
import hashlib
import hmac
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import ModuloContratado
from apps.reservas.models import Reserva, RestricaoVenda

from . import services
from .models import AvisoCanal, ConfiguracaoCanais, EnvioCanal
from .tests import DadosCanais

CONFIGURACAO = dict(CHANNEX_API_KEY="chave-canais-ficticia", CHANNEX_API_KEY_HML="chave-hml-ficticia",
    CHANNEX_WEBHOOK_SECRET="assinatura-producao-ficticia-qa", CHANNEX_WEBHOOK_SECRET_HML="assinatura-hml-ficticia-qa",
    CANAIS_HOMOLOGACAO_APLICAR=False)


@override_settings(**CONFIGURACAO)
class FilaCanaisTests(DadosCanais, TestCase):
    def versao(self):
        self.cfg.refresh_from_db()
        return self.cfg.versao_pendente

    def test_mudanca_e_pedido_da_fila_participam_da_mesma_transacao(self):
        antes = self.versao()
        with self.assertRaisesMessage(RuntimeError, "Reverter"):
            with transaction.atomic():
                self.tipo.tarifa_base = "400"
                self.tipo.save()
                self.assertGreater(self.versao(), antes)
                raise RuntimeError("Reverter")
        self.assertEqual(self.versao(), antes)
        self.tipo.refresh_from_db()
        self.assertEqual(str(self.tipo.tarifa_base), "300.00")

    def test_edicao_pela_tela_reverte_tarifa_se_fila_nao_persistir(self):
        self.client.force_login(self.op)
        dados = {"nome": self.tipo.nome, "descricao": "", "capacidade": "2", "tarifa_base": "400.00", "ativo": "on"}
        with patch("apps.canais.services.ConfiguracaoCanais.objects.filter", side_effect=RuntimeError("Falha fictícia ao persistir fila")):
            with self.assertRaisesMessage(RuntimeError, "persistir fila"):
                self.client.post(reverse("tipo_uh_editar", args=[self.tipo.pk]), dados)
        self.tipo.refresh_from_db()
        self.assertEqual(str(self.tipo.tarifa_base), "300.00")
        antes = self.versao()
        self.assertEqual(self.client.post(reverse("tipo_uh_editar", args=[self.tipo.pk]), dados).status_code, 302)
        self.tipo.refresh_from_db()
        self.assertEqual(str(self.tipo.tarifa_base), "400.00")
        self.assertGreater(self.versao(), antes)

    def test_estoque_restricao_manutencao_e_expiracao_enfileiram_sem_http(self):
        from apps.manutencao.models import OrdemServico
        with patch("apps.canais.services.Channex") as http:
            anterior = self.versao()
            self.uh.numero = "Canal-renomeado"
            self.uh.save()
            self.assertGreater(self.versao(), anterior)
            anterior = self.versao()
            restricao = RestricaoVenda.objects.create(descricao="Fechamento QA", inicio=self.inicio,
                fim=self.fim, min_noites=3, criado_por=self.op)
            self.assertGreater(self.versao(), anterior)
            anterior = self.versao()
            restricao.delete()
            self.assertGreater(self.versao(), anterior)
            anterior = self.versao()
            OrdemServico.objects.create(uh=self.uh, titulo="Bloqueio QA", bloqueia_uh=True,
                bloqueio_inicio=self.inicio, bloqueio_fim=self.fim, criado_por=self.op)
            self.assertGreater(self.versao(), anterior)
            # Expiração usa update em lote: deve emitir seu aviso explicitamente.
            services.aplicar_revisao(self.capturar(), self.op, manual=True)
            reserva = Reserva.objects.get()
            Reserva.objects.filter(pk=reserva.pk).update(status=Reserva.Status.PRE_RESERVA,
                expira_em=timezone.now()-timedelta(minutes=1))
            anterior = self.versao()
            self.assertEqual(services.reservas.expirar_vencidas(), 1)
            self.assertGreater(self.versao(), anterior)
            http.assert_not_called()

    def test_rotina_sem_alteracao_consulta_feed_mas_nao_republica_ari(self):
        self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "concluido")
        self.gateway.reset_mock()
        with patch("apps.canais.services.previa_envio", wraps=services.previa_envio) as previa:
            self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "concluido")
            previa.assert_not_called()
        self.gateway.revisoes.assert_called_once()
        self.gateway.tarifas.assert_not_called()
        self.gateway.disponibilidade.assert_not_called()

    def test_falha_aplica_espera_progressiva_e_preserva_pedido_manual(self):
        self.gateway.revisoes.side_effect = ValidationError("Limite temporário do provedor.")
        instante = timezone.now()
        for espera in (1, 2, 4, 8, 16, 30, 30):
            with patch("apps.canais.services.timezone.now", return_value=instante):
                self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "falha")
                self.cfg.refresh_from_db()
                self.assertEqual(self.cfg.proxima_tentativa, instante+timedelta(minutes=espera))
                services.solicitar_sincronizacao(self.cfg, self.op)
                self.gateway.reset_mock()
                self.assertEqual(services.sincronizar(gateway=self.gateway, forcar=True)["estado"], "aguardando")
                self.gateway.revisoes.assert_not_called()
                self.cfg.refresh_from_db()
                self.assertTrue(self.cfg.sincronizacao_solicitada)
            instante += timedelta(minutes=espera, seconds=1)
        self.gateway.revisoes.side_effect = None
        with patch("apps.canais.services.timezone.now", return_value=instante):
            self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "concluido")
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.sincronizacao_solicitada)
        self.assertEqual(self.cfg.falhas_consecutivas, 0)
        self.assertIsNone(self.cfg.proxima_tentativa)

    def test_dia_novo_e_envio_interrompido_exigem_nova_publicacao(self):
        services.sincronizar(gateway=self.gateway)
        ConfiguracaoCanais.objects.filter(pk=self.cfg.pk).update(ultimo_envio=timezone.now()-timedelta(days=1))
        EnvioCanal.objects.update(aceito_em=timezone.now()-timedelta(days=1))
        self.gateway.reset_mock()
        services.sincronizar(gateway=self.gateway)
        self.assertTrue(self.gateway.disponibilidade.called)
        self.cfg.refresh_from_db()
        pendente = EnvioCanal.objects.create(configuracao=self.cfg, ambiente=self.cfg.ambiente,
            propriedade=self.cfg.propriedade, assinatura="interrompida", dados={})
        services.sincronizar(gateway=self.gateway)
        pendente.refresh_from_db()
        self.assertEqual(pendente.estado, EnvioCanal.Estado.FALHOU)
        self.assertNotEqual(EnvioCanal.objects.first().pk, pendente.pk)

    def test_desativacao_exige_conexao_encerrada_e_filtros_invalidos_retornam_400(self):
        modulo = ModuloContratado.objects.get(codigo="canais")
        modulo.ativo = False
        with self.assertRaisesMessage(ValidationError, "desligue a conexão"):
            modulo.full_clean()
        self.client.force_login(self.op)
        resposta = self.client.post(reverse("modulos_central"), {"codigo": "canais", "acao": "desativar"}, follow=True)
        self.assertContains(resposta, "desligue a conexão")
        self.assertTrue(ModuloContratado.objects.get(pk=modulo.pk).ativo)
        for valor in ("0", "-1", "abc", "١٢٣", "9"*10000):
            self.assertEqual(self.client.get(reverse("canais:painel"), {"conexao": valor}).status_code, 400)
        self.cfg.vendas_abertas = False
        self.cfg.save()
        services.salvar_configuracao(self.cfg, self.dados_config(ativo=False), self.op)
        modulo.full_clean()


@override_settings(**CONFIGURACAO)
class AvisosCanaisTests(DadosCanais, TestCase):
    def aviso(self, **mudancas):
        return {"event": "booking", "property_id": str(self.cfg.propriedade), "payload": {
            "property_id": str(self.cfg.propriedade), "revision_id": str(uuid.uuid4())}, **mudancas}

    def enviar(self, dados, *, segredo=None, instante=None, assinatura=None, ambiente="producao"):
        bruto = dados if isinstance(dados, bytes) else json.dumps(dados).encode()
        instante = str(int(time.time())) if instante is None else str(instante)
        segredo = segredo or CONFIGURACAO["CHANNEX_WEBHOOK_SECRET"]
        assinado = hmac.new(segredo.encode(), instante.encode()+b"."+bruto, hashlib.sha256).hexdigest()
        return self.client.post(reverse("canais:webhook", args=[ambiente]), bruto,
            content_type="application/json", headers={"x-hmac-timestamp": instante,
                "x-hmac-signature-256": assinado if assinatura is None else assinatura})

    def test_aviso_autenticado_e_repetido_so_guarda_identidade_e_uma_pendencia(self):
        dados = self.aviso()
        dados["payload"]["ignorar"] = {"guarantee": "NAO_GUARDAR_DADOS_CARTAO"}
        antes = ConfiguracaoCanais.objects.get(pk=self.cfg.pk).versao_pendente
        with patch("apps.canais.services.Channex") as http:
            self.assertEqual(self.enviar(dados).status_code, 200)
            self.assertEqual(self.enviar(dados).status_code, 200)
            http.assert_not_called()
        self.assertEqual(AvisoCanal.objects.count(), 1)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.versao_pendente, antes+1)
        self.assertNotIn("NAO_GUARDAR", str(list(AvisoCanal.objects.values())))

    def test_assinatura_replay_ambientes_e_corpo_adulterado_nao_gravam(self):
        dados = self.aviso()
        for opcoes in ({"segredo": CONFIGURACAO["CHANNEX_WEBHOOK_SECRET_HML"]}, {"assinatura": "0"*64},
                       {"instante": int(time.time())-301}, {"instante": int(time.time())+301},
                       {"instante": "9"*13}, {"instante": "１２３"}, {"assinatura": ",".join(["0"*64]*3)}):
            with self.subTest(opcoes=opcoes):
                self.assertEqual(self.enviar(dados, **opcoes).status_code, 401)
        self.assertFalse(AvisoCanal.objects.exists())

    def test_rotacao_duas_assinaturas_corpo_limite_e_estrutura(self):
        dados = self.aviso()
        bruto = json.dumps(dados).encode()
        instante = str(int(time.time()))
        assinatura = hmac.new(CONFIGURACAO["CHANNEX_WEBHOOK_SECRET"].encode(), instante.encode()+b"."+bruto, hashlib.sha256).hexdigest()
        self.assertEqual(self.enviar(bruto, instante=instante, assinatura="0"*64+", "+assinatura).status_code, 200)
        self.assertEqual(self.enviar(bruto+b" ", instante=instante, assinatura=assinatura).status_code, 401)
        self.assertEqual(self.enviar(b"x"*16385).status_code, 413)
        for invalido in (b"not-json", [], self.aviso(payload=[]), self.aviso(property_id=str(uuid.uuid4()))):
            self.assertEqual(self.enviar(invalido).status_code, 400)
        self.assertEqual(self.enviar(self.aviso(event="message")).status_code, 204)
        self.assertEqual(AvisoCanal.objects.count(), 1)

    def test_sem_segredo_ou_conexao_nao_acusa_recebimento(self):
        with override_settings(CHANNEX_WEBHOOK_SECRET=""):
            self.assertEqual(self.enviar(self.aviso()).status_code, 503)
        self.assertEqual(self.enviar(self.aviso(), ambiente="homologacao", segredo=CONFIGURACAO["CHANNEX_WEBHOOK_SECRET_HML"]).status_code, 404)
        ModuloContratado.objects.filter(codigo="canais").update(ativo=False)
        self.assertEqual(self.enviar(self.aviso()).status_code, 404)
        self.assertFalse(AvisoCanal.objects.exists())


@override_settings(**CONFIGURACAO)
class PublicacaoConcorrenteTests(DadosCanais, TransactionTestCase):
    def test_reserva_durante_http_continua_pendente_para_novo_envio(self):
        entrou, liberar = Event(), Event()
        def tarifas(lote):
            self.assertFalse(connection.in_atomic_block)
            entrou.set()
            if not liberar.wait(timeout=15):
                raise RuntimeError("Teste não liberou o envio fictício.")
            return [str(uuid.uuid4())]
        self.gateway.tarifas.side_effect = tarifas
        def publicar():
            close_old_connections()
            try:
                return services.sincronizar(gateway=self.gateway)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(publicar)
            try:
                self.assertTrue(entrou.wait(timeout=10))
                RestricaoVenda.objects.create(descricao="Fechado durante envio", inicio=self.inicio,
                    fim=self.fim, min_noites=4, criado_por=self.op)
            finally:
                liberar.set()
            self.assertEqual(futuro.result(timeout=15)["estado"], "concluido")
        self.cfg.refresh_from_db()
        self.assertGreater(self.cfg.versao_pendente, self.cfg.versao_enviada)
        self.gateway.reset_mock()
        self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "concluido")
        self.assertTrue(self.gateway.tarifas.called)
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.versao_pendente, self.cfg.versao_enviada)
