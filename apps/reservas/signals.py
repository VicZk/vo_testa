"""
Sinais do módulo Reservas — pontos de integração para outros módulos ouvirem
sem inverter dependência (Reservas não conhece Governança/Lavanderia/Comercial).

quarto_liberado: enviado quando um quarto deixa de ser ocupado (check-out ou
troca). A Governança escuta para gerar a faxina e marcar o quarto como sujo.
kwargs: uh, reserva, usuario, origem ("checkout" | "troca").

reserva_encerrada: cancelamento ou no-show. Comercial anota follow-up.
kwargs: reserva, evento ("cancelada" | "no_show"), motivo, usuario.
"""

from django.dispatch import Signal

quarto_liberado = Signal()
reserva_encerrada = Signal()

# Interface pública: estoque físico, preço ou restrição de venda mudou. O receptor
# enfileira trabalho na mesma transação; não faz chamadas de rede.
distribuicao_alterada = Signal()
