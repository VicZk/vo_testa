from django.apps import AppConfig


class CanaisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.canais"
    verbose_name = "Canais e OTAs"

    def ready(self):
        from apps.nucleo.modulos import Modulo, antes_desativar_modulo
        from apps.reservas.signals import distribuicao_alterada

        from .services import enfileirar_alteracao, exigir_conexao_desligada
        distribuicao_alterada.connect(enfileirar_alteracao, weak=False, dispatch_uid="canais.enfileirar_distribuicao")
        antes_desativar_modulo(Modulo.CANAIS, exigir_conexao_desligada)
