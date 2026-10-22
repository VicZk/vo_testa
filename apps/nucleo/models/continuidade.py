from django.db import models


class EstadoBackup(models.Model):
    """Última execução e último sucesso; nunca contém credenciais nem dados do dump."""
    ultima_tentativa = models.DateTimeField(null=True, blank=True)
    ultimo_sucesso = models.DateTimeField(null=True, blank=True)
    situacao = models.CharField(max_length=15, default="pendente")
    destinos = models.JSONField(default=list)
    arquivo = models.CharField(max_length=100, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    tamanho = models.PositiveBigIntegerField(default=0)
    erro = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "situação do backup"


class EnsaioIntegracao(models.Model):
    canal = models.CharField(max_length=20, unique=True)
    configuracao_hash = models.CharField(max_length=64)
    evidencia = models.TextField(max_length=2000)
    realizado_em = models.DateTimeField()
    registrado_por = models.ForeignKey("nucleo.Usuario", on_delete=models.PROTECT)

    class Meta:
        verbose_name = "ensaio de integração"
