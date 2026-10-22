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
| Comercial | Origem da campanha, leads, responsáveis, tarefas, cotação e reserva | Próxima implementação e conferência |
| Navegação e acesso | Menu, busca, entrada por perfil e troca de telas | Conferência complementar pendente |
| Governança | Minha fila, quarto, limpeza, enxoval, inspeção e problema | Conferência com perfil de camareira pendente |
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
