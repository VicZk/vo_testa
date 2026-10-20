from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.site.forms import DadosHospedeForm, validar_cpf
from apps.site.models import (
    CategoriaQuarto,
    Hospede,
    Quarto,
    Reserva,
)

CPF_VALIDO = '111.444.777-35'


def criar_quarto(nome='Cabine', capacidade=2, preco='400.00'):
    cat, _ = CategoriaQuarto.objects.get_or_create(nome='Suíte')
    return Quarto.objects.create(
        nome=nome, categoria=cat, descricao='x', descricao_curta='x',
        capacidade=capacidade, metragem=20, preco_base=Decimal(preco),
        status='disponivel',
    )


def criar_reserva(quarto, ci, co, status='confirmada', expira_em=None):
    h = Hospede.objects.create(
        nome='Fulano Teste', email=f'{status}{ci}@ex.com',
        telefone='4999', cpf=None,
    )
    r = Reserva(
        hospede=h, quarto=quarto, data_checkin=ci, data_checkout=co,
        num_hospedes=1, preco_noite=quarto.preco_base, status=status,
    )
    if expira_em is not None:
        r.expira_em = expira_em
    r.save()
    return r


class ModeloReservaTests(TestCase):
    def setUp(self):
        self.quarto = criar_quarto()
        self.ci = date.today() + timedelta(days=10)
        self.co = self.ci + timedelta(days=3)

    def test_codigo_e_token_gerados(self):
        r = criar_reserva(self.quarto, self.ci, self.co)
        self.assertTrue(r.codigo.startswith('VT-'))
        self.assertIsNotNone(r.token)

    def test_expira_em_definido_para_aguardando(self):
        r = criar_reserva(self.quarto, self.ci, self.co, status='aguardando')
        self.assertIsNotNone(r.expira_em)

    def test_confirmada_nao_define_expira(self):
        r = criar_reserva(self.quarto, self.ci, self.co, status='confirmada')
        self.assertIsNone(r.expira_em)

