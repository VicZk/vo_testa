from django.contrib import admin

from .models import Cobranca, EventoPagamento


class EventoInline(admin.TabularInline):
    model = EventoPagamento
    extra = 0
    readonly_fields = ("tipo", "origem", "detalhe", "criado_em")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cobranca)
class CobrancaAdmin(admin.ModelAdmin):
    list_display = ("id", "metodo", "valor", "finalidade", "status", "criado_em")
    list_filter = ("status", "metodo", "finalidade")
    search_fields = ("descricao", "gateway_id")
    raw_id_fields = ("pagador", "criado_por")
    inlines = [EventoInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EventoPagamento)
class EventoPagamentoAdmin(admin.ModelAdmin):
    list_display = ("cobranca", "tipo", "origem", "criado_em")
    list_filter = ("tipo",)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
