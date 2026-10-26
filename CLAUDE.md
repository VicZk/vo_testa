# CRM Pousada Vô Testa

Sistema de gestão (PMS/CRM) para a Pousada Vô Testa — 24 quartos.
**Referência do produto:** [especificação](docs/ESPECIFICACAO.md) e [estado atual](docs/ESTADO_ATUAL.md).
Índice completo: [docs/README.md](docs/README.md). Planos antigos não comprovam implementação.
Pesquisa de mercado: `docs/REFERENCIA_DESBRAVADOR.md`.

## Stack

- Python 3.14 + Django 6.x + PostgreSQL (referência e CI: PostgreSQL 16)
- Templates Django + HTMX + Alpine.js locais em `static/vendor/` — sem SPA
- Views Django e webhooks próprios; DRF e Celery não estão instalados
- Redis opcional; sem `REDIS_URL`, cache compartilhado no PostgreSQL
- Deploy: Railway (gunicorn + whitenoise)

## Comandos

```bash
.venv/bin/python manage.py runserver      # dev server
.venv/bin/python manage.py test           # testes (obrigatório antes de commit)
.venv/bin/python manage.py makemigrations # após mudar models
.venv/bin/python manage.py migrate
.venv/bin/ruff check apps/ config/        # lint (config em ruff.toml) — tem que dar zero
```

Config por variável de ambiente (`.env` local — ver `.env.example`). `DEBUG=1` no dev.

O CI roda sozinho: `testes.yml` (ruff, `makemigrations --check` e a suíte contra
PostgreSQL 16, mais o job "Fluxos no navegador" com Playwright + Chromium —
todos os arquivos `apps/site/tests*e2e.py`, `E2E_OBRIGATORIO=1` —,
em todo push da `main`/`dev` e em PR)
e `security.yml` (pip-audit, bandit, ruff de segurança e gitleaks, no push da `main`/`dev`,
em PR, toda segunda e sob demanda; o gitleaks segue o `.gitleaks.toml`).
Rotinas agendadas: `manage.py rotinas --grupo frequentes` (a cada 10 min) e
`--grupo diarias` (03:15 de Brasília) — dois serviços cron no Railway, configs em
`deploy/`. Rotina nova entra no grupo certo em
`apps/nucleo/management/commands/rotinas.py`. Com `ROTINAS_MONITOR_FREQUENTES/DIARIAS`
(URL de um check do Healthchecks.io), o grupo avisa começo, fim e falha.

## Deploy, commit e push

**Organização local:** todo o trabalho deste projeto deve permanecer dentro de
`C:\Users\viczk\OneDrive\Desktop\Projects\Pousada`. Worktrees, ambientes de QA,
scripts temporários e evidências ficam em `.codex-work/`, ignorado localmente pelo
Git. Não criar pastas irmãs `Pousada-*` em `Projects` nem cópias do projeto em Temp.

**NUNCA fazer deploy, commit ou push sem comando explícito do usuário.** Trabalhar
normalmente no código local (editar, migrar, testar); versionar e subir, só quando
ele mandar.

**Fork e publicação:** o trabalho desta cópia ocorre em `VicZk/vo_testa`, branch
`dev`. `upstream` é o original, para leitura; não publicar nele. Os registros do
projeto associam a produção ao Railway e à `main` do original, mas a conexão e a
versão ativa precisam ser verificadas antes de uma entrega de código. Não rodar
`railway up` sem escopo explícito. Documentação, código e deploy são entregas
distintas; não incluir commits locais de código numa publicação só de documentação.

## Processo por módulo

Ao iniciar qualquer fase/módulo, **consultar primeiro como o Desbravador resolve**:
<https://www.desbravador.com.br/produtos/hoteis-e-pousadas> (+ resumo em
`docs/REFERENCIA_DESBRAVADOR.md`) — funcionalidades, fluxos e telas — antes de
desenhar o nosso.

## Arquitetura (regras que não se quebram)

- **Núcleo + módulos contratáveis.** Cada módulo é um app Django em `apps/`.
  Catálogo e dependências em `apps/nucleo/modulos.py`; ativação na tabela
  `ModuloContratado`. Menus/comportamentos consultam `modulo_ativo()` — nunca hard-code.
- **Módulos só conversam por services/interfaces públicas**, nunca importam models
  internos uns dos outros (exceto do núcleo). Degradação graciosa: módulo funciona
  sem os opcionais (ex.: Loja sem Reservas = só venda balcão).
- **Fonte de verdade única:** disponibilidade → Reservas; dinheiro → Financeiro (núcleo);
  estoque → motor de estoque (núcleo).