class CpfTests(TestCase):
    def test_cpf_valido(self):
        self.assertEqual(validar_cpf(CPF_VALIDO), '11144477735')

    def test_cpf_invalido_digitos(self):
        form = DadosHospedeForm(data={
            'nome': 'X', 'email': 'a@a.com', 'telefone': '49999990000', 'cpf': '123.456.789-00',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('cpf', form.errors)

    def test_cpf_repetido_invalido(self):
        form = DadosHospedeForm(data={
            'nome': 'X', 'email': 'a@a.com', 'telefone': '49999990000', 'cpf': '111.111.111-11',
        })
        self.assertFalse(form.is_valid())


class FluxoReservaViewTests(TestCase):
    def setUp(self):
        # Rate-limit do site usa LocMemCache (persiste entre testes do processo).
        from django.core.cache import cache
        cache.clear()
        # Fonte da verdade no CRM: um tipo com 1 quarto físico; o card do site aponta pra ele.
        from apps.nucleo.models import UH, TipoUH
        from apps.site.models import VitrineQuarto
        self.tipo = TipoUH.objects.create(
            nome='Suíte', tarifa_base=Decimal('400.00'), capacidade=2,
        )
        self.uh = UH.objects.create(
            numero='S1', tipo=self.tipo, nome_tematico='Cabine do Lago', vista_lago=True,
        )
        # Vitrine por unidade: sem ela o quarto não aparece na venda por quarto.
        self.vitrine = VitrineQuarto.objects.create(
            uh=self.uh, publicar=True, destaque=True, metragem=25,
        )
        self.quarto = criar_quarto()
        self.quarto.tipo_uh = self.tipo
        self.quarto.save(update_fields=['tipo_uh'])
        self.ci = (date.today() + timedelta(days=10)).strftime('%Y-%m-%d')
        self.co = (date.today() + timedelta(days=13)).strftime('%Y-%m-%d')

    def _post_finalizar(self, **over):
        dados = {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Maria Teste',
            'email': 'maria@ex.com', 'telefone': '49999990000', 'cpf': CPF_VALIDO,
            'observacoes': '',
        }
        dados.update(over)
        return self.client.post(reverse('core:finalizar_reserva'), dados)

    def test_finaliza_com_crianca_preco_por_pessoa(self):
        # Fase 6: site aplica pessoa adicional + criança 6-15 meia na diária do CRM.
        self.tipo.capacidade = 5
        self.tipo.pessoa_adicional = Decimal('100.00')
        self.tipo.save(update_fields=['capacidade', 'pessoa_adicional'])
        self.quarto.capacidade = 5
        self.quarto.save(update_fields=['capacidade'])
        self._post_finalizar(hospedes=3, criancas_6_15=1, metodo_pagamento='cartao')
        from apps.reservas.models import Reserva
        r = Reserva.objects.latest('id')
        # adultos = 3 − 1 criança = 2 (base 400) + 1 criança 6-15 (½×100=50) → 450/noite.
        self.assertEqual(r.valor_diaria, Decimal('450.00'))
        self.assertEqual(r.criancas_6_15, 1)
        self.assertTrue(r.cobra_iss)

    def test_finaliza_desmarcando_iss(self):
        self._post_finalizar(metodo_pagamento='cartao', cobra_iss='0')
        from apps.reservas.models import Reserva
        self.assertFalse(Reserva.objects.latest('id').cobra_iss)

    def test_passo1_datas_ok(self):
        self.assertEqual(self.client.get(reverse('core:reservar')).status_code, 200)

    def test_passo2_lista_quartos_por_unidade(self):
        # Venda por unidade: o passo 2 lista o quarto físico (nome temático) e seus
        # diferenciais, com link para reservar aquela UH específica.
        resp = self.client.get(reverse('core:reservar'), {
            'checkin': self.ci, 'checkout': self.co, 'hospedes': 2,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cabine do Lago')
        self.assertContains(resp, 'Vista para o lago')
        self.assertContains(resp, reverse('core:selecionar_unidade', args=[self.uh.pk]))

    def test_deeplink_com_datas_vai_direto_ao_quarto(self):
        resp = self.client.get(reverse('core:reservar'), {
            'uh': self.uh.id, 'checkin': self.ci, 'checkout': self.co, 'hospedes': 2,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('core:selecionar_unidade', args=[self.uh.id]), resp['Location'])

    def test_deeplink_sem_datas_carrega_o_quarto_escolhido(self):
        resp = self.client.get(reverse('core:reservar'), {'uh': self.uh.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cabine do Lago')          # nome temático do quarto
        self.assertContains(resp, 'name="uh" value="%d"' % self.uh.id)  # carregado no form

    def test_quarto_detalhe_abre_pagina_do_quarto(self):
        resp = self.client.get(reverse('core:quarto_detalhe', args=[self.uh.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cabine do Lago')            # nome temático
        self.assertContains(resp, 'Vista para o lago')         # qualidade
        # Botão Reservar leva às datas com o quarto escolhido (deep-link).
        self.assertContains(resp, reverse('core:reservar') + '?uh=%d' % self.uh.id)

    def test_home_card_leva_a_pagina_do_quarto(self):
        resp = self.client.get(reverse('core:home'))
        self.assertContains(resp, reverse('core:quarto_detalhe', args=[self.uh.id]))

    def test_finalizar_por_unidade_reserva_o_quarto_exato(self):
        from apps.reservas.models import Reserva as CrmReserva
        resp = self.client.post(reverse('core:finalizar_reserva'), {
            'uh_id': self.uh.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'João Teste',
            'email': 'joao@ex.com', 'telefone': '49999990000', 'cpf': CPF_VALIDO,
            'observacoes': '',
        })
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertIsNotNone(reserva.crm_reserva_id)
        crm = CrmReserva.objects.get(pk=reserva.crm_reserva_id)
        self.assertEqual(crm.uh, self.uh)  # o quarto EXATO, não "qualquer do tipo"
        self.assertEqual(crm.canal, CrmReserva.Canal.SITE)
        self.assertEqual(crm.status, CrmReserva.Status.PRE_RESERVA)

    def test_finalizar_cria_reserva_no_site_e_no_crm(self):
        from apps.pagamentos.models import Cobranca
        from apps.reservas.models import Reserva as CrmReserva
        resp = self._post_finalizar()
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.status, 'aguardando')
        self.assertIn(str(reserva.token), resp['Location'])
        # A integração: criou a reserva real no CRM (pré-reserva, canal site).
        self.assertIsNotNone(reserva.crm_reserva_id)
        crm = CrmReserva.objects.get(pk=reserva.crm_reserva_id)
        self.assertEqual(crm.status, CrmReserva.Status.PRE_RESERVA)
        self.assertEqual(crm.canal, CrmReserva.Canal.SITE)
        self.assertEqual(crm.uh.tipo, self.tipo)
        # Cobrança de sinal (Pix) ligada ao recibo do site.
        self.assertTrue(reserva.pagamento_id)
        cob = Cobranca.objects.get(token=reserva.pagamento_id)
        self.assertEqual(cob.finalidade, Cobranca.Finalidade.SINAL)
        self.assertEqual(cob.reserva_id, crm.pk)

    def test_confirmada_oferece_pagar_agora(self):
        self._post_finalizar()
        reserva = Reserva.objects.get()
        resp = self.client.get(reverse('core:reserva_confirmada', args=[reserva.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pagar agora')

    def test_resumo_mostra_formas_de_pagamento(self):
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Maria Teste',
            'email': 'maria@ex.com', 'telefone': '49999990000',
            'cpf': CPF_VALIDO, 'observacoes': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Forma de pagamento')
        self.assertContains(resp, 'value="pix"')
        self.assertContains(resp, 'value="cartao"')
        self.assertContains(resp, 'value="boleto"')

    def test_finalizar_com_cartao_cria_cobranca_cartao(self):
        from apps.pagamentos.models import Cobranca
        resp = self._post_finalizar(metodo_pagamento='cartao')
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.get()
        self.assertEqual(reserva.metodo_pagamento, 'cartao')
        self.assertEqual(reserva.desconto_percentual, 0)
        cob = Cobranca.objects.get(token=reserva.pagamento_id)
        self.assertEqual(cob.metodo, Cobranca.Metodo.CARTAO)
        self.assertEqual(cob.valor, reserva.valor_total)

    def test_mesmo_cpf_reutiliza_hospede_e_avanca(self):
        """CPF já cadastrado não bloqueia Continuar — reutiliza o hóspede."""
        from apps.site.models import Hospede
        Hospede.objects.create(
            nome='Gefferson Antigo', email='outro@ex.com',
            telefone='49990000000', cpf='111.444.777-35',
        )
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Hóspede Novo',
            'email': 'hospede.teste@exemplo.com', 'telefone': '49999990000',
            'cpf': '11144477735', 'observacoes': 'Teste',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'já existe')
        self.assertContains(resp, 'Confirmar Reserva')  # passo 4
        self.assertEqual(Hospede.objects.filter(cpf='111.444.777-35').count(), 1)

        # Finalizar atualiza o cadastro existente (mesmo CPF).
        resp = self._post_finalizar(
            nome='Hóspede Novo', email='hospede.teste@exemplo.com',
            telefone='49999990000', cpf='11144477735',
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Hospede.objects.count(), 1)
        h = Hospede.objects.get(cpf='111.444.777-35')
        self.assertEqual(h.email, 'hospede.teste@exemplo.com')
        self.assertEqual(h.nome, 'Hóspede Novo')

    def test_email_e_cpf_em_cadastros_diferentes_unifica(self):
        """Bug real: e-mail num hóspede (CPF lixo) e CPF noutro — Continuar unifica."""
        legado = Hospede.objects.create(
            nome='Legado Email', email='hospede.teste@exemplo.com',
            telefone='49990000000', cpf='vivan',
        )
        por_cpf = Hospede.objects.create(
            nome='Por CPF', email='typo@ex.com',
            telefone='49991111111', cpf='111.444.777-35',
        )
        # Reserva antiga no legado deve migrar para o do CPF.
        ci = date.today() + timedelta(days=40)
        Reserva.objects.create(
            hospede=legado, quarto=self.quarto,
            data_checkin=ci, data_checkout=ci + timedelta(days=2),
            num_hospedes=1, preco_noite=self.quarto.preco_base,
            status='confirmada',
        )
        resp = self.client.post(reverse('core:resumo_reserva'), {
            'quarto_id': self.quarto.id, 'checkin': self.ci, 'checkout': self.co,
            'hospedes': 2, 'metodo_pagamento': 'pix', 'nome': 'Hóspede Teste',
            'email': 'hospede.teste@exemplo.com', 'telefone': '49999990000',
            'cpf': '11144477735', 'observacoes': 'teste 02',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'já existe')
        self.assertContains(resp, 'Confirmar Reserva')
        # Unificação do legado (e-mail) acontece na validação do Continuar.
        self.assertFalse(Hospede.objects.filter(pk=legado.pk).exists())
        self.assertEqual(Reserva.objects.filter(hospede=por_cpf).count(), 1)
        self.assertEqual(Hospede.objects.filter(cpf='111.444.777-35').count(), 1)

        # Finalizar grava o e-mail correto no cadastro do CPF.
        form = DadosHospedeForm(
            data={
                'nome': 'Hóspede Teste', 'email': 'hospede.teste@exemplo.com',
                'telefone': '49999990000', 'cpf': '11144477735', 'observacoes': '',
            },
            instance=por_cpf,
        )
        self.assertTrue(form.is_valid(), form.errors)
        h = form.save()
        self.assertEqual(h.email, 'hospede.teste@exemplo.com')
        self.assertEqual(h.pk, por_cpf.pk)

    def test_finalizar_envia_email_de_confirmacao(self):
        from django.core import mail
        self._post_finalizar()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('maria@ex.com', mail.outbox[0].to)
        self.assertIn('Reserva', mail.outbox[0].subject)
        reserva = Reserva.objects.get()
        self.assertIn(f'/reserva/{reserva.token}/', mail.outbox[0].body)
        html = mail.outbox[0].alternatives[0][0]
        self.assertTrue(
            'Ver reserva' in html or 'Ver minha reserva' in html,
            html[:200],
        )
        self.assertIn('cid:email-hero', html)

    def test_confirmacao_por_token_ok(self):
        self._post_finalizar()
        reserva = Reserva.objects.get()
        resp = self.client.get(reverse('core:reserva_confirmada', args=[reserva.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reserva.codigo)

    def test_finalizar_bloqueia_conflito(self):
        # Só há 1 quarto físico do tipo → a 2ª reserva no mesmo período é barrada pelo CRM.
        self._post_finalizar()
        resp = self._post_finalizar(email='outro@ex.com')
        self.assertEqual(Reserva.objects.count(), 1)
        self.assertEqual(resp.status_code, 302)

    def test_endpoint_buscar_hospede_removido(self):
        # S1: o endpoint que vazava CPF por email não existe mais.
        resp = self.client.get('/reservar/hospede/', {'email': 'maria@ex.com'})
        self.assertEqual(resp.status_code, 404)

    def test_dia_na_pousada_no_fluxo_reservar(self):
        from apps.nucleo.models import UH, TipoUH
        from apps.reservas.models import Reserva as CrmReserva
        from apps.site.models import CategoriaQuarto
        tipo = TipoUH.objects.get(nome='Dia na Pousada')
        self.assertEqual(tipo.modalidade, 'day_use')
        self.assertTrue(UH.objects.filter(tipo=tipo).exists())
        cat, _ = CategoriaQuarto.objects.get_or_create(nome='Dia na Pousada')
        quarto, _ = Quarto.objects.get_or_create(
            tipo_uh=tipo,
            defaults={
                'nome': 'Dia na Pousada', 'categoria': cat,
                'descricao': 'x', 'descricao_curta': 'x',
                'capacidade': 10, 'metragem': 0, 'preco_base': tipo.tarifa_base,
                'status': 'disponivel', 'destaque': True,
            },
        )
        ci = (date.today() + timedelta(days=15)).strftime('%Y-%m-%d')
        resp = self.client.get(reverse('core:reservar'), {
            'checkin': ci, 'hospedes': 2, 'modalidade': 'day_use',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dia na Pousada')
        co = (date.today() + timedelta(days=16)).strftime('%Y-%m-%d')
        resp = self.client.post(reverse('core:finalizar_reserva'), {
            'quarto_id': quarto.id, 'checkin': ci, 'checkout': co,
            'hospedes': 2, 'modalidade': 'day_use', 'metodo_pagamento': 'pix',
            'nome': 'Day User', 'email': 'day@ex.com', 'telefone': '49999990000',
            'cpf': CPF_VALIDO, 'observacoes': '',
        })
        self.assertEqual(resp.status_code, 302)
        reserva = Reserva.objects.latest('id')
        crm = CrmReserva.objects.get(pk=reserva.crm_reserva_id)
        self.assertEqual(crm.uh.tipo.modalidade, 'day_use')


class EventosEHomeTests(TestCase):
    def test_home_tem_secoes_eventos_e_dia(self):
        resp = self.client.get(reverse('core:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="eventos"')
        self.assertContains(resp, 'id="dia-pousada"')
        self.assertContains(resp, 'Dia na Pousada')

    def test_proposta_evento_cria_oportunidade(self):
        from apps.comercial.models import Oportunidade
        r = self.client.post(reverse('core:pedir_proposta'), {
            'nome': 'Empresa XPTO',
            'telefone': '49999887766',
            'email': 'evento@xpto.com',
            'tipo_interesse': 'evento',
            'hospedes': '30',
            'mensagem': 'Confraternização de fim de ano',
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('proposta=ok', r['Location'])
        self.assertIn('#eventos', r['Location'])
        op = Oportunidade.objects.get(pessoa__email='evento@xpto.com')
        self.assertEqual(op.tipo_interesse, 'evento')
        self.assertIn('Evento', op.titulo)

    def test_proposta_de_robo_finge_sucesso_e_nao_cria_lead(self):
        from apps.comercial.models import Oportunidade
        from apps.nucleo.antirrobo import CAMPO_ARMADILHA, CAMPO_CARIMBO, carimbo
        base = {'nome': 'Robô', 'telefone': '49999887766', 'email': 'robo@x.com',
                'tipo_interesse': 'hospedagem'}
        r = self.client.post(reverse('core:pedir_proposta'), {**base, CAMPO_ARMADILHA: 'ACME'})
        self.assertIn('proposta=ok', r['Location'])
        # Carimbo de agora: rápido demais para ser gente.
        self.client.post(reverse('core:pedir_proposta'), {**base, CAMPO_CARIMBO: carimbo()})
        self.assertFalse(Oportunidade.objects.filter(pessoa__email='robo@x.com').exists())

    def test_formulario_traz_os_campos_antirrobo(self):
        from apps.nucleo.antirrobo import CAMPO_ARMADILHA, CAMPO_CARIMBO
        html = self.client.get(reverse('core:home')).content.decode()
        self.assertIn(f'name="{CAMPO_ARMADILHA}"', html)
        self.assertIn(f'name="{CAMPO_CARIMBO}"', html)

    def test_proposta_evento_aceita_mesmo_dia(self):
        from apps.comercial.models import Oportunidade
        r = self.client.post(reverse('core:pedir_proposta'), {
            'nome': 'Festa Único Dia',
            'telefone': '49999112233',
            'email': 'festa@dia.com',
            'tipo_interesse': 'evento',
            'checkin': '2026-12-20',
            'checkout': '2026-12-20',
            'hospedes': '40',
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('proposta=ok', r['Location'])
        self.assertTrue(Oportunidade.objects.filter(pessoa__email='festa@dia.com').exists())

    def test_proposta_hospedagem_rejeita_mesmo_dia(self):
        r = self.client.post(reverse('core:pedir_proposta'), {
            'nome': 'Casal',
            'telefone': '4999112244',
            'email': 'casal@noite.com',
            'tipo_interesse': 'hospedagem',
            'checkin': '2026-12-20',
            'checkout': '2026-12-20',
            'hospedes': '2',
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn('proposta=erro', r['Location'])


class MinhaReservaTests(TestCase):
    def setUp(self):
        self.quarto = criar_quarto()
        ci = date.today() + timedelta(days=10)
        self.reserva = criar_reserva(self.quarto, ci, ci + timedelta(days=2))  # hóspede "Fulano Teste"

    def test_pagina_abre(self):
        r = self.client.get(reverse('core:minha_reserva'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Minha reserva')

    def test_sobrenome_e_codigo_corretos_levam_a_area_do_hospede(self):
        r = self.client.post(reverse('core:minha_reserva'), {
            'sobrenome': 'Teste', 'codigo': self.reserva.codigo,
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('core:minha_reserva_detalhe', args=[self.reserva.token]))

    def test_area_do_hospede_mostra_a_reserva(self):
        r = self.client.get(reverse('core:minha_reserva_detalhe', args=[self.reserva.token]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.reserva.codigo)
        self.assertContains(r, self.reserva.quarto.nome)

    def test_codigo_minusculo_normaliza(self):
        r = self.client.post(reverse('core:minha_reserva'), {
            'sobrenome': 'teste', 'codigo': self.reserva.codigo.lower(),
        })
        self.assertEqual(r.status_code, 302)

    def test_sobrenome_errado_nao_acessa(self):
        r = self.client.post(reverse('core:minha_reserva'), {
            'sobrenome': 'Outro', 'codigo': self.reserva.codigo,
        })
        self.assertEqual(r.status_code, 200)  # sem redirect
        self.assertContains(r, 'Não encontramos')

    def test_pedaco_do_nome_nao_acessa(self):
        # Antes uma letra que aparecesse no nome bastava como "sobrenome".
        for tentativa in ('e', 'Tes', 'Fulano'):
            r = self.client.post(reverse('core:minha_reserva'), {
                'sobrenome': tentativa, 'codigo': self.reserva.codigo,
            })
            self.assertEqual(r.status_code, 200, tentativa)

    def test_sobrenome_sem_acento_e_composto(self):
        from .views import _sobrenome_confere
        self.assertTrue(_sobrenome_confere('conceicao', 'Maria da Conceição Souza'))
        self.assertTrue(_sobrenome_confere('Souza', 'Maria da Conceição Souza'))
        self.assertTrue(_sobrenome_confere('da Conceição Souza', 'Maria da Conceição Souza'))
        self.assertFalse(_sobrenome_confere('Maria', 'Maria da Conceição Souza'))

    def test_codigo_inexistente_nao_vaza(self):
        r = self.client.post(reverse('core:minha_reserva'), {
            'sobrenome': 'Teste', 'codigo': 'VT-000000-0000',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Não encontramos')

    def test_logins_tem_voltar_ao_site(self):
        # Ambos os logins têm apenas «Voltar ao site» (sem cross-links).
        for nome in ('login', 'core:minha_reserva'):
            r = self.client.get(reverse(nome))
            self.assertContains(r, 'Voltar ao site')
            self.assertContains(r, reverse('core:home'))


class SeoTests(TestCase):
    """Pacote SEO: robots, llms, sitemap, meta tags e GA4 condicional."""

    def test_robots_bloqueia_crm_e_aponta_sitemap(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        corpo = r.content.decode()
        self.assertIn("Disallow: /crm/", corpo)
        self.assertIn("Disallow: /hospede/", corpo)
        self.assertIn("Sitemap:", corpo)

    def test_llms_txt(self):
        r = self.client.get("/llms.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Pousada Vô Testa", r.content.decode())

    def test_sitemap_lista_paginas(self):
        r = self.client.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<loc>", r.content.decode())

    def test_home_tem_meta_description_e_canonical(self):
        html = self.client.get("/").content.decode()
        self.assertIn('name="description"', html)
        self.assertIn('rel="canonical"', html)

    def test_ga4_so_carrega_com_id(self):
        self.assertNotIn("googletagmanager", self.client.get("/").content.decode())
        with self.settings(GA_MEASUREMENT_ID="G-TESTE123"):
            html = self.client.get("/").content.decode()
            self.assertIn("G-TESTE123", html)


class PaginasLegaisTests(TestCase):
    """Páginas legais públicas (privacidade/termos/exclusão) p/ o app Meta/WhatsApp."""

    def test_paginas_legais_abrem_e_tem_chrome(self):
        for nome, trecho in [
            ("core:politica_privacidade", "Política de Privacidade"),
            ("core:termos_servico", "Termos de Serviço"),
            ("core:exclusao_dados", "Exclusão de dados"),
        ]:
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 200)
            html = r.content.decode()
            self.assertIn(trecho, html)
            self.assertIn("comercial@pousadavotesta.com.br", html)  # contato/DPO no rodapé

    def test_termos_tem_ancora_de_cancelamento(self):
        html = self.client.get(reverse("core:termos_servico")).content.decode()
        self.assertIn('id="cancelamento"', html)

    def test_exclusao_tem_whatsapp_e_sem_contato_duplicado(self):
        html = self.client.get(reverse("core:exclusao_dados")).content.decode()
        self.assertIn("wa.me/554920550005", html)            # WhatsApp clicável
        self.assertIn("(49) 2055-0005", html)
        self.assertNotIn("Dúvidas sobre o processo", html)   # seção Contato redundante removida

    def test_whatsapp_nas_tres_paginas_legais(self):
        for nome in ("core:politica_privacidade", "core:termos_servico", "core:exclusao_dados"):
            html = self.client.get(reverse(nome)).content.decode()
            self.assertIn("wa.me/554920550005", html)
            self.assertIn("(49) 2055-0005", html)

    def test_home_serve_o_index_por_padrao(self):
        # Sem HOME_MODO=lp_fundador, a raiz é o index do site (não a LP).
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)


class ConfirmacaoDepoisDoCommitTests(TestCase):
    """Cobrança e e-mail vêm depois da reserva gravada; falha deles não derruba a reserva."""

    setUp = FluxoReservaViewTests.setUp
    _post_finalizar = FluxoReservaViewTests._post_finalizar

    def test_confirmacao_enviada_fica_marcada(self):
        self._post_finalizar()
        self.assertIsNotNone(Reserva.objects.get().confirmacao_enviada_em)

    def test_erro_inesperado_do_gateway_nao_derruba_a_reserva(self):
        from unittest import mock

        with mock.patch("apps.pagamentos.services.criar_cobranca",
                        side_effect=RuntimeError("gateway não respondeu")), \
                self.assertLogs("apps.site.views", "ERROR"):
            resp = self._post_finalizar(metodo_pagamento='cartao')
        reserva = Reserva.objects.get()
        self.assertRedirects(resp, reverse('core:reserva_confirmada', args=[reserva.token]),
                             fetch_redirect_response=False)
        self.assertEqual(reserva.pagamento_id, '')

    def test_smtp_fora_deixa_sem_marca_e_o_backstop_reenvia(self):
        from io import StringIO
        from unittest import mock

        from django.core import mail
        from django.core.management import call_command

        with mock.patch("apps.site.emails.EmailMultiAlternatives.send",
                        side_effect=OSError("SMTP fora")), \
                self.assertLogs("apps.site.emails", "ERROR"):
            self._post_finalizar()
        reserva = Reserva.objects.get()
        self.assertIsNone(reserva.confirmacao_enviada_em)
        Reserva.objects.filter(pk=reserva.pk).update(
            criado_em=timezone.now() - timedelta(minutes=15))
        mail.outbox.clear()
        call_command("reenviar_confirmacoes_site", stdout=StringIO())
        reserva.refresh_from_db()
        self.assertIsNotNone(reserva.confirmacao_enviada_em)
        self.assertEqual(len(mail.outbox), 1)

    def test_backstop_nao_reenvia_o_que_ja_saiu(self):
        from io import StringIO

        from django.core import mail
        from django.core.management import call_command

        self._post_finalizar()
        Reserva.objects.update(criado_em=timezone.now() - timedelta(minutes=15))
        mail.outbox.clear()
        call_command("reenviar_confirmacoes_site", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)


class BuscaSemConsultaPorQuartoTests(TestCase):
    """A busca do site não faz consultas por quarto × noite (antes: 334 para 3 noites)."""

    def setUp(self):
        from apps.nucleo.models import Temporada as TemporadaCRM
        from apps.nucleo.models import TipoUH

        self.tipo = TipoUH.objects.create(nome='Suíte', tarifa_base=Decimal('300.00'),
                                          capacidade=4)
        self.ci = date.today() + timedelta(days=30)
        TemporadaCRM.objects.create(nome='Alta de verão', classificacao='alta',
                                    inicio=self.ci, fim=self.ci + timedelta(days=10))
        self._quartos(2)

    def _quartos(self, n):
        from apps.nucleo.models import UH
        from apps.reservas.models import TarifaUnidade
        from apps.site.models import VitrineQuarto

        inicio = UH.objects.count()
        for i in range(inicio, inicio + n):
            uh = UH.objects.create(numero=f'Q{i:02d}', tipo=self.tipo)
            VitrineQuarto.objects.create(uh=uh, publicar=True)
            TarifaUnidade.objects.create(uh=uh, classificacao='alta', valor=Decimal('450.00'))

    def _consultas(self, noites):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.site.views import _buscar_unidades

        co = self.ci + timedelta(days=noites)
        _buscar_unidades(self.ci, co, 2)  # aquece o que só roda uma vez (config, pool)
        with CaptureQueriesContext(connection) as ctx:
            resultados = _buscar_unidades(self.ci, co, 2)
        return len(ctx.captured_queries), resultados

    def test_consultas_nao_crescem_com_o_numero_de_quartos(self):
        com_2, _ = self._consultas(3)
        self._quartos(6)
        com_8, resultados = self._consultas(3)
        self.assertEqual(len(resultados), 8)
        self.assertEqual(com_2, com_8)

    def test_cada_noite_a_mais_custa_no_maximo_uma_consulta(self):
        from apps.reservas import services as reservas

        tres, _ = self._consultas(3)
        sete, resultados = self._consultas(7)
        self.assertLessEqual(sete - tres, 4)
        # O preço é o mesmo do cálculo sem memória (o período pode pegar feriado).
        uh = resultados[0]['quarto']
        from apps.nucleo.models import UH
        esperado = reservas.diaria_media_unidade(
            UH.objects.get(pk=uh.uh_id), self.ci, self.ci + timedelta(days=7))
        self.assertEqual(resultados[0]['preco_noite'], esperado)

    def test_selo_da_temporada_vem_do_crm(self):
        from apps.site.views import _temporada_de

        selo = _temporada_de(self.ci)
        self.assertEqual(selo.get_tipo_display, 'Alta Temporada')
        self.assertEqual(selo.nome, 'Alta de verão')
        self.assertIsNone(_temporada_de(self.ci + timedelta(days=60)))


class DadosEstruturadosTests(TestCase):
    """JSON-LD da pousada na home (ficha de hospedagem do Google)."""

    def test_home_tem_lodgingbusiness_valido(self):
        import json
        import re

        html = self.client.get("/").content.decode()
        achado = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.S
        )
        self.assertIsNotNone(achado, "home sem JSON-LD")
        dados = json.loads(achado.group(1))        # falha se o JSON sair quebrado
        self.assertEqual(dados["@type"], "LodgingBusiness")
        self.assertEqual(dados["numberOfRooms"], 24)
        self.assertEqual(dados["address"]["addressLocality"], "Itá")
        self.assertEqual(dados["address"]["addressRegion"], "SC")
        self.assertIn("priceRange", dados)
        self.assertTrue(dados["telephone"])

    def test_json_ld_nao_deixa_fechar_o_script(self):
        """Endereço com HTML colado no painel não pode escapar do <script>."""
        import json
        import re

        from apps.site.models import ConfiguracaoSite

        cfg = ConfiguracaoSite.load()
        cfg.endereco = "Rua X </script><script>alert(1)</script>"
        cfg.save()
        html = self.client.get("/").content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn(r"\u003C/script\u003E", html)
        # E o Google lê o endereço de volta, sem perder nada.
        achado = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        dados = json.loads(achado.group(1))
        self.assertEqual(dados["address"]["streetAddress"], cfg.endereco)


class SitemapQuartosTests(TestCase):
    """A vitrine e as páginas de quarto são o conteúdo que ranqueia — tinham de
    estar no sitemap."""

    def _publicar_quarto(self):
        from apps.nucleo.models import TipoUH as TipoUHCrm
        from apps.nucleo.models import UH
        from apps.site.models import VitrineQuarto

        tipo = TipoUHCrm.objects.create(nome="Suíte Lago", tarifa_base=Decimal("300"))
        uh = UH.objects.create(numero="Quarto 07", tipo=tipo, nome_tematico="Vista do Lago")
        return VitrineQuarto.objects.create(uh=uh, publicar=True, destaque=True)

    def test_sitemap_tem_vitrine_e_quartos_publicados(self):
        vitrine = self._publicar_quarto()
        corpo = self.client.get("/sitemap.xml").content.decode()
        self.assertIn(reverse("core:quartos_todos"), corpo)
        self.assertIn(reverse("core:quarto_detalhe", args=[vitrine.uh_id]), corpo)

    def test_quarto_nao_publicado_fica_fora(self):
        vitrine = self._publicar_quarto()
        vitrine.publicar = False
        vitrine.save()
        corpo = self.client.get("/sitemap.xml").content.decode()
        self.assertNotIn(reverse("core:quarto_detalhe", args=[vitrine.uh_id]), corpo)


class ProvaSocialLgpdTests(TestCase):
    """A notificação flutuante mostrava o primeiro nome de quem acabou de
    reservar em toda página do site — dado pessoal exposto sem necessidade."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.quarto = criar_quarto(nome="Cabana do Vô")
        hoje = date.today()
        criar_reserva(self.quarto, hoje + timedelta(days=5), hoje + timedelta(days=7))

    def test_nao_mostra_o_nome_do_hospede(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Nova reserva", html)
        self.assertNotIn("Fulano", html)

    def test_consulta_fica_em_cache(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        self.client.get("/")                       # aquece o cache
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/")
        sql = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("core_reserva", sql)


class ConsentimentoTests(TestCase):
    """LGPD: nada de medição carrega antes do "Aceitar"."""

    def test_banner_na_home_com_recusar_e_politica(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="consentimento"', html)
        self.assertIn("data-consent-aceitar", html)
        self.assertIn("data-consent-recusar", html)
        self.assertIn(reverse("core:politica_privacidade"), html)

    def test_ga4_nasce_desligado(self):
        with self.settings(GA_MEASUREMENT_ID="G-TESTE123"):
            html = self.client.get("/").content.decode()
        self.assertIn("G-TESTE123", html)
        # A tag está na página, mas como text/plain: o navegador não executa.
        self.assertIn('type="text/plain" data-consentimento', html)
        self.assertNotIn('<script async src="https://www.googletagmanager.com', html)


class DesempenhoHomeTests(TestCase):
    """Peso da home: WebP com width/height, prioridade no logo do hero e
    Flatpickr só onde há calendário."""

    def test_logos_em_webp_com_dimensoes(self):
        html = self.client.get("/").content.decode()
        self.assertIn("logo-hero.webp", html)
        self.assertIn('fetchpriority="high"', html)
        self.assertNotIn("logo-hero.png", html)
        self.assertIn('width="799" height="560"', html)

    def test_imagem_abaixo_da_dobra_e_lazy(self):
        html = self.client.get("/").content.decode()
        self.assertIn("logo-footer.webp", html)
        self.assertIn('loading="lazy"', html)

    def test_flatpickr_so_onde_tem_calendario(self):
        self.assertIn("flatpickr", self.client.get("/").content.decode())
        legal = self.client.get(reverse("core:politica_privacidade")).content.decode()
        self.assertNotIn("flatpickr", legal)

    def test_htmx_do_site_nao_bloqueia_a_pintura(self):
        html = self.client.get("/").content.decode()
        self.assertIn("htmx.min.js", html)
        for linha in html.splitlines():
            if "htmx.min.js" in linha:
                self.assertIn("defer", linha)

    def test_fontes_da_marca_com_preload(self):
        html = self.client.get("/").content.decode()
        self.assertIn('rel="preload"', html)
        self.assertIn("Neco-Regular.woff2", html)


class RotuloDeCampoTests(TestCase):
    """Rótulo tem de apontar para o campo (clique no texto foca o campo)."""

    def test_hero_liga_rotulos_aos_campos(self):
        html = self.client.get("/").content.decode()
        for campo in ("hero-checkin", "hero-checkout", "hero-hospedes"):
            self.assertIn(f'for="{campo}"', html)
            self.assertIn(f'id="{campo}"', html)


class HorariosDaPousadaTests(TestCase):
    """Os horários de entrada e saída vêm da Tabela de Preços (CRM)."""

    def setUp(self):
        import datetime

        from apps.nucleo.models import ConfiguracaoReservas
        cfg = ConfiguracaoReservas.carregar()
        cfg.hora_checkin, cfg.hora_checkout = datetime.time(15, 0), datetime.time(11, 0)
        cfg.save()
        self.quarto = criar_quarto()
        ci = date.today() + timedelta(days=10)
        self.reserva = criar_reserva(self.quarto, ci, ci + timedelta(days=2))

    def test_email_usa_os_horarios_configurados(self):
        from .emails import _ctx_confirmacao
        ctx = _ctx_confirmacao(self.reserva)
        self.assertIn("15:00", ctx["chegada"])
        self.assertIn("11:00", ctx["partida"])

    def test_confirmacao_mostra_os_horarios(self):
        r = self.client.get(reverse('core:reserva_confirmada', args=[self.reserva.token]))
        self.assertContains(r, "a partir das 15:00")
        self.assertContains(r, "até 11:00")


class EncarregadoLGPDTests(TestCase):
    def test_politicas_mostram_o_encarregado_configurado(self):
        with self.settings(LGPD_ENCARREGADO_NOME="Maria Dados",
                           LGPD_ENCARREGADO_EMAIL="dados@pousada.test"):
            site = self.client.get(reverse("core:politica_privacidade"))
            self.assertContains(site, "Maria Dados")
            self.assertContains(site, "mailto:dados@pousada.test")
            lp = self.client.get("/privacidade/")
            self.assertContains(lp, "Maria Dados")
