from django.core.exceptions import ValidationError


class CancelamentoPendente(ValidationError):
    """O provedor aceitou o pedido de cancelamento; a confirmação chega depois, pelo
    retorno ou pela consulta. O documento continua autorizado até lá."""
