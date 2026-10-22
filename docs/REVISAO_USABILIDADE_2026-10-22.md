# Revisão de usabilidade — 22/10/2026

Revisão em andamento na fork `VicZk/vo_testa`, branch `dev`. Cada entrega passa
por testes antes de commit, push e publicação no ambiente da Pousada em
`viczk.cloud/votesta`. O trabalho anterior foi integrado antes desta revisão.

A avaliação considera pessoas com pouca familiaridade com tecnologia: texto
direto em português, tarefa e próximo passo visíveis, alvos de toque, feedback de
salvamento, recuperação de erros e detalhes apresentados quando necessários.

## Método e evidências

- Base local isolada com dados fictícios e perfis de gestão, atendimento,
  marketing e camareira. Envios externos e pagamentos reais não integram esses testes.
- Inspeção e interação por Computer Use, complementadas por testes reproduzíveis
  de navegador e testes Django contra PostgreSQL 16.
- Larguras: 320, 390, 821 com menu aberto e 1440 px. Conferência de sobreposição,
  rolagem, teclado, alterações pendentes e preferência por movimento reduzido.
- A indicação de uma tela como inspecionada registra observação desta revisão;
  testes históricos e análise de código são evidências distintas.

## Cobertura atual

| Área | Fluxos | Situação nesta revisão |
|---|---|---|
| Marketing | Criar/cancelar campanha, editar dados e meta, validar, fechar, atualizar quadro | Corrigido; inspeção real do formulário e oito regressões no navegador aprovadas |
| Interface compartilhada | Modal, rolagem da página e interrupção da animação | Falha de escala reproduzida; motor corrigido e testado em 30 fps, 1 fps e retomada de aba |
| Marketing | Calendário, ocupação, relatório, peças, orçamento e aprovação | Próxima conferência de fluxo |
| Comercial | Novo lead, contato existente, origem da campanha, filtros e movimentação | Implementado; 18 testes de cadastro/integração e sete cenários de navegador aprovados |
| Comercial | Tarefas, cotação, comparação de quartos e conversão em reserva | Conferência complementar pendente |
| Navegação e acesso | Menu, busca, entrada por perfil e troca de telas | Conferência complementar pendente |
| Governança | Minha fila, iniciar/terminar limpeza e relato de problema | Falhas reproduzidas e corrigidas; quatro cenários com perfil de camareira aprovados no navegador automatizado |
| Reservas | Mapa, criação, alteração, grupos, entrada, saída, conta e FNRH | Conferência pendente |
| Operação | Manutenção, escala e lavanderia | Conferência pendente |
| Vendas | Loja, restaurante, comanda, cozinha e recebimento | Conferência pendente |
| Estoque | Consulta, entrada, saída, transferência e inventário | Conferência pendente |
| Financeiro | Caixa, contas, conciliação, auditoria e relatórios | Conferência pendente |
| Cadastros | Pessoas, quartos, tarifas, equipe e logbook | Conferência pendente |
| Área pública | Site, reserva, portal, pré check-in, pagamento e landing pages | Conferência pendente |

## Entrega 1 — Campanhas

O formulário antigo criava uma campanha antes de a pessoa preencher qualquer
dado. A ficha no celular reservava quase toda a altura para o cabeçalho; em 390 px,
o corpo útil observado era de aproximadamente 75 px. A gravação ao sair de um campo
substituía a ficha e tirava o foco do próximo campo.

A criação agora começa por nome e objetivo, com chave única por envio. A edição
tem salvamento explícito, validação de valores e datas, manutenção do texto em
caso de erro, confirmação de descarte e seções para os detalhes. O cabeçalho curto
deixa aproximadamente 581 px para o corpo na mesma tela de 390 × 844 px.

Durante o teste de fechamento, a transformação visual chegou a uma escala próxima
de 963 e a janela permaneceu bloqueada. O motor passou da integração aproximada
para a solução exata do movimento amortecido. O teste cobre intervalos de 33 ms,
1 segundo e 60 segundos entre quadros, além de abrir durante um fechamento.

Validação específica: `apps.marketing.tests_edicao` e
`apps.site.tests_e2e.CampanhaEdicaoE2ETests`. A migration `marketing.0007` acrescenta
uma chave UUID opcional e única; os registros existentes continuam sem chave.

A suíte completa local passou em 1.786 testes (665,219 s), sem pulos. Os dois
casos adicionados durante essa execução passaram na rodada focada posterior,
com 13 testes de edição e oito testes de navegador (21 aprovados). Ruff e
`makemigrations --check --dry-run` não indicaram pendências. A publicação depende
também do CI Linux do commit exato.

Capturas do teste automatizado com dados fictícios:
[celular de 390 px](evidencias/usabilidade-2026-10-22/campanha-390.png) e
[desktop de 1440 px](evidencias/usabilidade-2026-10-22/campanha-1440.png).

A conexão de Computer Use deixou de responder durante a rodada final. Os oito
cenários de navegador foram executados e aprovados pelo teste automatizado; a
reconferência visual final está pendente da retomada da conexão.

