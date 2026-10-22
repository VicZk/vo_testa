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
| Marketing | Calendário, ocupação, relatório, peças, orçamento e aprovação | Layouts inspecionados nas quatro larguras; calendário vazio e tooltip corrigidos; regras cobertas pela suíte do módulo |
| Comercial | Novo lead, contato existente, origem da campanha, filtros e movimentação | Implementado; 18 testes de cadastro/integração e sete cenários de navegador aprovados |
| Comercial | Tarefas, cotação, comparação de quartos e conversão em reserva | Layouts inspecionados; comparação e envio de proposta por e-mail exercitados no navegador; conversão coberta nos testes de serviço |
| Navegação e acesso | Menu, busca, entrada por perfil e troca de telas | Matriz de larguras e regressões existentes do menu; perfil exclusivo da camareira e foco dos diálogos exercitados |
| Governança | Minha fila, iniciar/terminar limpeza e relato de problema | Falhas reproduzidas e corrigidas; quatro cenários com perfil de camareira aprovados no navegador automatizado |
| Reservas | Mapa, criação, alteração, grupos, entrada, saída, conta e FNRH | Telas inspecionadas; reserva pública ponta a ponta na suíte de navegador; disponibilidade, conta e FNRH cobertas na suíte Django |
| Operação | Manutenção, escala e lavanderia | Layouts inspecionados; conclusão de manutenção com custo e ciclo da lavanderia com cobrança testados no navegador |
| Vendas | Loja, restaurante, comanda e recebimento | Venda com clique repetido e comanda exercitadas; totais, movimentos de caixa e estoque conferidos no banco de teste |
| Estoque | Consulta, entrada, saída, transferência e inventário | Layouts inspecionados; transferência recusada e corrigida, dados preservados e ajuste para zero exercitados no navegador |
| Financeiro | Caixa, contas, conciliação, auditoria e relatórios | Telas de entrada inspecionadas; relatórios individuais em conferência; regras financeiras na suíte Django |
| Cadastros | Pessoas, quartos, tarifas, funcionários e logbook | Layouts inspecionados; seleção dos dias da temporada exercitada; fichas preenchidas em conferência |
| Área pública | Site, reserva, portal, pré check-in, pagamento e landing pages | Layouts inspecionados; portal e pagamento simulado exercitados sem login; origem externa rejeitada; páginas de campanha restantes em conferência |

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

