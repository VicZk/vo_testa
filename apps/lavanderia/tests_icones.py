"""Inferência do ícone pelo nome (§8 da especificação da Lavanderia).

O ícone não é enfeite: ele aparece no cartão da fila, na grade do balcão, na linha da
cesta, na rouparia e no extrato. Errar o ícone é errar a leitura — por isso cada caso
difícil tem teste: a fronteira de palavra ("Calção" não é calça), o sinônimo mais longo
("Toalha de banho" não é maiô) e a escolha manual, que sempre vence.
"""
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase

from .icones import (
    ESCOLHAS_ICONES_LAV,
    GRUPOS,
    GRUPOS_DA_TABELA,
    ICONES,
    icone_de,
    rotulo_de,
)


class InferenciaDeIconeTests(SimpleTestCase):
    def test_nome_da_tabela_de_precos_cai_na_peca_certa(self):
        self.assertEqual(icone_de("Camisa social"), "camisa")
        self.assertEqual(icone_de("Roupa por quilo"), "quilo")
        self.assertEqual(icone_de("Passar (peça)"), "passar")
        self.assertEqual(icone_de("Vestido"), "vestido")
        self.assertEqual(icone_de("Calça"), "calca")

    def test_sinonimo_mais_longo_vence_o_mais_curto(self):
        # "toalha de banho" (15 letras) tem de ser conferido antes de "banho" (5), senão
        # a toalha do enxoval vira maiô.
        self.assertEqual(icone_de("Toalha de banho"), "toalha_banho")
        self.assertEqual(icone_de("Toalha de rosto"), "toalha_rosto")
        self.assertEqual(icone_de("Toalha de praia"), "toalha_praia")
        self.assertEqual(icone_de("Lençol casal"), "lencol")
        self.assertEqual(icone_de("Fronha"), "fronha")

    def test_fronteira_de_palavra_separa_calcao_de_calca(self):
        self.assertEqual(icone_de("Calção"), "bermuda")
        self.assertEqual(icone_de("Calcao"), "bermuda")
        self.assertEqual(icone_de("Calça social"), "calca")

    def test_nome_desconhecido_cai_no_generico(self):
        self.assertEqual(icone_de("Tapeçaria de veludo azul"), "generico")
        self.assertEqual(icone_de(""), "generico")
        self.assertEqual(icone_de(None), "generico")

    def test_escolha_manual_vence_a_inferencia(self):
        self.assertEqual(icone_de("Camisa social", "seco"), "seco")
        # Escolha inválida (chave que não existe) volta para a inferência.
        self.assertEqual(icone_de("Camisa social", "sutia"), "camisa")
        self.assertEqual(icone_de("Camisa social", "inventado"), "camisa")

    def test_sutia_nao_e_chave_e_cai_em_roupa_intima(self):
        self.assertNotIn("sutia", ICONES)
        self.assertEqual(icone_de("Sutiã"), "intima")
        self.assertEqual(icone_de("Soutien"), "intima")
        self.assertEqual(icone_de("Top íntimo"), "intima")
        self.assertEqual(icone_de("Cueca"), "intima")

    def test_acento_e_maiuscula_nao_mudam_a_chave(self):
        for nome in ("LENÇOL CASAL", "lencol casal", "Lençol Casal"):
            self.assertEqual(icone_de(nome), "lencol", nome)

    def test_estado_da_rouparia_tem_icone_proprio(self):
        self.assertEqual(icone_de("Limpa"), "estado_limpa")
        self.assertEqual(icone_de("Em uso"), "estado_em_uso")
        self.assertEqual(icone_de("Suja"), "estado_suja")
        self.assertEqual(icone_de("Lavando"), "estado_lavando")


