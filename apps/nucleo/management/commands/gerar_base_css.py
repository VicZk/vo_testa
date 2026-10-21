"""Gera `static/css/base.css` — o CSS do portal do hóspede e da página de pagamento — a
partir do `app.css` e do manifesto `apps/nucleo/css_publico.txt`.

Rode sempre que mexer no `app.css` numa regra que essas telas usam (o teste
`CssDasTelasPublicasTests` avisa quando o base.css ficou para trás).

Uso: manage.py gerar_base_css [--conferir]
"""

from django.core.management.base import BaseCommand, CommandError

from apps.nucleo import css_publico


class Command(BaseCommand):
    help = "Gera static/css/base.css (CSS das telas públicas) a partir do app.css."

    def add_arguments(self, parser):
        parser.add_argument(
            "--conferir", action="store_true",
            help="Só confere: sai com erro se o base.css não estiver em dia (para o CI).")

    def handle(self, *args, **opts):
        novo = css_publico.gerar_do_app()
        destino = css_publico.caminho_base_css()
        atual = destino.read_text(encoding="utf-8").replace("\r\n", "\n") \
            if destino.exists() else ""
        if opts["conferir"]:
            if atual != novo:
                raise CommandError("base.css desatualizado: rode manage.py gerar_base_css.")
            self.stdout.write("base.css em dia.")
            return
        destino.write_text(novo, encoding="utf-8", newline="\n")
        app = len(css_publico.caminho_app_css().read_bytes())
        self.stdout.write(self.style.SUCCESS(
            f"base.css gerado: {len(novo.encode('utf-8')):,} bytes "
            f"(o app.css tem {app:,})".replace(",", ".")))
