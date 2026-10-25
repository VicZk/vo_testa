"""Pequenas regras de apresentação compartilhadas pelo núcleo e módulos."""


def plural(quantidade, singular, pluralizado=None):
    """Retorna a palavra; plurais irregulares são informados explicitamente."""
    return singular if quantidade == 1 else (pluralizado or singular + "s")
