"""Notas previstas e recebimentos: invariantes do saldo, identidade e histórico."""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.nucleo.models import (
    AnexoNotaEntrada,
    CategoriaProduto,
    ContaPagarReceber,
    EmbalagemProduto,
    Fornecedor,
    ItemNotaEntrada,
    ItemRecebimentoNotaEntrada,
    LocalEstoque,
    LoteEstoque,
    ModuloContratado,
    MovimentoCaixa,
    MovimentoEstoque,
    NotaEntrada,
    Pessoa,
    Produto,
    RecebimentoNotaEntrada,
    RegistroLote,
    Usuario,
    registrar_compra,
    registrar_entrada,
    saldo,
)
from apps.nucleo.notas_entrada import cadastrar_nota_entrada, receber_nota_entrada


class NotasFixture:
    """Somente dados fictícios; não depende de seeds de módulos ou de produção."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = Usuario.objects.create_superuser(username="notas-qa", password="local-notas-123")
        self.cat = CategoriaProduto.objects.create(nome="Produtos fictícios de notas")
        self.local = LocalEstoque.objects.create(nome="Depósito fictício principal", modulo="nucleo")
        self.outro_local = LocalEstoque.objects.create(nome="Depósito fictício secundário", modulo="nucleo")
        self.produto = Produto.objects.create(nome="Guardanapos fictícios", categoria=self.cat)
        self.perecivel = Produto.objects.create(
            nome="Leite fictício", categoria=self.cat, unidade="l", controla_validade=True)
        self.embalagem = EmbalagemProduto.objects.create(
            produto=self.produto, nome="Caixa fictícia com 12 unidades", fator=12)
        self.fornecedor = Pessoa.objects.create(
            nome="Fornecedor fictício de testes", tipo="juridica", documento="12.345.678/0001-95")
        Fornecedor.objects.create(pessoa=self.fornecedor)
        self.hoje = timezone.localdate()
        self.lote = LoteEstoque.objects.create(
            produto=self.perecivel, codigo="LOTE-QA", validade=self.hoje + timedelta(days=10), criado_por=self.user)
        self.outro_lote = LoteEstoque.objects.create(
            produto=self.perecivel, codigo="OUTRO-QA", validade=self.hoje + timedelta(days=20), criado_por=self.user)
        ModuloContratado.objects.update_or_create(codigo="estoque", defaults={"ativo": True})
        self._proximo_numero = 100

    def item_previsto(self, produto=None, quantidade="5", custo="7.50", **campos):
        return {"produto": produto or self.produto, "quantidade": quantidade,
                "custo_unidade_compra": custo, **campos}

    def dados_nota(self, **campos):
        self._proximo_numero += 1
        return {"fornecedor": self.fornecedor, "tipo": "nfe", "numero": str(self._proximo_numero),
                "serie": "1", "emissao": self.hoje, "itens": [self.item_previsto()],
                "usuario": self.user, "chave": uuid.uuid4(), **campos}

    def nota(self, **campos):
        return cadastrar_nota_entrada(**self.dados_nota(**campos))

    def parcela(self, item, quantidade="2", local=None, **campos):
        return {"item": item, "quantidade": quantidade, "local": local or self.local, **campos}

    def receber(self, nota, parcelas=None, **campos):
        versao = NotaEntrada.objects.get(pk=nota.pk).versao_recebimento
        dados = {"parcelas": parcelas or [self.parcela(nota.itens.first())], "usuario": self.user,
                 "chave": uuid.uuid4(), "versao_conferida": versao, **campos}
        return receber_nota_entrada(nota, **dados)

    def conferir_sem_movimento(self):
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertFalse(RegistroLote.objects.exists())
        self.assertFalse(RecebimentoNotaEntrada.objects.exists())
        self.assertEqual(saldo(self.produto), 0)
        self.assertEqual(saldo(self.perecivel), 0)
        for produto in (self.produto, self.perecivel):
            produto.refresh_from_db()
            self.assertEqual(produto.custo_medio, 0)

    @staticmethod
    def xml(nome="nota-ficticia.xml", marcador="CONTEUDO_FICTICIO_NOTA"):
        return SimpleUploadedFile(nome, f'<?xml version="1.0"?><nota>{marcador}</nota>'.encode(),
                                  content_type="application/xml")


class CadastroNotasTests(NotasFixture, TestCase):
    def test_cadastrar_dois_itens_nao_mexe_em_saldo_custo_ou_financeiro(self):
        financeiro = MovimentoCaixa.objects.count(), ContaPagarReceber.objects.count()
        nota = self.nota(itens=[self.item_previsto(), self.item_previsto(self.perecivel, "3", "4.00")])
        self.assertEqual(nota.itens.count(), 2)
        self.assertEqual(nota.status, "pendente")
        self.assertEqual(nota.versao_recebimento, 0)
        self.assertEqual(nota.fornecedor_nome, self.fornecedor.nome)
        self.conferir_sem_movimento()
        self.assertEqual((MovimentoCaixa.objects.count(), ContaPagarReceber.objects.count()), financeiro)

    def test_reenvio_do_cadastro_retorna_mesma_nota_sem_duplicar_itens(self):
        dados = self.dados_nota()
        nota = cadastrar_nota_entrada(**dados)
        repetida = cadastrar_nota_entrada(**dados)
        self.assertEqual(repetida.pk, nota.pk)
        self.assertEqual(NotaEntrada.objects.count(), 1)
        self.assertEqual(ItemNotaEntrada.objects.count(), 1)
        self.conferir_sem_movimento()

    def test_uuid_do_cadastro_nao_pode_ser_reutilizado_com_outro_conteudo(self):
        dados = self.dados_nota()
        nota = cadastrar_nota_entrada(**dados)
        for mudanca in ({"numero": "999"}, {"itens": [self.item_previsto(quantidade="6")]},
                        {"observacao": "Outra conferência"}):
            with self.subTest(mudanca=mudanca), self.assertRaises(ValidationError):
                cadastrar_nota_entrada(**{**dados, **mudanca})
        self.assertEqual(list(NotaEntrada.objects.values_list("pk", flat=True)), [nota.pk])
        self.conferir_sem_movimento()

    def test_chave_fiscal_repetida_bloqueia_outro_cadastro_mesmo_com_outro_numero(self):
        self.nota(chave_acesso="1" * 44)
        with self.assertRaises(ValidationError):
            self.nota(numero="999", chave_acesso="1" * 44)
        self.assertEqual(NotaEntrada.objects.count(), 1)

    def test_emitente_normalizado_bloqueia_duplicata_mesmo_em_outro_cadastro_de_pessoa(self):
        self.nota(numero="42", serie="1")
        repetido = Pessoa.objects.create(nome="Mesmo emitente fictício", tipo="juridica", documento="12345678000195")
        Fornecedor.objects.create(pessoa=repetido)
        with self.assertRaises(ValidationError):
            self.nota(fornecedor=repetido, numero="42", serie="1")
        self.assertEqual(NotaEntrada.objects.count(), 1)

    def test_numero_igual_em_serie_tipo_ou_emitente_diferentes_e_legitimo(self):
        self.nota(numero="42", serie="1", tipo="nfe")
        self.nota(numero="42", serie="2", tipo="nfe")
        self.nota(numero="42", serie="1", tipo="outro")
        outro = Pessoa.objects.create(nome="Outro emitente fictício", documento="11.222.333/0001-81")
        Fornecedor.objects.create(pessoa=outro)
        self.nota(fornecedor=outro, numero="42", serie="1", tipo="nfe")
        self.assertEqual(NotaEntrada.objects.count(), 4)

    def test_identidade_e_descricao_ficam_congeladas_apos_editar_fornecedor_e_produto(self):
        nota = self.nota(numero="42")
        identidade, nome = nota.documento_numero, nota.fornecedor_nome
        item = nota.itens.get()
        nome_produto = item.produto_nome
        Pessoa.objects.filter(pk=self.fornecedor.pk).update(nome="Nome posterior", documento="11.222.333/0001-81")
        Produto.objects.filter(pk=self.produto.pk).update(nome="Produto renomeado")
        nota.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((nota.documento_numero, nota.fornecedor_nome), (identidade, nome))
        self.assertEqual(item.produto_nome, nome_produto)

    def test_documento_corrigido_do_mesmo_fornecedor_nao_permite_recadastrar_nota(self):
        nota = self.nota(numero="42", serie="1")
        identidade_original = nota.documento_numero
        Pessoa.objects.filter(pk=self.fornecedor.pk).update(documento="11.222.333/0001-81")
        with self.assertRaises(ValidationError):
            self.nota(numero="42", serie="1")
        nota.refresh_from_db()
        self.assertEqual(nota.documento_numero, identidade_original)
        self.assertEqual(NotaEntrada.objects.count(), 1)

    def test_fator_desatualizado_e_embalagem_de_outro_produto_sao_recusados(self):
        for campos in ({"embalagem": self.embalagem, "fator_conferido": "6"},
                       {"produto": self.perecivel, "embalagem": self.embalagem, "fator_conferido": "12"}):
            item = {**self.item_previsto(), **campos}
            with self.subTest(campos=campos), self.assertRaises(ValidationError):
                self.nota(itens=[item])
        self.assertFalse(NotaEntrada.objects.exists())
        self.conferir_sem_movimento()

    def test_cadastro_recusa_lista_vazia_valores_nao_finitos_excesso_e_precisao(self):
        with self.assertRaises(ValidationError):
            self.nota(itens=[])
        casos = [("quantidade", valor) for valor in ("0", "-1", "NaN", "Infinity", "1e999999", "1000000000", "0.0001", True)]
        casos += [("custo_unidade_compra", valor) for valor in ("-1", "NaN", "Infinity", "1e999999", "100000000", "0.00001", True)]
        for campo, valor in casos:
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError), transaction.atomic():
                self.nota(itens=[{**self.item_previsto(), campo: valor}])
        self.assertFalse(NotaEntrada.objects.exists())
        self.conferir_sem_movimento()

    def test_cadastro_recusa_chave_fiscal_malformada_e_uuid_invalido_sem_500(self):
        for campos in ({"chave_acesso": "1" * 43}, {"chave_acesso": "x" * 44},
                       {"chave_acesso": "١" * 44}, {"chave": "nao-e-uuid"}):
            with self.subTest(campos=campos), self.assertRaises(ValidationError):
                self.nota(**campos)
        self.assertFalse(NotaEntrada.objects.exists())


class RecebimentoNotasTests(NotasFixture, TestCase):
    def test_parcial_e_conclusao_baixam_pendencia_e_entram_so_as_quantidades_recebidas(self):
        nota = self.nota(itens=[self.item_previsto(quantidade="5"), self.item_previsto(self.perecivel, "3", "4")])
        comum, leite = list(nota.itens.order_by("sequencia"))
        primeiro = self.receber(nota, [self.parcela(comum, "2"), self.parcela(leite, "1", lote=self.lote)])
        nota.refresh_from_db()
        self.assertEqual((nota.status, nota.versao_recebimento), ("parcial", 1))
        self.assertEqual((saldo(self.produto), saldo(self.perecivel)), (2, 1))
        self.assertEqual(primeiro.parcelas.count(), 2)
        segundo = self.receber(nota, [self.parcela(comum, "3"), self.parcela(leite, "2", lote=self.lote)])
        nota.refresh_from_db()
        self.assertEqual((nota.status, nota.versao_recebimento), ("concluida", 2))
        self.assertEqual((saldo(self.produto), saldo(self.perecivel)), (5, 3))
        self.assertEqual(segundo.parcelas.count(), 2)
        self.assertEqual(MovimentoEstoque.objects.count(), 4)
        comum.refresh_from_db()
        leite.refresh_from_db()
        self.assertEqual((comum.quantidade_recebida, comum.quantidade_pendente), (5, 0))
        self.assertEqual((leite.quantidade_recebida, leite.quantidade_pendente), (3, 0))

    def test_parcelas_repetidas_do_mesmo_item_somam_no_teto_antes_de_gravar(self):
        nota = self.nota(itens=[self.item_previsto(quantidade="5")])
        item = nota.itens.get()
        with self.assertRaises(ValidationError):
            self.receber(nota, [self.parcela(item, "3"), self.parcela(item, "3", local=self.outro_local)])
        self.conferir_sem_movimento()
        self.receber(nota, [self.parcela(item, "2"), self.parcela(item, "3", local=self.outro_local)])
        self.assertEqual((saldo(self.produto, self.local), saldo(self.produto, self.outro_local)), (2, 3))
        self.assertEqual(MovimentoEstoque.objects.count(), 2)

    def test_reenvio_apos_conclusao_usa_versao_original_sem_duplicar_nem_trocar_autor(self):
        nota = self.nota(itens=[self.item_previsto(quantidade="2")])
        chave = uuid.uuid4()
        parcelas = [self.parcela(nota.itens.get(), "2")]
        primeiro = self.receber(nota, parcelas, chave=chave, versao_conferida=0)
        outro = Usuario.objects.create_user(username="outro-operador-notas")
        repetido = self.receber(nota, parcelas, chave=chave, versao_conferida=0, usuario=outro)
        self.assertEqual(repetido.pk, primeiro.pk)
        self.assertEqual(repetido.criado_por_id, self.user.pk)
        self.assertEqual((MovimentoEstoque.objects.count(), RecebimentoNotaEntrada.objects.count()), (1, 1))
        self.assertEqual(saldo(self.produto), 2)

    def test_chave_reutilizada_com_quantidade_local_ou_observacao_alterados_e_recusada(self):
        nota = self.nota()
        item, chave = nota.itens.get(), uuid.uuid4()
        self.receber(nota, [self.parcela(item, "2")], chave=chave, versao_conferida=0)
        mudancas = [([self.parcela(item, "3")], {}),
                    ([self.parcela(item, "2", local=self.outro_local)], {}),
                    ([self.parcela(item, "2")], {"observacao": "Outra parcela"})]
        for parcelas, extras in mudancas:
            with self.subTest(parcelas=parcelas, extras=extras), self.assertRaises(ValidationError):
                self.receber(nota, parcelas, chave=chave, versao_conferida=0, **extras)
        self.assertEqual((saldo(self.produto), MovimentoEstoque.objects.count()), (2, 1))

    def test_duas_abas_nao_recebem_sobre_versao_antiga_mesmo_havendo_pendencia(self):
        nota = self.nota()
        item = nota.itens.get()
        self.receber(nota, [self.parcela(item, "1")], versao_conferida=0)
        with self.assertRaises(ValidationError):
            self.receber(nota, [self.parcela(item, "1")], versao_conferida=0)
        self.assertEqual((saldo(self.produto), RecebimentoNotaEntrada.objects.count()), (1, 1))
        nota.refresh_from_db()
        self.assertEqual(nota.versao_recebimento, 1)

    def test_item_de_outra_nota_e_uuid_de_outro_recebimento_nao_podem_ser_reaproveitados(self):
        primeira, outra = self.nota(), self.nota()
        with self.assertRaises(ValidationError):
            self.receber(primeira, [self.parcela(outra.itens.get())])
        chave = uuid.uuid4()
        self.receber(primeira, chave=chave, versao_conferida=0)
        with self.assertRaises(ValidationError):
            self.receber(outra, chave=chave, versao_conferida=0)
        self.assertEqual((saldo(self.produto), RecebimentoNotaEntrada.objects.count()), (2, 1))

    def test_lote_invalido_na_segunda_linha_reverte_movimentos_custo_e_versao(self):
        nota = self.nota(itens=[self.item_previsto(), self.item_previsto(self.perecivel)])
        comum, leite = list(nota.itens.order_by("sequencia"))
        vencido = LoteEstoque.objects.create(
            produto=self.perecivel, codigo="VENCIDO-QA", validade=self.hoje - timedelta(days=1), criado_por=self.user)
        for lote in (None, vencido):
            with self.subTest(lote=lote), self.assertRaises(ValidationError):
                self.receber(nota, [self.parcela(comum), self.parcela(leite, lote=lote)])
            self.conferir_sem_movimento()
            nota.refresh_from_db()
            self.assertEqual(nota.versao_recebimento, 0)
        valido_hoje = LoteEstoque.objects.create(
            produto=self.perecivel, codigo="HOJE-QA", validade=self.hoje, criado_por=self.user)
        self.receber(nota, [self.parcela(leite, lote=valido_hoje)])
        self.assertEqual(saldo(self.perecivel), 2)

    def test_lote_errado_e_reuso_da_chave_com_outro_lote_sao_recusados(self):
        nota = self.nota(itens=[self.item_previsto(self.perecivel)])
        item = nota.itens.get()
        outro_perecivel = Produto.objects.create(
            nome="Outro perecível fictício", categoria=self.cat, controla_validade=True)
        errado = LoteEstoque.objects.create(
            produto=outro_perecivel, codigo="OUTRO-PRODUTO-QA", validade=self.hoje, criado_por=self.user)
        with self.assertRaises(ValidationError):
            self.receber(nota, [self.parcela(item, lote=errado)])
        chave = uuid.uuid4()
        self.receber(nota, [self.parcela(item, lote=self.lote)], chave=chave, versao_conferida=0)
        with self.assertRaises(ValidationError):
            self.receber(nota, [self.parcela(item, lote=self.outro_lote)], chave=chave, versao_conferida=0)
        self.assertEqual((saldo(self.perecivel), RegistroLote.objects.count()), (2, 1))

    def test_falha_no_segundo_movimento_reverte_primeiro_custo_lote_e_versao(self):
        nota = self.nota(itens=[self.item_previsto(self.perecivel), self.item_previsto()])
        leite, comum = list(nota.itens.order_by("sequencia"))
        parcelas = [self.parcela(leite, lote=self.lote), self.parcela(comum)]
        chamadas = []

        def registrar_ou_falhar(*args, **kwargs):
            chamadas.append(True)
            if len(chamadas) == 2:
                raise ValidationError("Falha fictícia ao persistir o segundo movimento.")
            movimento = registrar_entrada(*args, **kwargs)
            self.assertTrue(MovimentoEstoque.objects.filter(pk=movimento.pk).exists())
            self.assertEqual(RegistroLote.objects.count(), 1)
            self.perecivel.refresh_from_db()
            self.assertEqual(self.perecivel.custo_medio, Decimal("7.5000"))
            return movimento

        with patch("apps.nucleo.notas_entrada.registrar_entrada", side_effect=registrar_ou_falhar):
            with self.assertRaisesMessage(ValidationError, "Falha fictícia"):
                self.receber(nota, parcelas)

        self.assertEqual(len(chamadas), 2)
        self.conferir_sem_movimento()
        self.assertFalse(ItemRecebimentoNotaEntrada.objects.exists())
        nota.refresh_from_db()
        self.assertEqual((nota.status, nota.versao_recebimento), ("pendente", 0))

    def test_recebimento_usa_fator_e_custo_da_nota_mesmo_com_embalagem_renomeada(self):
        registrar_entrada(self.produto, self.local, 6, 2, self.user)
        nota = self.nota(itens=[self.item_previsto(quantidade="2", custo="60",
                                                embalagem=self.embalagem, fator_conferido="12")])
        self.embalagem.fator = 6
        self.embalagem.nome = "Caixa posterior com seis"
        self.embalagem.save()
        recebimento = self.receber(nota, [self.parcela(nota.itens.get(), "1")])
        mov = recebimento.parcelas.get().movimento
        self.assertEqual((mov.quantidade, mov.custo_unitario), (12, 5))
        self.assertEqual(Decimal(mov.compra["fator"]), 12)
        self.assertEqual(Decimal(mov.compra["valor_total"]), 60)
        self.assertEqual(saldo(self.produto), 18)
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.custo_medio, 4)
        self.assertEqual(nota.itens.get().fator, 12)

    def test_parcela_fracionada_preserva_total_de_aquisicao_antes_do_arredondamento(self):
        self.embalagem.fator = 3
        self.embalagem.save()
        nota = self.nota(itens=[self.item_previsto(quantidade="2", custo="10",
                                                embalagem=self.embalagem, fator_conferido="3")])
        recebimento = self.receber(nota, [self.parcela(nota.itens.get(), "2")])
        mov = recebimento.parcelas.get().movimento
        self.assertEqual(mov.custo_unitario, Decimal("3.3333"))
        self.assertEqual(Decimal(mov.compra["valor_total"]), 20)
        self.assertEqual(saldo(self.produto), 6)

    def test_recebimento_recusa_quantidades_invalidas_e_excesso_sem_escrita_parcial(self):
        nota = self.nota()
        item = nota.itens.get()
        for valor in ("0", "-1", "NaN", "Infinity", "1e999999", "1000000000", "0.0001", "6", True):
            with self.subTest(valor=valor), self.assertRaises(ValidationError), transaction.atomic():
                self.receber(nota, [self.parcela(item, valor)])
        with self.assertRaises(ValidationError):
            receber_nota_entrada(nota, parcelas=[], usuario=self.user, chave=uuid.uuid4(), versao_conferida=0)
        self.conferir_sem_movimento()

    def test_fluxo_legado_continua_independente_e_receber_nota_nao_cria_conta_ou_caixa(self):
        legado = registrar_compra(self.embalagem, self.local, 1, 60, self.user,
                                  fornecedor=self.fornecedor, documento="Documento legado fictício", chave=uuid.uuid4())
        snapshot = legado.quantidade, legado.custo_unitario, legado.documento, legado.compra
        financeiro = MovimentoCaixa.objects.count(), ContaPagarReceber.objects.count()
        nota = self.nota()
        self.receber(nota)
        legado.refresh_from_db()
        self.assertEqual((legado.quantidade, legado.custo_unitario, legado.documento, legado.compra), snapshot)
        self.assertFalse(ItemRecebimentoNotaEntrada.objects.filter(movimento=legado).exists())
        self.assertEqual(saldo(self.produto), 14)
        self.assertEqual((MovimentoCaixa.objects.count(), ContaPagarReceber.objects.count()), financeiro)


class DocumentosEImutabilidadeNotasTests(NotasFixture, TestCase):
    def test_documento_privado_valido_guarda_bytes_hash_e_nao_cria_arquivo_publico(self):
        arquivo = self.xml()
        conteudo = arquivo.read()
        arquivo.seek(0)
        nota = self.nota(documentos=[arquivo])
        anexo = nota.documentos.get()
        self.assertEqual(bytes(anexo.conteudo), conteudo)
        self.assertEqual(anexo.sha256, hashlib.sha256(conteudo).hexdigest())
        self.assertEqual(anexo.tamanho, len(conteudo))
        self.assertEqual(anexo.tipo, "application/xml")
        self.assertFalse(hasattr(anexo, "url"))
        self.conferir_sem_movimento()

    def test_documento_invalido_reverte_cadastro_inteiro(self):
        for arquivo in (SimpleUploadedFile("falso.pdf", b"texto comum", content_type="application/pdf"),
                        SimpleUploadedFile("entidade.xml", b'<!DOCTYPE x [<!ENTITY a "teste">]><x>&a;</x>'),
                        SimpleUploadedFile("script.html", b"<script>alert(1)</script>")):
            with self.subTest(nome=arquivo.name), self.assertRaises(ValidationError):
                self.nota(documentos=[arquivo])
        self.assertFalse(NotaEntrada.objects.exists())
        self.assertFalse(ItemNotaEntrada.objects.exists())
        self.assertFalse(AnexoNotaEntrada.objects.exists())

    def test_documento_preparado_adulterado_nao_burla_validador_compartilhado(self):
        falso = {"nome": "falso.pdf", "tipo": "application/pdf", "tamanho": 4,
                 "conteudo": b"ruim", "sha256": hashlib.sha256(b"ruim").hexdigest()}
        with self.assertRaises(ValidationError):
            self.nota(documentos=[falso])
        self.assertFalse(NotaEntrada.objects.exists())

    def test_documento_duplicado_no_mesmo_cadastro_e_guardado_uma_vez(self):
        nota = self.nota(documentos=[self.xml("primeiro.xml"), self.xml("reenvio.xml")])
        self.assertEqual(nota.documentos.count(), 1)

    def test_cadastro_com_documentos_acima_do_limite_nao_grava_nada(self):
        arquivos = [self.xml(f"documento-{n}.xml", f"FICTICIO_{n}") for n in range(11)]
        with self.assertRaises(ValidationError):
            self.nota(documentos=arquivos)
        self.assertFalse(NotaEntrada.objects.exists())
        self.assertFalse(AnexoNotaEntrada.objects.exists())

    def test_models_e_querysets_nao_permitem_reescrever_ou_apagar_historico(self):
        nota = self.nota(documentos=[self.xml()])
        recebido = self.receber(nota)
        objetos = [(nota, "numero", "alterada"), (nota.itens.get(), "quantidade", Decimal("99")),
                   (recebido, "observacao", "alterada"),
                   (recebido.parcelas.get(), "quantidade", Decimal("99")),
                   (nota.documentos.get(), "nome", "alterado.xml")]
        for objeto, campo, valor in objetos:
            modelo = type(objeto)
            with self.subTest(modelo=modelo.__name__):
                setattr(objeto, campo, valor)
                with self.assertRaises(ValidationError):
                    objeto.save()
                with self.assertRaises(ValidationError):
                    objeto.delete()
                with self.assertRaises(ValidationError):
                    modelo.objects.filter(pk=objeto.pk).update(**{campo: valor})
                with self.assertRaises(ValidationError):
                    modelo.objects.filter(pk=objeto.pk).delete()
        self.assertEqual(saldo(self.produto), 2)
        self.assertEqual(NotaEntrada.objects.count(), 1)
