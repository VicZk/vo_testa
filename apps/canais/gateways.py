"""Contrato Channex: tarefas aceitas não comprovam atualização em cada OTA.

Credenciais só vêm das configurações do processo. Nenhuma resposta bruta, cartão
ou chave de API é gravada ou incluída nos erros apresentados à operação.
"""
import json
import uuid
from decimal import Decimal
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError


class ErroCanal(ValidationError):
    pass


class _SemRedirecionamento(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Channex:
    AMBIENTES = {
        "homologacao": "https://staging.channex.io/api/v1",
        "producao": "https://app.channex.io/api/v1",
    }

    def __init__(self, ambiente, propriedade, *, abrir=None):
        if ambiente not in self.AMBIENTES:
            raise ErroCanal("Selecione o ambiente de canais.")
        self.ambiente = ambiente
        self.url = self.AMBIENTES[ambiente]
        try:
            self.propriedade = str(uuid.UUID(str(propriedade)))
        except (ValueError, TypeError, AttributeError):
            raise ErroCanal("Confira o identificador do estabelecimento no provedor.") from None
        self.abrir = abrir or urlrequest.build_opener(_SemRedirecionamento()).open

    def _pedir(self, metodo, caminho, *, dados=None, parametros=None):
        token = getattr(settings, "CHANNEX_API_KEY_HML" if self.ambiente == "homologacao" else "CHANNEX_API_KEY", "")
        if not token:
            raise ErroCanal("Configure a credencial Channex no servidor antes de conectar.")
        url = self.url + caminho
        if parametros:
            url += "?" + urlencode(parametros)
        req = urlrequest.Request(url, method=metodo,
            headers={"user-api-key": token, "Accept": "application/json", "Content-Type": "application/json"},
            data=json.dumps(dados).encode("utf-8") if dados is not None else None)
        try:
            with self.abrir(req, timeout=25) as resposta:
                if resposta.status != 200:
                    raise ErroCanal(f"O provedor não confirmou a operação (HTTP {resposta.status}).")
                bruto = resposta.read(5_000_001)
        except urlerror.HTTPError as erro:
            if erro.code in (401, 403):
                raise ErroCanal("O provedor recusou o acesso. Confira a credencial e o estabelecimento.") from None
            if erro.code == 429:
                raise ErroCanal("O provedor limitou as requisições. Aguarde a próxima tentativa.") from None
            raise ErroCanal(f"O provedor não confirmou a operação (HTTP {erro.code}).") from None
        except (urlerror.URLError, TimeoutError, OSError):
            raise ErroCanal("Sem resposta do provedor. O envio permanece pendente para nova tentativa.") from None
        if len(bruto) > 5_000_000:
            raise ErroCanal("O provedor devolveu uma resposta acima do limite esperado.")
        try:
            resultado = json.loads(bruto, parse_float=Decimal)
        except (ValueError, TypeError, UnicodeError):
            raise ErroCanal("O provedor devolveu uma resposta inválida.") from None
        if not isinstance(resultado, dict) or resultado.get("errors"):
            raise ErroCanal("O provedor recusou os dados. Confira o mapeamento e a configuração.")
        return resultado

    def revisoes(self, pagina=1):
        resultado = self._pedir("GET", "/booking_revisions/feed", parametros={
            "filter[property_id]": self.propriedade, "order[inserted_at]": "asc",
            "pagination[page]": pagina, "pagination[limit]": 100})
        itens = resultado.get("data")
        if not isinstance(itens, list) or len(itens) > 100:
            raise ErroCanal("A lista de reservas recebida é inválida.")
        return itens

    def confirmar_recebimento(self, revisao_id):
        try:
            identificador = str(uuid.UUID(str(revisao_id)))
        except (ValueError, TypeError, AttributeError):
            raise ErroCanal("Identificador de revisão inválido.") from None
        resultado = self._pedir("POST", f"/booking_revisions/{identificador}/ack")
        meta = resultado.get("meta")
        if not isinstance(meta, dict) or meta.get("message") != "Success" or meta.get("warnings"):
            raise ErroCanal("O provedor ainda não confirmou o recebimento desta revisão.")

    def _enviar(self, caminho, valores):
        if not isinstance(valores, list) or not valores or len(valores) > 5000:
            raise ErroCanal("Confira o lote de disponibilidade e tarifas antes de enviar.")
        if any(not isinstance(v, dict) or v.get("property_id") != self.propriedade for v in valores):
            raise ErroCanal("O envio contém outro estabelecimento.")
        resultado = self._pedir("POST", caminho, dados={"values": valores})
        meta, tarefas = resultado.get("meta", {}), resultado.get("data")
        if (not isinstance(meta, dict) or meta.get("message") != "Success"
                or meta.get("warnings") or not isinstance(tarefas, list) or not tarefas):
            raise ErroCanal("O provedor não aceitou todo o lote. Confira as tarifas, restrições e mapeamentos.")
        if any(not isinstance(t, dict) or t.get("type") != "task" or not t.get("id") for t in tarefas):
            raise ErroCanal("O provedor não identificou as tarefas de atualização.")
        try:
            return [str(uuid.UUID(str(t["id"]))) for t in tarefas]
        except (TypeError, ValueError, AttributeError):
            raise ErroCanal("O provedor devolveu identificadores de tarefa inválidos.") from None

    def disponibilidade(self, valores):
        return self._enviar("/availability", valores)

    def tarifas(self, valores):
        return self._enviar("/restrictions", valores)
