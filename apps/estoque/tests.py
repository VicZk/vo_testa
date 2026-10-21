from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.nucleo.models import (
    CategoriaProduto,
    Inventario,
    ItemInventario,
    LocalEstoque,
    ModuloContratado,
    MovimentoEstoque,
    Produto,
    TrilhaAuditoria,
    ajustar,
    posicao_estoque,
    produtos_abaixo_minimo,
    registrar_entrada,
    registrar_saida,
    saldo,
    transferir,
)
from apps.nucleo.modulos import Modulo

Usuario = get_user_model()


class EstoqueBase(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_superuser(
            username="estoquista", password="senha-forte-123"
        )
        self.cat = CategoriaProduto.objects.create(nome="Bebidas")
        self.almox = LocalEstoque.objects.create(nome="Almox", modulo="nucleo")
        self.loja = LocalEstoque.objects.create(nome="Loja dep", modulo="loja")
        self.produto = Produto.objects.create(
            nome="Refri lata", categoria=self.cat,
            preco_venda=Decimal("6.00"), estoque_minimo=Decimal("24"),
        )


class CustoMedioTests(EstoqueBase):
    def test_custo_medio_ponderado(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        registrar_entrada(self.produto, self.almox, 10, Decimal("3.00"), self.user)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, Decimal("2.5000"))
        self.assertEqual(saldo(self.produto, self.almox), Decimal("20.000"))

    def test_saida_mantem_custo_e_valida_saldo(self):
        registrar_entrada(self.produto, self.almox, 5, Decimal("4.00"), self.user)
        registrar_saida(self.produto, self.almox, 2, self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("3.000"))
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, Decimal("4.0000"))

    def test_saida_nao_deixa_saldo_negativo(self):
        registrar_entrada(self.produto, self.almox, 1, Decimal("1.00"), self.user)
        with self.assertRaises(ValidationError):
            registrar_saida(self.produto, self.almox, 5, self.user)

    def test_natureza_padrao_consumo(self):
        self.assertEqual(self.produto.natureza, "consumo")


class ImutabilidadeTests(EstoqueBase):
    def test_movimento_imutavel(self):
        mov = registrar_entrada(self.produto, self.almox, 3, Decimal("1.00"), self.user)
        mov.quantidade = Decimal("9")
        with self.assertRaises(ValidationError):
            mov.save()
        with self.assertRaises(ValidationError):
            mov.delete()

    def test_movimento_quantidade_nao_zero(self):
        with self.assertRaises(ValidationError):
            MovimentoEstoque(
                produto=self.produto, local=self.almox,
                tipo=MovimentoEstoque.Tipo.AJUSTE, quantidade=Decimal("0"),
                criado_por=self.user,
            ).save()


