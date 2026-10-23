import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import (
    UH,
    ConfiguracaoReservas,
    ConfiguracaoUH,
    ModuloContratado,
    Pessoa,
    PosicaoCama,
    TipoUH,
    Usuario,
)
from apps.reservas.models import ContaHospedagem, Reserva, RestricaoVenda

from . import services
from .models import (
    ConfiguracaoCanais,
    EnvioCanal,
    MapeamentoCanal,
    ReservaCanal,
    RevisaoCanal,
    UnidadeMapeada,
)
from .tests_contrato import revisao_exemplo


class DadosCanais:
    def setUp(self):
        super().setUp()
        self.op = Usuario.objects.create_superuser(username="canais-qa", password="canais-ficticio-qa")
        for codigo in ("reservas", "canais", "manutencao", "pagamentos"):
            ModuloContratado.objects.update_or_create(codigo=codigo, defaults={"ativo": True})
        ConfiguracaoReservas.objects.update_or_create(pk=1, defaults={"feriados_automaticos": False})
        self.inicio = timezone.localdate() + timedelta(days=1)
        self.fim = self.inicio + timedelta(days=2)
        self.tipo = TipoUH.objects.create(nome="Suíte Canais QA", capacidade=2, tarifa_base="300")
        self.uh = self.quarto("Canal-1")
        self.uh2 = self.quarto("Canal-2")
        self.cfg = ConfiguracaoCanais.objects.create(ativo=True, ambiente="producao", propriedade=uuid.uuid4(),
            responsavel=self.op, dias_publicados=5, importar_automaticamente=True)
        self.mapa = MapeamentoCanal.objects.create(configuracao=self.cfg, nome="Suítes QA", tipo_externo=uuid.uuid4(),
            tarifa_externa=uuid.uuid4(), ocupacao_tarifa=2, limite_venda=2, margem_seguranca=0)
        for uh in (self.uh, self.uh2):
            UnidadeMapeada.objects.create(configuracao=self.cfg, uh=uh, mapeamento=self.mapa)
        services.registrar_validacao(self.cfg, "Conferência fictícia de todos os contratos no ambiente de teste.", self.op)
        self.cfg.refresh_from_db()
        self.cfg.vendas_abertas = True
        self.cfg.save(update_fields=["vendas_abertas"])
        self.gateway = Mock()
        self.gateway.revisoes.return_value = []
        self.gateway.disponibilidade.side_effect = lambda lote: [str(uuid.uuid4())]
        self.gateway.tarifas.side_effect = lambda lote: [str(uuid.uuid4())]

    def quarto(self, numero):
        uh = UH.objects.create(numero=numero, tipo=self.tipo)
        PosicaoCama.objects.create(uh=uh, nome="Cama QA", ordem=1)
        ConfiguracaoUH.objects.create(uh=uh, max_colchoes_extras=0)
        return uh

    def bruto(self):
        item = revisao_exemplo(self.cfg.propriedade)
        a = item["attributes"]
        a["inserted_at"] = timezone.now().isoformat()
        q = a["rooms"][0]
        q.update(room_type_id=str(self.mapa.tipo_externo), rate_plan_id=str(self.mapa.tarifa_externa),
            checkin_date=self.inicio.isoformat(), checkout_date=self.fim.isoformat(),
            days={(self.inicio+timedelta(days=i)).isoformat(): "300.00" for i in range(2)})
        return item

    def capturar(self, item=None):
        return services.receber_revisao(self.cfg, item or self.bruto())

    def nova_versao(self, item, **mudancas):
        novo = copy.deepcopy(item)
        novo["id"] = novo["attributes"]["id"] = str(uuid.uuid4())
        novo["attributes"]["inserted_at"] = (timezone.now()+timedelta(minutes=2)).isoformat()
        novo["attributes"].update({"status": "modified", **mudancas})
        return novo

    def dados_config(self, **mudancas):
        dados = {campo: getattr(self.cfg, campo) for campo in (
            "ambiente", "propriedade", "responsavel", "dias_publicados", "ativo", "vendas_abertas", "importar_automaticamente")}
        return dados | mudancas

    def dados_mapa(self, **mudancas):
        return {c: getattr(self.mapa, c) for c in (
            "nome", "tipo_externo", "tarifa_externa", "ocupacao_tarifa", "limite_venda", "margem_seguranca", "ativo")} | mudancas


