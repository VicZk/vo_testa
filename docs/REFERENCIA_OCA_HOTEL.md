# Comparação com OCA/vertical-hotel

Leitura em 22/10/2026 da branch `19.0`, commit
[`ea83fba19b185d9245129b7ab20f5b1d7c04b124`](https://github.com/OCA/vertical-hotel/tree/ea83fba19b185d9245129b7ab20f5b1d7c04b124).
Comparação por código, modelos, testes e documentação; não foi instalada uma instância Odoo.
As capturas históricas do README não comprovam a aparência da versão atual.

O projeto é uma referência útil de processos. Seus módulos dependem do ORM, das
vendas, do estoque e da contabilidade do Odoo; não são componentes instaláveis no
nosso Django. Esta análise não incorpora código externo.

| Processo | Evidência no OCA | Situação no Vô Testa e encaminhamento |
|---|---|---|
| Conta da hospedagem | `hotel.folio`, linhas de quartos e serviços, pedidos do restaurante ligados ao folio | Já existe `ContaHospedagem`, inclusive conta de grupo, pagamentos, lavanderia e comandas. Preservar a vinculação explícita à estadia e os bloqueios de fechamento com pendências. |
| Reserva de mesas por horário | `hotel.restaurant.reservation` registra cliente, início/fim, mesas e confirmação com consulta de conflito | Lacuna: nossa `Mesa` identifica um ponto de atendimento; não tem agenda nem capacidade. Uma extensão útil deve distinguir reserva de mesa de comanda, impedir sobreposição inclusive concorrente e preservar o histórico de cancelamento/no-show. Prioridade posterior à estabilização operacional. |
| Atividades dentro da limpeza | `hotel.housekeeping.activities` possui atividade, responsável e horário de início/fim | Nossa tarefa registra limpeza, responsável, duração e inspeção, mas não uma lista configurável de etapas. Pode agregar checklist por tipo de UH, etapas obrigatórias e pendências da inspeção. Não exigir cliques redundantes no fluxo simples da camareira. |
| Consumo e cozinha | Pedidos, tickets da cozinha, atualização de itens e lançamento na conta | Já existem comanda, fila de cozinha, adicionais, observações e conta do hóspede. A lacuna prioritária é ficha técnica com ingredientes, unidades, perdas e lotes: o menu do OCA referencia produtos, sem resolver esse ciclo neste repositório. |
| Relatórios | Addons de relatórios agregam reservas e reservas de restaurante por estado | Os nossos relatórios já cobrem ocupação, receita por competência, caixa, carteira, pickup, ritmo, distribuição e governança. Agregar apenas indicadores ligados a novos processos; não substituir essa base por contagens mais simples. |
| Diárias e horas adicionais | Configuração de horas adicionais participa do cálculo da duração do folio | Nossa hospedagem usa noites e possui cobrança de serviços; não adotar a fórmula do OCA como política comercial. Uma eventual regra de entrada antecipada/saída tardia deve considerar ocupação física, limpeza, próxima chegada, valor aprovado e consentimento do hóspede. |
| Comunicação antes da chegada | Rotina agendada de lembrete de reserva com antecedência de 24 horas | Já há automações de CRM e jornadas. A referência reforça a necessidade de acompanhar entrega, falha e deduplicação, usando nossos adaptadores e preferências de contato. |

## Limites da referência

Os seis addons listados nesta revisão não fornecem um channel manager homologado,
integração fiscal brasileira, FNRH Digital nem operação de day pass com capacidade
de áreas comuns. Compras, lotes e conversões podem depender de outros módulos do
ecossistema Odoo; não devem ser atribuídos a este repositório sem análise própria.
Na fork, as correções OP27–OP29 foram implementadas após esta comparação:
Canais com fila e validação da configuração, Day Pass por turno e capacidade,
e compras por embalagem com lotes e fichas técnicas. Canais ainda depende de
credenciais/homologação; a capacidade de Day Pass e os cadastros físicos de
estoque devem ser definidos pela operação. Solicitação e aprovação de compras
usam o processo auxiliar do [manual de compras](ESTOQUE_COMPRAS.md).

O controle de conflitos observado na reserva de mesas faz uma consulta antes da
confirmação. Essa leitura isolada não comprova proteção contra duas confirmações
simultâneas. Qualquer implementação nossa precisa de transação, trava/constraint
e teste da disputa pelo mesmo horário.

## Fontes consultadas

- [Módulos disponíveis](https://github.com/OCA/vertical-hotel/tree/19.0).
- [Reserva de mesas, pedidos e cozinha](https://github.com/OCA/vertical-hotel/blob/ea83fba19b185d9245129b7ab20f5b1d7c04b124/hotel_restaurant/models/hotel_restaurant.py).
- [Atividades de governança](https://github.com/OCA/vertical-hotel/blob/ea83fba19b185d9245129b7ab20f5b1d7c04b124/hotel_housekeeping/models/hotel_housekeeping_activities.py).
- [Conta da hospedagem](https://github.com/OCA/vertical-hotel/blob/ea83fba19b185d9245129b7ab20f5b1d7c04b124/hotel/models/hotel_folio.py).
- [Relatório de reservas](https://github.com/OCA/vertical-hotel/blob/ea83fba19b185d9245129b7ab20f5b1d7c04b124/report_hotel_reservation/models/report_hotel_reservation.py).
- [Menu como cadastro de produto](https://github.com/OCA/vertical-hotel/blob/ea83fba19b185d9245129b7ab20f5b1d7c04b124/hotel_restaurant/models/hotel_menucard.py).

Licenças declaradas nos manifests: `hotel` declara LGPL-3; os demais cinco addons
declaram AGPL-3. A raiz do repositório tem licença AGPL-3.0. Essas declarações não
substituem a conferência por arquivo caso se proponha incorporar código no futuro.
