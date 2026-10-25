"""Estado de configuração e ensaios declarados; não dispara operações externas."""
import hashlib
import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .models import EnsaioIntegracao, EstadoBackup, registrar_auditoria
from .permissoes import requer_gerencia


def situacao_integracoes():
    definicoes = [
        ("pagamentos", "Pagamentos", "PAGAMENTOS_GATEWAY", {"safrapay": (
            ("SAFRAPAY_TOKEN", "Credencial do estabelecimento"), ("SAFRAPAY_GATEWAY_URL", "Ambiente do provedor"))},
            ("SAFRAPAY_ENV", "SAFRAPAY_ID"), "Ensaie cobrança, confirmação pelo banco e estorno; confira os valores na conciliação."),
        ("whatsapp", "WhatsApp", "WHATSAPP_GATEWAY", {"cloud": (
            ("WHATSAPP_CLOUD_TOKEN", "Credencial Meta"), ("WHATSAPP_CLOUD_PHONE_ID", "Número empresarial"),
            ("WHATSAPP_APP_SECRET", "Autenticação dos retornos"), ("WHATSAPP_VERIFY_TOKEN", "Validação do canal de retorno"))},
            ("WHATSAPP_API_VERSION",), "Ensaie envio, recebimento e status com um contato autorizado e template aprovado."),
        ("email", "E-mail comercial", "EMAIL_GATEWAY", {
            "smtp": (("EMAIL_HOST", "Servidor SMTP"), ("EMAIL_HOST_USER", "Remetente autenticado"), ("EMAIL_HOST_PASSWORD", "Senha de aplicativo")),
            "ses": (("EMAIL_SES_REGION", "Região SES"), ("EMAIL_SES_ACCESS_KEY_ID", "Credencial SES"), ("EMAIL_SES_SECRET_ACCESS_KEY", "Segredo SES"))},
            ("DEFAULT_FROM_EMAIL", "EMAIL_COMERCIAL_FROM", "EMAIL_COMERCIAL_HOST_USER", "EMAIL_COMERCIAL_HOST_PASSWORD", "EMAIL_PORT", "EMAIL_USE_TLS", "EMAIL_USE_SSL"),
            "Ensaie envio para uma caixa autorizada e confira recebimento e resposta. Aceitação pelo servidor não comprova entrega."),
        ("fnrh", "FNRH Digital", "FNRH_GATEWAY", {"serpro": (
            ("FNRH_API_URL", "Ambiente SERPRO"), ("FNRH_API_USER", "Usuário SERPRO"),
            ("FNRH_API_SENHA", "Credencial SERPRO"), ("FNRH_CPF_SOLICITANTE", "Solicitante autorizado"))},
            (), "Ensaie identificação, reserva, entrada, saída e cancelamento; confira os registros no sistema oficial."),
        ("fiscal", "Emissão fiscal", "FISCAL_GATEWAY", {"focus": (
            ("FISCAL_FOCUS_TOKEN", "Credencial Focus NFe"), ("FISCAL_FOCUS_URL", "Ambiente fiscal"),
            ("FISCAL_EMITENTE_CNPJ", "CNPJ emitente"), ("FISCAL_MUNICIPIO_IBGE", "Município do emitente"),
            ("FISCAL_DPS_SERIE", "Série exclusiva da DPS"), ("FISCAL_WEBHOOK_TOKEN", "Autenticação dos retornos")),
            "spedy": (("SPEDY_API_KEY", "Credencial Spedy"), ("SPEDY_WEBHOOK_SECRET", "Assinatura dos retornos"))},
            ("FISCAL_REGIME", "FISCAL_NFSE_COMPLEMENTOS", "FISCAL_NFCE_HABILITADA", "FISCAL_DPS_NUMERO_INICIAL", "FISCAL_NFSE_CODIGO_SERVICO",
             "FISCAL_NFSE_LC116", "FISCAL_NFSE_ISS_ALIQUOTA", "SPEDY_SANDBOX"),
            "Ensaie autorização, documento e cancelamento com o responsável fiscal, no ambiente indicado."),
    ]
    ensaios = {e.canal:e for e in EnsaioIntegracao.objects.select_related("registrado_por")}
    itens=[]
    for codigo, titulo, chave, modos, adicionais, orientacao in definicoes:
        modo = getattr(settings,chave,"")
        campos = modos.get(modo,())
        if codigo == "email" and modo == "smtp" and settings.EMAIL_COMERCIAL_HOST_USER:
            campos = (("EMAIL_HOST", "Servidor SMTP"), ("EMAIL_COMERCIAL_HOST_USER", "Remetente autenticado"),
                ("EMAIL_COMERCIAL_HOST_PASSWORD", "Senha de aplicativo"))
        pendencias = [rotulo for nome,rotulo in campos if not getattr(settings,nome,"")]
        if modo != "simulado" and modo not in modos:
            pendencias.append("Provedor selecionado não está disponível")
        valores = {k:str(getattr(settings,k,"")) for k in (chave,)+adicionais+tuple(c[0] for c in campos)}
        assinatura = hashlib.sha256(json.dumps(valores,sort_keys=True).encode()).hexdigest()
        ensaio = ensaios.get(codigo)
        valido = ensaio and ensaio.configuracao_hash == assinatura
        ambiente = ""
        if codigo == "pagamentos" and modo == "safrapay":
            from apps.pagamentos.gateways import GatewaySafrapay
            ambiente = {"hml":"Homologação", "prod":"Produção"}.get(settings.SAFRAPAY_ENV, "Ambiente inválido")
            try:
                GatewaySafrapay()._exigir_token()
            except ValidationError:
                pendencias.append("Confira credencial e endereço oficial do ambiente selecionado")
            if not settings.SAFRAPAY_ID:
                pendencias.append("Identificação do estabelecimento para o antifraude")
        if codigo == "fiscal" and modo in ("focus", "spedy"):
            from apps.fiscal.services import configuracao
            if modo == "focus":
                ambiente = "Homologação" if "homologacao" in settings.FISCAL_FOCUS_URL else "Produção"
            else:
                ambiente = "Homologação (sandbox)" if settings.SPEDY_SANDBOX else "Produção"
            if configuracao()["pendencias"]:
                pendencias.append("Revise a configuração no painel Fiscal")
        pronto = modo in modos and not pendencias
        itens.append({"codigo":codigo,"titulo":titulo,"modo":modo,"ambiente":ambiente,
            "pendencias":pendencias,"pronto":pronto,"assinatura":assinatura,"orientacao":orientacao,
            "ensaio":ensaio if valido else None,"ensaio_desatualizado":bool(ensaio and not valido),
            "situacao":"Simulação" if modo == "simulado" else ("Configuração pendente" if not pronto else ("Ensaio registrado" if valido else "Aguardando ensaio"))})
    from apps.canais.services import resumo_integracao
    itens.append(resumo_integracao())
    return itens