- **Dinheiro:** `DecimalField`, nunca float. Movimentos de caixa e estoque são
  imutáveis — correção é movimento inverso, nunca update/delete.
- **Overbooking:** impedido por `ExclusionConstraint` (PostgreSQL) no módulo
  Reservas, já implementado; não substituir a garantia do banco por checagem apenas na UI.
- **Auditoria:** operações sensíveis (estorno, cancelamento, ajuste, reabertura de
  caixa) registram quem/quando/por quê.
- `AUTH_USER_MODEL = nucleo.Usuario` — nunca usar `django.contrib.auth.models.User`.
- **Acesso por usuário × módulo, gerido pelo Admin:** toda view de módulo usa
  `@requer_modulo(Modulo.X)` (`apps/nucleo/permissoes.py`). Módulo inativo → 404;
  usuário sem o módulo em `Usuario.modulos` → 403. Superusuário acessa tudo.
- **Áreas-core (o que não é módulo contratável):** o núcleo (quartos, temporadas,
  caixa, financeiro, pessoas, logbook, NPS, equipe) tem controle por usuário via
  `Usuario.areas` (JSONField) + `@requer_area(*codigos)` (variádico: passa quem tiver
  QUALQUER uma). Catálogo em `apps/nucleo/areas.py` (`Area`), checagem `pode_area()`,
  filtros de template `|pode_area:'x'` / `|pode_modulo:'x'`. Gerido na tela **Equipe &
  Acessos** (`configuracoes/equipe/`, `@requer_area(Area.EQUIPE)`), não no admin.
  Superusuário faz bypass; gerentes (is_staff) recebem as áreas por migração seed.
- **Crédito na conta do hóspede tem origem — uma só.** `PagamentoConta` e `Adiantamento`
  (base `CreditoNaReserva`) vêm do **caixa** (`movimento_caixa`), do **online**
  (`cobranca_id`, único), do **faturado** (`conta_receber`, só pagamento) ou são um
  **estorno** (`estorno_de`, valor negativo); `CheckConstraint`s seguram o sinal no banco.
  Crédito nasce pelos services (`receber_pagamento`, `receber_adiantamento`,
  `registrar_pagamento_online`, `faturar_conta`, `devolver_ao_hospede`…), nunca por
  `objects.create` solto.
- **Estorno atravessa módulos por gancho, não por import:** `estornar_movimento` (núcleo)
  chama, na mesma transação, as funções registradas com `ao_estornar()`
  (`apps/nucleo/models/financeiro.py`). Módulo que guarda espelho do dinheiro registra a
  sua no `AppConfig.ready()` (ex.: Reservas desfaz o crédito na conta).
- **Concorrência (duplo clique, duas abas, webhook repetido):** escrita de dinheiro ou
  estoque roda em `transaction.atomic` e trava a linha com `travar(obj)`
  (`apps/nucleo/sistema.py`: SELECT … FOR UPDATE + refresh); várias linhas = travar em
  ordem de `pk`. POST que cobra leva chave de idempotência (ex.: `Venda.chave`): o reenvio
  devolve a mesma venda em vez de cobrar duas vezes. Confirmação de pagamento é idempotente.
- **Ação sem login (portal, site, webhook, cron) tem autor:** `usuario_de_sistema()`
  (`_portal`, `_site`…) assina na trilha. Documento e nascimento entram mascarados no diff
  (`CAMPOS_PII` em `audit.py`). `QuerySet.update()` e `bulk_create` não disparam signal:
  registrar à mão com `registrar_auditoria`. Retenção: `TRILHA_RETENCAO_DIAS` +
  `purgar_trilha` (rotina diária).
- **Formulário público** (site, LPs, captação) usa o antirrobô do núcleo:
  `{% campos_antirrobo %}` no template + `parece_robo(request.POST)` na view (armadilha +
  carimbo assinado), mais limite por IP. Robô recebe "sucesso" calado.

## Convenções

- Domínio em português: models, campos, verbose_names, templates, testes
  (ex.: `Reserva`, `UH`, `ModuloContratado`). Infra em inglês quando for padrão Django.
- UI em pt-BR; `TIME_ZONE = America/Sao_Paulo`.
- Testes em `apps/<app>/tests.py` e `tests_*.py` (runner Django); regras de dinheiro e disponibilidade
  sempre testadas.
- Antes de finalizar entrega de módulo: testes passando → skill django-verification →
  /code-review → commit → deploy. Publicação continua restrita ao escopo autorizado.
  Uma revisão somente documental não exige nem comprova novo deploy.

