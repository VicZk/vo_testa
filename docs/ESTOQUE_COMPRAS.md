# Compras, perecíveis e pratos

Fluxo operacional incorporado em 22/10/2026. O estoque físico continua vindo
do kardex do núcleo; embalagens, lotes e fichas técnicas usam esse mesmo motor.
O registro da entrega identifica o commit, os testes e o ambiente publicados.

## Antes de começar

1. Cadastre o fornecedor em **Pessoas** e confira o local que receberá a mercadoria.
2. Escolha a unidade base do produto: unidade, kg, g, litro etc. Ela permanece
   fixa depois de haver movimentos. Para comprar em outra apresentação, cadastre
   uma embalagem; não troque a unidade do saldo existente.
3. A gerência ativa **Controlar lotes e validade** para os perecíveis. Conclua
   qualquer inventário geral aberto desse produto antes de ativar.
4. Cadastre pratos como produtos com **Baixar ingredientes da ficha técnica**.
   Um produto que já tem histórico físico mantém seu tipo; crie outro cadastro
   para o prato. Os ingredientes continuam sendo produtos de estoque.

## Solicitação, cotação e aprovação

O recebimento está no sistema. Solicitação, comparação de cotações e aprovação
de compra usam **controle auxiliar no Livro de ocorrências**, antes do pedido
ao fornecedor. Não há pedido eletrônico de compra nem conciliação automática
da nota com uma ordem de compra.

Crie um tópico por solicitação, mantendo o número da própria ocorrência como
referência. Use este modelo:

```text
Solicitação de compra
Responsável:
Produto e unidade base:
Saldo conferido / mínimo / quantidade necessária:
Embalagem e quantidade a comprar:
Cotações: fornecedor, quantidade, valor total, frete, prazo e pagamento
Fornecedor escolhido e motivo:
Aprovação da gerência: responsável e data
Previsão de entrega:
```

A gerência registra a aprovação em uma resposta no mesmo tópico. A pessoa que
recebe acrescenta nota/documento, parcela recebida, divergências e referência
dos recebimentos. O Financeiro acrescenta a obrigação, vencimento e conferência
do pagamento. Resolva o tópico após conferir entrega e obrigação; preserve a
conversa como histórico. Esse controle é manual e depende de acesso ao Livro
de ocorrências e das responsabilidades definidas pela pousada.

## Receber na apresentação comprada

Em **Produto → Embalagens e ficha técnica**, cadastre a apresentação:

| Compra | Unidade do estoque | Quantidade base por embalagem |
|---|---|---:|
| Caixa com 12 garrafas | Unidade | 12 |
| Saco de 5 kg | Quilo | 5 |
| Pacote de 500 g | Quilo | 0,500 |
| Garrafa de 1 litro | Mililitro | 1000 |

Em **Compras → Receber por embalagem**, confira fornecedor, documento, local,
quantidade e custo por embalagem. A prévia mostra a conversão e o custo total.
Duas caixas de 12 unidades a R$ 60 por caixa entram como 24 unidades a R$ 5 por
unidade. O valor de aquisição é preservado antes do arredondamento do custo
unitário para quatro casas decimais.

O recebimento guarda a embalagem e o fator usados na época. Editar a embalagem
não recalcula entradas antigas; alterar o fator enquanto a tela está aberta
exige nova conferência. Reenviar o mesmo formulário não duplica o recebimento;
usar sua chave com outro conteúdo é recusado.

Receba somente a quantidade aceita. Em entrega parcial, registre cada parcela
e identifique-a na observação, mantendo a referência do documento. Antes de
abrir outro formulário, procure a nota no histórico para conferir se outra
pessoa já registrou aquela parcela. A chave protege o reenvio do mesmo
formulário; documentos podem aparecer em vários itens e parcelas.

**Receber mercadoria não paga a compra.** Registre ou confira a conta a pagar
no Financeiro e faça a baixa pelo procedimento financeiro já existente. O
recebimento não cria obrigação ou movimento de caixa automaticamente.

## Lotes, validade e correções

- Cadastre o lote e a validade copiados da embalagem. Um lote recebido vencido
  é recusado. O dia informado é o último dia considerado válido pelo sistema.
- Na saída, primeiro vence, primeiro sai. Lotes vencidos e quantidades ainda
  sem lote identificado ficam fora da disponibilidade da Loja e do Restaurante.
