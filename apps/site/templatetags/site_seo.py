"""Dados estruturados do site público (schema.org) para a busca do Google."""

import json

from django import template
from django.templatetags.static import static as arquivo_estatico
from django.utils.safestring import mark_safe

register = template.Library()

# Município/UF da pousada — fixos (não é dado que o painel edita; o endereço
# completo, sim, vem da Configuração do Site).
CIDADE, UF, CEP, PAIS = "Itá", "SC", "89760-000", "BR"
QUARTOS = 24  # os 24 quartos físicos de hospedagem (o day use fica fora da conta)


@register.simple_tag(takes_context=True)
def jsonld_pousada(context):
    """Ficha da pousada em JSON-LD (`LodgingBusiness`): nome, endereço em Itá/SC,
    telefone/WhatsApp, 24 quartos e faixa de preço. É o que o Google usa para a
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
        "telephone": cfg.telefone,
        "email": cfg.email,
        "numberOfRooms": QUARTOS,
        "priceRange": "R$$",
        "currenciesAccepted": "BRL",
        "petsAllowed": True,
    }
    redes = [f"https://wa.me/{cfg.whatsapp}"] if cfg.whatsapp else []
    redes += [u for u in (cfg.instagram_url, cfg.facebook_url, cfg.tiktok_url) if u]
    if redes:
        dados["sameAs"] = redes
    if base:
        dados["url"] = base + "/"
        dados["image"] = base + arquivo_estatico("site/img/og-pousada.jpg")

    # `</` escapado: nem um endereço com HTML colado no painel fecha o <script>.
    corpo = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    return mark_safe(f'<script type="application/ld+json">{corpo}</script>')