## Design & UI (toda tela nasce elegante — premissa fixa)

Todo template novo do CRM **nasce** já no design system unificado (visual "Lampião"):
nunca criar um estilo paralelo nem hard-codear cor/raio/sombra — sempre reusar os
tokens e as classes-base. Referência viva: `static/css/app.css` (tokens + componentes,
incluindo o kit de painel/lista/detalhe). O antigo `_estilo_elegante.html` está vazio
e não deve ser incluído. O portal do
hóspede e a página de pagamento carregam o `static/css/base.css`, recorte GERADO do app.css
(`manage.py gerar_base_css`, manifesto em `apps/nucleo/css_publico.txt`): edite só o app.css
e rode o comando — o teste `CssDasTelasPublicasTests` avisa quando o recorte ficou para trás.

- **Tokens, nunca valores fixos:** raio (`--raio-p` 10px / `--raio` 14px / `--raio-g`
  20px), sombra (`--sombra-1` para elementos pequenos, `--sombra-cartao` para o float
  suave de cartões), borda (`--fio`/`--fio-forte`), cores da marca (`--lampiao`,
  `--noturno`, `--madeira`, `--tinta`, `--tinta-suave`, semânticas `--sucesso`/`--alerta`
  /`--perigo`/`--info`).
- **Componentes-base reusados:** `.cartao`/`.cartao-el` (cartão com hairline + float),
  `.tabela`/`.quadro` (cabeçalho em maiúsculas discretas, hairlines, hover na linha) —
  **coluna de número/dinheiro leva `.num` no `<th>` E no `<td>`** (alinha à direita, nasce
  alinhada),
  `.botao-primario` (dourado), `.botao-neutro`, `.botao-mini` (nunca sublinhados; com
  `:active`), `.selo`/`.selo-*` (status com bolinha), `.kpi`/`.kpi-destaque` (métrica).
- **Pílula com parcimônia (pedido do dono: "pills em tudo, saturado demais"):** status
  neutro = `.selo` (bolinha + texto, sem fundo). Cápsula preenchida só para o que pede
  ação de alguém (`.selo--acao` e os estados críticos), no máximo uma por linha/cartão.
  Tipo, papel, canal e categoria são dado, não status: `.rotulo-dado` (texto discreto,
  separado por " · "). Filtro clicável é controle: `.filtro-chip`. Contagem é número
  solto, nunca pílula dentro de pílula.
- **Lista que pode crescer:** `paginar()` (`apps/nucleo/paginacao.py`) na view +
  `{% include "componentes/paginacao.html" with pagina=pagina %}` abaixo da tabela —
  nunca cortar em `[:200]`.
- **Telas de dashboard/lista/detalhe (padrão Comercial):** envolver em `<div class="eleg">`
  — herda KPIs, quadro e botões prontos de `app.css`, sem folha adicional.
- **Tipografia (craft):** números sempre com `font-variant-numeric: tabular-nums`;
  números grandes com tracking negativo (`letter-spacing:-.02em`); rótulos em MAIÚSCULAS
  discretas com leve tracking e tom suave; hierarquia por peso+tamanho, não só tamanho.
- **Interação:** feedback imediato no toque (`:active`), foco dourado da marca em todos
  os inputs (já global via `.conteudo … :focus`), hover sutil; respeitar
  `prefers-reduced-motion` (sem slide/spring — cross-fade). Duração e curva só pelos
  tokens de movimento (`--mov-toque/rapido/padrao/lento`, `--curva`, `--curva-entrada`,
  `--curva-pop`), que viram 1 ms sob reduced-motion; alvo de toque ≥ 44 px em ponteiro
  grosso. No toque, o modal é gaveta de baixo (`.modal-acoes` presas ao pé, altura em
  `dvh`) e o toast fica no topo — modal novo herda isso do bloco de toque do app.css.
