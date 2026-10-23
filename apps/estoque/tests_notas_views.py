"""Fluxos HTTP das notas, com autorização, CSRF e documentos privados reais."""

import uuid

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.nucleo.models import (
    AnexoNotaEntrada,
    ItemNotaEntrada,
    ModuloContratado,
    MovimentoEstoque,
    NotaEntrada,
    RecebimentoNotaEntrada,
    Usuario,
    saldo,
)

from .tests_notas import NotasFixture


class TelasNotasTests(NotasFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def payload_cadastro(self, **campos):
        dados = {
            "chave": str(uuid.uuid4()), "fornecedor": str(self.fornecedor.pk), "tipo": "nfe",
            "numero": "NF-HTTP-101", "serie": "1", "emissao": self.hoje.isoformat(),
            "chave_acesso": "", "observacao": "Conferência fictícia mantida no formulário",
            "itens-TOTAL_FORMS": "2", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "1", "itens-MAX_NUM_FORMS": "100",
        }
        for indice, produto in enumerate((self.produto, self.perecivel)):
            dados.update({f"itens-{indice}-produto": str(produto.pk),
                          f"itens-{indice}-quantidade": "5" if indice == 0 else "3",
                          f"itens-{indice}-custo_unidade_compra": "7.50" if indice == 0 else "4.00",
                          f"itens-{indice}-embalagem": "", f"itens-{indice}-fator_conferido": ""})
        return {**dados, **campos}

    def payload_receber(self, nota, quantidades=None, **campos):
        itens = list(nota.itens.order_by("sequencia"))
        quantidades = quantidades or ["1"] * len(itens)
        dados = {
            "chave": str(uuid.uuid4()), "versao_conferida": str(nota.versao_recebimento),
            "observacao": "Entrega fictícia conferida", "parcelas-TOTAL_FORMS": str(len(itens)),
            "parcelas-INITIAL_FORMS": str(len(itens)), "parcelas-MIN_NUM_FORMS": "0",
            "parcelas-MAX_NUM_FORMS": "100",
        }
        for indice, (item, quantidade) in enumerate(zip(itens, quantidades, strict=True)):
            dados.update({f"parcelas-{indice}-item": str(item.pk),
                          f"parcelas-{indice}-quantidade": quantidade,
                          f"parcelas-{indice}-local": str(self.local.pk),
                          f"parcelas-{indice}-lote": str(self.lote.pk) if item.produto_id == self.perecivel.pk else ""})
        return {**dados, **campos}

    def test_cadastro_com_dois_itens_redireciona_para_nota_sem_receber_mercadoria(self):
        resposta = self.client.post(reverse("estoque:nota_nova"), self.payload_cadastro())
        nota = NotaEntrada.objects.get()
        self.assertRedirects(resposta, reverse("estoque:nota", args=[nota.pk]))
        self.assertEqual(nota.itens.count(), 2)
        self.assertEqual(nota.status, "pendente")
        self.conferir_sem_movimento()

    def test_reenvio_do_mesmo_post_nao_duplica_documento_nem_itens(self):
        dados = self.payload_cadastro()
        primeira = self.client.post(reverse("estoque:nota_nova"), dados)
        repetida = self.client.post(reverse("estoque:nota_nova"), dados)
        self.assertEqual(primeira.status_code, 302)
        self.assertEqual(repetida.status_code, 302)
        self.assertEqual(primeira.url, repetida.url)
        self.assertEqual((NotaEntrada.objects.count(), ItemNotaEntrada.objects.count()), (1, 2))
        self.conferir_sem_movimento()

    def test_erro_de_item_preserva_cabecalho_e_os_outros_itens(self):
        dados = self.payload_cadastro(**{"itens-1-quantidade": "NaN"})
        resposta = self.client.post(reverse("estoque:nota_nova"), dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["formset"].errors[1])
        self.assertEqual(resposta.context["form"]["numero"].value(), dados["numero"])
        self.assertEqual(resposta.context["form"]["observacao"].value(), dados["observacao"])
        self.assertEqual(resposta.context["formset"].forms[0]["produto"].value(), str(self.produto.pk))
        self.assertEqual(resposta.context["formset"].forms[0]["quantidade"].value(), "5")
        self.assertFalse(NotaEntrada.objects.exists())

    def test_produto_invalido_e_uuid_invalido_voltam_com_erro_de_formulario(self):
        for mudanca in ({"itens-0-produto": "invalido"},
                        {"itens-0-produto": "999999999999999999999999999999"},
                        {"chave": "nao-e-uuid"}):
            with self.subTest(mudanca=mudanca):
                resposta = self.client.post(reverse("estoque:nota_nova"), self.payload_cadastro(**mudanca))
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(resposta.context["form"].errors or any(resposta.context["formset"].errors))
                self.assertFalse(NotaEntrada.objects.exists())

    def test_duplicata_exibe_erro_sem_descartar_campos(self):
        self.nota(numero="NF-HTTP-101", serie="1")
        resposta = self.client.post(reverse("estoque:nota_nova"), self.payload_cadastro())
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["form"].non_field_errors())
        self.assertEqual(resposta.context["form"]["numero"].value(), "NF-HTTP-101")
        self.assertEqual(resposta.context["formset"].forms[1]["quantidade"].value(), "3")
        self.assertEqual(NotaEntrada.objects.count(), 1)

    def test_erros_para_formulario_preservado_retornam_422_json(self):
        dados = self.payload_cadastro(**{"itens-0-quantidade": "-1"})
        resposta = self.client.post(reverse("estoque:nota_nova"), dados, HTTP_X_FORM_PRESERVE="1")
        self.assertEqual(resposta.status_code, 422)
        self.assertTrue(resposta.json()["errors"])
        self.assertIn("no-store", resposta.headers["Cache-Control"])
        self.assertFalse(NotaEntrada.objects.exists())

    def test_recebimento_parcial_completo_e_reenvio_pelo_http(self):
        nota = self.nota(itens=[self.item_previsto(quantidade="5"), self.item_previsto(self.perecivel, "3")])
        url = reverse("estoque:nota_receber", args=[nota.pk])
        parcial = self.client.post(url, self.payload_receber(nota, ["2", "1"]))
        self.assertRedirects(parcial, reverse("estoque:nota", args=[nota.pk]))
        nota.refresh_from_db()
        self.assertEqual(nota.status, "parcial")
        dados = self.payload_receber(nota, ["3", "2"])
        completa = self.client.post(url, dados)
        self.assertRedirects(completa, reverse("estoque:nota", args=[nota.pk]))
        repetida = self.client.post(url, dados)
        self.assertRedirects(repetida, reverse("estoque:nota", args=[nota.pk]))
        nota.refresh_from_db()
        self.assertEqual((nota.status, nota.versao_recebimento), ("concluida", 2))
        self.assertEqual((saldo(self.produto), saldo(self.perecivel)), (5, 3))
        self.assertEqual(RecebimentoNotaEntrada.objects.count(), 2)
        self.assertEqual(MovimentoEstoque.objects.count(), 4)

    def test_recebimento_excessivo_ou_aba_antiga_preserva_dados_e_saldo(self):
        nota = self.nota()
        url = reverse("estoque:nota_receber", args=[nota.pk])
        excesso = self.client.post(url, self.payload_receber(nota, ["6"]))
        self.assertEqual(excesso.status_code, 200)
        self.assertTrue(excesso.context["form"].errors or any(excesso.context["formset"].errors))
        self.assertEqual(excesso.context["formset"].forms[0]["quantidade"].value(), "6")
        self.assertEqual(saldo(self.produto), 0)
        self.client.post(url, self.payload_receber(nota, ["1"]))
        antiga = self.client.post(url, self.payload_receber(nota, ["1"]))
        self.assertEqual(antiga.status_code, 200)
        self.assertTrue(antiga.context["form"].non_field_errors())
        self.assertEqual(antiga.context["formset"].forms[0]["quantidade"].value(), "1")
        self.assertEqual((saldo(self.produto), RecebimentoNotaEntrada.objects.count()), (1, 1))

    def test_item_postado_de_outra_nota_e_recusado_sem_movimento(self):
        nota, outra = self.nota(), self.nota()
        dados = self.payload_receber(nota, **{"parcelas-0-item": str(outra.itens.get().pk)})
        resposta = self.client.post(reverse("estoque:nota_receber", args=[nota.pk]), dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["formset"].errors[0])
        self.conferir_sem_movimento()

    def test_get_das_telas_nao_recebe_itens_e_anexar_exige_post(self):
        nota = self.nota()
        urls = [reverse("estoque:notas"), reverse("estoque:nota_nova"),
                reverse("estoque:nota", args=[nota.pk]), reverse("estoque:nota_receber", args=[nota.pk])]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("estoque:nota_anexar", args=[nota.pk])).status_code, 405)
        self.conferir_sem_movimento()

    def test_lista_filtra_por_estado_e_busca_sem_confundir_nota_parcial(self):
        pendente = self.nota(numero="BUSCA-PENDENTE")
        parcial = self.nota(numero="BUSCA-PARCIAL")
        concluida = self.nota(numero="BUSCA-CONCLUIDA", itens=[self.item_previsto(quantidade="1")])
        self.receber(parcial)
        self.receber(concluida, [self.parcela(concluida.itens.get(), "1")])
        for estado, esperada in (("pendente", pendente), ("parcial", parcial), ("concluida", concluida)):
            resposta = self.client.get(reverse("estoque:notas"), {"estado": estado, "q": "BUSCA"})
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual([nota.pk for nota in resposta.context["pagina"]], [esperada.pk])

    def test_detalhe_preserva_quatro_casas_no_custo_e_centavos_no_total(self):
        nota = self.nota(itens=[self.item_previsto(quantidade="3", custo="1234.5678")])
        resposta = self.client.get(reverse("estoque:nota", args=[nota.pk]))
        self.assertContains(resposta, 'data-rotulo="Custo / unidade">R$ 1.234,5678</td>', html=False)
        self.assertContains(resposta, 'data-rotulo="Total previsto">R$ 3.703,70</td>', html=False)
        self.conferir_sem_movimento()

    def test_cadastro_e_anexo_reutilizam_o_mesmo_validador_sem_guardar_arquivo_invalido(self):
        dados = self.payload_cadastro(documentos=[SimpleUploadedFile("falso.pdf", b"falso")])
        resposta = self.client.post(reverse("estoque:nota_nova"), dados)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("documentos", resposta.context["form"].errors)
        self.assertFalse(NotaEntrada.objects.exists())
        nota = self.nota()
        resposta = self.client.post(reverse("estoque:nota_anexar", args=[nota.pk]),
                                   {"documentos": [SimpleUploadedFile("falso.pdf", b"falso")]})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("documentos", resposta.context["form"].errors)
        self.assertFalse(AnexoNotaEntrada.objects.exists())

    def test_download_autenticado_entrega_bytes_e_headers_privados_sem_mudar_saldo(self):
        nota = self.nota(documentos=[self.xml()])
        anexo = nota.documentos.get()
        url = reverse("estoque:nota_documento", args=[nota.pk, anexo.pk])
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        # O iterador do Client fecha a resposta ao ser consumido. Não fechar uma
        # segunda vez: isso emite request_finished fora do isolamento do Client.
        self.assertEqual(b"".join(resposta.streaming_content), bytes(anexo.conteudo))
        self.assertIn("attachment", resposta.headers["Content-Disposition"])
        self.assertIn("private", resposta.headers["Cache-Control"])
        self.assertIn("no-store", resposta.headers["Cache-Control"])
        self.assertEqual(resposta.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resposta.headers["Content-Security-Policy"], "sandbox")
        outra = self.nota()
        self.assertEqual(self.client.get(reverse("estoque:nota_documento", args=[outra.pk, anexo.pk])).status_code, 404)
        self.conferir_sem_movimento()

    def test_documentos_multiplos_e_reenvio_do_mesmo_arquivo_nao_duplicam_conteudo(self):
        nota = self.nota()
        url = reverse("estoque:nota_anexar", args=[nota.pk])
        resposta = self.client.post(url, {"documentos": [self.xml("primeiro.xml"), self.xml("segundo.xml", "OUTRO_FICTICIO")]})
        self.assertRedirects(resposta, reverse("estoque:nota", args=[nota.pk]))
        self.assertEqual(nota.documentos.count(), 2)
        self.client.post(url, {"documentos": [self.xml("reenvio.xml")]})
        self.assertEqual(nota.documentos.count(), 2)
        self.conferir_sem_movimento()

    def test_sem_login_sem_modulo_e_modulo_desativado_nao_expoem_nota_ou_documento(self):
        nota = self.nota(documentos=[self.xml()])
        urls = [reverse("estoque:notas"), reverse("estoque:nota_nova"),
                reverse("estoque:nota", args=[nota.pk]), reverse("estoque:nota_receber", args=[nota.pk]),
                reverse("estoque:nota_documento", args=[nota.pk, nota.documentos.get().pk])]
        self.client.logout()
        for url in urls:
            with self.subTest(cenario="sem_login", url=url):
                resposta = self.client.get(url)
                self.assertEqual(resposta.status_code, 302)
                self.assertTrue(resposta.url.startswith(reverse("login")))
        comum = Usuario.objects.create_user(username="sem-modulo-notas")
        self.client.force_login(comum)
        for url in urls:
            with self.subTest(cenario="sem_modulo", url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        for url in (reverse("estoque:nota_nova"), reverse("estoque:nota_receber", args=[nota.pk]),
                    reverse("estoque:nota_anexar", args=[nota.pk])):
            self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.user)
        ModuloContratado.objects.filter(codigo="estoque").update(ativo=False)
        cache.clear()
        for url in urls:
            with self.subTest(cenario="inativo", url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(NotaEntrada.objects.count(), 1)
        self.conferir_sem_movimento()

    def test_operador_com_estoque_pode_cadastrar_e_receber_sem_gerencia(self):
        operador = Usuario.objects.create_user(username="operador-notas")
        operador.modulos.set(ModuloContratado.objects.filter(codigo="estoque"))
        self.client.force_login(operador)
        resposta = self.client.post(reverse("estoque:nota_nova"), self.payload_cadastro())
        self.assertEqual(resposta.status_code, 302)
        nota = NotaEntrada.objects.get()
        self.assertEqual(nota.criado_por_id, operador.pk)
        recebido = self.client.post(reverse("estoque:nota_receber", args=[nota.pk]), self.payload_receber(nota))
        self.assertEqual(recebido.status_code, 302)
        self.assertEqual(nota.recebimentos.get().criado_por_id, operador.pk)

    def test_csrf_e_exigido_em_todos_os_posts_que_gravam(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.user)
        nota = self.nota()
        for url, dados in (
            (reverse("estoque:nota_nova"), self.payload_cadastro()),
            (reverse("estoque:nota_receber", args=[nota.pk]), self.payload_receber(nota)),
            (reverse("estoque:nota_anexar", args=[nota.pk]), {"documentos": [self.xml()]}),
        ):
            with self.subTest(url=url):
                self.assertEqual(cliente.post(url, dados).status_code, 403)
        self.assertEqual(NotaEntrada.objects.count(), 1)
        self.assertFalse(AnexoNotaEntrada.objects.exists())
        self.conferir_sem_movimento()
