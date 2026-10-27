"""
Auditoria — camada automática ("toda ação do atendente fica registrada").

Duas peças:
  1. `AuditContextMiddleware` guarda, por requisição, QUEM está agindo e de qual IP
     (num threadlocal), para que qualquer service — mesmo sem `request` em mãos —
     saiba a quem atribuir a ação.
  2. Signals `post_save`/`post_delete` nos models de negócio gravam automaticamente
     criar/editar/excluir com o diff dos campos. É o piso: nada de escrita escapa.

Regras:
  - Só registra quando há um usuário real no contexto (requisição autenticada). Seed,
    migrations, shell e cron sem usuário setado NÃO poluem a trilha.
  - Trilha é append-only (a própria TrilhaAuditoria nunca é auditada — evita loop).
  - Leituras (GET/listagens) não entram aqui; isto é trilha de ESCRITA.
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models import BinaryField
from django.db.models.signals import post_delete, post_save, pre_save

_contexto = threading.local()

# Campos que nunca entram no diff (ruído, automáticos ou sensíveis).
CAMPOS_IGNORADOS = {
    "criado_em", "atualizado_em", "modificado_em", "last_login", "password",
    # O HTML de uma LP (Marketing/Comercial) tem até megabytes e já fica guardado na
    # própria versão: a trilha registra a versão, não uma segunda cópia da página.
    "html",
}

# Credenciais nunca pertencem à trilha, nem para administradores. A mesma
# proteção atende snapshots, detalhes explícitos e registros anteriores.
CAMPOS_CREDENCIAIS = {
    "password", "senha", "secret", "segredo", "mfa_secret", "mfa_backup_codes",
    "backup_codes", "token", "access_token", "refresh_token", "api_key",
    "client_secret", "authorization",
}


def campo_credencial(nome):
    nome = str(nome).casefold().replace("-", "_")
    return nome in CAMPOS_CREDENCIAIS or nome.endswith(
        ("_secret", "_password", "_token", "_api_key")
    )


def redigir_credenciais(valor):
    """Cópia recursiva sem material de autenticação, inclusive em listas/JSON."""
    if isinstance(valor, dict):
        return {
            chave: "•••" if campo_credencial(chave) else redigir_credenciais(item)
            for chave, item in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [redigir_credenciais(item) for item in valor]
    return valor

# Campos sensíveis: a mudança É auditada (quem/quando), mas o VALOR só aparece na
# trilha para quem tem a área Remuneração — para os demais fica redigido ("•••").
CAMPOS_SENSIVEIS = {"salario"}

# Documento e nascimento (LGPD, minimização): a trilha registra QUE mudou, nunca o valor
# — o valor já mora no cadastro, e a trilha é lida e exportada por mais gente.
CAMPOS_PII = {"documento", "documento_numero", "chave_acesso", "cpf", "rg", "passaporte",
              "nascimento", "data_nascimento"}
_OCULTO = "•••"


def _mascara_pii(valores: dict) -> dict:
    """Troca o valor dos campos PII por "•••" (vazio continua vazio, para dar para ver
    que o campo foi preenchido ou apagado)."""
    return {campo: (_OCULTO if campo in CAMPOS_PII and valor not in (None, "") else valor)
            for campo, valor in valores.items()}


def redigir_sensiveis(detalhe, campos=CAMPOS_SENSIVEIS):
    """Devolve uma cópia do detalhe com os valores dos campos sensíveis mascarados.
    Cobre os dois formatos da trilha: {"valores": {...}} e {"alteracoes": {c:[a,b]}}.
    """
    if not isinstance(detalhe, dict):
        return detalhe
    masc = dict(detalhe)
    for chave in ("valores", "alteracoes"):
        bloco = masc.get(chave)
        if not isinstance(bloco, dict):
            continue
        novo = dict(bloco)
        for campo in list(novo):
            if campo in campos:
                novo[campo] = ["•••", "•••"] if chave == "alteracoes" else "•••"
        masc[chave] = novo
    return masc

# Denylist: por PADRÃO auditamos TODOS os models dos nossos apps (apps.*) —
# qualquer escrita de qualquer usuário, independente de permissão, vira registro.
# Aqui ficam só os que NÃO devem ser auditados (técnicos/loop/trilhas próprias).
MODELOS_EXCLUIDOS = {
    "nucleo.TrilhaAuditoria",       # a própria trilha — evita loop infinito
    "pagamentos.EventoPagamento",   # já é a trilha de webhooks do gateway
}


def _modelos_para_auditar():
    """Todos os models dos apps `apps.*`, menos os excluídos e tabelas M2M."""
    modelos = []
    for modelo in django_apps.get_models():
        if not modelo._meta.app_config.name.startswith("apps."):
            continue  # ignora Django/contrib
        if getattr(modelo._meta, "auto_created", False):
            continue  # tabelas intermediárias (M2M) automáticas
        rotulo = f"{modelo._meta.app_label}.{modelo.__name__}"
        if rotulo not in MODELOS_EXCLUIDOS:
            modelos.append((rotulo, modelo))
    return modelos


# ---------------------------------------------------------------- contexto (quem/IP)
def definir_contexto(usuario=None, ip=None):
    _contexto.usuario = usuario if (usuario and getattr(usuario, "is_authenticated", False)) else None
    _contexto.ip = ip


def limpar_contexto():
    _contexto.usuario = None
    _contexto.ip = None


def usuario_atual():
    return getattr(_contexto, "usuario", None)


def ip_atual():
    return getattr(_contexto, "ip", None)


def _ip_da_requisicao(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# Escritas sem login (site, portal do hóspede, link de pagamento, webhooks) também vão
# para a trilha, atribuídas a um usuário de sistema pelo caminho. Antes elas passavam
# sem registro nenhum (reserva do site, pedido no quarto, pagamento confirmado…).
_ATORES_PUBLICOS = (
    ("/hospede/", "_portal", "Portal"),
    ("/crm/pagamentos/", "_pagamentos", "Pagamentos (público)"),
    ("/whatsapp/", "_whatsapp", "WhatsApp"),
    ("/aprovacao/", "_aprovacao_lp", "Aprovação de LP (link)"),
)


def _ator(request):
    usuario = getattr(request, "user", None)
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        return usuario
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None  # leitura não escreve; nada a atribuir
    from apps.nucleo.sistema import usuario_de_sistema

    # `path_info`, não `path`: sob um prefixo (URL_PREFIX) o `path` começa por ele.
    for prefixo, username, nome in _ATORES_PUBLICOS:
        if request.path_info.startswith(prefixo):
            return usuario_de_sistema(username, nome)
    return usuario_de_sistema("_site", "Site")


class AuditContextMiddleware:
    """Publica o usuário/IP da requisição no threadlocal durante o processamento."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        definir_contexto(_ator(request), _ip_da_requisicao(request))
        try:
            return self.get_response(request)
        finally:
            limpar_contexto()


