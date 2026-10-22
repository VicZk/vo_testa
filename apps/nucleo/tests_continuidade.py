import hashlib
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.comercial import email_gateways, whatsapp_gateways

from .integracoes import situacao_integracoes
from .management.commands import backup_banco
from .models import EnsaioIntegracao, EstadoBackup


class EstadoIntegracoesTests(TestCase):
    def setUp(self):
        self.gerente=get_user_model().objects.create_user(username="gerente-integracoes",is_staff=True)
        self.client.force_login(self.gerente)

    def test_acesso_gerencia_sem_credenciais_na_pagina(self):
        segredo="TESTE-NAO-EXIBIR-CHAVE"
        with override_settings(SAFRAPAY_TOKEN=segredo,WHATSAPP_CLOUD_TOKEN=segredo,FISCAL_FOCUS_TOKEN=segredo):
            pagina=self.client.get(reverse("integracoes"))
        self.assertContains(pagina,"Operação e integrações")
        self.assertNotContains(pagina,segredo)
        self.assertContains(pagina,"Simulação")
        self.assertIn("no-store",pagina.headers["Cache-Control"])
        operador=get_user_model().objects.create_user(username="operador-integracoes")
        self.client.force_login(operador)
        self.assertEqual(self.client.get(reverse("integracoes")).status_code,403)

    @override_settings(EMAIL_GATEWAY="smtp",EMAIL_HOST="smtp.example.invalid",EMAIL_HOST_USER="",EMAIL_HOST_PASSWORD="",
        EMAIL_COMERCIAL_HOST_USER="comercial@example.invalid",EMAIL_COMERCIAL_HOST_PASSWORD="SENHA-QA")
    def test_smtp_dedicado_ensaio_e_rotacao_invalidam_sem_rede(self):
        email=next(i for i in situacao_integracoes() if i["codigo"]=="email")
        self.assertTrue(email["pronto"])
        with patch("apps.comercial.email_gateways.get_connection") as conexao:
            self.client.post(reverse("integracoes"),{"canal":"email","confirmado":"sim",
                "evidencia":"Conferido o recebimento e a resposta na caixa de ensaio."})
        conexao.assert_not_called()
        self.assertEqual(EnsaioIntegracao.objects.count(),1)
        self.assertEqual(next(i for i in situacao_integracoes() if i["codigo"]=="email")["situacao"],"Ensaio registrado")
        with override_settings(EMAIL_COMERCIAL_HOST_PASSWORD="ROTACIONADA-QA"):
            atual=next(i for i in situacao_integracoes() if i["codigo"]=="email")
        self.assertTrue(atual["ensaio_desatualizado"])
        self.assertEqual(atual["situacao"],"Aguardando ensaio")

    def test_simulado_nao_pode_receber_ensaio_real(self):
        resposta=self.client.post(reverse("integracoes"),{"canal":"pagamentos","confirmado":"sim",
            "evidencia":"Texto de ensaio que não configura o provedor."})
        self.assertContains(resposta,"Complete a configuração real")
        self.assertFalse(EnsaioIntegracao.objects.exists())


class TransportesMensagensTests(TestCase):
    dados=dict(para="qa@example.invalid",assunto="Ensaio",html="<p>Ensaio</p>",texto="Ensaio",remetente="Pousada <qa@example.invalid>")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",EMAIL_HOST="smtp.example.invalid")
    def test_simulado_nao_usa_smtp_configurado(self):
        with patch("django.core.mail.backends.smtp.EmailBackend.send_messages") as smtp:
            resultado=email_gateways.GatewaySimulado().enviar(**self.dados)
        smtp.assert_not_called()
        self.assertEqual(resultado["status"],"simulado")

    @override_settings(DEBUG=False,TESTING=False)
    def test_simulado_producao_nao_sinaliza_envio(self):
        with self.assertRaises(ValidationError):
            email_gateways.GatewaySimulado().enviar(**self.dados)
        with self.assertRaises(ValidationError):
            whatsapp_gateways.GatewaySimulado().enviar_template("5549999990000","ensaio")

    @override_settings(EMAIL_HOST="smtp.example.invalid",EMAIL_HOST_USER="qa",EMAIL_HOST_PASSWORD="QA")
    def test_smtp_exige_aceitacao_e_esconde_erro_do_servidor(self):
        conn=MagicMock()
        for retorno in (0,1):
            conn.send_messages.return_value=retorno
            with patch.object(email_gateways,"get_connection",return_value=conn):
                if retorno:
                    self.assertEqual(email_gateways.GatewaySmtp().enviar(**self.dados)["status"],"enviado")
                else:
                    with self.assertRaisesMessage(ValidationError,"não aceitou"):
                        email_gateways.GatewaySmtp().enviar(**self.dados)
        conn.send_messages.side_effect=OSError("SEGREDO-NAO-EXIBIR")
        with patch.object(email_gateways,"get_connection",return_value=conn), self.assertRaises(ValidationError) as erro:
            email_gateways.GatewaySmtp().enviar(**self.dados)
        self.assertNotIn("SEGREDO-NAO-EXIBIR",str(erro.exception))

    @override_settings(EMAIL_SES_REGION="sa-east-1",EMAIL_SES_ACCESS_KEY_ID="QA",EMAIL_SES_SECRET_ACCESS_KEY="QA")
    def test_ses_envia_mime_e_exige_message_id(self):
        cliente=MagicMock()
        cliente.send_raw_email.return_value={"MessageId":"SES-QA-1"}
        with patch("boto3.client",return_value=cliente):
            retorno=email_gateways.GatewaySes().enviar(**self.dados)
        self.assertEqual(retorno["message_id"],"SES-QA-1")
        pedido=cliente.send_raw_email.call_args.kwargs
        self.assertEqual(pedido["Source"],"qa@example.invalid")
        self.assertEqual(pedido["Destinations"],["qa@example.invalid"])
        self.assertIn(b"multipart/alternative",pedido["RawMessage"]["Data"])
        cliente.send_raw_email.return_value={}
        with patch("boto3.client",return_value=cliente), self.assertRaises(ValidationError):
            email_gateways.GatewaySes().enviar(**self.dados)

    @override_settings(WHATSAPP_CLOUD_TOKEN="QA",WHATSAPP_CLOUD_PHONE_ID="123456")
    def test_meta_sem_identificador_nao_confirma_mensagem_ou_midia(self):
        for corpo in ({},[],{"messages":[]},{"messages":[{}]}):
            resposta=MagicMock()
            resposta.__enter__.return_value=resposta
            resposta.read.return_value=json.dumps(corpo).encode()
            with patch.object(whatsapp_gateways.urlrequest,"urlopen",return_value=resposta):
                self.assertFalse(whatsapp_gateways._api_post({})["ok"])
                self.assertFalse(whatsapp_gateways._upload_media(b"qa","image/png","qa.png")["ok"])


