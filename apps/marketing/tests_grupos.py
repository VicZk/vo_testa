"""Os grupos simplificam o quadro sem encurtar o fluxo nem seus portões."""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import ModuloContratado, Usuario
from apps.nucleo.modulos import Modulo

from . import services
from .models import Campanha, ItemChecklist, PecaCampanha


class GruposQuadroTests(TestCase):
    def setUp(self):
        cache.clear()
        modulo, _ = ModuloContratado.objects.update_or_create(codigo=Modulo.MARKETING, defaults={"ativo": True})
        self.usuario = Usuario.objects.create_user(username="grupos")
        self.gerente = Usuario.objects.create_user(username="grupos-gerente", is_staff=True)
        self.usuario.modulos.add(modulo)
        self.gerente.modulos.add(modulo)
        self.client.force_login(self.usuario)
        self.campanhas = {
            fase: Campanha.objects.create(nome=f"Campanha {fase}", fase=fase, canais=["Instagram"],
                                          responsavel=self.usuario, verba_prevista=Decimal(i * 10))
            for i, fase in enumerate(Campanha.Fase.values, 1)
        }

    def test_sete_estados_aparecem_uma_vez_em_cinco_grupos_com_totais_corretos(self):
        colunas = services.quadro_colunas()
        self.assertEqual([c["label"] for c in colunas],
                         ["Planejamento", "Aprovação", "Produção", "No ar", "Encerradas"])
        self.assertEqual([c["conta"] for c in colunas], [2, 1, 2, 1, 1])
        self.assertEqual([c["total"] for c in colunas], [30, 30, 90, 60, 70])
        estados = [{card["obj"].fase for card in col["cards"]} for col in colunas]
        self.assertEqual(estados, [{"ideia", "proposta"}, {"aprovacao"},
                                  {"estruturacao", "producao"}, {"noar"}, {"encerrada"}])
        self.assertEqual(ItemChecklist.objects.count(), 0, "Ler o quadro não cria requisitos.")
        self.assertEqual([c["portao"] for c in colunas], [False, True, False, False, False])

    def test_canal_e_so_meus_se_aplicam_antes_de_contar_e_somar_os_grupos(self):
        proposta = self.campanhas["proposta"]
        proposta.responsavel = self.gerente
        proposta.save()
        producao = self.campanhas["producao"]
        producao.canais = ["WhatsApp"]
        producao.save()
        resposta = self.client.get(reverse("marketing:quadro"), {"canal": "Instagram", "meus": 1})
        colunas = resposta.context["colunas"]
        self.assertEqual([c["conta"] for c in colunas], [1, 1, 1, 1, 1])
        self.assertEqual([c["total"] for c in colunas], [10, 30, 40, 60, 70])
        self.assertEqual(resposta.context["meus_count"], 5)
        self.assertEqual({card["obj"].pk for col in colunas for card in col["cards"]},
                         {c.pk for fase, c in self.campanhas.items() if fase not in ("proposta", "producao")})

    def test_grupo_compartilhado_expoe_subetapa_e_proximo_passo_sem_arraste(self):
        resposta = self.client.get(reverse("marketing:quadro"))
        cards = {card["obj"].fase: card for col in resposta.context["colunas"] for card in col["cards"]}
        self.assertEqual(cards["ideia"]["subetapa"], "Ideia")
        self.assertEqual(cards["proposta"]["subetapa"], "Proposta")
        self.assertEqual(cards["estruturacao"]["subetapa"], "Estruturação")
        self.assertEqual(cards["producao"]["subetapa"], "Produção")
        self.assertEqual(cards["ideia"]["proximo_passo"], "Preparar proposta")
        self.assertEqual(cards["proposta"]["proximo_passo"], "Solicitar aprovação")
        self.assertContains(resposta, 'class="mk-card-passo"', count=7)
        self.assertNotContains(resposta, 'draggable="true"')
        self.assertNotContains(resposta, "soltarMkt")

    def test_avanco_dentro_do_grupo_nao_pula_portao_da_subetapa(self):
        campanha = self.campanhas["ideia"]
        url = reverse("marketing:mover_fase", args=[campanha.pk])
        # O nome do grupo não é um estado aceito, e nem uma tentativa de pulo passa.
        for destino in ("planejamento", "aprovacao", "proposta"):
            self.client.post(url, {"fase": destino})
            campanha.refresh_from_db()
            self.assertEqual(campanha.fase, "ideia")
        campanha.objetivo = "Ampliar as reservas de novembro"
        campanha.save()
        self.client.post(url, {"fase": "proposta"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "proposta")
        planejamento = services.quadro_colunas()[0]
        self.assertIn(campanha.pk, [c["obj"].pk for c in planejamento["cards"]])
        self.client.post(url, {"fase": "aprovacao"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "proposta", "Os requisitos da proposta continuam obrigatórios.")

    def test_producao_conserva_planejamento_de_entregas_e_conclusao_antes_de_noar(self):
        campanha = self.campanhas["estruturacao"]
        url = reverse("marketing:mover_fase", args=[campanha.pk])
        self.client.post(url, {"fase": "producao"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "estruturacao")
        entrega = PecaCampanha.objects.create(campanha=campanha, nome="Criativo principal")
        self.client.post(url, {"fase": "producao"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "producao")
        self.client.post(url, {"fase": "noar"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "producao")
        entrega.status = PecaCampanha.Status.PRONTA
        entrega.save()
        self.client.post(url, {"fase": "noar"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "noar")

    def test_aprovacao_separada_exige_gerencia_e_verba_e_preserva_filtro(self):
        campanha = self.campanhas["aprovacao"]
        url = reverse("marketing:mover_fase", args=[campanha.pk])
        origem = reverse("marketing:quadro") + "?canal=Instagram&meus=1"
        self.assertNotContains(self.client.get(origem), 'class="mk-btn-aprovar"')
        self.client.post(url, {"fase": "estruturacao"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "aprovacao")
        self.client.force_login(self.gerente)
        resposta = self.client.get(origem)
        self.assertContains(resposta, 'class="mk-btn-aprovar"', count=1)
        self.assertContains(resposta, 'name="next" value="' + origem.replace("&", "&amp;") + '"', count=2)
        self.client.post(url, {"fase": "estruturacao"})
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "aprovacao", "Sem saldo, a gerência também não avança.")
        services.definir_teto(services.mes_atual(), "1000")
        resposta = self.client.post(url, {"fase": "estruturacao", "next": origem})
        self.assertRedirects(resposta, origem, fetch_redirect_response=False)
        campanha.refresh_from_db()
        self.assertEqual(campanha.fase, "estruturacao")
        self.assertEqual(campanha.verba_travada, Decimal("30"))
        self.assertEqual(campanha.aprovada_por_id, self.gerente.pk)
        producao = services.quadro_colunas()[2]
        self.assertIn(campanha.pk, [c["obj"].pk for c in producao["cards"]])