class TransferenciaTests(EstoqueBase):
    def test_transferencia_dois_lados(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        saida, entrada = transferir(self.produto, self.almox, self.loja, 4, self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("6.000"))
        self.assertEqual(saldo(self.produto, self.loja), Decimal("4.000"))
        self.assertEqual(saldo(self.produto), Decimal("10.000"))  # total inalterado
        self.assertEqual(saida.transferencia_par, entrada)
        self.assertTrue(
            TrilhaAuditoria.objects.filter(acao="transferencia_estoque").exists()
        )

    def test_transferencia_valida_saldo_e_locais(self):
        with self.assertRaises(ValidationError):
            transferir(self.produto, self.almox, self.almox, 1, self.user)
        with self.assertRaises(ValidationError):
            transferir(self.produto, self.almox, self.loja, 1, self.user)  # sem saldo


class AjusteEInventarioTests(EstoqueBase):
    def test_ajuste_gera_diferenca_e_audita(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        ajustar(self.produto, self.almox, 8, self.user, motivo="quebra")
        self.assertEqual(saldo(self.produto, self.almox), Decimal("8.000"))
        self.assertTrue(TrilhaAuditoria.objects.filter(acao="ajuste_estoque").exists())

    def test_inventario_aplica_ajustes(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        inv = Inventario.objects.create(local=self.almox, criado_por=self.user)
        ItemInventario.objects.create(
            inventario=inv, produto=self.produto,
            saldo_sistema=Decimal("10"), quantidade_contada=Decimal("7"),
        )
        inv.aplicar(self.user)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("7.000"))
        self.assertEqual(inv.status, Inventario.Status.APLICADO)
        with self.assertRaises(ValidationError):
            inv.aplicar(self.user)  # não aplica duas vezes

    def test_posicao_e_alerta_minimo(self):
        registrar_entrada(self.produto, self.almox, 10, Decimal("2.00"), self.user)
        # 10 < mínimo 24 → alerta
        self.assertEqual(produtos_abaixo_minimo(), 1)
        registrar_entrada(self.produto, self.almox, 20, Decimal("2.00"), self.user)
        self.assertEqual(produtos_abaixo_minimo(), 0)
        linhas = posicao_estoque(self.almox)
        self.assertEqual(linhas[0]["saldo"], Decimal("30.000"))


class PermissaoTests(EstoqueBase):
    def test_view_exige_modulo(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("estoque:posicao")).status_code, 403)

    def test_modulo_inativo_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        self.client.login(username="estoquista", password="senha-forte-123")
        self.assertEqual(self.client.get(reverse("estoque:posicao")).status_code, 404)

    def test_fluxo_entrada_pela_view(self):
        self.client.login(username="estoquista", password="senha-forte-123")
        resposta = self.client.post(
            reverse("estoque:entrada"),
            {
                "produto": self.produto.pk, "local": self.almox.pk,
                "quantidade": "12", "custo_unitario": "2.5",
                "documento": "NF 10", "observacao": "",
            },
        )
        self.assertRedirects(resposta, reverse("estoque:posicao"))
        self.assertEqual(saldo(self.produto, self.almox), Decimal("12.000"))


class DevolverAoEstoqueTests(EstoqueBase):
    """Devolução (cancelamento de venda/comanda) soma ao saldo de agora, sem ler antes."""

    def test_soma_ao_saldo_atual_sem_mexer_no_custo_medio(self):
        from apps.nucleo.models import devolver_ao_estoque

        registrar_entrada(self.produto, self.almox, 10, Decimal("3.00"), self.user)
        registrar_saida(self.produto, self.almox, 4, self.user)
        custo = Produto.objects.get(pk=self.produto.pk).custo_medio
        mov = devolver_ao_estoque(self.produto, self.almox, 2, self.user, motivo="Cancelamento")
        self.assertEqual(mov.tipo, MovimentoEstoque.Tipo.AJUSTE)
        self.assertEqual(saldo(self.produto, self.almox), Decimal("8"))
        self.assertEqual(Produto.objects.get(pk=self.produto.pk).custo_medio, custo)

    def test_quantidade_precisa_ser_positiva(self):
        from apps.nucleo.models import devolver_ao_estoque

        with self.assertRaises(ValidationError):
            devolver_ao_estoque(self.produto, self.almox, 0, self.user)


# ─────────────────────────────────────────────────────────────────────────────
# Telas (redesenho de out/2026): leitura, formatação e consulta constante.
# ─────────────────────────────────────────────────────────────────────────────


class FormatoTests(TestCase):
    """Quantidade do jeito de gente: "55,000 unidade" não é como se conta prateleira."""

    def test_quantidade_com_sigla(self):
        from apps.estoque.formato import com_sinal, numero, quantidade

        self.assertEqual(quantidade(Decimal("55.000"), "un"), "55 un")
        self.assertEqual(quantidade(Decimal("4.500"), "kg"), "4,5 kg")
        self.assertEqual(quantidade(Decimal("5"), "l"), "5 L")      # litro em maiúscula
        self.assertEqual(quantidade(Decimal("0"), "un"), "0 un")
        self.assertEqual(numero(Decimal("1250.5")), "1.250,5")      # milhar com ponto
        self.assertEqual(com_sinal(Decimal("12"), "un"), "+12 un")
        self.assertEqual(com_sinal(Decimal("-3"), "un"), "−3 un")

    def test_filtro_de_template(self):
        from apps.estoque.templatetags.estoque_extras import qtd, unidade_sigla

        self.assertEqual(qtd(Decimal("2.000"), "cx"), "2 cx")
        self.assertEqual(unidade_sigla("l"), "L")


class ConsultasDeLeituraTests(EstoqueBase):
    """As consultas novas do motor: por local, resumo e indicadores."""

    def setUp(self):
        super().setUp()
        registrar_entrada(self.produto, self.almox, 40, Decimal("2.50"), self.user)
        transferir(self.produto, self.almox, self.loja, 10, self.user)

    def test_saldos_por_local_de_um_produto(self):
        from apps.nucleo.models import saldos_por_local

        mapa = saldos_por_local(self.produto)
        self.assertEqual(mapa[self.almox.pk], Decimal("30.000"))
        self.assertEqual(mapa[self.loja.pk], Decimal("10.000"))

    def test_saldos_por_local_do_catalogo_em_uma_consulta(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.nucleo.models import saldos_por_local

        with CaptureQueriesContext(connection) as ctx:
            mapa = saldos_por_local()
        self.assertEqual(len(ctx), 1)
        self.assertEqual(mapa[(self.produto.pk, self.loja.pk)], Decimal("10.000"))

    def test_resumo_locais_traz_valor_e_alerta(self):
        from apps.nucleo.models import resumo_locais

        resumo = {lo["local"].pk: lo for lo in resumo_locais()}
        self.assertEqual(resumo[self.almox.pk]["itens"], 1)
        self.assertEqual(resumo[self.almox.pk]["valor"], Decimal("75.00"))  # 30 × 2,50
        self.assertEqual(resumo[self.almox.pk]["alertas"], 0)               # 30 > mín 24
        self.assertEqual(resumo[self.loja.pk]["alertas"], 1)                # 10 ≤ mín 24

    def test_situacao_separa_zerado_de_abaixo(self):
        vazio = Produto.objects.create(nome="Suco", categoria=self.cat)
        linhas = {lin["produto"].pk: lin for lin in posicao_estoque()}
        self.assertEqual(linhas[self.produto.pk]["situacao"], "ok")       # 40 > 24
        self.assertEqual(linhas[vazio.pk]["situacao"], "zerado")
        self.assertFalse(linhas[vazio.pk]["abaixo"])          # zerado não é "abaixo"
        self.assertTrue(linhas[vazio.pk]["abaixo_minimo"])    # mas segue alerta
        na_loja = {lin["produto"].pk: lin for lin in posicao_estoque(self.loja)}
        self.assertEqual(na_loja[self.produto.pk]["situacao"], "abaixo")  # 10 ≤ 24
        self.assertEqual(na_loja[self.produto.pk]["nivel"], 41)           # 10/24

    def test_indicadores_somam_as_linhas(self):
        from apps.nucleo.models import indicadores_estoque

        Produto.objects.create(nome="Suco", categoria=self.cat)
        dados = indicadores_estoque(posicao_estoque())
        self.assertEqual(dados["valor"], Decimal("100.00"))   # 40 × 2,50
        self.assertEqual(dados["zerados"], 1)
        self.assertEqual(dados["com_saldo"], 1)
        self.assertEqual(dados["itens"], 2)


class FornecedorNaEntradaTests(EstoqueBase):
    def test_entrada_guarda_de_quem_veio(self):
        from apps.nucleo.models import Fornecedor, Pessoa

        pessoa = Pessoa.objects.create(nome="Distribuidora Teste")
        Fornecedor.objects.create(pessoa=pessoa)
        mov = registrar_entrada(
            self.produto, self.almox, 10, Decimal("2.00"), self.user,
            documento="NF 1", fornecedor=pessoa,
        )
        self.assertEqual(mov.fornecedor, pessoa)
        self.assertEqual(pessoa.entradas_estoque.count(), 1)

    def test_entrada_sem_fornecedor_continua_valendo(self):
        mov = registrar_entrada(self.produto, self.almox, 5, Decimal("2.00"), self.user)
        self.assertIsNone(mov.fornecedor)


class TelasBase(EstoqueBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        registrar_entrada(self.produto, self.almox, 40, Decimal("2.50"), self.user)


class PosicaoTests(TelasBase):
    def test_quantidade_aparece_legivel(self):
        html = self.client.get(reverse("estoque:posicao")).content.decode()
        self.assertIn("40 un", html)
        self.assertNotIn("40,000 unidade", html)

    def test_filtro_de_situacao_e_busca(self):
        Produto.objects.create(nome="Suco de uva", categoria=self.cat)
        url = reverse("estoque:posicao")
        zerados = self.client.get(url, {"situacao": "zerado"}).context["linhas"]
        self.assertEqual([lin["produto"].nome for lin in zerados], ["Suco de uva"])
        busca = self.client.get(url, {"q": "refri"}).context["linhas"]
        self.assertEqual([lin["produto"].nome for lin in busca], ["Refri lata"])
        # O indicador fala do escopo, não da busca: continua contando os dois.
        self.assertEqual(
            self.client.get(url, {"q": "refri"}).context["indicadores"]["itens"], 2
        )

    def test_alerta_antigo_do_painel_continua_valendo(self):
        """O dashboard e a Auditoria linkam `?alerta=1` — não pode quebrar."""
        resposta = self.client.get(reverse("estoque:posicao"), {"alerta": "1"})
        self.assertEqual(resposta.context["filtros"]["situacao"], "alerta")

    def test_consulta_nao_cresce_com_o_catalogo(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("estoque:posicao")
        self.client.get(url)  # aquece sessão/permissões
        with CaptureQueriesContext(connection) as poucos:
            self.client.get(url)
        for i in range(20):
            produto = Produto.objects.create(nome=f"Produto {i}", categoria=self.cat)
            registrar_entrada(produto, self.loja, 3, Decimal("1.00"), self.user)
        with CaptureQueriesContext(connection) as muitos:
            self.client.get(url)
        self.assertEqual(len(muitos), len(poucos), "posição faz consulta por produto")

    def test_deposito_mostra_so_o_que_ele_guarda(self):
        """Sem isto, escolher um depósito pintava o catálogo inteiro de
        "sem saldo" — 27 alarmes para dizer que a Loja não guarda detergente."""
        Produto.objects.create(nome="Só no almoxarifado", categoria=self.cat)
        resposta = self.client.get(reverse("estoque:posicao"), {"local": self.loja.pk})
        nomes = [lin["produto"].nome for lin in resposta.context["linhas"]]
        self.assertEqual(nomes, [])                       # nada passou pela loja
        self.assertEqual(resposta.context["fora_do_local"], 2)
        # O catálogo inteiro continua a um clique — e aí nada fica escondido.
        com_tudo = self.client.get(
            reverse("estoque:posicao"), {"local": self.loja.pk, "catalogo": "1"}
        )
        self.assertEqual(len(com_tudo.context["linhas"]), 2)
        self.assertEqual(com_tudo.context["fora_do_local"], 0)

    def test_cartao_de_todos_os_locais_fala_da_pousada(self):
        """Olhando um depósito, o cartão "Todos os locais" mostrava o número
        DELE — dois cartões lado a lado com o mesmo valor."""
        transferir(self.produto, self.almox, self.loja, 10, self.user)
        resposta = self.client.get(reverse("estoque:posicao"), {"local": self.loja.pk})
        self.assertEqual(resposta.context["indicadores"]["valor"], Decimal("25.00"))
        self.assertEqual(resposta.context["geral"]["valor"], Decimal("100.00"))

    def test_o_que_acabou_no_deposito_continua_aparecendo(self):
        transferir(self.produto, self.almox, self.loja, 5, self.user)
        registrar_saida(self.produto, self.loja, 5, self.user)   # acabou ali
        resposta = self.client.get(reverse("estoque:posicao"), {"local": self.loja.pk})
        linhas = resposta.context["linhas"]
        self.assertEqual([lin["produto"].nome for lin in linhas], ["Refri lata"])
        self.assertTrue(linhas[0]["zerado"])
        self.assertFalse(linhas[0]["nunca_movimentou"])
        self.assertEqual(resposta.context["indicadores"]["zerados"], 1)

    def test_acao_rapida_leva_produto_e_local(self):
        html = self.client.get(
            reverse("estoque:posicao"), {"local": self.almox.pk}
        ).content.decode()
        self.assertIn(
            f"{reverse('estoque:saida')}?produto={self.produto.pk}&local={self.almox.pk}",
            html,
        )


class ProdutosTests(TelasBase):
    def test_saldo_vem_anotado_sem_consulta_por_linha(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("estoque:produtos")
        self.client.get(url)
        with CaptureQueriesContext(connection) as poucos:
            self.client.get(url)
        for i in range(15):
            Produto.objects.create(nome=f"Outro {i}", categoria=self.cat)
        with CaptureQueriesContext(connection) as muitos:
            self.client.get(url)
        self.assertEqual(len(muitos), len(poucos))

    def test_filtro_de_situacao_esconde_inativo(self):
        Produto.objects.create(nome="Fora de linha", categoria=self.cat, ativo=False)
        url = reverse("estoque:produtos")
        ativos = self.client.get(url).context["produtos"]
        self.assertNotIn("Fora de linha", [p.nome for p in ativos])
        todos = self.client.get(url, {"situacao": "todos"}).context["produtos"]
        self.assertIn("Fora de linha", [p.nome for p in todos])


class KardexTests(TelasBase):
    def test_saldo_corrente_de_cada_movimento(self):
        registrar_saida(self.produto, self.almox, 10, self.user)
        linhas = self.client.get(
            reverse("estoque:kardex", args=[self.produto.pk])
        ).context["linhas"]
        self.assertEqual(
            [lin["saldo"] for lin in linhas], [Decimal("30"), Decimal("40")]
        )

    def test_filtra_por_local_e_por_sentido(self):
        transferir(self.produto, self.almox, self.loja, 5, self.user)
        url = reverse("estoque:kardex", args=[self.produto.pk])
        so_loja = self.client.get(url, {"local": self.loja.pk}).context["linhas"]
        self.assertEqual(len(so_loja), 1)
        self.assertEqual(so_loja[0]["saldo"], Decimal("5"))  # saldo DO LOCAL
        entradas = self.client.get(url, {"tipo": "entrada"}).context["linhas"]
        self.assertTrue(all(lin["movimento"].quantidade > 0 for lin in entradas))

    def test_consulta_nao_cresce_com_o_kardex(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("estoque:kardex", args=[self.produto.pk])
        self.client.get(url)
        with CaptureQueriesContext(connection) as poucos:
            self.client.get(url)
        for _ in range(10):
            registrar_saida(self.produto, self.almox, 1, self.user)
        with CaptureQueriesContext(connection) as muitos:
            self.client.get(url)
        self.assertEqual(len(muitos), len(poucos))


class MovimentarTests(TelasBase):
    def test_atalho_da_posicao_chega_preenchido(self):
        resposta = self.client.get(
            reverse("estoque:saida"),
            {"produto": self.produto.pk, "local": self.almox.pk},
        )
        form = resposta.context["form"]
        self.assertEqual(form.initial["produto"], str(self.produto.pk))
        self.assertEqual(form.initial["local"], str(self.almox.pk))

    def test_na_transferencia_o_local_vira_origem(self):
        form = self.client.get(
            reverse("estoque:transferencia"), {"local": self.almox.pk}
        ).context["form"]
        self.assertEqual(form.initial["origem"], str(self.almox.pk))
        self.assertNotIn("local", form.initial)

    def test_catalogo_da_previa_tem_saldo_por_local(self):
        transferir(self.produto, self.almox, self.loja, 10, self.user)
        dados = self.client.get(reverse("estoque:entrada")).context["produtos_json"]
        linha = next(p for p in dados if p["id"] == self.produto.pk)
        self.assertEqual(linha["saldos"][str(self.almox.pk)], 30.0)
        self.assertEqual(linha["saldos"][str(self.loja.pk)], 10.0)
        self.assertEqual(linha["unidade"], "un")

    def test_entrada_com_fornecedor_pela_tela(self):
        from apps.nucleo.models import Fornecedor, Pessoa

        pessoa = Pessoa.objects.create(nome="Distribuidora Teste")
        Fornecedor.objects.create(pessoa=pessoa)
        resposta = self.client.post(reverse("estoque:entrada"), {
            "produto": self.produto.pk, "local": self.almox.pk,
            "quantidade": "12", "custo_unitario": "3",
            "fornecedor": pessoa.pk, "documento": "NF 9", "observacao": "",
        })
        self.assertRedirects(resposta, reverse("estoque:posicao"))
        mov = MovimentoEstoque.objects.latest("criado_em")
        self.assertEqual(mov.fornecedor, pessoa)
        self.assertEqual(mov.documento, "NF 9")

    def test_transferencia_para_o_mesmo_local_avisa_no_campo(self):
        resposta = self.client.post(reverse("estoque:transferencia"), {
            "produto": self.produto.pk, "origem": self.almox.pk,
            "destino": self.almox.pk, "quantidade": "1", "observacao": "",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("destino", resposta.context["form"].errors)

    def test_saida_sem_saldo_volta_com_recado(self):
        resposta = self.client.post(reverse("estoque:saida"), {
            "produto": self.produto.pk, "local": self.loja.pk,
            "quantidade": "5", "tipo": "perda", "observacao": "",
        }, follow=True)
        recados = [m.message for m in resposta.context["messages"]]
        self.assertTrue(any("Saldo insuficiente" in m for m in recados), recados)


class ContagemTests(TelasBase):
    def _abrir(self):
        resposta = self.client.post(
            reverse("estoque:inventarios"), {"local": self.almox.pk}
        )
        inv = Inventario.objects.latest("criado_em")
        self.assertRedirects(resposta, reverse("estoque:inventario", args=[inv.pk]))
        return inv

    def test_abre_com_todos_os_produtos_e_nenhum_contado(self):
        inv = self._abrir()
        self.assertEqual(inv.itens.count(), Produto.objects.filter(ativo=True).count())
        self.assertEqual(inv.itens.filter(contado=True).count(), 0)
        resumo = self.client.get(
            reverse("estoque:inventario", args=[inv.pk])
        ).context["resumo"]
        self.assertEqual(resumo["contados"], 0)
        self.assertEqual(resumo["progresso"], 0)

    def test_campo_em_branco_nao_e_contagem(self):
        inv = self._abrir()
        item = inv.itens.get(produto=self.produto)
        self.client.post(
            reverse("estoque:inventario", args=[inv.pk]), {f"item_{item.pk}": ""}
        )
        item.refresh_from_db()
        self.assertFalse(item.contado)

    def test_o_que_ninguem_contou_fica_como_esta(self):
        """A venda feita durante a contagem não pode ser apagada pelo «Aplicar»."""
        inv = self._abrir()
        registrar_saida(self.produto, self.almox, 6, self.user)  # vendeu no meio
        outro = Produto.objects.create(nome="Suco", categoria=self.cat)
        inv.itens.create(produto=outro, saldo_sistema=Decimal("0"))
        item_outro = inv.itens.get(produto=outro)
        self.client.post(reverse("estoque:inventario", args=[inv.pk]), {
            f"item_{item_outro.pk}": "7", "aplicar": "1",
        })
        self.assertEqual(saldo(self.produto, self.almox), Decimal("34"))  # 40 − 6
        self.assertEqual(saldo(outro, self.almox), Decimal("7"))
        inv.refresh_from_db()
        self.assertEqual(inv.status, Inventario.Status.APLICADO)

    def test_contagem_invalida_nao_vira_saldo(self):
        inv = self._abrir()
        item = inv.itens.get(produto=self.produto)
        resposta = self.client.post(
            reverse("estoque:inventario", args=[inv.pk]),
            {f"item_{item.pk}": "trinta"}, follow=True,
        )
        item.refresh_from_db()
        self.assertFalse(item.contado)
        self.assertTrue(
            any("inválida" in m.message for m in resposta.context["messages"])
        )

    def test_lista_mostra_progresso_e_diferenca_em_dinheiro(self):
        inv = self._abrir()
        item = inv.itens.get(produto=self.produto)
        self.client.post(
            reverse("estoque:inventario", args=[inv.pk]), {f"item_{item.pk}": "38"}
        )
        linha = self.client.get(reverse("estoque:inventarios")).context["inventarios"][0]
        self.assertEqual(linha.itens_contados, 1)
        self.assertEqual(linha.valor_diferenca, Decimal("-5.00"))  # −2 × 2,50


class CadastrosTests(TelasBase):
    def test_salva_categoria_e_local_na_mesma_tela(self):
        url = reverse("estoque:cadastros")
        self.client.post(url, {"cadastro": "categoria", "nome": "Frios", "ativo": "on"})
        self.assertTrue(CategoriaProduto.objects.filter(nome="Frios").exists())
        self.client.post(url, {
            "cadastro": "local", "nome": "Rouparia", "modulo": "nucleo", "ativo": "on",
        })
        self.assertTrue(LocalEstoque.objects.filter(nome="Rouparia").exists())

    def test_mostra_o_valor_guardado_em_cada_local(self):
        locais = self.client.get(reverse("estoque:cadastros")).context["locais"]
        almox = next(lo for lo in locais if lo["local"].pk == self.almox.pk)
        self.assertEqual(almox["resumo"]["valor"], Decimal("100.00"))  # 40 × 2,50

    def test_endereco_antigo_redireciona(self):
        for nome in ("estoque:categorias", "estoque:locais"):
            self.assertRedirects(
                self.client.get(reverse(nome)), reverse("estoque:cadastros")
            )


class AcessoDasTelasTests(EstoqueBase):
    """Toda tela do módulo é protegida — não só a primeira."""

    TELAS = [
        "estoque:posicao", "estoque:produtos", "estoque:produto_novo",
        "estoque:cadastros", "estoque:entrada", "estoque:saida",
        "estoque:transferencia", "estoque:ajuste", "estoque:inventarios",
    ]

    def test_sem_o_modulo_no_usuario_da_403(self):
        Usuario.objects.create_user(username="sem", password="senha-forte-123")
        self.client.login(username="sem", password="senha-forte-123")
        for nome in self.TELAS:
            with self.subTest(tela=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 403)

    def test_modulo_desligado_da_404(self):
        ModuloContratado.objects.filter(codigo=Modulo.ESTOQUE).update(ativo=False)
        self.client.force_login(self.user)
        for nome in self.TELAS:
            with self.subTest(tela=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 404)