Publicação confirmada: commit `d4c5985f039236d63dac01a8575c356c21be86fe`,
[CI aprovado](https://github.com/VicZk/vo_testa/actions/runs/39731394095), aplicação
ativada na VPS às 03:15 de 22/10 (Brasília). A imagem ativa e os arquivos foram
comparados ao código publicado, a migration `comercial.0033` está aplicada e não
restaram migrations pendentes. Aplicação e banco saudáveis; health check público
e login responderam 200. Backup validado por catálogo e SHA-256, com a imagem
anterior preservada. O banco não foi reiniciado.

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

Publicação confirmada: commit `6a53dce80bf72b8f589aa4fa41caa4c655fe7e45`,
[CI aprovado](https://github.com/VicZk/vo_testa/actions/runs/39732763951), aplicação
ativada às 03:32 de 22/10 (Brasília). Imagem e arquivos conferidos, sem migrations
pendentes, aplicação e banco saudáveis e endpoints públicos de saúde e login com
HTTP 200. Backup validado por catálogo e SHA-256; imagem anterior preservada.
O banco não foi reiniciado.

## Entrega 4 — Responsividade e fluxos de operação

A primeira matriz percorreu 95 rotas GET em quatro larguras (380 combinações):
respostas 200, sem largura excedente na página e sem erro JavaScript. Algumas
rotas redirecionam à mesma tela. As capturas iniciais de celular e desktop foram
inspecionadas; essa matriz não comprova todos os fluxos de escrita.

A matriz adicional percorreu 37 rotas em quatro larguras. Encontrou largura
excedente no detalhe de página de captação (320 px) e no editor de e-mail
(320 e 390 px). Testes de interação reproduziram falha de Escape na comparação
de quartos e de contenção do foco na confirmação de e-mail. Mensagens de tabelas
vazias e alguns campos estavam cortados mesmo sem aumentar a largura da página.
Os diálogos passaram a usar o componente compartilhado, com rolagem interna,
cabeçalho e ações visíveis, retorno de foco e Escape. Os testes conferem também
a geometria após a animação e o ciclo completo de Tab dentro da confirmação.

O editor de e-mail e o detalhe da página de captação usam colunas que se adaptam
à largura disponível. Mensagens de tabelas vazias deixam de herdar a largura de
todas as colunas; buscas e rótulos de checkbox mantêm espaço utilizável. O
calendário vazio não esconde sua mensagem no fim de uma grade larga. A matriz
completa foi repetida com essas alterações: 132 rotas × quatro larguras, 528
combinações aprovadas em 321,847 s, sem erro JavaScript ou largura excedente na página.

O fluxo de transferência reproduziu perda de produto, locais e quantidade
após saldo insuficiente. A inicialização agora usa os dados do formulário
devolvido, e o erro aparece junto aos campos. O teste recusa 25 unidades quando
há 20 e confirma que nada foi movimentado; ao corrigir para três, os dois locais
terminam com 17 e 21 unidades. O ajuste para zero também foi reproduzido: a prévia
mostrava um traço. Agora mostra zero e o registro mantém o movimento de diferença.

Os formulários públicos do portal e do pagamento retornavam 403 porque a meta
`no-referrer` fazia o navegador enviar `Origin: null`. A troca para `same-origin`
mantém a origem nos envios locais e protege o token quando o destino é outro site.
Isso segue a orientação de [proteção CSRF do Django](https://docs.djangoproject.com/en/6.0/ref/csrf/)
e a [política de referência do SecurityMiddleware](https://docs.djangoproject.com/en/6.0/ref/middleware/#referrer-policy).
O teste reproduziu a falha antes da correção e aprovou depois; uma origem externa
com token CSRF válido continua recebendo 403, sem confirmar o pagamento.

Quatorze cenários estão versionados em `apps/site/tests_operacao_e2e.py` e fazem
parte do job de navegador do CI. Os 13 iniciais passaram em 79,044 s; os dois
casos finais de ajuste e total da venda passaram em 9,372 s (um caso sobreposto).
Incluem venda única após clique repetido, comanda, produção e cobrança da
lavanderia, manutenção com resolução e custo, pedidos do portal, envio de proposta
somente após confirmação e pagamento simulado sem login. O banco, os estoques,
o caixa e a caixa de e-mail em memória foram conferidos. A suíte completa passou:
1.834 testes em 817,969 s, sem falhas ou pulos. Ruff, migrations e diff também
passaram. A conferência adicional de relatórios e telas públicas segue em uma
entrega separada, mantendo esta versão igual à versão testada.

O NPS permanece sem coleta; a tela explica isso sem notas clicáveis falsas. O
Fiscal permanece sem emissão real e identifica os documentos simulados. Estas
mudanças de texto não implementam os recursos externos pendentes.

Capturas automatizadas conferidas visualmente: [comparação no celular](evidencias/usabilidade-2026-10-22/comparador-aberto-390.png),
[comparação no desktop](evidencias/usabilidade-2026-10-22/comparador-aberto-1440.png),
[confirmação de e-mail no celular](evidencias/usabilidade-2026-10-22/confirmacao-email-390.png),
[confirmação no desktop](evidencias/usabilidade-2026-10-22/confirmacao-email-1440.png),
[estoque com erro preservado](evidencias/usabilidade-2026-10-22/estoque-recusa-390.png),
[pedidos do portal](evidencias/usabilidade-2026-10-22/portal-pedidos-390.png) e
[total da venda](evidencias/usabilidade-2026-10-22/loja-venda-390.png).
