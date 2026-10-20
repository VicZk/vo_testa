# Pousada Vô Testa — PMS, CRM e site

Sistema próprio de gestão da **Pousada Vô Testa** (Itá/SC): reservas, recepção, conta do
hóspede, caixa, pontos de venda, governança, lavanderia, manutenção, escala, FNRH,
financeiro, fiscal, comercial e o site público com motor de reservas. Um único projeto
**Django 6 + PostgreSQL**, com telas server-side (templates + HTMX + Alpine.js).

Este README é o mapa do sistema: o que ele é, como as peças se encaixam, como rodar e
como desenvolver em cima dele. Dois documentos aprofundam o que aqui está resumido:

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md): núcleo, modularidade, padrões,
  todas as variáveis de ambiente, rotas, deploy, design system e o passo a passo de
  um módulo novo, com referência a arquivo e linha.
- [`docs/MODULOS_E_FLUXOS.md`](docs/MODULOS_E_FLUXOS.md): cada módulo por dentro
  (models, estados, services, sinais, telas, regras) e os fluxos ponta a ponta com
  diagramas.

> A fonte de verdade do **produto** continua sendo [`docs/ESPECIFICACAO.md`](docs/ESPECIFICACAO.md).
> O [`CLAUDE.md`](CLAUDE.md) é a memória de trabalho usada pelo Claude Code
> (convenções e "estado atual"); parte dele está desatualizada (ex.: o módulo Frigobar,
> que já foi removido).

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

