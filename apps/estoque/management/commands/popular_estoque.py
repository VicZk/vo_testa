"""
Popula o Estoque para demonstração: categorias, produtos de verdade da pousada,
depósitos e um histórico de movimentos (compras, transferências, consumo e
perdas) que deixa a posição com os três casos que a tela precisa mostrar —
produto em dia, produto abaixo do mínimo e produto zerado.

Uso: `manage.py popular_estoque` (idempotente: rodar de novo não duplica nada;
só completa o que faltar). Os movimentos nascem pelos services do motor
(`registrar_entrada`, `transferir`, `registrar_saida`) — nunca por create solto.
"""
from decimal import ROUND_DOWN, Decimal
from random import Random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.nucleo.models import (
    CategoriaProduto,
    LocalEstoque,
    MovimentoEstoque,
    Produto,
    registrar_entrada,
    registrar_saida,
    saldo,
    transferir,
)

Usuario = get_user_model()

LOCAIS = [
    ("Almoxarifado central", "nucleo"),
    ("Depósito da Loja", "loja"),
    ("Cozinha/Restaurante", "restaurante"),
    ("Rouparia", "lavanderia"),
]

# nome, categoria, unidade, custo, preço de venda, mínimo, compra inicial
PRODUTOS = [
    ("Água mineral 500ml", "Bebidas", "un", "1.20", "4.00", 48, 120),
    ("Refrigerante lata", "Bebidas", "un", "2.50", "7.00", 48, 96),
    ("Cerveja long neck", "Bebidas", "un", "3.80", "12.00", 48, 72),
    ("Suco de uva integral 1 L", "Bebidas", "un", "11.00", "22.00", 12, 24),
    ("Água de coco 1 L", "Bebidas", "un", "9.50", "18.00", 12, 18),
    ("Café em grãos", "Alimentos", "kg", "32.00", "0", 5, 12),
    ("Açúcar refinado", "Alimentos", "kg", "4.20", "0", 10, 25),
    ("Leite integral 1 L", "Alimentos", "un", "4.90", "0", 24, 48),
    ("Pão de forma", "Alimentos", "un", "7.50", "0", 10, 20),
    ("Queijo prato", "Alimentos", "kg", "42.00", "0", 3, 6),
    ("Presunto", "Alimentos", "kg", "38.00", "0", 3, 5),
    ("Ovos (dúzia)", "Alimentos", "dz", "12.00", "0", 10, 20),
    ("Salgadinho pacote", "Alimentos", "pct", "5.50", "12.00", 24, 36),
    ("Chocolate barra", "Alimentos", "un", "6.00", "14.00", 24, 30),
    ("Detergente 5L", "Limpeza", "l", "18.00", "0", 10, 20),
    ("Desinfetante 5 L", "Limpeza", "l", "16.00", "0", 10, 20),
    ("Água sanitária 5 L", "Limpeza", "l", "12.00", "0", 10, 15),
    ("Sabão em pó", "Limpeza", "kg", "9.80", "0", 15, 30),
    ("Amaciante 2 L", "Limpeza", "l", "11.00", "0", 8, 16),
    ("Papel higiênico (fardo)", "Limpeza", "cx", "48.00", "0", 6, 12),
    ("Saco de lixo 100 L", "Limpeza", "pct", "22.00", "0", 8, 14),
    ("Luva de limpeza", "Limpeza", "pct", "8.00", "0", 6, 10),
    ("Sabonete de cortesia", "Amenidades", "un", "1.80", "0", 100, 240),
    ("Xampu 30 ml", "Amenidades", "un", "2.40", "0", 100, 200),
    ("Condicionador 30 ml", "Amenidades", "un", "2.40", "0", 100, 180),
    ("Touca de banho", "Amenidades", "un", "0.90", "0", 50, 100),
    ("Kit dental", "Amenidades", "un", "2.10", "0", 50, 80),
    ("Protetor solar cortesia", "Amenidades", "un", "7.00", "16.00", 20, 24),
    ("Lâmpada LED 9 W", "Manutenção", "un", "11.00", "0", 12, 24),
    ("Pilha AA (par)", "Manutenção", "un", "9.00", "0", 10, 20),
    ("Fita isolante", "Manutenção", "un", "6.50", "0", 5, 10),
    ("Veda-rosca", "Manutenção", "un", "4.00", "0", 5, 8),
]
# Produtos que a demonstração deixa de propósito no vermelho e no zero.
# Nomes repetidos de propósito com os do `popular_demo` (os cinco primeiros
# produtos da casa): assim os dois comandos convivem sem catálogo duplicado.
NO_MINIMO = {"Cerveja long neck", "Café em grãos", "Sabonete de cortesia", "Pilha AA (par)"}
ZERADOS = {"Protetor solar cortesia", "Veda-rosca"}

FORNECEDORES = ["Distribuidora do Vale", "Mercado Central Ltda", "Casa das Bebidas"]


