# Changelog

Tudo o que muda neste fork (`VicZk/vo_testa`), push a push. Cada entrada diz **o que
melhorou**, ou seja, o efeito para a pousada, e **o que foi modificado**, ou seja, onde
o código mexeu, com os commits. A explicação completa de cada commit (o que mudou, por
quê e como foi testado) está na mensagem dele no GitHub.

A entrada mais nova fica no topo. As datas são as do push.

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
