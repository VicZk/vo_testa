from django.apps import AppConfig


class ManutencaoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manutencao"
    label = "manutencao"
    verbose_name = "Manutenção"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import OrdemServico
        from .signals import avisar_disponibilidade
        for sinal in (post_save, post_delete):
            sinal.connect(avisar_disponibilidade, sender=OrdemServico, weak=False,
                dispatch_uid=f"manutencao.disponibilidade.{id(sinal)}")