class Command(BaseCommand):
    help = "Cria dados de demonstração para o Estoque (produtos, depósitos e kardex)."

    def handle(self, *args, **opts):
        operador = (
            Usuario.objects.filter(is_superuser=True).first() or Usuario.objects.first()
        )
        if not operador:
            self.stderr.write("Crie um superusuário antes.")
            return
        sorteio = Random(2026)   # mesma demonstração toda vez

        locais = {}
        for nome, modulo in LOCAIS:
            locais[nome], _ = LocalEstoque.objects.get_or_create(
                nome=nome, defaults={"modulo": modulo}
            )
        almox = locais["Almoxarifado central"]
        destino_por_categoria = {
            "Bebidas": locais["Depósito da Loja"],
            "Alimentos": locais["Cozinha/Restaurante"],
            "Limpeza": locais["Rouparia"],
            "Amenidades": locais["Rouparia"],
        }
        fornecedores = self._fornecedores()

        criados = movimentados = 0
        for nome, categoria, unidade, custo, preco, minimo, compra in PRODUTOS:
            cat, _ = CategoriaProduto.objects.get_or_create(nome=categoria)
            produto, novo = Produto.objects.get_or_create(
                nome=nome,
                defaults={
                    "categoria": cat, "unidade": unidade,
                    "preco_venda": Decimal(preco), "estoque_minimo": Decimal(minimo),
                },
            )
            criados += int(novo)
            if MovimentoEstoque.objects.filter(produto=produto).exists():
                continue   # já tem história: não inventa outra por cima

            registrar_entrada(
                produto, almox, Decimal(compra), Decimal(custo), operador,
                documento=f"NF {sorteio.randint(1000, 9999)}",
                fornecedor=sorteio.choice(fornecedores) if fornecedores else None,
            )
            destino = destino_por_categoria.get(categoria)
            if destino:
                transferir(
                    produto, almox, destino,
                    self._passo(produto, Decimal(compra) / 4), operador,
                    observacao="Abastecimento inicial",
                )
            self._gastar(produto, almox, destino, nome, operador, sorteio)
            movimentados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Estoque populado: {criados} produto(s) novo(s), "
            f"{movimentados} com kardex, {len(locais)} depósitos."
        ))

    # ---------- bastidores ----------

    def _fornecedores(self):
        """Fornecedores da demonstração (Pessoa + papel), se o cadastro permitir."""
        from apps.nucleo.models import Fornecedor, Pessoa

        pessoas = []
        for nome in FORNECEDORES:
            pessoa, _ = Pessoa.objects.get_or_create(nome=nome)
            Fornecedor.objects.get_or_create(pessoa=pessoa)
            pessoas.append(pessoa)
        return pessoas

    def _passo(self, produto, valor):
        """Meia unidade de sabonete não existe; meio quilo de café, sim."""
        casas = Decimal("1") if produto.unidade in ("un", "cx", "pct", "dz") else Decimal("0.001")
        return valor.quantize(casas, rounding=ROUND_DOWN)

    def _gastar(self, produto, almox, destino, nome, operador, sorteio):
        """Consome o produto até o ponto que a demonstração quer mostrar."""
        local = destino or almox
        if nome in ZERADOS:
            disponivel = saldo(produto, local)
            if disponivel > 0:
                registrar_saida(
                    produto, local, disponivel, operador,
                    tipo=MovimentoEstoque.Tipo.SAIDA_VENDA,
                    observacao="Acabou — repor na próxima compra",
                )
            sobra = saldo(produto, almox)
            if local is not almox and sobra > 0:
                registrar_saida(
                    produto, almox, sobra, operador,
                    tipo=MovimentoEstoque.Tipo.CONSUMO_INTERNO,
                    observacao="Último estoque usado na operação",
                )
            return

        alvo = (
            (produto.estoque_minimo * Decimal("0.6")).quantize(Decimal("0.001"))
            if nome in NO_MINIMO else None
        )
        for _ in range(sorteio.randint(2, 5)):
            disponivel = saldo(produto, local)
            if disponivel <= 1:
                break
            if alvo is not None and saldo(produto) <= alvo:
                break
            quantidade = self._passo(
                produto, disponivel / Decimal(sorteio.randint(3, 8))
            )
            if quantidade <= 0:
                break
            registrar_saida(
                produto, local, quantidade, operador,
                tipo=sorteio.choice([
                    MovimentoEstoque.Tipo.SAIDA_VENDA,
                    MovimentoEstoque.Tipo.CONSUMO_INTERNO,
                    MovimentoEstoque.Tipo.PERDA,
                ]),
            )
        # Quem tem de ficar no vermelho desce também o que sobrou no almoxarifado.
        while alvo is not None and saldo(produto) > alvo:
            restante = saldo(produto, almox)
            if restante <= 0:
                break
            baixa = self._passo(produto, min(restante, saldo(produto) - alvo))
            if baixa <= 0:
                break
            registrar_saida(
                produto, almox, baixa, operador,
                tipo=MovimentoEstoque.Tipo.CONSUMO_INTERNO,
                observacao="Consumo da operação",
            )