class CatalogoDeIconesTests(SimpleTestCase):
    def test_sao_trinta_e_seis_chaves_bem_formadas(self):
        self.assertEqual(len(ICONES), 36)
        grupos = {codigo for codigo, _ in GRUPOS}
        for chave, dados in ICONES.items():
            with self.subTest(chave=chave):
                self.assertTrue(dados["rotulo"][:1].isupper(), "rótulo começa com maiúscula")
                self.assertIn(dados["grupo"], grupos)
                self.assertTrue(dados["sinonimos"])
                self.assertTrue(dados["svg"].startswith(("<path", "<circle")))
                self.assertNotIn("<svg", dados["svg"], "o miolo não repete a casca")
                self.assertNotIn('fill="#', dados["svg"], "cor só por currentColor")

    def test_escolhas_vem_agrupadas_e_sem_os_estados_do_enxoval(self):
        """A tabela de preços oferece peça, serviço e enxoval — não ESTADO.

        «Limpa», «Suja» e «Lavando» são a cor da barra da rouparia, não um serviço
        que o hóspede compra: na grade de 36 desenhos eles só atrapalhavam a escolha.
        """
        self.assertEqual([grupo for grupo, _ in ESCOLHAS_ICONES_LAV],
                         ["Peças", "Serviços", "Enxoval"])
        oferecidas = [chave for _, opcoes in ESCOLHAS_ICONES_LAV for chave, _ in opcoes]
        self.assertNotIn("estado_limpa", oferecidas)
        self.assertEqual(len(oferecidas),
                         sum(1 for d in ICONES.values() if d["grupo"] in GRUPOS_DA_TABELA))
        for _, opcoes in ESCOLHAS_ICONES_LAV:
            for chave, rotulo in opcoes:
                self.assertEqual(rotulo, rotulo_de(chave))

    def test_procedencia_declarada_em_toda_chave(self):
        fontes = {}
        for chave, dados in ICONES.items():
            with self.subTest(chave=chave):
                self.assertTrue(dados["fonte"])
                self.assertTrue(dados["licenca"])
                if dados["fonte"] != "proprio":
                    self.assertIn("arquivo", dados, "traçado de fora aponta o SVG de origem")
            fontes[dados["fonte"].split("@")[0]] = True
        self.assertEqual(set(fontes), {"lucide", "tabler", "proprio"})


class ProcedenciaDoVendorTests(SimpleTestCase):
    """O registro de procedência tem de continuar verdadeiro.

    Declarar `fonte`, `licenca` e `arquivo` não prova nada se o arquivo não existe
    mais ou se o traçado baixado foi editado à mão depois: o `origem.json` envelheceria
    em silêncio e a licença de terceiro ficaria pendurada num desenho que já é outro.
    Aqui o sha256 do que está no disco é conferido contra o que foi registrado, e cada
    chave de fora aponta um arquivo que existe.
    """

    VENDOR = Path(settings.BASE_DIR) / "static" / "vendor"

    def test_sha256_de_cada_arquivo_bate_com_o_registro(self):
        for projeto in ("lucide", "tabler"):
            registro = json.loads((self.VENDOR / projeto / "origem.json").read_text(encoding="utf-8"))
            self.assertTrue(registro["arquivos"], projeto)
            for nome, dados in registro["arquivos"].items():
                with self.subTest(projeto=projeto, arquivo=nome):
                    caminho = self.VENDOR / projeto / nome
                    self.assertTrue(caminho.exists(), "arquivo registrado não está no disco")
                    atual = hashlib.sha256(caminho.read_bytes()).hexdigest()
                    self.assertEqual(atual, dados["sha256"], "o arquivo mudou depois de registrado")
                    self.assertTrue(dados["url"].startswith("https://"))

    def test_toda_chave_de_fora_aponta_um_arquivo_que_existe(self):
        for chave, dados in ICONES.items():
            if dados["fonte"] == "proprio":
                continue
            projeto = dados["fonte"].split("@")[0]
            with self.subTest(chave=chave):
                registro = json.loads(
                    (self.VENDOR / projeto / "origem.json").read_text(encoding="utf-8"))
                self.assertIn(dados["arquivo"], registro["arquivos"])
                self.assertTrue((self.VENDOR / projeto / dados["arquivo"]).exists())


class TagDeIconeTests(SimpleTestCase):
    def renderizar(self, trecho, **contexto):
        return Template("{% load pecas_lavanderia %}" + trecho).render(Context(contexto))

    def test_tag_devolve_svg_acessivel_com_a_classe_da_casa(self):
        html = self.renderizar('{% icone_peca "Camisa social" %}')
        self.assertIn('class="ico-peca"', html)
        self.assertIn('viewBox="0 0 24 24"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn('focusable="false"', html)
        self.assertIn("<path", html)

    def test_tag_aceita_a_escolha_manual_e_classe_extra(self):
        manual = self.renderizar('{% icone_peca "Camisa social" "quilo" %}')
        self.assertIn(ICONES["quilo"]["svg"][:40], manual)
        extra = self.renderizar('{% icone_peca "Camisa social" classe="ico-peca--grande" %}')
        self.assertIn('class="ico-peca ico-peca--grande"', extra)

    def test_rotulo_da_chave_vem_do_catalogo(self):
        """Quem traduz a chave é `rotulo_de` (usado por `ESCOLHAS_ICONES_LAV`).

        O filtro de template que fazia isto saiu: nenhuma tela o usava, e ele chamava
        a chave vazia de «Genérico (peça)» enquanto o `<select>` a chama de «Automático
        pelo nome» — duas palavras para a mesma coisa.
        """
        self.assertEqual(rotulo_de("lencol"), "Lençol")
        self.assertEqual(rotulo_de("camisa"), "Camisa social")
