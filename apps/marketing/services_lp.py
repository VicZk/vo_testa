"""Aprovação de LPs: versões, comentários, aprovação e publicação.

O HTML vem do design, autocontido (fotos e fontes embutidas), como as LPs que já
estão no ar. Quem revisa abre a prévia pelo link (`AprovacaoLP.token`), comenta,
pede ajuste ou aprova; a publicação passa pelo Comercial (`publicar_lp_aprovada`).
"""
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.nucleo.sistema import travar

from .models import AprovacaoLP, ComentarioLP, VersaoLP, _token_previa

LIMITE_HTML = 15 * 1024 * 1024  # a maior LP de hoje (Inauguração) tem 2,1 MB
LIMITE_TEXTO = 2000
_PARECE_HTML = re.compile(rb"<(?:!doctype\s+html|html|head|body)\b", re.IGNORECASE)


def ler_html(arquivo):
    """Texto do arquivo enviado, ou ValidationError com o que fazer."""
    nome = (getattr(arquivo, "name", "") or "").rsplit("/", 1)[-1][:200]
    if not nome.lower().endswith((".html", ".htm")):
        raise ValidationError("Envie o arquivo .html da LP.")
    if arquivo.size > LIMITE_HTML:
        raise ValidationError("O arquivo passa de 15 MB. Comprima as imagens e envie de novo.")
    bruto = arquivo.read()
    if not _PARECE_HTML.search(bruto[:20000]):
        raise ValidationError("O arquivo não parece uma página HTML.")
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("Salve o arquivo em UTF-8 e envie de novo.") from None
    return nome, texto, len(bruto)


def _nova_versao(aprovacao, *, arquivo, usuario, nota):
    nome, html, tamanho = ler_html(arquivo)
    numero = (aprovacao.versoes.aggregate(m=Max("numero"))["m"] or 0) + 1
    return VersaoLP.objects.create(
        aprovacao=aprovacao, numero=numero, html=html, nome_arquivo=nome,
        tamanho=tamanho, nota=nota.strip()[:300], enviada_por=usuario)


def criar(*, nome, arquivo, usuario, campanha=None, prazo=None, nota=""):
    with transaction.atomic():
        aprovacao = AprovacaoLP.objects.create(
            nome=nome.strip(), campanha=campanha, prazo=prazo, criado_por=usuario)
        _nova_versao(aprovacao, arquivo=arquivo, usuario=usuario, nota=nota)
    return aprovacao


def enviar_versao(aprovacao, *, arquivo, usuario, nota=""):
    """Versão nova volta para aprovação: o que foi aprovado era a anterior. A página
    publicada continua no ar com a versão antiga até a nova ser aprovada e publicada."""
    with transaction.atomic():
        travar(aprovacao)
        versao = _nova_versao(aprovacao, arquivo=arquivo, usuario=usuario, nota=nota)
        aprovacao.situacao = AprovacaoLP.Situacao.AGUARDANDO
        aprovacao.aprovada_versao, aprovacao.aprovada_por, aprovacao.aprovada_em = None, "", None
        aprovacao.save(update_fields=["situacao", "aprovada_versao", "aprovada_por",
                                      "aprovada_em", "atualizado_em"])
    return versao