Publicação confirmada: commit `e12cb510e319d01ebad87cefb555308b1d0c9b35`,
[CI aprovado](https://github.com/VicZk/vo_testa/actions/runs/39727416864), VPS
conferida às 02:35 de 22/10 (Brasília). A imagem ativa foi comparada ao código
publicado, a migration estava aplicada, o banco e a aplicação estavam saudáveis
e o health check público e o login responderam 200. O backup foi validado por
leitura do catálogo e SHA-256; a imagem anterior foi preservada para retorno.

## Entrega 2 — Leads e integração com campanhas

O formulário anterior criava o contato separadamente e redirecionava ao funil em
caso de erro na oportunidade, perdendo o preenchimento. O novo formulário grava
contato e atendimento na mesma transação e permite escolher alguém já cadastrado.
A chave única também foi testada com duas solicitações concorrentes; apenas um
contato e um atendimento permaneceram no banco.

Campanha, canal de origem e interesse ficam no primeiro grupo de campos. Datas,
quantidades, valor e responsável aparecem em uma seção opcional. Valores inválidos,
datas invertidas e contatos malformados retornam com o texto preservado e foco no
erro. A criação manual não concede consentimento de marketing ao contato.

A ligação entre Marketing e Comercial leva ao funil filtrado pela campanha,
mantém o filtro na movimentação e apresenta o acesso ao planejamento apenas para
quem tem permissão. A agregação de resultados passou para a interface pública do
Comercial, preservando a fonte única dos leads e das reservas.

A movimentação no celular usa o modal compartilhado. Uma falha de autorização
encontrada durante a revisão permitia reabrir um lead encerrado pela rota comum,
sem passar pela gestão de fechados. Os serviços agora travam e conferem o estado
antes de alterar; a perda de um lead ganho também exige o fluxo apropriado.

Validações aprovadas: 513 testes de Comercial, Marketing e design; oito testes de
navegador (sete novos e o arrasto existente). Os cenários incluem quatro larguras,
erro e recuperação, contato existente, ida e volta entre campanha e funil,
cancelamento, cliques repetidos, teclado e motivo de perda. A suíte completa da
segunda entrega passou em 1.813 testes (719,514 s), sem pulos. Ruff, sintaxe dos
scripts, comparação das migrations e verificação do diff não indicaram pendências.
A fixture do teste de limpeza de reservas passou a criar sua própria etapa do
funil; o teste de concorrência encerra as conexões dos dois trabalhadores.
A conferência manual por Computer Use segue pendente da conexão.

Capturas do teste automatizado com dados fictícios:
[celular de 390 px](evidencias/usabilidade-2026-10-22/lead-390.png) e
[desktop de 1440 px](evidencias/usabilidade-2026-10-22/lead-1440.png).

## Entrega 3 — Governança

No teste com o perfil exclusivo de camareira, começar uma limpeza mudava o botão
para «Terminei», mas mantinha a instrução antiga no cabeçalho. A orientação agora
faz parte do trecho atualizado e mostra o quarto em andamento ou o trabalho
concluído. A visão geral também distingue tarefas já distribuídas de nenhuma
limpeza pendente.

Um relato com espaços em branco fechava o modal sem registrar o chamado. O
formulário agora valida descrição obrigatória e limite de 400 caracteres,
preserva o texto, apresenta o motivo e mantém a janela aberta. Apenas o sucesso
confirmado fecha o relato e atualiza a fila. O chamado aparece na Manutenção;
o bloqueio do quarto continua sendo uma decisão operacional separada.

Os quatro cenários de Governança passaram junto dos oito de campanhas e sete
de leads (19 testes, 92,154 s). Incluem a entrada direta pelo perfil, começo e
conclusão da limpeza, erro e correção do relato, clique repetido, descarte,
retorno do foco e geometria nas quatro larguras. A suíte completa passou:
1.820 testes em 730,298 s, sem pulos. Ruff, sintaxe do JavaScript, comparação
das migrations e diff passaram; os arquivos publicados correspondem à cópia testada.

Capturas automatizadas, inspecionadas visualmente nas quatro larguras:
[relato no celular](evidencias/usabilidade-2026-10-22/governanca-relato-390.png) e
[relato no desktop](evidencias/usabilidade-2026-10-22/governanca-relato-1440.png).

## Varredura complementar em andamento

A primeira matriz percorreu 95 rotas GET em quatro larguras (380 combinações):
respostas 200, sem largura excedente na página e sem erro JavaScript. Algumas
rotas redirecionam à mesma tela. As capturas iniciais de celular e desktop foram
inspecionadas; essa matriz não comprova todos os fluxos de escrita.

A matriz adicional percorreu 37 rotas em quatro larguras. Encontrou largura
excedente no detalhe de página de captação (320 px) e no editor de e-mail
(320 e 390 px). Testes de interação reproduziram falha de Escape na comparação
de quartos e de contenção do foco na confirmação de e-mail. Mensagens de tabelas
vazias e alguns campos estavam cortados mesmo sem aumentar a largura da página.
Essas correções integram a próxima entrega.
