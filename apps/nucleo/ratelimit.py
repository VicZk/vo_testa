"""
Rate limiting leve por IP, via cache do Django (sem dependência nova).

Defesa em profundidade para endpoints públicos (webhook, link de pagamento, portal).
NOTA: em produção com múltiplos workers, use um cache COMPARTILHADO (Redis) — o
LocMemCache é por processo, então o limite fica por worker. Ainda assim reduz abuso
automatizado; a proteção primária de cada rota não depende disto.

Todo contador passa por `somar()`: no cache em banco (DatabaseCache, o padrão sem
REDIS_URL), o `incr()` regrava a chave com o prazo PADRÃO do cache (300 s), e não com o
da janela. Sem reafirmar o prazo, um limite por hora virava "5 minutos desde a última
tentativa" e um por minuto só zerava depois de 5 minutos de silêncio.
"""
import math
import time

from django.core.cache import cache


def client_ip(request) -> str:
    """IP do cliente. Atrás de proxy (Railway), o 1º item de X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "desconhecido")


def janela_atual(janela_seg: int) -> tuple[int, int]:
    """A janela fixa corrente: (início, segundos até ela acabar).

    O início entra na chave do contador, então a contagem zera na virada da janela
    qualquer que seja o cache — e o que falta é o prazo que `somar()` reafirma."""
    agora = time.time()
    inicio = int(agora // janela_seg) * janela_seg
    return inicio, max(1, math.ceil(inicio + janela_seg - agora))


def somar(chave: str, prazo_seg: int) -> int:
    """Soma 1 ao contador `chave` e devolve o total; a chave vive `prazo_seg` segundos.

    O prazo é reafirmado a cada soma (`touch`), porque o `incr()` do cache em banco o
    troca pelo padrão do cache. No Redis e na memória o prazo já ficava; o `touch` lá
    só repete o mesmo valor."""
    if cache.add(chave, 1, prazo_seg):
        return 1
    try:
        atual = cache.incr(chave)
    except ValueError:  # expirou entre o add e o incr
        cache.set(chave, 1, prazo_seg)
        return 1
    cache.touch(chave, prazo_seg)
    return atual


def _chave_conta(escopo: str, identificador: str, janela_seg: int) -> str:
    import hashlib

    resumo = hashlib.sha256((identificador or "").strip().lower().encode()).hexdigest()[:32]
    inicio, _ = janela_atual(janela_seg)
    return f"rl:{escopo}:conta:{resumo}:{inicio}"


def falhas_da_conta(escopo: str, identificador: str, janela_seg: int) -> int:
    """Quantas falhas a conta (ex.: o usuário digitado no login) acumula na janela —
    independe do IP, então trocar de IP não renova as tentativas."""
    return cache.get(_chave_conta(escopo, identificador, janela_seg), 0)


def registrar_falha_da_conta(escopo: str, identificador: str, janela_seg: int) -> int:
    _, resta = janela_atual(janela_seg)
    return somar(_chave_conta(escopo, identificador, janela_seg), resta)


def limpar_falhas_da_conta(escopo: str, identificador: str, janela_seg: int) -> None:
    cache.delete(_chave_conta(escopo, identificador, janela_seg))


def limite_excedido(request, escopo: str, limite: int, janela_seg: int, sufixo: str = "") -> bool:
    """True se o IP passou de `limite` requisições em `janela_seg` para `escopo`.
    `sufixo` permite bucket adicional (ex.: token da cobrança)."""
    inicio, resta = janela_atual(janela_seg)
    return somar(f"rl:{escopo}:{client_ip(request)}:{sufixo}:{inicio}", resta) > limite
