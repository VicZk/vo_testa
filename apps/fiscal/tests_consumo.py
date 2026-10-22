from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from apps.loja import services as loja
from apps.loja import tests as testes_loja
from apps.nucleo.models import ModuloContratado, Produto, registrar_entrada, saldo
from apps.nucleo.modulos import Modulo

from . import services
from .consumo import emitir_origem, payload_consumo
from .focus import GatewayFocus
from .models import ConfigFiscalProduto, DocumentoFiscal
from .tests_focus import FOCUS


@override_settings(**FOCUS, FISCAL_NFCE_HABILITADA=True)
class ConsumoFiscalTests(testes_loja.LojaBase):
    def setUp(self):
        super().setUp()
        self.abrir_caixa()
        self.configurar(self.produto)
        ModuloContratado.objects.update_or_create(codigo=Modulo.FISCAL, defaults={"ativo": True})

    def configurar(self, produto):
        return ConfigFiscalProduto.objects.create(produto=produto, ncm="22021000", cfop="5102",
            cst_csosn="00", tributos={"pis_situacao_tributaria":"01", "cofins_situacao_tributaria":"01"})

    def venda(self, **extras):
        return loja.finalizar_venda(self.op, self.local, self.itens(), "caixa", forma=self.dinheiro, **extras)

    def test_venda_emite_nfce_com_itens_e_pagamento_sem_nova_baixa(self):
        venda = self.venda(desconto=Decimal("1.01"))
        antes = saldo(self.produto, self.local)
        with patch.object(GatewayFocus, "_req", side_effect=[None, {"status":"autorizado", "numero":"77"}]) as req:
            doc = emitir_origem("venda", venda.pk, self.op)
            repetido = emitir_origem("venda", venda.pk, self.op)
        self.assertEqual(doc.pk, repetido.pk)
        self.assertEqual(doc.valor, Decimal("12.99"))
        self.assertEqual(saldo(self.produto, self.local), antes)
        self.assertEqual(req.call_count, 2)
        metodo, caminho, corpo = req.call_args.args
        self.assertEqual(metodo, "POST")
        self.assertTrue(caminho.startswith("/v2/nfce?ref="))
        self.assertEqual(corpo["items"][0]["valor_desconto"], "1.01")
        self.assertEqual(corpo["formas_pagamento"], [{"forma_pagamento":"01", "valor_pagamento":"12.99"}])
        self.assertEqual(corpo["items"][0]["codigo_ncm"], "22021000")

    def test_ultimo_centavo_do_desconto_fecha_entre_itens(self):
        itens=[]
        for i in range(3):
            produto=Produto.objects.create(nome=f"Produto fictício {i}", categoria=self.cat, preco_venda=1)
            registrar_entrada(produto,self.local,10,Decimal(".50"),self.op)
            self.configurar(produto)
            itens.append({"produto_id":produto.pk,"quantidade":1})
        venda=loja.finalizar_venda(self.op,self.local,itens,"caixa",forma=self.dinheiro,desconto=Decimal(".01"))
        total,dados=payload_consumo(venda)
        self.assertEqual(total,Decimal("2.99"))
        self.assertEqual(sum(Decimal(i["valor_desconto"]) for i in dados["items"]),Decimal(".01"))
        self.assertEqual(sum(Decimal(i["valor_bruto"])-Decimal(i["valor_desconto"]) for i in dados["items"]),total)

    def test_pix_exige_modalidade_sem_inventar_pagamento(self):
        venda=self.venda()
        from apps.nucleo.models import FormaPagamento
        venda.forma_pagamento=FormaPagamento.objects.get(tipo="pix")
        venda.save(update_fields=["forma_pagamento"])
        with patch.object(GatewayFocus,"_req") as req, self.assertRaises(ValidationError):
            emitir_origem("venda",venda.pk,self.op)
        req.assert_not_called()
        self.assertFalse(DocumentoFiscal.objects.exists())
        _,dados=payload_consumo(venda,"20")
        self.assertEqual(dados["formas_pagamento"][0]["forma_pagamento"],"20")
        venda.destino="conta"
        _,dados=payload_consumo(venda)
        self.assertEqual(dados["formas_pagamento"][0]["forma_pagamento"],"91")

    def test_codigo_fiscal_incompleto_e_nfce_desligada_bloqueiam_sem_rede(self):
        venda=self.venda()
        with override_settings(FISCAL_NFCE_HABILITADA=False), self.assertRaises(ValidationError):
            emitir_origem("venda",venda.pk,self.op)
        ConfigFiscalProduto.objects.filter(produto=self.produto).update(ncm="")
        with patch.object(GatewayFocus,"_req") as req, self.assertRaises(ValidationError):
            emitir_origem("venda",venda.pk,self.op)
        req.assert_not_called()
        self.assertFalse(DocumentoFiscal.objects.exists())

    def test_cancelar_venda_com_nfce_ativa_preserva_venda_e_estoque(self):
        venda=self.venda()
        with patch.object(GatewayFocus,"_req",side_effect=[None,{"status":"autorizado","numero":"77"}]):
            doc=emitir_origem("venda",venda.pk,self.op)
        with self.assertRaisesMessage(ValidationError,"documento fiscal"):
            loja.cancelar_venda(venda,self.op,"Cliente desistiu")
        venda.refresh_from_db()
        self.assertEqual(venda.status,"fechada")
        self.assertEqual(saldo(self.produto,self.local),18)
        services.processar_retorno_focus({"ref":doc.gateway_id,"status":"cancelado"})
        loja.cancelar_venda(venda,self.op,"Cancelamento fiscal conciliado")
        self.assertEqual(saldo(self.produto,self.local),20)

    def test_correcao_rejeitada_atualiza_cadastro_mas_preserva_referencia(self):
        venda=self.venda()
        with patch.object(GatewayFocus,"_req",side_effect=[None,{"status":"erro_autorizacao"}]):
            doc=emitir_origem("venda",venda.pk,self.op)
        ConfigFiscalProduto.objects.filter(produto=self.produto).update(cfop="5405")
        with patch.object(GatewayFocus,"_req",side_effect=[{"status":"erro_autorizacao"},{"status":"autorizado","numero":"77"}]) as req:
            atualizado=services.corrigir(doc)
        self.assertEqual(atualizado.pk,doc.pk)
        self.assertEqual(atualizado.gateway_id,doc.gateway_id)
        self.assertEqual(req.call_args.args[2]["items"][0]["cfop"],"5405")
        self.assertEqual(atualizado.status,"autorizada")
        self.assertEqual(DocumentoFiscal.objects.count(),1)
        self.assertEqual(atualizado.eventos.filter(tipo="correcao").count(),1)

    def test_comanda_aberta_bloqueia_e_fechada_emite(self):
        from apps.nucleo.models import SessaoCaixa
        from apps.restaurante import services as restaurante
        from apps.restaurante.models import Mesa
        self.local.modulo="restaurante"
        self.local.save(update_fields=["modulo"])
        SessaoCaixa.objects.create(operador=self.op,modulo="restaurante")
        comanda=restaurante.abrir_comanda(self.op,self.local,mesa=Mesa.objects.create(nome="Mesa fictícia"))
        restaurante.adicionar_item(comanda,self.produto,2,self.op)
        with self.assertRaises(ValidationError):
            emitir_origem("comanda",comanda.pk,self.op)
        restaurante.fechar_comanda(comanda,self.op,"caixa",forma=self.dinheiro)
        with patch.object(GatewayFocus,"_req",side_effect=[None,{"status":"autorizado","numero":"78"}]):
            doc=emitir_origem("comanda",comanda.pk,self.op)
        self.assertEqual(doc.valor,Decimal("14"))
        self.assertEqual(doc.referencia,f"comanda:{comanda.pk}")

    def test_endpoint_respeita_origem_desativada_e_exibe_resultado(self):
        venda=self.venda()
        self.client.force_login(self.op)
        url=reverse("fiscal:emitir_consumo",args=["venda",venda.pk])
        ModuloContratado.objects.update_or_create(codigo=Modulo.LOJA,defaults={"ativo":False})
        self.assertEqual(self.client.post(url).status_code,403)
        ModuloContratado.objects.filter(codigo=Modulo.LOJA).update(ativo=True)
        with patch.object(GatewayFocus,"_req",side_effect=[None,{"status":"autorizado","numero":"77"}]):
            resposta=self.client.post(url,follow=True)
        self.assertContains(resposta,"Autorizada")
        self.assertContains(resposta,"Estimativa CBS")
