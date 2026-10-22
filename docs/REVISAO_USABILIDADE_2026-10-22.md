# Revisão de usabilidade — 22/10/2026

Revisão executada na fork `VicZk/vo_testa`, branch `dev`. Cada entrega passa
por testes antes de commit, push e publicação no ambiente da Pousada em
`viczk.cloud/votesta`. O trabalho anterior foi integrado antes desta revisão.

A avaliação considera pessoas com pouca familiaridade com tecnologia: texto
direto em português, tarefa e próximo passo visíveis, alvos de toque, feedback de
salvamento, recuperação de erros e detalhes apresentados quando necessários.

## Método e evidências

- Base local isolada com dados fictícios e perfis de gestão, atendimento,
  marketing e camareira. Envios externos e pagamentos reais não integram esses testes.
- Inspeção e interação por Computer Use, retomadas após a reconexão em 22/10.
  A entrega 6 encerra a pendência de reconferência manual das rodadas anteriores:
  os 35 módulos do menu foram visitados em 390 e 1440 px, com 70 capturas
  inspecionadas, além dos formulários e diálogos descritos abaixo.
- Testes reproduzíveis de navegador, capturas inspecionadas visualmente e testes
  Django contra PostgreSQL 16 complementam a sessão manual.
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
| Navegação e acesso | Menu, busca, entrada por perfil e troca de telas | Matriz de larguras e regressões do menu; perfil da camareira, foco dos diálogos e cinco telas de acesso com/sem sessão exercitados |
| Governança | Minha fila, iniciar/terminar limpeza e relato de problema | Falhas reproduzidas e corrigidas; quatro cenários com perfil de camareira aprovados no navegador automatizado |
| Reservas | Mapa, criação, alteração, grupos, entrada, saída, conta e FNRH | Telas inspecionadas; reserva pública e grupo com quarto, entrada e recebimento na suíte de navegador; disponibilidade, conta e FNRH na suíte Django |
| Operação | Manutenção, escala e lavanderia | Layouts inspecionados; conclusão de manutenção com custo e ciclo da lavanderia com cobrança testados no navegador |
| Vendas | Loja, restaurante, comanda e recebimento | Venda com clique repetido e comanda exercitadas; totais, movimentos de caixa e estoque conferidos no banco de teste |
| Estoque | Consulta, entrada, saída, transferência e inventário | Layouts inspecionados; transferência recusada e corrigida, dados preservados e ajuste para zero exercitados no navegador |
| Financeiro | Caixa, contas, conciliação, auditoria e relatórios | Telas e relatórios individuais inspecionados nas quatro larguras; regras financeiras na suíte Django |
| Cadastros | Pessoas, quartos, tarifas, funcionários e logbook | Layouts e fichas preenchidas inspecionados; seleção dos dias da temporada exercitada |
| Área pública | Site, reserva, portal, pré check-in, pagamento e landing pages | Portal e pagamento simulado exercitados sem login; origem externa rejeitada; captação dinâmica e três LPs exercitadas com falha e nova tentativa |

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
reconferência visual ficou pendente naquela rodada e foi retomada na entrega 6.

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
A conferência manual por Computer Use ficou pendente naquela rodada e foi
retomada na entrega 6.

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