def comentar(aprovacao, *, numero, tipo, texto, nome, usuario=None, pelo_link=False):
    """Comentário, pedido de ajuste ou aprovação de quem revisa a versão `numero`.

    Ajuste e aprovação valem para a versão mais nova: se chegou outra enquanto a
    pessoa olhava, ela precisa ver a nova antes de decidir."""
    texto = (texto or "").strip()
    nome = (nome or "").strip()[:80]
    if tipo not in ComentarioLP.Tipo.values:
        raise ValidationError("Escolha comentar, pedir ajuste ou aprovar.")
    if not nome:
        raise ValidationError("Diga seu nome para a equipe saber quem comentou.")
    if len(texto) > LIMITE_TEXTO:
        raise ValidationError(f"Escreva até {LIMITE_TEXTO} caracteres.")
    if tipo != ComentarioLP.Tipo.APROVACAO and not texto:
        raise ValidationError("Escreva o comentário ou o ajuste que precisa.")
    with transaction.atomic():
        travar(aprovacao)
        versao = aprovacao.versoes.filter(numero=numero).first()
        if versao is None:
            raise ValidationError("Essa versão não existe mais. Recarregue a página.")
        mais_nova = aprovacao.versoes.aggregate(m=Max("numero"))["m"]
        if tipo != ComentarioLP.Tipo.COMENTARIO and versao.numero != mais_nova:
            raise ValidationError(f"Chegou a versão {mais_nova}. Confira a nova antes de decidir.")
        if tipo == ComentarioLP.Tipo.APROVACAO and aprovacao.situacao in (
                AprovacaoLP.Situacao.APROVADA, AprovacaoLP.Situacao.PUBLICADA):
            raise ValidationError("Esta versão já está aprovada.")
        comentario = ComentarioLP.objects.create(
            aprovacao=aprovacao, versao=versao, tipo=tipo, texto=texto, nome_autor=nome,
            autor=usuario if usuario and usuario.is_authenticated else None,
            pelo_link=pelo_link)
        campos = ["atualizado_em"]
        if tipo == ComentarioLP.Tipo.AJUSTE:
            aprovacao.situacao = AprovacaoLP.Situacao.AJUSTES
            campos.append("situacao")
        elif tipo == ComentarioLP.Tipo.APROVACAO:
            aprovacao.situacao = AprovacaoLP.Situacao.APROVADA
            aprovacao.aprovada_versao, aprovacao.aprovada_por = versao.numero, nome
            aprovacao.aprovada_em = comentario.em
            campos += ["situacao", "aprovada_versao", "aprovada_por", "aprovada_em"]
        aprovacao.save(update_fields=campos)
    return comentario


def alternar_resolvido(comentario):
    with transaction.atomic():
        travar(comentario)
        comentario.resolvido = not comentario.resolvido
        comentario.save(update_fields=["resolvido"])
    return comentario


def novo_link(aprovacao):
    """Troca o link de prévia: o antigo deixa de abrir (enviado para a pessoa errada)."""
    with transaction.atomic():
        travar(aprovacao)
        aprovacao.token = _token_previa()
        aprovacao.save(update_fields=["token", "atualizado_em"])
    return aprovacao


def publicar(aprovacao, *, slug, usuario):
    """Põe no ar a versão aprovada, pelo Comercial."""
    from apps.comercial.services import publicar_lp_aprovada

    with transaction.atomic():
        travar(aprovacao)
        versao = aprovacao.ultima
        if aprovacao.situacao != AprovacaoLP.Situacao.APROVADA or (
                versao is None or aprovacao.aprovada_versao != versao.numero):
            raise ValidationError("Só a versão aprovada vai ao ar. Peça a aprovação primeiro.")
        pagina = publicar_lp_aprovada(usuario=usuario, nome=aprovacao.nome, slug=slug,
                                      html=versao.html, pagina_id=aprovacao.pagina_id)
        aprovacao.pagina_id, aprovacao.slug = pagina["id"], slug
        aprovacao.publicada_versao = versao.numero
        aprovacao.publicada_em = timezone.now()
        aprovacao.situacao = AprovacaoLP.Situacao.PUBLICADA
        aprovacao.save(update_fields=["pagina", "slug", "publicada_versao", "publicada_em",
                                      "situacao", "atualizado_em"])
    return pagina["url"]


def pendencias(aprovacao):
    """Pedidos de ajuste ainda não resolvidos."""
    return aprovacao.comentarios.filter(tipo=ComentarioLP.Tipo.AJUSTE, resolvido=False).count()