- Ao ativar o controle em um produto com saldo antigo, use **Identificar saldo
  existente**, após conferir fisicamente cada embalagem. Essa operação apenas
  identifica o saldo já registrado e não aumenta a quantidade física.
- Para corrigir identificação ou validade, cadastre o lote correto e use
  **Corrigir identificação**. A gerência informa quantidade, local e motivo;
  a correção conserva o saldo físico e mantém os dois registros no histórico.
- A transferência entre depósitos leva os mesmos lotes e vencimentos. Um lote
  vencido continua bloqueado para venda no destino.
- Lotes e registros anteriores não são reescritos. Correções são registradas
  com autor, data e motivo.

A conferência de integridade da embalagem, condição de armazenamento,
temperatura e prazo após abertura continua no procedimento operacional da
cozinha. O sistema controla a data registrada; ele não mede essas condições.
Quando a identificação interna muda após fracionamento ou abertura, a equipe
deve conferir a etiqueta correta e registrar a reidentificação correspondente.

## Perdas e inventário

Abra o lote e use **Registrar perda** para quebra, descarte ou vencimento,
informando o motivo. A saída por perda aceita lote vencido e retira exatamente
a quantidade indicada daquele lote. O saldo físico não pode ficar negativo.

Produtos comuns ficam no inventário geral. Perecíveis são contados em
**Lotes e validade → Conferir lote → Contar**; pratos usam a contagem dos
ingredientes. A contagem por lote precisa ser atual: se houver movimento
depois da abertura da tela, atualize e conte novamente. Saldo antigo ainda
sem lote deve ser identificado antes de aumentar a contagem de um lote.

Uma diferença real de contagem gera ajuste. Uma etiqueta errada deve usar a
correção de identificação, que não altera a quantidade física. Esses dois
procedimentos têm efeitos diferentes e ficam separados na auditoria.

## Vender pratos

Na ficha técnica, informe o consumo de cada ingrediente para **uma unidade
vendida**, usando a unidade base exibida ao lado do ingrediente. Exemplo:
um café com leite consome 0,200 litro de leite. A ficha deve refletir o consumo
efetivo previsto, inclusive a perda normal do preparo.

Pratos sem ficha não são vendidos. Ingredientes inativos, fichas dentro de
outras fichas, ciclos, repetição de ingredientes e quantidades incompatíveis
com a precisão de três casas são recusados. A disponibilidade considera o
ingrediente limitante e seus lotes válidos.

A venda no PDV e a inclusão na comanda baixam os ingredientes. Cada item guarda
os movimentos usados naquela operação. Alterar a ficha depois não muda a
devolução de um pedido anterior. Antes do preparo, o cancelamento devolve os
mesmos ingredientes e lotes; depois do preparo, o Restaurante exige gerência
e motivo e registra perda, sem recolocar o alimento preparado à venda.

## Conferência de abertura da operação

O catálogo da Loja, do Restaurante e a lista de produtos exibem um ícone pelo
nome e pela categoria. Em **Estoque → Produtos → Editar → Ícone no catálogo**,
deixe **Automático** ou escolha outra ilustração. A prévia acompanha a edição;
nome, preço e saldo continuam identificando o produto. As ilustrações são
genéricas; os SVGs e suas licenças estão em `static/vendor/lucide/`.

- Gerência: definir responsáveis por aprovação, recebimento, conferência de
  validade, perdas e Financeiro; adotar o tópico de compra no Livro de ocorrências.
- Estoquista: conferir unidades, embalagens, fornecedores e saldo de cada local.
- Cozinha: conferir fichas técnicas e etiquetas; identificar o saldo antigo.
- Operação: ensaiar uma compra, transferência, venda de prato, cancelamento e
  perda com dados de treinamento; conferir kardex, lotes e caixa ao fim.

Testes automatizados cobrem limites numéricos, repetição, rollback, disputa
pelo último saldo, alteração concorrente da ficha, permissões, preservação dos
formulários e uso no navegador. Ensaios de código não validam a ficha culinária,
o estoque físico ou os parâmetros fiscais reais de cada produto.

Referências de produto consultadas antes da implementação:
[Desbravador POS](https://www.desbravador.com.br/produtos/bares-e-restaurantes/pos) e
[ERP POS Fast](https://desbravador.com.br/produtos/bares-e-restaurantes/erp-pos-fast),
com fracionamento, ficha técnica, compras e controle de estoque.