Publicação confirmada: commit `9391d539586e6336d5d2bf3eea9405e858fa5b04`,
[CI aprovado](https://github.com/VicZk/vo_testa/actions/runs/39736970766), aplicação
ativada às 04:09:59 de 22/10 (Brasília) e saudável na conferência seguinte.
Os hashes do CSS, da view de estoque e do template do portal coincidem entre
checkout, imagem construída e container ativo. Não há migrations pendentes;
saúde e login públicos responderam 200 após a partida. O banco permaneceu
saudável, com o mesmo horário de inicialização. Backup conferido por catálogo e
SHA-256, com imagem anterior preservada para retorno.

## Entrega 5 — Grupos, captação pública e telas de acesso

A matriz adicional reuniu 33 telas ou estados: todos os relatórios disponíveis,
fichas preenchidas, inventário, grupo, documento fiscal com chave de 44 dígitos,
captação pública, três LPs, privacidade e recuperação de senha. Foram 132
combinações nas quatro larguras, aprovadas em 141,011 s. Somadas à matriz anterior,
são 660 combinações de tela e largura. Há rotas que mostram a mesma página; este
número não significa 165 fluxos de escrita distintos.

A inspeção encontrou formulários de grupo ultrapassando 320, 390 e 821 px,
chave fiscal ultrapassando 320 px e formulário público excedendo 320 px.
As colunas dos grupos agora se organizam pelo espaço disponível, com rótulos
visíveis e explicação de onde entram diárias e consumo. O teste de recebimento
revelou também a ausência do campo de parcelas exigido pelo servidor. O fluxo
completo adiciona um quarto, confirma o grupo, registra a entrada e recebe
R$ 120 de R$ 600; o caixa recebe R$ 120 e a conta termina com R$ 480 de saldo.
A chave fiscal quebra linha dentro de sua ficha.

Na captação pública, campos de data deixam de empurrar a página, o consentimento
usa uma caixa de seleção com texto ao lado e os campos têm rótulos permanentes.
Telefone, e-mail, limites e datas são validados antes da gravação. Dados inválidos
continuam preenchidos com o erro correspondente. O consentimento descreve os
dois canais efetivamente concedidos pelo serviço: e-mail e WhatsApp.

Uma falha simulada depois de criar o contato reproduziu o falso sucesso da
captação. A fronteira pública agora usa transação, desfaz a gravação parcial e
mostra o erro. O retorno sem oportunidade também não confirma a inscrição.
A origem da campanha, datas, pessoas e aceite são conferidos após a correção.
As respostas silenciosas de antirrobô e limite de abuso continuam cobertas.

As três LPs oficiais também ignoravam falhas de gravação: o servidor retornava
sucesso e ainda tentava enviar o evento de conversão. Agora devolve falha e só
envia esse evento após salvar. O navegador exige HTTP bem-sucedido e `ok: true`,
preserva os campos, libera nova tentativa e foca o aviso. O teste cobre erro 503,
HTTP 200 com `ok: false`, DDD inválido com explicação do servidor, correção e
clique repetido em 320, 390 e 1440 px.
Na inauguração, a condição de domínio fazia a página da VPS usar demonstração;
o envio passou a ocorrer em páginas servidas por HTTP/HTTPS. A medição mantém
seu controle de consentimento. Ao confirmar, o título fica visível abaixo do
cabeçalho fixo e recebe o foco depois da virada do cartão.

As telas de recuperação ficavam vazias quando o usuário já estava conectado:
o template-base escolhia o conteúdo interno, enquanto a tela definia somente o
conteúdo público. As cinco views de acesso agora informam seu contexto ao base.
Os testes conferem título e largura com e sem sessão, além do fluxo existente
de redefinição e da resposta a e-mail desconhecido.

Validações focadas: 17 testes iniciais de grupo/captação; 33 testes de LPs,
falhas e recuperação; dois cenários de navegador em 87,342 s. A rodada final
das três LPs, incluindo a confirmação visível e o erro de DDD, passou em
43,731 s. Os 146 testes de design e captação passaram em 27,053 s após adequar
os rótulos ao componente compartilhado. A suíte completa final passou:
1.849 testes em 396,152 s, sem falhas ou pulos. Ruff e migrations passaram;
12 blocos JavaScript das LPs tiveram sintaxe conferida.
As capturas aguardam o fim das animações finitas de entrada antes de serem
inspecionadas. Nenhum model ou migration foi alterado nesta entrega.

A repetição integral local usa um arquivo temporário de configuração com
`MD5PasswordHasher` apenas para senhas fictícias, conforme a orientação de
[aceleração de testes do Django](https://docs.djangoproject.com/en/6.0/topics/testing/overview/#password-hashing).
Essa configuração não integra o repositório nem o deploy; o CI executa os
hashers configurados no projeto. A rodada anterior com os hashers do projeto
executou os mesmos 1.849 casos e apontou somente a convenção de rótulos,
corrigida e revalidada. Os arquivos finais coincidem com os da cópia testada.

Capturas automatizadas inspecionadas: [formulários do grupo](evidencias/usabilidade-2026-10-22/grupo-final-390.png),
[recebimento e saldo](evidencias/usabilidade-2026-10-22/grupo-recebimento-390.png),
[detalhe fiscal](evidencias/usabilidade-2026-10-22/fiscal-final-390.png),
[correção da data na captação](evidencias/usabilidade-2026-10-22/captacao-erro-320.png),
[telefone inválido na LP](evidencias/usabilidade-2026-10-22/lp-fundador-dados-invalidos-390.png),
[falha preservada no Fundador II](evidencias/usabilidade-2026-10-22/lp-fundador_2-erro-390.png),
[falha na inauguração](evidencias/usabilidade-2026-10-22/lp-inauguracao-erro-390.png),
[confirmação no celular](evidencias/usabilidade-2026-10-22/lp-inauguracao-sucesso-390.png),
[confirmação no desktop](evidencias/usabilidade-2026-10-22/lp-inauguracao-sucesso-1440.png),
[recuperação no celular](evidencias/usabilidade-2026-10-22/senha-recuperacao-390.png) e
[recuperação no desktop](evidencias/usabilidade-2026-10-22/senha-recuperacao-1440.png).

Publicação confirmada: commit `61af5f0df7748c001d088101f09e23ca0141ee5d`,
[CI aprovado](https://github.com/VicZk/vo_testa/actions/runs/39740626887), aplicação
ativada às 04:36:24 de 22/10 (Brasília). Os 16 arquivos conferidos coincidem entre
commit, checkout da VPS, imagem e container ativo; as diferenças locais de CRLF
foram normalizadas para comparar com os blobs do Git. Aplicação e banco saudáveis,
sem reinícios ou migrations pendentes; seis URLs públicas responderam 200.

## Entrega 6 — Galeria, PDV e reconferência visual do CRM

A sessão de Computer Use foi reconectada e a prioridade voltou ao CRM. Foram
percorridos os 35 módulos do menu em celular de 390 px e computador de 1440 px,
com o menu lateral aberto no computador. A revisão abriu também busca global,
nova reserva em 320 px, cadastro de lead expandido em 390/821/1440 px, atendimento
e comparação de quartos, criação e detalhe de campanha, seções de responsáveis
e peças, guia da Governança, início de limpeza, comanda e respostas aos recados.
Os nove blocos principais da homepage foram inspecionados em 390 e 1440 px.
Todos os dados usados são fictícios, na base local isolada.

O PDV da Loja agora usa as categorias já cadastradas, como Bebidas e Lanches,
para filtrar o catálogo. A busca aceita palavras sem acento e pode ser limpa em
um clique. Os cartões mostram a quantidade escolhida e o saldo ainda disponível;
o carrinho exibe nomes completos, quantidade, subtotal e botões de 44 px. Em uma
área estreita, Produtos e Carrinho se alternam por uma barra que mantém quantidade
e total visíveis. O carrinho é preservado entre as abas e ao redimensionar a tela.
O local de estoque fica bloqueado enquanto há itens, para evitar perder a seleção.

No computador, um produto pode ser arrastado para o carrinho. O gesto aceita
somente o produto iniciado no próprio catálogo e não grava uma venda. A
finalização mantém a chave única existente: o teste faz o servidor gravar,
descarta a resposta e repete o envio, comprovando uma única venda e uma única
baixa de estoque. Regras financeiras e serviços de venda não foram alterados.
O arraste foi confirmado pelo teste de Chromium com `drag_to`; a tentativa pelo
controlador manual não incluiu o produto e não é contada como confirmação manual
desse gesto. Filtros, seleção por clique e uso do carrinho foram operados manualmente.

A galeria estava dentro de uma seção com transformação visual, que mudava a
referência de posicionamento e deixava a janela escapar da tela. Ela agora usa
um diálogo nativo fora da seção, acima do cabeçalho e do botão de WhatsApp. A foto
permanece inteira, sem corte, com legenda e contador; fechar, avançar e voltar
têm área de 44 px. Escape devolve o foco à foto de origem e libera a rolagem.
Uma foto ausente não desloca o índice das seguintes. A conferência manual incluiu
320 × 568, 390 × 844, 844 × 390 e 1440 × 844 px; a regressão automatizada também
cobre 821 px e navegação da última para a primeira foto.

Outros ajustes encontrados durante a navegação:

- Opções de Escala, Comercial e outros controles segmentados quebram linha,
  deixando visíveis os itens antes escondidos pela rolagem sem barra.
- A lista de funcionários da Escala aproveita a largura disponível no celular.
- O campo de resposta dos recados usa o estilo e o foco visível do sistema.
- Ao abrir Responsáveis e equipe no Marketing, o fornecedor e seu botão saíam
  do cartão. Campos e ações agora quebram linha; a regressão abre todas as seções
  da ficha e confere seus limites nas quatro larguras.
- Textos públicos de contato, eventos e Dia na Pousada descrevem o atendimento
  ao visitante sem expor termos internos de CRM e funil.

A matriz adicional foi repetida: 380 combinações operacionais, 148 complementares
e 132 de detalhes, totalizando **660 combinações**, aprovadas em 400,632 s. Ela
verifica resposta, erros de JavaScript e largura, mas não equivale a 660 fluxos de
gravação. A sessão manual complementa essa matriz ao abrir os estados recolhidos.
O [índice manual](evidencias/usabilidade-2026-10-22/revisao-6-telas.csv) registra as
70 capturas dos módulos, e a [matriz de larguras](evidencias/usabilidade-2026-10-22/revisao-6-matriz.csv)
registra as 660 verificações. As capturas integrais permanecem no ambiente local.

Validação focada: 136 testes de design, galeria, PDV e navegação aprovados em
22,379 s; depois, 131 testes de design e da ficha expandida de Marketing aprovados
em 9,176 s. A suíte integral contém 1.855 casos, incluindo 62 de navegador.
A rodada integral final passou: **1.855 testes em 422,020 s, sem falhas ou pulos**.
Os 12 arquivos de implementação e testes permaneceram idênticos durante a rodada,
conferidos por SHA-256 antes e depois da execução.
Ruff, sintaxe do JavaScript e `makemigrations --check --dry-run` aprovados.
Nenhum model ou migration foi alterado. A configuração temporária para acelerar
senhas fictícias segue o método descrito na entrega 5; ela não integra o deploy.

Capturas da sessão de Computer Use, com dados e imagens de teste:

- [Carrinho antes](evidencias/usabilidade-2026-10-22/pdv-antes-carrinho-390.jpg),
  [catálogo depois](evidencias/usabilidade-2026-10-22/pdv-depois-produtos-390.jpg) e
  [carrinho depois](evidencias/usabilidade-2026-10-22/pdv-depois-carrinho-390.jpg).
- [Galeria antes](evidencias/usabilidade-2026-10-22/galeria-antes-aberta-390.jpg),
  [depois em 320 px](evidencias/usabilidade-2026-10-22/galeria-depois-320.jpg),
  [paisagem](evidencias/usabilidade-2026-10-22/galeria-depois-paisagem.jpg) e
  [computador](evidencias/usabilidade-2026-10-22/galeria-depois-1440.jpg).
- [Fornecedor no Marketing](evidencias/usabilidade-2026-10-22/marketing-fornecedor-depois-390.jpg)
  e [resposta aos recados](evidencias/usabilidade-2026-10-22/recados-resposta-depois-390.jpg).