# ------------------------------------------------------------------- diff dos campos
def _serializa(valor):
    if valor is None or isinstance(valor, (int, float, bool, str)):
        return valor
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return str(valor)


def _snapshot(instance, campos=None) -> dict:
    """Valores dos campos concretos; com `campos` (update_fields), só esses."""
    dados = {}
    for campo in instance._meta.concrete_fields:
        # Documentos privados ficam no modelo de origem; a trilha guarda apenas
        # seus metadados e nunca uma segunda cópia do conteúdo do arquivo.
        if (campo.name in CAMPOS_IGNORADOS or campo_credencial(campo.name)
                or campo.primary_key or isinstance(campo, BinaryField)):
            continue
        if campos is not None and campo.name not in campos and campo.attname not in campos:
            continue
        dados[campo.attname] = _serializa(getattr(instance, campo.attname, None))
    return dados


def _pre_save(sender, instance, update_fields=None, **kwargs):
    """Guarda o estado anterior (do banco) para calcular o diff no post_save.

    Sem usuário no contexto o post_save não registra nada, então a leitura extra não
    acontece (site, portal, webhooks e rotinas pagavam um SELECT por gravação à toa).
    Com update_fields, lê e compara só os campos gravados: os demais não mudam no banco."""
    instance._audit_anterior = None
    instance._audit_campos = set(update_fields) if update_fields is not None else None
    if not instance.pk or usuario_atual() is None:
        return
    qs = sender._base_manager.filter(pk=instance.pk)
    if instance._audit_campos is not None:
        qs = qs.only(*instance._audit_campos)
    anterior = qs.first()
    instance._audit_anterior = _snapshot(anterior, instance._audit_campos) if anterior else None


def _post_save(sender, instance, created, **kwargs):
    usuario = usuario_atual()
    if usuario is None:
        return  # sem ator real → não registra (seed/migration/cron sem usuário)
    from apps.nucleo.models import registrar_auditoria

    if created:
        registrar_auditoria(usuario, "criar", instance,
                            {"valores": _mascara_pii(_snapshot(instance))})
        return
    anterior = getattr(instance, "_audit_anterior", None) or {}
    atual = _snapshot(instance, getattr(instance, "_audit_campos", None))
    # A comparação usa os valores reais; só o que é gravado na trilha sai mascarado.
    alteracoes = {
        campo: ([_OCULTO, _OCULTO] if campo in CAMPOS_PII
                else [anterior.get(campo), novo])
        for campo, novo in atual.items()
        if anterior.get(campo) != novo
    }
    if not alteracoes:
        return  # save sem mudança de campo → nada a registrar
    registrar_auditoria(usuario, "editar", instance, {"alteracoes": alteracoes})


def _post_delete(sender, instance, **kwargs):
    usuario = usuario_atual()
    if usuario is None:
        return
    from apps.nucleo.models import registrar_auditoria

    registrar_auditoria(usuario, "excluir", instance,
                        {"valores": _mascara_pii(_snapshot(instance))})


# ------------------------------------------------------------------ login/logout
def _logou(sender, request, user, **kwargs):
    from apps.nucleo.models import registrar_auditoria

    ip = _ip_da_requisicao(request) if request is not None else None
    registrar_auditoria(user, "login", user, {"username": user.get_username()}, ip=ip)


def _deslogou(sender, request, user, **kwargs):
    if user is None:  # sessão expirada sem usuário — nada a registrar
        return
    from apps.nucleo.models import registrar_auditoria

    ip = _ip_da_requisicao(request) if request is not None else None
    registrar_auditoria(user, "logout", user, {"username": user.get_username()}, ip=ip)


def conectar_auditoria_automatica():
    """Liga os signals para cada model auditado. Chamado no AppConfig.ready()."""
    from django.contrib.auth.signals import user_logged_in, user_logged_out

    for rotulo, modelo in _modelos_para_auditar():
        uid = f"audit_{rotulo}"
        pre_save.connect(_pre_save, sender=modelo, dispatch_uid=uid + "_pre")
        post_save.connect(_post_save, sender=modelo, dispatch_uid=uid + "_post")
        post_delete.connect(_post_delete, sender=modelo, dispatch_uid=uid + "_del")

    # Entrar/sair fecham a linha do tempo do operador ("Peterson entrou 14:03…").
    user_logged_in.connect(_logou, dispatch_uid="audit_login")
    user_logged_out.connect(_deslogou, dispatch_uid="audit_logout")
