"""Lê toda a edição de preços antes de autorizar qualquer gravação."""
import re
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .validadores import decimal_valido


class LeituraPrecos:
    def __init__(self, dados):
        self.dados = dados
        self.erros = []

    def decimal(self, campo, rotulo, *, minimo=Decimal("0"), maximo=Decimal("99999999.99")):
        bruto = (self.dados.get(campo) or "").strip()
        if not bruto:
            return None
        # A máscara envia BRL. Também aceitamos decimal simples sem agrupamento.
        if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,2})?", bruto):
            numero = bruto.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"[0-9]+\.[0-9]{1,2}", bruto):
            numero = bruto
        else:
            self.erros.append(f"{rotulo}: informe um valor válido, com até duas casas decimais.")
            return None
        try:
            return decimal_valido(numero, nome=rotulo, minimo=minimo, maximo=maximo)
        except ValidationError as erro:
            self.erros.extend(erro.messages)
            return None

    def grupo(self, campos, rotulo):
        """Grupo ausente não muda nada; base vazia remove somente se extras vazios."""
        if not any(campo in self.dados for campo in campos.values()):
            return None
        base = next(iter(campos))
        if campos[base] not in self.dados:
            self.erros.append(f"{rotulo}: envie também o preço base para alterar esta tarifa.")
        valores = {
            destino: self.decimal(campo, f"{rotulo} · {destino.replace('_', ' ')}",
                                 minimo=Decimal("0.01") if destino == base else Decimal("0"))
            for destino, campo in campos.items() if campo in self.dados
        }
        if valores.get(base) is None and any(valor is not None for chave, valor in valores.items() if chave != base):
            self.erros.append(f"{rotulo}: preencha a base ou deixe todos os valores vazios para remover a tarifa.")
        return valores

    def horario(self, campo, rotulo):
        try:
            return forms.TimeField(input_formats=["%H:%M"]).clean(self.dados.get(campo))
        except ValidationError:
            self.erros.append(f"{rotulo}: informe um horário válido, como 14:00.")

    def escolha(self, campo, rotulo, opcoes):
        bruto = self.dados.get(campo, "")
        if bruto not in {str(opcao) for opcao in opcoes}:
            self.erros.append(f"{rotulo}: selecione uma opção da lista.")
            return None
        return int(bruto)

    def conferir(self):
        if self.erros:
            raise ValidationError(self.erros)


def valor_exibido(request, campo, inicial):
    """Em erro, o formulário sem JavaScript também conserva o texto informado."""
    return request.POST.get(campo, inicial) if request.method == "POST" else inicial
