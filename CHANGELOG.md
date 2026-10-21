# Changelog

Tudo o que muda neste fork (`VicZk/vo_testa`), push a push. Cada entrada diz **o que
melhorou**, ou seja, o efeito para a pousada, e **o que foi modificado**, ou seja, onde
o código mexeu, com os commits. A explicação completa de cada commit (o que mudou, por
quê e como foi testado) está na mensagem dele no GitHub.

A entrada mais nova fica no topo. As datas são as do push.

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
