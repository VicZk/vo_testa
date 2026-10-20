from django.conf import settings
from django.core.cache import cache

from apps.site.models import Reserva


def analytics(request):
    """Expõe o ID do GA4 aos templates do site (vazio = tag não carrega)."""
    return {"ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", "")}


def reserva_passos(request):
    """Passos do fluxo de reserva para o stepper (partial).

    'Pagamento' será reinserido quando a integração existir (Etapa B).
    """
    return {
        'reserva_passos': [
            (1, 'Datas'),
            (2, 'Quartos'),
            (3, 'Dados'),
            (4, 'Resumo'),
            (5, 'Confirmação'),
        ],
    }


_CHAVE_PROVA = 'site:prova-social'


def prova_social(request):
    """Reserva real mais recente para a notificação flutuante — SEM identificar ninguém.

    Antes aparecia "Fulano reservou · Quarto X · há 5 min" em TODA página: o nome
    de quem acabou de reservar ficava visível para qualquer visitante, sem
    necessidade nenhuma (LGPD, minimização de dados). Ficou só o tipo de quarto e
    o tempo — a prova social continua, o hóspede sai da vitrine.

    Cacheado 60 s: é um rodapé de todas as páginas, não precisa de uma consulta
    por visita.
    """
    dados = cache.get(_CHAVE_PROVA)
    if dados is None:
        ultima = (
            Reserva.objects
            .filter(status__in=['confirmada', 'checkin', 'finalizada'])
            .select_related('quarto', 'quarto__categoria')
            .order_by('-criado_em')
            .first()
        )
        dados = {}
        if ultima:
            categoria = getattr(ultima.quarto.categoria, 'nome', '') if ultima.quarto_id else ''
            dados = {
                'quarto': categoria or (ultima.quarto.nome if ultima.quarto_id else 'Hospedagem'),
                'quando': ultima.criado_em,
            }
        cache.set(_CHAVE_PROVA, dados, 60)
    return {'prova_social': dados or None}
