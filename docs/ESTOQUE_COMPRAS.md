# Compras, perecíveis e pratos

Fluxo operacional incorporado em 22/10/2026, com notas de entrada em 23/10.
O estoque físico continua vindo do kardex do núcleo; notas, embalagens, lotes
e fichas técnicas usam esse mesmo motor.
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

## Cadastrar a nota e receber as entregas

Em **Estoque → Notas → Cadastrar nota**, informe fornecedor, tipo de documento,
número, série e emissão. A chave de acesso é opcional; quando informada, precisa
ter 44 dígitos. Confira o CPF/CNPJ do fornecedor no cadastro antes de começar.
Cadastre os itens e as quantidades previstas na unidade base ou na embalagem de
compra, com o custo nessa mesma unidade. Uma nota aceita até 100 itens.

**Cadastrar a nota não aumenta o estoque nem altera o custo do produto.** A nota
guarda o que se espera receber. A ficha mostra, por item, as quantidades previstas,
recebidas e pendentes; a situação passa de **Pendente** para **Parcial** e, ao
completar todos os itens, para **Concluída**.

Na ficha, abra **Receber itens** e informe em **Receber agora** somente o que chegou
e foi aceito. Deixe vazios os itens que não chegaram. Escolha o local e, quando o
produto controla validade, o lote. Cada nova entrega usa a mesma nota, respeitando
o saldo pendente. Se um item chegar em lotes ou locais diferentes, registre as
parcelas separadamente, reabrindo a tela para conferir o pendente atualizado.

O recebimento grava todos os itens válidos daquela confirmação juntos e liga cada
entrada à nota no kardex. Se houver erro em um item, a confirmação inteira fica
sem efeito. A apresentação e o custo conferidos no cadastro da nota ficam
preservados, mesmo que a embalagem seja alterada depois.

A nota impede novo cadastro com a mesma identidade de fornecedor, tipo, número e
série, ou com a mesma chave de acesso informada. Números e séries apenas numéricos
ignoram zeros à esquerda. Sem CPF/CNPJ, a identificação usa o cadastro do fornecedor;
evite cadastros duplicados da mesma empresa. Reenviar a mesma confirmação devolve
o registro já concluído; reutilizar sua chave com outro conteúdo é recusado. Se
outra pessoa receber enquanto a tela estiver aberta, atualize e confira novamente
as quantidades antes de enviar.

Anexe PDF, PNG, JPG ou XML no cadastro ou depois, na própria ficha: até dez arquivos
de até 10 MB por nota. Um arquivo idêntico já anexado não é duplicado. Os documentos
são privados, exigem login e acesso ao Estoque e não ganham endereço público em
`media/`. Anexar XML apenas guarda o documento: os itens são transcritos pela equipe;
não há importação automática, consulta ou validação fiscal na SEFAZ.

Notas, itens e recebimentos formam histórico imutável. Confira os dados antes de
registrar; esta etapa não oferece edição ou cancelamento da nota. Divergências
devem ser registradas e conferidas pela gerência antes de movimentar o estoque.

## Receber na apresentação comprada

Em **Produto → Embalagens e ficha técnica**, cadastre a apresentação:

| Compra | Unidade do estoque | Quantidade base por embalagem |
|---|---|---:|
| Caixa com 12 garrafas | Unidade | 12 |
| Saco de 5 kg | Quilo | 5 |
| Pacote de 500 g | Quilo | 0,500 |
| Garrafa de 1 litro | Mililitro | 1000 |

Use a embalagem no item da nota ou, para uma entrada avulsa, em
**Compras → Receber por embalagem**. Na entrada avulsa, confira fornecedor,
documento, local, quantidade e custo por embalagem. A prévia mostra a conversão
e o custo total.
Duas caixas de 12 unidades a R$ 60 por caixa entram como 24 unidades a R$ 5 por
unidade. O valor de aquisição é preservado antes do arredondamento do custo
unitário para quatro casas decimais.

O recebimento avulso guarda a embalagem e o fator usados na época. Editar a embalagem
não recalcula entradas antigas; alterar o fator enquanto a tela está aberta
exige nova conferência. Reenviar o mesmo formulário não duplica o recebimento;
usar sua chave com outro conteúdo é recusado.

**Na entrada avulsa, o controle de duplicidade do documento continua manual.**
Receba somente a quantidade aceita, identifique cada parcela na observação e
procure o documento no histórico antes de abrir outro formulário. A chave protege
o reenvio daquele formulário, mas não consolida documentos, itens e pendências.
Para entregas parciais de uma mesma nota, prefira o fluxo **Notas** descrito acima.
Não registre novamente como avulso um item já recebido pela nota.

**Cadastrar a nota ou receber mercadoria não paga a compra.** Registre ou confira
a conta a pagar no Financeiro e faça a baixa pelo procedimento financeiro existente. O
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
- Operação: ensaiar o cadastro de uma nota, duas entregas parciais, transferência,
  venda de prato, cancelamento e perda com dados de treinamento; conferir itens
  pendentes, kardex, lotes e caixa ao fim.

Testes automatizados cobrem limites numéricos, repetição, rollback, disputa
pelo último saldo, alteração concorrente da ficha, permissões, preservação dos
formulários e uso no navegador. Ensaios de código não validam a ficha culinária,
o estoque físico ou os parâmetros fiscais reais de cada produto.

Referências de produto consultadas antes da implementação:
[Desbravador POS](https://www.desbravador.com.br/produtos/bares-e-restaurantes/pos) e
[ERP POS Fast](https://desbravador.com.br/produtos/bares-e-restaurantes/erp-pos-fast),
com fracionamento, ficha técnica, compras e controle de estoque.