@override_settings(CHANNEX_API_KEY="chave-canais-ficticia", CHANNEX_API_KEY_HML="chave-hml-ficticia", CHANNEX_WEBHOOK_SECRET="assinatura-producao-ficticia-qa", CHANNEX_WEBHOOK_SECRET_HML="assinatura-hml-ficticia-qa", CANAIS_HOMOLOGACAO_APLICAR=False)
class CanaisTests(DadosCanais, TestCase):
    def test_configuracao_exige_chave_mapa_e_validacao_da_versao_atual(self):
        self.assertTrue(services.situacao(self.cfg)["validada"])
        with override_settings(CHANNEX_API_KEY="outra-chave-ficticia"):
            self.assertFalse(services.situacao(self.cfg)["validada"])
            with self.assertRaises(ValidationError):
                services.salvar_configuracao(self.cfg, self.dados_config(), self.op)
        with override_settings(CHANNEX_API_KEY=""):
            self.assertFalse(services.situacao(self.cfg)["configurada"])
        self.cfg.vendas_abertas = False
        self.cfg.save()
        services.salvar_mapeamento(self.cfg, self.mapa, self.dados_mapa(limite_venda=1), [self.uh, self.uh2], self.op)
        self.assertFalse(services.situacao(self.cfg)["validada"])
        with self.assertRaises(ValidationError):
            services.salvar_configuracao(self.cfg, self.dados_config(vendas_abertas=True), self.op)

    def test_mapeamento_nao_duplica_uh_nem_supera_limite(self):
        self.cfg.vendas_abertas = False
        self.cfg.save()
        outro = MapeamentoCanal(configuracao=self.cfg)
        dados = self.dados_mapa(tipo_externo=uuid.uuid4(), tarifa_externa=uuid.uuid4())
        with self.assertRaisesMessage(ValidationError, "já pertence"):
            services.salvar_mapeamento(self.cfg, outro, dados, [self.uh], self.op)
        with self.assertRaisesMessage(ValidationError, "não podem superar"):
            services.salvar_mapeamento(self.cfg, self.mapa, self.dados_mapa(limite_venda=3), [self.uh, self.uh2], self.op)

    def test_recebimento_idempotente_ordem_e_colisao_nao_perdem_revisao(self):
        item = self.bruto()
        primeira = self.capturar(item)
        self.assertEqual(self.capturar(item).pk, primeira.pk)
        nova = self.nova_versao(item)
        ultima = self.capturar(nova)
        primeira.refresh_from_db()
        self.assertEqual(primeira.estado, RevisaoCanal.Estado.ANTERIOR)
        tardia = self.nova_versao(item)
        tardia["attributes"]["inserted_at"] = (timezone.now()-timedelta(days=1)).isoformat()
        self.assertEqual(self.capturar(tardia).estado, RevisaoCanal.Estado.ANTERIOR)
        self.assertEqual(ReservaCanal.objects.get().ultima_revisao_id, ultima.pk)
        adulterada = copy.deepcopy(nova)
        adulterada["attributes"]["amount"] = "601"
        with self.assertRaisesMessage(ValidationError, "dados diferentes"):
            self.capturar(adulterada)
        self.assertEqual(RevisaoCanal.objects.count(), 3)

    def test_nova_reserva_aplica_uma_vez_valor_bruto_sem_pagamento(self):
        rev = self.capturar()
        services.aplicar_revisao(rev, self.op)
        services.aplicar_revisao(rev, self.op)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.status, Reserva.Status.CONFIRMADA)
        self.assertEqual(reserva.canal, Reserva.Canal.OTA)
        self.assertEqual(reserva.valor_hospedagem, Decimal("600"))
        self.assertEqual(reserva.total_previsto(), Decimal("600"))
        self.assertFalse(reserva.cobra_iss or reserva.cobra_taxa_turismo)
        self.assertFalse(reserva.adiantamentos.exists())
        self.assertFalse(ContaHospedagem.objects.exists())
        self.assertFalse(reserva.hospede.aceita_email or reserva.hospede.aceita_whatsapp)
        rev.refresh_from_db()
        self.assertEqual(rev.estado, RevisaoCanal.Estado.APLICADA)
        self.assertEqual(list(rev.vinculos_aplicados.values())[0]["reserva_id"], reserva.pk)

    def test_alteracao_e_cancelamento_preservam_id_e_nao_reabrem_cancelada(self):
        item = self.bruto()
        services.aplicar_revisao(self.capturar(item), self.op)
        reserva = Reserva.objects.get()
        novo = self.nova_versao(item, amount="650.00")
        novo["attributes"]["rooms"][0].update(amount="650.00", days={})
        services.aplicar_revisao(self.capturar(novo), self.op)
        reserva.refresh_from_db()
        self.assertEqual(reserva.valor_hospedagem, Decimal("650"))
        cancelada = self.nova_versao(novo)
        cancelada["attributes"].update(status="cancelled", rooms=[], inserted_at=(timezone.now()+timedelta(minutes=3)).isoformat())
        services.aplicar_revisao(self.capturar(cancelada), self.op)
        reserva.refresh_from_db()
        self.assertEqual(reserva.status, Reserva.Status.CANCELADA)
        self.assertEqual(Reserva.objects.count(), 1)
        repetida = self.nova_versao(cancelada)
        repetida["attributes"].update(status="cancelled", inserted_at=(timezone.now()+timedelta(minutes=4)).isoformat())
        services.aplicar_revisao(self.capturar(repetida), self.op)
        self.assertEqual(Reserva.objects.get().status, Reserva.Status.CANCELADA)

    def test_intervencao_no_pms_ou_conta_aberta_exige_conferencia(self):
        item = self.bruto()
        services.aplicar_revisao(self.capturar(item), self.op)
        reserva = Reserva.objects.get()
        original = reserva.valor_diaria
        Reserva.objects.filter(pk=reserva.pk).update(valor_diaria=original+1)
        rev = self.capturar(self.nova_versao(item))
        with self.assertRaisesMessage(ValidationError, "alterada no PMS"):
            services.aplicar_revisao(rev, self.op)
        Reserva.objects.filter(pk=reserva.pk).update(valor_diaria=original)
        ContaHospedagem.objects.create(reserva=reserva)
        with self.assertRaisesMessage(ValidationError, "conta"):
            services.aplicar_revisao(rev, self.op)

    def test_multiplos_quartos_sao_atomicos_na_falta_de_estoque(self):
        UnidadeMapeada.objects.filter(uh=self.uh2).delete()
        services.registrar_validacao(self.cfg, "Conferência fictícia da categoria com apenas uma unidade.", self.op)
        item = self.bruto()
        segundo = copy.deepcopy(item["attributes"]["rooms"][0])
        segundo["ota_unique_id"] = "quarto-dois"
        item["attributes"]["rooms"].append(segundo)
        item["attributes"]["amount"] = "1200"
        rev = self.capturar(item)
        pessoas = Pessoa.objects.count()
        with self.assertRaisesMessage(ValidationError, "Nenhum quarto"):
            services.aplicar_revisao(rev, self.op)
        self.assertFalse(Reserva.objects.exists())
        self.assertEqual(Pessoa.objects.count(), pessoas)
        self.assertFalse(rev.reserva.quartos.exists())

    def test_recebimento_ota_moeda_tributos_idades_e_soma_nao_sao_adivinhados(self):
        variantes = [({"currency": "USD"}, {}), ({"payment_collect": "ota"}, {}),
            ({"services": ["cafe"]}, {}), ({}, {"taxes": ["tributo"]}),
            ({}, {"occupancy": {"adults": 1, "children": 1}}),
            ({"amount": "700"}, {}), ({}, {"days": {self.inicio.isoformat(): "500"}})]
        for reserva, quarto in variantes:
            with self.subTest(reserva=reserva, quarto=quarto):
                item = self.bruto()
                item["attributes"].update(reserva)
                item["attributes"]["rooms"][0].update(quarto)
                with self.assertRaises(ValidationError):
                    services.aplicar_revisao(self.capturar(item), self.op)
        self.assertFalse(Reserva.objects.exists())

    def test_homologacao_guarda_ensaio_sem_ocupar_estoque(self):
        self.cfg.ambiente = "homologacao"
        self.cfg.save()
        item = self.bruto()
        self.gateway.revisoes.side_effect = [[item], []]
        resultado = services.sincronizar(gateway=self.gateway)
        self.assertEqual(resultado["estado"], "concluido")
        self.assertEqual(RevisaoCanal.objects.get().estado, RevisaoCanal.Estado.ENSAIO)
        self.assertFalse(Reserva.objects.exists())
        with self.assertRaisesMessage(ValidationError, "separadas"):
            services.aplicar_revisao(RevisaoCanal.objects.get(), self.op, manual=True)

    def test_feed_indisponivel_ou_invalido_tenta_fechar_venda_sem_ack(self):
        for itens in (ValidationError("Feed indisponível."), [{"type": "invalido"}]):
            with self.subTest(itens=itens):
                ConfiguracaoCanais.objects.filter(pk=self.cfg.pk).update(proxima_tentativa=None)
                self.gateway.reset_mock()
                self.gateway.revisoes.side_effect = itens if isinstance(itens, Exception) else None
                if not isinstance(itens, Exception):
                    self.gateway.revisoes.return_value = itens
                resultado = services.sincronizar(gateway=self.gateway, forcar=True)
                self.assertEqual(resultado["estado"], "falha")
                self.gateway.confirmar_recebimento.assert_not_called()
                self.assertTrue(self.gateway.disponibilidade.called)
                for chamada in self.gateway.disponibilidade.call_args_list:
                    self.assertTrue(all(linha["availability"] == 0 for linha in chamada.args[0]))

    def test_pendencia_fecha_oferta_e_revisao_valida_vai_para_pms(self):
        item = self.bruto()
        self.cfg.importar_automaticamente = False
        self.cfg.save()
        self.gateway.revisoes.side_effect = [[item], []]
        services.sincronizar(gateway=self.gateway)
        rev = RevisaoCanal.objects.get()
        self.assertEqual(rev.estado, RevisaoCanal.Estado.PENDENTE)
        self.assertIsNotNone(rev.recebimento_confirmado_em)
        self.assertTrue(all(v["availability"] == 0 for v in EnvioCanal.objects.first().dados["disponibilidade"]))
        services.aplicar_revisao(rev, self.op, manual=True)
        self.assertEqual(Reserva.objects.count(), 1)
        previa = services.previa_envio(self.cfg)
        noite = next(v for v in previa["disponibilidade"] if v["date"] == self.inicio.isoformat())
        self.assertEqual(noite["availability"], 1)

    def test_envio_parcial_ou_interrompido_nao_desliga_conexao_por_fechamento_antigo(self):
        self.cfg.vendas_abertas = False
        self.cfg.save()
        envio = services.publicar(self.cfg, self.gateway)
        services.conferir_envio(envio, "Fechamento conferido no canal de teste para todas as datas.", self.op)
        self.assertTrue(services._ultimo_envio_fechado(self.cfg))
        self.gateway.tarifas.side_effect = ValidationError("Falha fictícia no preço.")
        with self.assertRaises(ValidationError):
            services.publicar(self.cfg, self.gateway, forcar=True)
        self.assertFalse(services._ultimo_envio_fechado(self.cfg))
        with self.assertRaisesMessage(ValidationError, "Feche as vendas"):
            services.salvar_configuracao(self.cfg, self.dados_config(ativo=False), self.op)
        self.gateway.tarifas.side_effect = lambda lote: [str(uuid.uuid4())]
        self.assertIsNotNone(services.publicar(self.cfg, self.gateway))
        self.assertEqual(EnvioCanal.objects.first().estado, EnvioCanal.Estado.ACEITO)

    def test_previa_aplica_ocupacao_margem_manutencao_e_restricoes(self):
        from apps.manutencao.models import OrdemServico
        self.mapa.margem_seguranca = 1
        self.mapa.save()
        services.registrar_validacao(self.cfg, "Conferência fictícia após mudança da margem de segurança.", self.op)
        self.cfg.refresh_from_db()
        RestricaoVenda.objects.create(descricao="Mínimo QA", inicio=self.inicio, fim=self.inicio,
            min_noites=3, fechado_chegada=True, fechado_saida=True, criado_por=self.op)
        previa = services.previa_envio(self.cfg)
        noite = next(v for v in previa["linhas"] if v["data"] == self.inicio.isoformat())
        self.assertEqual((noite["livres"], noite["publicar"], noite["min_noites"]), (2, 1, 3))
        self.assertTrue(noite["fechado_chegada"] and noite["fechado_saida"])
        OrdemServico.objects.create(uh=self.uh, titulo="Reparo QA", bloqueia_uh=True,
            bloqueio_inicio=self.inicio, bloqueio_fim=self.inicio, criado_por=self.op)
        noite = next(v for v in services.previa_envio(self.cfg)["linhas"] if v["data"] == self.inicio.isoformat())
        self.assertEqual((noite["livres"], noite["publicar"]), (1, 0))

    def test_previa_nao_consulta_por_noite_e_preco_engloba_tributos(self):
        with CaptureQueriesContext(connection) as curto:
            linhas = services.previa_envio(self.cfg)["linhas"]
        self.assertEqual(linhas[0]["tarifa"], "316.00")
        self.cfg.dias_publicados = 500
        with CaptureQueriesContext(connection) as longo:
            previa = services.previa_envio(self.cfg)
        self.assertLessEqual(len(longo), len(curto)+2)
        self.assertEqual(len(previa["linhas"]), 500)

    def test_painel_integracoes_reflete_conexao_e_nao_substitui_validacao(self):
        from apps.nucleo.models import EnsaioIntegracao
        self.client.force_login(self.op)
        with patch("apps.canais.services.Channex") as http:
            pagina = self.client.get(reverse("integracoes"))
            self.assertContains(pagina, "Validação registrada")
            self.assertNotContains(pagina, "chave-canais-ficticia")
            self.assertNotContains(pagina, "assinatura-producao-ficticia-qa")
            resposta = self.client.post(reverse("integracoes"), {"canal": "canais", "confirmado": "sim",
                "evidencia": "Não substitui a validação de mapeamento do módulo."})
            self.assertContains(resposta, "Complete a configuração real")
            http.assert_not_called()
        self.assertFalse(EnsaioIntegracao.objects.filter(canal="canais").exists())

    def test_tarifas_diferentes_camas_sem_configuracao_e_colchoes_compartilhados_fecham_oferta(self):
        outro_tipo = TipoUH.objects.create(nome="Tarifa distinta QA", tarifa_base="400")
        self.uh2.tipo = outro_tipo
        self.uh2.save()
        self.assertTrue(all(v["publicar"] == 0 for v in services.previa_envio(self.cfg)["linhas"]))
        self.uh2.tipo = self.tipo
        self.uh2.save()
        PosicaoCama.objects.filter(uh=self.uh2).delete()
        self.assertTrue(all(v["publicar"] == 0 for v in services.previa_envio(self.cfg)["linhas"]))
        PosicaoCama.objects.create(uh=self.uh2, nome="Cama QA", ordem=1)
        ConfiguracaoUH.objects.filter(uh__in=[self.uh, self.uh2]).update(max_colchoes_extras=1)
        self.mapa.ocupacao_tarifa = 3
        self.mapa.save()
        services.registrar_validacao(self.cfg, "Conferência fictícia da ocupação com colchão extra.", self.op)
        self.cfg.refresh_from_db()
        previa = services.previa_envio(self.cfg)
        self.assertTrue(all(v["publicar"] == 0 for v in previa["linhas"]))
        self.assertTrue(any("compartilhados" in p for p in previa["pendencias"]))

    def test_incerteza_de_data_de_revisao_e_identidade_repetida_nao_sobrescrevem(self):
        item = self.bruto()
        original = self.capturar(item)
        colidente = self.nova_versao(item)
        colidente["attributes"]["inserted_at"] = item["attributes"]["inserted_at"]
        revisao = self.capturar(colidente)
        self.assertEqual(revisao.estado, RevisaoCanal.Estado.PENDENTE)
        with self.assertRaisesMessage(ValidationError, "mesmo horário"):
            services.aplicar_revisao(revisao, self.op, manual=True)
        original.reserva.refresh_from_db()
        self.assertEqual(original.reserva.ultima_revisao_id, original.pk)
        outro = self.bruto()
        outro["attributes"]["rooms"].append(copy.deepcopy(outro["attributes"]["rooms"][0]))
        outro["attributes"]["amount"] = "1200"
        with self.assertRaisesMessage(ValidationError, "repete a identificação"):
            services.aplicar_revisao(self.capturar(outro), self.op, manual=True)

    def test_vinculo_manual_confere_categoria_valor_e_cancelamento(self):
        from apps.reservas import services as reservas
        rev = self.capturar()
        pessoa = Pessoa.objects.create(nome="Pessoa manual QA")
        outra_uh = self.quarto("Canal-fora-mapa")
        r = reservas.criar_prereserva(uh=outra_uh, checkin=self.inicio, checkout=self.fim,
            hospede=pessoa, usuario=self.op, canal=Reserva.Canal.OTA, valor_diaria="300",
            cobra_iss=False, cobra_taxa_turismo=False)
        r.confirmar(self.op)
        with self.assertRaisesMessage(ValidationError, "categoria"):
            services.resolver_manualmente(rev, [r.pk], "Conferência manual fictícia da categoria e valor.", self.op)
        r.uh = self.uh
        r.valor_diaria = Decimal("325")
        r.valor_hospedagem = Decimal("650")
        r.save()
        with self.assertRaisesMessage(ValidationError, "total previsto"):
            services.resolver_manualmente(rev, [r.pk], "Conferência manual fictícia da categoria e valor.", self.op)
        r.valor_hospedagem = Decimal("600")
        r.valor_diaria = Decimal("300")
        r.save()
        services.resolver_manualmente(rev, [r.pk], "Conferência manual fictícia da categoria e valor.", self.op)
        rev.refresh_from_db()
        self.assertEqual(rev.estado, RevisaoCanal.Estado.CONFERIDA)
        self.assertEqual(list(rev.vinculos_aplicados.values())[0]["reserva_id"], r.pk)

    def test_pedido_de_atualizacao_aguarda_rotina_e_reenvia_sem_fazer_http_na_view(self):
        envio = services.publicar(self.cfg, self.gateway)
        self.client.force_login(self.op)
        with patch("apps.canais.services.Channex") as gateway:
            self.assertEqual(self.client.post(reverse("canais:solicitar", args=[self.cfg.pk])).status_code, 302)
            gateway.assert_not_called()
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.sincronizacao_solicitada)
        services.sincronizar(gateway=self.gateway)
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.sincronizacao_solicitada)
        self.assertNotEqual(self.cfg.envios.first().pk, envio.pk)

    def test_erro_inesperado_na_captura_nao_vaza_dados_e_tenta_fechar_oferta(self):
        self.gateway.revisoes.side_effect = RuntimeError("CHAVE_E_DADOS_PESSOAIS_FICTICIOS")
        with self.assertLogs("apps.canais.services", level="ERROR") as logs:
            resultado = services.sincronizar(gateway=self.gateway)
        self.assertEqual(resultado["estado"], "falha")
        self.assertNotIn("CHAVE_E_DADOS", str(resultado)+str(logs.output))
        self.assertTrue(all(v["availability"] == 0 for v in EnvioCanal.objects.first().dados["disponibilidade"]))

    def test_conferencia_manual_exige_reserva_real_e_preserva_texto_do_formulario(self):
        self.client.force_login(self.op)
        rev = self.capturar()
        resposta = self.client.post(reverse("canais:resolver", args=[rev.pk]), {"reservas": "999999", "motivo": "Conferência fictícia preservada após erro de vínculo."})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Conferência fictícia preservada")
        self.assertContains(resposta, "não existe")
        rev.refresh_from_db()
        self.assertEqual(rev.estado, RevisaoCanal.Estado.RECEBIDA)
        services.aplicar_revisao(rev, self.op)
        outra = self.capturar(self.nova_versao(self.bruto()))
        # O vínculo único impede associar a mesma reserva do PMS a outra origem.
        with self.assertRaisesMessage(ValidationError, "outro quarto ou canal"):
            services.resolver_manualmente(outra, [Reserva.objects.get().pk], "Conferência fictícia de associação entre reservas.", self.op)

    def test_telas_modulo_permissoes_post_e_configuracao_sem_chave_preservam_dados(self):
        self.client.force_login(self.op)
        rev = self.capturar()
        envio = services.publicar(self.cfg, self.gateway)
        nomes = [("painel", []), ("conexao", [self.cfg.pk]), ("conexao_nova", []),
            ("mapeamento", [self.cfg.pk, self.mapa.pk]), ("mapeamento_novo", [self.cfg.pk]),
            ("validacao", [self.cfg.pk]), ("disponibilidade", [self.cfg.pk]),
            ("revisao", [rev.pk]), ("envios", [self.cfg.pk]), ("envio", [envio.pk])]
        for nome, args in nomes:
            with self.subTest(tela=nome):
                self.assertEqual(self.client.get(reverse(f"canais:{nome}", args=args)).status_code, 200)
        self.assertEqual(self.client.get(reverse("canais:solicitar", args=[self.cfg.pk])).status_code, 405)
        sem = Usuario.objects.create_user(username="sem-canais", password="qa-sem-canais")
        self.client.force_login(sem)
        self.assertEqual(self.client.get(reverse("canais:painel")).status_code, 403)
        sem.modulos.set(ModuloContratado.objects.filter(codigo="canais"))
        self.assertEqual(self.client.get(reverse("canais:conexao", args=[self.cfg.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("canais:aplicar", args=[rev.pk])).status_code, 403)
        ModuloContratado.objects.filter(codigo="canais").update(ativo=False)
        self.assertEqual(self.client.get(reverse("canais:painel")).status_code, 404)


@override_settings(CHANNEX_API_KEY="chave-canais-ficticia", CHANNEX_API_KEY_HML="chave-hml-ficticia", CHANNEX_WEBHOOK_SECRET="assinatura-producao-ficticia-qa", CHANNEX_WEBHOOK_SECRET_HML="assinatura-hml-ficticia-qa", CANAIS_HOMOLOGACAO_APLICAR=False)
class CapturaDuravelTests(DadosCanais, TransactionTestCase):
    def test_ack_acontece_apos_commit_e_falha_reprocessa_sem_duplicar(self):
        item = self.bruto()
        self.gateway.revisoes.return_value = [item]
        def falhar(identificador):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(RevisaoCanal.objects.filter(identificador=identificador).exists())
            raise ValidationError("Provedor indisponível para confirmar captura.")
        self.gateway.confirmar_recebimento.side_effect = falhar
        self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "falha")
        self.assertEqual(RevisaoCanal.objects.count(), 1)
        self.assertEqual(Reserva.objects.count(), 1)
        self.gateway.revisoes.side_effect = [[item], []]
        self.gateway.confirmar_recebimento.side_effect = None
        ConfiguracaoCanais.objects.filter(pk=self.cfg.pk).update(proxima_tentativa=None)
        self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "concluido")
        self.assertEqual(RevisaoCanal.objects.count(), 1)
        self.assertEqual(Reserva.objects.count(), 1)

    def test_modulo_inativo_nao_acessa_provedor(self):
        ModuloContratado.objects.filter(codigo="canais").update(ativo=False)
        self.assertEqual(services.sincronizar(gateway=self.gateway)["estado"], "desativado")
        self.gateway.revisoes.assert_not_called()

    def test_duas_aplicacoes_concorrentes_na_ultima_unidade_nao_sobrevendem(self):
        UnidadeMapeada.objects.filter(uh=self.uh2).delete()
        revisoes = [self.capturar(), self.capturar()]
        barreira = Barrier(2)
        def aplicar(pk):
            close_old_connections()
            try:
                rev = RevisaoCanal.objects.get(pk=pk)
                op = Usuario.objects.get(pk=self.op.pk)
                barreira.wait(timeout=10)
                try:
                    services.aplicar_revisao(rev, op, manual=True)
                except ValidationError:
                    return "recusada"
                return "aplicada"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(aplicar, [r.pk for r in revisoes]))
        self.assertCountEqual(resultados, ["aplicada", "recusada"])
        self.assertEqual(Reserva.objects.count(), 1)

    def test_rotina_exclusiva_impede_segundo_worker_e_edicao_durante_http(self):
        entrou, liberar = Event(), Event()
        def feed():
            self.assertFalse(connection.in_atomic_block)
            entrou.set()
            if not liberar.wait(timeout=15):
                raise RuntimeError("Teste não liberou o provedor fictício.")
            return []
        self.gateway.revisoes.side_effect = feed
        def rodar():
            close_old_connections()
            try:
                return services.sincronizar(gateway=self.gateway)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(rodar)
            try:
                self.assertTrue(entrou.wait(timeout=10))
                outro = Mock()
                self.assertEqual(services.sincronizar(gateway=outro)["estado"], "em_andamento")
                outro.revisoes.assert_not_called()
                with self.assertRaisesMessage(ValidationError, "atualizada"):
                    services.salvar_configuracao(self.cfg, self.dados_config(vendas_abertas=False), self.op)
            finally:
                liberar.set()
            self.assertEqual(futuro.result(timeout=15)["estado"], "concluido")
