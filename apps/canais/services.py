"""Conexão de canais, caixa de entrada durável e publicação com conferência.

O recebimento (ACK) confirma a captura no PMS. Pendências ficam visíveis e
bloqueiam novas ofertas; tarefas aceitas não são chamadas de sincronização OTA.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.nucleo.models import UH, TipoUH, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo
from apps.nucleo.sistema import travar_quartos, usuario_de_sistema
from apps.reservas import services as reservas

from .gateways import Channex
from .models import (
    ConfiguracaoCanais,
    EnvioCanal,
    MapeamentoCanal,
    QuartoReservaCanal,
    ReservaCanal,
    RevisaoCanal,
    UnidadeMapeada,
)
from .normalizacao import normalizar

logger = logging.getLogger(__name__)
TRAVA = 846521907
PENDENTES = (RevisaoCanal.Estado.RECEBIDA, RevisaoCanal.Estado.PENDENTE)


def enfileirar_alteracao(sender=None, **kwargs):
    """Geração durável evita perder mudanças ocorridas durante uma chamada externa."""
    if modulo_ativo(Modulo.CANAIS):
        ConfiguracaoCanais.objects.filter(ativo=True).update(versao_pendente=F("versao_pendente")+1)


@transaction.atomic
def exigir_conexao_desligada():
    _travar_edicao()
    if ConfiguracaoCanais.objects.filter(ativo=True).exists():
        raise ValidationError("Feche as vendas, confira o fechamento nos canais e desligue a conexão antes de desativar o módulo.")


def _hash(dados):
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _chave(configuracao):
    return getattr(settings, "CHANNEX_API_KEY_HML" if configuracao.ambiente == "homologacao" else "CHANNEX_API_KEY", "")


def segredo_webhook(ambiente):
    return getattr(settings, "CHANNEX_WEBHOOK_SECRET_HML" if ambiente == "homologacao" else "CHANNEX_WEBHOOK_SECRET", "")


def _travar_edicao():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [TRAVA])
        if not cursor.fetchone()[0]:
            raise ValidationError("A conexão está sendo atualizada. Aguarde a conclusão e tente novamente.")


@contextmanager
def _execucao_exclusiva():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [TRAVA])
        obtida = cursor.fetchone()[0]
    try:
        yield obtida
    finally:
        if obtida:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [TRAVA])


def mapeamentos(configuracao):
    return list(configuracao.mapeamentos.prefetch_related("unidades__uh").order_by("pk"))


def situacao(configuracao):
    mapas = mapeamentos(configuracao)
    assinatura = _hash({"ambiente": configuracao.ambiente, "propriedade": configuracao.propriedade,
        "chave": _hash(_chave(configuracao)), "webhook": _hash(segredo_webhook(configuracao.ambiente)), "responsavel": configuracao.responsavel_id,
        "dias": configuracao.dias_publicados,
        "mapeamentos": [{"id": m.pk, "tipo": m.tipo_externo, "tarifa": m.tarifa_externa,
            "limite": m.limite_venda, "margem": m.margem_seguranca, "ocupacao": m.ocupacao_tarifa,
            "ativo": m.ativo, "unidades": sorted(u.uh_id for u in m.unidades.all())} for m in mapas]})
    pendencias = []
    if not configuracao.propriedade:
        pendencias.append("Identifique o estabelecimento no provedor.")
    if not _chave(configuracao):
        pendencias.append("Configure a credencial do ambiente no servidor.")
    if not segredo_webhook(configuracao.ambiente):
        pendencias.append("Configure a assinatura das notificações do provedor no servidor.")
    if not configuracao.responsavel_id or not configuracao.responsavel.is_active:
        pendencias.append("Defina um responsável ativo pela conferência dos canais.")
    if not any(m.ativo and m.unidades.all() for m in mapas):
        pendencias.append("Mapeie ao menos uma categoria com unidades físicas.")
    validada = bool(configuracao.validada_em and configuracao.validacao_hash == assinatura)
    return {"assinatura": assinatura, "pendencias": pendencias, "configurada": not pendencias,
        "validada": validada, "chave_presente": bool(_chave(configuracao)),
        "validacao_desatualizada": bool(configuracao.validada_em and not validada)}


def resumo_integracao():
    """Interface pública para o painel de operação; não cria conexão nem faz HTTP."""
    habilitado = modulo_ativo(Modulo.CANAIS)
    cfg = ConfiguracaoCanais.objects.filter(ativo=True).first() or ConfiguracaoCanais.objects.order_by("-pk").first()
    estado = situacao(cfg) if cfg else {"pendencias": ["Cadastre uma conexão e mapeie as categorias."], "validada": False}
    return {"codigo": "canais", "titulo": "Canais de venda", "modo": "Channex",
        "ambiente": cfg.get_ambiente_display() if cfg else "",
        "situacao": "Módulo desativado" if not habilitado else ("Conexão desabilitada" if not cfg or not cfg.ativo else
            ("Validação registrada" if estado["validada"] and not estado["pendencias"] else "Configuração pendente")),
        "pendencias": estado["pendencias"], "url_name": "canais:painel" if habilitado else "modulos_central",
        "orientacao": "Mapeie as unidades, confira preço e disponibilidade e valide o recebimento de novas reservas, alterações e cancelamentos. Aceitação do envio não comprova atualização nas OTAs."}


def _ultimo_envio_fechado(configuracao):
    ultimo = configuracao.envios.first()
    return not ultimo or (ultimo.estado == EnvioCanal.Estado.ACEITO
        and not any(v["availability"] for v in ultimo.dados.get("disponibilidade", [])) and ultimo.conferido_em)


@transaction.atomic
def salvar_configuracao(configuracao, dados, usuario):
    _travar_edicao()
    anterior = ConfiguracaoCanais.objects.select_for_update().filter(pk=configuracao.pk).first() if configuracao.pk else None
    if anterior:
        tem_historico = anterior.reservas.exists() or anterior.envios.exists()
        if tem_historico and (dados["ambiente"] != anterior.ambiente or dados["propriedade"] != anterior.propriedade):
            raise ValidationError("Esta conexão já tem histórico. Crie outra conexão para um estabelecimento ou ambiente diferente.")
        if anterior.ativo and not dados["ativo"] and not _ultimo_envio_fechado(anterior):
            raise ValidationError("Feche as vendas, aguarde o envio e registre a conferência no canal antes de desligar a conexão.")
        if (anterior.vendas_abertas or not _ultimo_envio_fechado(anterior)) and any(dados[campo] != getattr(anterior, campo) for campo in ("responsavel", "dias_publicados")):
            raise ValidationError("Feche as vendas e confira o fechamento no canal antes de alterar o responsável ou o período publicado.")
    for campo, valor in dados.items():
        setattr(configuracao, campo, valor)
    configuracao.full_clean()
    if configuracao.ativo:
        if not configuracao.propriedade or not configuracao.responsavel_id or not _chave(configuracao):
            raise ValidationError("Defina estabelecimento, responsável e credencial antes de habilitar a conexão.")
        if ConfiguracaoCanais.objects.filter(ativo=True).exclude(pk=configuracao.pk).exists():
            raise ValidationError("Encerre a conexão atual antes de habilitar outra.")
    if configuracao.vendas_abertas:
        estado = situacao(configuracao) if configuracao.pk else {}
        if not configuracao.pk or not configuracao.ativo or not estado.get("validada") or not estado.get("configurada"):
            raise ValidationError("Habilite a conexão e registre a validação da configuração antes de abrir vendas.")
    configuracao.save(update_fields=list(dados) if configuracao.pk else None)
    ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(sincronizacao_solicitada=True)
    registrar_auditoria(usuario, "configuracao_canais", configuracao,
        {"ativo": configuracao.ativo, "ambiente": configuracao.ambiente, "vendas_abertas": configuracao.vendas_abertas})
    return configuracao


@transaction.atomic
def salvar_mapeamento(configuracao, mapa, dados, unidades, usuario):
    _travar_edicao()
    configuracao = ConfiguracaoCanais.objects.select_for_update().get(pk=configuracao.pk)
    if configuracao.vendas_abertas or not _ultimo_envio_fechado(configuracao):
        raise ValidationError("Feche as vendas e confira o fechamento nos canais antes de alterar o mapeamento.")
    anterior = MapeamentoCanal.objects.select_for_update().filter(pk=mapa.pk).first() if mapa.pk else None
    if anterior and anterior.configuracao_id != configuracao.pk:
        raise ValidationError("Esta categoria pertence a outra conexão.")
    if anterior and configuracao.envios.exists() and any(dados[c] != getattr(anterior, c) for c in ("tipo_externo", "tarifa_externa")):
        raise ValidationError("Identificadores publicados ficam no histórico. Desative esta categoria e cadastre a nova.")
    ids = sorted({u.pk for u in unidades})
    fisicas = list(UH.objects.filter(pk__in=ids, status=UH.Status.ATIVA, tipo__modalidade=TipoUH.Modalidade.HOSPEDAGEM))
    travar_quartos(*fisicas)
    if not ids or len(fisicas) != len(ids):
        raise ValidationError("Selecione unidades ativas de hospedagem.")
    if UnidadeMapeada.objects.filter(configuracao=configuracao, uh_id__in=ids).exclude(mapeamento=mapa if mapa.pk else None).exists():
        raise ValidationError("Uma unidade já pertence a outra categoria desta conexão.")
    if dados["limite_venda"] > len(ids) or dados["margem_seguranca"] > len(ids):
        raise ValidationError("Limite e margem não podem superar a quantidade de unidades selecionadas.")
    for campo, valor in dados.items():
        setattr(mapa, campo, valor)
    mapa.configuracao = configuracao
    mapa.full_clean()
    mapa.save()
    mapa.unidades.exclude(uh_id__in=ids).delete()
    for pk in ids:
        UnidadeMapeada.objects.get_or_create(configuracao=configuracao, uh_id=pk, defaults={"mapeamento": mapa})
    registrar_auditoria(usuario, "mapeamento_canal", mapa,
        {"unidades": ids, "limite_venda": mapa.limite_venda, "margem_seguranca": mapa.margem_seguranca})
    ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(sincronizacao_solicitada=True)
    return mapa


@transaction.atomic
def registrar_validacao(configuracao, evidencia, usuario):
    _travar_edicao()
    configuracao = ConfiguracaoCanais.objects.select_for_update().get(pk=configuracao.pk)
    estado = situacao(configuracao)
    if estado["pendencias"]:
        raise ValidationError(estado["pendencias"])
    if not isinstance(evidencia, str) or not 20 <= len(evidencia.strip()) <= 2000:
        raise ValidationError("Descreva a conferência com o provedor em 20 a 2000 caracteres.")
    configuracao.validacao_hash = estado["assinatura"]
    configuracao.validacao = evidencia.strip()
    configuracao.validada_em = timezone.now()
    configuracao.validada_por = usuario
    configuracao.save(update_fields=["validacao_hash", "validacao", "validada_em", "validada_por"])
    registrar_auditoria(usuario, "validacao_canal", configuracao, {"ambiente": configuracao.ambiente})
    ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(sincronizacao_solicitada=True)


@transaction.atomic
def receber_revisao(configuracao, item):
    dados = normalizar(item, configuracao.propriedade)
    externa, _ = ReservaCanal.objects.get_or_create(ambiente=configuracao.ambiente,
        propriedade=configuracao.propriedade, identificador=dados["reserva_id"], defaults={"configuracao": configuracao})
    externa = ReservaCanal.objects.select_for_update().get(pk=externa.pk)
    revisao, criada = RevisaoCanal.objects.get_or_create(identificador=dados["revisao_id"], defaults={
        "reserva": externa, "alterada_em": parse_datetime(dados["alterada_em"]), "tipo": dados["status"], "dados": dados})
    if revisao.reserva_id != externa.pk or revisao.dados != dados:
        raise ValidationError("O provedor repetiu uma identidade com dados diferentes. Confira a revisão no canal.")
    if criada:
        anterior = externa.ultima_revisao
        if anterior and anterior.alterada_em > revisao.alterada_em:
            revisao.estado = RevisaoCanal.Estado.ANTERIOR
            revisao.save(update_fields=["estado"])
        elif anterior and anterior.alterada_em == revisao.alterada_em:
            revisao.estado = RevisaoCanal.Estado.PENDENTE
            revisao.pendencia = "Duas revisões têm o mesmo horário. Confira qual versão é a atual no canal."
            revisao.save(update_fields=["estado", "pendencia"])
        else:
            externa.ultima_revisao = revisao
            externa.canal, externa.codigo = dados["canal"], dados["codigo"]
            externa.save(update_fields=["ultima_revisao", "canal", "codigo"])
            externa.revisoes.filter(estado__in=PENDENTES, alterada_em__lt=revisao.alterada_em).update(estado=RevisaoCanal.Estado.ANTERIOR)
    ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(ultimo_recebimento=timezone.now(), versao_pendente=F("versao_pendente")+int(criada))
    return revisao


def _permitir_aplicacao(configuracao):
    if configuracao.ambiente == "homologacao" and not settings.CANAIS_HOMOLOGACAO_APLICAR:
        raise ValidationError("Reservas de homologação ficam separadas da operação. A aplicação só é liberada numa instalação isolada de teste.")


def _destinos(configuracao, dados, *, manual=False):
    mapas = {str(m.tipo_externo): m for m in mapeamentos(configuracao) if m.ativo or dados["status"] == "cancelled"}
    destinos, por_quarto = {}, {}
    for indice, quarto in enumerate(dados["quartos"]):
        mapa = mapas.get(quarto["tipo_id"])
        if not mapa or str(mapa.tarifa_externa) != quarto["tarifa_id"]:
            raise ValidationError("Tipo ou tarifa recebida ainda não está mapeada nesta conexão.")
        chave = quarto["identificador"] or (f"manual-{indice}" if manual else "")
        if chave in destinos:
            raise ValidationError("A revisão repete a identificação de um quarto. Solicite a correção no canal.")
        destinos[chave] = [u.uh_id for u in mapa.unidades.all()]
        por_quarto[chave] = mapa
    return destinos, por_quarto


def _gravar_vinculos(externa, resultado, mapas):
    for chave, dados in resultado.items():
        existente = externa.quartos.filter(identificador=chave).first()
        mapa = mapas.get(chave) or (existente.mapeamento if existente else None)
        if mapa is None:
            raise ValidationError("Confira a categoria de cada quarto antes de concluir o vínculo.")
        QuartoReservaCanal.objects.update_or_create(externa=externa, identificador=chave,
            defaults={"reserva_id": dados["reserva_id"], "mapeamento": mapa, "estado_aplicado": dados["estado"]})


@transaction.atomic
def aplicar_revisao(revisao, usuario, *, manual=False):
    _travar_edicao()
    externa = ReservaCanal.objects.select_for_update().get(pk=revisao.reserva_id)
    revisao = RevisaoCanal.objects.select_for_update().get(pk=revisao.pk)
    if revisao.estado in (RevisaoCanal.Estado.APLICADA, RevisaoCanal.Estado.CONFERIDA, RevisaoCanal.Estado.ANTERIOR):
        return revisao
    configuracao = externa.configuracao
    _permitir_aplicacao(configuracao)
    if externa.ultima_revisao_id != revisao.pk:
        raise ValidationError("Há outra revisão mais recente ou com o mesmo horário. Confira a versão atual antes de aplicar.")
    if not manual and not configuracao.importar_automaticamente:
        raise ValidationError("Aguardando conferência da recepção; importação automática desativada.")
    if not manual and not situacao(configuracao)["validada"]:
        raise ValidationError("A configuração da conexão precisa de validação antes da importação automática.")
    destinos, mapas = _destinos(configuracao, revisao.dados) if revisao.tipo != "cancelled" else ({}, {})
    vinculos = {v.identificador: {"reserva_id": v.reserva_id, "estado": v.estado_aplicado} for v in externa.quartos.all()}
    resultado = reservas.aplicar_reserva_canal(revisao.dados, destinos, vinculos, usuario)
    _gravar_vinculos(externa, resultado, mapas)
    agora = timezone.now()
    revisao.estado, revisao.pendencia = RevisaoCanal.Estado.APLICADA, ""
    revisao.resolvida_em, revisao.resolvida_por = agora, usuario
    revisao.vinculos_aplicados = resultado
    revisao.save(update_fields=["estado", "pendencia", "resolvida_em", "resolvida_por", "vinculos_aplicados"])
    externa.revisao_aplicada_em = revisao.alterada_em
    externa.save(update_fields=["revisao_aplicada_em"])
    registrar_auditoria(usuario, "revisao_canal_aplicada", revisao, {"tipo": revisao.tipo})
    enfileirar_alteracao()
    return revisao


@transaction.atomic
def resolver_manualmente(revisao, ids, motivo, usuario):
    _travar_edicao()
    externa = ReservaCanal.objects.select_for_update().get(pk=revisao.reserva_id)
    revisao = RevisaoCanal.objects.select_for_update().get(pk=revisao.pk)
    _permitir_aplicacao(externa.configuracao)
    if revisao.estado not in PENDENTES:
        return revisao
    if externa.ultima_revisao_id != revisao.pk:
        raise ValidationError("Resolva a versão mais recente; revisões conflitantes precisam ser reenviadas pelo provedor.")
    if not isinstance(motivo, str) or not 20 <= len(motivo.strip()) <= 1000:
        raise ValidationError("Descreva em 20 a 1000 caracteres o que foi conferido e ajustado.")
    dados = dict(revisao.dados)
    if revisao.tipo == "cancelled" and not dados["quartos"]:
        anterior = externa.revisoes.filter(estado__in=[RevisaoCanal.Estado.APLICADA, RevisaoCanal.Estado.CONFERIDA]).first()
        dados["quartos"] = anterior.dados["quartos"] if anterior else []
    destinos, mapas = _destinos(externa.configuracao, dados, manual=True) if dados["quartos"] else ({}, {})
    anteriores = list(externa.quartos.values_list("reserva_id", flat=True))
    resultado = reservas.conferir_reservas_canal(dados, ids, usuario, anteriores=anteriores, destinos=destinos)
    try:
        with transaction.atomic():
            externa.quartos.all().delete()
            _gravar_vinculos(externa, resultado, mapas)
    except IntegrityError:
        raise ValidationError("Uma reserva do PMS já está vinculada a outro quarto ou canal.") from None
    revisao.estado, revisao.pendencia = RevisaoCanal.Estado.CONFERIDA, ""
    revisao.resolucao, revisao.resolvida_em, revisao.resolvida_por = motivo.strip(), timezone.now(), usuario
    revisao.vinculos_aplicados = resultado
    revisao.save(update_fields=["estado", "pendencia", "resolucao", "resolvida_em", "resolvida_por", "vinculos_aplicados"])
    externa.revisao_aplicada_em = revisao.alterada_em
    externa.save(update_fields=["revisao_aplicada_em"])
    registrar_auditoria(usuario, "revisao_canal_conferida", revisao, {"reservas": ids})
    enfileirar_alteracao()
    return revisao


def previa_envio(configuracao, *, feed_ok=True):
    mapas = mapeamentos(configuracao)
    hoje = timezone.localdate()
    previa = reservas.previa_distribuicao_canais([{"id": m.pk, "nome": m.nome,
        "unidades": [u.uh_id for u in m.unidades.all()], "ocupacao": m.ocupacao_tarifa,
        "limite": m.limite_venda, "margem": m.margem_seguranca, "ativo": m.ativo} for m in mapas],
        hoje, hoje + timedelta(days=configuracao.dias_publicados))
    estado = situacao(configuracao)
    motivos = list(estado["pendencias"])
    if not configuracao.ativo:
        motivos.append("Conexão desabilitada.")
    if not configuracao.vendas_abertas:
        motivos.append("Vendas fechadas nesta conexão.")
    if not estado["validada"]:
        motivos.append("Validação da configuração pendente ou desatualizada.")
    if not feed_ok:
        motivos.append("O recebimento de reservas precisa ser conferido.")
    if RevisaoCanal.objects.filter(reserva__configuracao=configuracao, estado__in=PENDENTES).exists():
        motivos.append("Há reservas recebidas aguardando conferência.")
    lookup = {m.pk: m for m in mapas}
    disponibilidade, tarifas = [], []
    for linha in previa["linhas"]:
        mapa = lookup[linha["mapeamento"]]
        quantidade = 0 if motivos else linha["disponibilidade"]
        disponibilidade.append({"property_id": str(configuracao.propriedade), "room_type_id": str(mapa.tipo_externo),
            "date": linha["data"], "availability": quantidade})
        restricao = {"property_id": str(configuracao.propriedade), "rate_plan_id": str(mapa.tarifa_externa),
            "date": linha["data"], "min_stay_through": linha["min_noites"], "min_stay_arrival": 1,
            "closed_to_arrival": linha["fechado_chegada"], "closed_to_departure": linha["fechado_saida"],
            "stop_sell": quantidade == 0}
        if linha["tarifa"]:
            restricao["rate"] = linha["tarifa"]
        tarifas.append(restricao)
        linha["publicar"] = quantidade
    return {"disponibilidade": disponibilidade, "tarifas": tarifas,
        "linhas": previa["linhas"], "motivos": motivos, "pendencias": previa["pendencias"]}


def _lotes(valores):
    for inicio in range(0, len(valores), 5000):
        yield valores[inicio:inicio+5000]


def publicar(configuracao, gateway, *, feed_ok=True, forcar=False):
    configuracao.refresh_from_db()
    if not configuracao.ativo or not configuracao.propriedade or not _chave(configuracao):
        raise ValidationError("Habilite e configure a conexão antes de publicar.")
    previa = previa_envio(configuracao, feed_ok=feed_ok)
    versao = configuracao.versao_pendente
    dados = {chave: previa[chave] for chave in ("disponibilidade", "tarifas", "motivos", "pendencias")}
    assinatura = _hash(dados)
    if not dados["disponibilidade"]:
        raise ValidationError("Nenhuma categoria mapeada para atualizar.")
    ultimo = configuracao.envios.first()
    if (not forcar and ultimo and ultimo.estado == EnvioCanal.Estado.ACEITO and ultimo.assinatura == assinatura
            and ultimo.aceito_em and ultimo.aceito_em > timezone.now()-timedelta(hours=24)):
        ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(versao_enviada=versao)
        return None
    envio = EnvioCanal.objects.create(configuracao=configuracao, ambiente=configuracao.ambiente,
        propriedade=configuracao.propriedade, assinatura=assinatura, dados=dados)
    tarefas = []
    try:
        # A ordem FIFO do provedor mantém o fechamento à frente da troca de preços.
        for lote in _lotes([{**v, "availability": 0} for v in dados["disponibilidade"]]):
            tarefas += gateway.disponibilidade(lote)
        for lote in _lotes(dados["tarifas"]):
            tarefas += gateway.tarifas(lote)
        if any(v["availability"] for v in dados["disponibilidade"]):
            for lote in _lotes(dados["disponibilidade"]):
                tarefas += gateway.disponibilidade(lote)
    except Exception as erro:
        mensagem = " ".join(erro.messages)[:500] if isinstance(erro, ValidationError) else "O envio foi interrompido. Confira o provedor antes de reabrir vendas."
        envio.estado, envio.erro = EnvioCanal.Estado.FALHOU, mensagem
        envio.tarefas = tarefas
        envio.save(update_fields=["estado", "erro", "tarefas"])
        raise ValidationError(mensagem) from None
    envio.estado, envio.aceito_em, envio.tarefas = EnvioCanal.Estado.ACEITO, timezone.now(), tarefas
    envio.save(update_fields=["estado", "aceito_em", "tarefas"])
    ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(assinatura_aceita=assinatura, ultimo_envio=envio.aceito_em, versao_enviada=versao)
    return envio


@transaction.atomic
def conferir_envio(envio, evidencia, usuario):
    envio = EnvioCanal.objects.select_for_update().get(pk=envio.pk)
    if envio.estado != EnvioCanal.Estado.ACEITO:
        raise ValidationError("O provedor ainda não aceitou o envio completo.")
    if not isinstance(evidencia, str) or not 20 <= len(evidencia.strip()) <= 1000:
        raise ValidationError("Descreva a conferência nos canais em 20 a 1000 caracteres.")
    envio.conferencia, envio.conferido_em, envio.conferido_por = evidencia.strip(), timezone.now(), usuario
    envio.save(update_fields=["conferencia", "conferido_em", "conferido_por"])
    registrar_auditoria(usuario, "envio_canal_conferido", envio, {"ambiente": envio.ambiente})


@transaction.atomic
def solicitar_sincronizacao(configuracao, usuario):
    _travar_edicao()
    configuracao = ConfiguracaoCanais.objects.select_for_update().get(pk=configuracao.pk)
    if not configuracao.ativo:
        raise ValidationError("Habilite a conexão antes de solicitar uma atualização.")
    configuracao.sincronizacao_solicitada = True
    configuracao.save(update_fields=["sincronizacao_solicitada"])
    registrar_auditoria(usuario, "sincronizacao_canal_solicitada", configuracao)


def sincronizar(*, forcar=False, gateway=None):
    if not modulo_ativo(Modulo.CANAIS) or not modulo_ativo(Modulo.RESERVAS):
        return {"estado": "desativado", "recebidas": 0}
    with _execucao_exclusiva() as obtida:
        if not obtida:
            return {"estado": "em_andamento", "recebidas": 0}
        configuracao = ConfiguracaoCanais.objects.filter(ativo=True).first()
        if not configuracao:
            return {"estado": "desativado", "recebidas": 0}
        if configuracao.proxima_tentativa and configuracao.proxima_tentativa > timezone.now():
            return {"estado": "aguardando", "recebidas": 0}
        forcar = forcar or configuracao.sincronizacao_solicitada
        ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(ultima_execucao=timezone.now(), sincronizacao_solicitada=False)
        configuracao.envios.filter(estado=EnvioCanal.Estado.PENDENTE).update(
            estado=EnvioCanal.Estado.FALHOU, erro="Execução anterior interrompida; estado externo precisa de conferência.")
        recebidas, falhas = 0, []
        pode_publicar = False
        try:
            if not configuracao.propriedade or not _chave(configuracao):
                raise ValidationError("Configure estabelecimento e credencial do ambiente antes de conectar.")
            gateway = gateway or Channex(configuracao.ambiente, configuracao.propriedade)
            pode_publicar = True
            reservas.expirar_vencidas()
            # No máximo 500 revisões por rodada. Repetir a primeira página: ACK a retira do feed.
            for _ in range(5):
                try:
                    itens = gateway.revisoes()
                except ValidationError as erro:
                    falhas.append(" ".join(erro.messages)[:500])
                    break
                if not itens:
                    break
                lote_ok = True
                for item in itens:
                    try:
                        revisao = receber_revisao(configuracao, item)
                        recebidas += 1
                        # receber_revisao encerrou sua transação antes da chamada externa.
                        gateway.confirmar_recebimento(revisao.identificador)
                        RevisaoCanal.objects.filter(pk=revisao.pk).update(recebimento_confirmado_em=timezone.now())
                    except ValidationError as erro:
                        falhas.append(" ".join(erro.messages)[:500])
                        lote_ok = False
                if not lote_ok:
                    break
            else:
                falhas.append("O feed ainda pode ter revisões. A próxima rodada continuará antes de reabrir as vendas.")
            usuario = usuario_de_sistema("_canais", "Integração de canais")
            for revisao in RevisaoCanal.objects.filter(reserva__configuracao=configuracao, estado__in=PENDENTES).select_related("reserva").order_by("alterada_em", "pk")[:500]:
                if configuracao.ambiente == "homologacao" and not settings.CANAIS_HOMOLOGACAO_APLICAR:
                    RevisaoCanal.objects.filter(pk=revisao.pk).update(estado=RevisaoCanal.Estado.ENSAIO,
                        pendencia="Registro de teste separado das reservas operacionais.")
                    continue
                try:
                    aplicar_revisao(revisao, usuario)
                except ValidationError as erro:
                    RevisaoCanal.objects.filter(pk=revisao.pk, estado__in=PENDENTES).update(
                        estado=RevisaoCanal.Estado.PENDENTE, pendencia=" ".join(erro.messages)[:500])
        except ValidationError as erro:
            falhas.append(" ".join(erro.messages)[:500])
        except Exception as erro:
            # Nunca serializar corpo do provedor ou dados do titular em logs de rotina.
            logger.error("Conexão de canais interrompida: configuracao=%s tipo=%s", configuracao.pk, type(erro).__name__)
            falhas.append("A atualização foi interrompida. Confira a conexão antes de abrir novas vendas.")
        if pode_publicar:
            try:
                configuracao.refresh_from_db()
                agora = timezone.now()
                estado = situacao(configuracao)
                ultimo = configuracao.envios.first()
                precisa = (forcar or falhas or configuracao.versao_pendente != configuracao.versao_enviada
                    or not ultimo or ultimo.estado != EnvioCanal.Estado.ACEITO
                    or not estado["validada"] or not estado["configurada"]
                    or not configuracao.ultimo_envio or configuracao.ultimo_envio <= agora-timedelta(hours=24)
                    or timezone.localdate(configuracao.ultimo_envio) != timezone.localdate())
                if precisa:
                    publicar(configuracao, gateway, feed_ok=not falhas, forcar=forcar)
            except ValidationError as erro:
                falhas.append(" ".join(erro.messages)[:500])
            except Exception as erro:
                logger.error("Publicação de canais interrompida: configuracao=%s tipo=%s", configuracao.pk, type(erro).__name__)
                falhas.append("Não foi possível concluir a publicação. Confira a disponibilidade nos canais.")
        resumo = " ".join(dict.fromkeys(falhas))[:500]
        tentativas = min(configuracao.falhas_consecutivas+1, 20) if falhas else 0
        proxima = timezone.now()+timedelta(minutes=min(2**max(0, tentativas-1), 30)) if falhas else None
        ConfiguracaoCanais.objects.filter(pk=configuracao.pk).update(ultima_falha=resumo,
            falhas_consecutivas=tentativas, proxima_tentativa=proxima)
        return {"estado": "falha" if falhas else "concluido", "recebidas": recebidas, "erro": resumo}