@override_settings(BACKUP_R2_BUCKET="",BACKUP_R2_ENDPOINT_URL="",BACKUP_R2_ACCESS_KEY_ID="",BACKUP_R2_SECRET_ACCESS_KEY="",BACKUP_R2_PRIVADO=False)
class BackupVerificadoTests(TestCase):
    def rodar(self,*args):
        call_command("backup_banco",*args,stdout=StringIO())

    def test_auto_nao_recua_para_json_sem_pg_dump(self):
        with tempfile.TemporaryDirectory() as pasta, patch.dict(os.environ,{"BACKUP_DIR":pasta}), \
                patch.object(backup_banco,"_dump_pg",return_value=False),patch.object(backup_banco,"_dump_json") as json_dump:
            with self.assertRaisesMessage(CommandError,"pg_dump/pg_restore"):
                self.rodar()
            self.assertEqual(list(Path(pasta).iterdir()),[])
        json_dump.assert_not_called()
        self.assertEqual(EstadoBackup.objects.get(pk=1).situacao,"falha")

    def test_copia_local_hash_e_manifesto_correspondem(self):
        with tempfile.TemporaryDirectory() as pasta,patch.dict(os.environ,{"BACKUP_DIR":pasta}):
            self.rodar("--formato","json")
            arquivo=next(Path(pasta).glob("crm-*.json.gz"))
            meta=json.loads((Path(pasta)/("metadata-"+arquivo.name+".json")).read_text())
            self.assertEqual(meta["sha256"],hashlib.sha256(arquivo.read_bytes()).hexdigest())
            self.assertEqual(meta["bytes"],arquivo.stat().st_size)
            self.assertFalse(list(Path(pasta).glob("*.part")))
        estado=EstadoBackup.objects.get(pk=1)
        self.assertEqual(estado.situacao,"concluido")
        self.assertEqual(estado.sha256,meta["sha256"])

    def test_copia_corrompida_nao_vira_backup_concluido(self):
        with tempfile.TemporaryDirectory() as pasta,patch.dict(os.environ,{"BACKUP_DIR":pasta}), \
                patch.object(backup_banco.shutil,"copyfileobj",side_effect=lambda origem,saida:saida.write(b"truncado")):
            with self.assertRaisesMessage(CommandError,"hash"):
                self.rodar("--formato","json")
            self.assertEqual(list(Path(pasta).iterdir()),[])
        self.assertEqual(EstadoBackup.objects.get(pk=1).situacao,"falha")

    def test_r2_incompleto_ou_publico_falha(self):
        with tempfile.TemporaryDirectory() as pasta,patch.dict(os.environ,{"BACKUP_DIR":pasta}),override_settings(BACKUP_R2_BUCKET="bucket"):
            with self.assertRaisesMessage(CommandError,"cópia externa"):
                self.rodar("--formato","json")
        with override_settings(BACKUP_R2_BUCKET="midia",R2_BUCKET="midia",BACKUP_R2_ENDPOINT_URL="https://qa.invalid",
            BACKUP_R2_ACCESS_KEY_ID="Q",BACKUP_R2_SECRET_ACCESS_KEY="Q",BACKUP_R2_PRIVADO=True):
            self.assertFalse(backup_banco._r2_configurado())

    @override_settings(BACKUP_R2_BUCKET="privado",BACKUP_R2_ENDPOINT_URL="https://qa.invalid",BACKUP_R2_ACCESS_KEY_ID="Q",BACKUP_R2_SECRET_ACCESS_KEY="Q",BACKUP_R2_PRIVADO=True)
    def test_falha_externa_preserva_ultimo_sucesso_e_nao_marca_tudo_ok(self):
        sucesso=timezone.now()
        EstadoBackup.objects.create(pk=1,ultimo_sucesso=sucesso,situacao="concluido")
        with tempfile.TemporaryDirectory() as pasta,patch.dict(os.environ,{"BACKUP_DIR":pasta}), \
                patch.object(backup_banco.Command,"_enviar_r2",side_effect=OSError("SEGREDO-NAO-LOGAR")):
            with self.assertRaises(CommandError) as erro:
                self.rodar("--formato","json")
            self.assertTrue(list(Path(pasta).glob("crm-*.json.gz")))
        self.assertNotIn("SEGREDO-NAO-LOGAR",str(erro.exception))
        estado=EstadoBackup.objects.get(pk=1)
        self.assertEqual(estado.ultimo_sucesso,sucesso)
        self.assertEqual(estado.situacao,"falha")