- **Responsivo e menu (pedido do dono: "atenção nos menus colapsados, no que fica dentro
  e fora, fully responsive"):** conferir toda tela em 320, 390, 821 com o menu ABERTO e
  1440 px — nada de rolagem lateral, nada saindo do cartão, nada cortado sem reticências.
  A largura útil muda com o menu aberto/recolhido e o `@media` só enxerga a janela: o que
  divide espaço decide pelo espaço (`flex-wrap`, `minmax(min(Npx, 100%), 1fr)`, container
  query). Regra do trilho (`.app.recolhida …`) só dentro do `@media (width > 820px)`, e
  só mexendo em opacidade, cor, giro e posição: o trilho é o menu aberto recortado (nada
  reflui na troca — conferir animação quadro a quadro, não só os estados finais).
- **Dica = `data-dica`:** um balão só no CRM (`static/js/dicas.js`, no `base.html`);
  `data-dica-lado="direita"` para o menu recolhido. Nunca criar tooltip em `::after` nem
  reservar espaço para ele — o balão é fixo e não ocupa layout.
- **Largura e transição:** o conteúdo para em `--conteudo-max` (1760 px) e centra; tela
  que precisa da largura toda usa `{% block conteudo_classe %}conteudo-largo{% endblock %}`.
  Na troca de página só `.conteudo` faz View Transition (menu e topo têm nome próprio e
  ficam parados) — não reativar a transição global do HTMX.
- **O que a equipe manda a alguém** (link de pagamento, Pix, portal, pré check-in) sai com
  `{% copiar texto rotulo=… recado=… telefone=… %}` (`templates/componentes/copiar.html` +
  `static/js/copiar.js`): "Copiar" com plano B e "Enviar pelo WhatsApp" com mensagem
  pronta. Para quem mandar, `reservas.services.contato_da_reserva`. Nunca texto solto
  para a recepção selecionar com o mouse.
- **Nada de caminho fixo** (`'/crm/…'`, `href="/…"`, `redirect("/…")`): sempre `{% url %}`,
  `{% static %}`, `reverse()` ou `pattern_name=`. O sistema pode rodar sob um prefixo
  (`URL_PREFIX`, ex.: viczk.cloud/votesta) e o teste `PrefixoDeUrlTests` barra o que
  ignorar isso. Comparação de caminho usa `request.path_info` (sem o prefixo).
- **Comentário de template de várias linhas é `{% comment %}`:** `{# … #}` é de UMA linha
  no Django; em duas, o texto aparece cru na tela (há teste de design barrando).
- **Texto da tela com maiúscula:** rótulo, status, nota de KPI e opção de filtro começam
  com maiúscula; código gravado no banco ("no_show", "media") nunca aparece cru — vira
  rótulo (ex.: `auditoria.formatacao.rotulo_acao`).
- **Cor só por token, também no `<style>` próprio da tela:** fundo suave de semântica é
  `--sucesso-bg`/`--alerta-bg`/`--perigo-bg`/`--info-bg`; tinta translúcida é
  `color-mix(in srgb, var(--token) N%, transparent)`. O teste `CorSoPorTokenTests` barra
  hex/rgba no CRM.
- **Impressão:** o `@page` geral é A4 (kit de contingência) e o `@media print` do app.css
  tira o app-shell. Recibo, conta e comprovante de balcão saem pelo cupom de 80 mm
  (`templates/componentes/cupom.html`, página nomeada `@page cupom` com a altura medida
  pelo próprio componente) — não criar outro layout de recibo.
- **Componente injetado em página de terceiros** (LPs do design, site): classes com
  prefixo próprio e conferência visual na página hospedeira — o aviso de cookies nasceu
  com `.consent`, a classe do checkbox de LGPD das LPs, e arrancava o checkbox do form.
- **Referências de princípio:** skill `apple-design` (resposta, tipografia ótica,
  materiais, simplicidade) e a memória [[design-lampiao]]. Ao mudar o "look" global,
  mexer nos **tokens** (propaga a tudo), não em cada template.

## Estado atual

**Referência revisada em 26/10/2026:** [Estado atual](docs/ESTADO_ATUAL.md).
Esse documento identifica o código publicado da fork e os limites de
ativação/homologação externa; o que entrou depois está no [CHANGELOG](CHANGELOG.md).

- **Núcleo e operação:** cadastros, acessos, caixa, financeiro, estoque, reservas,
  loja, restaurante, lavanderia, governança, manutenção e escala implementados.
- **Reservas:** FNRH local/BOH, grupos, capacidade/camas, conta, origens de crédito,
  restrições de venda, no-show configurável, fechamento por competência e contingência.
- **Governança:** tarefas, arrumação, inspeção opcional, ronda e discrepâncias. A
  entrada é a visão geral da casa (`governanca:painel`); a lista de trabalho é
  `governanca:quartos`, com o ciclo de `services.CICLO` (fonte única dos rótulos da
  tela: "Pronto" = inspecionado; "Arrumado" com hóspede dentro) e um próximo passo por
  quarto; plano do dia por prioridade; "Minha fila" da camareira
  (`governanca:minha_fila`), com "Reportar problema" pela `manutencao.abrir_os`;
  "Distribuir a fila" entre quem está de turno (`escala.services.usuarios_de_turno`).
  `abrir_faxina` e `iniciar_tarefa` travam a linha e são seguros a toque duplo. Uso
  principal em tablet e celular: desenhar a partir do toque. O toque na porta abre a
  ficha do quarto (`governanca:quarto`, gaveta com HTMX); é para lá que o aviso de
  check-in barrado pela limpeza aponta. Quem só tem a Governança
  entra direto na Minha fila (`APRESENTACAO["url_pessoal"]`, lido pelo dashboard).
- **Estoque:** recebimento por embalagem, lotes e validade, ficha técnica de pratos
  e movimentos pelo motor do núcleo. Conversões e baixas ficam congeladas no
  histórico; devolução usa a origem. Perecíveis têm contagem por lote; o inventário
  geral cobre produtos comuns. Veja [Compras e perecíveis](docs/ESTOQUE_COMPRAS.md).
- **Gestão:** relatórios de carteira, pickup, ritmo e distribuição; três relatórios
  de governança; auditoria de pendências, trilha e fechamento; conciliação OFX/cartão.
- **Contábil/gerencial (upstream, 24/10):** app `apps/contabil`, módulo
  `Modulo.CONTABIL` (grupo Gestão). Camada ADITIVA e de LEITURA sobre o financeiro —
  sem partidas dobradas, DRE por soma. Plano de contas + de-para (`resolver_conta`),
  capturas por competência (receita do folio/vendas, taxa de cartão, CMV),
  `FechamentoMensal` (folha/encargos/pró-labore/impostos sobre a receita) e painel em abas com export CSV.
  Carimba `conta_contabil` por signal (o núcleo não importa `contabil`). Comissão de
  OTA é stub até o módulo Canais. No fork, as capturas e as recorrentes rodam na
  rotina `rotina_contabil` (grupo `diarias`); o endpoint token-gated
  (`CONTABIL_CRON_TOKEN`, só no cabeçalho) fica como alternativa e sem o token responde
  404. Integração com os fluxos do fork: baixa de título com categoria gerida pelo
  sistema (faturado, folha por recorrência) e a compra para o estoque ("Insumos") vão
  para contas fora da DRE (1.x/2.x); o custo do estoque entra pela saída (CMV, consumo
  interno, perdas), e o day pass e os descontos da conta entram nas capturas.
- **Comercial/marketing:** funil, cotações, atividades, WhatsApp, e-mail, LPs, campanhas,
  peças e orçamento. Site e portal integrados à hospedagem.
- **Integrações:** Safrapay, Serpro, WhatsApp Cloud, Meta e JEV têm adapters; produção
  depende de configuração/homologação verificadas. Pix direto tem baixa manual.
- **E-mail (22/10):** modo simulado não envia; adaptadores SMTP e SES implementados.
  Envio real exige configuração explícita e preferências de contato válidas.
- **Fiscal (22/10):** Focus NFe v2, NFS-e/NFC-e, consulta e cancelamento implementados;
  classificação fiscal e credenciais precisam ser conferidas antes da homologação real.
  Spedy (original, 25/10) adaptado ao ciclo do fork em `apps/fiscal/spedy.py`: NFS-e
  assíncrona, `integrationId` = `gateway_id`, retorno com assinatura Standard Webhooks
  (`SPEDY_WEBHOOK_SECRET`) e cancelamento que só fecha com a confirmação
  (`CancelamentoPendente`). Regime confirmado: Lucro Presumido (`settings.EMPRESA_*`).
- **NPS (22/10):** coleta persistida, consentimento e acompanhamento disponíveis.
- **Day pass:** módulo próprio de turnos, capacidade, visitantes, caixa e comandas;
  veja `docs/Reservas/DAY_PASS.md`. Nenhuma capacidade física é presumida.
- **Formulários:** veja `docs/FORMULARIOS.md`; erro não deve apagar campos ou fechar modal.
- **Canais/OTAs:** conexão Channex, mapeamento, fila de revisões e publicação de
  disponibilidade/tarifas/restrições. Inicia desativada; credenciais e homologação
  real dependem do provedor. Rotina independente a cada minuto (`--grupo canais`).
- **Futuro:** CRM do Hóspede e telefonia.
  Frigobar foi removido; não existe app ativo desse módulo.

Detalhes técnicos devem ficar em [Arquitetura](docs/ARQUITETURA.md) e
[Módulos e fluxos](docs/MODULOS_E_FLUXOS.md), evitando uma segunda especificação extensa
neste arquivo. Use o [índice](docs/README.md) para distinguir manuais de roteiros,
planos e auditorias históricas. Resultados antigos de testes não são validação atual.