**Produção:** `www.pousadavotesta.com.br`, no Railway, com deploy automático a cada push
na `main` do repositório original (`Geffersonvivan/vo_testa`). Este repositório
(`VicZk/vo_testa`) é um **fork de desenvolvimento**: nada daqui vai para produção sem Pull
Request aprovado no original (ver [§12.1](#121-fluxo-de-trabalho-com-o-fork)).

### Estado dos módulos

| Módulo | Situação |
|---|---|
| Núcleo (pessoas, quartos, temporadas, caixa, financeiro, estoque, recados, dashboard) | Implementado; caixa homologado em 04/07/2026 |
| Reservas (mapa, ciclo, conta do hóspede, grupos, FNRH local, BOH, colchões extras) | Implementado |
| Loja, Restaurante, Lavanderia, Governança, Manutenção, Escala, Estoque | Implementados |
| Site + motor de reservas, Portal do hóspede | Implementados |
| Comercial (funil, WhatsApp, e-mail, landing pages) e Marketing (campanhas) | Implementados |
| Relatórios, Auditoria (pendências + trilha), Conciliação (OFX e cartão) | Implementados |
| Pagamentos online | Safrapay implementado, aguardando liberação de produção; Pix direto com baixa manual |
| FNRH Digital (envio ao governo) | Integração escrita; em modo `simulado` até haver credenciais |
| Fiscal (NFS-e/NFC-e) | Esqueleto com gateway `simulado`; provedores reais são stubs |
| NPS, CRM do Hóspede, Canais/OTAs | Proposta / não iniciados |

Todo integrador externo começa em modo **`simulado`** (sem rede), então o sistema roda de
ponta a ponta em desenvolvimento sem nenhuma credencial.

---

## 2. Começando: rodar localmente

### 2.1 Pré-requisitos

- **Python 3.14** (o projeto usa `target-version = py314`)
- **PostgreSQL 14+**. SQLite não serve: a trava contra overbooking usa
  `ExclusionConstraint` com a extensão `btree_gist`.
- **Docker** (o jeito mais simples de ter o Postgres) e **Git**

### 2.2 Ambiente

**macOS / Linux**

```bash
git clone https://github.com/VicZk/vo_testa.git && cd vo_testa
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt        # inclui requirements.txt

docker run -d --name vo_testa_pg -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=vo -e POSTGRES_PASSWORD=vo_local_dev -e POSTGRES_DB=crm_vo_testa \
  -v vo_testa_pgdata:/var/lib/postgresql/data postgres:16
```

**Windows (PowerShell)**: veja os cuidados em [§13](#13-desenvolvendo-no-windows).

```powershell
uv python install 3.14
uv venv --python 3.14 $HOME\.venvs\vo_testa          # venv fora do OneDrive
uv pip install --python $HOME\.venvs\vo_testa\Scripts\python.exe -r requirements-dev.txt

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
desses nomes de tipos e quartos.

**Dados de demonstração (opcional).** Os seeds não acompanharam todas as regras novas:

- `popular_lotacao` ocupa cerca de 80% dos quartos exercitando Reservas, Loja, Caixa e
  Governança. Rode com a trava da FNRH desligada (`FNRH_BLOQUEAR_CHECKIN=0` no ambiente),
  senão o check-in é recusado por falta de ficha.
- `popular_manutencao`, `popular_marketing`, `popular_comercial`,
  `popular_templates_email` e `popular_respostas_rapidas` funcionam direto.
- `popular_lavanderia` e `popular_demo` exigem caixas abertos do usuário (o caixa é por
  módulo, ver [§4.2](#42-o-núcleo)); `popular_demo` está desatualizado e pode falhar.
  `popular_escala` exige ao menos 6 funcionários cadastrados.

Os seeds usam o usuário `gvivan` se existir, senão o primeiro superusuário.

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
python manage.py test                    # suíte inteira (~880 testes, ~6 min)
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
| `lavanderia` | `lavanderia` | Serviço de lavanderia ao hóspede + rouparia (enxoval) |
| `governanca` | `governanca` | Situação de limpeza por quarto e fila de faxinas |
| `manutencao` | `manutencao` | Ordens de serviço, bloqueio e liberação de quarto |
| `escala` | `escala` | Turnos, grade semanal, ausências e trocas |
| `estoque` | `estoque` | Telas de gestão sobre o motor de estoque do núcleo |
| `comercial` | `comercial` | Funil de vendas, cotações, WhatsApp, e-mail, landing pages |
| `marketing` | `marketing` | Fluxo de campanhas (fases, peças, verba) sobre o comercial |
| `conciliacao` | — (área Financeiro) | Conciliação bancária (OFX) e de cartão (NSU) |
| `relatorios` | `relatorios` | Relatórios por período com exportação |
| `auditoria` | `auditoria` | Varredura de pendências + leitura da trilha de auditoria |
| `nps` | — (área NPS) | Proposta de NPS e API stub |

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
  recalculado sob trava de linha e saída que nunca deixa saldo negativo.

### 4.3 Modularidade e controle de acesso

- **Catálogo** (`apps/nucleo/modulos.py`): o enum `Modulo` (17 códigos), `DEPENDENCIAS`
  (ex.: Governança exige Reservas; Loja exige Estoque) e `APRESENTACAO` (grupo do menu,
  ordem, rota principal; módulo sem rota aparece como "em construção").
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
| `FNRH_GATEWAY` | `simulado`, `serpro` | Fluxo da API v2 escrito; falta credencial |
| `FISCAL_GATEWAY` | `simulado`, `focus`, `governo` | `focus` e `governo` são stubs |
| `WHATSAPP_GATEWAY` | `simulado`, `cloud`, `bsp` | Cloud API (Meta) pronta; `bsp` stub |
| `EMAIL_GATEWAY` | `simulado`, `ses` | `ses` stub |
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
trava de check-in, pré-check-in por QR e BOH mensal com exportação.

**Pagamentos.** `Cobranca` com token público, estados pendente → pago, estornado,
cancelado ou expirado, e trilha `EventoPagamento`. Confirmação idempotente com trava de
linha; sinal pago confirma a reserva. Link de pagamento público com Pix e cartão.

**Portal do hóspede.** Acesso por token ou QR durante a estadia: extrato, pedido ao
restaurante (lançado na conta), limpeza extra, manutenção, pré-check-in da FNRH e
check-out expresso. Ações registradas em nome do usuário de sistema `_portal`.

**Fiscal.** `DocumentoFiscal` e eventos; emissão a partir da conta separando serviço
(NFS-e) e consumo (NFC-e); parâmetros do contador em variáveis (código 090101, ISS 4%).

**Site (`core`).** Vitrine por quarto, busca de disponibilidade, seleção da unidade,
resumo com a política de cancelamento, pré-reserva com retenção de 30 minutos, cobrança
do sinal e e-mail de confirmação. Ainda carrega modelos do site antigo (recibo do canal).

**Loja e Restaurante.** PDV com carrinho e comandas por ponto de atendimento; cada item
baixa o estoque na hora e a cobrança vai para o caixa do setor ou para a conta do quarto.

**Lavanderia.** Ordens de serviço ao hóspede (recebida → lavando → pronta → entregue) e
rouparia interna como livro-razão de enxoval (limpa, em uso, suja, lavando).

**Governança.** Situação de cada quarto (suja, em limpeza, limpa, inspecionada) e fila
de faxinas geradas pelo check-out, pela manutenção ou pelo portal.

**Manutenção.** Ordens corretivas e preventivas (com recorrência), bloqueio do quarto
na disponibilidade e liberação com faxina automática.

**Escala.** Turnos por setor, grade semanal, ausências que impedem escalar, trocas
aprovadas pela gerência e "minha escala" para o funcionário.

**Estoque.** Telas sobre o motor do núcleo: posição com alerta de mínimo, entradas,
saídas, transferências, ajustes, kardex e inventário.

**Comercial.** Funil Kanban com ganho só por conversão em reserva, cotação pelo motor de
preços, sinal online, WhatsApp Cloud API dentro do card (janela de 24 h e template de
retomada), e-mail 1:1 e campanhas, landing pages e captura de leads com Meta CAPI.

**Marketing.** Gerência de campanhas com fases, peças com data, checklist, verba mensal
e calendário, embrulhando as campanhas do Comercial.

**Conciliação.** Importa extrato OFX e arquivo de cartão, casa por valor, data e NSU, e
fecha o mês.

**Relatórios e Auditoria.** Relatórios por mês (produção, ocupação, caixa, faturamento
por setor, consumo, funil) com CSV; painel de pendências que cada módulo alimenta e
leitura da trilha.

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
| `BACKUP_DIR` | pasta do `backup_banco` quando não há R2 (vazio e sem R2 = backup não roda) |

A lista completa, com padrões e efeitos, está em
[`docs/ARQUITETURA.md` §7](docs/ARQUITETURA.md). Durante os testes a flag `TESTING`
desliga a trava da FNRH, as taxas automáticas, o MFA e o limite de login.

---

## 9. Testes e qualidade

- **Onde:** dentro de cada app (`apps/<app>/tests.py` e `tests_*.py`), com `TestCase` do
  Django. Regras de dinheiro e de disponibilidade são sempre testadas.
- **Quantos:** cerca de 900 testes, com cerca de 74% de cobertura de instruções. Os mais densos:
  `comercial`, `nucleo`, `reservas`, `marketing`, `pagamentos`.
- **Navegador:** `apps/site/tests_e2e.py` usa Playwright e é pulado se ele não estiver
  instalado (`pip install playwright && playwright install chromium`).
- **Rodar:**

```bash
python manage.py test                                   # tudo
python manage.py test apps.reservas.tests_precos        # um arquivo
coverage run --source=apps manage.py test && coverage report   # cobertura
```

- **Lint e segurança:** `ruff check apps config`, `bandit -r apps config -ll`,
  `pip-audit -r requirements.txt` e `pre-commit install` para os hooks locais.
- **CI de testes** (`.github/workflows/testes.yml`): a cada push em `main` e `dev` e em
  todo PR, sobe um PostgreSQL 16, confere se as migrations estão em dia
  (`makemigrations --check`) e roda a suíte inteira. Ele existe neste fork; no original o
  push na `main` ainda publica sem esperar teste nenhum. Para fechar essa porta lá, basta
  levar o arquivo e fazer o Railway aguardar os checks do GitHub antes de publicar.
- **CI de segurança** (`.github/workflows/security.yml`): pip-audit, bandit, regras de
  segurança do ruff, semgrep (só relatório), `check --deploy` e gitleaks.

---

## 10. Deploy e operação

**Railway** (`railway.json`): build pelo Railpack; a cada deploy roda
`migrate`, `collectstatic` e sobe `gunicorn config.wsgi:application --workers 2`;
healthcheck em `/healthz/`, que confere o banco e responde 503 se ele não atender (um
container sem banco não substitui o que está no ar). O serviço está ligado ao GitHub e
publica a cada push na `main` do repositório original. Estáticos saem pelo WhiteNoise.

**Logs:** tudo vai para a saída padrão, que o Railway mostra nos logs do deploy: erros
500 com traceback (`django.request`) e falhas de receivers de sinais
(`apps.nucleo.sinais`). O nível geral vem de `LOG_LEVEL` (padrão `INFO`).

**Mídia:** com as cinco variáveis `R2_*`, uploads vão para o Cloudflare R2; rode
`python manage.py migrar_media_r2` uma vez para levar o que já está em disco. Sem R2, a
mídia fica no disco do container, que é apagado a cada deploy.

**Deploy:** as migrations rodam no `preDeployCommand` (uma vez por deploy, antes do
container novo entrar no ar; se falharem, o deploy é abortado) e o gunicorn sobe com 2
workers × 4 threads e timeout de 60 s.

**Rotinas agendadas.** `python manage.py rotinas --grupo frequentes|diarias` roda as
tarefas periódicas, cada uma isolada: uma falha vai para o log, não impede as outras e
faz o comando terminar com erro. No Railway, crie dois serviços de Cron a partir deste
repositório, com as mesmas variáveis do serviço web e o arquivo de configuração
`deploy/railway.rotinas.json` (a cada 10 min) ou `deploy/railway.rotinas-diarias.json`
(03h15 de Brasília).

| Grupo | Comando | O que faz |
|---|---|---|
| frequentes | `expirar_reservas` | cancela pré-reservas e grupos com retenção vencida |
| frequentes | `expirar_recibos_site` | marca como expirados os recibos do site não pagos |
| frequentes | `enviar_fnrh_pendentes` | reenvia à FNRH Digital as fichas pendentes ou com erro |
| frequentes | `enviar_campanhas_email` | dispara campanhas de e-mail agendadas |
| frequentes | `reenviar_confirmacoes_site` | manda a confirmação das reservas do site que ficaram sem e-mail |
| frequentes | `reprocessar_webhooks_whatsapp` | reprocessa mensagens do WhatsApp cujo processamento falhou (até 5 tentativas) e apaga as processadas há mais de 30 dias |
| frequentes | `reenviar_emails_pendentes` | reenvia e-mails do Comercial presos em "pendente" ou com erro (até 3 tentativas) |
| diarias | `enviar_conversoes_pendentes` | reenvia conversões de mídia pendentes |
| diarias | `sincronizar_gastos_midia` | puxa o gasto das plataformas de anúncio |
| diarias | `backup_banco` | cópia do banco para o R2 (ou `BACKUP_DIR`), apagando as de mais de 30 dias |

**Backup:** além dos backups do Railway (ligue o PITR do Postgres lá), `backup_banco`
guarda uma cópia fora dele todo dia: `pg_dump` quando disponível, senão JSON compactado
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
  global se faz nos tokens.
- **Componentes:** `.cartao`/`.cartao-el`, `.tabela`/`.quadro`, `.botao-primario`,
  `.botao-neutro`, `.botao-mini`, `.selo-*`, `.kpi`, combos de pessoa e quarto em
  `templates/componentes/`.
- **App shell** (`templates/base.html`): sidebar por permissão, navegação com
  `hx-boost`, paleta de comandos (⌘K ou `/`), toasts a partir das mensagens do Django,
  atalho `N` para nova reserva.
- **Site público:** Tailwind em build estático, com paleta própria. O CRM não usa
  Tailwind e o site não usa o `app.css`.

Regras para uma tela nova: estender `base.html`; telas de painel ou lista usam
`<div class="eleg">` com o kit `comercial/_estilo_elegante.html`; colunas de número com
`.num` no `<th>` e no `<td>`; dinheiro com `|intcomma_brl`; mensagens por
`django.contrib.messages`. Detalhes em [`docs/ARQUITETURA.md` §11](docs/ARQUITETURA.md).

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
(hoje ele ainda descreve o Frigobar, que foi removido). Este README e os dois documentos
em `docs/` servem para humanos e para a IA como mapa do código.

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
5. **Teste que falha só no Windows:**
   `comercial…test_webhook_audio_baixa_e_salva_arquivo` lê um arquivo sem fechá-lo antes
   de apagar a pasta temporária. No Linux passa.

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
| [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) | Referência técnica completa da arquitetura |
| [`docs/MODULOS_E_FLUXOS.md`](docs/MODULOS_E_FLUXOS.md) | Cada módulo por dentro e os fluxos ponta a ponta |
| [`docs/ESPECIFICACAO.md`](docs/ESPECIFICACAO.md) | Especificação do produto (módulos, regras, fases) |
| [`docs/REFERENCIA_DESBRAVADOR.md`](docs/REFERENCIA_DESBRAVADOR.md) | Levantamento do Desbravador usado como referência de mercado |
| [`docs/Checklist_CRM_100.md`](docs/Checklist_CRM_100.md) | Checklist de integrações e homologação para a inauguração |
| `docs/Implementar_*.md` | Planos de FNRH, Safrapay, fiscal, WhatsApp e telefonia |
| `docs/Reservas/`, `docs/Descritivo_Quartos/`, `docs/Precificação/` | Configuração física dos quartos, descritivos e estudo de preços |
| `docs/Marketing/`, `docs/Comercial/`, `docs/WhatsAppAPI/` | Material comercial e de marketing |
| [`CLAUDE.md`](CLAUDE.md) | Convenções e estado atual para o Claude Code |
