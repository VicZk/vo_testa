from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.fiscal.models import DocumentoFiscal
from apps.fiscal.services import consultar


class Command(BaseCommand):
    help = "Concilia até 20 emissões fiscais em processamento; não cria novas notas."

    def handle(self, *args, **options):
        falhas = 0
        documentos = DocumentoFiscal.objects.filter(gateway="focus", status="processando").order_by("criado_em")[:20]
        for doc in documentos:
            try:
                consultar(doc)
            except ValidationError:
                falhas += 1
        if falhas:
            raise CommandError(f"{falhas} documento(s) sem confirmação fiscal. Confira o painel Fiscal.")
        self.stdout.write("Conciliação fiscal concluída.")
