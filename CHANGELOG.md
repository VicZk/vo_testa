# Changelog

Tudo o que muda neste fork (`VicZk/vo_testa`), push a push. Cada entrada diz **o que
melhorou**, ou seja, o efeito para a pousada, e **o que foi modificado**, ou seja, onde
o código mexeu, com os commits. A explicação completa de cada commit (o que mudou, por
quê e como foi testado) está na mensagem dele no GitHub.

A entrada mais nova fica no topo. As datas são as do push.

---

## 27/10/2026: Cronograma do mês e Aprovação de LPs no Marketing

Os dois pedidos do Marketing para centralizar o trabalho no CRM.

- **Cronograma do mês.** A nova aba Cronograma mostra o mês em grade, um quadrado por dia.
  Num só lugar aparecem:
  - as entregas com prazo;
  - as tarefas das campanhas com prazo;
  - o início e o fim de cada campanha;
  - os prazos de aprovação de LP.

  Nada é cadastrado duas vezes: a entrega ou a tarefa criada dentro da campanha aparece
  pela própria data. O "+" de cada dia abre uma entrega nova já com aquele prazo. As
  entregas ganharam os tipos **Arte** e **Ação / evento**, ao lado de Post, Anúncio,
  Impresso e Landing page. O filtro de canal vale aqui também. No espaço estreito (menu
  aberto no tablet, celular), a grade vira a lista dos dias que têm algo.
- **Aprovação de LPs.** Na nova aba LPs, a equipe envia o HTML da LP, que é o mesmo
  arquivo autocontido que o design entrega hoje. O CRM gera um link de prévia que abre
  sem login e fica fora das buscas. Por esse link, o gestor ou o cliente:
  - vê a página como computador ou celular, ou em tela cheia;
  - comenta, pede ajuste ou aprova a versão.

  Cada arquivo novo é uma versão: volta para aprovação e quem estava vendo a anterior
  precisa abrir a nova antes de decidir. A equipe marca cada ajuste como feito. Pode
  também gerar um link novo, e o antigo deixa de abrir. Depois de aprovada, a LP é
  publicada daqui em `/lp/<endereço>/`, pelo Comercial, e os leads do formulário caem
  no funil como os das outras LPs. Republicar troca o HTML da mesma página.
- **Segurança da prévia.** Um HTML de fora servido no endereço do CRM rodaria com a
  sessão de quem abriu. Por isso a prévia vai com `Content-Security-Policy: sandbox`
  (sem `allow-same-origin`) e dentro de `<iframe sandbox>`: o script da LP roda, mas não
  lê cookie nem age no CRM como o usuário. O formulário do link tem antirrobô e limite
  por IP. O que chega sem login fica na trilha como "Aprovação de LP (link)". O HTML,
  que pode ter alguns megabytes, fica na versão e não é copiado para a trilha de
  auditoria.

**O que foi modificado:**
- Models `AprovacaoLP`, `VersaoLP` e `ComentarioLP` (migração `marketing.0012`).
- Campo `PaginaCaptacao.html` (`comercial.0035`).
- Novos arquivos: `apps/marketing/services_lp.py`, `views_lps.py`, `views_previa.py`,
  `urls_previa.py` (montado em `/aprovacao/`) e `forms_lp.py`.
- `services_agenda.cronograma_mes` e a view `cronograma`.
- `comercial.services.publicar_lp_aprovada`, com as rotas `lp:publicada` e
  `lp:publicada_lead`.
- Templates em `templates/marketing/` (`cronograma`, `lps`, `lp_nova`, `lp_detalhe`,
  `previa_publica` e parciais) e estilos `.cron-*`/`.mkt-lp*` no `app.css`.
- Manifesto do `base.css`.
- Testes em `apps/marketing/tests_lp_cronograma.py`.
- A lista de LPs ordena explicitamente pela última atualização. Com a contagem de
  ajustes, o banco agrupa e o Django deixa de aplicar a ordem do model. O aviso do
  paginador apareceu na conferência na VPS.
- O texto dos itens do Cronograma subiu para 0,75 rem, o piso de legibilidade no toque
  que o teste de design exige (`TemaCompartilhadoTests`).

## 26/10/2026: aba Comparativo técnica, com o código de cada conserto

- **Código no lugar da paráfrase.** A versão em linguagem do dia a dia ficou simples
  demais para apresentar a quem escreveu o sistema. Cada conserto traz agora o antes e o
  agora em termos técnicos (funções, models, migrations) e o diff do trecho: `−` é a
  linha do `main` do original, `+` a da `dev`, com link para o commit. São 12 consertos
  com código e 27 blocos ao todo; os dois de segurança seguem sem código, porque a página
  é aberta e a produção ainda roda a versão anterior.
- **Números técnicos.** Nove medidas: testes (977 → 2.863), testes de ponta a ponta
  (8 → 282), restrições no banco (21 → 60), travas de linha (5 → 77), consultas ao abrir
  um lead (444 → 56) e na busca de quartos (334 → 18), tamanho e primeira pintura da LP
  da inauguração e alvos de toque abaixo de 44 px.
- **O que é do Gefferson, com o código dele.** Nova parte "A base que ficou": o
  `ExclusionConstraint` contra overbooking, o `@requer_modulo` e o `travar()`, iguais nas
  duas versões. Também ficou dito o que já era dele: o `security.yml`, a verificação em
  duas etapas e a trava do custo médio no estoque.
- **Trechos conferidos no git.** Os trechos são colados sem retoque, e
  `conferir_trechos.py` confere cada linha no `main` do original e no commit do fork.
  Na conferência, a máscara de R$ apareceu reescrita também no front: converte só o que
  é enviado (`formdata` e `htmx:configRequest`), e o diff mostra as duas camadas.
- **Modificado:** `deploy/vps/comparador/comparativo.py`, `trechos.py` (novo),
  `conferir_trechos.py` (novo), `templates/vps/comparativo.html`, `_texto.html` e
  `_codigo.html` (novos), o README da pasta e `apps/site/tests_comparativo.py`.
- **Teste de navegador estável:** o do calendário da reserva no site falhou uma vez no
  CI com "Transition was aborted… Viewport size changed". É o próprio teste trocando a
  largura da janela no meio de uma transição de página, e só acontece se ela ainda
  estiver rodando naquele instante. `tests_auditoria_publico_e2e` passou a ignorar só
  esse aviso; qualquer outro erro de JavaScript continua reprovando.

## 26/10/2026: aba Comparativo em linguagem do dia a dia, com gráficos

