"""Sitemap do site público (só páginas indexáveis). O domínio vem do request —
sem depender do framework Sites."""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class PaginasEstaticas(Sitemap):
    """As páginas fixas + uma página por quarto publicado na vitrine.

    Os 24 quartos têm página própria (nome temático, fotos, tour 360°) e é esse o
    conteúdo que ranqueia em busca como "pousada em Itá com vista para o lago" —
    estavam todos invisíveis para o Google, junto com a vitrine `/quartos/`.

    Tudo numa classe só de propósito: o `sitemaps={"paginas": …}` do
    `config/urls.py` registra uma entrada, e assim o sitemap fica completo sem
    depender de mudança lá.
    """

    changefreq = "weekly"
    ROTAS = ["core:home", "core:reservar", "core:quartos_todos"]

    def items(self):
        return list(self.ROTAS) + list(self._quartos())

    def _quartos(self):
        from apps.nucleo.models import TipoUH, UH
        from apps.site.models import VitrineQuarto

        return (
            VitrineQuarto.objects
            .filter(publicar=True, uh__status=UH.Status.ATIVA)
            .exclude(uh__tipo__modalidade=TipoUH.Modalidade.DAY_USE)
            .select_related("uh")
            .order_by("-destaque", "ordem", "uh__numero")
        )

    def location(self, item):
        if isinstance(item, str):
            return reverse(item)
        return reverse("core:quarto_detalhe", args=[item.uh_id])

    def priority(self, item):
        return 0.8 if isinstance(item, str) else 0.7
