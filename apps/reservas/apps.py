from django.apps import AppConfig


class ReservasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reservas"
    label = "reservas"
    verbose_name = "Reservas"

    def ready(self):
        # Estorno no caixa de um pagamento/adiantamento desfaz o crédito na conta junto.
        from apps.nucleo.models.financeiro import ao_estornar

        from .services import desfazer_credito_do_estorno

        ao_estornar(desfazer_credito_do_estorno)
        from .eventos_distribuicao import conectar
        conectar()
