from django.apps import AppConfig


class NucleoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.nucleo"
    label = "nucleo"
    verbose_name = "Núcleo"

    def ready(self):
        # Auditoria automática: liga os signals de escrita dos models de negócio.
        from django.db.models.signals import post_delete, post_save

        from .audit import conectar_auditoria_automatica
        from .models import ModuloContratado
        from .models.usuarios import esquecer_modulos_ativos

        conectar_auditoria_automatica()
        # Ativar/desativar um módulo no meio da requisição invalida a memória dos ativos.
        post_save.connect(esquecer_modulos_ativos, sender=ModuloContratado,
                          dispatch_uid="nucleo.esquecer_modulos_ativos.save")
        post_delete.connect(esquecer_modulos_ativos, sender=ModuloContratado,
                            dispatch_uid="nucleo.esquecer_modulos_ativos.delete")
