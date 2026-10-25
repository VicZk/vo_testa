"""As telas da Lavanderia pelo lado da view: o que chega no contexto e o que o POST faz.

O desenho das cinco telas entra depois; aqui ficam as garantias que não dependem do HTML
novo — filtro da fila, cobrança só do que está pronto, conserto do "Serviço salvo." que
não salvava, lote da rouparia e o extrato (quadro já existente) com o motivo traduzido.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.nucleo.models import FormaPagamento, ModuloContratado, SessaoCaixa
from apps.nucleo.modulos import Modulo

from . import services
from .models import ItemEnxoval, MovimentoEnxoval, OrdemLavanderia, ServicoLavanderia

Usuario = get_user_model()


class TelaBase(TestCase):
    def setUp(self):
        self.op = Usuario.objects.create_superuser(username="lav-tela",
                                                   password="senha-forte-123")
        self.client.force_login(self.op)
        self.camisa = ServicoLavanderia.objects.create(nome="Camisa social",
                                                       preco=Decimal("8.00"))
        self.hoje = timezone.localdate()

    def ordem(self, rotulo="Quarto 12", prazo=None, pecas=2):
        ordem = services.abrir_ordem(self.op, rotulo=rotulo, prazo=prazo)
        if pecas:
            services.adicionar_item(ordem, self.camisa, pecas, self.op)
        return ordem


class PainelDaFilaTests(TelaBase):
    def test_painel_entrega_kpis_filas_chips_e_prazos(self):
        atrasada = self.ordem(rotulo="Quarto 2", prazo=self.hoje - timedelta(days=3))
        resposta = self.client.get(reverse("lavanderia:painel"))
        self.assertEqual(resposta.status_code, 200)
        contexto = resposta.context
        self.assertEqual(contexto["kpis"]["atrasadas"], 1)
        # "Lavando" não vira "Lavandos": o chip não leva plural automático.
        self.assertEqual([chip["rotulo"] for chip in contexto["chips"]],
                         ["Todas", "Recebidas", "Lavando", "Prontas", "Atrasadas"])
        self.assertTrue(contexto["chips"][-1]["perigo"])
        self.assertEqual([prazo["rotulo"] for prazo in contexto["prazos"]],
                         ["Hoje", "Amanhã", "Em 2 dias"])
        recebidas = contexto["filas"][0]
        self.assertEqual([o.pk for o in recebidas["ordens"]], [atrasada.pk])
        self.assertEqual(recebidas["ordens"][0].dias_atraso, 3)

    def test_filtro_por_etapa_vem_do_endereco(self):
        lavando = self.ordem(rotulo="Quarto 3")
        services.avancar_status(lavando)
        self.ordem(rotulo="Quarto 4")
        resposta = self.client.get(reverse("lavanderia:painel"), {"etapa": "lavando"})
        self.assertEqual(resposta.context["etapa"], "lavando")
        self.assertEqual([fila["codigo"] for fila in resposta.context["filas"]], ["lavando"])
        self.assertEqual([o.pk for fila in resposta.context["filas"]
                          for o in fila["ordens"]], [lavando.pk])

    def test_etapa_inventada_cai_na_fila_inteira(self):
        self.ordem()
        resposta = self.client.get(reverse("lavanderia:painel"), {"etapa": "chutada"})
        self.assertEqual(resposta.context["etapa"], "")
        self.assertEqual(len(resposta.context["filas"]), 3)

    def test_receber_roupa_aceita_o_chip_de_prazo(self):
        amanha = self.hoje + timedelta(days=1)
        resposta = self.client.post(reverse("lavanderia:abrir"),
                                    {"rotulo": "Quarto 9", "prazo": amanha.isoformat()})
        ordem = OrdemLavanderia.objects.get(rotulo="Quarto 9")
        self.assertRedirects(resposta, reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertEqual(ordem.prazo, amanha)

    def test_receber_roupa_aceita_outra_data(self):
        depois = self.hoje + timedelta(days=5)
        self.client.post(reverse("lavanderia:abrir"),
                         {"rotulo": "Quarto 10", "prazo": "", "prazo_data": depois.isoformat()})
        self.assertEqual(OrdemLavanderia.objects.get(rotulo="Quarto 10").prazo, depois)


class TelaDaOrdemTests(TelaBase):
    def setUp(self):
        super().setUp()
        SessaoCaixa.objects.create(operador=self.op, modulo="lavanderia",
                                   fundo_troco=Decimal("0.00"))
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")

    def test_contexto_tem_trilha_proximo_passo_e_recado(self):
        resposta = self.client.get(reverse("lavanderia:ordem", args=[self.ordem().pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["trilha"]), 4)
        self.assertEqual(resposta.context["proximo"]["rotulo"], "Enviar para lavagem")
        self.assertFalse(resposta.context["pode_entregar"])
        self.assertIn("já está pronta", resposta.context["recado"])

    def test_avancar_com_etapa_vencida_avisa_em_vez_de_pular(self):
        ordem = self.ordem()
        url = reverse("lavanderia:avancar", args=[ordem.pk])
        self.client.post(url, {"de": "recebida"})
        resposta = self.client.post(url, {"de": "recebida"}, follow=True)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.LAVANDO)
        self.assertContains(resposta, "alterada em outra sessão")

    def test_avancar_sem_a_etapa_da_tela_recusa(self):
        """Sem o `de`, o service compararia o status com ele mesmo e a proteção de
        duplo clique virava enfeite: página velha em cache levava «recebida» a
        «pronta» em dois POSTs."""
        ordem = self.ordem()
        resposta = self.client.post(reverse("lavanderia:avancar", args=[ordem.pk]), {},
                                    follow=True)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.RECEBIDA)
        self.assertContains(resposta, "Atualize a tela")

    def test_avancar_pelo_cartao_volta_para_a_fila_com_o_filtro(self):
        """O botão do cartão existe para a fila andar sem abrir a ordem: avançar oito
        quartos no tablet são oito toques, não oito idas e voltas."""
        ordem = self.ordem(rotulo="Quarto 15")
        resposta = self.client.post(reverse("lavanderia:avancar", args=[ordem.pk]),
                                    {"de": "recebida", "voltar": "painel",
                                     "etapa": "recebida"})
        self.assertRedirects(resposta,
                             f"{reverse('lavanderia:painel')}?etapa=recebida")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.LAVANDO)
        # Etapa inventada não entra na querystring.
        servicos_ordem = self.ordem(rotulo="Quarto 16")
        sem_etapa = self.client.post(
            reverse("lavanderia:avancar", args=[servicos_ordem.pk]),
            {"de": "recebida", "voltar": "painel", "etapa": "chutada"})
        self.assertRedirects(sem_etapa, reverse("lavanderia:painel"))

    def test_ordem_vazia_mostra_o_passo_apagado_e_nao_avanca(self):
        vazia = services.abrir_ordem(self.op, rotulo="Quarto 17")
        tela = self.client.get(reverse("lavanderia:ordem", args=[vazia.pk]))
        self.assertTrue(tela.context["vazia"])
        self.assertContains(tela, "Lance ao menos uma peça")
        self.assertContains(tela, "disabled")
        resposta = self.client.post(reverse("lavanderia:avancar", args=[vazia.pk]),
                                    {"de": "recebida"}, follow=True)
        vazia.refresh_from_db()
        self.assertEqual(vazia.status, OrdemLavanderia.Status.RECEBIDA)
        self.assertContains(resposta, "ao menos uma peça")

    def test_entregar_sem_estar_pronta_avisa_e_nao_cobra(self):
        ordem = self.ordem()
        resposta = self.client.post(reverse("lavanderia:entregar", args=[ordem.pk]),
                                    {"destino": "caixa", "forma": self.dinheiro.pk},
                                    follow=True)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.RECEBIDA)
        self.assertIsNone(ordem.movimento_caixa)
        self.assertContains(resposta, "ainda não está pronta")

    def test_entregar_antecipada_confirmada_cobra(self):
        ordem = self.ordem()
        self.client.post(reverse("lavanderia:entregar", args=[ordem.pk]),
                         {"destino": "caixa", "forma": self.dinheiro.pk, "confirmar": "1"})
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.ENTREGUE)
        self.assertEqual(ordem.movimento_caixa.valor, Decimal("16.00"))

    def test_stepper_define_a_quantidade_e_zero_remove(self):
        ordem = self.ordem()
        item = ordem.itens.get()
        url = reverse("lavanderia:item_qtd", args=[ordem.pk, item.pk])
        self.assertEqual(self.client.post(url, {"quantidade": "3"}).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantidade, Decimal("3"))
        self.client.post(url, {"quantidade": "0"})
        self.assertEqual(ordem.itens.count(), 0)

    def test_quilo_entra_com_casa_decimal_pela_grade(self):
        quilo = ServicoLavanderia.objects.create(
            nome="Roupa por quilo", preco=Decimal("22.00"),
            unidade=ServicoLavanderia.Unidade.KG)
        ordem = self.ordem(pecas=0)
        self.client.post(reverse("lavanderia:add_item", args=[ordem.pk]),
                         {"servico_id": quilo.pk, "quantidade": "1.5"})
        self.assertEqual(ordem.itens.get().quantidade, Decimal("1.500"))
        self.assertEqual(ordem.total(), Decimal("33.00"))

    def test_observacao_salva_no_blur(self):
        ordem = self.ordem()
        resposta = self.client.post(reverse("lavanderia:observacao", args=[ordem.pk]),
                                    {"observacao": "Mancha na manga, não passar."})
        self.assertContains(resposta, "Observação salva.")
        ordem.refresh_from_db()
        self.assertEqual(ordem.observacao, "Mancha na manga, não passar.")
        # O recado tem de sair impresso com a roupa, não ficar só na tela.
        cupom = self.client.get(reverse("lavanderia:cupom", args=[ordem.pk]))
        self.assertContains(cupom, "Mancha na manga, não passar.")


class CobrancaPelaTelaTests(TelaBase):
    """O que o POST da cobrança aceita de quem NÃO é gerente.

    A tela esconde o campo de desconto e escreve «Desconto só com a gerência.»: a
    promessa tem de valer no servidor, senão é só um texto. O mesmo para o destino —
    qualquer valor diferente de "caixa" caía no fólio, por fora do gate do Reservas.
    """

    def setUp(self):
        super().setUp()
        SessaoCaixa.objects.create(operador=self.op, modulo="lavanderia",
                                   fundo_troco=Decimal("0.00"))
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.recepcao = Usuario.objects.create_user(
            username="lav-recepcao", password="senha-forte-123",
            is_staff=False, is_superuser=False)
        self.recepcao.modulos.add(ModuloContratado.objects.get(codigo=Modulo.LAVANDERIA))
        # A gaveta é por operador: sem a sessão dela, a recepção não recebe no caixa.
        SessaoCaixa.objects.create(operador=self.recepcao, modulo="lavanderia",
                                   fundo_troco=Decimal("0.00"))

    def pronta(self, rotulo="Quarto 30"):
        ordem = self.ordem(rotulo=rotulo)
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        return ordem

    def test_desconto_de_quem_nao_e_gerencia_e_recusado(self):
        ordem = self.pronta()
        self.client.force_login(self.recepcao)
        resposta = self.client.post(reverse("lavanderia:entregar", args=[ordem.pk]),
                                    {"destino": "caixa", "forma": self.dinheiro.pk,
                                     "desconto": "15.00"})
        self.assertEqual(resposta.status_code, 403)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.PRONTA)
        self.assertEqual(ordem.desconto, Decimal("0.00"))
        # Sem desconto, a mesma recepção entrega normalmente.
        self.client.post(reverse("lavanderia:entregar", args=[ordem.pk]),
                         {"destino": "caixa", "forma": self.dinheiro.pk, "desconto": "0"})
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.ENTREGUE)
        self.assertEqual(ordem.total(), Decimal("16.00"))

    def test_campo_de_desconto_aparece_so_para_a_gerencia(self):
        ordem = self.pronta(rotulo="Quarto 31")
        gerente = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertContains(gerente, 'name="desconto"')
        self.client.force_login(self.recepcao)
        recepcao = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertNotContains(recepcao, 'name="desconto"')
        self.assertContains(recepcao, "Desconto só com a gerência.")

    def test_destino_inventado_nao_lanca_no_folio(self):
        ordem = self.pronta(rotulo="Quarto 32")
        resposta = self.client.post(reverse("lavanderia:entregar", args=[ordem.pk]),
                                    {"destino": "xpto", "forma": self.dinheiro.pk},
                                    follow=True)
        self.assertContains(resposta, "Escolha como cobrar")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, OrdemLavanderia.Status.PRONTA)
        self.assertEqual(ordem.destino, "")


class TabelaDePrecosNaTelaTests(TelaBase):
    def test_cadastrar_e_editar_pelo_mesmo_formulario(self):
        self.client.post(reverse("lavanderia:servicos"),
                         {"nome": "Vestido", "preco": "15,00", "unidade": "peca"})
        vestido = ServicoLavanderia.objects.get(nome="Vestido")
        self.assertEqual(vestido.preco, Decimal("15.00"))
        self.client.post(reverse("lavanderia:servicos"),
                         {"pk": vestido.pk, "nome": "Vestido", "preco": "18,00",
                          "unidade": "peca", "icone": "vestido"})
        vestido.refresh_from_db()
        self.assertEqual(vestido.preco, Decimal("18.00"))
        self.assertEqual(vestido.icone, "vestido")

    def test_nome_repetido_avisa_em_vez_de_fingir_que_salvou(self):
        resposta = self.client.post(reverse("lavanderia:servicos"),
                                    {"nome": "Camisa social", "preco": "99"}, follow=True)
        self.assertContains(resposta, "Já existe um serviço com esse nome.")
        self.camisa.refresh_from_db()
        self.assertEqual(self.camisa.preco, Decimal("8.00"))

    def test_editar_pelo_endereco_preenche_o_formulario(self):
        resposta = self.client.get(reverse("lavanderia:servicos"),
                                   {"editar": self.camisa.pk})
        self.assertEqual(resposta.context["editar"], self.camisa)
        self.assertEqual([grupo for grupo, _ in resposta.context["escolhas_icones"]],
                         ["Peças", "Serviços", "Enxoval"])

    def test_preco_do_formulario_de_edicao_vem_em_formato_de_maquina(self):
        """O `value` de um `<input type=number>` é lido pelo navegador: com «10,00»
        (localizado) o campo nascia VAZIO e quem só queria renomear tinha de redigitar
        o preço de cabeça — e o campo é obrigatório."""
        self.camisa.preco = Decimal("10.00")
        self.camisa.save(update_fields=["preco"])
        resposta = self.client.get(reverse("lavanderia:servicos"),
                                   {"editar": self.camisa.pk})
        self.assertContains(resposta, 'value="10.00"')
        self.assertNotContains(resposta, 'value="10,00"')

    def test_desativar_e_reativar_pela_linha_do_quadro(self):
        url = reverse("lavanderia:servico_salvar", args=[self.camisa.pk])
        self.client.post(url, {"acao": "desativar"})
        self.camisa.refresh_from_db()
        self.assertFalse(self.camisa.ativo)
        self.client.post(url, {"acao": "reativar"})
        self.camisa.refresh_from_db()
        self.assertTrue(self.camisa.ativo)

    def test_linha_do_quadro_so_desativa_e_reativa(self):
        """A linha não edita: havia um ramo "editar" que a tela nunca usava e que
        LIMPAVA o ícone escolhido sempre que o POST não trouxesse o campo."""
        self.camisa.icone = "calca"
        self.camisa.save(update_fields=["icone"])
        resposta = self.client.post(
            reverse("lavanderia:servico_salvar", args=[self.camisa.pk]),
            {"acao": "editar", "nome": "Camisa social", "preco": "11,00"}, follow=True)
        self.assertContains(resposta, "Ação inválida")
        self.camisa.refresh_from_db()
        self.assertEqual(self.camisa.icone, "calca")
        self.assertEqual(self.camisa.preco, Decimal("8.00"))


class RoupariaNaTelaTests(TelaBase):
    def setUp(self):
        super().setUp()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol casal", minimo=50,
                                                 por_faxina=1)
        self.toalha = ItemEnxoval.objects.create(nome="Toalha de banho", minimo=0,
                                                 por_faxina=2)
        services.adquirir(self.lencol, 20, self.op)
        services.adquirir(self.toalha, 20, self.op)

    def test_rouparia_traz_kpis_barra_e_alvo_sugerido(self):
        services.distribuir(self.lencol, 8, self.op)
        resposta = self.client.get(reverse("lavanderia:rouparia"))
        self.assertEqual(resposta.status_code, 200)
        kpis = resposta.context["kpis"]
        self.assertEqual(kpis["limpa"], 32)      # 12 lençóis + 20 toalhas
        self.assertEqual(kpis["fora"], 8)
        self.assertEqual(kpis["abaixo"], 1)      # o lençol está abaixo do alvo
        linha = next(linha for linha in resposta.context["posicao"]
                     if linha["item"] == self.lencol)
        self.assertEqual(sum(fatia["pct"] for fatia in linha["barra"]), 100)
        self.assertEqual(resposta.context["alvo_novo"],
                         resposta.context["quartos"] * services.POR_FAXINA_PADRAO)

    def test_lote_move_as_linhas_marcadas(self):
        resposta = self.client.post(reverse("lavanderia:rouparia_lote"), {
            "itens": [self.lencol.pk, self.toalha.pk],
            "acao": "distribuir", "quantidade": "5",
        }, follow=True)
        self.assertContains(resposta, "2 itens")
        for item in (self.lencol, self.toalha):
            self.assertEqual(services.saldo_enxoval(item, MovimentoEnxoval.Estado.EM_USO), 5)

    def test_lote_sem_saldo_nao_grava_nada(self):
        antes = MovimentoEnxoval.objects.count()
        resposta = self.client.post(reverse("lavanderia:rouparia_lote"), {
            "itens": [self.lencol.pk, self.toalha.pk],
            "acao": "distribuir", "quantidade": "999",
        }, follow=True)
        self.assertContains(resposta, "Saldo insuficiente")
        self.assertEqual(MovimentoEnxoval.objects.count(), antes)

    def test_lote_recusa_item_que_saiu_da_lista(self):
        """"Tudo ou nada" vale para a LISTA: id inexistente (ou item desativado em
        outra aba) derrubava o lote? Não — ele saía do movimento calado, e a tela
        dizia "1 item: movimento registrado" para duas caixas marcadas."""
        antes = MovimentoEnxoval.objects.count()
        resposta = self.client.post(reverse("lavanderia:rouparia_lote"), {
            "itens": [self.lencol.pk, 999999],
            "acao": "distribuir", "quantidade": "3",
        }, follow=True)
        self.assertContains(resposta, "Algum item saiu da lista")
        self.assertEqual(MovimentoEnxoval.objects.count(), antes)
        self.assertEqual(
            services.saldo_enxoval(self.lencol, MovimentoEnxoval.Estado.EM_USO), 0)

    def test_lote_recusa_item_desativado_em_outra_aba(self):
        self.toalha.ativo = False
        self.toalha.save(update_fields=["ativo"])
        antes = MovimentoEnxoval.objects.count()
        resposta = self.client.post(reverse("lavanderia:rouparia_lote"), {
            "itens": [self.lencol.pk, self.toalha.pk],
            "acao": "distribuir", "quantidade": "2",
        }, follow=True)
        self.assertContains(resposta, "Algum item saiu da lista")
        self.assertEqual(MovimentoEnxoval.objects.count(), antes)

    def test_lote_guarda_a_selecao_quando_o_servidor_recusa(self):
        """`data-preservar-erros`: o lote recusado volta com as linhas ainda
        marcadas (o redirect limpava as caixas e a quantidade)."""
        tela = self.client.get(reverse("lavanderia:rouparia"))
        self.assertContains(tela, "data-preservar-erros")
        resposta = self.client.post(
            reverse("lavanderia:rouparia_lote"),
            {"itens": [self.lencol.pk], "acao": "distribuir", "quantidade": "999"},
            HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertIn("Saldo insuficiente", resposta.json()["errors"][0])


class ExtratoNaTelaTests(TelaBase):
    def setUp(self):
        super().setUp()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol casal", por_faxina=1)
        self.toalha = ItemEnxoval.objects.create(nome="Toalha de rosto", por_faxina=1)
        services.adquirir(self.lencol, 10, self.op)
        services.distribuir(self.lencol, 4, self.op)
        services.adquirir(self.toalha, 6, self.op)

    def test_extrato_traduz_o_motivo_e_o_estado(self):
        resposta = self.client.get(reverse("lavanderia:extrato"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Distribuição")
        self.assertContains(resposta, "Aquisição")
        self.assertContains(resposta, "Em uso")
        # O código do banco só pode viver no `value` do filtro, nunca numa célula.
        self.assertNotContains(resposta, ">em_uso<")
        self.assertNotContains(resposta, ">distribuicao<")

    def test_extrato_filtra_por_item_e_pagina(self):
        resposta = self.client.get(reverse("lavanderia:extrato"), {"item": self.toalha.pk})
        self.assertEqual(len(resposta.context["linhas"]), 1)
        self.assertEqual(resposta.context["pagina"].paginator.count, 1)
        vazio = self.client.get(reverse("lavanderia:extrato"),
                                {"de": (self.hoje + timedelta(days=1)).isoformat()})
        self.assertContains(vazio, "Nenhum movimento no período.")

    def test_extrato_recusa_filtro_que_nao_e_registro(self):
        self.assertEqual(
            self.client.get(reverse("lavanderia:extrato"), {"item": "ou 1=1"}).status_code,
            400)

    def test_periodo_do_extrato_vem_em_chip_e_a_data_livre_fica_atras_de_outro(self):
        """O `<input type=date>` cru mostra mm/dd/yyyy no Chrome em inglês: o recorte
        comum é chip, como no histórico, e a data livre só aparece em «Outro período»."""
        aberto = self.client.get(reverse("lavanderia:extrato"))
        self.assertEqual([p["rotulo"] for p in aberto.context["periodos"]],
                         ["Hoje", "7 dias", "Este mês", "Tudo", "Outro período"])
        self.assertEqual(aberto.context["periodo"], "tudo")
        self.assertNotContains(aberto, 'type="date"')
        hoje = self.client.get(reverse("lavanderia:extrato"), {"periodo": "hoje"})
        self.assertEqual(hoje.context["pagina"].paginator.count, 4)
        self.assertTrue(any(p["ativo"] and p["codigo"] == "hoje"
                            for p in hoje.context["periodos"]))
        # Data livre informada à mão abre o chip «Outro período» com os dois campos.
        amanha = (self.hoje + timedelta(days=1)).isoformat()
        livre = self.client.get(reverse("lavanderia:extrato"), {"de": amanha})
        self.assertEqual(livre.context["periodo"], "outro")
        self.assertContains(livre, 'type="date"')
        self.assertContains(livre, "Nenhum movimento no período.")

    def test_extrato_mostra_o_nome_de_quem_moveu(self):
        """Login («auditor», «_governanca») é código; a coluna «Quem» mostra gente,
        como nas outras dez telas da casa."""
        self.op.first_name = "Camareira"
        self.op.last_name = "da Casa"
        self.op.save(update_fields=["first_name", "last_name"])
        resposta = self.client.get(reverse("lavanderia:extrato"))
        self.assertContains(resposta, '<td data-rotulo="Quem"><div class="tabela-valor">Camareira',
                            html=False)


class HistoricoNaTelaTests(TelaBase):
    def setUp(self):
        super().setUp()
        SessaoCaixa.objects.create(operador=self.op, modulo="lavanderia",
                                   fundo_troco=Decimal("0.00"))
        self.dinheiro = FormaPagamento.objects.get(tipo="dinheiro")
        self.entregue = self.ordem(rotulo="Quarto 21")
        services.avancar_status(self.entregue)
        services.avancar_status(self.entregue)
        services.entregar(self.entregue, self.op, "caixa", forma=self.dinheiro)
        self.cancelada = self.ordem(rotulo="Quarto 22", pecas=1)
        services.cancelar_ordem(self.cancelada, self.op, "hóspede desistiu")

    def test_historico_soma_o_total_do_periodo(self):
        resposta = self.client.get(reverse("lavanderia:historico"))
        kpis = resposta.context["kpis"]
        self.assertEqual(kpis["ordens"], 2)              # entregue + cancelada
        self.assertEqual(kpis["total"], Decimal("16.00"))   # cancelada não soma
        self.assertEqual(kpis["caixa"], Decimal("16.00"))
        self.assertEqual(kpis["conta"], Decimal("0.00"))

    def test_filtro_de_situacao_e_de_periodo(self):
        so_canceladas = self.client.get(reverse("lavanderia:historico"),
                                        {"situacao": "cancelada"})
        self.assertEqual([o.pk for o in so_canceladas.context["ordens"]],
                         [self.cancelada.pk])
        hoje = self.client.get(reverse("lavanderia:historico"), {"periodo": "hoje"})
        self.assertEqual(hoje.context["kpis"]["ordens"], 2)
        self.assertTrue(any(chip["ativo"] and chip["codigo"] == "hoje"
                            for chip in hoje.context["periodos"]))

    def test_kpi_do_periodo_fecha_com_a_soma_das_ordens(self):
        """Os números do topo saem de agregação no banco (antes a view percorria todo
        o recorte em Python, com os itens): têm de bater com `total()` ordem por ordem,
        inclusive na página 2 e com desconto no meio."""
        for numero in range(3):
            ordem = self.ordem(rotulo=f"Quarto 4{numero}")
            services.avancar_status(ordem)
            services.avancar_status(ordem)
            services.entregar(ordem, self.op, "caixa", forma=self.dinheiro,
                              desconto=Decimal("1.50"))
        entregues = OrdemLavanderia.objects.filter(
            status=OrdemLavanderia.Status.ENTREGUE)
        esperado = sum((o.total() for o in entregues), Decimal("0.00"))
        resposta = self.client.get(reverse("lavanderia:historico"), {"periodo": "tudo"})
        kpis = resposta.context["kpis"]
        self.assertEqual(kpis["total"], esperado)
        self.assertEqual(kpis["caixa"], esperado)
        self.assertEqual(kpis["conta"], Decimal("0.00"))
        self.assertEqual(kpis["ordens"], entregues.count() + 1)   # + a cancelada

    def test_busca_por_numero_e_por_cliente(self):
        por_numero = self.client.get(reverse("lavanderia:historico"),
                                     {"busca": f"#{self.entregue.pk}", "periodo": "tudo"})
        self.assertEqual([o.pk for o in por_numero.context["ordens"]], [self.entregue.pk])
        por_rotulo = self.client.get(reverse("lavanderia:historico"),
                                     {"busca": "Quarto 22", "periodo": "tudo"})
        self.assertEqual([o.pk for o in por_rotulo.context["ordens"]], [self.cancelada.pk])


class PainelDesenhadoTests(TelaBase):
    """O HTML do painel: a cápsula do atraso, o chip ativo e o botão do próximo
    passo dentro do cartão (é ele que faz a fila andar sem abrir a ordem)."""

    def test_cartao_da_fila_grita_o_atraso_e_traz_o_proximo_passo(self):
        self.ordem(rotulo="Quarto 2", prazo=self.hoje - timedelta(days=3))
        resposta = self.client.get(reverse("lavanderia:painel"))
        self.assertContains(resposta, "Atrasada há 3 dias")
        self.assertContains(resposta, "lav-ordem--atrasada")
        # O POST do cartão carimba a etapa que a tela mostrava.
        self.assertContains(resposta, 'name="de" value="recebida"')
        self.assertContains(resposta, "Enviar para lavagem")

    def test_pronta_no_cartao_vira_link_porque_cobrar_pede_destino(self):
        ordem = self.ordem(rotulo="Quarto 3")
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        resposta = self.client.get(reverse("lavanderia:painel"))
        alvo = reverse("lavanderia:ordem", args=[ordem.pk])
        self.assertContains(resposta, f'<a class="botao-primario" href="{alvo}">Entregar e cobrar</a>')

    def test_chip_da_etapa_marca_o_ativo_e_a_fila_vem_filtrada(self):
        lavando = self.ordem(rotulo="Quarto 4")
        services.avancar_status(lavando)
        resposta = self.client.get(reverse("lavanderia:painel"), {"etapa": "lavando"})
        self.assertContains(resposta, 'href="?etapa=lavando"')
        self.assertContains(resposta, 'aria-current="page"')
        self.assertNotContains(resposta, "Enviar para lavagem")
        self.assertContains(resposta, "Marcar como pronta")

    def test_cartao_manda_voltar_para_a_fila_e_o_painel_nao_repete_a_aba(self):
        self.ordem(rotulo="Quarto 7")
        resposta = self.client.get(reverse("lavanderia:painel"))
        self.assertContains(resposta, 'name="voltar" value="painel"')
        # «Rouparia» já é aba: o botão de ação a 60 px dela saiu do cabeçalho.
        self.assertNotContains(
            resposta,
            f'<a class="botao-neutro" href="{reverse("lavanderia:rouparia")}">Rouparia</a>')

    def test_sem_ordem_nenhuma_a_fila_convida_a_receber(self):
        resposta = self.client.get(reverse("lavanderia:painel"))
        self.assertContains(resposta, "Nenhuma ordem em produção. Receba a primeira acima.")

    def test_aba_ordens_mostra_a_contagem_em_producao(self):
        self.ordem()
        self.ordem(rotulo="Quarto 5")
        resposta = self.client.get(reverse("lavanderia:servicos"))
        self.assertContains(resposta, 'Ordens <span class="n">2</span>')


class OrdemDesenhadaTests(TelaBase):
    """O balcão: trilha, lançamento por quilo, stepper e a cobrança condicional."""

    def test_trilha_e_grade_com_icone_de_peca(self):
        resposta = self.client.get(reverse("lavanderia:ordem", args=[self.ordem().pk]))
        self.assertContains(resposta, "lav-trilha")
        self.assertContains(resposta, "Recebida")
        # O ícone é SVG inline, com o nome do serviço em texto ao lado.
        self.assertContains(resposta, 'class="ico-peca ico-peca--grande"')
        self.assertContains(resposta, "Camisa social")

    def test_servico_em_quilo_abre_campo_de_peso_em_vez_de_somar_um(self):
        ServicoLavanderia.objects.create(nome="Roupa por quilo", preco=Decimal("22.00"),
                                         unidade=ServicoLavanderia.Unidade.KG)
        resposta = self.client.get(reverse("lavanderia:ordem", args=[self.ordem().pk]))
        self.assertContains(resposta, "lav-peso")
        self.assertContains(resposta, "Peso (kg)")

    def test_cobranca_so_abre_quando_a_ordem_esta_pronta(self):
        ordem = self.ordem()
        recebida = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertContains(recebida, "Entregar antes de ficar pronta")
        self.assertContains(recebida, 'name="confirmar" value="1"')
        services.avancar_status(ordem)
        services.avancar_status(ordem)
        pronta = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertNotContains(pronta, "Entregar antes de ficar pronta")
        self.assertNotContains(pronta, 'name="confirmar" value="1"')
        # Pronta é a hora de avisar quem deixou a roupa.
        self.assertContains(pronta, "Aviso de roupa pronta")

    def test_partial_devolve_o_resumo_para_a_aba_cesta(self):
        """No celular a cesta não está na tela: o resumo volta por `hx-swap-oob`."""
        ordem = self.ordem()
        resposta = self.client.post(
            reverse("lavanderia:add_item", args=[ordem.pk]),
            {"servico_id": self.camisa.pk, "quantidade": 1})
        self.assertContains(resposta, 'id="lav-resumo" hx-swap-oob="true"')
        self.assertContains(resposta, 'id="lav-contador"')
        self.assertContains(resposta, "3 peças")

    def test_a_cesta_embutida_nao_repete_o_id_do_resumo(self):
        resposta = self.client.get(reverse("lavanderia:ordem", args=[self.ordem().pk]))
        self.assertEqual(resposta.content.decode().count('id="lav-resumo"'), 1)
        self.assertEqual(resposta.content.decode().count('id="lav-contador"'), 1)

    def test_resumo_da_aba_cesta_mostra_o_quilo(self):
        """No celular a aba «Cesta» é o único resumo enquanto se lança peça: sem o
        granel, parecia que o peso não tinha entrado."""
        quilo = ServicoLavanderia.objects.create(
            nome="Roupa por quilo", preco=Decimal("22.00"),
            unidade=ServicoLavanderia.Unidade.KG)
        ordem = self.ordem()
        resposta = self.client.post(reverse("lavanderia:add_item", args=[ordem.pk]),
                                    {"servico_id": quilo.pk, "quantidade": "1,5"})
        self.assertContains(resposta, "2 peças · 1,5 kg · R$ 49,00")
        tela = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertContains(tela, "2 peças · 1,5 kg · R$ 49,00")

    def test_trilha_mostra_hora_no_passo_cumprido(self):
        """Carimbo é hora, e só hora: a trilha não escreve «Cumprido» nem «Agora»
        onde devia haver horário."""
        ordem = self.ordem()
        services.avancar_status(ordem)
        resposta = self.client.get(reverse("lavanderia:ordem", args=[ordem.pk]))
        self.assertNotContains(resposta, "Cumprido")
        self.assertNotContains(resposta, ">Agora<")
        ordem.refresh_from_db()
        self.assertContains(resposta, ordem.lavando_em.astimezone(
            timezone.get_current_timezone()).strftime("%d/%m %H:%M"))

    def test_quilo_com_virgula_entra_como_o_balcao_digita(self):
        quilo = ServicoLavanderia.objects.create(
            nome="Roupa por quilo", preco=Decimal("22.00"),
            unidade=ServicoLavanderia.Unidade.KG)
        ordem = self.ordem(pecas=0)
        self.client.post(reverse("lavanderia:add_item", args=[ordem.pk]),
                         {"servico_id": quilo.pk, "quantidade": "1,5"})
        self.assertEqual(ordem.itens.get().quantidade, Decimal("1.500"))


class RoupariaDesenhadaTests(TelaBase):
    def setUp(self):
        super().setUp()
        self.lencol = ItemEnxoval.objects.create(nome="Lençol casal", minimo=50, por_faxina=1)
        services.adquirir(self.lencol, 20, self.op)
        services.distribuir(self.lencol, 8, self.op)

    def test_barra_descreve_a_situacao_e_o_numero_propoe_o_movimento(self):
        resposta = self.client.get(reverse("lavanderia:rouparia"))
        self.assertContains(resposta, 'class="lav-barra"')
        self.assertContains(resposta, "Limpa 12, Em uso 8, Suja 0, Lavando 0")
        # Tocar no número de "em uso" propõe recolher aquelas peças como sujas.
        self.assertContains(resposta, f"propor('{self.lencol.pk}', 'coletar', 8)")
        self.assertContains(resposta, "Repor")   # 12 limpas para um alvo de 50

    def test_lote_e_extrato_tem_caminho_pela_tela(self):
        resposta = self.client.get(reverse("lavanderia:rouparia"))
        self.assertContains(resposta, reverse("lavanderia:rouparia_lote"))
        self.assertContains(resposta, reverse("lavanderia:extrato"))
        self.assertContains(resposta, "Enviar para lavar")

    def test_alvo_do_item_novo_ja_vem_sugerido(self):
        resposta = self.client.get(reverse("lavanderia:rouparia"))
        alvo = resposta.context["alvo_novo"]
        self.assertContains(resposta, f'name="minimo" min="0" value="{alvo}"')
        self.assertContains(resposta, "Alvo na rouparia")


class TabelaDePrecosDesenhadaTests(TelaBase):
    def test_quadro_mostra_icone_situacao_e_acoes(self):
        resposta = self.client.get(reverse("lavanderia:servicos"))
        self.assertContains(resposta, 'class="ico-peca"')
        self.assertContains(resposta, "Desativar")
        self.assertContains(resposta, f'href="?editar={self.camisa.pk}"')

    def test_formulario_de_edicao_vem_preenchido_e_com_o_icone_escolhido(self):
        self.camisa.icone = "camisa"
        self.camisa.save(update_fields=["icone"])
        resposta = self.client.get(reverse("lavanderia:servicos"), {"editar": self.camisa.pk})
        self.assertContains(resposta, "Editar «Camisa social»")
        self.assertContains(resposta, 'value="camisa" selected')
        self.assertContains(resposta, "Salvar serviço")
