# Pousada Vô Testa — PMS, CRM e site

**Mapa de leitura:** [estado atual](docs/ESTADO_ATUAL.md) · [documentação completa](docs/README.md) · [changelog](CHANGELOG.md).

Sistema próprio de gestão da **Pousada Vô Testa** (Itá/SC): reservas, recepção, conta do
hóspede, caixa, pontos de venda, governança, lavanderia, manutenção, escala, FNRH,
financeiro, fiscal, comercial e o site público com motor de reservas. Um único projeto
**Django 6 + PostgreSQL**, com telas server-side (templates + HTMX + Alpine.js).

Este README é o mapa do sistema: o que ele é, como as peças se encaixam, como rodar e
como desenvolver em cima dele. Dois documentos aprofundam o que aqui está resumido:

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md): núcleo, modularidade, padrões,
  todas as variáveis de ambiente, rotas, deploy, design system e o passo a passo de
  um módulo novo, com referências aos arquivos de implementação.
- [`docs/MODULOS_E_FLUXOS.md`](docs/MODULOS_E_FLUXOS.md): cada módulo por dentro
  (models, estados, services, sinais, telas, regras) e os fluxos ponta a ponta com
  diagramas.

> **Revisão documental: 21/10/2026.** O [Estado atual](docs/ESTADO_ATUAL.md)
> identifica a base de código publicada e as integrações; os commits de interface que
> a revisão listava como locais foram publicados no décimo primeiro bloco do
> [CHANGELOG](CHANGELOG.md). O [índice da documentação](docs/README.md) separa manuais
> atuais, planos e registros históricos.
>
> A [especificação](docs/ESPECIFICACAO.md) descreve o produto implementado.
> O [CLAUDE.md](CLAUDE.md) reúne convenções de desenvolvimento. Uma funcionalidade
> escrita ou uma evidência antiga de teste não comprova ativação em produção.