@never_cache
@requer_gerencia
def painel(request):
    itens=situacao_integracoes()
    if request.method == "POST":
        try:
            item=next((i for i in itens if i["codigo"] == request.POST.get("canal")),None)
            evidencia=request.POST.get("evidencia","").strip()
            if not item or not item.get("pronto") or item.get("url_name"):
                raise ValidationError("Complete a configuração real antes de registrar um ensaio.")
            if not 20 <= len(evidencia) <= 2000 or request.POST.get("confirmado") != "sim":
                raise ValidationError("Descreva o resultado em 20 a 2000 caracteres e confirme a conferência no provedor.")
            ensaio,_=EnsaioIntegracao.objects.update_or_create(canal=item["codigo"],defaults={
                "configuracao_hash":item["assinatura"],"evidencia":evidencia,
                "realizado_em":timezone.now(),"registrado_por":request.user})
            registrar_auditoria(request.user,"ensaio_integracao",ensaio,{"canal":item["codigo"],"ambiente":item["ambiente"]})
            messages.success(request,"Ensaio registrado com a configuração atual.")
            return redirect("integracoes")
        except ValidationError as erro:
            messages.error(request," ".join(erro.messages))
    backup=EstadoBackup.objects.filter(pk=1).first()
    recente=bool(backup and backup.ultimo_sucesso and backup.ultimo_sucesso > timezone.now()-timedelta(hours=30))
    from .management.commands.backup_banco import _r2_configurado
    from .models import modulo_ativo
    from .modulos import Modulo
    grupos_monitorados = ["frequentes", "diarias"]
    if modulo_ativo(Modulo.CANAIS):
        grupos_monitorados.append("canais")
    return render(request,"nucleo/integracoes.html",{"integracoes":itens,"backup":backup,
        "backup_recente":recente,"backup_local":bool(os.environ.get("BACKUP_DIR")),"backup_externo":_r2_configurado(),
        "monitores":all(settings.ROTINAS_MONITOR.get(grupo) for grupo in grupos_monitorados),"kit_configurado":bool(settings.KIT_CONTINGENCIA_EMAILS),
        "pix_manual":settings.PIX_DIRETO,"pix_configurado":bool(settings.PIX_CHAVE),
        "smtp_configurado":bool(settings.EMAIL_HOST),"instalacao":request.build_absolute_uri("/")})