- **Sem jargão.** Os textos foram reescritos para quem não é da área técnica, com
  exemplos concretos ("R$ 650,00 virava R$ 65.000,00", "o despertador que dispara as
  tarefas da madrugada"). As seções viraram "O que foi consertado", "O que é novo",
  "Mais fácil de usar", "Por trás das telas" e "O que veio do Gefferson".
- **Em números, com barras.** No lugar dos quatro indicadores do topo, seis medidas com
  barra cinza (antes) e dourada (agora), cada uma na sua escala e com o destaque escrito
  ("10× mais rápida", "35× mais"). As duas cores passaram pelo validador de cores do
  guia de gráficos, e cada barra tem rótulo e valor escritos.
- **Modificado:** `deploy/vps/comparador/comparativo.py` e
  `templates/vps/comparativo.html`.

## 26/10/2026: aba Comparativo com o tom revisto

- **Texto para apresentar.** "Grave" e "Importante" viraram "Impacto alto" e "Impacto
  médio", que falam do efeito para a pousada e não do trabalho de ninguém. Os textos com
  tom de crítica ficaram descritivos: as rotinas da madrugada estavam prontas e faltava
  ligar o agendador. "De volta para o original" não repete a lista de correções. Entrou
  a Visão geral reorganizada, com o antes e o agora.
- **Modificado:** `deploy/vps/comparador/comparativo.py` e
  `templates/vps/comparativo.html`; o texto das duas entradas abaixo e um comentário do
  `app.css` ficaram neutros.

## 26/10/2026: Visão geral com chegadas e saídas empilhadas e recados ao lado

- **Chegadas e saídas uma embaixo da outra.** Lado a lado, as duas listas tinham
  alturas diferentes (a vazia ficava maior que a com um hóspede) e, com muita gente,
  a mais curta sobrava em branco. Agora ficam empilhadas, com a mesma largura, e a
  lista vazia vira uma linha só ("Sem saídas previstas para hoje.").
- **Recados do turno num cartão ao lado.** Os recados saíram da faixa entre as listas
  e o mapa dos quartos e viraram um cartão da casa, em lista como as chegadas, numa
  coluna ao lado do movimento do dia que acompanha a rolagem. No celular, e em tela
  média com o menu aberto, vêm depois das saídas. O recado importante tem o ponto
  vermelho e o fundo suave, e o pé do cartão leva a "Escrever um recado".
- **Modificado:** `templates/nucleo/dashboard.html`, `static/css/app.css` (saiu também
  uma regra antiga que reservava uma faixa vazia em cima de cada recado).

## 26/10/2026: aba "Comparativo" na versão atualizada

- **O que mudou, numa tela só.** A cópia atualizada da VPS ganhou o item "Comparativo"
  no menu, acima de "Versão anterior". A página traz os números das duas versões
  (testes automáticos de 977 para 2.863, testes de navegador de 8 para 282), as 14
  correções mais importantes com o antes e o agora (9 de impacto alto), as novidades, o design,
  a qualidade e a operação, o que veio do Gefferson nesses dias e os próximos
  passos. Cada item com tela leva à mesma tela nas duas versões.
- **Segurança só por alto.** A página fica aberta e a produção ainda roda a versão
  anterior, então os itens de segurança aparecem sem o detalhe técnico, que fica num
  relatório à parte.
- **Só na VPS.** Liga com `COMPARATIVO_VERSOES=1` na cópia atualizada. A produção e o
  desenvolvimento local não mudam.
- **Modificado:** `deploy/vps/comparador/` (`comparativo.py`, `urls_vps.py`,
  `settings_vps.py`, `templates/vps/comparativo.html`, `nova.js`, README),
  `apps/site/tests_comparativo.py`, README §10.

## 26/10/2026: comparação entre as versões sem senha

- **As duas cópias de teste abrem sem senha.** O item "Versão anterior/atualizada" do
  menu já abria a mesma tela na outra versão, mas lá pedia login de novo. Agora se
  entra direto, como `teste`, e a troca cai na mesma tela.
- **Tela que só existe numa das versões.** Na troca, ela sobe até a tela mais próxima
  que exista do outro lado (Pendências leva ao painel), com o aviso "Esta tela não
  existe nesta versão", em vez de um 404.
- **Só na VPS.** As duas cópias carregam uma configuração própria (`settings_vps.py`).
  A produção e o desenvolvimento local não mudam. Depois de "Sair", a entrada volta a
  pedir senha por 15 min, para testar outro usuário.
- **Modificado:** `deploy/vps/comparador/` (`acesso_livre.py`, `settings_vps.py`,
  README), `apps/site/tests_acesso_livre.py`, README §10.

## 26/10/2026: checkout da Loja, ajustes depois do CI

- **Botões do carrinho com 44 px também no mouse.** No redesenho, eles ficavam com
  36 px fora das telas de toque. Mas o monitor de toque do balcão nem sempre se
  anuncia como toque ao navegador, e a regra da casa (o teste de navegador do carrinho)
  pede 44 px em qualquer largura.
- **Soltar o produto em qualquer ponto do carrinho.** Arrastar um produto e soltar em
  cima do campo "Cliente" não o colocava no carrinho, porque o campo de texto ficava
  com o soltar. Durante o arraste, o painel inteiro passa a ser o alvo.
- **Testes de navegador no checkout novo.** Três testes ainda escolhiam a forma de
  pagamento no select antigo e agora usam os botões. O teste de arraste solta na lista
  do carrinho: o painel ficou mais alto que a janela do teste, e o Playwright rolava a
  página no meio do arraste, que então nem começava.
- **Modificado:** `static/css/app.css`, `apps/site/tests_operacao_e2e.py`.

## 26/10/2026: checkout da Loja redesenhado

- **Linha do carrinho arrumada.** O "×" de tirar o item ficava sozinho no canto
  direito, longe da quantidade e fora do alinhamento do nome. A linha agora segue o
  desenho dos checkouts open source (como o Medusa e o PDV do Odoo):
  - em cima, a miniatura do produto, o nome e o total da linha;
  - embaixo, o preço unitário ("R$ 12,00 cada") e, juntas no fim, a quantidade e uma
    lixeira.

  O "−" para no 1: antes, ele apagava a linha sem querer, e agora tirar é só com a
  lixeira. Em telas de toque os botões têm 44 px; no mouse, 36 px.
- **Forma de pagamento num toque.** Era um select que precisava ser aberto. Agora cada
  forma é um botão, com as mais usadas primeiro: Pix, dinheiro, débito, crédito,
  transferência e cortesia. Por baixo são rádios, então as setas do teclado e o leitor
  de tela funcionam.
- **Subtotal** aparece acima do desconto quando há desconto.
- **O aviso de estoque travado** ("para trocar o estoque, conclua a venda…") saiu do
  meio do carrinho e foi para junto do seletor de estoque, onde se tenta trocar.
- Conferido em 320, 390, 821 e 1440 px, sem rolagem lateral. Em 320 px, a miniatura
  sai para o preço caber.
- **Modificado:**
  - `templates/loja/pdv.html`;
  - `static/css/app.css`: bloco do carrinho da Loja, sem mexer no do Restaurante nem
    no da Lavanderia;
  - `apps/loja/views.py`: ordem das formas;
  - teste de navegador `apps/site/tests_navegacao_e2e.py`: escolhe a forma pelo botão.

## 26/10/2026: painel Contábil mais claro, comparado ao mês anterior e sem vazar no celular

- **DRE comparada com o mês anterior.** A tabela ganhou duas colunas:
  - "% receita": quanto cada linha pesa na receita bruta;
  - o mês anterior. Em janeiro, a comparação é com dezembro do ano anterior.

  Os indicadores dizem quanto variaram ("↑ 16,3% sobre setembro"). Com o cartão
  estreito, sai primeiro a coluna do mês anterior e depois a da receita, para a tabela
  caber.
- **Indicadores no padrão do CRM e com menos cor.** Receita, lucro bruto e despesas
  ficam na cor normal do texto. Só o resultado muda de cor pelo sinal, e no fluxo, o
  líquido e o projetado.
- **Gráficos em reais.** O eixo da cascata mostrava "60,000", no formato americano.
  Agora mostra "R$ 60 mil", e o balão traz o valor com centavos. A rosca ganhou uma
  legenda com o valor e a fatia de serviços e de mercadorias.
- **Fluxo de caixa:**
  - a ponte termina no projetado, e no celular vira extrato;
  - as contas em aberto que vencem no mês aparecem uma a uma; antes só o total entrava
    na ponte;
  - os movimentos viraram "Caixa dia a dia", com entradas, saídas e saldo acumulado.
    A lista anterior parava em 200 movimentos sem avisar, e um mês de restaurante e
    loja passa disso.
- **Celular:** a tabela de movimentos vazava para o lado em 390 px e cortava a coluna
  "Saída". Com o menu aberto em 821 px, a DRE saía da tela, porque o canvas do gráfico
  segurava a coluna. Conferido nas seis abas em 320, 390, 821 (menu aberto) e 1440 px.
- **Fila "A classificar" com ação.** Quem tem permissão no admin vê um botão em cada
  item, que abre o cadastro no admin:
  - "Mapear", nas categorias sem de-para;
  - "Classificar", nos lançamentos sem conta.

  A lista agora tem páginas, em vez de parar nos 50 primeiros. O aviso da DRE leva
  direto para essa aba.
- **A aba fica na URL.** Trocar o mês, recarregar a página ou voltar de "Fechar o mês"
  mantém a aba aberta, e as setas do teclado passam de uma aba para outra.
- **"Fechar o mês"** mostra se o mês já foi aplicado e quando.
- **Modificado:**
  - `templates/contabil/painel.html`;
  - `apps/contabil/views.py`: abas, comparação, fatias e paginação da fila;
  - `apps/contabil/relatorios.py`: `fluxo_diario`;
  - `static/js/graficos.js`: formato dos gráficos;
  - três testes novos em `apps/contabil/tests.py`.

## 26/10/2026: verificação de segurança verde e rodando na dev

- **A verificação de segurança passa a rodar a cada push da dev**, e não só na
  semanal. A primeira semanal na dev (segunda, 26/10) ficou vermelha por alarme falso,
  sem segredo nem falha de verdade:
  - o gitleaks leu o histórico inteiro e marcou 359 linhas, todas em arquivo de teste
    (senha de usuário fictício) ou no `.secrets.baseline` do detect-secrets (só hashes);
  - o bandit marcou os ícones SVG da Lavanderia e do Marketing, que saem de tabelas
    fixas do código, e a leitura do XML anexado, que já recusa DTD antes do parse. Marcou
    também um teste chamado `tests_servicos.py`, que o filtro de testes não pegava.
  - Com o bandit parado, o ruff de segurança e o `check --deploy` nem rodaram. Rodados à
    mão, passam.
- **Disparo manual:** o workflow também roda pelo botão "Run workflow" do Actions, com
  o histórico inteiro, como a semanal.
- **Modificado:** `.gitleaks.toml` (novo: regras padrão, fora os testes e o
  baseline), `.github/workflows/security.yml` (push da `dev`, `workflow_dispatch` e
  filtro `*/tests_*.py` no bandit), `# nosec` com o motivo em
  `apps/lavanderia/templatetags/pecas_lavanderia.py`,
  `apps/marketing/templatetags/canais_marketing.py` e `apps/nucleo/documentos_privados.py`.
- **O semgrep passou a bloquear.** Ele só gerava relatório, com a anotação "trocar
  para `--error` quando esses forem fechados". Os 38 alertas foram conferidos, e todos
  eram alarme falso:
  - 34 linhas de CSV: as células passam por `apps/nucleo/export.py`, que o semgrep não
    acompanha. Essa regra fica de fora;
  - a volta da Governança só aceita dois destinos fixos;
  - o formulário do "Minha reserva" tem o token CSRF;
  - o nome e o documento do funcionário são validados antes de gravar;
  - o webhook do WhatsApp só devolve o desafio com o token certo, em texto puro.

  Os quatro últimos levam `nosemgrep` na linha, com o motivo num comentário.
  (`.github/workflows/security.yml`, `apps/governanca/views.py`, `apps/nucleo/views.py`,
  `apps/comercial/views_whatsapp.py`, `apps/site/templates/site/reservas/minha_reserva.html`.)
- **Checklist de ativação e estado atual em dia (só documentação).** O checklist ainda
  dizia que o fiscal era stub, que o simulador de e-mail podia enviar e que NPS e Canais
  eram backlog. Agora traz:
  - o que o Spedy precisa (conta, chave, certificado A1, segredo do retorno e o teste
    no sandbox);
  - que a NFC-e depende da inscrição estadual;
  - o Channex;
  - o primeiro fechamento do Contábil com o contador.

  O estado atual ganhou a atualização de 26/10. O checklist do contador registra o
  regime (Lucro Presumido) e os provedores implementados.
  (`docs/Checklist_CRM_100.md`, `docs/ESTADO_ATUAL.md`, `docs/Checklist_contador.md`.)
- **Testes dos ícones passam também no Windows.** O `.gitattributes` só mantinha o
  Lucide em LF; os ícones do Tabler e o Chart.js saíam com CRLF no checkout do Windows, e
  o teste que compara o sha256 com o `origem.json` falhava só lá. Agora vale para todo o
  `static/vendor/`. (`.gitattributes`, README §13.)

## 25/10/2026: exportações e impressões conferidas

- **Os CSV abrem certo no Excel em português.** Os números saíam com ponto
  ("62983.20"), que o Excel brasileiro lê como texto: a coluna não soma, e "5.7" pode
  virar data. Agora saem com vírgula, data em dd/mm/aaaa e cabeçalho legível
  ("Quartos disponíveis", não `quartos_disponiveis`). Valia para o export do Contábil
  para o contador (resumo, lançamentos e plano de contas), fechamentos do dia, marketing,
  conciliação e boletim de ocupação (BOH).
- **A trilha de auditoria em CSV saía no horário de Greenwich**, 3 horas à frente.
  Agora sai no horário de Brasília, com a ação por extenso ("Estorno de pagamento"). O
  código técnico continua numa coluna própria, para a perícia filtrar.
- **Lançamentos do Contábil para o contador** ganharam a coluna Tipo (receita ou
  despesa), e o centro e a origem saem em palavras ("Fechamento do mês", não
  `fechamento`).
- **Valor negativo nos relatórios** não sai mais com apóstrofo ("'-R$ 50,00"). A
  proteção contra fórmula continua para texto digitado.
- **Período escolhido por datas:** o CSV e o "Período:" das telas de Auditoria,
  Conciliação, Escala e Marketing mostravam "personalizado". Agora mostram as datas.
- **Impressão do Contábil (Imprimir / PDF):**
  - a folha diz a competência e cada seção sai com título;
  - o DRE ocupa a largura toda e os gráficos cabem na página (o de receita por natureza
    invadia a seção seguinte);
  - o formulário "Fechar o mês" e os links de exportação não vão mais para o papel.
- **BOH:** "28 fichas sem preenchimento ficaram fora" (antes, "ficou").
- **Conferidos sem mudança:**
  - cupons de 80 mm da loja, do restaurante e da lavanderia;
  - kit de contingência e conferência da hospedagem;
  - relatórios em retrato e em paisagem;
  - relatório da escala, marketing, conciliação e BOH.
- **Modificado:** `apps/nucleo/export.py` (`celula`, novo, e `sanitizar_celula`),
  `apps/nucleo/periodos.py`, os exports em `apps/contabil`, `apps/auditoria`,
  `apps/conciliacao`, `apps/marketing`, `apps/reservas` e `apps/relatorios`,
  `templates/contabil/painel.html`, `templates/relatorios/relatorio.html` e
  `templates/reservas/boh.html`. Testes em `apps/nucleo/tests_export.py` (novo) e nos
  testes dos módulos. O teste de comentários de template deixou de ler as worktrees
  locais em `.codex-work`, que davam falha falsa só na máquina.

## 25/10/2026: NFS-e pelo Spedy e regime Lucro Presumido, vindos do original

- **O original passou a emitir NFS-e pelo Spedy** (commit `85e19bf` do Gefferson). O
  fiscal do fork tem outro desenho (referência gravada antes do envio, trava contra
  clique duplo, confirmação pelo provedor), então o Spedy foi reescrito nesse padrão em
  vez de entrar como veio:
  - a nota fica **Processando** até o retorno do Spedy ou a consulta, sem virar
    rejeitada por engano;
  - a referência do sistema vai como `integrationId`: reenviar depois de uma resposta
    perdida, ou corrigir uma rejeição de cadastro, atualiza a mesma nota, sem criar outra;
  - o retorno só é aceito com a **assinatura do Spedy** (HMAC com o segredo da conta,
    conforme a documentação deles). A versão original esperava um token no cabeçalho,
    que o Spedy não manda: todo retorno seria recusado;
  - um retorno atrasado de "na fila" não desfaz uma nota já autorizada. Nota de outro
    sistema da mesma conta é ignorada, sem erro;
  - o cancelamento no Spedy é assíncrono. O pedido entra na trilha de auditoria (quem,
    quando e por quê) já na hora, e a nota só vira Cancelada quando o Spedy confirma;
  - links de PDF e XML da nota, situação e pendências no painel Fiscal e em "Operação e
    integrações".
- **Regime confirmado: Lucro Presumido.** No "Fechar o mês" do Contábil, o campo "DAS /
  Simples" virou "Impostos s/ receita" (PIS, COFINS e ISS), e a conta 3.1.02.01 passou a
  "(-) Impostos sobre a receita". A categoria antiga troca de nome junto, para o próximo
  fechamento não criar uma segunda. O pró-labore ganhou a dica de que, pelo contrato, fica
  em R$ 0. Dados do emitente (CNPJ, inscrição municipal, IBGE de Itá) em `EMPRESA_*`.
- **Nada muda na operação agora:** o fiscal segue em modo de teste e o módulo inativo. Para
  ligar o Spedy: chave da API, segredo do retorno, certificado A1 no painel deles e ensaio
  no sandbox, como descreve `docs/Implementar_fiscal.md`.
- **Modificado:** `apps/fiscal/spedy.py` e `apps/fiscal/erros.py` (novos),
  `apps/fiscal/gateways.py`, `apps/fiscal/services.py`, `apps/fiscal/views.py`,
  `templates/fiscal/`, `apps/nucleo/integracoes.py`, `config/settings.py`,
  `apps/contabil/` (formulário, migrações `0009_conta_deducao_neutra` e
  `0011_merge_regime_presumido`), `templates/contabil/painel.html`,
  `aplicar_fechamento` e `docs/Implementar_fiscal.md`.
- **CI:** o teste da assinatura dos avisos do Channex falhava de vez em quando. O caso
  "carimbo 301 s no futuro" era montado com o segundo truncado; se o relógio virasse o
  segundo antes da conferência, a diferença caía para 300 s, dentro da tolerância, e o
  aviso passava. O teste agora para o relógio do webhook (`apps/canais/tests_fila.py`).

## 25/10/2026: varredura final do front (Contábil, Comercial e site)

- **Fechar o mês no Contábil grava o que foi digitado.** "12.500,00" chegava ao servidor
  como "12.500.00" (não é número) e a folha entrava como zero, sem aviso. Agora os
  quatro campos usam a máscara de R$ da casa. Valor inválido avisa no próprio formulário,
  sem apagar o que foi digitado e sem gravar nada. Mês fora de 1–12 não quebra mais.
- **Painel Contábil no padrão da casa:**
  - indicadores dois por linha no celular (antes, um por linha);
  - dinheiro que não parte entre o "R$" e o número;
  - plano de contas recuado pela profundidade (antes, só as contas do topo recuavam);
  - rótulos com o tamanho mínimo de leitura no toque;
  - dourado legível como texto;
  - "Baixar CSV" como botão secundário;
  - aviso de vazio na largura do cartão;
  - nota do plano atualizada para as contas fora da DRE.
- **Comercial:** a lista de quartos do lead não empurra mais a coluna para baixo ao
  carregar. Os 6 primeiros já nascem visíveis, em vez de esperar o JavaScript.
- **Site:** o peso Bold da fonte também é pré-carregado. A vitrine de quartos não muda
  mais de tamanho quando a fonte chega.
- **Como foi achado:** varredura completa de 415 telas em 5 larguras (320, 390, 821 com o
  menu aberto e 1440 aberto e recolhido), comparada com a de 24/10. Resultado: 38 melhoras,
  1.895 iguais e 4 pioras reais, as duas mexidas de layout acima, corrigidas aqui.
- **Modificado:** `apps/contabil/forms.py` (novo), `apps/contabil/views.py`,
  `templates/contabil/painel.html`, `templates/comercial/_painel_quartos.html` e
  `apps/site/templates/site/base.html`.

## 25/10/2026: Contábil do original integrado, sem contar nada duas vezes

- **Chegou a camada Contábil do original** (DRE, fluxo de caixa, plano de contas,
  fechamento mensal e export para o contador), com os ajustes que os fluxos deste fork
  pedem:
  - **o faturado não conta duas vezes:** quando a agência ou a empresa paga o título da
    hospedagem faturada, a DRE não soma a diária de novo — ela já entrou pela
    competência. O pagamento vai para uma conta fora da DRE ("recebimento de receita já
    reconhecida");
  - **a folha conta uma vez,** pelo fechamento do mês: a folha paga por conta recorrente
    e a categoria "Salários" viram pagamento de algo já reconhecido;
  - **a compra para o estoque não é custo:** "Insumos" vai para a conta do estoque, e o
    custo entra quando a mercadoria sai — venda (CMV), consumo interno (amenities,
    limpeza, cozinha) e perdas;
  - **entram o day pass** (ingressos pela data do turno) **e os descontos dados na conta
    do hóspede**, como abatimento da receita;
  - **a conta a receber avulsa tem categoria:** "Outras receitas" (evento, parceria),
    porque as receitas de hospedagem, loja, restaurante e lavanderia agora vêm sozinhas
    dos módulos;
  - **a DRE se atualiza sozinha pela rotina diária da casa** (`rotina_contabil`). Saiu o
    agendamento do GitHub que chamava a produção do original;
  - **os gráficos do painel aparecem também quando se chega pelo menu** (antes, só
    recarregando a página).
- **Modificado:**
  - merge de `b28bec2` (original) com a migração `nucleo/0062_merge_contabil`;
  - `apps/contabil/` (receivers, capturas, views, classificacao, models, migrações
    0009–0010, `management/commands/rotina_contabil.py` e `tests_integracao.py`);
  - `apps/nucleo/models/estoque.py` (`saidas_sem_venda_por_modulo`),
    `apps/nucleo/models/financeiro.py` (`db_default` nas colunas novas, migração 0063) e
    `apps/nucleo/management/commands/rotinas.py`;
  - `apps/daypass/services.py` (`faturamento_periodo`) e `apps/reservas/services.py`
    (`descontos_periodo`; "Hospedagem faturada" gerida pelo sistema);
  - `static/js/graficos.js` e `templates/contabil/painel.html`;
  - saiu `.github/workflows/cron-financeiro.yml`;
  - README e CLAUDE.md.

## 25/10/2026: plurais nas mensagens que saem para hóspede e equipe

- As últimas frases com "(s)" que alguém lê viraram singular ou plural de verdade:
  - o rascunho de resposta do Comercial ao hóspede: "Temos 1 quarto livre no período", "para 2 pessoas";
  - o aviso de campanha de e-mail enviada;
  - a solicitação do portal para o Restaurante ("Comanda #12 · 1 item");
  - o assunto do e-mail do kit de contingência;
  - o estoque de berços;
  - o aviso de colchão extra em falta ("na noite" ou "nas noites").
- **Modificado:** `apps/comercial/services.py`, `apps/comercial/views.py`, `apps/portal/services.py`,
  `apps/reservas/models.py`, `apps/reservas/services.py` e
  `apps/reservas/management/commands/enviar_kit_contingencia.py`, todos com `nucleo.textos.plural`.

## 25/10/2026: regressões da execução completa de navegador

- Os indicadores do Estoque mantêm duas colunas em telas estreitas, com o total
  monetário inteiro e o último contador ocupando a largura disponível. O respiro
  lateral permanece igual entre os cartões. Resumo por depósito e filtros fechados
  compartilham uma linha para manter os produtos próximos à primeira tela.
- Os formulários com texto livre do Estoque usam “Buscar”, inclusive os dois
  botões da Posição; o histórico de movimentos usa “Filtrar”. Os testes cobrem a
  busca sem JavaScript e conferem o selo atual do Comercial, o calendário sem
  altura excedente e a ação do estado vazio específico de contas abertas após a baixa.
- Acrescentada conferência dos indicadores com valor de milhões e fontes de
  16 e 20 px, preservando as verificações de filtros, baixa única e navegação.

## 25/10/2026: conclusão da varredura de interface e páginas públicas

- Estados vazios indicam o próximo passo e preservam o papel da pessoa ao limpar a
  busca. Configuração de quartos, FNRH, preços e cabeçalhos mantêm alinhamento e
  leitura. O mapa conserva a coluna do quarto e os meses durante a rolagem.
- A Manutenção destaca “Iniciar” em ordens abertas. Comercial e Marketing ganham
  filtros proporcionais, quartos disponíveis sem corte e orçamento com ação visível.
  Informações neutras deixam de competir com alertas que exigem ação.
- Relatórios distribuem melhor as colunas; o kardex usa duas colunas no celular.
  O PDV alinha busca e estoque e só pede para deslizar quando há categorias fora da
  área visível. NPS, cardápio, retornos e plurais seguem o padrão dos módulos.
- As três campanhas usam alvos de toque consistentes. Os CTAs das páginas de fundador
  usam dourado, a inauguração cabe em 320 px e a leitura da história fica alinhada.
  A política da lista usa o layout do site; seu conteúdo foi preservado e o link de
  privacidade de navegação tem rótulo próprio, pois trata de outra finalidade.
- O calendário deixa de esticar o cartão, os campos de data indicam “Selecione” e o
  quarto sem foto usa uma área menor. O comando `corrigir_icones_experiencias` corrige
  somente os cinco desenhos antigos, com simulação, auditoria e aplicação idempotente.
- Modificados os templates dos módulos, CSS compartilhado, páginas públicas, LPs e
  testes de navegador. As verificações cobrem relatórios, CSV/impressão, operações
  financeiras, cinco estados de largura/menu e preservação do conteúdo dos ícones.

## 25/10/2026: lotes, valores monetários, cobranças vencidas e auditoria

- O filtro de lotes oferece novamente “Com saldo” e mantém a seleção após filtrar.
  Recebimento, lotes e embalagens usam a navegação do Estoque. O cadastro de nota
  mostra a quantidade de anexos; indicadores e filtros respeitam a largura disponível.
- Estornos abrem com o valor preenchido em reais. Tarifas e dinheiro contado usam
  o mesmo widget, aceitando vírgula e decimal sem multiplicar valores por cem.
  O saldo a receber tem leitura neutra nos dois resumos da reserva.
- Cobranças vencidas aparecem como “Expirado” e deixam de oferecer envio de link
  ou Pix. O pagamento público destaca o vencimento; a confirmação de um pagamento
  já recebido continua válida. Cobranças sem prazo continuam compartilháveis.
- A trilha apresenta nomes, campos, datas e situações em português. Estruturas
  técnicas são resumidas na frase, preservando o detalhe bruto da auditoria.
- Modificados os forms/views do núcleo e Estoque, apresentação de Pagamentos e
  Auditoria, templates correspondentes e regressões de dinheiro e navegador.

## 25/10/2026: filtros, abas e indicadores com espaço para leitura

- As barras de filtro aproveitam a largura disponível, alinham campos e ações e
  preservam o ano nas datas. A Manutenção recupera a grade de filtros.
- O Comercial, o ciclo de limpeza e o resumo financeiro da reserva se reorganizam
  pela largura do conteúdo. Painéis laterais param na altura dos próprios dados.
- Abas deixam de esticar para preencher linhas vazias; indicadores mantêm duas
  colunas no celular e valores completos. Os números das listas permanecem à direita.
- Caixas de seleção ganham dimensão uniforme e se alinham à primeira linha do
  texto, com o rótulo oferecendo pelo menos 44 px de altura no toque. As três opções
  do produto ficam juntas, abaixo dos campos de preço.
- Links de ação ganham área de toque; filtros de seleção múltipla recuperam a forma
  de botão. Campos de URL usam o mesmo acabamento dos demais formulários.
- O menu mostra uma indicação discreta de continuação, que desaparece ao chegar
  ao fim. Voltar recebe seta consistente e títulos deixam de hifenizar palavras.
- Modificados `app.css`, o recorte público, `sidebar.js`, os templates de Produto,
  Movimentar, Vendas, convite NPS, checkout e pagamento, além das regressões de
  navegador em `tests_retomada_front_e2e.py`.

## 25/10/2026: varredura do front, parte 1 (selects, rodapé da porta, tabelas e `[hidden]`)

- **A seta voltou em todo `<select>` do sistema.** Ficha do hóspede (FNRH), modal de Nova
  reserva, Novo grupo, Caixa, Tabela de preços, filtro do cardápio do Restaurante,
  Day pass e relatório do colaborador mostravam caixas lisas, que a recepção lia como
  campo só de leitura. Eram telas que escreviam o fundo com o atalho `background`, e o
  atalho apaga o desenho da seta junto — o mesmo valia para os campos do pedido e do
  detalhe da comanda do Restaurante. De quebra, o `<select>` voltou a ter o respiro à
  direita (a seta ficava em cima do texto) e, quando a opção é mais longa que a coluna,
  termina em reticências em vez de partir no meio da letra: no modal de Novo grupo,
  "Particular (o hósped…" no lugar de "Particular (o hóspede pag".
- **No mapa de quartos, o dinheiro nunca mais encolhe.** Nos quartos com tarja ("SAÍDA
  HOJE") o saldo saía reticenciado — justamente onde a recepção precisa saber quanto o
  hóspede deve. Agora o rodapé da porta decide pelo espaço: quando as duas pontas não
  cabem lado a lado, a tarja fica na fileira de cima e o valor desce para a de baixo,
  por extenso e alinhado à direita. A altura mínima reserva as duas fileiras sem
  comprimir a data nem cortar o saldo na vertical. Vale na Visão geral e no mapa de
  Reservas, de 320 px ao monitor.
- **Tabela volta a ser tabela onde há largura.** Pickup, Ritmo e os dois relatórios de
  Governança desmontavam em cartões com o menu aberto e viravam tabela com o menu
  recolhido — a mesma tela, dois desenhos, porque o limiar (1200 px) caía bem no meio
  das duas larguras úteis. Com o limiar em 896 px os quatro relatórios ficam iguais nos
  dois estados (a lista do Pickup cai de 3,5 m para 35 cm de altura) e no celular
  continuam em cartão.
- **A semana da Escala volta a ter sete colunas** em largura de computador, em vez de
  quatro e a segunda fileira recomeçando na segunda-feira.
- **Turnos, Ausências e Trocas:** o formulário saiu da coluna lateral e virou um bloco
  "Novo turno" / "Nova ausência" / "Solicitar troca" recolhido acima da lista — aberto
  enquanto não há nenhum registro. A lista fica com a largura toda e volta a ser tabela
  no computador. A conciliação do painel de Pagamentos (três colunas curtas) também
  deixou de virar cartões, e a tabela de preço por quarto da Temporada volta a caber na
  tela: a página cai de 5,5 m para 2,9 m de altura.
- **Cartão escondido some de verdade.** Um `<section class="cartao" hidden>` aparecia
  vazio na tela, porque o componente trazia um `display` mais forte que o `[hidden]` do
  navegador. Corrigido na base, não caso a caso: valia para a conferência da embalagem
  no recebimento do Estoque e vale para qualquer cartão futuro.
- **Modificado:** `static/css/app.css` (seta, respiro e reticências do `<select>` nos
  blocos de modal/FNRH/BOH, Caixa, Restaurante (filtros e pedido/comanda), Day pass,
  relatório do colaborador e cartão
  elegante; rodapé da porta; `.cartao[hidden]`; limiar do modo cartão dos relatórios
  largos; sete colunas da grade da Escala), `static/css/base.css` (recorte público
  regerado), `templates/nucleo/tabela_precos.html`, `templates/nucleo/temporada_form.html`,
  `templates/escala/turnos.html`, `templates/escala/ausencias.html`,
  `templates/escala/trocas.html`, `templates/pagamentos/painel.html` e os testes de
  navegador `apps/site/tests_escala_uso_e2e.py`, `apps/site/tests_operacao_e2e.py` e
  `apps/site/tests_retomada_front_e2e.py` (setas, cálculo da embalagem e saldo completo
  em cinco configurações de largura e menu).

## 24/10/2026: Lavanderia redesenhada e plurais em português

- **Receber roupa virou um gesto.** Quem deixou, para quando fica pronta (chip "Hoje ·
  Amanhã · Em 2 dias") e o botão — o campo de data só aparece em "Outra data", porque o
  `<input type=date>` cru mostra `mm/dd/yyyy` no Chrome em inglês. A ordem abre em
  seguida com a grade da tabela de preços: um toque lança a peça, o serviço por quilo
  abre o campo de peso (1,5 kg, com os pesos de sempre em chip) e a cesta soma na hora,
  com o resumo na aba para quem está no celular. O recado da recepção ("mancha, não
  passar") fica na ordem e sai impresso com a roupa.
- **A produção é uma fila por etapa** (Recebida · Lavando · Pronta), com o próximo passo
  escrito no botão do próprio cartão: a lavadeira faz a fila andar no tablet sem abrir
  ordem nenhuma — e, depois de avançar, continua **na fila**, no mesmo filtro, em vez de
  cair na ordem a cada toque. Quem venceu o prazo sobe na frente e é o único com cápsula
  vermelha. No tablet, o bloco "Receber roupa" nasce recolhido: antes ele empurrava a
  fila um scroll inteiro abaixo da dobra e a lavadeira abria a tela sem ver trabalho.
- **Cada passo da ordem fica com a hora.** A trilha mostra "Recebida 20/10 12:12 ·
  Lavando 14:30 · Pronta 17:05 · Entregue —" em vez de inventar "Cumprido" e "Agora"
  onde devia haver horário (dois carimbos novos no banco).
- **Ordem vazia não anda nem é cobrada:** o botão do próximo passo fica apagado com
  "Lance ao menos uma peça" enquanto a cesta está vazia, e o servidor recusa — o que não
  foi contado não é cobrado.
- **Desconto só com a gerência, de verdade.** A tela já escondia o campo; agora o
  servidor recusa o desconto de quem não é gerência, e todo desconto fica na trilha de
  auditoria, como todo ajuste de dinheiro da casa. A forma de cobrança também é
  conferida no servidor: um valor inventado no lugar de "caixa" ou "conta do quarto"
  lançava no fólio do hóspede por fora da permissão do Reservas.
- **Peça é contada, quilo é pesado:** meia camisa não entra mais (cobrava metade e o
  cartão dizia "0 peças"), e um peso absurdo recebe "informe um número" em vez de uma
  página de erro.
- **Rouparia:** cada item mostra a barra da situação (limpa · em uso · suja · lavando) e
  um toque no número já propõe o movimento que sai dele — agora com pista visual no
  toque, onde não existe hover. O lote move várias linhas numa transação só (tudo ou
  nada): se alguma caixinha marcada saiu da lista, o lote é recusado em vez de mover as
  outras calado, e a recusa volta **com as linhas ainda marcadas**. No celular a barra
  do lote fica presa ao pé da tela (antes nascia 85 px abaixo da dobra, sem como rolar
  até ela) e a caixa de marcar passou a ter 44 px de alvo.
- **Extrato do enxoval** (tela nova): cada movimento com quem, quando e por quê — nada
  se apaga. Período em chip, como no histórico; "Quem" mostra o nome da pessoa, não o
  login.
- **Histórico:** os números do topo e o rodapé do quadro somam o período inteiro por
  agregação no banco. Antes a tela percorria todas as ordens e todos os itens em memória
  a cada carregamento (com o chip "Tudo", o histórico completo) e o rodapé não fechava
  com a página 2.
- **Tabela de preços:** "Editar" volta com o preço preenchido (o campo nascia vazio
  porque o valor ia localizado para um `input type=number`, e o preço era obrigatório —
  quem só queria renomear redigitava de cabeça). Cada serviço tem **ícone**: 36 traçados
  próprios, do Tabler (MIT) e do Lucide (ISC), com licença e sha256 registrados e
  conferidos por teste; a escolha pelo desenho agora mora dentro do campo "Ícone",
  agrupada por tipo, acima do botão de salvar — e sem os ícones de estado do enxoval,
  que não são serviço.
- **Correções de interface que valem para o sistema inteiro:** a seta do `<select>`
  voltou em toda tela elegante (`.eleg`) — Lavanderia, Canais, Conciliação, Estoque e
  Comercial mostravam caixas sem seta, porque o atalho `background` apagava o desenho;
  a moldura quebrada do segmentado do balcão (meia caixa com as pontas enroladas) sumiu
  na Lavanderia e na Loja; a faixa vermelha do cartão atrasado não desaparece mais
  quando o dedo mira o cartão; e rótulo de KPI em maiúsculas não se hifeniza
  ("PARA ENTRE-GAR HOJE" a 390 px).
- **Plural em português:** "2 items" nas comandas do Restaurante e "contagemns" no
  inventário do Estoque viraram "2 itens" e "2 contagens". O `|pluralize` do Django só
  acrescenta "s", o que erra toda palavra terminada em m, l, r, z, "ão" ou "ês" — o
  teste novo `PluralEmPortuguesTests` varre todos os templates e barra o caso.
- **Modificado:** `apps/lavanderia/` (`models.py` + migrações `0003`/`0004` — ícone,
  observação, alvo e carimbos de produção; `services.py` — validação por unidade, teto
  da quantidade, destino conferido, trilha do desconto, carimbos, `mover_lote`;
  `views.py` — gate do desconto e do destino, volta para a fila, KPIs do histórico por
  agregação, chips do extrato, lote tudo-ou-nada; `icones.py` e
  `templatetags/pecas_lavanderia.py`, novos; `urls.py`), `templates/lavanderia/`
  (`painel.html`, `ordem.html`, `historico.html`, `servicos.html`, `rouparia.html`,
  `extrato.html` novo e os parciais `cobranca.html`, `fila_cartao.html`, `itens.html`,
  `nav.html`, `observacao_status.html`), `static/css/app.css` (bloco da Lavanderia,
  `background-color` no campo `.eleg`, `.pdv-loja .pdv-seg` sem raio, hover do cartão
  atrasado, `hyphens` do letreiro), `static/vendor/tabler/` e `static/vendor/lucide/`
  (traçados com LICENSE e `origem.json`), `apps/auditoria/formatacao.py` (rótulo do
  desconto), `templates/restaurante/comandas.html`, `templates/estoque/inventarios.html`
  e os testes: `apps/lavanderia/tests.py`, `tests_producao.py`, `tests_tela.py`,
  `tests_icones.py` (novos), `apps/site/tests_lavanderia_e2e.py` (novo),
  `apps/nucleo/tests_design.py` (`PluralEmPortuguesTests` + alvo de toque da caixinha do
  lote), `apps/nucleo/tests_operacionais.py` e `apps/site/tests_operacao_e2e.py`.
  Documentação: `README.md`, `docs/MODULOS_E_FLUXOS.md` (A.10) e `docs/ARQUITETURA.md`.

## 24/10/2026: Escala mais sóbria

- Os cartões do último turno da grade (Tarde) perdiam a borda de baixo — e o de domingo, o
  canto arredondado — porque herdavam regras do modo tabela; agora todo cartão tem as
  quatro bordas e o mesmo raio.
- Validação sem as quatro faixas pintadas (vermelho, verde, azul, amarelo): fundo neutro,
  uma faixa fina na cor do aviso e o ícone colorido; o texto volta à cor normal.
- Nomes para arrastar como etiquetas retas com a inicial num círculo (não mais pílulas) e,
  nos cartões de cada dia, os nomes como linhas de lista alinhadas, sem sombra de botão.
- **Modificado:** `static/css/app.css` (bloco de cartões da `.escala-grade`, `.escala-al`,
  `.escala-roster .rpill`, `.rpill-ini`) e `templates/escala/grade.html` (inicial no nome).

## 24/10/2026: ajustes de interface para a abertura (sidebar, Pendências, Marketing, Estoque)

- Topo do menu: o logotipo fica no eixo da sidebar (estava 18 px à esquerda) e desce um
  pouco, com mais respiro em cima (24 px) do que embaixo (18 px); o topo passou de 116 para
  128 px. No celular, a gaveta do menu cortava o "POUSADA" do logotipo — agora ele aparece
  inteiro. No menu recolhido, o símbolo cresce para acompanhar a coluna.
- O ponto de alerta no avatar (MFA desligada) aparece inteiro, com um anel separando-o do
  dourado — antes o próprio avatar o recortava em meia-lua — e em coral, legível no azul.
- Pendências com um filtro só: a origem num seletor com a contagem de cada área (escolher já
  filtra) e a situação nas abas da casa, com "Precisa de atenção" logo depois de "Todas".
  Saíram os dois selects com "Aplicar filtros" e as duas fileiras de pílulas que faziam a
  mesma coisa. Na lista, a situação é bolinha colorida + texto; o urgente leva a palavra
  "Urgente", sem cápsula em cada linha.
- Marketing: "+ Nova ideia" centrado no quadro tracejado e sem sublinhado; no Relatório, os
  indicadores ficam direto sobre a seção (sumiu a faixa bege atrás dos cartões) e, sem teto
  definido, a nota diz "Sem teto para comparar" em vez de "— do teto".
- Estoque: os indicadores menores no celular e no tablet ganharam recuo do lado da faixa
  colorida — "Abaixo do mínimo" encostava nela.
- **Modificado:** `static/css/app.css` (`--sidebar-topo-h` 128/96 px, `.marca-full` pelo
  token, `.marca-icone` 52 px, ponto de MFA, `.mk-nova-ideia`, `.mk-kpis.kpis`, bloco de
  Pendências, recuo dos `.est-kpis`), `static/css/base.css` (regerado),
  `templates/nucleo/pendencias.html`, `templates/nucleo/partials/pendencias_resultados.html`,
  `apps/nucleo/views_pendencias.py` (totais e ordem das situações), `static/js/pendencias.js`
  (seletor aplica ao escolher; a atualização automática não redesenha o filtro em uso),
  `templates/marketing/relatorio.html` e `docs/ARQUITETURA.md`.

## 23/10/2026: cantos das caixas, canais com ícone e verba alinhada

- O quadrado branco no cantinho das tabelas arredondadas (Pessoas, Reservas, Estoque e
  todo módulo com listagem) sumiu. Eram duas coisas: o invólucro de rolagem pintava
  "cortinas" da cor da superfície atrás da tabela, visíveis só fora dos cantos; e o
  cabeçalho, a coluna fixa e a linha em hover não seguiam o raio da moldura. Correção
  nas classes-base (`.tabela`/`.tabela-rol`), vale para o sistema inteiro — inclusive a
  grade da Escala em modo cartão e a tabela vazia (a célula única leva os quatro cantos
  e não realça no hover). Varredura por pixel em 29 telas, com os menus suspensos
  abertos e hover na primeira e na última linha: nenhum canto vazando.
- Marketing: os canais aparecem como ícone (Instagram, Meta, Google, WhatsApp, E-mail…)
  no filtro, nos cartões do quadro, na ficha e nas entregas, em vez de nomes em caixa
  alta — o cartão que quebrava cinco canais em três linhas mostra uma fileira.
  Monocromático, na cor do texto. O nome segue no `aria-label` e na dica.
- Marketing: Reservado, Gasto e Teto do mês na mesma linha de base; o teto passou a ser
  um valor como os outros, com "Alterar" para a gerência abrir o campo. "Gasta" virou
  "Gasto", concordando com "Reservado".
- **Modificado:** `static/css/app.css` (cantos da tabela por `--raio-tabela`/`--raio-celula`,
  hover na célula, invólucro sem fundo, `.ico-canal`, `.mk-canal`, `.mk-teto`),
  `apps/marketing/templatetags/canais_marketing.py` (novo, `{% icone_canal %}`; traçados
  do Simple Icons, CC0, e do Lucide, ISC), `templates/marketing/quadro.html`,
  `_canais.html`, `_ficha_drawer.html`, `_entrega_linha.html`,
  `apps/nucleo/tests_design.py` (`CantosDasCaixasTests`) e `apps/marketing/tests.py`.

## 23/10/2026: topo do trilho em coluna

- Com o menu recolhido, o topo deixou de ser um símbolo pequeno com o botão colado ao
  lado e uns 60 px vazios até o fio. Agora é uma coluna centrada: símbolo maior (44 px),
  botão de expandir embaixo dele e o fio. No tablet (alvo de 44 px) o símbolo encolhe
  um pouco para manter o respiro até o botão.
- O botão de recolher não desliza mais entre o canto (menu aberto) e o centro do trilho:
  some de onde está e surge já no destino, quando a largura terminou de andar — sem
  diagonal nos dois sentidos. Sob `prefers-reduced-motion` a troca é imediata.
- **Modificado:** `static/css/app.css` (símbolo e botão do topo medidos pelos tokens
  `--sidebar-topo-h`/`--alvo`, `.menu-alternando`, keyframes `botao-recolher-surge`; o
  bloco "botão no canto" do fim do arquivo foi absorvido pela regra base),
  `templates/base.html` (`alternarSidebar()` marca a troca por 400 ms),
  `apps/nucleo/tests_design.py` (o botão não transita `top`/`right`; a animação e a altura do link da marca usam os
  tokens) e `apps/site/tests_sidebar_e2e.py` (quadro a quadro, o botão só é visto nas
  duas alturas de repouso; no trilho, símbolo e botão centrados e com respiro).

## 23/10/2026: tabelas, agenda de Marketing e operação da comanda

- Listagens e relatórios adaptam os campos à largura disponível, inclusive no
  tablet com menu aberto. Valores monetários permanecem juntos na tela e na
  impressão; relatórios amplos mantêm cabeçalho repetido e exportação CSV.
- Escala apresenta os dias por turno quando a matriz não cabe, preservando
  atribuições, horas extras, banco de horas e ações de toque. Os rótulos e as
  136 declarações de fonte em pixels examinadas passam a acompanhar a fonte do
  usuário; Funcionários filtra setores por chips com estado e teclado.
- Marketing mostra cinco grupos: Planejamento, Aprovação, Produção, No ar e
  Encerradas. As sete etapas internas, condições de avanço e aprovações continuam
  preservadas. Cada cartão informa a subetapa e o próximo passo.
- Entregas podem ser avulsas ou vinculadas explicitamente a uma campanha. Filtros
  de vínculo e canal, agenda semanal e ações de produção mantêm o contexto após
  editar. Mês e ano continuam disponíveis. A migração aditiva `0011` torna a
  campanha opcional; versões e travas protegem edições e vínculos concorrentes.
- Comanda no celular organiza Pedidos e Cardápio em painéis, reúne os dados de
  cada pedido e mantém total e fechamento alcançáveis. Não há rolagem interna
  escondendo pedidos. Vínculo com estadia, transferência, cancelamento, descontos
  e permissões fiscais continuam fazendo parte dos fluxos existentes.
- Quantidades deixam de expor zeros decimais artificiais: cinco unidades aparecem
  como `5 un`, e meio quilo como `0,5 kg`, também nas mensagens de saldo insuficiente.
  A precisão do estoque e dos valores monetários permanece preservada.
- A revisão dos temas do relatório corrigiu resíduos na prioridade e nos
  formulários da Manutenção, no texto do Inventário e na altura dos indicadores
  de Estoque. Categorias longas cabem nos cartões, e os indicadores do Kardex
  mantêm cifras completas. As abas foram conferidas nas 15 páginas do módulo,
  em cinco estados de largura/menu. Os testes incluem listas preenchidas, ações persistidas, impressão,
  mudança de fonte, concorrência e os cinco estados de largura/menu.

## 23/10/2026: revisão da rodada de interface (trilho, abas, avisos)

- Os grupos do menu deixaram de ser colapsáveis: são categorias fixas (título + itens)
  em todos os estados. Com os grupos fechados o trilho virava uma coluna de setas sem
  ícone, e colapsar grupo dentro de um menu que já recolhe era colapso dentro de
  colapso. O menu volta a mostrar o ícone de todos os módulos sempre.
- Quem está sem verificação em duas etapas vê de novo o aviso: um ponto de alerta no
  avatar, com o motivo no título do link — a cápsula "MFA off" não volta.
- O contador vermelho de "Precisa de atenção" (painel e Governança) voltou a ter o
  número claro; os outros contadores de seção seguem como número solto, sem pílula.
- Abas de módulo que quebram linha: o fio passou a pertencer a cada aba, então o
  sublinhado dourado encosta no fio da própria aba em qualquer linha; abaixo de 30 rem
  de largura útil as abas ficam mais compactas (Estoque a 390 px: 3 linhas em vez de 4).
  O Estoque abre em **Posição**; Notas, Compras e Lotes vêm depois do fluxo principal.
- A página "Nova reserva" (e o modal) não abre mais a lista de hóspedes por cima dos
  campos ao carregar: a lista aparece ao clicar, digitar ou usar ↓.
- O grupo de menu "Financeiro" dos módulos (Pagamentos Online, Fiscal) passou a
  "Pagamentos e fiscal": não há mais dois grupos com o mesmo nome.
- Filtro clicável (`.filtro-chip`) volta a ter forma de cápsula, distinta da aba de
  navegação. Relatórios: colunas numéricas com largura natural (a primeira coluna
  não engole mais toda a sobra). Portal e pagamento ganharam o piso de 12 px de
  rótulo no toque (`base.css` regenerado).
- Rodapé do menu de volta em linha (avatar, nome e Sair na mesma altura) com o menu
  aberto e na gaveta; só o trilho empilha o Sair. O botão de recolher fica no canto
  superior direito nos dois estados e anda em linha reta ao recolher (antes ia em
  diagonal para baixo do símbolo).
- Lotes e validade: a frase de apoio abaixo do título saiu (deslocava a barra de seções).
- Faixa colorida de cartão (funil, cartão de lead, "Precisa de atenção", fila da
  Governança, comandas, recados) deixou de ser borda grossa, que afinava no canto e
  parecia gradiente vazando: virou sombra interna, que acompanha o raio.
- Escala: chips da grade redesenhados (etiqueta discreta, nome com reticências, "+" e
  "×" redondos e centrados, 44 px no toque; violação = faixa interna colorida). Hora
  extra e banco de horas ganharam um cartão próprio embaixo do chip, com tipo, horário
  e total; o resumo semanal de horas extras virou cartão, fora da lista de avisos.
- Estoque: a barra de seções vem logo abaixo do nome do módulo e antes do título da
  tela, em todas as 15 telas — ela nasce sempre na mesma altura e não salta ao trocar
  de aba (antes variava 39 px no computador e 129 px no celular). O subtítulo das
  telas de nota fica abaixo da barra e o sobre-título é "Vendas & Estoque" em todas.
- Marketing abre no quadro de campanhas (Entregas vira a segunda aba) e, no celular,
  o quadro vira lista por fase em vez de sete colunas rolando de lado.
- Restaurante no celular: barra fixa no pé com o total e "Ver e fechar"; vincular
  estadia, transferir e cancelar ficam dobrados em "Mais ações"; o aviso da NFC-e só
  aparece para a gerência (o garçom não decide isso). O painel formata o saldo das
  saídas vencidas como dinheiro (R$ 10.892,40).
- **Modificado:** `templates/base.html` (grupos do menu como `<div>`, bootstrap só da
  rolagem, rodapé, sinal de MFA), `static/js/sidebar.js`, `static/css/app.css` (blocos
  "Revisão pós-rodada 1", "Faixas sem vazar", chips e cartões da Escala, abas, rodapé,
  botão de recolher), `static/css/base.css` + `apps/nucleo/css_publico.txt`,
  `apps/nucleo/modulos.py`, `apps/nucleo/views.py` (saldo formatado),
  `apps/escala/services.py` + `templates/escala/partials/grade_conteudo.html`,
  `templates/componentes/combo_pessoa.html` e `combo_quarto.html`, as 15 telas de
  `templates/estoque/` + `partials/nav.html`, `templates/marketing/_tabs.html`,
  `templates/restaurante/comanda.html`, `templates/loja/pdv.html`,
  `templates/relatorios/relatorio.html`, `templates/nucleo/dashboard.html`,
  `templates/governanca/visao.html`; testes E2E do shell e da sidebar sem o passo de
  abrir grupo (`apps/site/tests_auditoria_shell_e2e.py`, `apps/site/tests_e2e.py`).

## 23/10/2026: restaurante, entregas de Marketing e pendências operacionais

- Comandas e pedidos têm identidade persistida: reenviar a mesma abertura ou
  inclusão não duplica consumo. O portal usa a disponibilidade de receitas e
  lotes válidos. Cancelar exige os acessos do Restaurante e da gerência.
- A comanda atualiza saldos sem recarregar, filtra o cardápio por categoria e
  disponibilidade, protege pedidos não salvos e mostra o total após desconto.
  Desconto integral fecha sem recebimento fictício; estornos aparecem no histórico
  e cupom. Relatórios distinguem a data da venda da data do movimento financeiro.
- Marketing abre em **Entregas**, com impressos, anúncios, posts e landing pages
  separados por tipo e situação. Cada entrega pode apontar para material e LP
  existentes; conclusão registra autor/data e edição desatualizada é recusada.
  Peças antigas ficam em **Não classificado**, preservando seus dados.
- **Pendências** reúne ações das áreas autorizadas, com filtros e atualização
  automática. O número da Governança abre os serviços aguardando início;
  andamento e inspeção têm filtros próprios. Consultar a central não executa
  rotinas nem altera os registros de origem.
- Os [manuais operacionais](docs/README.md) explicam esses fluxos e os limites
  ainda existentes, incluindo pagamento misto e divisão de conta no Restaurante.

## 23/10/2026: notas de entrada e ajustes de interface

- A nota reúne fornecedor, número, série, emissão e itens previstos. Cadastrar
  o documento preserva a previsão; o estoque e o custo mudam ao receber os itens.
- Cada entrega informa quantidade, local e lote, mantém o saldo pendente e liga
  o movimento à nota no kardex. Reenvios não duplicam a confirmação; duas abas
  precisam conferir a versão atual antes de registrar uma nova parcela.
- A identificação do documento evita notas repetidas. PDF, PNG, JPG e XML ficam
  privados, acessíveis apenas a usuários autorizados no Estoque. Os anexos são
  arquivados sem importação automática ou consulta fiscal externa.
- O [manual de compras](docs/ESTOQUE_COMPRAS.md) diferencia notas e recebimentos
  avulsos e mantém a conferência financeira no fluxo próprio. A migração
  `nucleo.0061_notas_entrada` acrescenta cinco modelos, sem reescrever o kardex.
- Campos de RH se reorganizam pela largura disponível, inclusive no cadastro
  e na edição do funcionário; os cartões do NPS mantêm espaço entre as seções.
- O formulário de Nova ideia fica centralizado no desktop. No celular, mantém
  campos e ações acessíveis; tabelas de notas se apresentam como cartões completos.

## 23/10/2026: interface consistente e fluxos conferidos em uso real

- Menus internos ficam estáveis durante a navegação, sem a duplicação da
  Governança. Transições, histórico, busca por Ctrl/Cmd+K e avisos de alterações
  pendentes funcionam juntos; gráficos reaparecem ao voltar pelo histórico.
- Voltar durante uma troca de página conserva a rolagem restaurada; a
  navegação anterior não desloca mais a página para o topo ao terminar.
- Reservas, manutenção, financeiro, pagamentos, NPS e cadastros apresentam
  registros legíveis no celular. Ações da reserva têm grupos claros, foco por
  teclado e fechamento previsível. Filtros de caixa e períodos ocupam menos espaço.
- A tabela de preços permite filtrar ala/quarto sem perder os demais valores;
  erros em campos ocultos revelam o quarto afetado. Gráficos usam biblioteca local.
- Manutenção aceita documentos privados PDF, PNG, JPG e XML, inclusive depois
  de concluir a OS. Histórico, busca por nota fiscal e indicação do bloqueio atual
  ajudam a localizar o serviço; anexos inválidos não concluem a OS parcialmente.
- Contas resistem a baixas simultâneas sem duplicar o lançamento. Importações de
  cartão repetidas não duplicam transações; liquidação valida valor líquido,
  taxa e data. Movimentar o caixa mantém o módulo que estava selecionado.
- Cadastros de funcionário e acesso são gravados juntos; login duplicado não
  deixa ficha parcial. Escala recusa valores inválidos, decisões desatualizadas
  e conflitos de ausência; corrige o travamento mútuo entre solicitações e
  aprovações simultâneas.
- A [revisão de 23/10](docs/REVISAO_USABILIDADE_2026-10-23.md) registra a matriz
  de 37 telas em quatro larguras, os fluxos exercitados e os limites dos testes.

### Chegadas, saídas e saldos no Painel da recepção

- Os seis indicadores formam linhas completas de dois, três ou seis cartões,
  conforme a largura, sem deixar um cartão isolado no desktop.
- As listas do dia aparecem antes dos gráficos, com quarto, hóspede, situação,
  saldo e atalhos de check-in/check-out para a etapa existente da reserva.
- Chegadas sem conta mostram a previsão de diárias e taxas descontando o sinal;
  contas abertas mostram o saldo atual. Créditos, contas ausentes e cobranças de
  grupo são identificados sem confundir diárias do grupo com consumos do quarto.
- As listas e os totais usam os mesmos critérios de hospedagem e deixam Day Use
  no seu fluxo próprio. As ações mantêm as verificações de documentos, limpeza,
  conta e consumos pendentes. O layout se adapta ao celular e aos nomes longos.

## 23/10/2026: navegação estável, categorias ilustradas e Marketing consistente

- O menu lateral conserva a posição ao trocar de página, recarregar e voltar.
  A abertura e o recolhimento mantêm ícones alinhados, inclusive com barras de
  rolagem clássicas e telas de toque. Indicadores têm números centralizados,
  espaço nas bordas e contagem completa para leitores de tela.
- O histórico troca só o conteúdo da página, preservando o funcionamento do
  menu e da gaveta. Ao sair da largura de celular, a gaveta libera foco e rolagem.
- Os filtros de categoria da Loja mostram miniícones de bebidas, alimentos e
  outros grupos, usando as mesmas ilustrações locais do catálogo.
- As quatro telas de Marketing compartilham cabeçalho, largura e ação de criar
  campanha. Os períodos selecionados ficam identificados e as ações de exportar
  e imprimir seguem o padrão dos demais módulos.

## 22/10/2026: catálogo com ícones e escolha visual no cadastro

- Loja, Restaurante e lista de produtos compartilham ilustrações por nome e
  categoria. O cadastro permite escolher outro ícone e mostra a prévia ao editar.
- O reconhecimento diferencia refrigerantes, água com ou sem gás, café, leite,
  lanches, pratos, doces e outros grupos. Nome, preço e disponibilidade continuam
  visíveis; a escolha do ícone é preservada se o formulário tiver erro.
- Os 27 SVGs Lucide ficam no próprio aplicativo, com origem, hashes e licenças
  ISC/MIT preservadas. Não são fotos ou logotipos oficiais de marcas.

## 22/10/2026: quartos e preços validados antes de salvar

- O cadastro de quarto novo abre a configuração de camas. A edição confere
  quarto, camas, vitrine, descritivo e tarifas antes de gravar qualquer parte.
- A tabela de preços e as temporadas distinguem campo ausente, campo vazio e
  valor inválido. Uma falha mantém os preços anteriores e os dados digitados.
- Percentuais aceitam duas casas decimais sem perder precisão na fração salva.
  Valores excessivos, negativos, não finitos e horários inválidos são recusados.
- Em telas estreitas, preços aparecem por quarto e temporada, com os valores
  identificados e visíveis; os avisos de erro cabem no formulário.
- A central exige o monitor de Canais quando esse módulo está ativo.

## 22/10/2026: compras por embalagem, lotes e ingredientes dos pratos

- O recebimento converte embalagens para a unidade base e conserva a conversão
  usada na compra. A prévia mostra produto, embalagem, quantidade e custo total.
- Perecíveis têm lote, validade, contagem e correção de identificação com autoria.
  Lotes vencidos e saldo antigo ainda não identificado ficam fora da venda.
- Loja e Restaurante baixam ingredientes pela ficha técnica; o cancelamento
  usa a baixa original, mesmo após editar a ficha. Descarte após preparo é perda.
- Reenvios, alterações concorrentes, valores fora do limite e permissões têm
  verificações próprias. Formulários conservam os dados após erro; títulos e
  códigos longos cabem no celular.
- O [manual de compras](docs/ESTOQUE_COMPRAS.md) define o controle auxiliar de
  solicitações e aprovações no Livro de ocorrências e a conferência no Financeiro.

## 22/10/2026: canais de venda preparados para configuração e homologação

- Canais tem conexão por ambiente, responsável, categorias e unidades físicas,
  limite de venda, margem de segurança e prévia de disponibilidade.
- Reservas recebidas ficam numa fila durável. Novas reservas, alterações e
  cancelamentos compatíveis usam as travas do PMS; divergências ficam para
  conferência, sem registrar pagamento ou consentimento comercial automaticamente.
- Alterações da operação alimentam a fila de publicação. Notificações exigem
  assinatura, envios interrompidos são retomados e falhas têm espera progressiva.
  Fechamento confirmado é obrigatório antes de desligar uma conexão publicada.
- Telas e formulários foram conferidos em seis larguras; nomes longos permanecem
  dentro das fichas e tabelas. Erros de validação preservam o preenchimento.
- Credenciais, contratação e homologação reais permanecem pendentes; os ensaios
  automatizados usam respostas fictícias. A conexão inicia desativada.

## 22/10/2026: textos contidos nos cartões e contagem utilizável no celular

- O aviso de limpeza dispensada quebra dentro da porta do quarto; os cartões
  da governança se ajustam ao espaço disponível. A lista em tablet mantém
  a altura necessária para as informações e ações de cada quarto.
- O inventário mostra produto, saldo, campo de contagem e diferença juntos
  no celular. Erros preservam o valor digitado e o filtro da lista.
- A tela Safrapay distingue configuração local de homologação. A exportação
  de exemplos não cria cobranças, grava arquivos nem aciona o gateway ativo.
- Regressões de navegador verificam os limites reais dos textos em seis
  larguras, incluindo avisos, campos e detalhes técnicos expandidos.

## 22/10/2026: Day Pass por turno e formulários que preservam o preenchimento

- Visitas às áreas comuns têm agenda, lotação por pessoa, regra explícita para
  hóspedes, ingresso, controle nominal de entrada/saída e comanda do grupo.
  A última vaga e os recebimentos são protegidos contra operações simultâneas.
  Sem horários, valores e capacidade definidos, a agenda pública permanece fechada.
- Erros de validação e conexão mantêm campos, seleções e arquivos. Modais só
  fecham quando a ação é confirmada; valores em reais permanecem corretos no reenvio.
  No site, indisponibilidade e edição da revisão preservam os contatos informados.
- Contatos públicos dependem de conferência; selos de escassez sem cálculo real
  foram removidos. A comparação com OCA/vertical-hotel está documentada com fontes.
- Regressões de navegador incluem seis larguras, cartão recusado, arquivo inválido,
  resposta a ocorrência já resolvida e o ciclo completo de Day Pass.

## 22/10/2026: correções operacionais e preparação das integrações

- Reservas, contas, consumos, estoque e rotinas sensíveis revalidam o estado sob
  trava; concorrência não pode duplicar recebimentos, devoluções ou reservas.
- Escala considera virada de data e descanso configurável. NPS tem convite,
  consentimento, resposta e acompanhamento. FNRH diferencia nacionalidade de
  residência e prepara o ciclo completo de atualizações e saída.
- Fiscal e pagamentos têm adaptadores, configuração verificável e ensaios
  registrados. Credenciais e homologação externas ainda são necessárias.
- Backup automático passa a usar destino persistente; restauração isolada
  conferiu dez tabelas e os totais de caixa, estoque e contas da instalação VPS.
  Cópia externa, monitores e destinatários do kit aguardam configuração.

## 22/10/2026: busca e formulários centralizados em telas ultrawide

- A busca global acompanha o centro da área útil com o menu aberto ou recolhido.
- MFA, cadastros, edição de quartos e formulários de operação agrupam título,
  campos e ações numa coluna central com largura de leitura adequada.
- Conferência visual em 38 telas, 117 medições de layout e regressão de navegador
  com 40 combinações de largura, formulário e estado do menu.
- O teste de limite do webhook usa uma janela de tempo controlada e também
  confirma a renovação do limite, evitando falha aleatória na virada do minuto.

## 22/10/2026: credenciais fora da trilha de auditoria

- A ativação e as alterações de MFA continuam auditadas, sem copiar segredos ou
  códigos de recuperação. A proteção também cobre detalhes explícitos e aninhados.
- CSV, tela da auditoria, descrições e administração ocultam credenciais antigas
  para todos os perfis. A migração 0052 saneia o conteúdo legado preservando os
  eventos, sua autoria e suas datas.
- Reteste do achado OP01 e testes de ativação real, perfis, administração,
  registros explícitos e migração idempotente.

## 22/10/2026: mais espaço, botões simples e Conciliação alinhada

**O que melhorou**

- Cabeçalhos, indicadores e painéis têm separação consistente, inclusive na
  captação, nos formulários e no PDV.
- Botões principais usam fundo escuro uniforme; secundários têm borda discreta.
  Foco e áreas de interação foram preservados.
- Os importadores da Conciliação ficam alinhados, mesmo com nomes longos de
  arquivo, e se adaptam ao celular. O carrinho do PDV destaca o destino do arraste.
- Site, campanhas e CRM usam instruções e confirmações mais diretas.

**O que foi modificado**

- Estilos e templates compartilhados; textos da interface e metadados de campos.
  As seis migrations não alteram o esquema do banco.
- Suíte completa: 1.858 testes aprovados, incluindo 65 de navegador, sem pulos.
  Inspeção adicional de 35 telas em duas larguras, sem rolagem horizontal.
- Capturas, método e limites em `docs/REVISAO_USABILIDADE_2026-10-22.md`.

---

## 22/10/2026 — Cabeçalho completo em tablets e menu com rolagem

**O que melhorou**
- Os acessos da equipe e da reserva permanecem disponíveis em tablets: abaixo
  de 1440 px, o site usa o menu lateral. O ajuste inclui o link de comparação
  acrescentado pela instalação publicada.
- Em telas baixas, o menu permite rolar até Fazer Reserva. Ao ampliar para
  desktop, ele fecha e libera a rolagem da página, mantendo o foco visível.

**O que foi modificado**
- Template do cabeçalho, estilos públicos e tratamento de redimensionamento.
- Regressão em nove larguras, de 320 a 1600 px, com teste de rolagem em paisagem.
  Conferência manual em celular, tablet, tela baixa e transição para desktop.
- Suíte completa aprovada: 1.856 testes, incluindo 63 de navegador, em 420,729 s,
  sem falhas ou pulos; Ruff e sintaxe do JavaScript aprovados.
- Evidências antes e depois em `docs/REVISAO_USABILIDADE_2026-10-22.md`.

---

## 22/10/2026 — PDV por categorias, galeria dentro da tela e revisão visual do CRM

**O que melhorou**
- A Loja organiza o catálogo por categoria, busca palavras sem acentos e mostra
  o saldo restante e os itens escolhidos. Produtos e Carrinho têm abas no celular,
  com quantidade e total visíveis; os nomes ficam completos e os botões maiores.
- No computador, produtos podem ser arrastados para o carrinho. A proteção contra
  venda duplicada foi exercitada também com perda da resposta e novo envio.
- A galeria abre acima de toda a página, preserva a foto inteira e mantém fechar,
  navegação e legenda acessíveis inclusive no celular deitado.
- A navegação mostra todas as opções; a Escala aproveita a largura do celular;
  os recados têm campo de resposta consistente. No Marketing, fornecedor e botão
  de salvar permanecem dentro do cartão com a seção expandida.

**O que foi modificado**
- Templates e estilos da Loja, galeria, recados e controles compartilhados;
  textos de atendimento nas seções públicas; seis regressões de navegador e
  reforço da inspeção das seções expandidas do Marketing.
- Computer Use reconectado: 35 módulos em celular e computador, além dos diálogos
  e homepage. Matriz adicional com 660 combinações de tela e largura aprovada.
- Suíte integral final aprovada: 1.855 testes, incluindo 62 de navegador,
  sem falhas ou pulos. Ruff, migrations e sintaxe do JavaScript aprovados.
- Nenhum model ou migration alterado. Resultados, capturas e limites do método
  em `docs/REVISAO_USABILIDADE_2026-10-22.md`.

---

## 22/10/2026 — Captação com confirmação real, grupos no celular e acesso visível

**O que melhorou**
- A conta de grupos tem campos identificados, colunas adaptáveis e orientação
  sobre diárias e consumo. O recebimento inclui as parcelas exigidas pelo
  formulário; adicionar quarto, confirmar, fazer entrada e receber foi exercitado.
- A captação pública preserva os campos e informa erros de contato, datas e
  quantidade. Uma falha ao gravar deixa a pessoa tentar novamente e desfaz
  registros parciais.
- As três páginas de campanha conferem a resposta do CRM antes da confirmação.
  Falhas mantêm o formulário e o foco no aviso; a página de inauguração grava
  também quando servida pelo endereço da VPS. A confirmação aparece na área visível.
- Entrada e recuperação de senha aparecem mesmo com uma sessão já aberta.
  A chave longa do documento fiscal passa a quebrar linha no celular.

**O que foi modificado**
- Formulários públicos, fronteiras de captação, HTML oficial das três LPs,
  contexto das telas de acesso e detalhes de Reservas/Fiscal.
- Regressões de gravação, rollback, validação, acesso e interação com as páginas.
  A matriz adicional passou em 132 combinações, completando 660 combinações
  de tela e largura. A suíte completa passou nos 1.849 testes, sem pulos;
  a configuração local e os resultados focados estão descritos no relatório.
- Nenhum model ou migration alterado. Evidências e limites da validação em
  `docs/REVISAO_USABILIDADE_2026-10-22.md`.

---

## 22/10/2026 — Formulários utilizáveis no celular e pedidos do hóspede funcionando

**O que melhorou**
- O editor de e-mail e o detalhe de página de captação cabem em telas pequenas.
  A comparação de quartos e a confirmação de e-mail usam o diálogo compartilhado,
  com Escape, foco contido, retorno ao botão de origem e ações acessíveis.
- Mensagens de tabelas vazias ficam visíveis sem arrastar. A busca da Loja e de
  Reservas mantém espaço para digitar; os dias da temporada têm área de toque
  adequada, e o calendário vazio apresenta a orientação fora da grade larga.
- Uma movimentação de estoque recusada preserva produto, locais, quantidade,
  custo e fornecedor. O erro permanece no formulário; o ajuste para zero mostra
  o saldo correto na prévia. O total da venda aparece antes da tabela no celular.
- Pedidos e solicitações do portal e a confirmação pública de pagamento deixam
  de falhar com erro 403. A política da página mantém a origem nos formulários
  locais, sem enviar o endereço com token a outros sites; a proteção CSRF continua ativa.
- NPS e Fiscal explicam o que ainda não está disponível em linguagem de operação,
  sem expor instruções de desenvolvimento. O pagamento confirmado informa seu
  registro sem prometer uma reserva para toda cobrança avulsa.

**O que foi modificado**
- CSS compartilhado, diálogos do Comercial, campos de Estoque, telas públicas e
  textos de orientação. Nenhum model ou migration foi alterado nesta entrega.
- Quatorze cenários de regressão em `apps/site/tests_operacao_e2e.py`, incluídos
  no CI: layouts, teclado, dados inválidos e fluxos de loja, restaurante,
  lavanderia, manutenção, portal, estoque, proposta por e-mail e pagamento simulado.
- A matriz de 132 rotas GET passou em quatro larguras (528 combinações), e a suíte
  completa passou nos 1.834 testes em 817,969 s, sem pulos; detalhes e evidências
  em `docs/REVISAO_USABILIDADE_2026-10-22.md`.

---

## 22/10/2026 — Governança com orientação atualizada e relato que pode ser corrigido

**O que melhorou**
- A Minha fila atualiza a instrução ao começar e terminar a limpeza. O perfil
  exclusivo da Governança entra nessa tela e vê o quarto e o próximo botão.
- Relatar um problema mantém a janela e o preenchimento quando falta a descrição
  ou ela passa do limite. O campo explica a correção e recebe o foco.
- O fechamento de um relato preenchido pede confirmação; o envio concluído
  confirma que o chamado está na lista da manutenção. O relato não bloqueia o
  quarto automaticamente; a orientação pede avisar a recepção se ele não puder ser usado.
- A visão geral distingue uma fila já distribuída de um dia sem pendências.
  A conferência de ocupação usa instruções curtas, sem termos em inglês.

**O que foi modificado**
- Formulário de relato, respostas HTMX da Governança, fila e telas de orientação.
- Proteção compartilhada de alterações pendentes passa a considerar o próprio
  formulário quando ele é a raiz da página completa.
- Três casos novos de servidor e quatro cenários de navegador, incluindo erros,
  cliques repetidos, teclado, perfil de camareira e quatro larguras.
- Validação local: 1.820 testes passaram em 730,298 s, sem pulos; lint,
  sintaxe do JavaScript e comparação das migrations sem pendências.

---

## 22/10/2026 — Leads ligados às campanhas e cadastro em uma só etapa

**O que melhorou**
- "Novo lead" reúne o contato e o atendimento em um único salvamento. É possível
  escolher um contato já cadastrado; cancelar ou corrigir um erro não deixa
  cadastros incompletos. Reenvios e solicitações simultâneas criam um só lead.
- Origem, campanha e interesse ficam à mão; período, pessoas, previsão de valor
  e responsável ficam em "Mais informações". O formulário preserva o preenchimento
  e leva o foco ao campo que precisa de correção.
- A campanha abre os seus leads no funil. Os filtros, os indicadores e as etapas
  abertas/encerradas respeitam a campanha escolhida; o atendimento permite voltar
  ao mesmo conjunto e consultar o planejamento, quando o perfil tem acesso.
- "Mover" usa a janela compartilhada, com acesso por teclado e formulário de
  perda que mantém a explicação digitada. O cabeçalho e os botões permanecem
  acessíveis enquanto o formulário rola, no celular e no computador.
- A rota comum de movimentação não reabre atendimentos encerrados nem desfaz uma
  venda. Essas alterações continuam pelo fluxo da gestão, que verifica a reserva
  e os efeitos financeiros. Repetir uma perda não duplica o histórico.

**O que foi modificado**
- Formulários e serviços do Comercial, migration aditiva `comercial.0033`, filtros
  do funil e ligações com Marketing por interfaces públicas.
- Proteção de alterações pendentes compartilhada com a edição de campanhas.
- Dezoito testes de cadastro/integração e sete novos cenários de navegador.
  A rodada de regressão de Comercial, Marketing e design passou em 513 testes;
  os sete cenários novos e o arrasto existente passaram no Chromium.
- Suíte completa local: 1.813 testes aprovados, sem pulos (719,514 s). Ruff,
  migrations, sintaxe dos scripts e diff sem pendências. A fixture de limpeza de
  reservas ficou independente dos dados semeados pelas migrations.

---

## 22/10/2026 — Campanhas com criação guiada e edição segura

**O que melhorou**
- "Nova campanha" pede nome e objetivo antes de criar. Cancelar não deixa uma
  campanha vazia; repetir o envio retorna a mesma campanha.
- A ficha usa a janela compartilhada do sistema, acima do menu, com cabeçalho
  curto, conteúdo que rola e ações visíveis no rodapé. Planejamento, tarefas,
  equipe, peças e resultados ficam organizados em seções.
- Os dados são salvos por botão. Digitar ou mudar de campo não troca mais o
  formulário; erros explicam a correção e preservam o preenchimento. Fechar ou
  executar outra ação com dados pendentes pede uma decisão.
- O quadro atualiza ao fechar uma ficha alterada. Os títulos das campanhas são
  links acessíveis por teclado, também com abertura da página completa.
- A animação compartilhada usa um cálculo estável com poucos quadros por segundo;
  abrir novamente interrompe o fechamento anterior sem apagar a nova janela.

**O que foi modificado**
- Formulários, views, templates e JavaScript de Marketing; migration aditiva
  `marketing.0007` para a chave única de criação. Campanhas existentes são preservadas.
- Modal de `base.html`, estilos no design system e motor `fluid.js`.
- Testes de validação/idempotência e oito cenários de navegador. O teste antigo de
  áudio fecha o arquivo que lê para permitir a limpeza da pasta no Windows.

**Validação e cobertura**
- Suíte completa local: 1.786 testes aprovados. A rodada focada posterior passou
  nos 13 testes de edição e oito testes de navegador, incluindo os dois casos
  acrescentados após o início da suíte completa. Lint e migrations sem pendências.
- Oito cenários novos passaram no Chromium: cancelamento/criação repetida,
  digitação/erro/salvamento, alterações pendentes, teclado, interrupção da animação,
  baixa taxa de quadros e larguras de 320, 390, 821 e 1440 px.
- A cobertura da revisão geral, ainda em andamento, está em
  [Revisão de usabilidade de 22/10](docs/REVISAO_USABILIDADE_2026-10-22.md).
- Publicado como `e12cb51` na fork e na VPS, após os dois jobs do CI. A migration,
  os arquivos do container, a saúde do serviço e os endpoints públicos foram
  conferidos em 22/10 às 02:35 (Brasília), com backup verificável preservado.

---

## 22/10/2026 — Dois arremates do toque (`03549c9`, `40280ee`; merges `f9c5832` e `3e72743`)

**O que melhorou**
- O "Mais opções — camas, taxas e observações" da gaveta de nova reserva passa de 39
  para 44 px: a regra de toque do `<summary>` só alcançava o conteúdo da página, e a
  gaveta mora fora dele.
- A linha do plano do dia da Governança fica travada por teste como alvo inteiro (não
  só o número do quarto), para nenhuma mexida futura no cartão desfazer isso.

**O que foi modificado**
- `static/css/app.css` (`.modal-caixa summary` no bloco de toque) e
  `apps/nucleo/tests_design.py`.

**Como foi testado**
- `tests_design` e `apps.reservas` (479) OK; base.css em dia; as gavetas de Nova
  reserva e da ficha do quarto percorridas controle a controle a 390 px.

---

## 22/10/2026 — Celular, última rodada: ficha de campanha, "×" dos carrinhos e e-mail do lead (`5a20346`, merge `8e11d6c`)

Fecha a lista da varredura do CRM a 390 px com toque.

**O que melhorou**
- **Ficha da campanha (Marketing):** os botões dela passam a ter 44 px, e a caixa de
  marcar das etapas continua com o desenho de 20 px, mas com 44 × 44 de área de toque.
  São eles:
  - os chips de canal, "Adicionar", "Salvar dados" e "Dispensar";
  - copiar e fechar no cabeçalho;
  - o ✕ de cada etapa.
- **"×" de tirar item** do carrinho da Loja, da comanda do Restaurante e da ordem da
  Lavanderia com 44 × 44.
- **E-mail do lead:** "Aplicar" e "Biblioteca" com 44 px.

**O que ficou de fora, de propósito**
- As barras do calendário do Marketing: a altura já tem 44 px, e a largura é a duração
  da campanha no mês — esticar faria a barra mentir.

**O que foi modificado**
- `static/css/app.css` (seção "Polimento mobile"), `templates/comercial/email/enviar.html`;
  `tests_design` com o contrato novo.

**Como foi testado**
- E2E do site (18), `tests_design` (122) e os módulos tocados (405) no branch; varredura
  em 320, 390, 821 com o menu aberto e 1440 px sem rolagem lateral.

---

## 22/10/2026 — Governança no toque: ficha do quarto, "Desfazer" e a gaveta de baixo (`85fa82e` a `42010f3`, merge `4d7f1e0`, `306bba4`)

Segunda rodada do pedido "a governança vai ser usada mais no tablet e no celular, tem
que ser bem intuitiva". Feita pelo mesmo agente da Governança v2, revisada no
navegador com toque emulado antes do merge.

**O que melhorou**
- **Ficha do quarto:** tocar numa porta do corredor abre uma gaveta com o estado, o
  porquê, quem está no quarto e o próximo passo ("Começar limpeza", "Aprovar
  limpeza"…). O que antes só aparecia passando o mouse agora está escrito, a um toque.
- **"Desfazer" no lugar de "tem certeza?":** ao liberar o quarto, a ação acontece na
  hora e um aviso verde oferece desfazer.
- **Check-in barrado pela limpeza:** o link do aviso na reserva abre a ficha daquele
  quarto ("Ver a limpeza do quarto"), e não a Governança inteira.
- **No toque, em todo o CRM:**
  - o modal vira gaveta encostada embaixo, com os botões presos ao pé, onde o polegar
    já está; a altura acompanha a tela que existe, mesmo com a barra do Safari à vista;
  - o aviso (toast) sobe para o topo, para não cair em cima desses botões;
  - os botões vizinhos ganham 10 px de folga;
  - o texto de apoio, os rótulos e os selos de estado ficam legíveis sem zoom.
- A legenda do corredor da Governança, que filtra a lista, tem 44 px; a do painel, que
  é só legenda, continua compacta.

**O que ficou de fora, de propósito**
- Do commit antigo `01dcaaf`, que nunca tinha entrado:
  - o gráfico "Ritmo do dia" (o número de cada barra seria uma dica de passar o mouse,
    a pergunta já está escrita no Plano do dia e ele traria o Chart.js de fora ao
    celular da camareira; se for útil, o lugar é Relatórios);
  - o botão "Meus quartos", que a Minha fila já substitui.
- "Terminei a limpeza" não tem "Desfazer": concluir avisa a Lavanderia, que recolhe o
  enxoval num registro que não se apaga. O caminho de volta é "Devolver para limpar".

**O que foi modificado**
- `apps/governanca`: rota `governanca:quarto` (ficha; gaveta com HTMX e página sem
  JavaScript), `desfazer_aprovacao`, parciais `acoes_quarto`, `quarto_ficha`,
  `quarto_sheet` e `desfazer`.
- `apps/reservas/views.py`: o link do aviso de check-in.
- `static/css/app.css`: ficha do quarto e, no bloco de toque, a gaveta de baixo
  (`88dvh`, com `88vh` antes), o toast no topo, as folgas e o texto legível (escopo
  `.conteudo`, fora do recorte público).
- `306bba4`: na ficha, "Devolver para limpar" empilha abaixo de "Aprovar limpeza" no
  celular, em vez de se espremer em três linhas.

**Como foi testado**
- Testes novos: `FichaDoQuartoTests`, `DesfazerAprovacaoTests`, `AvisoDeCheckinSujoTests`,
  `SemHoverTests` e o contrato de toque `DesenhadoParaODedoTests`.
- Governança, escala, manutenção, reservas e design: 696 testes no branch.
- Navegador:
  - a 390 × 844, 768 × 1024 e 1024 × 768 com toque, sem alvo abaixo de 44 px nem
    rolagem lateral;
  - as gavetas de Nova reserva, Novo grupo, ficha do quarto e Devolver para limpar
    com os botões à vista e o combobox de pessoa inteiro dentro da gaveta;
  - a 1440 px, o modal continua centrado.

---

## 22/10/2026 — Polimento do celular: o dedo acerta, nada flutua por cima, o site cabe na mão (`246e590` a `d532dc7`, merge `3bf4f7c`, `486f501`)

Pedido do dono, testando no celular: "só tem que polir a interface no mobile e tudo —
até a homepage tem ícone com overlap". Feito por um agente numa cópia separada do
código, medido com o navegador em toque emulado (320, 390, 768, 821 com o menu aberto e
1440) e revisado antes do merge.

**O que melhorou**
- **Homepage:** na primeira visita pelo celular, o botão do WhatsApp subia por cima do
  aviso de cookies e caía no canto do "Ver Disponibilidade". Agora ele espera a escolha
  e volta depois.
- **O aviso de cookies não come mais o fim das páginas:** reserva a própria altura,
  então o formulário de proposta da home, o "Perdeu o código?" e o "Voltar ao site" de
  Minha reserva aparecem. Com o menu do site aberto, aviso e botões flutuantes saem da
  frente (o aviso cobria o "Fazer Reserva").
- **O caminho inteiro da reserva cabe no dedo:** campos e botão do hero, cartões de
  /quartos/, lotação do passo 1, "Reservar" e "Alterar datas" do passo 2, camas do
  passo 3, calendário e links do rodapé com 44 px.
- **No CRM:**
  - os controles pequenos dentro de chips e células: os 56 "+" e "×" da grade da
    Escala, abas de Tarefas, Responder/Enviar dos recados, ações do relatório do
    Marketing, nome do produto no Estoque;
  - os campos da "Nova reserva" e dos outros modais;
  - na lista de reservas e de vendas, a linha inteira abre o registro;
  - a porta do corredor perdeu o vão vazio (a 390 px, de 26 para 5 px).
- A bolinha de iniciais dos recados mostrava o login inteiro escrito por cima do
  cartão; agora mostra duas letras.
- LPs: FAQ e "Inscrever outra pessoa" com 44 px, sem mexer no HTML do design.

**O que foi modificado**
- `static/css/app.css` (seção "Polimento mobile" e o bloco de alvos de toque, tudo
  dentro de `@media (pointer: coarse), (max-width: 820px)`), `static/js/consentimento.js`
  e `componentes/consentimento.html`, parciais e passos de reserva do site,
  `views_lp.py` (CSS injetado nas LPs), `reservas/lista.html`, `loja/vendas.html`,
  `logbook_ocorrencia.html`.

**Como foi testado**
- E2E do site com 5 casos novos (folga do aviso, WhatsApp fora dos créditos e do
  formulário da primeira tela, 44 px no caminho da reserva, menu aberto sem nada por
  cima), `tests_design` com o contrato de toque, `ToqueNasLPsTests`; desktop conferido
  a 1440 px sem mudança.

---

## 22/10/2026 — Varredura do CRM no celular e limites de tentativa com o prazo certo (`ba026c7`, `f26b04e`)

Uma varredura automática passou por 168 telas do CRM a 390 px com toque, procurando
rolagem lateral, elementos encavalados e alvos de toque pequenos. Rolagem lateral:
nenhuma. Encavalado de verdade: um. Os alvos pequenos que sobraram (Marketing,
Lavanderia, Comercial) foram para a rodada de polimento do celular, que está em
andamento.

**O que melhorou**
- **Lead no celular:** a lista "Quartos para este lead" não rola mais dentro da
  página. O teto de 420 px cortava o segundo quarto no meio dos botões, e o "Ver
  todos" parecia estar em cima de "Ver ficha" e "Enviar ao cliente". No desktop com
  mouse, nada muda.
- **Limites de tentativa com o prazo certo:** sem Redis, o cache fica numa tabela do
  Postgres, e lá cada tentativa encurtava a janela para 5 minutos. Os limites de 1
  hora (cartão, proposta e reserva no site) e de 10-15 minutos (trava de login por
  conta, "Já paguei", leads das LPs) zeravam 5 minutos depois da última tentativa. Os
  de 1 minuto (webhook) só zeravam depois de 5 minutos de silêncio, e o teto diário
  de envios do Comercial zerava a cada 5 minutos sem envio. Agora cada janela vale o
  tempo pedido.

**O que foi modificado**
- `templates/comercial/oportunidade.html`: a lista dos quartos que servem cresce com a
  página no toque e até 820 px; a dos indisponíveis segue com rolagem própria.
- `apps/nucleo/ratelimit.py`: `janela_atual()` e `somar()` (reafirma o prazo a cada
  soma); o limite por IP, a trava por conta, o limite do site, o de leads das LPs e o
  teto diário de envios passam por eles.

**Como foi testado**
- `JanelaDoLimiteTests` com o cache em banco: a janela de 1 hora continua de 1 hora
  depois da terceira tentativa, a contagem zera na virada, e as falhas da conta somam
  e somem juntas. Trava por conta e limites dos pagamentos seguem passando.
- Lead de demonstração no navegador a 390 px (seis quartos inteiros, "Ver todos"
  abaixo) e a 1440 px (lista de 420 px com rolagem, como antes).

---

## 22/10/2026 — Cada um entra no que é seu: a camareira cai direto na fila dela (`b0630e0`)

Achado testando o login da camareira na VPS: depois de entrar, ela via uma "Visão
geral" vazia — só "Seu resumo do dia." e nada abaixo — e precisava abrir o menu e achar
a Governança para começar.

**O que melhorou**
- **Quem tem um módulo só entra direto nele:** a camareira cai na "Minha fila"; a moça
  da Loja, no PDV; o garçom, no Restaurante.
- **Quem tem vários módulos e nenhum bloco da Visão geral** (Loja + Restaurante, por
  exemplo) vê um cartão por módulo, com o nome e o que se faz nele, em vez da página
  vazia.
- O rótulo "Recepção · hoje" no alto da Visão geral vira "Hoje" para quem não é da
  recepção.
- Gerência e recepção não mudam: o painel continua o mesmo.

**O que foi modificado**
- `apps/nucleo/views.py` (`dashboard`): sem nenhum bloco do painel, redireciona para o
  único módulo ou entrega os atalhos; `apps/nucleo/modulos.py`: a Governança ganhou
  `url_pessoal` (a Minha fila); `templates/nucleo/dashboard.html` e `app.css`: os
  atalhos reaproveitam o cartão-atalho dos Relatórios.

**Como foi testado**
- `EntradaPorPerfilTests`: só Governança, Loja + Restaurante e superusuário; o teste do
  menu por permissão segue a nova entrada. `apps.nucleo`, `apps.governanca` e
  `apps.loja` OK; ruff zero.
- Navegador a 390 e 1440 px, sem rolagem lateral.

---

## 22/10/2026 — Governança para tablet e celular: quem está no quarto, o plano do dia e a fila da camareira (`1bd56a0` a `603a797`)

Pedido do dono: "a governança, a maioria do uso vai ser por tablet/mobile, então tem
que ficar uma parada bem intuitiva". Feito por um agente numa cópia separada do código,
desenhado a partir do toque e revisado no navegador (celular e tablet com toque emulado)
antes do merge.

**O que melhorou**
- **O bloco do quarto diz quem está nele**, não só como está a limpeza: vago, ocupado,
  chega hoje, sai hoje ou bloqueado, com o hóspede. O número e o estado vêm na frente,
  legíveis de longe (contraste de 7:1 em todos os estados); o tipo do quarto virou
  detalhe. Com hóspede dentro, o quarto limpo e conferido aparece como "Arrumado" — não
  mais "pode receber hóspede" —, e em manutenção também não anuncia que está livre.
- **Plano do dia:** a ordem de atacar, sem conta de cabeça — chegadas de hoje com o
  quarto ainda não pronto, saídas de hoje (vão sujar), ocupados a arrumar e o resto,
  com a hora do check-in e se dá tempo. A lista de quartos abre na mesma ordem.
- **Minha fila**, a tela da camareira no celular: um cartão por quarto, do mais urgente
  ao resto, com "Começar" e "Terminei" grandes e "Reportar problema", que abre a ordem de
  serviço na Manutenção sem sair do corredor. Quarto bloqueado não entra na fila.
- **Escala:** quem está de turno hoje aparece primeiro no "quem limpa", e "Distribuir a
  fila" divide num toque os quartos a limpar entre essas pessoas, equilibrado. Se a
  camareira está escalada mas não tem login no sistema, a tela diz isso (e não "ninguém
  de turno").
- **Banco novo nasce certo:** quarto que nunca teve limpeza registrada aparece como
  "Pronto" — antes, uma instalação nova dizia "Faltam 23 quartos" e enchia a fila de
  conferência da supervisora sem ninguém ter entrado nos quartos.
- A legenda do corredor, que também filtra a lista, ganhou alvo de toque de 44 px.

**O que foi modificado**
- `apps/governanca`: `plano_do_dia`, `minha_fila`, `distribuir_fila`,
  `camareiras_do_dia` e a ocupação por quarto (`ocupacao_pms`, que lê `reservas.ocupacao_por_uh`) no quadro;
  rotas `governanca:minha_fila`, `distribuir` e `reportar`; templates `fila.html`,
  `partials/fila.html`, `reportar*.html`; migração `governanca.0004` (só o padrão do
  campo: nenhuma linha existente muda).
- `apps/escala/services.py`: `de_turno()` e `usuarios_de_turno()` — interface pública
  para quem atribui trabalho a quem está de turno.
- `app.css`: o bloco do quarto, o plano do dia, a fila e a legenda no toque.

**Como foi testado**
- Testes novos na Governança e na Escala (ocupação no bloco, prioridade do plano, banco
  novo, distribuição equilibrada, fila da camareira, reportar problema, degradação sem
  Reservas ou sem Escala, consultas constantes na visão geral); na árvore juntada,
  governanca, escala, manutencao, reservas, nucleo.tests_design e PrefixoDeUrlTests —
  719 testes OK.
- Revisão no navegador com toque emulado em 390 × 844 e 768 × 1024, e no desktop a
  1440: visão geral, lista e Minha fila, sem rolagem lateral; o fluxo da camareira
  percorrido (Começar → Reportar problema → Terminei).
- **Suíte completa no Windows:** 1.707 testes no `603a797`, só a falha conhecida do ambiente (`test_webhook_audio_baixa_e_salva_arquivo`).
- `makemigrations --check` limpo; ruff zero.

**Para a pousada decidir**
- "Pronto" × "Arrumado": a palavra muda com a ocupação; o estado gravado e a trava de
  check-in continuam os mesmos.
- Quarto novo nasce "Pronto". Se preferirem que a casa comece "a conferir", é trocar o
  padrão e aceitar a fila inicial de 24 inspeções.
- Camareiras precisam de login para a fila e o "Distribuir": em Configurações → Equipe
  & Acessos.

---

## 22/10/2026 — A lista do combo cabe no painel no celular (`35c01ac`)

**O que melhorou**
- No celular, a lista de um combo (cliente, hóspede, quarto, produto, fornecedor)
  que mora dentro de um painel com rolagem própria abria para baixo e era cortada
  por ele — no PDV da Loja, metade da lista do cliente ficava fora do carrinho e da
  tela. Agora a lista escolhe o lado com espaço e não passa do painel nem da parte
  visível da tela (com o teclado aberto, inclusive).

**O que foi modificado**
- `templates/base.html` (`posicionar()` dos combos: visualViewport + ancestrais que
  cortam) e `.combo-lista` com `--combo-max` no `app.css`.

**Como foi testado**
- Novo `ComboNoPainelE2ETests` (navegador, 390 px): falha no código anterior (a
  lista ia até 924 px; o painel acaba em 805) e passa agora.
- Todos os combos medidos em 390 px com toque emulado: nenhum cortado, coberto ou
  fora da tela. `apps.site.tests_e2e`, `apps.loja` e `apps.nucleo.tests_design` OK.

---

## 21/10/2026 — O sistema roda sob um prefixo de URL e o ambiente de teste vai para viczk.cloud/votesta (`c37ae9a` a `ac3d522`)

Décimo quarto bloco, pequeno: para o ambiente de teste morar num caminho do domínio
pessoal do dono (onde outros projetos vivem lado a lado), e não num endereço próprio.

**O que melhorou**
- **O sistema inteiro (site, CRM, portal, LPs) roda sob um caminho**, como
  `https://viczk.cloud/votesta`, com a variável `URL_PREFIX`. Antes ele assumia a raiz
  do domínio: link, CSS, formulário e redirecionamento apontariam para outro projeto.
  Na produção (`URL_PREFIX` vazio) nada muda.
- **Endereços escritos à mão viraram nomes de rota:** 5 atalhos da paleta de comandos
  (⌘K), mover lead no funil, mover campanha no quadro do Marketing, os
  redirecionamentos da captação para as LPs, o link de pagamento do gateway e o "voltar
  ao site" do lab. A auditoria (autor de sistema por caminho) e o atalho de estáticos do
  MFA olham o caminho sem o prefixo.
- **LPs:** o HTML das landing pages vem pronto do design, com caminhos absolutos; sob um
  prefixo, eles são reescritos na hora (fotos, vídeo, política de privacidade, envio do
  lead), sem duplicar o que já vem certo.
- **Healthcheck sob prefixo (`d0d2d57`):** a isenção de HTTPS do `/healthz/` comparava
  com o caminho sem o prefixo; sob `/votesta` o healthcheck em HTTP levava 301 e o
  container nunca ficava saudável. Achado pelo próprio deploy.
- **Relatório de CSP sob prefixo:** o navegador mandava as violações para
  `viczk.cloud/csp/relatorio/`, a raiz do domínio (outro projeto); agora vão para
  dentro do prefixo.

**O que foi modificado**
- `config/settings.py`: `URL_PREFIX` → `FORCE_SCRIPT_NAME`, cookies de sessão e CSRF
  restritos ao caminho e `STATIC_URL`/`MEDIA_URL` com o prefixo escrito (o storage dos
  estáticos guarda a URL base no primeiro uso, e o WhiteNoise o usa na subida do
  servidor).
- `templates/base.html`, `comercial/funil.html`, `marketing/quadro.html`,
  `site/lab.html`, `config/urls.py`, `pagamentos/gateways.py`, `comercial/views.py`,
  `nucleo/audit.py`, `nucleo/security_headers.py` e `comercial/views_lp.py`
  (`_no_prefixo()`).
- README §8, `docs/ARQUITETURA.md` §7 e CLAUDE.md (regra: nada de caminho fixo).

**Como foi testado**
- Novo `PrefixoDeUrlTests` (6): nenhum caminho fixo em templates e JS; o CRM sob
  `/votesta` gera links, estáticos e paleta com o prefixo; as três LPs apontam para
  dentro dele sem duplicá-lo; o redirecionamento da captação fica no prefixo; a trilha
  atribui o portal pelo caminho sem o prefixo; e sem prefixo nada muda. Sem as
  correções, 4 dos 6 falham.
- **Suíte completa no Windows:** 1.606 testes no `c37ae9a`. Além da falha conhecida
  do ambiente (`test_webhook_audio_baixa_e_salva_arquivo`), 4 testes de navegador
  estouraram o tempo nessa rodada — havia outro agente usando a máquina ao mesmo tempo;
  rodados de novo sozinhos, os 12 de navegador passaram. Ruff zero,
  `makemigrations --check` limpo.
- Ambiente de teste conferido em `viczk.cloud/votesta`: site, CRM, LPs e estáticos
  dentro do caminho, e os outros projetos do domínio sem mudança.

---

## 21/10/2026 — A demonstração monta sozinha num banco novo e o ambiente de teste na VPS (`f93c241` a `d1eb308`)

Décimo terceiro bloco, pequeno: o que apareceu ao montar um ambiente de teste do zero.

**O que melhorou**
- **Ambiente de teste fora do Railway:** o sistema inteiro (site e CRM) roda numa VPS
  própria, com dados só de demonstração, atrás de usuário e senha, fora dos buscadores
  (`noindex`) e sem nenhuma integração real (pagamento, e-mail, WhatsApp, FNRH e fiscal
  simulados; sem o bucket de mídia da produção). Serve para testar e mostrar sem tocar na
  produção. A configuração do servidor fica fora do repositório.
- **Os dados de demonstração montam num banco vazio.** Ali, os seeds quebraram ou não
  fizeram nada: `popular_demo` exigia um superusuário criado antes ("criado_por não pode
  ser nulo"); os seeds abriam o caixa do núcleo, mas desde o caixa por módulo a reserva
  recebe no caixa de Reservas, a venda de balcão no da Loja e a entrega da lavanderia no
  dela; `popular_escala` só reclamava sem funcionário cadastrado; e o check-in da
  demonstração batia na trava da FNRH (hóspede de mentira não tem ficha). Agora os sete
  comandos montam tudo em sequência num banco novo — o mesmo vale para um ambiente novo
  do original ou uma recuperação de desastre.

**O que foi modificado**
- **Seeds (`f93c241`, `d1eb308`):** `popular_demo`, `popular_lotacao`,
  `popular_lavanderia`, `popular_escala`, `popular_estoque` e `popular_manutencao` caem
  num usuário de sistema (`_demo`) quando não há superusuário; caixas abertos no módulo
  certo; `popular_escala` cria a equipe que falta ("(demo)"); o check-in do seed passa
  pela trava da FNRH só dentro do comando (`override_settings`).
- **README:** a ordem dos seeds e o que cada um precisa (§2.3).

**Como foi testado**
- Novo `DemonstracaoBancoNovoTests`: num banco de teste sem superusuário e com a trava
  da FNRH ligada, `estrutura_inicial --completo` + os seis seeds montam reserva
  hospedada, caixas de Reservas e da Loja, ordem de lavanderia entregue, equipe e escala
  gerada — e a trava segue ligada depois. No código anterior, o teste quebra em
  "criado_por: Este campo não pode ser nulo".
- `apps.nucleo.tests`, `apps.lavanderia`, `apps.escala`, `apps.estoque` e
  `apps.manutencao` OK; ruff zero.
- Ambiente de teste conferido no navegador: site, entrada do CRM, Governança, Estoque,
  Reservas e Pagamentos abrindo; certificado válido; sem senha, só o `/healthz/` responde.

---

## 21/10/2026 — Copiar e mandar pelo WhatsApp, as ações da reserva à vista e a passada de usabilidade (`3123896` a `0477f85`)

Décimo segundo bloco: o resto dos pedidos do dono — "dá para colocar um botãozinho de
copiar" o link de pagamento e mandar pelo WhatsApp em vez de copiar e colar à mão; "a
mudança de quarto e o estender reserva ficam num dropdown muito pequeno, meio perdido";
o copiar do FNRH; e uma passada de usabilidade pelos fluxos do dia a dia. Feito por um
agente numa cópia separada do código e revisado no navegador antes do merge.

**O que melhorou**
- **Copiar e Enviar pelo WhatsApp** em tudo o que a equipe manda a alguém: link de
  pagamento e Pix copia-e-cola (Pagamentos, no detalhe e na própria linha do painel), a
  cobrança no detalhe da reserva, o link do portal do hóspede, o link do **pré check-in
  (FNRH)** — agora também ao lado de "Preencher / editar FNRH" —, o link público da
  página de captação e o texto e a proposta do painel de quartos do Comercial. O WhatsApp
  abre com a mensagem pronta, em português, e com o telefone do hóspede (ou para escolher
  o contato, quando não há telefone legível). O "Copiar" funciona também no servidor da
  pousada aberto por `http://` na rede local, onde o navegador não deixa usar a área de
  transferência pelo caminho normal, e o leitor de tela anuncia o "Copiado".
- **As ações da reserva numa barra à vista**, logo abaixo da ficha: o que fazer agora em
  destaque (Confirmar / Check-in / Check-out), as alterações ao lado (receber sinal,
  alterar lotação, transferir datas, estender estadia, trocar de quarto, QR do hóspede,
  emitir NFS-e) e o que desfaz separado no fim (não compareceu, cancelar — agora com
  confirmação). O formulário abre num painel largo, um por vez. Antes eram caixinhas de
  13 px no meio da página, e três formulários ficavam abertos para sempre, empurrando a
  conta do quarto para baixo da dobra.
- **Passada de usabilidade** (criar reserva → confirmar → check-in → consumo → receber,
  PDV, comanda, caixa, funil, governança e manutenção, em 56 telas × 4 larguras):
  - datas que **sumiam** ao reabrir a ficha: nascimento na FNRH, restrição de venda,
    grupo e oportunidade voltavam com o campo em branco e pediam a data de novo;
  - o aviso da tarifa dizia "R$ 940.00" e "ISS 4.0%" — agora "R$ 940,00", como a
    recepção lê em voz alta (e o mesmo na frase da política de cancelamento);
  - nova reserva abre com hoje → amanhã; "Receber pagamento" na estadia já abre com o
    saldo; o que impede o check-in (FNRH pendente, menor sem responsável) aparece
    **antes** do clique, com o caminho para a ficha;
  - "Nenhuma cobrança" virou atalho para gerar a cobrança já apontada para a reserva;
  - os dois campos "Valor" do detalhe tinham o mesmo id — clicar no rótulo de um punha
    o cursor no outro;
  - PDV da Loja: o cliente era uma lista com todas as pessoas; agora é a busca agrupada
    do Restaurante;
  - Escala: a grade ficava inerte quando não havia funcionário cadastrado; Restaurante
    sem ponto de atendimento agora avisa e leva ao cadastro; BOH cortava "PERMANÊNCIA
    MÉDIA" a 821 px;
  - um comentário do template escrito em duas linhas aparecia como texto cru na tela do
    PDV e na lista da Governança — e um teste de design barra a volta.
- **Monitor grande, por dentro do detalhe:** o painel da ação para em 900 px e os
  indicadores do Financeiro em 300 px, em vez de faixas com o rótulo num canto e o valor
  no outro.
- **Estados da FNRH com maiúscula** ("Completa", "Pendente", "Responsável", "Enviada",
  "Pendente de envio").

**O que foi modificado**
- **Copiar (`3123896`, `1e64729`):** `{% copiar texto rotulo recado telefone mostrar %}`
  (`templates/componentes/copiar.html` + `static/js/copiar.js`, ouvinte delegado com
  plano B por `execCommand`); `apps/nucleo/compartilhar.py` (`telefone_whatsapp`,
  `mensagem_whatsapp`, `link_whatsapp`); `reservas.services.contato_da_reserva` (para
  quem mandar, sem import de models).
- **Ações da reserva (`5160e06`, `bb0c7c5`):** barra `.acoes-reserva-barra` (com o destrutivo em `.acoes-reserva-risco`) e painéis no
  `reserva_detalhe.html` (mesmas views e POSTs); sai `reservas/partials/alterar_reserva.html`;
  sinal recebido no painel Financeiro; `Reserva.pode_receber_sinal` e `STATUS_SINAL`.
- **Atritos (`8a89948`, `0b36447`):** `DataInput`/`DataHoraInput` do núcleo nos forms de
  FNRH, restrição, grupo e oportunidade; `tarifa_preview` com `intcomma_brl`; `auto_id`
  próprio nos dois forms do detalhe; combobox de pessoa no PDV; aviso de ponto de
  atendimento; `bindRoster()` da Escala; teste de design contra `{# … #}` em duas linhas.
- **Maiúsculas (`0477f85`):** selos da FNRH no detalhe e nas fichas.

**Como foi testado**
- 25+ testes novos (telefone e mensagem do WhatsApp, o componente, as telas de
  Pagamentos/reserva/QR/captação, datas em ISO nos quatro forms, saldo pré-preenchido,
  ids separados, aviso do check-in, barra de ações por estado e cada painel com o seu
  botão).
- Merge sobre o `dev` com conflito só no fim de `apps/reservas/tests.py` (os dois lados
  acrescentaram testes); 1.201 testes dos apps tocados na árvore juntada, só a falha conhecida do Windows.
- Revisão no navegador antes do merge: detalhe da reserva (confirmada e hospedada),
  Pagamentos e PDV em 390, 821 (menu aberto), 1440 e 2560 px — sem rolagem lateral,
  nada saindo do cartão; o "Copiar" e o "Enviar pelo WhatsApp" do FNRH ao lado do botão.
- **Suíte completa no Windows:** 1.599 testes no `0477f85` (eram 1.547 no bloco anterior), só a falha conhecida do ambiente
  (`test_webhook_audio_baixa_e_salva_arquivo`). Ruff zero, `makemigrations --check`
  limpo.

**Para a pousada decidir**
- Cobrar o **saldo** online de uma reserva já confirmada ou hospedada ainda não tem
  atalho: o painel de Pagamentos só aceita sinal de orçamento ou pré-reserva.
- O seletor de quarto da nova reserva lista quartos ocupados e só acusa no envio.
- Não há nenhum ponto de atendimento cadastrado no Restaurante (a tela agora avisa).

---

## 21/10/2026 — A navegação sem piscar, as dicas no lugar, a governança que ensina e o Estoque redesenhado (`6f66d4f` a `7899e11`)

Décimo primeiro bloco: os pedidos do dono depois de usar o sistema — o menu piscando a
cada troca de página, as caixinhas de hover fora do centro, texto em minúsculo, espaço
sobrando no monitor grande, os botões da governança desalinhados, um fluxo de faxina que
ensine quem nunca trabalhou em hotel, uma visão da governança "mais gráfica" e o Estoque
"simplório". Governança e Estoque foram feitos por agentes em cópias separadas do código,
revisados no navegador e corrigidos antes do merge. Copiar e mandar link pelo WhatsApp e
as ações da reserva vêm no próximo push. Entram também a revisão de documentação
publicada no `dev` (`784c208`) e os dois commits novos do original (`bcd9ee8`, `5f57fb8`).

**O que melhorou**
- **Trocar de página não pisca mais.** A transição pegava a página inteira como um bloco
  só: menu e barra do topo sumiam e voltavam a cada clique. Agora menu e topo ficam
  parados e só o conteúdo troca, num cross-fade curto; a navegação comum (link que
  recarrega a página) ganhou a mesma troca. As trocas parciais (item na comanda, filtro,
  ronda) deixaram de animar a página inteira.
- **Caixinhas de hover centradas, inteiras e iguais no sistema todo.** Eram três motores,
  cada um com outra cara, e o balão era desenhado dentro do elemento: cortado pela tabela
  no mapa e em Pessoas, vazando pela direita no detalhe da reserva, nascendo a até 363 px
  do que se via no calendário do Marketing. Agora é um balão só — centrado no que se vê,
  em cima quando cabe e embaixo quando não, sempre dentro da tela. Com o menu recolhido, o
  nome do item aparece na hora ao lado do ícone. E passar o mouse numa porta do corredor
  não empurra mais a tela de baixo (o espaço que o balão antigo reservava fazia tudo
  descer 62 px).
- **Nada de código cru nem frase em minúsculo.** A Auditoria mostrava "no_show",
  "lead_fechado_movido", "SessaoCaixa" e gravidade "media"; a conciliação, "pendente".
  Agora "Não comparecimento", "Lead fechado movido", "Caixa", "Média", "Pendente" — o
  código continua no banco e no CSV. As frases soltas do painel, do PDV, da comanda, dos
  tipos de quarto, da Manutenção, da Tabela de Preços e do Estoque começam com maiúscula.
- **Monitor grande:** o conteúdo para em 1760 px e fica centrado, com a busca alinhada.
  A 2560 px, o detalhe da reserva virava faixas de 2.300 px, com o valor do financeiro lá
  na ponta. O mapa de reservas e o calendário do Marketing continuam de ponta a ponta.
- **Governança que ensina quem nunca trabalhou em hotel:**
  - o ciclo do quarto à vista e na ordem — **A limpar › Em limpeza › Limpo › Pronto** —,
    que também filtra a lista; cada linha diz por que o quarto está ali ("O hóspede fez
    check-out. Na fila de Maria.", "Limpo às 11:05 por Maria. Falta a supervisora
    conferir.");
  - **um** botão por quarto, com o nome do que acontece: "Começar limpeza", "Terminei a
    limpeza", "Aprovar limpeza". Quarto sujo sem faxina na fila começa num toque só (eram
    dois botões seguidos). "Devolver para limpar" abre na janela da casa, e o motivo
    aparece na linha de quem vai limpar de novo;
  - "Só os meus" para a camareira e um "Como funciona" com o glossário (ronda, inspeção,
    faxina × arrumação, skip, sleeper);
  - os botões da linha com a mesma altura e na mesma linha — também no celular e no
    tablet, onde "Aprovar" saía 8 px mais baixo que "Devolver".
- **Governança — "Como está a casa"**, a nova entrada do módulo: os quartos em blocos
  pintados pelo estado da limpeza, "22 de 24 prontos" com a barra do dia e a hora em que o
  primeiro hóspede pode entrar, o "Precisa de atenção agora" (chegada sem quarto pronto,
  quarto esperando inspeção, divergência da ronda, quarto sem camareira), as chegadas de
  hoje e a carga de cada camareira. Tudo clicável para a lista já filtrada. No celular, o
  progresso e o que pede ação vêm antes dos blocos. A lista foi para a aba Quartos.
- **Estoque redesenhado:**
  - a posição virou tela de decisão: quanto dinheiro está parado em mercadoria, quantos
    itens estão abaixo do mínimo, quantos acabaram e quanto se mexeu na semana;
  - a escolha do depósito, que era um chip com o nome, virou um cartão por depósito com
    o que ele guarda, quanto vale e quantos itens estão no limite — e, escolhido, a tela
    mostra só o que aquele depósito guarda, em vez do catálogo inteiro em alarme;
  - cada linha tem a régua saldo × mínimo e atalhos de entrar, tirar e transferir aquele
    produto já preenchidos;
  - registrar movimento tem busca de produto, saldo de cada depósito ao vivo, fornecedor
    e nota na entrada e a prévia "saldo hoje → fica com" (com o custo médio novo);
  - kardex com saldo corrente; contagem de inventário com progresso, busca e resumo — e o
    item que ninguém contou não é mais mexido (antes, uma venda feita durante a contagem
    era apagada no "Aplicar");
  - quantidade como se fala: "55 un", "4,5 kg", "5 L".
- **Clique duplo no Estoque não grava duas vezes.** Na entrada, dobrava o saldo e
  deslocava o custo médio; na saída, baixava duas vezes. E um "nan" digitado na contagem
  derrubava a tela.

**O que foi modificado**
- **Navegação (`6f66d4f`):** View Transition com nomes próprios (`menu`, `topo`,
  `conteudo`), e só o conteúdo anima; `@view-transition { navigation: auto }` fora de
  `prefers-reduced-motion`; no `base.html`, sai o `globalViewTransitions` do HTMX e entra
  `transition:true` só no `hx-boost` do menu.
- **Dicas (`f649111`, `1f1aab6`):** `static/js/dicas.js` — um balão fixo
  (`#dica-flutuante`) para todo `[data-dica]`, com `data-dica-lado` para o menu recolhido;
  saem a dica em `::after`, o `.mk-dica` e o `#fx-tip` do Marketing, e o
  `.corredor-hero:has(.porta:hover)` que reservava espaço para o balão antigo.
- **Rótulos (`fa79ddb`, `85543e0`):** `auditoria.formatacao.rotulo_acao/rotulo_alvo/
  rotulo_gravidade` e os filtros no `auditoria_extras`; `pagamentos.services.conciliacao()`
  leva o rótulo; `.filtro-barra input[type=search|text]` na moldura da casa.
- **Tela grande (`45f9417`):** token `--conteudo-max` e a classe `.conteudo-largo`.
- **Governança (`6eab595`, `e275059`, merge `d2d858d`, `c218532`, `1f1aab6`):**
  `services.CICLO`, `explicar_estado`, `visao_geral` e `carga_das_camareiras`; rotas
  `governanca:quartos` (a lista) e `governanca:devolver`; `painel` vira a visão geral;
  `abrir_faxina` trava a situação do quarto e não rebaixa faxina já começada;
  `iniciar_tarefa` acerta o quarto preso em "A limpar"; o "Resolver" do quarto sem ronda
  leva à lista. Sem migração.
- **Estoque (`202a059` a `00b4d0a`, merge `1381a71`):** `MovimentoEstoque.fornecedor` e
  `chave` (idempotência, como a `Venda.chave`), `ItemInventario.contado` e
  `Inventario.aplicar(somente_contados=)` — migração `nucleo.0050`; consultas
  `saldos_por_local`, `resumo_locais`, `indicadores_estoque` e `movimento_da_chave`;
  `apps/estoque/formato.py`; telas novas (`movimentar.html`, `cadastros.html`,
  `produto_form.html`); `combo_pessoa.html` emite `combo-mudou`; comando
  `popular_estoque`.
- **Original (`bcd9ee8`, `5f57fb8`):** comando `zerar_reservas` (reset de ambiente de
  teste, dry-run por padrão) e um commit vazio de redeploy.
- **Docs:** revisão publicada em `784c208` (índice `docs/README.md`, `docs/ESTADO_ATUAL.md`)
  e, neste push, README, `docs/ESTADO_ATUAL.md`, `docs/ARQUITETURA.md`,
  `docs/MODULOS_E_FLUXOS.md` e CLAUDE.md em dia.

**Como foi testado**
- **Navegação:** quadro a quadro no Chromium (transição pausada de 0 a 200 ms), menu
  aberto e recolhido — na faixa do menu, a diferença para a página em repouso caiu de
  62–64 (numa escala de 255) para menos de 1.
- **Dicas:** mouse de verdade em 8 telas, a 1440 e 390 px, sem nenhum problema; testes
  `DicasTests` e `DicasE2ETests` (no navegador). O pulo do corredor medido: o bloco de
  baixo descia de 1015 para 1077 px com o mouse numa porta; agora fica em 1015.
- **Minúsculas:** varredura do texto visível em todas as telas do menu e em 21 detalhes:
  de 30 textos em minúsculo para só dado (nome de usuário, área digitada numa OS).
- **Tela grande:** medido a 2560 e 1920 px; nada muda até 1920 com o menu aberto.
- **Governança:** 104 testes no app (ciclo, frase de cada estado, uma ação por estado, o
  toque único, o modal e a página sem JS, o motivo na linha, "Só os meus", a visão geral
  com consultas constantes). O toque duplo e o quarto preso falham no código anterior e
  passam agora. Altura dos botões medida com toque emulado: antes 36 × 44 px, agora
  44 × 44. Fluxo real nos dois papéis (camareira a 390 px, supervisora a 1440 px) e as
  telas em 320, 390, 821 (menu aberto), 1440 e 1920 px.
- **Estoque:** 64 testes no app — formatação, consulta constante (20 produtos a mais =
  mesmas consultas), saldo corrente do kardex, atalhos preenchidos, contagem parcial e
  inválida (nan, Infinity, 1e20) e dois POSTs com a mesma chave (um movimento, mesmo saldo
  e mesmo custo médio). Fluxo real no navegador: entrada, transferência, saída sem saldo,
  inventário aplicado e duplo envio (29 → 36 un, não 43). As nove telas em 390, 821 (menu
  aberto) e 1440 px antes do merge.
- **Suíte completa no Windows:** 1.547 testes no `7899e11` (eram 1.450 no bloco anterior), só a falha conhecida do ambiente
  (`test_webhook_audio_baixa_e_salva_arquivo`). Ruff zero, `makemigrations --check`
  limpo.

**Depois do deploy (no Railway)**
- A migração `nucleo.0050` o deploy roda sozinho.
- Opcional: `manage.py popular_estoque` só para demonstração — não rodar com dados reais.
- Decisões da pousada:
  - estoque mínimo: hoje é um por produto, para a casa toda — por isso o depósito da
    Loja aparece com quase tudo "abaixo do mínimo". Mínimo por depósito seria um campo
    novo;
  - governança: confirmar com a camareira e a supervisora os nomes dos passos
    ("Começar limpeza", "Terminei a limpeza", "Aprovar limpeza") e da ronda ("Vago / Com
    mala / Sem mala").

---

## 21/10/2026 — Documentação revisada e índice do projeto

- README, especificação, arquitetura, módulos e convenções alinhados ao código
  publicado; removidas descrições obsoletas de Frigobar, stack, bootstrap e CI.
- Novo índice em `docs/README.md` e snapshot em `docs/ESTADO_ATUAL.md`, separando
  implementação publicada, nove commits locais de interface e ativação externa.
- Guias e checklist distinguem simuladores, providers pendentes e homologação;
  corrigido o aviso de que `EMAIL_GATEWAY=simulado` pode enviar SMTP real.
- Planos, estudos, auditorias e evidências antigos identificados como históricos;
  preços, contas externas e resultados de testes passados não foram revalidados.
- Entrega somente documental: sem mudança de código, migração ou deploy. Revisão
  de links, referências, UTF-8 e diff; suíte funcional não reexecutada nesta entrega.

## 21/10/2026 — Telas rápidas, a LP leve, o cupom da térmica, o no-show da madrugada e os relatórios de receita e de governança (`2e1ae94` a `a8a3f1a`)

Décimo bloco: o que ainda estava aberto no relatório da auditoria, tirando dados
fictícios e LGPD, que ficaram de fora por decisão do dono. Os relatórios de receita e os
de governança foram feitos por agentes em cópias separadas do código e revisados no
navegador antes do merge. O original não ganhou commit novo desde o último push.

**O que melhorou**
- **Telas do dia a dia mais rápidas** (medido no banco local com os dados de teste):
  - abrir um lead: 444 consultas ao banco e 481 ms → 56 consultas e 69 ms. O painel de
    quartos do lead relia temporada, tarifas e configuração para cada quarto × noite —
    e piorava a cada noite a mais no pedido;
  - o funil: 60 consultas e 211 ms → 16 e 24 ms (eram duas consultas por card);
  - "Nova reserva": 38 consultas e 410 ms → 11 e 21 ms. Mais da metade do tempo era o
    JIT do Postgres, que compilava por 185 ms uma consulta de 1,4 ms (tabelas pequenas
    que ainda não passaram pelo ANALYZE). O sistema agora conecta com o JIT desligado.
- **A landing page da inauguração, leve e compartilhável:**
  - tinha 2,1 MB, sendo 2,0 MB de sete fontes e quinze imagens dentro do próprio HTML —
    as fontes e a foto do hero no `<head>`. Num celular com 4G fraco: 4,2 s de tela vazia
    e 10,9 s para carregar. Agora o HTML tem 89 KB e as fotos e fontes vêm em arquivos
    próprios, que o navegador guarda: primeira pintura em 0,4 s, carga completa em
    5,6 s, metade dos bytes (a foto que aparecia duas vezes e o selo que aparecia três
    passam a vir uma vez só). A página é a mesma, pixel a pixel;
  - o link compartilhado no WhatsApp e no Instagram saía **sem imagem**: a imagem e o
    canônico apontavam para `/lp/inauguracao/…`, endereço que nunca existiu (e o Google
    recebia um canônico que dá 404). Agora há uma imagem de compartilhamento feita do
    próprio hero da página (a torre do relógio, "A casa do Vô abre as portas.", "31 de
    Outubro"), e quem digitar `/lp/inauguracao/` cai na LP com a campanha junto.
- **Conserto de um defeito deste fork:** o aviso de cookies que entrou nas LPs no bloco
  anterior usava a mesma classe do checkbox de LGPD do formulário. Na Fundador e na
  Inauguração, o checkbox ia parar no rodapé da tela e o botão "Quero participar" subia
  por cima do texto; o aviso, por sua vez, saía espremido numa coluna de 22 px. A
  produção do original não tem o aviso, então não foi afetada — mas o patch do aviso
  preparado para o Gefferson tinha o mesmo defeito e ganhou a correção junto.
- **No-show automático (opcional):** em Tabela de Preços → "Horários e não
  comparecimento". Desligado, nada muda: a reserva confirmada sem check-in continua
  aparecendo na Auditoria para a recepção decidir. Ligado, a rotina da madrugada marca o
  "não compareceu" — na madrugada seguinte à entrada ou com 1 ou 2 dias de tolerância — e
  o quarto volta à venda nas noites que sobravam. O que o hóspede pagou fica na conta,
  como no no-show manual. Se ele aparecer (voo atrasado, check-in esquecido no sistema),
  "Desfazer não comparecimento" devolve a reserva, desde que o quarto ainda esteja livre.
- **Cupom de 80 mm na impressora térmica**, pelo navegador:
  - Loja: o recibo da venda; Restaurante: a conferência da conta com a comanda aberta
    (a que vai à mesa) e o recibo depois de fechada; Lavanderia: o comprovante que fica
    com o hóspede quando entrega a roupa (o que entrou e quando fica pronto) e o recibo
    na entrega;
  - sai do tamanho do cupom: a bobina corta logo depois do rodapé, sem puxar papel em
    branco. Diz "Não é documento fiscal" (a NFC-e é com o Fiscal).
- **Aviso quando uma rotina parar:** com um check do Healthchecks.io para cada grupo de
  rotinas, quem cuida da operação recebe o alerta quando o cron para, trava ou falha —
  expiração das pré-reservas, FNRH, backup e fechamento do dia. Até aqui, um cron parado
  só aparecia em vermelho num painel do Railway.
- **Relatórios de receita** (Relatórios → Consolidados):
  - **Carteira (OTB):** o que já está vendido para o mês, dia a dia — quartos-noite,
    ocupação, receita e diária média —, com a pré-reserva separada ("pode cair") e cortes
    por canal e faturamento;
  - **Pickup:** quanto entrou e quanto caiu (cancelamento, retenção vencida, no-show) nos
    últimos 7, 14 ou 30 dias para aquelas datas — se o mês está andando para a frente;
  - **Ritmo de vendas:** quanto do mês foi vendido com 90, 60, 30, 14, 7 e 0 dias de
    antecedência;
  - **Custo de distribuição por canal:** receita bruta, custo estimado e líquida, com os
    percentuais na Tabela de Preços (OTA começa em 18%, venda direta em 0%).
- **Governança — a ronda que confere a ocupação:**
  - na ronda, a camareira registra num toque o que viu em cada quarto (vago, com bagagem,
    sem bagagem). A aba "Discrepâncias" confronta com o sistema e diz o que fazer:
    hóspede que foi embora sem passar na recepção (conta aberta, diária correndo, quarto
    invendável), saída não lançada, hóspede sem check-in lançado, quarto não conferido.
    As divergências do dia entram também na Auditoria. A conferência só aponta: não
    fecha conta nem mexe na reserva — quem corrige é a recepção. A aba de hoje recalcula
    ao vivo (o que a recepção resolve some) e o relatório guarda o que a ronda encontrou
    na hora; para o mesmo dia, os dois podem não bater, de propósito;
  - inspeção da faxina com "Reprovar", que devolve o quarto para a fila, com motivo;
  - três relatórios: faxinas por camareira (por tipo e tempo médio), inspeção e
    retrabalho (com os motivos mais comuns) e discrepâncias da ronda.
- **Testes no navegador no CI:** os testes com navegador de verdade existiam, mas só
  rodavam na máquina de quem tinha o Playwright — no CI, pulavam em silêncio. Agora rodam
  num job próprio a cada push, e ganharam a LP da inauguração (checkbox no lugar, fotos e
  fontes carregando, medição só depois do "Aceitar") e o menu lateral (nenhum ícone pula
  ao recolher).
- **Miúdos:** o botão pequeno de "Voltar" dos relatórios, do kit e do Comercial tinha o
  texto colado no topo; os CSVs do sistema traziam um caractere invisível no começo de
  toda linha (agora só no começo do arquivo, que é onde o Excel precisa); e o cabeçalho
  das colunas de número não alinhava à direita em cerca de 30 telas.

**O que foi modificado**
- **Desempenho (`2e1ae94`, `a40c619`):** `config/settings.py` conecta com `-c jit=off`
  (`DB_JIT=1` religa); `reservas.services`: `configuracao_reservas()` memorizada no lote
  de preços, `precarregar_classificacoes(inicio, fim)` e `precarregar_tarifas_unidade`
  trazendo também as `TarifaTemporada`; `precos.py` lê a configuração por `_config()`;
  `ReservaForm` com `select_related("tipo")`; `comercial.quartos.quartos_para_lead` dentro
  de `precos_em_lote()`; `comercial.services._anotar_tarefa_e_contato()` no funil e
  `AtividadeComercial.TIPOS_CONTATO`.
- **Aviso de cookies (`89b16cd`):** classes `aviso-cookies*` em
  `componentes/consentimento.html`; teste que barra classe repetida entre o aviso e as LPs.
- **LP (`049138e`):** `views_lp._desembutir()` e a view `arquivo_lp` (`/lp/arquivo/<hash>`,
  cache imutável) nas três LPs; canônico, og:url e og:image da inauguração;
  `static/lp/og-inauguracao.jpg`; redirect `/lp/inauguracao/`. O arquivo em `LPs/`
  continua como o design entregou.
- **CI (`5aff095`):** job "Fluxos no navegador" em `testes.yml` (Playwright 1.64.0 +
  Chromium) com `E2E_OBRIGATORIO=1`; `playwright` no `requirements-dev.txt`; testes
  `LpInauguracaoE2ETests` e `MenuLateralE2ETests`.
- **No-show (`f85ea00`):** `ConfiguracaoReservas.no_show_automatico_noites` (migração
  `nucleo.0048`); `reservas.services.marcar_no_shows_vencidos()`; comando
  `marcar_no_shows` no grupo `diarias`, antes do fechamento; `Reserva.desfazer_no_show()`
  e a rota `reservas:desfazer_no_show`; a pendência "no-show provável" diz em que
  madrugada o sistema marca.
- **Monitor das rotinas (`cdddbca`):** `rotinas` avisa `ROTINAS_MONITOR_FREQUENTES` /
  `ROTINAS_MONITOR_DIARIAS` (`/start`, fim e `/fail`, só com o nome da tarefa e o tipo do
  erro); `.env.example`.
- **Cupom (`bbaca7a`):** `templates/componentes/cupom.html` e o bloco "Cupom 80 mm" do
  `app.css` (`@page cupom`); rotas `loja:cupom`, `restaurante:cupom` e `lavanderia:cupom`
  e os botões nas telas da venda, da comanda e da ordem; `nucleo.formatos.qtd_br()`.
- **Receita (`034fabe` a `6825cfe`, merge `f0ef20b`):** `apps/reservas/receita.py` e as
  portas `carteira`, `pickup`, `ritmo_de_vendas` e `custo_distribuicao` em
  `reservas.services`; `Reserva.cancelada_em` (migração `reservas.0031`), preenchida no
  cancelamento, no no-show e na expiração, e limpa no "Desfazer"; custo por canal na
  `ConfiguracaoReservas` (migração `nucleo.0049`, renumerada no merge para vir depois da
  do no-show); CSV com um BOM só (`nucleo/export.py`); `.tabela th.num`.
- **Botão pequeno (`3a62e76`):** `.botao-mini` nasce `inline-flex` centrado.
- **Governança (`f2f84cd`, `0bf4759`, merge `a8a3f1a`):** model `ConferenciaOcupacao` e
  campos de inspeção na `TarefaGovernanca` (migração `governanca.0003`); services
  `registrar_conferencia`, `discrepancias`, `reprovar_inspecao`, `pendencias_auditoria` e
  os três relatórios; rotas `governanca:discrepancias` e `ronda`; abas Limpeza /
  Discrepâncias; `reservas.services.ocupacao_por_uh()`; a Governança na varredura da
  Auditoria.
- **Docs:** README, `docs/ARQUITETURA.md` (variáveis, rotas, rotinas, impressão) e
  `docs/MODULOS_E_FLUXOS.md`.

**Como foi testado**
- **Desempenho:** testes que fixam o número de consultas — o funil com 2 ou 8 leads, o
  lead com 3 quartos × 2 noites ou 12 × 7, o modal com 3 ou 12 quartos — e o `SHOW jit`
  da conexão.
- **LP:** celular emulado em 4G lento (perfil do Lighthouse, mediana de 3); comparação
  pixel a pixel da página inteira em 390 e 1440 px entre o HTML do design e a LP servida
  (só os segundos da contagem regressiva diferem); cada arquivo responde com o tipo certo
  e o conteúdo do próprio hash. O aviso de cookies medido nas três LPs e no site, em 320,
  390 e 1440 px.
- **No-show:** ponta a ponta no servidor local — regra ligada pela tela, a rotina marcou
  as duas confirmadas vencidas, "Desfazer" pela tela devolveu as duas, regra desligada.
- **Cupom:** PDF de impressão do tamanho do cupom (80 × 95 mm numa venda de um item); a
  hora sai em Brasília (a primeira versão escrevia em UTC — 15:12 no cupom, 12:12 na
  tela —, pego no navegador e coberto por teste).
- **Monitor:** pedido de verdade contra um servidor HTTP local; falha chega sem a
  mensagem do erro.
- **Antes de cada merge:** as telas novas da receita e da governança em 320, 390, 821
  (menu aberto) e 1440 px — sem rolagem lateral, nada cortado.
- **Suíte completa no Windows:** 1.450 testes no `a8a3f1a` (eram 1.324 no bloco anterior), os 10 de navegador inclusive, só a falha conhecida do ambiente (`test_webhook_audio_baixa_e_salva_arquivo`, que só falha no Windows). Ruff zero, `makemigrations --check` limpo.

**Depois do deploy (no Railway)**
- As migrações (`nucleo.0048`, `nucleo.0049`, `reservas.0031`, `governanca.0003`) o deploy
  roda sozinho.
- Decisões da pousada, nenhuma obrigatória:
  - ligar o no-show automático (sugestão: "1 dia de tolerância", que dá à recepção a
    manhã inteira);
  - conferir os percentuais de custo por canal na Tabela de Preços (OTA 18%; site,
    WhatsApp e balcão em 0% — o Pix sai por BR Code, sem taxa; quando o cartão entrar, é
    editar o número);
  - a comissão de agência aparece no relatório de distribuição só como **estimativa**
    (pela comissão do cadastro), abaixo do total e fora da receita líquida, até a pousada
    decidir se ela é desconto na diária, despesa comercial ou repasse — e quando nasce;
  - Governança: se "ocupado sem bagagem" no meio da estadia deve virar achado (hoje é
    aviso leve) e se a ronda deve ter horário-limite (hoje há "não conferido", não "ronda
    atrasada").
- O pickup conta as saídas da carteira daqui para a frente: cancelamento anterior a esta
  versão não aparece na coluna "Saiu" (a tela avisa).
- Opcional, recomendado: criar no Healthchecks.io um check para cada grupo de rotinas e
  pôr as URLs em `ROTINAS_MONITOR_FREQUENTES` e `ROTINAS_MONITOR_DIARIAS` nos dois
  serviços de cron.
- Impressora térmica: na caixa de impressão do navegador é só escolher a térmica — o
  tamanho do papel e as margens vêm do próprio cupom.

---

## 21/10/2026 — O menu que não pula, o kit de contingência, as regras do Réveillon e o aceite da política (`28524ef` a `d60824b`)

Nono bloco. Começou por um pedido sobre o menu — "aquela sidebar tem vários elementos
que quando expande/contrai ficam meio fora, tipo overlap e extrusão" — e seguiu pelas
pendências da auditoria que ainda estavam abertas. O kit de contingência e as
restrições de venda foram feitos por agentes em cópias separadas do código e revisados
no navegador antes do merge. O original não ganhou commit novo
desde o último push (o `main` do fork foi sincronizado com o dele, que já estava todo no
`dev`).

**O que melhorou**
- **Abrir e recolher o menu:** o bloco anterior tinha medido só os dois estados finais;
  desta vez a animação foi filmada quadro a quadro (pausada de 20 em 20 ms):
  - abrindo, no primeiro quadro a cápsula "MFA off" saía 75 px por cima da página e o
    avatar encostava no Sair; até os 40 ms os nomes dos itens saíam das pílulas e do
    "Nova reserva", e o menu acendia uma barra de rolagem lateral;
  - recolhendo, todos os ícones pulavam para o meio do menu e voltavam deslizando, e
    os itens subiam — o último, 313 px;
  - agora o menu recolhido é o menu aberto recortado pela borda: ícones, avatar e
    símbolo não saem do lugar em nenhum quadro, os nomes esmaecem (saem antes de a
    largura fechar, entram depois que ela abriu), o botão de recolher e o Sair deslizam
    até o lugar novo, e nada passa da borda. No recolhido, os grupos ganham um fio de
    separação no lugar do título;
  - com o menu aberto, ícones e textos andaram 5 px para a direita (para alinhar com o
    recolhido). A gaveta do celular segue a mesma, com esse ajuste.
- **Kit de contingência (para quando a internet cair):** uma folha A4 do dia, em
  Reservas → "Kit de contingência" (botão na lista e no mapa de quartos, e no ⌘K):
  - hospedados agora, quarto a quarto, com os hóspedes, entrada → saída e o **saldo da
    conta**; chegadas de hoje com o **telefone** do hóspede, o total e o que já foi
    pago; saídas de hoje com o saldo a receber; a situação dos 24 quartos (com a
    limpeza, quando a Governança está ligada); chegadas de amanhã; e os totais;
  - sai limpa na impressora — e, de quebra, qualquer tela do CRM mandada para a
    impressora deixou de imprimir o menu, a barra de cima e os botões;
  - cópia automática por e-mail toda madrugada para quem estiver em
    `KIT_CONTINGENCIA_EMAILS` (vazio = não manda nada): com a internet da pousada fora
    do ar, o retrato do dia abre no celular, no 4G.
- **Restrições de venda (Réveillon e feriados):** até aqui o site vendia a noite solta de
  31/12 e deixava as noites ao redor vazias. Agora, em Temporadas → "Restrições de
  venda", dá para definir por período — na casa toda, num tipo de quarto ou num quarto:
  - estadia mínima (vale para qualquer estadia que toque o período; com várias regras,
    vale o maior mínimo), fechado para chegada, fechado para saída e parar vendas;
  - no site, a busca não oferece o que a regra barra e **diz o motivo** ("Réveillon —
    mínimo 3 noites: com entrada em 31/12, a saída precisa ser a partir de 03/01"),
    com atalho para escolher outras datas; um envio forjado também é recusado;
  - na recepção, a regra aparece como aviso ao vivo no formulário e não trava — hóspede
    no balcão se negocia. "Parar vendas" é a exceção: só a gerência passa, e fica
    registrado na trilha com o motivo. A conversão de lead do Comercial não trava;
  - regra desativada fica guardada (o Réveillon deste ano serve de molde para o próximo).
- **Reserva pelo site — aceite da política de cancelamento:**
  - para concluir, o hóspede marca "Li e aceito a política de cancelamento e os termos
    de serviço" (o navegador não deixa confirmar sem; o servidor confere de novo);
  - a reserva guarda quando ele aceitou e o texto que estava na tela, e o e-mail de
    confirmação leva os dois — numa disputa, dá para provar o que ele viu;
  - os termos de serviço diziam "devolução de 90% dentro dos 7 dias", e o sistema
    devolve 100% (o que o CDC pede para venda pela internet). Agora os termos saem da
    mesma configuração do resumo e do cálculo da devolução.
- **"Retemos 1E+1% do valor total":** era o que o passo 4 da reserva mostrava ao
  hóspede, e "reter 1E+1%" o que o cancelamento no CRM gravava no motivo. Agora "10%".
- **Minha reserva:** o exemplo do código tinha 4 caracteres no fim; o código real tem 6.
- **LGPD — Google e Meta só com licença:** as três landing pages (Fundador, Fundador II
  e a da inauguração, com campanha no ar) carregavam GA4 e Meta Pixel na hora, sem
  aviso de cookies; o `<noscript>` do Pixel disparava até sem JavaScript. Agora nada
  carrega antes do "Aceitar", e no "Recusar" nada carrega.
- **Visual:**
  - a tela do lead tinha 33 cores escritas à mão no próprio estilo (e quatro "tokens"
    que nem existiam); agora tudo sai dos tokens da casa, e um teste impede a volta em
    qualquer tela do CRM;
  - **sem emoji nas telas do CRM:** eram 66, em 21 telas — rótulos ("⏱ Tempo de
    casa"), filtros ("🌅 Vista lago"), estados vazios ("Nada pendente. 🎉"), status
    ("🟢 janela 24h aberta") e até os botões de anexar e gravar áudio do WhatsApp. O
    decorativo saiu, o status ficou na cor e no selo que já existiam, e os botões viraram
    os ícones da casa. Emoji muda de desenho em cada aparelho e enchia a tela como as
    pílulas enchiam. Site, e-mails e páginas públicas de captação ficaram como estão.
- **Para o original:** as correções que valem também para a produção do Gefferson (R$
  cem vezes maior, "1E+1%", termos × sistema e o aviso de cookies, que lá nem existe)
  foram preparadas como patches em cima do `main` dele, para ele aplicar.

**O que foi modificado**
- **`static/css/app.css` (`28524ef`):** seção da sidebar reescrita — tokens
  `--sidebar-w-aberta`, `--trilho-w`, `--trilho-centro`, `--sidebar-ico-x` e `--alvo`;
  `.sidebar` com `overflow: hidden`; topo com posições fixas a partir da borda esquerda
  e janela do logotipo (`.marca-janela`); rótulos e títulos no fluxo; rodapé com altura
  animada e o Sair posicionado; o trilho (`.app.recolhida …`) só mexe em opacidade, cor,
  giro e posição. `templates/base.html`: `.marca-janela` e `.usuario-texto`.
- **`apps/nucleo/formatos.py` (`68d7e99`):** `pct_br()`, usado no resumo da política, na
  nota do cancelamento e na descrição do ISS.
- **Site (`2303d6b`, `994a48a`):** `core.Reserva` ganhou `politica_aceita_em` e
  `politica_aceita` (migração `core.0009`); passo 4 com a caixa de aceite; os dois
  caminhos de `finalizar_reserva` conferem o aceite; e-mail de confirmação (HTML e
  texto); termos de serviço a partir de `descricao_politica()`; exemplo do código em
  Minha reserva.
- **LPs (`35f4eaf`):** tags de medição como `type="text/plain" data-consentimento`
  nos três arquivos de `LPs/`; `views_lp._com_aviso_de_cookies()` põe o aviso do site
  no fim do `<body>` ao servir cada LP.
- **Cores (`f4ab374`):** `comercial/oportunidade.html` e mais quatro telas só com
  tokens; teste `CorSoPorTokenTests`.
- **Emoji (`b8bf5c0`):** 21 templates do CRM; SVG `.ico` nos botões de anexo e áudio
  da conversa e no cadeado da Central de Módulos; ponto dourado no feriado do
  calendário do colaborador (`.rc-dia .ferm`); teste `SemEmojiNoCrmTests`.
- **Kit (`34d6edb`, `b8cf2d0`):** `reservas.services.kit_contingencia()` (consultas
  constantes: reservas numa consulta, saldos em lote, limpeza pelo mesmo caminho do
  mapa), view `reservas:kit` e `templates/reservas/kit.html`; comando
  `enviar_kit_contingencia` no grupo `diarias` de `rotinas`, com e-mail HTML (estilo
  inline) e texto; `KIT_CONTINGENCIA_EMAILS` no settings e no `.env.example`;
  `Reserva.total_previsto(cfg)` e `precos.taxas(…, cfg)` aceitam a configuração já
  carregada; `@media print` da casa no `app.css` (e no `base.css`).
- **Restrições (`9a1b727` a `3a0bc43`):** model `RestricaoVenda` (migração
  `reservas.0030`, CheckConstraints de escopo e de datas) e os services
  `restricoes_da_estadia()` e `restricoes_no_periodo()`; `criar_prereserva(…,
  respeitar_restricoes=)` — o canal site bloqueia, os internos avisam; busca e passos
  do site; modal de nova reserva (`tarifa_preview` devolve as violações); telas
  `reservas/restricoes.html` e `restricao_form.html` (área Temporadas); trilha lê
  "restrição de venda"; duas correções do design system que a tela achou (caixa de
  marcar com texto de ajuda e duas ações na mesma célula).
- **Testes:** 4 contratos novos da sidebar e 4 reescritos para o desenho novo; cor só
  por token; aceite da política (sem aceite não há reserva, com aceite fica gravado,
  e-mail, termos); percentual; LPs sem tag solta; nenhum emoji em tela do CRM; kit
  (24, em `tests_kit.py`);
  restrições (47 em `tests_restricoes.py` e 9 no site).

**Como foi testado**
- **Menu, quadro a quadro** (0 a 300 ms, abrindo e recolhendo, a 1440 px com mouse e a
  1024 px com toque): texto ou caixa fora do menu 2–3 quadros → 0; sobreposições 3 → 0;
  barra lateral 3 quadros → 0; o x de cada ícone e o y de cada item constantes nos dois
  sentidos (antes, até 313 px). Estados finais conferidos por captura; a gaveta sai
  idêntica com o menu salvo recolhido ou aberto; Tab pelo menu nos dois estados com
  todos os anéis de foco inteiros.
- **Aceite:** POST sem a caixa, pelos dois caminhos (por tipo e por quarto), não cria
  recibo nem pré-reserva; no navegador, sem marcar, o envio é barrado; o teste de ponta
  a ponta marca a caixa e conclui a reserva.
- **LPs no navegador:** zero requisições a Google/Meta antes da escolha em todas; o
  Pixel carrega depois do "Aceitar". A da inauguração (que só mede no domínio oficial)
  foi servida sob www.pousadavotesta.com.br para conferir: carrega depois do "Aceitar",
  sem erro de JavaScript.
- **Cores:** captura da tela do lead antes × depois — maior diferença de 4/255 num
  canal, nenhum pixel acima de 8.
- **Kit e restrições, na revisão antes do merge:** as telas novas (kit, lista e
  formulário de restrições, Temporadas) a 1440 px com o menu recolhido e aberto, 821 px
  com o menu aberto, 390 e 320 px — sem rolagem lateral, nada saindo da tela, nenhum
  texto cortado sem reticências. Kit em PDF A4 real: 3 páginas, tabelas inteiras. Site
  no Réveillon (390 e 1440 px): aviso com o motivo e atalho; a estadia de 4 noites que
  atravessa o período passa. Modal da recepção: aviso ao vivo.
- **Depois do merge:** as duas novidades do site nasceram em paralelo, e a suíte
  apontou o encontro — os testes das restrições postavam a reserva sem o aceite da
  política. Um deles falhou; outros dois continuavam verdes pelo motivo errado (a
  recusa vinha do aceite, não da regra). Ajustados (`d60824b`) para cada um provar o
  que diz.
- **Suíte completa no Windows:** 1.324 testes no `d60824b` (antes dos merges, 1.243 no
  `f4ab374`), só a falha conhecida do ambiente (`test_webhook_audio_baixa_e_salva_arquivo`,
  que só falha no Windows). Ruff zero, `makemigrations --check` limpo, `base.css` em dia.

**Depois do deploy (no Railway)**
- As migrações (`core.0009` e `reservas.0030`) o deploy já roda sozinho.
- Opcional: `KIT_CONTINGENCIA_EMAILS` com os e-mails de quem deve receber a folha do dia.
- Operação, não código: cadastrar a regra do Réveillon em Temporadas → "Restrições de
  venda" (ex.: 30/12 a 01/01, mínimo 3 noites) antes de abrir as vendas do feriado. No
  campo de descrição, só o nome do período ("Réveillon"): ele entra na frase que o
  hóspede lê — "Réveillon: a estadia mínima é de 3 noites. Com entrada em 31/12, a saída
  precisa ser a partir de 03/01."

---

## 21/10/2026 — Menus, o que vaza e o que corta, e o sistema inteiro no celular (`e650640` a `7ea1ce2`)

Oitavo bloco: um pente-fino na interface pedido com estas palavras — "atenção na
interface dos menus, dos menus colapsados, das animações, o que fica de dentro e o que
fica de fora, e tudo fully responsive". Medido no navegador, tela por tela, em oito
larguras (320 a 1440 px) e nos três estados do menu (aberto, recolhido e gaveta do
celular). O original não ganhou commit novo desde o último push.

**O que melhorou**
- **Menu recolhido (o trilho de ícones, que é o padrão do sistema):**
  - cada ícone tem nome: o leitor de tela anunciava "link" 32 vezes e o mouse não
    mostrava dica nenhuma. Agora a dica aparece ao passar o mouse — só no trilho; com o
    menu aberto o nome já está escrito ao lado;
  - o rodapé do usuário (avatar, nome e "MFA off") vazava 27 px para fora do menu em
    todas as telas. No trilho fica só o avatar, e o aviso do MFA vira um ponto;
  - ao recolher ou abrir, o menu inteiro saltava 52 px num quadro só. Agora só a
    largura anima;
  - a cartola do topo voltou a ser clicável (leva à Visão geral), e o botão diz o que
    vai fazer: "Expandir menu" ou "Recolher menu".
- **Menu no celular e no tablet (a gaveta):**
  - fechada, continuava "existindo" para o teclado: 39 links invisíveis antes do
    conteúdo. Agora some de verdade;
  - aberta, funciona como janela: o Tab não foge para a página de trás, a página não
    rola por baixo, Esc fecha e o foco volta ao botão;
  - abre inteira mesmo para quem deixou o menu recolhido no computador — antes o
    logotipo saía cortado ao meio e o "MFA off" perdia a forma;
  - botão do menu de 38 para 44 px, véu que entra suave, e o movimento obedece a quem
    pede menos animação no aparelho.
- **Menu do site no celular:** as mesmas correções (11 links invisíveis no Tab, foco
  que escapava, botão que dizia "Abrir menu" com o menu já aberto). Botão de 40 para
  48 px — é o que o hóspede mais toca.
- **Nada vaza nem é cortado sem avisar:**
  - período personalizado dos relatórios e da trilha: no celular a segunda data
    simplesmente não aparecia. Agora as duas empilham;
  - mapa de reservas: nome de ala comprido era cortado junto com a tabela. Agora
    reticências, e o nome inteiro ao passar o mouse;
  - com o menu aberto num tablet deitado (821 px), o painel lateral de Manutenção e
    Pagamentos virava uma tira de 154 px, com selects de 10 px, e a página rolava de
    lado. Agora ele desce para baixo do conteúdo quando não cabe — no desktop, a
    proporção é a mesma de antes;
  - na mesma largura, o corredor de quartos da Visão geral cortava a data e o saldo das
    24 portas ("R$ 2.6…") e o selo PCD subia em cima da situação. Agora são quatro
    portas por fileira, e tudo aparece;
  - também a 821 px com o menu aberto, a tabela de Pessoas (e Hóspedes, Agências,
    Empresas e Fornecedores, que são a mesma tela) espremia seis colunas em 486 px:
    cabeçalhos encostados, "SITUAÇÃO" cortado, "Ati/va" e o CNPJ em três linhas.
    Agora, com a tabela estreita, ficam Nome e Papéis, como no celular; a 1024 px com
    o menu aberto, as seis colunas cabem inteiras;
  - a lista de Páginas cortava a coluna das ações; agora rola de lado;
  - tabelas pararam de quebrar palavra no meio ("Revisã/o do/ar-condi/ciona/do");
  - corredor de quartos, "Precisa de atenção", urgências do Marketing, BOH, Central de
    Módulos, ficha da OS e semana da Escala deixaram de vazar no celular; o "Enviar" do
    WhatsApp no lead deixou de ficar 118 px fora da tela;
  - nenhuma tela rola de lado em nenhuma das oito larguras.
- **Toque:** 223 alvos abaixo de 44 px no dedo viraram 2 — dois links no meio de uma
  frase, que a regra de acessibilidade isenta. Inclui portal do hóspede, página de
  pagamento e login, que ficavam fora da regra, e as respostas rápidas do WhatsApp.
- **Menus que flutuam:** a lista do combo (hóspede, quarto) abre para cima quando não
  cabe embaixo, em vez de sair da tela; a gaveta do Marketing entra deslizando; a gaveta
  do funil no celular usa os tempos da casa.
- **CI:** a máquina dos testes fica presa no Ubuntu 24.04 até a abertura. O GitHub troca
  o "ubuntu-latest" para o 26 a partir de 19/10, e trocar o ambiente de teste na semana
  da abertura é risco à toa.

**O que foi modificado**
- **`static/css/app.css`:**
  - o trilho inteiro (`.app.recolhida …`) num único `@media (width > 820px)`; a gaveta
    não tem mais nada a desfazer. Tokens novos: `--sidebar-topo-h` e `--vao-2-1`;
  - gaveta com `visibility` + tokens de movimento; `body.sem-rolagem`;
  - `.colunas-2-1` e `.ficha-cols` de grid com ponto de corte para `flex-wrap` (quem
    decide é o espaço, não a janela);
  - grades elásticas em `minmax(min(Npx, 100%), 1fr)`; `.tabela td` com
    `overflow-wrap: break-word`;
  - as primeiras container queries da casa: o `.corredor-hero` conta as colunas do
    corredor pela largura dele, e o invólucro da tabela de Pessoas decide quais colunas
    mostrar (Situação passou de 10% para 12%); `.quadro:has(> table:not(.tabela))` rola
    de lado;
  - alvos de 44 px no ponteiro grosso, inclusive fora da casca do CRM.
- **`templates/base.html`:** `title` em cada item do menu e `rotularSidebar()` (rótulo
  do botão e dica só no trilho); a gaveta como diálogo (foco preso, `aria-expanded`,
  foco devolvido); o combo escolhe o lado antes de abrir (`posicionar()`).
- **Site:** `main.js`, `partials/header.html` e `animations.css` (menu do celular como
  diálogo).
- **Comercial e Reservas:** funil (tokens na gaveta do celular), lead (caixa do
  WhatsApp), mapa (`title` na coluna do quarto).
- **`static/css/base.css`** regerado, com 8 seletores novos no manifesto.
- **Testes de contrato:** 31 novos em `apps/nucleo/tests_design.py`
  (`MenuLateralTests`, `DentroDoContainerTests`, `FlutuantesTests`, `MenuDoSiteTests`).
- **`.github/workflows/*.yml`:** `runs-on: ubuntu-24.04`.

**Como foi testado**
- **Varredura no navegador** (Playwright): 59 telas × 8 larguras × estado do menu,
  medindo caixa por caixa. Vazamentos 390 → 1 (o valor da barra selecionada no
  relatório do Marketing, que passa 6 px da própria coluna no celular, sem cobrir
  nada); cortes calados 51 → 14 na varredura, e os 14 medidos um a um depois e
  corrigidos (tabela de Pessoas, corredor a 821 px e lista de Páginas); elementos fora
  da tela 500 → 0; telas com rolagem lateral 8 → 0.
- **Quadro a quadro, com animação ligada:** o maior salto do topo do menu numa
  transição foi de 52 px para 0,6 px, nos dois sentidos.
- **Teclado:** com a gaveta fechada, o Tab entra nela 0 vezes em 12; aberta, o foco não
  escapa em 20 Tabs.
- **Pixel:** das 59 telas a 1440 px, 46 mudam só na faixa do menu; as outras 13 são as
  mudanças de propósito.
- **Revisão independente** do trabalho, antes do merge: 6 problemas corrigidos, cada um
  com medida antes e depois — a gaveta herdando o trilho, o "Enviar" esticado para
  363 px no desktop, um ajuste do celular que nunca valia (achado por um verificador de
  cascata), a coluna cortada na lista de Páginas, o corredor e a tabela de Pessoas a
  821 px. Este último a revisão tinha descartado por engano (procurou elemento passando
  da borda, e o que passava era texto dentro da célula); o próprio agente apontou o
  erro na resposta final, e a nova medida, célula a célula, deu razão a ele.
- **Suíte completa no Windows:** 1.226 testes no `f862b31`, só a falha conhecida do
  ambiente (`test_webhook_audio_baixa_e_salva_arquivo`, que só falha no Windows). O
  último commit (`7ea1ce2`, só CSS e um contrato) passou nos 93 testes de design. Ruff
  zero, `makemigrations --check` limpo, `gerar_base_css --conferir` em dia.

**Depois do deploy (no Railway)**
- Nada.

---

## 21/10/2026 — Pendências do visual, novidades do original e o R$ que saía cem vezes maior (`158133c` a `f80d989`)

Sétimo bloco: as pendências do visual da auditoria, os sete commits que o original
ganhou entre a noite de 20/10 e a madrugada de 21/10 (já adaptados às regras do fork)
e um bug antigo de dinheiro que eles deixaram à vista.

**O que melhorou**
- **Valor em R$ que voltava do servidor saía cem vezes maior.** O campo de R$ tira os
  pontos de milhar no envio. Um valor preenchido pelo servidor, como "650.00" vindo
  da cotação, chegava ao backend como 65000. No «Ganhar», uma cotação convertida sem
  mexer no campo virava diária cem vezes maior. O mesmo valia para qualquer formulário
  de R$ que voltasse com erro na tela. Agora o campo já vem como "650,00". O bug é de
  julho/2026 e **existe em produção no original**.
- **Novidades do original** (Comercial):
  - reabrir ou mover para qualquer etapa um lead ganho ou perdido, com permissão
    própria (área `comercial_fechados`);
  - no «Ganhar»:
    - a diária da tabela de preços aparece, e a diferença para a diária vendida fica
      na linha do tempo;
    - o total da reserva aparece ao vivo;
    - o sinal pode ser em R$ ou em %, sem o padrão de 30%;
  - a barra de rolagem do funil virou trilho + polegar e não treme mais;
  - a Tabela de Preços usa a largura toda;
  - o detalhe da reserva ganhou o cartão "Financeiro" (previsto, recebido, sinal
    pendente, saldo e as cobranças com o link de pagamento), e "reserva #N" na linha
    do tempo do lead vira link.
- **O que foi corrigido nelas ao juntar:**
  - tirar um lead do Ganho cancela a reserva e devolve o que foi pago pelo caminho do
    fork, a mesma devolução da tela da reserva. O código original quebrava com sinal
    pago online e tentava estornar um estorno;
  - pagamento online bloqueia o movimento e diz o valor a estornar em Pagamentos;
  - voltar para Ganho exige uma reserva ativa;
  - na tela, reabrir funciona: o campo "motivo da perda", escondido, impedia o envio
    do formulário para qualquer etapa que não fosse «Perdido". O original chegou à
    mesma correção na mesma noite, e ficou a versão dele;
  - o sinal digitado como "150.50" virava 15050. Agora o ponto com até duas casas é
    decimal;
  - a regra da Tabela de Preços mudou de lugar: onde estava, perdia para a dos
    620 px, que tem a mesma especificidade;
  - o "Recebido" do painel financeiro contava duas vezes o sinal pago online: no
    fork, a cobrança paga já vira crédito na reserva. Agora é o total pago de
    verdade, inclusive o pago na conta depois do check-in.
- **CRM sem estilo escrito na tag:**
  - os 610 `style="…"` estáticos viraram classe do design system (Marketing tinha 352);
  - um teste impede que voltem, em qualquer tela;
  - o funil perdeu as cápsulas de enfeite: origem e campanha viram texto, temperatura
    e reativado viram selo, e fica uma cápsula por cartão.
- **Portal do hóspede e página de pagamento mais leves:** baixam 6 KB de CSS (comprimido)
  em vez de 52 KB, só o que usam do design system, gerado do `app.css`.
- **Site:**
  - os avisos e erros saem nas cores da casa, as mesmas do CRM. O erro de campo da
    reserva passou de contraste 3,8:1 para ~7:1;
  - a vitrine dos 24 quartos ganhou filtro por pessoas, tipo e qualidades, e ordem por
    preço e por nome. O filtro fica no link, para mandar pelo WhatsApp.
- **Mapa de reservas no celular:** a barra da reserva e o "+" da célula livre passaram
  de ~25 px para 40–44 px de toque.
- **Marketing:** a gaveta da campanha aberta pelo Quadro deixou de mostrar o ✕ e o ⧉
  como botão cru do navegador.

**O que foi modificado**
- **Merges do original:**
  - `eed0969` (cadb560), `6517a9c` (7147d78 e b95b158) e `8e5902e` (2abef84, 23908e5
    e 379fe9d) e `f80d989` (fdebccc);
  - Reservas ganhou `situacao_da_venda`, `exigir_venda_desfazivel` e `desfazer_venda`.
    O Comercial não importa mais o model de Reserva;
  - Pagamentos ganhou `cobrancas_da_reserva`. Reservas não importa mais o model de
    Pagamentos.
- **Núcleo:**
  - `ReaisInput` agora no `apps/nucleo/forms.py`, usado por Comercial e Reservas;
  - `apps/nucleo/css_publico.py`, o manifesto `css_publico.txt` e o comando
    `gerar_base_css`, que gera o `static/css/base.css`.
- **CSS:**
  - as classes do lote de estilos (`.op-*`, `.mk-*`, `.lp-*`, modificadores
    `.bloco-*`);
  - `.qr-hospede*`, `.mkt-btn-ghost` e `.mkt-meta` no `app.css`;
  - no site, cores semânticas no Tailwind (`perigo`, `alerta`, `sucesso`, `info`),
    com o CSS do site recompilado.
- **Site:**
  - vitrine: `quartos_todos` com os filtros e `static/site/js/vitrine.js`;
  - `.cartao-hospede` no Tailwind.
- **Testes de contrato:** `EstiloForaDoAtributoTests`, ampliado para o sistema todo,
  e `CssDasTelasPublicasTests`.
- **Documentação:** `CLAUDE.md` e `docs/ARQUITETURA.md` (o recorte do CSS e o
  comando).

**Como foi testado**
- **Visual:**
  - cada mudança com capturas antes e depois, iguais pixel a pixel onde nada devia
    mudar;
  - o lote de estilos conferiu o estilo computado de 13.991 elementos em 88 telas,
    170 de 182 capturas idênticas, e as 12 restantes são mudanças de propósito ou
    telas que não se repetem sozinhas;
  - portal e pagamento com o CSS recortado: estilo computado de 880 elementos, 14 de
    14 telas iguais, e pixel 14 de 14.
- **Dinheiro:**
  - testes novos para o widget de R$;
  - mover lead fechado: os 11 testes do original mais 6 do fork (pago online, Ganho
    com reserva cancelada, duplo clique, estorno que desfaz o crédito sem reter nada,
    e o motivo no formulário);
  - no navegador, a ida e volta do campo de R$: "10.000,00" chega como 10000.00 e
    antes chegava como 1.000.000.
- **Um teste que dependia do dia:** o selo da temporada do site usava "hoje + 30"
  e, rodado em 21/10, caiu em 20/11 (Consciência Negra). Agora pula feriado.
- **Suíte completa no Windows:** 1.196 testes, só a falha conhecida do ambiente
  (`test_webhook_audio_baixa_e_salva_arquivo`, que só falha no Windows). Ruff zero,
  `makemigrations --check` limpo, `gerar_base_css --conferir` em dia.

**Depois do deploy (no Railway)**
- Nada obrigatório. Quem mexer no `app.css` numa regra do portal ou do pagamento roda
  `manage.py gerar_base_css`; o teste avisa quando esquecer.
- **Para o original:** o bug do R$ cem vezes maior está em produção lá. A correção é
  o `ReaisInput.format_value` deste bloco, que dá para levar como está.

---

## 20/10/2026 — Visual sem excesso de pílulas, fechamento do dia e base em dia (`e40ab34` a `f971a4d`)

Sexto bloco: o pedido do dono sobre o visual saturado de pílulas, o último item "alto" da
auditoria de Reservas (diárias e fechamento do dia) e a manutenção da base (dependências,
CI, linter e documentação).

**O que melhorou**
- **Menos pílulas, visual mais limpo** (pedido do dono: "pills em tudo, saturado demais"):
  - status neutro virou bolinha + texto; cápsula preenchida só no que pede ação;
  - tipo, papel, canal e categoria viraram texto discreto; filtros viraram controles;
  - pílulas preenchidas nas telas do CRM: **252 → 28** (Pessoas 78 → 1, Auditoria
    26 → 0, lista de Reservas 24 → 0, Governança 25 → 1, Central de Módulos 20 → 1,
    Marketing 25 → 8).
- **Polimento do visual inteiro:**
  - nenhuma tela rola para o lado no celular, e os botões têm 44 px no toque;
  - as cinco cores da marca têm um valor só no CRM e no site, e há uma forma única de
    botão;
  - formulários sem "Nome:", sem "---------" e com as mensagens de validação em
    português;
  - corredor da recepção legível (nome inteiro, dinheiro à direita);
  - movimento suave: transição entre telas, esqueleto de carregamento e avisos na base
    da tela com ícone. Tudo desligado para quem pede menos movimento no aparelho;
  - fichas e listas com hierarquia. No site, o botão do funil volta a ser dourado e os
    rótulos ficam legíveis. No portal do hóspede, a FNRH abre uma ficha por vez;
  - dinheiro em pt-BR em 88 lugares que ainda mostravam o número cru.
- **Fechamento do dia (auditoria noturna).** Toda madrugada a rotina grava o retrato do
  dia anterior, que nunca muda: ocupação, chegadas, saídas, no-shows, diárias, ADR,
  consumo e saldo em aberto. Fica em Auditoria → Fechamentos do dia, com os totais do
  mês e CSV para a gerência.
- **Diária conta pela noite.**
  - A receita dos relatórios entra no mês da noite, não no do check-in: antes, uma
    estadia de 28/10 a 03/11 caía inteira em outubro.
  - As diárias já lançadas foram acertadas pela data que está na descrição.
- **Ocupação só de quartos.** O relatório de ocupação e o gráfico do painel deixam o day
  use de fora. Antes, as unidades de day use contavam como quartos: a taxa ficava menor
  do que a real e o preço do day use entrava no ADR.
- **Listas paginadas.**
  - Pessoas carregava a base inteira; as outras listas cortavam em 100, 200 ou 300 sem
    avisar. Agora todas mostram 50 por página (a trilha, o kardex e os lançamentos,
    100), com busca e filtros mantidos.
  - No celular, Pessoas mostra nome e papéis inteiros.
- **Segurança e manutenção:**
  - Django 6.0.9 (quatro correções de segurança) e gunicorn 26.2.0 (cabeçalhos HTTP
    mais rígidos);
  - a checagem de segurança do CI volta a passar. Estava vermelha desde 19/10 por um
    alarme falso das ferramentas do próprio CI;
  - ações do GitHub em Node 24; linter (ruff) zerado e cobrado no CI;
  - `CLAUDE.md` com as regras novas: dinheiro, concorrência, autoria das ações,
    formulários públicos, pílulas, paginação e movimento.

**O que foi modificado**
- **Migrations:**
  - `reservas.0028`: competência do lançamento, com o acerto das diárias antigas;
  - `reservas.0029`: fechamento do dia.
- **Serviços e comandos:**
  - Reservas: `fechar_dia`, `fechamentos` e `lancar_na_conta(..., competencia=)`;
  - comando `fechar_dia`, o primeiro do grupo diário do `rotinas`;
  - núcleo: `apps/nucleo/paginacao.py` (`paginar`) + `templates/componentes/paginacao.html`
    e o filtro `milhar`.
- **Tela nova:** `auditoria:fechamentos`.
- **CSS:** `.selo--acao`, `.rotulo-dado`, `.filtro-chip`, `.paginacao`; tokens de
  movimento `--mov-*` e `--curva*`.
- **CI:**
  - `security.yml`: pip-audit só no `requirements.txt`; ações v7/v3;
  - `testes.yml`: passo do ruff.
- **Dependências:** Django 6.0.9, gunicorn 26.2.0, psycopg 3.3.6, python-dotenv 1.2.4,
  boto3 1.43.116.
- **Documentação:** `CLAUDE.md`, `docs/MODULOS_E_FLUXOS.md`, `docs/ARQUITETURA.md`.

**Como foi testado**
- **Visual:**
  - as apps mexidas a cada lote e a suíte inteira no fim do ramo;
  - 192 capturas do "depois" (desktop, tablet e celular) e contagem automática das
    pílulas por tela.
- **Testes novos**, entre eles:
  - estadia que vira o mês e ADR calculado com as mesmas noites;
  - day use fora da ocupação;
  - fechamento do dia: os números, não refaz, não edita, e o comando;
  - tela dos fechamentos: a gerência exporta, o operador não;
  - paginação: página estável, página inválida, busca mantida;
  - regras de design: selo, movimento e botões.
- **Suíte e checagens:**
  - suíte completa no Windows: 1.150 testes, só a falha conhecida do ambiente
    (`test_webhook_audio_baixa_e_salva_arquivo`, que só falha no Windows);
  - dependências novas testadas num ambiente separado;
  - `pip-audit -r requirements.txt` sem vulnerabilidade;
  - bandit e ruff de segurança limpos;
  - `check --deploy` sem aviso.

**Depois do deploy (no Railway)**
- Nada obrigatório: as migrations rodam sozinhas e o `fechar_dia` já faz parte do cron
  diário. O fechamento só aparece se o serviço de cron das rotinas diárias estiver
  criado (config em `deploy/railway.rotinas-diarias.json`).

---

## 20/10/2026 — Operação da recepção, fiscal e limpeza de código (`2cc35b1` a `f0441b0`)

Quinto bloco: o que faltava da operação de Reservas, a preparação fiscal e a limpeza de
código apontada na auditoria.

**O que melhorou**
- **Menores de idade (ECA, art. 82).**
  - A ficha FNRH pergunta se o menor está com os pais, com o responsável legal ou com um
    adulto autorizado por escrito; a recepção confere a autorização.
  - O check-in só passa com isso em ordem.
- **Arrumação diária.** Toda manhã a Governança recebe uma arrumação para cada quarto em
  que o hóspede continua (quem sai no dia já tem a faxina do check-out).
- **No-show provável.** Reserva confirmada cuja entrada passou sem check-in aparece na
  Auditoria para a recepção decidir.
- **Horários de check-in e check-out** configuráveis na Tabela de Preços (padrão 14h e
  12h) e mostrados na confirmação e no e-mail.
- **Fiscal:**
  - IBS e CBS da reforma tributária destacados no documento fiscal (fase de teste de 2026:
    0,9% e 0,1%);
  - os PDVs avisam que a venda de produto está sem NFC-e enquanto não houver Inscrição
    Estadual, com bloqueio opcional para o contador decidir.
- **LGPD:** as políticas de privacidade identificam o encarregado pelos dados (nome e
  e-mail configuráveis).
- **Relatórios** com dinheiro em pt-BR ("R$ 1.234,56").
- **Webhook de pagamento** de uma cobrança que não é nossa responde 200 (o provedor para
  de reenviar). O estoque de colchões e berços nunca vira duas linhas.
- **Código mais limpo:**
  - os três endpoints de lead das LPs viraram um caminho só (a LP Fundador ganhou o
    enriquecimento do lead que faltava);
  - saiu o motor antigo de preço do site;
  - o rótulo do pagamento do site não fala mais em Mercado Pago.

**O que foi modificado**
- **Migrations:**
  - `reservas.0027`: campos do menor na FNRH;
  - `nucleo.0047`: horários de entrada e saída;
  - `fiscal.0002`: IBS/CBS;
  - `core.0008`: rótulo do pagamento.
- **Serviços:**
  - Governança: `gerar_arrumacoes_do_dia` e o comando `gerar_arrumacoes`, no grupo
    diário do `rotinas`;
  - Reservas: `uhs_em_permanencia`, `Reserva.menores_pendentes`;
  - Fiscal: `ibs_cbs`;
  - núcleo: `fiscal_regras`.
- **Configurações:**
  - `ECA_BLOQUEAR_CHECKIN`;
  - `FISCAL_BLOQUEAR_VENDA_SEM_NFCE`;
  - `FISCAL_IBS_CBS_ATIVO`, `FISCAL_CBS_ALIQUOTA`, `FISCAL_IBS_ALIQUOTA`;
  - `LGPD_ENCARREGADO_NOME`, `LGPD_ENCARREGADO_EMAIL`.
- **Documentação:** `docs/MODULOS_E_FLUXOS.md` e `docs/ARQUITETURA.md`.

**Como foi testado**
- Testes novos em cada commit, entre eles:
  - menor sem informação trava o check-in e com os pais entra;
  - arrumação para quem fica e não para quem sai;
  - no-show provável;
  - horários no e-mail e na confirmação;
  - IBS/CBS calculados;
  - aviso e bloqueio da NFC-e;
  - encarregado nas políticas;
  - webhook desconhecido.
- Suíte completa no Windows antes do push; o CI (Linux + PostgreSQL 16) roda no push.

**Depois do deploy (no Railway, se quiser)**
- Definir `LGPD_ENCARREGADO_NOME` e `LGPD_ENCARREGADO_EMAIL` com quem responde pelos dados.
- Confirmar com o contador as alíquotas de IBS/CBS e se a venda sem NFC-e deve ser
  bloqueada (`FISCAL_BLOQUEAR_VENDA_SEM_NFCE=1`).

---

## 20/10/2026 — Segurança e LGPD (`9082fc0` a `5f3c8b6`)

Quarto bloco: as proteções de login, os formulários públicos e o tratamento de dados
pessoais apontados na auditoria.

**O que melhorou**
- **Entrada da equipe:**
  - **"Esqueci minha senha":** o funcionário recebe por e-mail um link de uso único,
    válido por 1 hora. A tela é a mesma exista ou não o e-mail.
  - **Trava por usuário:** 8 senhas erradas para o mesmo usuário seguram aquela conta por
    15 minutos, venham de onde vierem.
  - **MFA obrigatório configurável:** só superusuário (padrão, decisão do dono),
    gerência, ou também quem opera dinheiro.
  - As mensagens da entrada aparecem em português e como são (o limite de tentativas não
    vira mais "senha incorreta").
- **Formulários públicos:**
  - "Pedir proposta" e as páginas de captação ganham defesa silenciosa contra robôs
    (campo-armadilha + tempo mínimo); as páginas de captação, também limite por IP.
  - As boas-vindas automáticas vão uma vez por pessoa, com teto diário. O formulário não
    vira um disparador de e-mail em nome da pousada.
- **LGPD:**
  - Contato das páginas de captação só entra na lista de e-mail se marcar o
    consentimento; a caixa não vem mais marcada.
  - Descadastro só com confirmação: o antivírus que abre o link sozinho não tira ninguém
    da lista. E o botão "descadastrar" do Gmail passa a funcionar.
  - Trilha de auditoria:
    - registra que o documento ou o nascimento mudou, mas não guarda o valor;
    - retenção configurável;
    - exportação só pela gerência;
    - escritas feitas pelo site, pelo portal, pelo link de pagamento e pelos webhooks
      também ficam registradas.
  - Testes e exemplos passam a usar dados sintéticos. Sem telefone do pagador, o gateway
    recebe o comercial da pousada.
- **Pagamentos:**
  - Link vencido não aceita mais pagamento novo (o que o gateway confirmar continua
    valendo).
  - "Já paguei" tem limite de cliques.
- **Portal do hóspede:** "Gerar novo QR" invalida o link que foi parar onde não devia.
- **"Minha reserva" no site:** o sobrenome precisa ser um sobrenome inteiro, não um
  pedaço do nome.
- **Outros:**
  - token da Meta no cabeçalho, nunca na URL;
  - upload da Conciliação limitado a 5 MB e ao tipo certo;
  - violações de CSP vão para o log, para o bloqueio ser ligado sem quebrar tela.

**O que foi modificado**
- **Novos:**
  - `apps/nucleo/antirrobo.py` e a tag `{% campos_antirrobo %}`;
  - comando `purgar_trilha`;
  - rotas `/crm/senha/…` (Esqueci minha senha);
  - `/csp/relatorio/`;
  - `portal:qr_novo`;
  - templates `registration/senha_*`.
- **Configurações:**
  - `MFA_OBRIGATORIO_PARA`;
  - `TRILHA_RETENCAO_DIAS`;
  - `LEAD_BOAS_VINDAS_MAX_DIA`;
  - `PAGAMENTOS_TELEFONE_PADRAO`;
  - `LOGIN_TRAVA_POR_CONTA` (fixa, desligada só nos testes).
- **Sem migrations.**
- **Documentação:** `docs/ARQUITETURA.md` (auditoria, camadas de segurança e variáveis).

**Como foi testado**
- Testes novos em cada commit, entre eles:
  - o fluxo completo de "Esqueci minha senha";
  - a trava com 8 IPs diferentes;
  - o descadastro de um cliente com CSRF ligado;
  - lead sem consentimento;
  - token fora da URL;
  - upload grande;
  - relatório de CSP com token mascarado;
  - link vencido;
  - novo QR;
  - robô e teto de boas-vindas;
  - sobrenome por pedaço;
  - documento mascarado na trilha e escrita pública atribuída.
- Suíte completa no Windows: 1080 testes; a única falha é a conhecida do Windows. O CI
  (Linux + PostgreSQL 16) roda no push.

**Depois do deploy (opcional, no Railway)**
- Para exigir MFA também da gerência: `MFA_OBRIGATORIO_PARA=gerencia`.
- Para ligar a retenção da trilha: `TRILHA_RETENCAO_DIAS` (5 anos ≥ 1830).
- Para o "Esqueci minha senha" sair de verdade: `EMAIL_HOST` configurado (o mesmo dos
  e-mails de reserva) e o e-mail de cada funcionário preenchido no cadastro.

---

## 20/10/2026 — Faturamento para agência, NFS-e certa e a recepção mais flexível (`a6d63a4` a `108b444`)

Terceiro bloco: o resto das regras de dinheiro da auditoria e as primeiras correções de
operação da recepção.

**O que melhorou**
- **Reserva de agência ou empresa fecha sem o hóspede pagar.**
  - Na reserva faturada, a gerência (ou quem tem o Financeiro) clica em "Faturar para
    <empresa>": o saldo vira uma conta a receber no Financeiro, com vencimento em 30 dias
    por padrão, e a saída fecha.
  - Consumo pessoal pode ficar de fora e ser recebido do hóspede.
  - Funciona também no folio de grupo.
- **NFS-e sobre o valor certo.** O ISS e a taxa de turismo saíram da base da nota: antes o
  ISS incidia sobre ele mesmo. Contas antigas foram corrigidas pela migration.
- **Diárias somam o total cotado.** A última noite absorve os centavos do arredondamento:
  sem sobra de 1 centavo no check-out e sem adiantamento exato recusado.
- **Loja sem venda em dobro.** Clique duplo ou conexão que cai não cobra nem baixa o
  estoque duas vezes. Devoluções de estoque não apagam mais uma venda feita no mesmo
  instante.
- **Troca de quarto mais esperta.**
  - Confere se as camas cabem no quarto novo.
  - Mantém a diária combinada e avisa quando a tarifa do quarto novo é outra; a gerência
    pode cobrar a nova.
  - Só manda faxinar o quarto antigo se o hóspede estava nele.
- **Estender a estadia** de quem está hospedado: as noites a mais entram na conta pela
  tarifa do dia, com ISS e taxa.
- **Mudar a lotação antes do check-in** (veio mais uma criança): refaz camas e diária.
- **Gerência decide o preço.** Dispensar ISS ou taxa de turismo numa reserva, manter a
  diária com outra lotação e cobrar a tarifa do quarto novo exigem gerência.
- **Sinal do Comercial configurável** (`COMERCIAL_SINAL_PCT`, padrão 30%). A mensagem do
  WhatsApp mostra o percentual real do sinal.
- **Menos tropeços:**
  - quarto de grupo ocupa a vaga de uma pré-reserva vencida;
  - o BOH deixa de fora as fichas FNRH vazias;
  - o pedido pelo portal aceita só itens do cardápio, até 20 por item, e nunca dá erro
    500;
  - reservas criadas pelo site ou pelo Comercial seguem as regras do formulário (1
    adulto, titular no faturado).

**O que foi modificado**
- **Migrations:**
  - `loja.0002`: `Venda.chave`;
  - `reservas.0024`: tipo "taxa" no folio, com correção das contas antigas;
  - `reservas.0025`: `Reserva.valor_hospedagem`;
  - `reservas.0026`: `PagamentoConta.conta_receber`.
- **Serviços novos:**
  - Reservas: `faturar_conta`, `estender_estadia`, `alterar_lotacao`,
    `Reserva.valores_das_diarias()`;
  - núcleo: `devolver_ao_estoque`.
- **Configuração:** `COMERCIAL_SINAL_PCT` e `FATURAMENTO_PRAZO_DIAS`.
- **Telas:**
  - "Faturar para" no detalhe da reserva e do grupo;
  - "Estender a estadia" e "Mudar a lotação";
  - opção da gerência na troca de quarto;
  - PDV da Loja com a chave do carrinho.
- **Documentação:** `docs/MODULOS_E_FLUXOS.md` e `docs/ARQUITETURA.md`.

**Como foi testado**
- Testes novos em cada commit, entre eles:
  - faturar parte e o resto fica com o hóspede;
  - permissão de faturar;
  - folio de grupo;
  - base da NFS-e com taxas ligadas;
  - última noite com o arredondamento;
  - venda repetida com a mesma chave;
  - troca de quarto com tarifa nova, hospedado e antes do check-in;
  - estender sobre a próxima reserva é recusado;
  - pedido do portal com quantidade inválida.
- Suíte completa no Windows antes do push; o CI (Linux + PostgreSQL 16) roda no push.

**Depois do deploy:** as migrations rodam sozinhas. Se quiser outro percentual de sinal
ou outro prazo de faturamento, defina `COMERCIAL_SINAL_PCT` / `FATURAMENTO_PRAZO_DIAS` no
Railway.

---

## 20/10/2026 — Dinheiro certo na conta do hóspede e primeira polida no front-end

Segundo bloco das correções da auditoria. Duas frentes: o dinheiro que entrava por um
caminho e não aparecia no outro, e o acabamento das telas que a equipe e o hóspede usam.

### Dinheiro (`421fba7`, `862a220`, `a90eb5e`)

**O que melhorou**
- **O que o hóspede paga online abate a conta dele.** Pix, cartão ou boleto pagos pelo
  site, pelo link do Comercial ou pelo portal viram crédito na reserva (ou no folio do
  grupo). Antes, no check-out ele aparecia devendo o que já tinha pago.
- **Estorno desfaz o crédito.** Devolver no gateway ou estornar no caixa faz a conta
  voltar a cobrar o valor devolvido. Antes o dinheiro saía e a conta continuava "paga",
  e o check-out fechava sem receber. Se a conta já estiver fechada, o estorno é recusado
  antes de qualquer devolução.
- **Sinal do lead não some.** O sinal pago num lead do Comercial vira crédito na reserva
  criada a partir dele, na conversão automática ou na manual, e a manual não gera um
  segundo sinal.
- **Adiantamento não passa do total da estadia.** Um valor digitado a mais (3000 em vez
  de 300) deixava a conta com crédito e o check-out travado.
- **Devolver ao hóspede** (só gerência), no detalhe da reserva:
  - devolve o que ele pagou a mais;
  - executa a política de cancelamento: o cancelamento grava quanto a pousada retém, a
    tela sugere devolver o resto e a Auditoria cobra até a devolução sair;
  - o dinheiro sai do caixa de Reservas de quem devolve;
  - o que entrou online volta pela tela de Pagamentos.
- **Caixa sem atropelo.** Fechar o caixa e receber ao mesmo tempo não se perdem mais
  um do outro. O estorno de um recebimento de caixa já fechado entra no caixa aberto de
  hoje, sem reabrir (e apagar) a conferência antiga.

**O que foi modificado**
- **Modelos e migrations:**
  - `reservas.0022`: `PagamentoConta` e `Adiantamento` ganham a base comum
    `CreditoNaReserva`, com três origens: caixa, online (`cobranca_id`, único) e estorno
    (`estorno_de`, valor negativo). Check-constraints garantem o sinal do valor. Os dados
    atuais já cumprem a regra.
  - `reservas.0023`: `Reserva.valor_retido`.
- **Serviços novos em Reservas:**
  - `registrar_pagamento_online`, `verificar_estorno_online`, `estornar_pagamento_online`;
  - `limite_devolucao`, `situacao_devolucao`, `devolver_ao_hospede`;
  - `Reserva.total_previsto()`.
- **Núcleo:** gancho `ao_estornar` no `estornar_movimento`, para Reservas desfazer o
  crédito na mesma transação sem o núcleo conhecer o módulo. Também as travas no
  `fechar()`/`receber_no_caixa()`.
- **Pagamentos:** `confirmar_pagamento` credita; `estornar` trava a cobrança, confere
  antes e desfaz depois; novo `vincular_reserva`.
- **Comercial:** a conversão de lead amarra e credita o sinal já pago.
- **Telas:** folio e adiantamentos mostram a origem e o sinal de cada linha; bloco
  "Devolver ao hóspede" no detalhe da reserva; nova pendência "cancelada com devolução
  pendente" na Auditoria.
- **Documentação:** `docs/MODULOS_E_FLUXOS.md` (Reservas, Pagamentos, Caixa, Comercial) e
  `docs/ARQUITETURA.md` (motor de caixa e regras de dinheiro).

### Front-end (`1372a9b` a `75e8d04`)

**O que melhorou**
- **Dá para ver onde está o foco** em todo campo e botão. O laranja de "em andamento"
  passou a ter contraste legível. O kit de painel do Comercial, que redefinia os botões
  com outra cor, foi absorvido pelo estilo principal: um botão, um visual.
- **O balcão opera pelo teclado.** O seletor de pessoa e de quarto vira combobox de
  verdade (setas, Enter, Esc). No modal de nova reserva o foco nasce no hóspede,
  Ctrl+Enter cria a pré-reserva e o que raramente se mexe fica em "Mais opções".
- **As fontes da marca moram no próprio sistema**, sem depender do Google: chegam também
  ao portal do hóspede e à página de pagamento.
- **Cache que se renova sozinho.** CSS e JS ganham hash no nome em produção: o navegador
  guarda, e o deploy troca sem ninguém precisar lembrar de mudar versão.
- **Mapa de quartos.** Uma troca de quarto que falha mostra o motivo e devolve o quarto
  ao lugar. Antes a página recarregava e parecia que tinha dado certo.
- **Governança sem recarregar.** A camareira marca o quarto e a linha muda na hora; o
  filtro fica guardado; no celular cada quarto vira um cartão.
- **Site:**
  - home 640 KB mais leve (logos em WebP no tamanho certo);
  - o calendário só carrega onde é usado;
  - Google Analytics e Meta Pixel só depois do "Aceitar" (LGPD), com "Recusar" do mesmo
    tamanho;
  - a notificação de "nova reserva" não mostra mais o nome de ninguém;
  - dados estruturados da pousada para o Google e sitemap com os 24 quartos.
- **Portal e pagamento com cara de pousada.** Alvos de toque de 44 px, a página do cartão
  com máscara, bandeira e um bloco de confiança, e as duas fora dos buscadores (têm
  token na URL).

**O que foi modificado**
- `static/css/app.css` (foco, tokens, kit promovido); `static/fonts/` (novas);
  `static/js/tabela-rol.js`, `static/js/consentimento.js` (novos); `templates/base.html`
  (combobox, foco preso no modal e na paleta, avisos por HTMX).
- `config/settings.py`: `CompressedManifestStaticFilesStorage` fora de DEBUG e testes.
- Governança: o quadro virou `templates/governanca/partials/quadro.html`, com ações por
  `hx-post`.
- Site: imagens WebP, `componentes/consentimento.html`, JSON-LD, sitemap e prova social
  anônima com cache.

**Como foi testado**
- Testes novos nos dois blocos:
  - dinheiro: crédito online, estornos, sinal do lead, limite do adiantamento,
    devolução e permissão;
  - front-end: combobox e rótulos, painel da governança por HTMX, site, portal e página
    de pagamento.
- `collectstatic` de produção conferido: 235 arquivos com hash. Todos os `{% static %}`
  dos templates existem no manifesto, então nenhuma página quebra por arquivo faltando.
- Suíte completa no Windows antes do push; o CI (Linux + PostgreSQL 16) roda no push.

**Depois do deploy:** nada a fazer além das migrations, que rodam sozinhas no pré-deploy.

---

## 20/10/2026 — Infraestrutura e desempenho (`7c1394e` a `f1faf57`)

Primeiro bloco das correções da auditoria: o que mantém o sistema de pé em produção e o
que deixava as telas lentas.

**O que melhorou**
- **Telas muito mais rápidas** (consultas ao banco por abertura de tela, medidas com os
  dados de exemplo; no Railway cada consulta ainda paga a rede):

  | Tela | Antes | Depois |
  |---|---:|---:|
  | Busca de quartos no site (3 noites) | 334 | 18 |
  | Busca de quartos no site (7 noites) | 682 | 24 |
  | Home do site | 15 | 9 |
  | Dashboard do CRM | 213 | 52 |
  | Mapa de quartos | 157 | 20 |
  | Pessoas | 181 | 16 |
  | Pendências da Auditoria | 134 | 37 |
  | Governança | 49 | 36 |

  O número de consultas deixou de crescer com a quantidade de quartos, noites ou pessoas,
  e há testes que acusam se voltar a crescer. Nenhum preço mudou: 480 preços comparados
  antes e depois, com zero diferenças.
- **Tarefas agendadas funcionando.** O comando `rotinas` roda tudo o que dependia de um
  agendador que não existia: expira pré-reservas, reenvia FNRH, dispara campanhas
  agendadas, reenvia e-mails e mensagens que falharam, e faz o backup do banco. Os dois
  serviços de cron do Railway estão prontos em `deploy/`.
- **Nada se perde quando algo cai no meio.**
  - Confirmação de reserva do site: só sai depois que a reserva está gravada; se não
    sair, é reenviada.
  - E-mails do Comercial presos em "pendente" e mensagens do WhatsApp que falharam ao
    processar: são reenviados ou reprocessados sozinhos.
  - Erro do gateway de pagamento: não derruba mais a reserva do site.
- **Gateway lento não trava o CRM.**
  - A Safrapay espera no máximo 10 s.
  - O servidor atende 8 requisições ao mesmo tempo, em vez de 2.
  - As migrations rodam antes do deploy, uma vez só.
- **Limites de tentativa de verdade.** Login, MFA, cartão e site passam a ter um contador
  único entre os workers, que sobrevive ao deploy (antes valiam o dobro e zeravam).
- **Backup diário fora do Railway**, com retenção de 30 dias e restauração documentada.
- **Erros avisam.** Integração opcional com o Sentry, sem enviar dado pessoal nem de cartão.
- **Hosts.** Só são aceitos os domínios do próprio serviço (saiu o curinga
  `.railway.app`).
- **Selo da temporada no site.** Vem da mesma classificação que forma o preço; antes podia
  mostrar "Alta" num dia cobrado como baixa.

**O que foi modificado**
- **Configuração e deploy:**
  - `config/settings.py`: cache compartilhado (Redis com `REDIS_URL`, senão tabela no
    Postgres), Sentry opcional, `SAFRAPAY_TIMEOUT`, hosts e o middleware de módulos por
    requisição;
  - `railway.json`: pré-deploy com `migrate`; gunicorn com threads e timeout de 60 s;
  - `deploy/railway.rotinas*.json` (novos);
  - `requirements.txt`: `redis`, `sentry-sdk`.
- **Comandos novos:**
  - `rotinas` e `backup_banco` (núcleo);
  - `reenviar_emails_pendentes` e `reprocessar_webhooks_whatsapp` (Comercial);
  - `reenviar_confirmacoes_site` (site);
  - o `expirar_reservas` do site virou `expirar_recibos_site`.
- **Modelos e migrations:**
  - `nucleo.0046`: tabela do cache;
  - `comercial.0031`: `EnvioEmail` guarda o conteúdo até sair;
  - `comercial.0032`: `WebhookWhatsApp`;
  - `core.0007`: `Reserva.confirmacao_enviada_em`;
  - `reservas.0021`: índices.
- **Desempenho:**
  - `precos_em_lote()` e `precarregar_tarifas_unidade()` (Reservas);
  - `ContaHospedagem.saldos()`;
  - pré-cargas no mapa, no pool de colchões, na lista de Pessoas e na Governança;
  - auditoria sem leitura extra quando não há usuário;
  - módulos ativos lidos uma vez por requisição.
- **Fluxos:**
  - `criar_cobranca` grava a cobrança antes de chamar o provedor;
  - a finalização da reserva do site separa as gravações (numa transação) da cobrança
    e do e-mail;
  - o webhook do WhatsApp grava o corpo antes de processar.
- **Documentação:** README (seções 8 e 10), `docs/ARQUITETURA.md` (4.2, 5.5, 7, 9.5, 10.1,
  10.4 e a nova 10.6, de backup) e `docs/MODULOS_E_FLUXOS.md`.

**Como foi testado**
- Testes novos em cada commit, entre eles os que medem consultas: busca do site, mapa de
  quartos e Pessoas com mais itens fazem o mesmo número de consultas.
- Suíte completa no Windows e no CI (Linux + PostgreSQL 16) depois do push.

**Depois do deploy (no Railway)**
- Criar os dois serviços de Cron com os arquivos de `deploy/` e as mesmas variáveis do
  serviço web.
- Para o backup sair do Railway, configurar o R2 (variáveis `R2_*`) ou `BACKUP_DIR`; ligar
  também o PITR do Postgres.
- Opcional: add-on Redis (`REDIS_URL`) e `SENTRY_DSN`.

---

## 20/10/2026 — Novidades do original: Tabela de Preços (`dae8904`)

**O que melhorou**
- Os campos da Tabela de Preços mostram o valor inteiro: juntamos a correção que o
  Gefferson publicou hoje com a que já existia aqui, e as duas se completam.

**O que foi modificado**
- Merge dos commits `723a7ea`, `e71dd5f` e `8fb5eee` do original, que chegaram pelo
  PR #1 aberto pela automação. Um conflito em `templates/nucleo/tabela_precos.html`,
  resolvido mantendo as duas correções:
  - daqui: o cartão do formulário deixa de limitar a 620px, que era a causa do aperto;
  - de lá: regra mais forte e `flex: 0 0 auto`, para o campo nunca encolher, com
    números tabulares;
  - largura do campo: 5.75rem, conferida na tela com "1.250,00".

**Como foi testado**
- A tela já tinha sido conferida com essa largura; a regra nova só impede o campo de
  encolher. CI roda a suíte inteira neste push.

---

## 20/10/2026 — Acompanhamento automático do projeto original

**O que melhorou**
- O fork passa a acompanhar sozinho o que o Gefferson publica no projeto original. Duas
  vezes por dia (8h e 17h), se houver commit novo lá, o GitHub junta as novidades com o
  `dev`, roda a suíte de testes nesse merge e abre um Pull Request "Novidades do
  original (Gefferson)" com a lista de commits e o resultado dos testes.
- Nada entra no `dev` sozinho: quem decide é quem revisa o PR. Se as novidades
  conflitarem com o que existe aqui, o PR avisa que o merge precisa ser resolvido à mão.

**O que foi modificado**
- `.github/workflows/novidades-do-original.yml` (novo): busca a `main` do original,
  atualiza o espelho `main` deste fork, faz o merge com o `dev` no branch
  `sincronizar/original`, testa e abre ou atualiza o PR.
- `.github/workflows/testes.yml`: pode ser chamado por outro workflow com o branch a
  testar (`workflow_call`), para o mesmo CI valer para o merge com o original.
- `CHANGELOG.md` (este arquivo, novo): histórico de tudo o que já subiu, e de agora em
  diante uma entrada por push.

**Como foi testado**
- Rodado de verdade no GitHub logo depois do push, contra as 3 novidades que o Gefferson
  publicou hoje na Tabela de Preços. Ele atualizou o espelho `main` e abriu o PR #1
  avisando do conflito com a correção que já existia aqui (resolvida na entrada acima).
  O caminho sem conflito (merge + testes + PR) roda na próxima novidade do original.

---

## 20/10/2026 — Documentação atualizada e fork abrindo no `dev` (`44bb7d0`)

**O que melhorou**
- Quem abre `github.com/VicZk/vo_testa` vê o README completo: o fork passou a abrir no
  `dev`, e não mais no espelho do original.
- O Gefferson foi convidado como colaborador do fork e o README tem o passo a passo para
  ele levar daqui o que quiser (commit a commit, tudo de uma vez ou por PR).
- A documentação descreve o sistema como ele é hoje, com as 12 melhorias abaixo.

**O que foi modificado**
- `README.md`, `docs/ARQUITETURA.md`, `docs/MODULOS_E_FLUXOS.md`: regra dos sinais,
  check-in/out atômicos, tolerância de arredondamento, day use de um dia, travas da
  comanda e da conta, healthcheck, logs, CI de testes, `estrutura_inicial`, HTMX e Alpine
  locais, e o modelo de colaboração do fork.
- No GitHub: branch padrão do fork = `dev`; convite de colaborador para o Gefferson.

**Como foi testado**
- Só documentação, conferida trecho a trecho contra o código. CI: 898 testes OK.

---

## 20/10/2026 — 12 melhorias encontradas na auditoria (`1aa5175` a `27ac05c`)

**O que melhorou**
- **Check-out, troca de quarto, faxina e manutenção não caem mais por erro de outro
  módulo** (`1aa5175`). Um erro no Comercial, na Governança ou na Lavanderia vai para o
  log; a operação da recepção continua valendo.
- **Check-in e check-out atômicos** (`e07b9b2`): se um lançamento falhar, nada fica pela
  metade; clique duplo não duplica; consumo nunca entra em conta já fechada.
- **Check-out não trava por centavos** (`32ba4e2`): sobra de arredondamento até R$ 0,10
  (configurável) vira desconto automático, registrado na trilha.
- **Day use só aceita um dia** (`c13a9e9`): um erro de digitação não ocupa mais a unidade
  de day use por vários dias.
- **Comanda do restaurante travada** (`80caff6`): dois garçons lançando ao mesmo tempo
  não perdem quantidade, e não entra item em comanda fechada.
- **Healthcheck confere o banco e os erros aparecem no Railway** (`b356d54`): um
  container sem banco não substitui o que está no ar; erros 500 saem nos logs.
- **CI de testes** (`00cbeaf`): a suíte inteira roda com PostgreSQL a cada push e PR.
- **Banco novo montável do zero** (`bc2ac8c`): `estrutura_inicial` cria tipos e os 24
  quartos (com `--completo`, também camas, tarifas e vitrine).
- **Toda ação mostra que está carregando e avisa erro** (`4038b0b`); HTMX e Alpine
  servidos pelo próprio sistema, sem depender de CDN.
- **Telas no celular e Tabela de Preços** (`9f8ae05`): painel sem quartos cortados,
  valores legíveis, moeda no formato R$ 1.234,56.
- **Link do site com foto no WhatsApp e no Facebook** (`f71e2ac`), e canonical sem
  query string para o Google.
- **Dependências com versão fixa** (`27ac05c`): `qrcode` e `Pillow`; `.env.example`
  limpo e documentado.

**O que foi modificado**
- `apps/nucleo/sinais.py` (novo) e os emissores/receptores de sinais de Reservas,
  Governança, Manutenção, Pagamentos, Comercial e Lavanderia.
- `apps/reservas/models.py` e `services.py` (check-in/out, arredondamento, day use,
  `lancar_na_conta`), `apps/restaurante/services.py`, `config/urls.py`,
  `config/settings.py` (LOGGING, tolerância), `.github/workflows/testes.yml`,
  `apps/nucleo/management/commands/estrutura_inicial.py`, `templates/base.html`,
  `static/css/app.css`, `static/vendor/`, templates do site, `requirements.txt`,
  `.env.example`.

**Como foi testado**
- Testes novos para cada correção. Suíte completa: 898 testes no CI (Linux +
  PostgreSQL 16).

---

## 20/10/2026 — Novidades do original até `62fbaf5` (`f0313bc`)

**O que melhorou**
- Trazidos do projeto original: meia diária para crianças de 6 a 15 anos, ajustes no
  day use, parâmetros de preço e a opção de tarifa não reembolsável.

**O que foi modificado**
- Merge da `main` do original no `dev` (16 arquivos de Reservas e da Tabela de Preços).

---

## 20/10/2026 — Documentação completa do sistema (`e94061b`)

**O que melhorou**
- O sistema ganhou um mapa: como rodar, como as peças se encaixam e como desenvolver
  em cima dele.

**O que foi modificado**
- `README.md` (reescrito), `docs/ARQUITETURA.md` e `docs/MODULOS_E_FLUXOS.md` (novos).

---

## 20/10/2026 — Fork preparado para Windows (`ef3f309`)

**O que melhorou**
- O projeto passa a ser clonado no Windows: dois arquivos da documentação da SafraPay
  tinham `?` no nome, caractere proibido no Windows, e travavam o clone.

**O que foi modificado**
- Renomeados os arquivos de `docs/SafraPay/` com `?` no nome (só documentação).
