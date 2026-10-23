# Restaurante: do pedido ao fechamento

Referência operacional do código de 23/10/2026. A publicação e a versão em execução
devem ser conferidas no registro da entrega.

## Preparação

Cadastre produtos, embalagens de compra e preços de venda no Estoque. Pratos podem
usar ficha técnica e adicionais com consumo de insumos. O cardápio usa a
disponibilidade do local da comanda, incluindo receitas e lotes válidos. Um produto
sem preço de venda positivo não entra no cardápio.

Lista de compra, previsão de consumo e mercadoria recebida têm papéis diferentes.
Só registre entrada após conferir a mercadoria, a quantidade e a unidade. Custo de
compra não é preço de venda. O [manual de compras](ESTOQUE_COMPRAS.md) descreve notas,
recebimentos parciais, conversões e rastreabilidade.

## Atendimento

1. Abra a comanda indicando o ponto, cliente ou identificação do atendimento.
   O sistema escolhe automaticamente um local ativo do Restaurante; se não houver,
   usa um local ativo da Loja ou outro local ativo cadastrado. Se houver hospedagem,
   vincule a estadia para que o check-out reconheça a comanda ainda aberta.
2. Use busca, categoria e o filtro de disponibilidade para escolher o produto.
   Informe quantidade, opções e observações. **Adicionar à comanda já envia o item
   à fila da cozinha e baixa seu estoque.** Não existe uma segunda confirmação de
   rodada. A tela atualiza os saldos após incluir, editar ou remover.
3. Antes de iniciar o preparo, o pedido pode ser editado. Fechar uma janela com
   alterações não salvas pede confirmação. Reenviar a mesma inclusão não acrescenta
   quantidade novamente; incluir mais unidades é um novo pedido.
4. Na Cozinha, avance o item de **A preparar → Em preparo → Pronto → Entregue**.
   O pagamento não retira um item da cozinha antes de sua entrega. A verificação de
   versão impede que duas telas avancem uma etapa com informação desatualizada.
5. Confira os itens e o total. O desconto aparece no **Total a fechar** antes da
   confirmação. Imprima a conferência se necessário.
6. Escolha **Pagar agora** e a forma de pagamento, ou **Conta do quarto** e a conta
   aberta. O pagamento imediato usa o caixa do Restaurante. O lançamento no quarto
   compõe a conta da hospedagem e não simula dinheiro recebido no setor.

O Day Pass mantém seus ingressos e consumos identificados. A comanda do Restaurante
não deve ser confundida com o recebimento do ingresso.

## Correções e conferência

| Situação | Ação e efeito |
|---|---|
| Item ainda aguardando preparo | Remover devolve o estoque pela origem registrada. |
| Item cujo preparo já começou | Cancelar exige gerência e motivo; o consumo é registrado como perda. |
| Comanda aberta cancelada | Exige acesso ao Restaurante e gerência; a regra de devolução/perda respeita o estado de cada item. |
| Desconto maior que o subtotal | O fechamento é recusado e os campos permanecem preenchidos. |
| Desconto de 100% | A comanda fecha como **Sem valor a receber**, com consumo e auditoria, sem movimento de caixa de valor zero. |
| Pagamento estornado no caixa | Comanda, histórico e cupom mostram estorno parcial/total, valor devolvido e recebido líquido. O estorno financeiro não reabre o preparo nem devolve mercadoria automaticamente. |

Nos relatórios, vendas e descontos seguem a data de fechamento da comanda.
Recebimentos e estornos seguem a data de cada movimento. Assim, devolver hoje um
pagamento de ontem afeta o caixa de hoje, mantendo a venda no período original.
O cupom de 80 mm é conferência/recibo; a emissão fiscal mantém seu fluxo próprio.

## Comparação com Odoo e limites atuais

A referência foi o repositório público Odoo 20.0 no commit
[`4b274b9486ff84ba9b326fd4413ff597d308e6a2`](https://github.com/odoo/odoo/tree/4b274b9486ff84ba9b326fd4413ff597d308e6a2/addons/pos_restaurant).
A comparação ajudou a revisar reenvios, pagamentos e preparo; não significa
equivalência de funcionalidades.

| Recurso | Situação neste sistema |
|---|---|
| Reenvio seguro de pedido | Identidade persistida e validação do conteúdo; pedido repetido não repete consumo. |
| Pagamento misto ou parcial | Ainda há uma forma de pagamento por fechamento. O Odoo possui uma coleção de [pagamentos por pedido](https://github.com/odoo/odoo/blob/4b274b9486ff84ba9b326fd4413ff597d308e6a2/addons/point_of_sale/models/pos_order.py). |
| Divisão de conta por itens/quantidades | Ainda não implementada. O Odoo possui [fluxo específico de divisão](https://github.com/odoo/odoo/blob/4b274b9486ff84ba9b326fd4413ff597d308e6a2/addons/pos_restaurant/static/src/app/screens/split_bill_screen/split_bill_screen.js). |
| Reunir comandas | Transferir muda o ponto da comanda inteira; não mescla comandas. |
| Rodadas e estações de preparo | Inclusão envia imediatamente à fila única. Não há liberação separada por rodada ou roteamento entre bar e cozinha. |
| Devolução comercial por item após pagamento | O estorno financeiro está refletido na comanda; não existe tela para devolver quantidades de uma venda paga. |
| Operação sem conexão | O pedido depende do servidor; não há fila offline persistente. |

Pagamento misto e divisão de conta são as próximas extensões operacionais mais
relevantes. Planta de salão, sequência de pratos e múltiplas estações dependem do
modelo de atendimento da pousada.
