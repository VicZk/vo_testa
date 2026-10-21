from django.contrib import admin

from .models import ConferenciaOcupacao, StatusLimpeza, TarefaGovernanca


@admin.register(StatusLimpeza)
class StatusLimpezaAdmin(admin.ModelAdmin):
    list_display = ["uh", "situacao", "atualizado_em", "atualizado_por"]
    list_filter = ["situacao"]


@admin.register(TarefaGovernanca)
class TarefaGovernancaAdmin(admin.ModelAdmin):
    list_display = ["uh", "tipo", "status", "camareira", "gerada_em", "concluida_em",
                    "inspecionada_em", "reprovada_em"]
    list_filter = ["status", "tipo"]


@admin.register(ConferenciaOcupacao)
class ConferenciaOcupacaoAdmin(admin.ModelAdmin):
    """Histórico da ronda — leitura. Corrigir é registrar de novo, não editar o que
    já foi visto (o retrato do PMS vale para o momento daquela conferência)."""

    list_display = ["uh", "dia", "visto", "pms_ocupado", "divergencia",
                    "registrado_em", "registrado_por"]
    list_filter = ["dia", "divergencia", "visto"]
    date_hierarchy = "dia"

    def has_change_permission(self, request, obj=None):
        return False
