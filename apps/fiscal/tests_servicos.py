from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.nucleo.models import ModuloContratado
from apps.nucleo.modulos import Modulo
from apps.reservas.models import LancamentoConta

from . import services, servicos, tests
from .models import DocumentoFiscal


class ClassificacaoServicosTests(tests.NfseDaDiariaTests):
    def extra(self, valor="100", codigo=""):
        return LancamentoConta.objects.create(conta=self.conta,tipo="servico",natureza="servico",
            descricao="Serviço auxiliar QA",valor=Decimal(valor),codigo_servico_fiscal=codigo,criado_por=self.op)

    def test_servico_auxiliar_nao_recebe_codigo_de_hospedagem(self):
        extra = self.extra()
        with self.assertRaisesMessage(ValidationError,"Classifique os serviços"):
            services.emitir_nfse_da_conta(self.conta.pk,self.op)
        self.assertFalse(DocumentoFiscal.objects.exists())
        # Código sintético: o contrato exige classificação, não presume código legal.
        servicos.classificar(self.conta.pk,{str(extra.pk):"999999"},self.op)
        LancamentoConta.objects.create(conta=self.conta,tipo="desconto",natureza="servico",
            descricao="Desconto concedido",valor=Decimal("50"),criado_por=self.op)
        hospedagem=services.emitir_nfse_da_conta(self.conta.pk,self.op)
        auxiliar=services.emitir_nfse_da_conta(self.conta.pk,self.op,"999999")
        self.assertEqual(hospedagem.valor,Decimal("360"))
        self.assertEqual(auxiliar.valor,Decimal("90"))
        self.assertEqual(auxiliar.payload["codigo_servico"],"999999")
        self.assertEqual(services.emitir_nfse_da_conta(self.conta.pk,self.op,"999999").pk,auxiliar.pk)
        self.assertEqual(DocumentoFiscal.objects.count(),2)
        with self.assertRaises(ValidationError):
            servicos.classificar(self.conta.pk,{str(extra.pk):"888888"},self.op)

    def test_rateio_de_muitos_centavos_nao_ultrapassa_item(self):
        self.conta.lancamentos.all().delete()
        for i in range(100):
            self.extra(".01",f"{900000+i}")
        LancamentoConta.objects.create(conta=self.conta,tipo="desconto",natureza="servico",
            descricao="Desconto QA",valor=Decimal(".49"),criado_por=self.op)
        resultado=servicos.resumo(self.conta)
        self.assertEqual(sum(g["desconto"] for g in resultado["grupos"]),Decimal(".49"))
        self.assertEqual(sum(g["valor"] for g in resultado["grupos"]),Decimal(".51"))
        self.assertTrue(all(0 <= g["desconto"] <= g["bruto"] for g in resultado["grupos"]))

    def test_preparacao_classifica_emite_e_confere_html(self):
        extra=self.extra()
        ModuloContratado.objects.update_or_create(codigo=Modulo.FISCAL,defaults={"ativo":True})
        self.client.force_login(self.op)
        url=reverse("fiscal:preparar_conta",args=[self.conta.pk])
        self.assertContains(self.client.get(url),"classificar todos os serviços")
        resposta=self.client.post(url,{f"codigo-{extra.pk}":"999999","conferido":"sim"},follow=True)
        self.assertContains(resposta,"Emitir NFS-e")
        extra.refresh_from_db()
        self.assertEqual(extra.codigo_servico_fiscal,"999999")
        resposta=self.client.post(reverse("fiscal:emitir_nfse"),{"conta_id":self.conta.pk,"codigo_servico":"999999"},follow=True)
        self.assertContains(resposta,"Autorizada")
        self.assertEqual(DocumentoFiscal.objects.get().valor,Decimal("100"))

    def test_operador_sem_gerencia_nao_reclassifica(self):
        from django.contrib.auth import get_user_model
        extra=self.extra()
        operador=get_user_model().objects.create_user(username="fiscal-operador")
        with self.assertRaises(ValidationError):
            servicos.classificar(self.conta.pk,{str(extra.pk):"999999"},operador)
        extra.refresh_from_db()
        self.assertEqual(extra.codigo_servico_fiscal,"")