> **Sobre este repositório.** Este é o fork [`VicZk/vo_testa`](https://github.com/VicZk/vo_testa)
> do projeto original [`Geffersonvivan/vo_testa`](https://github.com/Geffersonvivan/vo_testa).
> Ele anda como um projeto próprio ligado ao original: recebe as novidades de lá e
> desenvolve aqui, na branch `dev` (a padrão deste fork), sem mexer no original. O
> Gefferson é colaborador deste fork e pode levar para o original o que quiser daqui; o
> passo a passo está em [12.1](#121-fluxo-de-trabalho-com-o-fork).

---

## Sumário

1. [O que é o sistema](#1-o-que-é-o-sistema)
2. [Começando: rodar localmente](#2-começando-rodar-localmente)
3. [Anatomia do repositório](#3-anatomia-do-repositório)
4. [Arquitetura](#4-arquitetura)
5. [Módulos](#5-módulos)
6. [Fluxos principais](#6-fluxos-principais)
7. [Rotas](#7-rotas)
8. [Configuração](#8-configuração)
9. [Testes e qualidade](#9-testes-e-qualidade)
10. [Deploy e operação](#10-deploy-e-operação)
11. [Design system "Lampião"](#11-design-system-lampião)
12. [Como desenvolver](#12-como-desenvolver)
13. [Desenvolvendo no Windows](#13-desenvolvendo-no-windows)
14. [Glossário](#14-glossário)
15. [Documentação relacionada](#15-documentação-relacionada)

---

## 1. O que é o sistema

Um processo Django atende quatro públicos, separados por URL:

| Endereço | Público | O que é |
|---|---|---|
| `/` | hóspede | Site público: vitrine dos quartos, motor de reservas em 5 passos, páginas legais, SEO |
| `/crm/` | equipe | PMS/CRM: reservas, recepção, caixa, PDVs, governança, financeiro, comercial etc. |
| `/hospede/<token>/` | hóspede hospedado | Portal sem login (QR): extrato, pedidos ao restaurante, limpeza, manutenção, pré-check-in, check-out expresso |
| `/lp/…`, `/captacao/…` | visitante de campanha | Landing pages com captura de lead para o funil comercial |

**A pousada modelada:** 24 quartos de pernoite (`Quarto 01` a `Quarto 24`, em quatro alas)
e unidades de day use ("Dia na Pousada", `DAY-01` a `DAY-04` ativas), com restaurante da
piscina, loja, lavanderia e equipe com escala.

**Estratégia de produto:** o sistema é um **núcleo + módulos contratáveis**, para que no
futuro possa ser oferecido a outras pousadas. Cada módulo é um app Django, ativado por
cliente na tabela `ModuloContratado`.

**Ambientes:** os registros operacionais associam `www.pousadavotesta.com.br` ao
Railway e à `main` do original. Essa conexão e a versão em produção não foram
consultadas nesta revisão. Esta é uma **fork de desenvolvimento**: publicar na
`dev` daqui não comprova deploy no original (ver [§12.1](#121-fluxo-de-trabalho-com-o-fork)).

### Estado dos módulos

| Módulo | Situação |
|---|---|
| Núcleo (pessoas, quartos, temporadas, caixa, financeiro, estoque, recados, dashboard) | Implementado; homologação do caixa de 04/07/2026 é registro histórico |
| Reservas (mapa, ciclo, conta do hóspede, grupos, FNRH local, BOH, colchões extras) | Implementado |
| Loja, Restaurante, Lavanderia, Governança, Manutenção, Escala, Estoque | Implementados |
| Site + motor de reservas, Portal do hóspede | Implementados |
| Comercial (funil, WhatsApp, e-mail, landing pages) e Marketing (campanhas) | Implementados |
| Relatórios, Auditoria (pendências, trilha e fechamentos), Conciliação (OFX e cartão) | Implementados |
| Pagamentos online | Safrapay implementado; ativação em produção a confirmar. Pix direto tem baixa manual |
| FNRH Digital (envio ao governo) | Integração Serpro escrita; credenciais e homologação precisam ser verificadas no ambiente |
| Fiscal (NFS-e/NFC-e) | Focus NFe v2 implementado; cadastro, credenciais e homologação pendentes de configuração |
| NPS | Pesquisa pós-estadia, resposta por token e painel implementados |
| Canais/OTAs | Adaptador Channex e operação no CRM; ativação e homologação real pendentes ([guia](docs/CANAIS.md)) |
| CRM do Hóspede | Evolução de catálogo |

Os gateways usam **`simulado`** por padrão, com uma exceção importante de comportamento:
`EMAIL_GATEWAY=simulado` envia pelo backend do Django e pode usar **SMTP real** se
`EMAIL_HOST` estiver preenchido. Para desenvolvimento sem envio real, deixe as
credenciais externas vazias. Detalhes e limites: [Estado atual](docs/ESTADO_ATUAL.md).

O código publicado inclui relatórios de **carteira (OTB), pickup, ritmo de vendas e
custo de distribuição**, três relatórios de governança, restrições de venda,
fechamento diário e kit de contingência. A nova visão gráfica da governança e os
refinos mais recentes de navegação ainda estavam locais na data desta revisão.

A arquitetura modular permite ativação por instalação; não implementa isolamento
SaaS de vários hotéis no mesmo banco.

---

## 2. Começando: rodar localmente

### 2.1 Pré-requisitos

- **Python 3.14** (o projeto usa `target-version = py314`)
- **PostgreSQL**; o ambiente de referência e o CI usam **PostgreSQL 16**. SQLite não serve: a trava contra overbooking usa
  `ExclusionConstraint` com a extensão `btree_gist`.
- **Docker** (o jeito mais simples de ter o Postgres) e **Git**

### 2.2 Ambiente

**macOS / Linux**

```bash
git clone https://github.com/VicZk/vo_testa.git && cd vo_testa
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt        # inclui requirements.txt
source .venv/bin/activate                           # comandos python abaixo usam esta venv

docker run -d --name vo_testa_pg -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=vo -e POSTGRES_PASSWORD=vo_local_dev -e POSTGRES_DB=crm_vo_testa \
  -v vo_testa_pgdata:/var/lib/postgresql/data postgres:16
```

**Windows (PowerShell)**: veja os cuidados em [§13](#13-desenvolvendo-no-windows).

```powershell
uv python install 3.14
uv venv --python 3.14 $HOME\.venvs\vo_testa          # venv fora do OneDrive
uv pip install --python $HOME\.venvs\vo_testa\Scripts\python.exe -r requirements-dev.txt
# Nos passos seguintes, use este executável no lugar de python:
$PousadaPython = Join-Path $HOME '.venvs\vo_testa\Scripts\python.exe'
# Exemplo: & $PousadaPython manage.py migrate

docker run -d --name vo_testa_pg -p 127.0.0.1:55432:5432 `
  -e POSTGRES_USER=vo -e POSTGRES_PASSWORD=vo_local_dev -e POSTGRES_DB=crm_vo_testa `
  -v vo_testa_pgdata:/var/lib/postgresql/data postgres:16
```

Crie o `.env` na raiz (ele é ignorado pelo git; modelo completo em `.env.example`):

```ini
DEBUG=1
DATABASE_URL=postgres://vo:vo_local_dev@127.0.0.1:55432/crm_vo_testa
```

### 2.3 Banco e dados iniciais

```bash
python manage.py migrate
python manage.py createsuperuser
```

O `migrate` já cria os módulos ativos, as formas de pagamento, o almoxarifado central, o
tipo "Dia na Pousada" com as unidades `DAY-0N` e as áreas de acesso dos gerentes.

Depois, a estrutura física da pousada:

```bash
python manage.py estrutura_inicial --completo
```

O comando cria os 4 tipos de quarto de pernoite e os 24 quartos (`Quarto 01` a
`Quarto 24`, só o que faltar, sem alterar nada que já exista) e, com `--completo`, roda
em seguida `configurar_camas` (posições de cama, sofás e pool de colchões extras),
`carregar_tarifas` (tabela de preços aprovada) e `sincronizar_vitrine` (um card por
quarto no site, com 9 destaques). Os seeds de preço e camas dependem exatamente
desses nomes de tipos e quartos. Use o fluxo completo em banco novo; os comandos
chamados por `--completo` possuem efeitos próprios sobre camas, tarifas e vitrine.

**Dados de demonstração (opcional).** Montam sozinhos num banco novo, nesta ordem:

```bash
python manage.py popular_demo          # reservas, caixa, contas, estoque e recados "[demo]"
python manage.py popular_estoque       # catálogo, depósitos e kardex
python manage.py popular_lavanderia --limpar
python manage.py popular_escala --limpar
python manage.py popular_manutencao --limpar
python manage.py popular_lotacao       # ~80% de ocupação: Reservas, Loja, Caixa e Governança
```

- Usam o usuário `gvivan` se existir, senão o primeiro superusuário, senão um usuário de
  sistema (`_demo`) — não é preciso criar o superusuário antes.
- Abrem o caixa do módulo certo (o caixa é por módulo, ver [§4.2](#42-o-núcleo)):
  Reservas para as reservas, Loja para o balcão, Lavanderia para a entrega.
- O check-in da demonstração passa pela trava da FNRH só dentro do comando (hóspede de
  mentira não tem ficha); o sistema em pé continua com a trava ligada.
- `popular_escala` cria a equipe que faltar (3 recepcionistas e 3 camareiras "(demo)").
- `popular_marketing`, `popular_comercial`, `popular_templates_email` e
  `popular_respostas_rapidas` funcionam direto.
- O teste `DemonstracaoBancoNovoTests` monta a demonstração num banco vazio a cada push.

### 2.4 Subir

```bash
python manage.py runserver
```

| | Endereço |
|---|---|
| Site público | <http://127.0.0.1:8000/> |
| CRM | <http://127.0.0.1:8000/crm/> (login em `/crm/entrar/`) |
| Admin do Django | <http://127.0.0.1:8000/crm/admin/> |

Em desenvolvimento o MFA não é obrigatório (`MFA_OBRIGATORIO=1` liga para testar) e todo
e-mail é impresso no terminal (sem `EMAIL_HOST`, o backend é o de console).

### 2.5 Testes

```bash
python manage.py test --noinput          # suíte inteira; quantidade e tempo variam
python manage.py test apps.reservas      # um app
```

Detalhes em [§9](#9-testes-e-qualidade).

---

## 3. Anatomia do repositório

```
.
├── apps/                 19 apps Django: o núcleo e os módulos (tabela abaixo)
├── config/               settings.py, urls.py, wsgi.py, asgi.py
├── templates/            telas do CRM: base.html (app shell), uma pasta por app, componentes/
├── static/               CSS do CRM (css/app.css = design system), js/, img/, fonts/, lp/
├── LPs/                  HTML das landing pages, servido direto do disco
├── docs/                 especificação, planos de implementação, estudos, mockups
├── media/                uploads (fotos de quartos e galeria versionadas; o resto, não)
├── evidencias/           pacote de homologação Safrapay
├── Logo/                 artes da marca (não usadas em runtime)
├── manage.py
├── railway.json          build, start e healthcheck do deploy
├── requirements.txt      dependências de produção
├── requirements-dev.txt  + ruff, bandit, pip-audit, detect-secrets, pre-commit
├── ruff.toml  .pre-commit-config.yaml  .secrets.baseline
├── tailwind.config.js  tailwind.src.css     (só para o site público)
├── .env.example          modelo das variáveis de ambiente
├── CLAUDE.md             memória de trabalho do Claude Code
└── .github/              workflow de segurança + Dependabot
```

### Os apps

| App | Módulo contratável | Papel |
|---|---|---|
| `nucleo` | — (núcleo) | Usuários e acessos, pessoas, quartos, temporadas, caixa, financeiro, motor de estoque, recados, dashboard, busca global, trilha de auditoria, catálogo de módulos |
| `reservas` | `reservas` | Ciclo da reserva, antioverbooking, mapa, conta do hóspede, tarifas, grupos, FNRH/BOH, colchões e berços |
| `pagamentos` | `pagamentos` | Cobranças Pix/cartão/boleto/link, link público de pagamento, webhook, liquidação |
| `portal` | `appsite` | Portal do hóspede por token |
| `fiscal` | `fiscal` | Documentos fiscais (NFS-e, NFC-e, NF-e) com gateway plugável |
| `site` (label **`core`**) | — (serve `/`) | Site público, motor de reservas, páginas legais, e-mails transacionais |
| `loja` | `loja` | PDV de balcão |
| `restaurante` | `restaurante` | Comandas por mesa, guarda-sol ou bar |
| `lavanderia` | `lavanderia` | Serviço ao hóspede (fila por etapa, cesta de peças, cobrança) + rouparia (enxoval com lote e extrato) |
| `governanca` | `governanca` | Situação de limpeza por quarto e fila de faxinas |
| `manutencao` | `manutencao` | Ordens de serviço, bloqueio e liberação de quarto |
| `escala` | `escala` | Turnos, grade semanal, ausências e trocas |
| `estoque` | `estoque` | Telas de gestão sobre o motor de estoque do núcleo |
| `comercial` | `comercial` | Funil de vendas, cotações, WhatsApp, e-mail, landing pages |
| `marketing` | `marketing` | Fluxo de campanhas (fases, peças, verba) sobre o comercial |
| `conciliacao` | — (área Financeiro) | Conciliação bancária (OFX) e de cartão (NSU) |
| `relatorios` | `relatorios` | Relatórios por período com exportação |
| `auditoria` | `auditoria` | Varredura de pendências + leitura da trilha de auditoria |
| `nps` | — (área NPS) | NPS pós-estadia, painel e acompanhamento |

Cada app segue a mesma forma: `models.py`, `services.py` (a interface pública do módulo),
`views.py`, `urls.py`, `forms.py`, `admin.py`, `tests.py`, `migrations/` e, quando há,
`signals.py`, `receivers.py`, `gateways.py` e `management/commands/`. Os templates do CRM
ficam em `templates/<app>/`; os do site, em `apps/site/templates/site/`.

---

## 4. Arquitetura

### 4.1 Visão geral

```mermaid
flowchart TB
    subgraph Navegador
        H[Hóspede: site, portal, link de pagamento]
        E[Equipe: CRM /crm/]
    end
    subgraph Django["Django (gunicorn no Railway)"]
        U[config/urls.py] --> V[views: finas, com decorators de acesso]
        V --> S[services.py: regras e interface pública de cada módulo]
        S --> M[models]
        S -. sinais .-> S2[receivers de outros módulos]
        S --> G[gateways plugáveis: pagamentos, FNRH, fiscal, WhatsApp, e-mail, mídia]
        A[audit.py: trilha automática] -.-> M
    end
    H --> U
    E --> U
    M --> PG[(PostgreSQL)]
    G --> X[Safrapay · Serpro FNRH · NFS-e · Meta WhatsApp/CAPI · SMTP]
    Django --> R2[(Cloudflare R2: mídia, opcional)]
```

Princípios que guiam o código:

1. **Fonte de verdade única.** Disponibilidade pertence a Reservas; dinheiro, ao
   financeiro do núcleo; estoque, ao motor de estoque do núcleo. Nenhum módulo duplica
   essas regras.
2. **Módulos isolados.** Um módulo fala com outro pelo `services.py` dele, nunca
   importando models internos (o núcleo é a exceção, porque é compartilhado).
3. **Degradação graciosa.** Cada módulo funciona sem os opcionais: a Loja sem Reservas só
   vende no balcão; com Reservas, também lança na conta do quarto.
4. **Ativação por cliente.** Menus, permissões e integrações consultam
   `modulo_ativo()`; nada é fixo no código.
5. **Trilha de auditoria.** Toda escrita feita por um usuário fica registrada, e as
   operações sensíveis (estorno, cancelamento, ajuste, reabertura de caixa) guardam o
   motivo.

### 4.2 O núcleo

`apps/nucleo` concentra o que não é módulo contratável. Os models são um **pacote**
(`apps/nucleo/models/`) reexportado por `apps.nucleo.models`:

| Arquivo | Conteúdo |
|---|---|
| `usuarios.py` | `Usuario` (`AUTH_USER_MODEL`, com `modulos`, `areas` e MFA), `ModuloContratado`, `modulo_ativo()` |
| `cadastros.py` | `Pessoa` + papéis (`Hospede`, `Prospecto`, `Funcionario`, `Fornecedor`, `Agencia`), `TipoUH`, `UH`, `PosicaoCama`, `ConfiguracaoUH`, `Temporada` |
| `financeiro.py` | `FormaPagamento`, `SessaoCaixa`, `MovimentoCaixa`, `LancamentoFinanceiro`, `ContaPagarReceber`, `TrilhaAuditoria`, `receber_no_caixa()`, `estornar_movimento()` |
| `estoque.py` | `Produto` (custo médio ponderado), `LocalEstoque`, `MovimentoEstoque` (kardex), `Inventario` e os serviços `saldo`, `registrar_entrada`, `registrar_saida`, `transferir`, `ajustar` |
| `suprimentos.py` | Embalagens de compra, lotes e registros imutáveis, conversão de recebimento, contagem por lote e composição dos pratos |
| `logbook.py` | Recados do turno com conversa |

Peças que todo módulo usa:

- **Pessoa única com papéis.** Hóspede, prospecto, funcionário, fornecedor e agência são
  extensões `OneToOne` de `Pessoa`; "cliente avulso" é uma pessoa sem papel.
- **Estrutura física.** `TipoUH` (categoria, tarifa base, modalidade pernoite ou day use)
  e `UH` (o quarto, com qualidades para a vitrine). `apps/nucleo/estrutura.py` deriva
  capacidade e descrição das camas; `alas.py`, a ala pelo número; `feriados.py` calcula
  os feriados nacionais e de Itá sem banco.
- **Caixa por operador e por módulo.** Cada `SessaoCaixa` é a gaveta de um operador em um
  módulo (Reservas/recepção, Loja, Restaurante, Lavanderia), com uma aberta por vez.
  `receber_no_caixa(usuario, forma, valor, descricao, parcelas, modulo)` é o único ponto
  de recebimento. Movimentos são **imutáveis** (correção é estorno, com motivo) e o
  fechamento é por **conferência cega**.
- **Motor de estoque.** Kardex imutável com quantidade sinalizada, custo médio
  recalculado sob trava de linha e saída que nunca deixa saldo negativo. Entrada,
  saída e transferência aceitam uma `chave` de envio (como a `Venda.chave`): o reenvio
  do mesmo formulário devolve o movimento já gravado. A entrada guarda o fornecedor, e o
  inventário aplica só o que foi contado (`ItemInventario.contado`).
  Perecíveis usam lotes válidos; pratos baixam ingredientes e preservam a origem
  das devoluções. Veja o [manual de compras, perecíveis e pratos](docs/ESTOQUE_COMPRAS.md)
  para configuração e responsabilidades da operação.

### 4.3 Modularidade e controle de acesso

- **Catálogo** (`apps/nucleo/modulos.py`): o enum `Modulo` (17 códigos), `DEPENDENCIAS`
  (ex.: Governança exige Reservas; Loja exige Estoque) e `APRESENTACAO` (grupo do menu,
  ordem, rota principal, e `url_pessoal` quando o módulo tem uma entrada de quem
  opera — a Minha fila da camareira; módulo sem rota aparece como "em construção").
- **Ativação** (`ModuloContratado`): uma linha por módulo, gerida na **Central de
  Módulos** (`/crm/configuracoes/modulos/`), que respeita as dependências.
- **Áreas-core** (`apps/nucleo/areas.py`): permissões do que não é módulo (quartos,
  temporadas, caixa, financeiro, pessoas, funcionários, remuneração, recados, NPS,
  equipe), guardadas em `Usuario.areas`.
- **Decorators** (`apps/nucleo/permissoes.py`):

| Decorator | Efeito |
|---|---|
| `@requer_modulo(Modulo.X)` | Exige login. Módulo inativo → **404** para todos; usuário sem o módulo → **403**; superusuário passa |
| `@requer_area(*areas)` | Exige login e **qualquer uma** das áreas, senão 403 |
| `@requer_gerencia` | Exige `is_staff` ou superusuário |

Usuários, módulos e áreas de cada funcionário são concedidos a partir da tela
**Funcionários** (`/crm/funcionarios/`), que substituiu a antiga "Equipe & Acessos". A
sidebar, a paleta ⌘K e o dashboard se montam conforme o acesso de quem está logado.
Quem não tem nenhum bloco do dashboard (nem Reservas, Estoque, Financeiro, Logbook ou
gerência) entra direto no módulo dele quando só tem um — a camareira na Minha fila —, ou
vê um cartão por módulo quando tem vários.

### 4.4 Como os módulos conversam

**Chamando services.** Exemplos reais:

| Quem | Chama | Para |
|---|---|---|
| Loja, Restaurante, Lavanderia | `nucleo.registrar_saida` + `receber_no_caixa(modulo=…)` ou `reservas.services.lancar_na_conta` | baixar estoque e cobrar no caixa do setor ou na conta do quarto |
| Site | `reservas.services.criar_reserva_site_unidade`, `uhs_disponiveis`, `diaria_media_unidade` | pré-reserva do canal site |
| Portal | `restaurante.abrir_comanda`, `governanca.abrir_faxina`, `manutencao.abrir_os`, `pagamentos.criar_cobranca` | pedidos do hóspede |
| Pagamentos | `reservas.services.confirmar_reserva` | sinal pago confirma a reserva |
| Auditoria | `pendencias_auditoria()` de cada módulo (via `importlib`) | painel de pendências sem importar models |

**Avisando por sinais** (integração "de baixo para cima"). Quem emite usa
`apps.nucleo.sinais.emitir()`; todo receiver leva `@receptor_isolado` e começa checando
`modulo_ativo`. Se um módulo ouvinte falhar, o erro vai para o log e a operação de origem
(check-out, troca de quarto, faxina, reparo, pagamento) continua valendo:

| Sinal | Emitido em | Ouvido por | Efeito |
|---|---|---|---|
| `reservas.quarto_liberado` | check-out e troca de quarto | Governança, Comercial | quarto vira "sujo" com faxina; hand-off pós-estadia |
| `reservas.reserva_encerrada` | cancelamento e no-show | Comercial | tarefa de reabordagem |
| `manutencao.reparo_concluido` | OS concluída que bloqueava o quarto | Governança | faxina antes de revender |
| `governanca.faxina_concluida` | faxina concluída | Lavanderia | recolhe o enxoval do quarto |
| `pagamentos.pagamento_confirmado` | pagamento confirmado | Comercial | ganha a oportunidade do sinal |

Há exceções pontuais e documentadas à regra de não importar models de outro app (ex.:
Fiscal lê `ContaHospedagem` com trava; Marketing embrulha `comercial.Campanha` por
desenho). A lista completa está em [`docs/ARQUITETURA.md` §5.1](docs/ARQUITETURA.md).

### 4.5 Gateways plugáveis

Cada integração externa é escolhida por uma variável e sempre começa em `simulado`:

| Variável | Implementações | Situação |
|---|---|---|
| `PAGAMENTOS_GATEWAY` | `simulado`, `safrapay` | Safrapay pronto para Pix, cartão e boleto (homologação) |
| `PIX_DIRETO` (flag) | BR Code gerado localmente | Sem PSP: confirmação manual pela recepção |
| `FNRH_GATEWAY` | `simulado`, `serpro` | Fluxo da API v2 escrito; conferir credenciais e homologação no ambiente |
| `FISCAL_GATEWAY` | `simulado`, `focus` | Focus NFe v2: emissão, consulta, cancelamento e retorno autenticado; exige homologação |
| `WHATSAPP_GATEWAY` | `simulado`, `cloud` | Cloud API (Meta), assinatura do webhook e confirmação do identificador de envio |
| `EMAIL_GATEWAY` | `simulado`, `smtp`, `ses` | SMTP e SES implementados; simulado usa memória e não envia externamente |
| `MIDIA_GATEWAY` | `simulado`, `meta`, `google` | Meta CAPI pronta; Google stub |
| `DECISAO_GATEWAY` | `simulado`, `jev` | Piloto de score de lead |

Para integrar um provedor novo: criar a classe no `gateways.py` do módulo, registrá-la no
dicionário de gateways e documentar as variáveis no `.env.example`.

### 4.6 Regras de dinheiro

1. Valores sempre em `DecimalField`; nada de `float` em dinheiro.
2. Livros-razão imutáveis (`MovimentoCaixa`, `MovimentoEstoque`, `LancamentoConta`,
   `MovimentoEnxoval`): correção é movimento inverso, nunca `UPDATE` ou `DELETE`.
3. Todo item vendável e todo lançamento da conta têm **natureza fiscal**: `SERVICO`
   (diárias e serviços → NFS-e/ISS) ou `CONSUMO` (produtos → NFC-e/NF-e/ICMS).
4. Dinheiro na tela sempre pelo filtro `|intcomma_brl` (`R$ 1.600,00`).
5. Leitura-modificação-escrita de saldo sob trava de linha (`apps.nucleo.sistema.travar`).

### 4.7 Trilha de auditoria automática

`apps/nucleo/audit.py` liga sinais `pre_save`/`post_save`/`post_delete` em **todos** os
models de `apps.*` (com poucas exclusões) e registra criar, editar (com diff campo a
campo) e excluir, além de login e logout. Um middleware publica o usuário e o IP da
requisição para que qualquer service saiba a quem atribuir a ação. Só há registro quando
existe um usuário real no contexto (seeds, migrations e rotinas de sistema não poluem,
nem pagam a leitura do estado anterior).
Fluxos com motivo (estorno, cancelamento, troca de quarto, reabertura de caixa) também
chamam `registrar_auditoria(...)` explicitamente. A leitura fica no módulo Auditoria,
com frases legíveis e exportação CSV.

### 4.8 Camadas de segurança

- `SECRET_KEY` obrigatória em produção; HTTPS, HSTS e cookies seguros com `DEBUG=0`.
- Login com limite de tentativas (`LoginComLimite`) e MFA por TOTP com códigos de backup
  (obrigatório para superusuário em produção).
- Content-Security-Policy por middleware (começa em modo de observação).
- Webhooks com verificação de assinatura ou token; o de pagamento consulta o provedor em
  vez de confiar no corpo da requisição.
- Exportações CSV com neutralização de fórmulas; `Referrer-Policy: same-origin` para
  proteger tokens em URL.
- No CI: pip-audit, bandit, regras de segurança do ruff, gitleaks e `check --deploy`.
- Medição só com licença (LGPD): GA4, Google tag e Meta Pixel ficam no HTML como
  `<script type="text/plain" data-consentimento>` e só ligam no "Aceitar" do aviso de
  cookies (`templates/componentes/consentimento.html` + `static/js/consentimento.js`).
  Vale no site, nas páginas de captação e nas LPs autocontidas de `LPs/`, onde o servidor
  (`views_lp`) põe o aviso ao servir o arquivo; um teste barra LP nova com tag solta.

---

## 5. Módulos

Resumo de cada módulo. O detalhe (models, estados, services, sinais, telas e regras)
está em [`docs/MODULOS_E_FLUXOS.md`](docs/MODULOS_E_FLUXOS.md).

**Reservas.** Fonte da disponibilidade e da conta do hóspede. Estados: orçamento,
pré-reserva, confirmada, hospedada, check-out, cancelada, no-show; só os três do meio
seguram o quarto. Overbooking é impossível no banco (`ExclusionConstraint` sobre
`daterange(checkin, checkout)`, com a noite da saída livre). Preço por quarto, temporada
e número de pessoas (sozinho paga 70%; criança até 5 anos não paga, de 6 a 15 paga meia
pessoa adicional), feriados automáticos, pool global de colchões extras e berços por
noite, grupos com conta-mãe, troca de quarto arrastando no mapa, FNRH por hóspede com
trava de check-in, pré-check-in por QR e BOH mensal com exportação. O detalhe da
reserva tem um painel financeiro: total previsto, o que já foi pago (pela gaveta,
online ou faturado, líquido de estornos), o sinal pendente, o saldo e as cobranças de
Pagamentos com o link público (copiar ou mandar pelo WhatsApp na própria linha). As ações
ficam numa barra logo abaixo da ficha: o que fazer agora em destaque (confirmar,
check-in, check-out), as alterações ao lado (sinal, lotação, transferir datas, estender,
trocar de quarto, QR, NFS-e) e o que desfaz separado no fim (não compareceu, cancelar,
com confirmação); o formulário abre num painel largo, um por vez. O que impede o
check-in (FNRH pendente, menor sem responsável) aparece antes do clique.
Restrições de venda por período (`RestricaoVenda`, tela em Temporadas → "Restrições de
venda"): estadia mínima — vale para qualquer estadia que toque o período, e com várias
regras vale o maior mínimo —, fechado para chegada, fechado para saída e parar vendas,
na casa toda, num tipo ou num quarto. No site a regra barra e diz o motivo; na recepção é
aviso, e só "parar vendas" exige gerência (fica na trilha). Kit de contingência
(`reservas:kit`): a folha A4 do dia — hospedados com saldo, chegadas com telefone,
saídas, situação dos quartos — para a recepção seguir quando a internet cair, com cópia
diária por e-mail. No-show automático (Tabela de Preços → "Horários e não comparecimento",
desligado por padrão): a rotina da madrugada marca a confirmada sem check-in como "não
compareceu" e o quarto volta à venda; "Desfazer não comparecimento" devolve a reserva se
o hóspede aparecer e o quarto ainda estiver livre.

**Pagamentos.** `Cobranca` com token público, estados pendente → pago, estornado,
cancelado ou expirado, e trilha `EventoPagamento`. Confirmação idempotente com trava de
linha; sinal pago confirma a reserva. Link de pagamento público com Pix e cartão. O
link e o Pix copia-e-cola têm "Copiar" e "Enviar pelo WhatsApp" (mensagem pronta, com o
telefone de quem paga), no detalhe da cobrança e na linha do painel.

**Portal do hóspede.** Acesso por token ou QR durante a estadia: extrato, pedido ao
restaurante (lançado na conta), limpeza extra, manutenção, pré-check-in da FNRH e
check-out expresso. Ações registradas em nome do usuário de sistema `_portal`.

**Fiscal.** `DocumentoFiscal` e eventos; emissão a partir da conta separando serviço
(NFS-e) e consumo (NFC-e). NFS-e agrupa por código de serviço: diárias usam o código
configurado; lavanderia e demais serviços exigem classificação explícita. NFC-e usa
itens de vendas/comandas fechadas e cadastro tributário revisado na tela Fiscal.
Referências persistidas evitam duplicidade; respostas incertas exigem consulta antes
de novo envio. [Configuração, limites e homologação](docs/Implementar_fiscal.md).

**Site (`core`).** Vitrine por quarto, busca de disponibilidade, seleção da unidade,
resumo com a política de cancelamento, pré-reserva com retenção de 30 minutos, cobrança
do sinal e e-mail de confirmação. Ainda carrega modelos do site antigo (recibo do canal).
Venda pela internet (CDC art. 49): sem marcar "Li e aceito a política de cancelamento"
não há reserva, e o recibo guarda quando o hóspede aceitou e o texto que estava na tela
(vai também no e-mail). Prazo e retenção vêm de `CANCELAMENTO_ARREPENDIMENTO_DIAS` e
`CANCELAMENTO_RETENCAO_PCT` — a mesma fonte do resumo, do cálculo da devolução e dos
termos de serviço.

**Loja e Restaurante.** PDV com carrinho e comandas por ponto de atendimento; cada item
baixa o estoque na hora e a cobrança vai para o caixa do setor ou para a conta do quarto.
Cupom de 80 mm para impressora térmica pelo navegador (`componentes/cupom.html`): o
recibo da venda e, no restaurante, a conferência da conta com a comanda aberta. Não é
documento fiscal (a NFC-e sai pelo Fiscal).

**Lavanderia.** Receber roupa é um gesto no balcão: quem deixou, para quando fica pronta
(em chip: hoje, amanhã, em 2 dias) e o botão. A ordem abre em seguida com a grade da
tabela de preços — um toque lança a peça, o serviço por quilo pede o peso (1,5 kg) — e a
cesta soma na hora; o recado da recepção ("mancha, não passar") sai impresso com a roupa.
A produção é uma **fila por etapa** (recebida → lavando → pronta), com o próximo passo
escrito no botão do próprio cartão: a lavadeira faz a fila andar no tablet sem abrir
ordem nenhuma, e cada passo fica com a hora na trilha da ordem. O que venceu o prazo
sobe na frente e é o único com cápsula. Na entrega, cobrança no caixa do setor ou na
conta do quarto (desconto só com a gerência, sempre com trilha) e aviso de "roupa
pronta" pelo WhatsApp. Histórico com período, situação e busca.
A **rouparia interna** é o livro-razão do enxoval (limpa → em uso → suja → lavando →
limpa): cada item mostra a barra da situação e um toque no número já propõe o movimento
que sai dele; o lote move várias linhas numa transação (tudo ou nada) e o extrato mostra
cada movimento, com quem, quando e por quê — nada se apaga. A faxina da Governança
recolhe o enxoval sujo sozinha. O mesmo cupom de 80 mm serve de comprovante na recepção
da roupa e de recibo na entrega.

**Governança** (pensada para tablet e celular). A entrada é "Como está a casa": os
quartos em blocos com o número e o estado na frente e quem está dentro (vago, ocupado,
chega hoje, sai hoje, bloqueado, com o hóspede), o progresso do dia ("22 de 24 prontos",
com a hora do check-in), o que pede ação agora, o **plano do dia** na ordem de atacar
(chegadas, saídas, ocupados a arrumar, o resto — e se dá tempo) e a carga de cada
camareira. A camareira tem a **Minha fila** no celular: um cartão por quarto, na ordem de
prioridade, com "Começar"/"Terminei" e "Reportar problema" (abre OS na Manutenção). Quem
está de turno na Escala aparece primeiro no seletor de quem limpa, e "Distribuir a fila"
divide os quartos a limpar entre essas pessoas. Quarto nunca mexido nasce "Pronto". Tocar
num bloco abre a **ficha do quarto** (gaveta de baixo no toque; página própria sem
JavaScript): estado, porquê, quem está dentro e o próximo passo. Liberar o quarto tem
"Desfazer" logo depois, em vez de "tem certeza?" antes. A aba Quartos é a
lista de trabalho: o ciclo **A limpar › Em limpeza › Limpo › Pronto** à vista (e
filtrando), uma frase por linha dizendo por que o quarto está ali e **um** botão por
quarto com o nome do que acontece ("Começar limpeza", "Terminei a limpeza", "Aprovar
limpeza"); "Só os meus" para a camareira e um "Como funciona" com o glossário. As faxinas
nascem do check-out, da manutenção ou do portal. "Devolver para limpar" leva o motivo até
a linha de quem vai limpar de novo. Na ronda, a camareira registra o que
viu em cada quarto (vago, com bagagem, sem bagagem), e a aba "Discrepâncias" confronta com
o sistema: hóspede que saiu sem passar na recepção (skip), saída não lançada, hóspede sem
check-in (sleeper) e quarto não conferido — cada um com o que fazer. Relatórios do setor:
faxinas por camareira, inspeção e retrabalho, discrepâncias da ronda.

**Manutenção.** Ordens corretivas e preventivas (com recorrência), bloqueio do quarto
na disponibilidade e liberação com faxina automática.

**Escala.** Turnos por setor, grade semanal, ausências que impedem escalar, trocas
aprovadas pela gerência e "minha escala" para o funcionário.
Turnos, Ausências e Trocas mantêm a lista na largura disponível; os formulários
ficam em blocos expansíveis acima dela, abertos quando a lista está vazia.

**Estoque.** Telas sobre o motor do núcleo, em cinco abas (Posição, Produtos,
Movimentar, Inventário, Cadastros). A posição mostra o valor parado em mercadoria, o que
está abaixo do mínimo ou zerado e o movimento da semana; cada depósito é um cartão com o
que guarda, e cada linha tem a régua saldo × mínimo e atalhos de entrada, saída e
transferência já preenchidos. Movimentar tem busca de produto, saldo por depósito ao
vivo, fornecedor e nota na entrada e a prévia "saldo hoje → fica com" (com o custo médio
novo). Kardex com saldo corrente; contagem de inventário com progresso, busca e resumo.
Quantidade como se fala ("55 un", "4,5 kg").

**Comercial.** Funil Kanban com ganho só por conversão em reserva, cotação pelo motor de
preços, sinal online, WhatsApp Cloud API dentro do card (janela de 24 h e template de
retomada), e-mail 1:1 e campanhas, landing pages e captura de leads com Meta CAPI.
O «Ganhar» mostra a diária da tabela, a vendida e o total da reserva, com o sinal em
R$ ou em %. Lead fechado pode ser reaberto ou movido por quem tem a área
`comercial_fechados`: tirar do Ganho desfaz a venda em Reservas (`desfazer_venda`:
cancela e devolve o que foi pago pela gaveta; pago online bloqueia até o estorno no
gateway).

**Marketing.** Gerência de campanhas com fases, peças com data, checklist, verba mensal
e calendário, embrulhando as campanhas do Comercial.

**Conciliação.** Importa extrato OFX e arquivo de cartão, casa por valor, data e NSU, e
fecha o mês.

**Relatórios e Auditoria.** Relatórios por mês (produção, ocupação, caixa, faturamento
por setor, consumo, funil) com CSV; e os de receita vendida: carteira (OTB, o que já está
vendido para o mês), pickup (entrou × saiu nos últimos 7/14/30 dias), ritmo de vendas
(por antecedência) e custo de distribuição por canal (percentuais na Tabela de Preços).
Painel de pendências que cada módulo alimenta e leitura da trilha.

---

## 6. Fluxos principais

Os fluxos completos, passo a passo e com diagramas, estão em
[`docs/MODULOS_E_FLUXOS.md` §B](docs/MODULOS_E_FLUXOS.md). Em resumo:

**Reserva pelo site.** Busca (`/reservar/`) → quartos disponíveis com preço → escolha da
unidade e das camas → resumo → `finalizar_reserva` cria hóspede e **pré-reserva** no
CRM com retenção → cobrança do sinal → página de pagamento → `confirmar_pagamento`
confirma a reserva.

**Do check-in ao quarto limpo:**

```mermaid
flowchart LR
    A[FNRH na recepção ou pelo QR] --> B{fichas completas?}
    B -- não --> A
    B -- sim --> C[check-in: abre a conta e lança diárias, ISS e taxa]
    C --> D[consumos: loja, restaurante, lavanderia, portal → conta do quarto]
    D --> E[recebimento no caixa da recepção]
    E --> F{saldo zero?}
    F -- não --> E
    F -- sim --> G[check-out + sinal quarto_liberado]
    G --> H[Governança: quarto sujo + faxina]
    H --> I[Lavanderia recolhe o enxoval]
    G --> J[Fiscal: NFS-e da parte de serviço]
    G --> K[Comercial: pós-estadia]
```

**Caixa do turno.** Abrir com fundo de troco → receber, reforçar, sangrar → fechar
informando o contado sem ver o esperado → diferença registrada e auditada. Estorno e
reabertura só pela gerência, sempre com motivo.

**Comercial.** Lead do site, landing page ou WhatsApp → card no funil com tarefa de
primeiro contato em 24 h → cotação → sinal pelo link → conversão em reserva (manual ou
automática quando o sinal é pago) → hand-off depois do check-out.

---

## 7. Rotas

Tudo parte de `config/urls.py`:

| Prefixo | Quem atende | Acesso |
|---|---|---|
| `/` e páginas do site | `apps.site.urls` (`core`) | público |
| `/hospede/<token>/…` | `apps.portal.urls` | hóspede por token |
| `/lp/…`, `/captacao/…`, `/privacidade/`, `/email/descadastrar/…` | `apps.comercial` | público |
| `/whatsapp/webhook/` | `apps.comercial.urls_whatsapp` | Meta (assinatura) |
| `/crm/` | `apps.nucleo.urls` (dashboard, pessoas, quartos, caixa, financeiro…) | equipe |
| `/crm/<módulo>/…` | `apps.<módulo>.urls`, namespace igual ao código do módulo | equipe |
| `/crm/pagamentos/pagar/<token>/` | link de pagamento | público, por token |
| `/crm/admin/` | admin do Django | equipe |
| `/healthz/` | probe do Railway | infra |

São cerca de 300 rotas declaradas no projeto, sem contar as do admin. A tabela completa
por grupo está em
[`docs/ARQUITETURA.md` §6](docs/ARQUITETURA.md).

---

## 8. Configuração

Tudo que varia por ambiente vem de variáveis (`.env` em desenvolvimento, painel do
Railway em produção). As essenciais:

| Variável | Para quê |
|---|---|
| `DEBUG` | `1` só em desenvolvimento |
| `SECRET_KEY` | obrigatória em produção |
| `DATABASE_URL` | conexão com o Postgres |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | domínios aceitos |
| `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_PUBLIC_DOMAIN` | mídia no Cloudflare R2 (as cinco juntas; sem elas, disco local) |
| `EMAIL_HOST` e afins | SMTP; vazio = e-mail no console |
| `SITE_PUBLIC_URL` | links absolutos nos e-mails |
| `PAGAMENTOS_GATEWAY`, `SAFRAPAY_*`, `PIX_DIRETO`, `PIX_CHAVE` | pagamentos |
| `FNRH_GATEWAY`, `FNRH_API_*`, `FNRH_BLOQUEAR_CHECKIN` | FNRH Digital e trava de check-in |
| `FISCAL_GATEWAY`, `FISCAL_NFSE_*` | emissão fiscal |
| `WHATSAPP_*`, `META_*`, `GA_MEASUREMENT_ID` | comunicação e mídia |
| `RESERVA_RETENCAO_MINUTOS`, `PRECO_*`, `CANCELAMENTO_*` | regras de reserva e preço |
| `CHECKOUT_TOLERANCIA_ARREDONDAMENTO` | resíduo de centavos quitado sozinho no check-out (padrão R$ 0,10) |
| `LOG_LEVEL` | nível dos logs no stdout (padrão INFO) |
| `REDIS_URL` | cache compartilhado em Redis; vazio = tabela no próprio Postgres |
| `SAFRAPAY_TIMEOUT` | segundos de espera pela Safrapay (padrão 10) |
| `SENTRY_DSN` | monitoramento de erros no Sentry (sem corpo de requisição nem variáveis locais) |
| `BACKUP_DIR` | pasta persistente do `backup_banco`; sem destino o comando falha e registra o problema |
| `BACKUP_R2_*` | cópia externa em bucket privado dedicado, separado da mídia pública |
| `KIT_CONTINGENCIA_EMAILS` | quem recebe a folha do dia por e-mail, separados por vírgula (vazio = ninguém) |
| `ROTINAS_MONITOR_FREQUENTES`, `ROTINAS_MONITOR_DIARIAS` | URL de um check do Healthchecks.io por grupo de rotinas: avisa quando o cron para, trava ou falha (vazio = não avisa) |
| `DB_JIT` | `1` religa o JIT do Postgres (desligado por padrão: deixava telas pequenas lentas) |
| `URL_PREFIX` | roda o sistema sob um caminho (ex.: `votesta` para `https://viczk.cloud/votesta`): o nginx tira o prefixo e o Django o põe em todo link, estático e cookie. Vazio na produção |

A lista completa, com padrões e efeitos, está em
[`docs/ARQUITETURA.md` §7](docs/ARQUITETURA.md). Durante os testes a flag `TESTING`
desliga a trava da FNRH, as taxas automáticas, o MFA e o limite de login.

---

## 9. Testes e qualidade

- **Onde:** dentro de cada app (`apps/<app>/tests.py` e `tests_*.py`), com `TestCase` do
  Django. Regras de dinheiro e de disponibilidade são sempre testadas.
- **Resultados:** contagens e tempos em auditorias/changelogs pertencem à execução
  registrada. Consulte o resultado da suíte e do CI no commit que será publicado.
- **Navegador:** `apps/site/tests_e2e.py` usa Playwright (reserva no site, calendário,
  funil, a LP da Inauguração e o menu lateral do CRM). Localmente é pulado se ele não
  estiver instalado (`pip install playwright==1.64.0 && playwright install chromium`); no
  CI roda num job próprio, onde faltar o Playwright é erro.
- **Rodar:**

```bash
python manage.py makemigrations --check --dry-run
python manage.py test --noinput                         # tudo
python manage.py test apps.reservas.tests_precos        # um arquivo
python -m playwright install chromium
E2E_OBRIGATORIO=1 python manage.py test apps.site.tests_e2e --noinput
```

- **Lint e segurança:** `ruff check apps config`, `bandit -r apps config -ll`,
  `pip-audit -r requirements.txt` e `pre-commit install` para os hooks locais.
- **CI de testes** (`.github/workflows/testes.yml`): a cada push em `main` e `dev` e em
  todo PR, roda o ruff, sobe um PostgreSQL 16, confere se as migrations estão em dia
  (`makemigrations --check`) e roda a suíte inteira; em paralelo, o job "Fluxos no
  navegador" roda os testes do Playwright com Chromium. Proteção de branch e espera
  dos checks pelo serviço de deploy são configurações externas; precisam ser
  conferidas antes de uma publicação de código.
- **CI de segurança** (`.github/workflows/security.yml`): pip-audit, bandit, regras de
  segurança do ruff, semgrep (só relatório), `check --deploy` e gitleaks.
- **Máquina do CI:** os workflows fixam `ubuntu-24.04` e Python 3.14.
- **PowerShell:** use `$env:E2E_OBRIGATORIO = '1'` antes do comando de navegador;
  `playwright` está em `requirements-dev.txt`, mas o Chromium precisa ser instalado.
- **Documentação:** links, comandos, configuração e diff são conferidos; uma revisão
  somente de texto não representa nova homologação dos módulos.

---

## 10. Deploy e operação

**Railway** (`railway.json`): build pelo Railpack; a cada deploy roda
`migrate`, `collectstatic` e sobe `gunicorn config.wsgi:application --workers 2`;
healthcheck em `/healthz/`, que confere o banco e responde 503 se ele não atender (um
container sem banco não deve substituir o que está no ar). A configuração de
auto-deploy do ambiente deve ser confirmada antes de publicar código.
Estáticos saem pelo WhiteNoise; em produção, o storage usa manifesto com hashes.

**Logs:** tudo vai para a saída padrão, que o Railway mostra nos logs do deploy: erros
500 com traceback (`django.request`) e falhas de receivers de sinais
(`apps.nucleo.sinais`). O nível geral vem de `LOG_LEVEL` (padrão `INFO`).

**Mídia:** com as cinco variáveis `R2_*`, uploads vão para o Cloudflare R2; rode
`python manage.py migrar_media_r2` uma vez para levar o que já está em disco. Sem R2, a
mídia fica no disco do container, que é apagado a cada deploy.

**Deploy:** as migrations rodam no `preDeployCommand` (uma vez por deploy, antes do
container novo entrar no ar; se falharem, o deploy é abortado) e o gunicorn sobe com 2
workers × 4 threads e timeout de 60 s.

**Rotinas agendadas.** `python manage.py rotinas --grupo canais|frequentes|diarias` roda as
tarefas periódicas, cada uma isolada: uma falha vai para o log, não impede as outras e
faz o comando terminar com erro. No Railway, crie dois serviços de Cron a partir deste
repositório, com as mesmas variáveis do serviço web e o arquivo de configuração
`deploy/railway.rotinas.json` (a cada 10 min) ou `deploy/railway.rotinas-diarias.json`
(03h15 de Brasília). Para Canais, há um serviço independente a cada minuto em
`deploy/railway.rotinas-canais.json`; sem módulo e conexão ativos ele não acessa o provedor.

| Grupo | Comando | O que faz |
|---|---|---|
| canais | `sincronizar_canais` | captura revisões, confirma recebimento após persistir e atualiza disponibilidade, tarifas e restrições quando necessário |
| frequentes | `expirar_reservas` | cancela pré-reservas e grupos com retenção vencida |
| frequentes | `expirar_recibos_site` | marca como expirados os recibos do site não pagos |
| frequentes | `enviar_fnrh_pendentes` | reenvia à FNRH Digital as fichas pendentes ou com erro |
| frequentes | `enviar_campanhas_email` | dispara campanhas de e-mail agendadas |
| frequentes | `reenviar_confirmacoes_site` | manda a confirmação das reservas do site que ficaram sem e-mail |
| frequentes | `reprocessar_webhooks_whatsapp` | reprocessa mensagens do WhatsApp cujo processamento falhou (até 5 tentativas) e apaga as processadas há mais de 30 dias |
| frequentes | `reenviar_emails_pendentes` | reenvia e-mails do Comercial presos em "pendente" ou com erro (até 3 tentativas) |
| diarias | `marcar_no_shows` | no-show automático, se ligado na Tabela de Preços: confirmada sem check-in vira "não compareceu" e o quarto volta à venda |
| diarias | `fechar_dia` | fechamento do dia de ontem (ocupação, chegadas, saídas, no-shows, receita, saldo em aberto) — imutável |
| diarias | `enviar_conversoes_pendentes` | reenvia conversões de mídia pendentes |
| diarias | `sincronizar_gastos_midia` | puxa o gasto das plataformas de anúncio |
| diarias | `backup_banco` | dump PostgreSQL verificado em `BACKUP_DIR` e/ou R2 privado, com SHA-256 e retenção de 30 dias |
| diarias | `purgar_trilha` | apaga da trilha o que passou de `TRILHA_RETENCAO_DIAS` (0 = guarda sempre) |
| diarias | `gerar_arrumacoes` | uma arrumação para cada quarto em que o hóspede continua |
| diarias | `enviar_kit_contingencia` | manda a folha do dia (kit de contingência) para `KIT_CONTINGENCIA_EMAILS`; vazio = não envia |

**Monitor das rotinas.** Com `ROTINAS_MONITOR_FREQUENTES` e `ROTINAS_MONITOR_DIARIAS`
(um check do [Healthchecks.io](https://healthchecks.io) para cada grupo), as rotinas
avisam quando começam, quando terminam e quando falham — e o monitor manda o alerta se o
aviso não chegar no prazo. Sem isso, um cron parado só aparece em vermelho no painel do
Railway. Configuração dos checks: frequentes com período de 10 min e tolerância de 10 min;
diárias com o cron `15 6 * * *` (UTC) e tolerância de 1 h.

**Backup:** com R2 ou `BACKUP_DIR` configurado e a rotina agendada,
`backup_banco` exige `pg_dump`/`pg_restore` compatíveis e destino persistente configurado.
Grava arquivo e manifesto SHA-256, verifica a cópia e mantém o resultado no painel
**Operação e integrações**. O modo automático nunca substitui um dump por JSON.
O R2 precisa de bucket privado próprio (`BACKUP_R2_*`); local e R2 podem ser usados
simultaneamente. Cópia verificada não substitui ensaio de restauração em banco isolado.
O mesmo painel distingue configuração presente de ensaio registrado para cada integração.
O comando usa: `pg_dump` quando disponível, senão JSON compactado
de todos os dados. Restaurar: `pg_restore --clean --if-exists --no-owner -d
"$DATABASE_URL" arquivo.dump` ou `python manage.py migrate && python manage.py loaddata
arquivo.json.gz`. Teste a restauração num banco separado antes de precisar dela.

**Comandos de operação:** `estrutura_inicial` (banco novo: tipos e os 24 quartos; com
`--completo`, também camas, tarifas e vitrine), `sincronizar_vitrine` (quarto novo no site),
`carregar_tarifas` (tabela de preços aprovada), `configurar_camas` (mudança física de
camas), `migrar_media_r2`. Os de limpeza de demonstração (`zerar_funil`, `sanear_demo`,
`recentrar_demo`, `limpar_nomes_quartos`) são destrutivos e não devem rodar em produção.

Detalhes em [`docs/ARQUITETURA.md` §10](docs/ARQUITETURA.md).

---

## 11. Design system "Lampião"

Toda tela do CRM nasce no design system; nada de estilo paralelo nem cor fixa no template.

- **Tokens** em `static/css/app.css` (`:root`): marca (`--noturno`, `--lampiao`,
  `--madeira`), canvas e superfícies, tinta, fios, cores semânticas (`--sucesso`,
  `--alerta`, `--perigo`, `--info`, `--andamento`), sombras, raios e fontes (Fraunces nos
  títulos, Hanken Grotesk na interface, IBM Plex Mono em dados). Mudança de visual
  global se faz nos tokens. Cor só por token também no `<style>` próprio de uma tela
  (fundos suaves: `--sucesso-bg`, `--alerta-bg`, `--perigo-bg`, `--info-bg`); o teste
  `CorSoPorTokenTests` barra hex e rgba escritos à mão.
- **Componentes:** `.cartao`/`.cartao-el`, `.tabela`/`.quadro`, `.botao-primario`,
  `.botao-neutro`, `.botao-mini`, `.selo-*`, `.kpi`, combos de pessoa e quarto em
  `templates/componentes/`. Tudo o que a equipe manda a alguém (link de pagamento, Pix,
  portal, pré check-in) usa `{% copiar texto rotulo=… recado=… telefone=… %}`: botão
  "Copiar" (com plano B onde a área de transferência do navegador não existe, como no
  `http://` da rede local) e "Enviar pelo WhatsApp" com a mensagem pronta.
- **App shell** (`templates/base.html`): sidebar por permissão, navegação com
  `hx-boost`, paleta de comandos (⌘K ou `/`), toasts a partir das mensagens do Django,
  atalho `N` para nova reserva. Na troca de página só o conteúdo faz a transição (View
  Transition com nomes `menu`, `topo` e `conteudo`): menu e topo ficam parados.
- **Dicas:** um balão só para todo o CRM — `data-dica="texto"` no elemento e o
  `static/js/dicas.js` cuida do resto (centrado no que se vê, dentro da tela, em cima ou
  embaixo; `data-dica-lado="direita"` no menu recolhido). Nada de dica em `::after`.
- **Largura:** o conteúdo para em `--conteudo-max` (1760 px) e centra no monitor grande;
  tela que vive de largura (mapa de reservas, calendário do Marketing) usa
  `{% block conteudo_classe %}conteudo-largo{% endblock %}`.
- **Menu lateral:** nasce recolhido em trilho de ícones (⌘\ ou o botão alterna, e a
  escolha fica no navegador). No trilho cada item tem dica e nome para leitor de tela;
  tudo o que é do trilho mora num `@media (width > 820px)`. O trilho é o menu aberto
  recortado: ícones, "Nova reserva", símbolo e avatar ficam no mesmo x
  (`--trilho-centro`) e na mesma altura nos dois estados; rótulos e títulos de grupo só
  esmaecem; a borda direita anda e recorta. O que muda de lugar (o Sair) desliza com
  os tokens de movimento; o botão de recolher é a exceção: do canto (menu aberto) ao
  centro do trilho, embaixo do símbolo, a reta seria uma diagonal, então ele some e
  surge no destino (`.menu-alternando`). No trilho o topo é uma coluna centrada:
  símbolo de 44 px, botão de expandir, fio. Regra do trilho só pode mexer em opacidade,
  cor, giro e posição — o contrato está nos testes de design. Os grupos do menu são
  categorias fixas (título + itens), nunca colapsáveis: colapsar grupo dentro de um
  menu que já recolhe é colapso dentro de colapso, e no trilho esconderia os ícones.
  Sem MFA, o avatar leva um ponto de alerta (`data-mfa="desligada"`), nunca
  cápsula. Abaixo de 820 px o menu é
  gaveta e abre sempre inteiro, como diálogo: foco preso, Esc e o véu fecham, a página
  não rola por baixo e o foco volta ao botão.
  A base do menu indica quando há mais opções abaixo; a indicação desaparece ao
  alcançar o fim e preserva a posição de rolagem entre telas.
- **Contrato responsivo:** conferir ausência de rolagem lateral entre 320 e 1440 px, com o menu aberto,
  recolhido ou em gaveta. A largura que sobra depende do menu, e o `@media` só enxerga a
  janela; por isso o que divide espaço decide pelo espaço: painel lateral em
  `flex-wrap` (`.colunas-2-1`), grades em `minmax(min(Npx, 100%), 1fr)`, e o corredor de
  quartos e a tabela de Pessoas por container query. Tabela larga rola dentro do próprio invólucro
  (`.tabela-rol`, criado pelo `static/js/tabela-rol.js`); o invólucro não pinta fundo e as
  células de canto herdam o raio da tabela (`--raio-celula`), sem quadrado branco no
  cantinho das caixas arredondadas. Alvo de toque ≥ 44 px no
  ponteiro grosso, inclusive no portal, no pagamento, no login e dentro dos modais.
  Controle pequeno que mora dentro de outra coisa (chip, célula, linha) segue a seção
  "Polimento mobile" do `app.css`: a caixa de toque cresce, o desenho fica onde está.
- **Modal no toque é gaveta de baixo:** encostada no pé da tela, com `.modal-acoes`
  presas embaixo e altura em `88dvh` (com `88vh` antes, para navegador antigo); o toast
  sobe para o topo para não cair nos botões dela. No mouse o modal segue centrado.
- **Nada fixo por cima do conteúdo:** o aviso de cookies reserva a própria altura no
  fim da página (`--aviso-cookies-altura`); com o menu do site aberto, aviso e botões
  flutuantes saem da frente; no celular, o WhatsApp só aparece depois da escolha dos
  cookies.
- **Portal do hóspede e página de pagamento:** carregam o `static/css/base.css`, um
  recorte do `app.css` com os componentes necessários às telas públicas.
  O recorte é GERADO: edite só o `app.css` e rode `python manage.py gerar_base_css`;
  a lista do que entra está em `apps/nucleo/css_publico.txt`, e o teste
  `CssDasTelasPublicasTests` avisa quando o recorte ficou para trás ou quando uma
  tela pública ganhou classe que falta nele.
- **Campos e cartões:** selects preservam a seta e o espaço à direita mesmo nos
  formulários especializados; cartões com `hidden` só aparecem quando há dados para
  mostrar. O recebimento de compras revela a prévia após escolher uma embalagem.
  Filtros ocupam a largura disponível e reservam espaço para datas completas.
  Abas conservam a largura do texto; seleção múltipla usa botões com estado próprio.
- **Site público:** Tailwind em build estático, com paleta própria e as mesmas cores
  de aviso do CRM. O CRM não usa Tailwind e o site não usa o `app.css`.

Regras para uma tela nova: estender `base.html`; telas de painel ou lista usam
`<div class="eleg">` com os componentes de `app.css`; colunas de número com
`.num` no `<th>` e no `<td>`; dinheiro com `|intcomma_brl`; mensagens por
`django.contrib.messages`; nada de `style="…"` com medida ou cor fixa (vira classe;
o atributo só fica quando o valor é dado, como uma largura em %). Campo de R$ usa o
`ReaisInput` do núcleo. Antes de dar a tela por pronta, abrir em 320, 390, 821 (com o
menu aberto) e 1440 px: nada pode sair do cartão, ser cortado sem reticências ou empurrar
a página de lado. Os testes de `apps/nucleo/tests_design.py` cobram essas regras.
Detalhes em [`docs/ARQUITETURA.md` §11](docs/ARQUITETURA.md).

---

## 12. Como desenvolver

### 12.1 Fluxo de trabalho com o fork

Este repositório é um **fork**. Desenvolvemos aqui; o original só recebe mudanças por
Pull Request revisado.

| Remoto | Repositório | Uso |
|---|---|---|
| `origin` | `VicZk/vo_testa` (fork) | onde fazemos push |
| `upstream` | `Geffersonvivan/vo_testa` (original) | só leitura; push desativado no clone |

| Branch | Papel |
|---|---|
| `main` | espelho do `upstream/main`; não commitar direto |
| `dev` | desenvolvimento do fork; é a branch padrão no GitHub |
| `feat/…`, `fix/…` | trabalho do dia a dia, sai de `dev` e volta por PR |

> O `main` do original publica em produção a cada push. Nada deste fork chega lá sem PR
> aprovado pelo dono do original.

```bash
# Trazer as novidades do original
git fetch upstream
git checkout main && git merge --ff-only upstream/main && git push origin main
git checkout dev && git merge main            # resolver conflitos e rodar os testes

# Trabalhar numa melhoria
git checkout -b fix/paginacao-pessoas dev
# ...código + testes...
git push -u origin fix/paginacao-pessoas
gh pr create --base dev --head fix/paginacao-pessoas

# Propor ao original, quando estiver maduro
gh pr create --repo Geffersonvivan/vo_testa --base main --head VicZk:dev
```

Proteção configurada no clone para não enviar nada ao original por engano:

```bash
git remote set-url --push upstream DISABLED--nao-fazer-push-no-original
```

**Para o Gefferson: levar algo daqui para o original.** Ele é colaborador deste fork e
pode trazer o que quiser, inteiro ou em partes. Os commits do `dev` tratam de um assunto
cada e explicam o que mudou, por quê e como foi testado, então dá para escolher commit a
commit:

```bash
# Uma vez, no clone do original
git remote add vic https://github.com/VicZk/vo_testa.git

# Ver o que o fork tem a mais que a main
git fetch vic
git log --oneline main..vic/dev

# Levar só alguns commits...
git cherry-pick <hash> [<hash>...]
# ...ou tudo de uma vez
git merge vic/dev
```

Também dá para abrir pelo GitHub um PR do `VicZk:dev` para o `main` do original e revisar
lá. Um commit que vale levar logo é o `ef3f309`: ele renomeia os arquivos de
`docs/SafraPay/` que têm `?` no nome, que impedem clonar o original no Windows.

### 12.2 Convenções

- **Domínio em português** (models, campos, services, templates, testes: `Reserva`,
  `UH`, `ModuloContratado`); infraestrutura em inglês quando for o padrão do Django.
- **Regra de negócio no `services.py`**, views finas. Um módulo só chama outro pelo
  `services.py` dele e degrada com `modulo_ativo()`.
- **Dinheiro:** `Decimal`, livros imutáveis, natureza fiscal obrigatória, `|intcomma_brl`.
- **Toda view do CRM** com `@requer_modulo`, `@requer_area` ou `@requer_gerencia`; ações
  sensíveis com `@requer_gerencia` e `registrar_auditoria(...)` com motivo.
- **Commits** no formato *Conventional Commits* em português: `feat(reservas): …`,
  `fix(caixa): …`, `docs: …`. PRs pequenos.
- **Testes** junto da mudança, sempre para dinheiro e disponibilidade.

### 12.3 Criar um módulo novo (resumo)

1. `python manage.py startapp meumodulo apps/meumodulo` e ajustar `apps.py`
   (`name = "apps.meumodulo"`, `label`, `ready()` se houver receivers).
2. Incluir em `INSTALLED_APPS` (`config/settings.py`).
3. Em `apps/nucleo/modulos.py`: novo código em `Modulo`, entrada em `APRESENTACAO`
   (grupo, ordem, descrição, rota) e, se houver, em `DEPENDENCIAS`.
4. `makemigrations` (gera também a mudança de choices em `nucleo`) e uma migration de
   dados que cria o `ModuloContratado` ativo.
5. `urls.py` com `app_name` igual ao código do módulo e `path("crm/meumodulo/", …)` em
   `config/urls.py`.
6. Views com `@requer_modulo(Modulo.MEUMODULO)`; regras no `services.py`; cobrança por
   `receber_no_caixa(..., modulo=…)` e/ou `reservas.services.lancar_na_conta`.
7. Ícone em `templates/componentes/icone_modulo.html` (o menu se monta sozinho).
8. Opcional: `pendencias_auditoria()` registrado em `apps/auditoria/services.py`,
   relatório em `apps/relatorios/services.py`, seed `popular_meumodulo`.
9. Templates no design system e `tests.py` ativando o módulo no `setUp`.

O passo a passo completo, com os arquivos exatos, está em
[`docs/ARQUITETURA.md` §12](docs/ARQUITETURA.md).

### 12.4 Antes de abrir um PR

- [ ] `python manage.py test` verde
- [ ] `python manage.py makemigrations --check --dry-run` sem mudanças pendentes
- [ ] `ruff check apps config` sem avisos novos
- [ ] Telas novas no design system, testadas em celular
- [ ] Variáveis novas documentadas no `.env.example` e na seção 8
- [ ] Nada de segredo, dado pessoal real ou arquivo com nome inválido no Windows

### 12.5 Trabalhando com IA

O projeto foi construído com o Claude Code. O `CLAUDE.md` é lido automaticamente por ele
e descreve convenções e o estado de cada módulo: mantenha-o atualizado quando algo mudar
junto do [Estado atual](docs/ESTADO_ATUAL.md). O [índice](docs/README.md) identifica
quais documentos são manuais atuais e quais preservam planos/evidências históricos.

---

## 13. Desenvolvendo no Windows

O projeto nasceu no macOS e funciona no Windows com alguns cuidados:

1. **venv fora do OneDrive**, com o Python 3.14 do `uv` (ver §2.2). Pastas sincronizadas
   tentam subir milhares de arquivos do ambiente e atrapalham.
2. **PostgreSQL em Docker**, numa porta livre (`55432` no exemplo). Se outro projeto já
   usa a 5432, troque só a porta do host.
3. **UTF-8 no terminal:** alguns comandos imprimem acentos e setas e quebram no console
   padrão. Antes de rodar: `$env:PYTHONUTF8 = "1"`.
4. **Nomes de arquivo:** o Windows proíbe `? : * " < > |`. Dois documentos com `?` no
   nome impediam o clone e foram renomeados neste fork; não adicione arquivos assim.
5. **Arquivos abertos em testes:** feche os handles antes de apagar temporários;
   o Windows pode impedir a remoção que o Linux permite. Um relato antigo de falha
   deve ser reproduzido no commit atual antes de ser tratado como problema aberto.

---

## 14. Glossário

| Termo | Significado |
|---|---|
| **UH** | Unidade habitacional, o quarto físico (`nucleo.UH`) |
| **TipoUH** | Categoria de quarto: Padrão, Intermediário, Cabana Intermediária, Cabana Hobbit, Dia na Pousada |
| **Ala** | Localização do quarto pelo número: Embaixo da Recepção (01–02), Corredor Engenhocas (03–09), Corredor Histórias (10–15), Condado dos Hobbits (16–24) |
| **Diária** | Preço de uma noite, definido pela precedência de tarifas do quarto, temporada e tipo |
| **Temporada** | Faixa do calendário com classificação (baixa, média, alta, super alta, feriado) e dias da semana |
| **Day use** | Uso no dia, sem pernoite, nas unidades `DAY-0N` |
| **Conta (folio)** | `ContaHospedagem` com lançamentos e pagamentos; o check-out exige saldo zero |
| **Natureza fiscal** | `SERVICO` (NFS-e/ISS) ou `CONSUMO` (NFC-e/ICMS) |
| **Pré-reserva** | Reserva que segura o quarto por tempo limitado até a confirmação |
| **Sinal / adiantamento** | Valor pago antes do check-in que confirma a reserva |
| **Antioverbooking** | Constraint do PostgreSQL que impede duas reservas ativas no mesmo quarto e período |
| **Sessão de caixa** | A gaveta de um operador em um módulo |
| **Conferência cega** | Fechamento de caixa em que o operador informa o contado sem ver o esperado |
| **Sangria / reforço** | Retirada / aporte de dinheiro no caixa |
| **Kardex** | Livro-razão do estoque (`MovimentoEstoque`) |
| **FNRH** | Ficha Nacional de Registro de Hóspedes, uma por hóspede |
| **BOH** | Boletim de Ocupação Hoteleira, agregado mensal das fichas |
| **Área-core** | Permissão do núcleo que não é módulo contratável |
| **Gateway plugável** | Integração externa escolhida por variável, com versão `simulado` |
| **Lampião** | O design system do CRM |
| **Vitrine** | Camada de marketing de cada quarto no site (`VitrineQuarto`) |
| **OS** | Ordem de serviço da Manutenção |

O glossário completo está em [`docs/ARQUITETURA.md` §13](docs/ARQUITETURA.md).

---

## 15. Documentação relacionada

| Documento | Conteúdo |
|---|---|
| [Índice completo](docs/README.md) | Todos os manuais, planos e registros históricos |
| [Estado atual](docs/ESTADO_ATUAL.md) | Base publicada, código local e limites de integrações |
| [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | Referência técnica completa da arquitetura |
| [`docs/MODULOS_E_FLUXOS.md`](docs/MODULOS_E_FLUXOS.md) | Cada módulo por dentro e os fluxos ponta a ponta |
| [`docs/ESPECIFICACAO.md`](docs/ESPECIFICACAO.md) | Especificação do produto (módulos, regras, fases) |
| [`docs/REFERENCIA_DESBRAVADOR.md`](docs/REFERENCIA_DESBRAVADOR.md) | Levantamento do Desbravador usado como referência de mercado |
| [`docs/Checklist_CRM_100.md`](docs/Checklist_CRM_100.md) | Checklist de ativação e operação, separado da implementação |
| `docs/Implementar_*.md` | Planos de FNRH, Safrapay, fiscal, WhatsApp e telefonia |
| `docs/Reservas/`, `docs/Descritivo_Quartos/`, `docs/Precificação/` | Configuração física dos quartos, descritivos e estudo de preços |
| `docs/Marketing/`, `docs/Comercial/`, `docs/WhatsAppAPI/` | Material comercial e de marketing |
| [`CLAUDE.md`](CLAUDE.md) | Convenções e estado atual para o Claude Code |
