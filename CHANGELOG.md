# Changelog

Tudo o que muda neste fork (`VicZk/vo_testa`), push a push. Cada entrada diz **o que
melhorou**, ou seja, o efeito para a pousada, e **o que foi modificado**, ou seja, onde
o código mexeu, com os commits. A explicação completa de cada commit (o que mudou, por
quê e como foi testado) está na mensagem dele no GitHub.

A entrada mais nova fica no topo. As datas são as do push.

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
