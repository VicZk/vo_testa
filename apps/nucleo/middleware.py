"""Middlewares de desempenho do núcleo."""

from .models.usuarios import memoria_de_modulos


class ModulosPorRequisicaoMiddleware:
    """Os módulos ativos são lidos do banco uma vez por requisição.

    Menu, `@requer_modulo`, filtros de template (`|pode_modulo`, `|modulo_ativo`) e
    services perguntam `modulo_ativo()` de 7 a 22 vezes por página; dentro desta
    requisição a resposta vem da memória. Ativar/desativar um módulo limpa a memória."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with memoria_de_modulos():
            return self.get_response(request)
