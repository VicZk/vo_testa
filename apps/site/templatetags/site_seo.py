"""Dados estruturados do site público (schema.org) para a busca do Google."""

import json

from django import template
from django.templatetags.static import static as arquivo_estatico
from django.utils.safestring import mark_safe

register = template.Library()

# Mesmo escape do `json_script` do Django: `<`, `>` e `&` viram \uXXXX. O JSON continua
# válido (o Google lê igual) e nenhum texto do painel fecha o <script> nem abre `<!--`.
_ESCAPE_JSON_EM_SCRIPT = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}

# Município/UF da pousada — fixos (não é dado que o painel edita; o endereço
# completo, sim, vem da Configuração do Site).
CIDADE, UF, CEP, PAIS = "Itá", "SC", "89760-000", "BR"


@register.simple_tag(takes_context=True)
def jsonld_pousada(context):
    """Ficha da pousada em JSON-LD (`LodgingBusiness`): nome, endereço em Itá/SC,
    contatos e número de quartos conferidos. É o que o Google usa para a
    ficha de hospedagem e o mapa. Só é montado onde a tag é chamada (a home)."""
    from apps.site.models import ConfiguracaoSite

    cfg = ConfiguracaoSite.load()
    pedido = context.get("request")
    base = f"{pedido.scheme}://{pedido.get_host()}" if pedido is not None else ""

    dados = {
        "@context": "https://schema.org",
        "@type": "LodgingBusiness",
        "name": "Pousada Vô Testa",
        "description": (
            "Pousada à beira do Lago de Itá (SC): quartos e cabanas, Dia na Pousada "
            "com piscina e mirantes, pesca esportiva e eventos."
        ),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": cfg.endereco,
            "addressLocality": CIDADE,
            "addressRegion": UF,
            "postalCode": CEP,
            "addressCountry": PAIS,
        },
        "email": cfg.email,
        "priceRange": "R$$",
        "currenciesAccepted": "BRL",
        "petsAllowed": True,
    }
    if cfg.telefone_publico:
        dados["telephone"] = cfg.telefone_publico
    if cfg.numeros_publicos and cfg.numero_quartos.isdigit():
        dados["numberOfRooms"] = int(cfg.numero_quartos)
    redes = [f"https://wa.me/{cfg.whatsapp_publico}"] if cfg.whatsapp_publico else []
    redes += [u for u in (cfg.instagram_url, cfg.facebook_url, cfg.tiktok_url) if u]
    if redes:
        dados["sameAs"] = redes
    if base:
        dados["url"] = base + "/"
        dados["image"] = base + arquivo_estatico("site/img/og-pousada.jpg")

    corpo = json.dumps(dados, ensure_ascii=False).translate(_ESCAPE_JSON_EM_SCRIPT)
    # `corpo` é JSON com <, > e & escapados (acima): não há HTML nele.
    return mark_safe(f'<script type="application/ld+json">{corpo}</script>')  # nosec B308, B703
