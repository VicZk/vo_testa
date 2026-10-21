# CRM/PMS Pousada Vô Testa — Arquitetura

> Referência técnica revisada em 21/10/2026, complementar ao [README](../README.md).
> A base publicada, as diferenças locais e os limites de homologação estão no
> [Estado atual](ESTADO_ATUAL.md). Caminhos são relativos à raiz do repositório;
> prefira nomes de funções/classes a números de linha. Índice: [docs](README.md).

---

## 1. Visão geral

Sistema único que atende dois públicos no mesmo processo Django, roteado por URL:

- **`/` — site público + motor de reservas** (hóspede final): vitrine dos quartos,
  fluxo de reserva em 5 passos, páginas legais, SEO (`robots.txt`, `llms.txt`,
  `sitemap.xml`).
- **`/crm/` — PMS/CRM da equipe**: reservas, recepção/caixa, governança,
  manutenção, lavanderia, loja, restaurante, escala, financeiro, fiscal, comercial,
  marketing, conciliação, relatórios e auditoria.
- **`/hospede/<token>/` — portal do hóspede** (sem login, por token opaco/QR).
- **`/lp/…` e `/captacao/…` — landing pages** de campanha, públicas.

A operação modelada é a da **Pousada Vô Testa** (Itá/SC): **24 quartos de pernoite**
(`Quarto 01`…`Quarto 24`, divididos em 4 alas — `apps/nucleo/alas.py`) mais as unidades
de **Dia na Pousada** (day use) `DAY-01`…`DAY-08`, das quais **apenas DAY-01..04 estão
ativas** (`apps/nucleo/migrations/0028_reduzir_day_use_para_4.py` inativou DAY-05..08).

**Decisão estratégica** (`docs/ESPECIFICACAO.md` §1): o sistema é construído como
**núcleo + módulos contratáveis**, para poder ser vendido depois a outras pousadas. A
Vô Testa é o cliente nº 1.

**Ambientes:** os registros do projeto associam a produção ao Railway e à `main`
do original. A configuração e a versão ativa não foram consultadas nesta revisão.
A fork de desenvolvimento é `VicZk/vo_testa`, branch `dev`; publicação de documentos
nela não comprova deploy. Consulte o [Estado atual](ESTADO_ATUAL.md) para separar
implementação, trabalho local e serviços externos.

### Stack

| Camada | Escolha | Onde está |
|---|---|---|
| Linguagem | Python **3.14** | `.python-version`, `ruff.toml` (`target-version = "py314"`) |
| Framework | **Django 6** (pin em requirements) | `requirements.txt` |
| Banco | **PostgreSQL** (obrigatório) | `django.contrib.postgres` em `INSTALLED_APPS`; `ExclusionConstraint` + extensão `btree_gist` (`apps/reservas/migrations/0001_initial.py`) |
| Driver | `psycopg` (pin em requirements) (+ `psycopg-binary`) | `requirements.txt` |
| Config de banco | `dj-database-url` **3.1.2** (`DATABASE_URL`) | `config/settings.py` |
| `.env` | `python-dotenv` (pin em requirements) | `config/settings.py` |
| Servidor | `gunicorn` (pin em requirements) | `railway.json` |
| Estáticos | `whitenoise` (manifesto com hashes em produção; storage comprimido em desenvolvimento) | `config/settings.py` |
| Mídia | `django-storages` **1.14.6** + `boto3` (pin em requirements) (Cloudflare R2, S3 API) | `config/settings.py` |
| Front do CRM | Templates Django + **HTMX 2.0.4** + **Alpine.js 3.14.8** (servidos de `static/vendor/`) — sem SPA | `templates/base.html` |
| Front do site | Templates Django + **Tailwind** (build estático) | `tailwind.config.js`, `apps/site/static/site/css/tailwind.css` |
| Gráficos | Chart.js via CDN, tematizado | dashboard / painéis |
| QR / imagem | `qrcode`, `Pillow` (pins em requirements) | portal, FNRH, MFA, Pix |
| MFA | `pyotp>=2.9.0` (TOTP) | `apps/nucleo/mfa.py` |
| Pins de segurança | `sqlparse>=0.6.0`, `urllib3>=2.8.0` | `requirements.txt` |

**Não instalados:** Django REST Framework e Celery. O cliente Redis está em
`requirements.txt`; o uso é opcional por `REDIS_URL`. A API NPS é um *stub*
(`/api/nps/v1/`) em views Django; há outras views públicas e webhooks próprios.
Rotinas agendadas são *management commands* (§10); e-mail 1:1 também pode usar thread
de fundo (`EMAIL_ENVIO_ASSINCRONO`). Os pins efetivos são os do requirements.

Ferramentas de desenvolvimento (`requirements-dev.txt`): `ruff==0.15.20`,
`pip-audit==2.10.1`, `pytest==9.1.1`, `bandit==1.9.4`, `detect-secrets==1.5.0`,
`semgrep` e `pre-commit` (sem pin).

---

## 2. Anatomia do repositório

```
.
├── apps/                  19 apps Django (ver tabela abaixo)
├── config/                projeto Django: settings.py, urls.py, wsgi.py, asgi.py
├── templates/             templates do CRM (base.html + 1 pasta por app) + componentes/
├── static/                estáticos do CRM: css/app.css (+ base.css gerado), js/fluid.js, img/, fonts/, lp/, comercial/
├── docs/                  especificação, planos de implementação, mockups, estudos
├── LPs/                   HTML “oficial” das landing pages (fonte da verdade, servido direto)
├── Logo/                  fontes e artes da marca (.ai, .woff, .png) — não usados em runtime
├── media/                 uploads: galeria/, quartos/, marketing/checklist/, whatsapp/midia/
├── evidencias/            pacote de evidências Safrapay (safrapay/)
├── manage.py
├── railway.json           build/start/healthcheck do deploy
├── requirements.txt / requirements-dev.txt
├── ruff.toml / .pre-commit-config.yaml / .secrets.baseline
├── tailwind.config.js / tailwind.src.css
├── .env.example           modelo de variáveis de ambiente
├── CLAUDE.md              memória de produto/arquitetura (fonte de “estado atual”)
├── ROTEIRO.md / ROTEIRO-MARKETING.md
└── .github/               workflows/testes.yml + security.yml + dependabot.yml
```

### Apps (`apps/`) — 19, todos em `INSTALLED_APPS`

| App | Label | Módulo contratável | Papel em uma linha |
|---|---|---|---|
| `nucleo` | `nucleo` | — (núcleo) | Usuário, pessoas, estrutura física, temporadas, caixa/financeiro, motor de estoque, logbook, dashboard, busca global, auditoria automática, catálogo de módulos e áreas. |
| `reservas` | `reservas` | `reservas` | Ciclo da reserva, antioverbooking, mapa de quartos, folio/conta, tarifas, FNRH/BOH, grupos, colchões/berços. |
| `estoque` | `estoque` | `estoque` | Telas de gestão do motor de estoque do núcleo (posição, produtos, entradas/saídas, kardex, inventário). |
| `loja` | `loja` | `loja` | PDV de balcão: venda com baixa de estoque e cobrança no caixa ou na conta do quarto. |
| `restaurante` | `restaurante` | `restaurante` | Comandas por ponto de atendimento (mesa/guarda-sol/bar), consumo e fechamento. |
| `lavanderia` | `lavanderia` | `lavanderia` | Serviço ao hóspede (ordens de lavanderia) + rouparia interna (livro-razão de enxoval). |
| `governanca` | `governanca` | `governanca` | Status de limpeza por quarto e fila de faxinas/arrumações. |
| `manutencao` | `manutencao` | `manutencao` | Ordens de serviço corretivas/preventivas, bloqueio e liberação de quarto. |
| `escala` | `escala` | `escala` | Turnos, atribuições, ausências, horas extras, trocas, grade semanal e publicação. |
| `pagamentos` | `pagamentos` | `pagamentos` | Cobranças online (Pix/cartão/boleto/link), webhook, conciliação de cartão, gateway plugável. |
| `fiscal` | `fiscal` | `fiscal` | Documentos fiscais (NFS-e/NFC-e/NF-e) com gateway plugável; emissão a partir do folio. |
| `portal` | `portal` | `appsite` | Portal do hóspede por token (conta, pedidos, limpeza, manutenção, check-out expresso, pré check-in FNRH). |
| `site` | **`core`** | — (serve `/`) | Site público: vitrine, fluxo de reserva, páginas legais, sitemap, e-mails transacionais. |
| `comercial` | `comercial` | `comercial` | Funil/Kanban de leads, cotações, atividades, WhatsApp, e-mail de funil, landing pages, impulsionamento. |
| `marketing` | `marketing` | `marketing` | Camada de fluxo das campanhas (fases, verba mensal, peças com data, checklists) sobre `comercial.Campanha`. |
| `conciliacao` | `conciliacao` | — (área Financeiro) | Conciliação bancária (OFX) e de cartão (NSU/SafraPay), manual e automática. |
| `relatorios` | `relatorios` | `relatorios` | Catálogo de relatórios por período com export CSV/print. |
| `auditoria` | `auditoria` | `auditoria` | Read-only: varredura de pendências do CRM + leitura/filtro/export da trilha de auditoria. |
| `nps` | `nps` | — (área NPS) | Esqueleto/proposta de NPS + API stub HTTP 501. |

Observações importantes:

- `apps/site` tem **label `core`** (`apps/site/apps.py`) — as tabelas são `core_*` e as
  migrações do site antigo foram reaproveitadas.
- `conciliacao`, `nps` e `site` **não** são módulos contratáveis: não existem no enum
  `Modulo`. `conciliacao` é protegida por `@requer_area(Area.FINANCEIRO)` e `nps` por
  `@requer_area(Area.NPS)`.
- O app `frigobar`, documentado em `CLAUDE.md`, **não existe mais**: a migração
  `nucleo/0036_remover_modulo_frigobar.py` tira o código das choices, apaga o
  `ModuloContratado` e dropa as tabelas `frigobar_*`.

### `templates/`

`templates/base.html` é o app-shell do CRM (§11). Há uma pasta por app
(`nucleo/`, `reservas/`, `comercial/`, `marketing/`, `escala/`, `estoque/`, `loja/`,
`restaurante/`, `lavanderia/`, `governanca/`, `manutencao/`, `pagamentos/`, `fiscal/`,
`auditoria/`, `relatorios/`, `conciliacao/`, `portal/`, `nps/`), mais:

- `templates/componentes/` — includes reusáveis: `combo_pessoa.html` (combobox de
  pessoa com busca e agrupamento por papel), `combo_quarto.html` (combobox de quarto
  com seções por ala e recarga via `fetch` quando as datas mudam),
  `icone_modulo.html` (ícone SVG por código de módulo, usado na sidebar) e
  `paginacao.html` (anterior · página X de Y · próxima, com busca e filtros mantidos).
- `templates/registration/` — `login.html` e `mfa_desafio.html`.
- `templates/lp/privacidade.html` — política de privacidade pública.

Os templates do **site público** não ficam aqui: vivem em `apps/site/templates/site/`
(`home.html`, `quartos_todos.html`, `quarto_detalhe.html`, `reservas/`, `sections/`,
`partials/`, `legal/`, `emails/`, `lab.html`), com `base.html` próprio.

### `static/`

`static/css/app.css` (≈4.800 linhas) é o **único** CSS do CRM — tokens + componentes +
telas (§11). O portal do hóspede e a página de pagamento carregam `static/css/base.css`:
o recorte do app.css que elas usam (24 KB; 6 KB comprimido, contra 52 KB do app.css),
GERADO por `manage.py gerar_base_css` a partir do manifesto `apps/nucleo/css_publico.txt`.
Não se edita o base.css: muda-se o app.css e roda-se o comando (o teste
`CssDasTelasPublicasTests` falha enquanto o recorte estiver para trás). Também:
`static/js/dicas.js` (o balão único de todo `[data-dica]` do CRM),
`static/js/tabela-rol.js`, `static/js/form-pt.js`, `static/js/fluid.js`, `static/img/` (logotipos e símbolo,
`wpp-doodles.svg`), `static/fonts/Rosaline-Regular.woff2?` (fonte da marca),
`static/lp/` e `static/comercial/`. Os estáticos do site ficam em
`apps/site/static/site/` (`css/tailwind.css`, `js/`, `img/`, `fonts/`, `vendor/`,
`prototipos/`).

### `LPs/`

HTML bespoke das campanhas, **servido direto do disco** (fonte da verdade, não é
template):

- `LPs/LP_Fundador/LP_Fundador.html` (+ `Fotos/`, mockups)
- `LPs/LP_Fundador_II_13_09_2026/LP_Fundador_II_13_09_2026.html` (+ `Fotos/`)
- `LPs/LP_Inauguração_31_10_2026/LP-Inauguracao-VoTesta.html`

`apps/comercial/views_lp.py` lê o arquivo e injeta o que precisa; os formulários
postam JSON no CRM e caem no funil (`capturar_lead_site`).

### `docs/` (agrupado por tema)

| Tema | Arquivos |
|---|---|
| Fonte da verdade do produto | `ESPECIFICACAO.md` (+ `.docx`), `REFERENCIA_DESBRAVADOR.md`, `apresentacao_easy_web.pdf` |
| Checklists e auditorias | `Checklist_CRM_100.md`/`.pdf`, `Auditoria_CRM.md`, `Auditoria_Layout_CRM.md`, `Auditoria_Seguranca_CRM.md`, `pagamentos-fnrh-threat-model.md` |
| Planos de implementação | `Implementar_FNRH_API.md`, `Implementar_Safrapay.md`, `Implementar_fiscal.md`, `Implementar_WhatsApp_Meta.md`, `Implementar_Telefonia_Vendas.md`, `IMPLEMENTAR_Ideias.md` |
| Comercial | `Plano_Comercial.md`, `Comercial/Manual_Vendedora.md`, `Comercial/Religar_Funil_Fase6.md` |
| Marketing | `Marketing/` — `CRM_WhatsApp.md`, `Gestor_Impulsionamento_CRM.md`, `Gestor_LPs.md`, `Gestor_Email_MKT_Massa.md`, `Gestor_email_leads_funil.md`, `Plano_Marketing_Inauguracao.md`, `Calendario_Editorial_Inauguracao.md`, mockups HTML |
| WhatsApp (API) | `WhatsAppAPI/Plano_Audio_WhatsApp.md`, `WhatsAppAPI/Plano_Campanhas_e_Optin_WhatsApp.md`, `Evidencia_WhatsApp_141008.md`/`.png` |
| Pagamentos | `SafraPay/DECISAO.md`, `SafraPay/Homologação_Máquina_Cartão/` |
| Reservas / estrutura física | `Reservas/CONFIGURACAO_QUARTOS.md`, `Reservas/PLANO_ESTOQUE_COLCHOES.md`, `Descritivo_Quartos/` (descritivo + `Parametros_CRM.md` + Manual de Vendas) |
| Preço | `Precificação/` (`precificação.md`, `Estudo_Precificacao_Vo_Testa.pdf`, comissão), `Tarifario.pdf` |
| Fiscal/contábil | `Checklist_contador.md`, `Produtos_para_NCM.md` |
| Relacionamento | `Proposta_NPS.md`, `PLANEJAMENTO_EMAIL.md` |
| Outros | `Estrutura_NAS.md`, `JEV_CRM_TEST.md`, `Projeto_Pousada/` (plantas e fotos), `mock_ups/`, `mockups/operacao-lampiao.html`, mockups de tela na raiz de `docs/` |

### `media/`

Uploads servidos em `/media/` (ou pelo R2, quando configurado): `galeria/`,
`quartos/`, `marketing/checklist/`, `whatsapp/midia/`.

### `config/`

- `settings.py` — tudo por variável de ambiente (§7); define a flag `TESTING`
  (`"test" in sys.argv`) usada para desligar travas nos testes.
- `urls.py` — roteamento único do projeto (§6).
- `wsgi.py` / `asgi.py` — pontos de entrada (gunicorn usa `config.wsgi:application`).

---

## 3. Arquitetura do núcleo (`apps/nucleo`)

O núcleo é **o que não é módulo contratável**: as fontes de verdade (dinheiro,
estoque, estrutura física, pessoas) e a infraestrutura transversal.

### 3.1 O pacote de models

`apps/nucleo/models/` é um **pacote**, um arquivo por domínio, com `__init__.py`
reexportando tudo (`__all__`, `apps/nucleo/models/__init__.py`) — o resto do sistema
importa sempre de `apps.nucleo.models`.

| Arquivo | Models | Funções públicas exportadas |
|---|---|---|
| `usuarios.py` | `Usuario` (AbstractUser), `ModuloContratado` | `modulo_ativo()`, `modulos_ativos()` |
| `cadastros.py` | `Pessoa`, `Hospede`, `Prospecto`, `Funcionario`, `Fornecedor`, `Agencia`, `TipoUH`, `UH`, `PosicaoCama`, `ConfiguracaoUH`, `Temporada`, `ConfiguracaoReservas` | — |
| `financeiro.py` | `FormaPagamento`, `SessaoCaixa`, `MovimentoCaixa`, `CategoriaFinanceira`, `LancamentoFinanceiro`, `ContaPagarReceber`, `TrilhaAuditoria` + enum `NaturezaFiscal` | `centro_choices()`, `receber_no_caixa()`, `estornar_movimento()`, `registrar_auditoria()` |
| `estoque.py` | `CategoriaProduto`, `Produto`, `LocalEstoque`, `MovimentoEstoque`, `Inventario`, `ItemInventario` | `saldo()`, `posicao_estoque()`, `produtos_abaixo_minimo()`, `registrar_entrada()`, `registrar_saida()`, `transferir()`, `ajustar()` |
| `logbook.py` | `EntradaLogbook`, `ComentarioLogbook` | — |

### 3.2 Cadastros: Pessoa + papéis

`Pessoa` é a **base única** (nome, tipo PF/PJ, documento, contato, endereço, consentimentos
LGPD de e-mail e WhatsApp independentes, `unsub_token` para o link de descadastro).
Os papéis são especializações `OneToOne`:

- `Hospede` (nascimento, nacionalidade, preferências)
- `Prospecto` (lead do funil; ao ganhar, o Comercial cria o papel Hóspede)
- `Funcionario` (cargo, setor, vínculo, jornada, `salario` **sensível**, parâmetros de
  escala — sexo, regime de horas, compensação de feriado — e `usuario` → login do CRM)
- `Fornecedor` (ramo de atividade)
- `Agencia` (categoria agência|empresa, comissão padrão)

“Cliente avulso” = `Pessoa` sem especialização. `Pessoa.papeis`
(`apps/nucleo/models/cadastros.py`) devolve os papéis ativos para exibição.

### 3.3 Estrutura física: TipoUH / UH / temporadas / feriados

- **`TipoUH`** — categoria de quarto: capacidade, `tarifa_base`, `modalidade`
  (`hospedagem` | `day_use`), `pessoa_adicional`, `preco_day_use`.
- **`UH`** — o quarto físico: `numero` único, `nome_tematico` (vitrine), tipo, bloco/ala,
  andar, `status` operacional (`ativa` | `bloqueada` | `inativa`), PCD, qualidades
  (vista para o lago, varanda, aceita pet, ar-condicionado, tipo de cama, layout,
  diferenciais, banheiro, área externa, acessibilidade) e `tarifa_override`.
  A propriedade `UH.ala` deriva a ala oficial do número via `apps/nucleo/alas.py`
  (Embaixo da Recepção 01–02, Corredor Engenhocas 03–09, Corredor Histórias 10–15,
  Condado dos Hobbits 16–24) e devolve `""` para day use.
- **`PosicaoCama`** — espaço físico de cama (1 posição = 2 pessoas, montagem casal ou
  dois solteiros). **A montagem não altera a lotação.**
- **`ConfiguracaoUH`** — sofá-cama (adultos/crianças/idade máxima), máximo de colchões
  extras e tarifa do colchão.
- **`apps/nucleo/estrutura.py`** é a **fonte única derivada**: `capacidade(uh)`,
  `descricao_camas(uh)` (frase gerada, nunca digitada), `eh_duplo(uh)`, `casais_max`,
  `camas_solteiro`, `extras_para(uh, pessoas)`, `faixa_do_tipo(tipo)`. Use
  `capacidade(uh)["maxima_criancas"]` para disponibilidade.
- **`Temporada`** — nome, `classificacao` (baixa/média/alta/super alta/feriado),
  `dias_semana` (JSON; vazio = todos os dias) e intervalo. `vale_no_dia(dia)` decide se
  a temporada se aplica àquela noite.
- **`ConfiguracaoReservas`** — singleton (`pk=1`) com `feriados_automaticos`.
- **`apps/nucleo/feriados.py`** — calendário computado por ano, **sem banco**:
  nacionais fixos + aniversário de Itá (13/12) + móveis derivados da Páscoa
  (Sexta-feira Santa, Carnaval, Corpus Christi). `eh_feriado(dia)` devolve o nome.

### 3.4 Financeiro e motor de caixa

Regras que não se quebram (`apps/nucleo/models/financeiro.py`):

1. **Dinheiro é `DecimalField`**, nunca float.
2. **`MovimentoCaixa` é imutável** — `save()` levanta `ValidationError` se não for
   criação; `delete()` sempre levanta. Correção = movimento inverso.
3. **Estorno exige motivo + movimento original** e é sempre auditado.
4. **Uma sessão aberta por operador × módulo**, garantida por
   `UniqueConstraint(fields=["operador","modulo"], condition=Q(status="aberta"))`.

**`SessaoCaixa`** = a gaveta física de um operador em um módulo (`modulo` é um código de
`centro_choices()` = `nucleo` + todos os módulos). Abre com `fundo_troco`;
`esperado_em_dinheiro()` = fundo + recebimentos em dinheiro + reforços − sangrias −
estornos em dinheiro; `totais_por_forma()` dá o líquido por forma de pagamento.

- **Conferência cega**: `fechar(valor_contado, usuario, observacoes)` grava o contado,
  calcula `diferenca = contado − esperado` e audita (`acao="fechamento_caixa"`). O
  operador informa o contado **sem ver o esperado**.
- **Reabertura**: `reabrir(usuario, motivo)` exige motivo, recusa se já há outra sessão
  aberta do mesmo operador/módulo, e audita (`acao="reabertura_caixa"`). A permissão de
  gerência é verificada na view (`@requer_gerencia` em `caixa_reabrir`).

**`MovimentoCaixa`** — tipos `recebimento`, `reforco`, `sangria`, `estorno`; forma de
pagamento obrigatória em recebimento/estorno; `autorizacao` (NSU) para conciliar com a
maquininha; `CheckConstraint(valor > 0)`. `clean()` valida: sessão aberta, estorno só
sobre recebimento, estorno não excede o saldo restante do recebimento original,
sangria não passa do dinheiro em caixa, parcelas só em forma que permite.

**Interface pública para os módulos:**

```python
receber_no_caixa(usuario, forma, valor, descricao, parcelas=1, modulo=CENTRO_NUCLEO, autorizacao="")
```

Acha a sessão aberta **daquele** operador **naquele** módulo e cria o recebimento. Se
não houver, levanta `ValidationError` nomeando o caixa a abrir. Quem chama:
Loja → `Modulo.LOJA`, Restaurante → `Modulo.RESTAURANTE`,
Lavanderia → `Modulo.LAVANDERIA`, Reservas → `Modulo.RESERVAS`
(via `reservas.services._receber_no_caixa`).

```python
estornar_movimento(origem, sessao, usuario, motivo, valor=None)  # @transaction.atomic
```

Trava a linha de origem (`apps.nucleo.sistema.travar` → `SELECT … FOR UPDATE`) para
serializar estornos parciais concorrentes, cria o movimento inverso e audita. Antes de
auditar, chama as funções registradas com `ao_estornar(funcao)`: é como um módulo que
guarda um espelho do recebimento desfaz o espelho na mesma transação sem o núcleo
conhecê-lo (Reservas registra `desfazer_credito_do_estorno` no `ready()`; se a função
levanta `ValidationError`, nada é estornado).

**Classificação e títulos:** `CategoriaFinanceira` (receita|despesa),
`LancamentoFinanceiro` (tipo + categoria + `centro` = módulo + data de competência),
`ContaPagarReceber` (`baixar()` gera o lançamento correspondente e audita
`baixa_conta`; `vencida` é derivada).

### 3.5 Motor de estoque

`apps/nucleo/models/estoque.py` — **fonte de verdade única do estoque**. Loja,
Restaurante e Lavanderia **só** entram/baixam por estas funções.

- `Produto` — natureza fiscal obrigatória (default `CONSUMO`), `custo_medio`
  (4 decimais, calculado pelo sistema), `preco_venda`, `estoque_minimo`, `margem`.
- `LocalEstoque` — depósito, vinculado a um `modulo` (almoxarifado central = `nucleo`).
- `MovimentoEstoque` — **kardex imutável**; `quantidade` é **sinalizada** (positiva
  entra, negativa sai); saldo = soma. `save()`/`delete()` barram alteração/remoção.
  `fornecedor` (FK Pessoa, opcional) na entrada por compra; `chave` (UUID único,
  opcional) é a chave de envio do formulário — ver idempotência abaixo.
- `Inventario` / `ItemInventario` — `aplicar(usuario, somente_contados=False)` gera um
  ajuste por item com diferença e audita `inventario_aplicado`. A tela de contagem passa
  `somente_contados=True`: o item com `contado=False` (ninguém conferiu) não vira ajuste —
  senão uma venda feita durante a contagem era apagada pelo saldo da abertura.

**Serviços públicos** (`saldo`, `posicao_estoque`, `produtos_abaixo_minimo`,
`registrar_entrada`, `registrar_saida`, `transferir`, `ajustar`):

- `registrar_entrada` trava a linha do produto e recalcula o **custo médio ponderado**
  (read-modify-write serializado).
- `registrar_saida` trava a mesma âncora (a linha do produto) e **recusa deixar saldo
  negativo** no local.
- `transferir` grava os dois lados (movimentos ligados por `transferencia_par`) e audita
  `transferencia_estoque`.
- `ajustar` leva o saldo do local a um valor e audita `ajuste_estoque` (no-op se a
  diferença for zero).
- **Idempotência:** `registrar_entrada`, `registrar_saida` e `transferir` aceitam
  `chave=`. Com uma chave já gravada, devolvem o movimento existente
  (`movimento_da_chave`); numa corrida, a unicidade da chave estoura dentro do atomic (o
  custo médio volta junto) e o motor devolve o que o primeiro envio gravou. Na
  transferência a chave fica na perna de saída. Quem chama sem chave (Loja, Restaurante,
  Lavanderia) não muda.
- **Leitura para as telas** (não escrevem nada): `saldos_por_local` (uma consulta, de um
  produto ou do catálogo), `resumo_locais` (itens, valor e alertas por depósito) e
  `indicadores_estoque` (totais a partir das linhas da posição).

### 3.6 Logbook (recados do turno)

`EntradaLogbook` é um tópico com conversa (`ComentarioLogbook`) e ciclo
aberta → em andamento → resolvida. `apps/nucleo/logbook_services.py` é a interface:
`registrar_ocorrencia`, `comentar` (move para “em andamento” quando quem responde não é
o autor), `resolver` (audita `resolver_ocorrencia`), `reabrir`.

### 3.7 Dashboard, busca global e demais utilitários do núcleo

- **Dashboard** (`apps/nucleo/views.py`) — monta **tudo conforme o acesso**:
  cards de módulos (só os ativos que o usuário tem), KPIs e bloco “Precisa de atenção”
  por área (`tem_financeiro`, `tem_reservas`, `tem_estoque`, `tem_logbook`) e
  **gráficos de decisão só para gerência** (`tem_graficos = eh_gerente(user)`).
- **Busca global** (`views.py:455`, rota `busca_global`) — alimenta a paleta ⌘K; busca
  `Pessoa` sempre e, condicionada a `pode_acessar`, `Reserva` (Reservas), `Produto`
  (Estoque) e `Oportunidade` (Comercial). Mínimo de 2 caracteres, 5 resultados por tipo,
  devolve JSON.
- **`seletores.py`** — `pessoas_agrupadas(queryset=None)` classifica pessoas em
  Hóspedes → Prospecção → Clientes avulsos → Agências e empresas → Funcionários →
  Fornecedores, para o `combo_pessoa.html` via `json_script`.
- **`periodos.py`** — seletor mês/ano compartilhado: `periodo(request)` devolve
  `(inicio, fim, rotulo)` (padrão = mês corrente; `de`+`ate` sobrepõem) e
  `selecao_periodo(request)` monta as opções. Usado por Relatórios e pela Trilha.
- **`historico.py`** — histórico do funcionário montado **só de leitura** sobre a
  trilha (progressão salarial, movimentações de cargo/setor, presença por login/logout)
  e do cálculo de tempo de casa. Sem model novo.
- **`export.py`** — `resposta_csv(filename)` (delimitador `;` + BOM utf-8-sig para o
  Excel pt-BR) e `sanitizar_celula(v)` (neutraliza `=`, `+`, `-`, `@`, tab, CR).
- **`sistema.py`** — `usuario_de_sistema(username, nome)` (conta robô, senha
  inutilizável, idempotente) e `travar(obj)` (`SELECT … FOR UPDATE` + `refresh_from_db`).
- **`validadores.py`** — `validar_telefone_br` com tabela de DDDs válidos; exige celular
  por padrão, aceita fixo com `aceitar_fixo=True`, e normaliza a formatação.
- **`alas.py`**, **`estrutura.py`**, **`feriados.py`** — descritos acima.

**Context processors** (registrados em `config/settings.py`):

| Context processor | Entrega |
|---|---|
| `nucleo.context_processors.menu_modulos` | `menu_modulos` (grupos → itens com URL resolvida) e `eh_gerente` |
| `comercial.context_processors.whatsapp_nao_lidas` | `wpp_nao_lidas_total` (badge da sidebar; só com módulo ativo e acesso) |
| `site.context_processors.reserva_passos` | `reserva_passos` (stepper 1 Datas → 5 Confirmação) |
| `site.context_processors.prova_social` | `prova_social` (última reserva real, só o primeiro nome) |
| `site.context_processors.analytics` | `ga_measurement_id` |

**Templatetags**:

- `nucleo/templatetags/nucleo_extras.py` — `|modulo_ativo`, `user|pode_area:'x'`,
  `user|pode_modulo:'x'`, `uh|camas_uh`, `uh|lotacao_uh`.
- `nucleo/templatetags/moeda.py` — `|intcomma_brl` (**único** formatador de dinheiro do
  sistema: `1600 → "R$ 1.600,00"`, negativo com sinal fora, inválido → `"R$ 0,00"`).
- `auditoria/templatetags/auditoria_extras.py` — `|frase_auditoria` (JSON cru → frase).

---

## 4. Modularidade

### 4.1 `apps/nucleo/modulos.py` — o catálogo

```python
class Modulo(models.TextChoices):   # 17 códigos
    RESERVAS, GOVERNANCA, MANUTENCAO, ESCALA, ESTOQUE, LOJA, RESTAURANTE,
    LAVANDERIA, PAGAMENTOS, APPSITE, CRM_HOSPEDE, CANAIS, FISCAL, AUDITORIA,
    RELATORIOS, COMERCIAL, MARKETING
```

- **`DEPENDENCIAS: dict[str, list[str]]`** — módulo → módulos exigidos:
  Governança→Reservas · Manutenção→Reservas · Loja→Estoque · Restaurante→Estoque ·
  Lavanderia→Estoque · APP/Site→Reservas+Pagamentos · CRM do Hóspede→Reservas ·
  Canais→Reservas.
- **`APRESENTACAO`** — por módulo: `grupo` do menu (Hospedagem, Vendas & Estoque,
  Financeiro, Equipe, Comercial, Online, Gestão), `ordem`, `descricao` curta e
  `url_name` opcional. **Sem `url_name` = módulo sem tela**: o menu e o card do
  dashboard ficam sem link (“em construção”). Hoje `CRM_HOSPEDE` e `CANAIS` não têm.

### 4.2 `ModuloContratado` e `modulo_ativo()`

`ModuloContratado` (`codigo` único, `ativo`, `ativado_em`, `desativado_em`,
`parametros` JSON) é a **ativação por cliente**. `clean()` recusa ativar um módulo cujas
dependências não estejam ativas.

`modulo_ativo(codigo)` é a **consulta central**; `modulos_ativos()` devolve os códigos
ativos ordenados pelo catálogo. **Nunca hard-code um módulo** — menu, permissão,
integração e degradação graciosa passam por aqui.

Dentro de uma requisição, o `ModulosPorRequisicaoMiddleware` (`apps/nucleo/middleware.py`)
liga uma memória: os módulos ativos são lidos do banco **uma vez** e as demais perguntas
(menu, `@requer_modulo`, `|pode_modulo`, services) vêm dela. Salvar ou apagar um
`ModuloContratado` limpa a memória (receiver ligado no `NucleoConfig.ready`). Fora de
requisição (rotinas, shell), cada chamada consulta o banco, como antes.

Ativação inicial por migração *seed*:

| Migração | O que ativa |
|---|---|
| `nucleo/0002_seed_modulos_fase1.py` | 11 códigos da fase 1 (inclui o extinto `frigobar`) |
| `auditoria/0001_ativar_modulo.py` | `auditoria` |
| `relatorios/0001_ativar_modulo.py` | `relatorios` |
| `comercial/0002_seed_e_ativar.py` | `comercial` (+ seed do funil) |
| `marketing/0002_seed_e_ativar.py` | `marketing` (+ `VerbaMarketing` singleton) |
| `nucleo/0029` e `nucleo/0036` | desativam e depois **removem** `frigobar` |

### 4.3 Central de Módulos

`/crm/configuracoes/modulos/` → `nucleo.views.modulos_central` (`@requer_gerencia`).
Mostra o catálogo inteiro agrupado, com status derivado:

- **funcionando** = ativo **e** com `url_name` que resolve;
- **construção** = ativo **sem** tela;
- **disponível** = inativo.

Cada card lista as `DEPENDENCIAS` e `bloqueia_desativar` (**dependentes reversos** que
estão ativos). O POST (`_alternar_modulo`) ativa rodando `full_clean()` (respeita as
dependências) ou desativa. Item “Configurações → Módulos” aparece na sidebar só para
`is_staff`/`is_superuser`.

### 4.4 `apps/nucleo/areas.py` — áreas-core

O que **não** é módulo contratável, mas precisa de controle por usuário. 11 códigos em
`Area` (TextChoices), concedidos em `Usuario.areas` (JSONField, lista de strings):

| Código | Rótulo | Observação |
|---|---|---|
| `quartos` | Quartos & tipos | `@requer_area` em 4 views |
| `temporadas` | Temporadas & tarifas | 2 views |
| `caixa` | Caixa próprio (abrir/receber/fechar) | sempre junto com `financeiro` nas telas de caixa |
| `financeiro` | Financeiro (contas/gestão) | área mais usada (17 views, incl. Conciliação) |
| `pessoas` | Pessoas | 6 views |
| `funcionarios` | Funcionários (RH) | 4 views, sempre `(Area.FUNCIONARIOS, Area.EQUIPE)` |
| `remuneracao` | Remuneração (ver salários) | **não** usada em `@requer_area`; checada por `pode_ver_salario()` |
| `logbook` | Recados do turno | 3 views |
| `nps` | NPS | 1 view |
| `marketing` | Marketing (analista) | declarada no catálogo, **sem uso no código** hoje |
| `equipe` | Equipe & Acessos | só como alternativa de `funcionarios` |

`Usuario.pode_area(codigo)` → `True` para superusuário; senão `codigo in self.areas`.
`areas_catalogo()` devolve `(código, rótulo)` para montar a tela de acessos.

Seeds: `nucleo/0019_usuario_areas` cria o campo; `0020_seed_areas_gerencia`,
`0022_seed_area_caixa`, `0024_seed_funcionarios` e `0031_conceder_remuneracao_gerentes`
concedem áreas a `is_staff`.

### 4.5 `apps/nucleo/permissoes.py` — semântica exata

```python
def eh_gerente(user) -> bool:
    return user.is_authenticated and (user.is_superuser or user.is_staff)
```

| Decorator | Comportamento exato |
|---|---|
| `@requer_modulo(codigo)` | `@login_required` (anônimo → redirect para `LOGIN_URL`). Se `modulo_ativo(codigo)` é falso → **`Http404`** (“Módulo não contratado” — não existe para este cliente, inclusive para superusuário). Senão, se `request.user.pode_acessar(codigo)` é falso → **`PermissionDenied` (403)**. |
| `@requer_area(*codigos)` | `@login_required`. Passa quem tiver **qualquer** uma das áreas (variádico); senão **403**. Superusuário passa por `pode_area`. Chamar sem argumentos daria `any([])` = `False` → 403 sempre. |
| `@requer_gerencia` | `@login_required`. `eh_gerente(user)` falso → **403**. |
| `pode_ver_salario(user)` | `is_superuser` **ou** `pode_area(Area.REMUNERACAO)`. **Ser gerente não basta** — precisa da flag. |

`Usuario.pode_acessar(codigo)`: módulo tem de estar ativo **e** (superusuário **ou**
`self.modulos.filter(codigo=codigo, ativo=True).exists()`). Ou seja: **o 404 vem antes
do bypass de superusuário** — módulo inativo é 404 para todo mundo.

### 4.6 Como o menu/sidebar é montado

Três camadas, todas por permissão:

1. **Módulos** — `menu_modulos` (context processor) percorre `modulos_ativos()`,
   filtra por `request.user.modulos` (superusuário vê todos), agrupa pelo `grupo` do
   `APRESENTACAO` e resolve a `url_name`. Item sem URL vira
   `<span class="nav-item desabilitado" title="Em construção">`.
2. **Áreas-core** — `templates/base.html` usa `{% if user|pode_area:'…' %}` para os
   grupos “Operação” (Caixa, Recados do turno), “Cadastros” (Hóspedes, Agências,
   Empresas, Fornecedores, Pessoas, Funcionários, Quartos & tipos, Tabela de preços,
   Temporadas), “Financeiro” (Lançamentos, Contas, Sessões de caixa, Conciliação) e
   “Relacionamento” (NPS).
3. **Configurações** — só `user.is_staff or user.is_superuser`.

A **paleta de comandos** (⌘K) tem a mesma lógica: a lista estática de comandos em
`base.html` é montada dentro dos mesmos `{% if %}`, e os resultados dinâmicos vêm de
`busca_global`, que também filtra por `pode_acessar`.

---

## 5. Padrões transversais

### 5.1 Services como interface pública entre módulos

Regra (`CLAUDE.md`, `docs/ESPECIFICACAO.md` §1.2): **módulos só conversam por
services/interfaces públicas; nunca importam models internos uns dos outros** — exceto
os do núcleo, que são a fonte de verdade compartilhada.

Exemplos reais:

| Chamador | Chamada | Para que |
|---|---|---|
| `loja.services.finalizar_venda` | `nucleo.models.registrar_saida` + `receber_no_caixa(..., modulo=Modulo.LOJA)` **ou** `reservas.services.lancar_na_conta` | baixar estoque e cobrar no caixa da Loja ou no folio |
| `restaurante.services.fechar_comanda` | `receber_no_caixa(..., modulo=Modulo.RESTAURANTE)` ou `reservas.lancar_na_conta` | idem para comandas |
| `lavanderia.services.entregar` | `receber_no_caixa(..., modulo=Modulo.LAVANDERIA)` ou `reservas.lancar_na_conta` (tipo `servico`, natureza SERVIÇO) | cobrança do serviço ao hóspede |
| `portal.services` | `restaurante.abrir_comanda`, `governanca.abrir_faxina`, `manutencao.abrir_os`, `pagamentos.criar_cobranca`, `reservas.dados_estadia`/`estadia_ativa` | ações do hóspede, atribuídas ao usuário de sistema `_portal` |
| `site.views.finalizar_reserva` | `reservas.obter_ou_criar_hospede`, `reservas.criar_reserva_site[_unidade]`, `reservas.tipo_disponivel`, `reservas.diaria_media` | pré-reserva do canal site |
| `auditoria.services.varrer` | `importlib.import_module(...).pendencias_auditoria()` | agrega pendências sem importar models |
| `manutencao.services` | `reservas.uh_ocupada` | não bloquear quarto ocupado |
| `governanca.services` / `lavanderia.services` | `nucleo.models.modulo_ativo` | degradação graciosa dentro dos receivers |

`apps/reservas/services.py` é a interface pública do módulo mais
central: disponibilidade (`uhs_disponiveis`, `uh_disponivel`, `tipo_disponivel`,
`reservas_ativas_qs`, `expirar_vencidas`), preço (`tarifa_do_dia`,
`tarifa_da_unidade`, `diaria_media`, `diaria_media_unidade`, `tarifa_base_unidade`,
`preco_unidade_noite`), reserva (`criar_prereserva`, `criar_reserva_site[_unidade]`,
`confirmar_reserva`, `trocar_quarto`, `transferir_datas`), folio
(`lancar_na_conta`, `receber_pagamento`, `receber_adiantamento`, `contas_abertas`,
`resumo_fiscal_conta`), grupos (`criar_grupo`, `adicionar_quarto`, …), estadia
(`estadia_ativa`, `dados_estadia`), FNRH/BOH (`garantir_fichas_fnrh`, `preparar_fnrh`,
`fnrh_formset`, `enviar_fnrh`, `boh_mensal`), painéis (`mapa_quartos_hoje`,
`resumo_do_dia`, `dados_graficos`) e `pendencias_auditoria`.

**Exceções que existem hoje** (import cruzado de model, quase sempre *lazy*, dentro da
função, para não criar ciclo):

- `apps/nucleo/views.py` e `apps/nucleo/historico.py` importam models de módulos
  (`reservas.Reserva`, `reservas.TarifaUnidade`/`TarifaTemporada`, `comercial.Oportunidade`,
  `comercial.FichaComercial`, `site.VitrineQuarto`, `governanca.TarefaGovernanca`,
  `loja.Venda`, `restaurante.Comanda`). O núcleo lendo os módulos é a inversão
  consciente das telas agregadoras (dashboard, busca, form de quarto, histórico).
- `apps/fiscal/services.py` importa `reservas.ContaHospedagem`.
- `apps/relatorios/services.py` importa `reservas.Reserva`.
- `apps/reservas/views.py` e `apps/site/views.py` importam `pagamentos.Cobranca`.
- `apps/pagamentos/services.py` e `views.py:388` importam `site.Reserva` (sincroniza
  o recibo do canal).
- `apps/comercial/*` importa `pagamentos.Cobranca` e `site.ConfiguracaoSite`.
- `apps/marketing/*` importa `comercial.Oportunidade`/`Campanha`/`GastoDiario` — aqui é
  **por desenho**: Marketing é a camada de fluxo que embrulha `comercial.Campanha`.
- Seeds (`management/commands/*`) importam models livremente — são scripts, não módulos.

### 5.2 Signals para eventos entre módulos

Sinais customizados declarados em `apps/<app>/signals.py`; receivers em
`apps/<app>/receivers.py`, conectados no `AppConfig.ready()`. Todo receiver começa
checando `modulo_ativo(...)` (degradação graciosa).

**A falha de um ouvinte não desfaz a operação de origem** (`apps/nucleo/sinais.py`):

- quem emite chama `emitir(sinal, sender=..., **dados)`, que usa `send_robust` e registra
  no log (`apps.nucleo.sinais`) o receiver que falhou, com traceback;
- todo receiver entre módulos leva `@receptor_isolado`, que roda o corpo num savepoint
  próprio e nunca levanta erro para o emissor. No PostgreSQL um erro de banco aborta a
  transação inteira; o savepoint segura o estrago dentro do receiver.

Assim, um erro da Lavanderia ao recolher o enxoval não desfaz a faxina concluída, e um erro
do Comercial não desfaz o check-out. Sinal ou receiver novo segue as duas regras; os
testes estão em `apps/reservas/tests.py` (`SinaisIsoladosTests`).

| Sinal | Emitido por | Recebido por | Efeito |
|---|---|---|---|
| `reservas.signals.quarto_liberado` (`uh`, `reserva`, `usuario`, `origem`) | `reservas.models.Reserva.fazer_checkout` (`origem="checkout"`, `models.py:536`) e `reservas.services.trocar_quarto` (`origem="troca"`, `services.py:1405`) | `governanca.receivers.on_quarto_liberado`; `comercial.receivers.on_checkout_comercial` | Governança abre a faxina com a origem recebida; Comercial anota o hand-off pós-checkout (**só** quando `origem == "checkout"`) |
| `reservas.signals.reserva_encerrada` (`reserva`, `evento`, `motivo`, `usuario`) | `Reserva.cancelar` (`evento="cancelada"`) e `Reserva.marcar_no_show` (`evento="no_show"`) | `comercial.receivers.on_reserva_encerrada` | registra follow-up/retenção no funil |
| `manutencao.signals.reparo_concluido` (`uh`, `ordem`, `usuario`) | `manutencao.services.concluir_os`, quando a OS bloqueava o quarto (`services.py:145`) | `governanca.receivers.on_reparo_concluido` | abre faxina com `origem="manutencao"` antes de o quarto voltar a receber |
| `governanca.signals.faxina_concluida` (`uh`, `tarefa`, `usuario`) | `governanca.services.concluir_tarefa` (`services.py:68`) | `lavanderia.receivers.on_faxina_concluida` | `lavanderia.services.coletar_faxina(uh, usuario)` recolhe o kit `por_faxina` (em uso → suja) |
| `pagamentos.signals.pagamento_confirmado` (`cobranca`, `usuario`) | `pagamentos.services.confirmar_pagamento` (`services.py:114`) — um receiver que falhe não desfaz a confirmação | `comercial.receivers.on_sinal_pago` | sinal “solto” (finalidade `SINAL`, sem reserva/grupo) pago em oportunidade aberta → `ganhar_por_sinal` (ganha e cria a reserva) |
| `post_save` em `comercial.Oportunidade` | ORM | `marketing.signals.atribuir_campanha_vigente` (conectado em `MarketingConfig.ready`) | lead novo sem campanha recebe a campanha vigente do seu canal (via `.update()`, sem recursão) |
| `pre_save` / `post_save` / `post_delete` em **todos** os models de `apps.*` | ORM | `apps/nucleo/audit.py` | auditoria automática (§5.5) |
| `user_logged_in` / `user_logged_out` | `django.contrib.auth` | `apps/nucleo/audit.py` | registra `login` / `logout` na trilha |

### 5.3 Padrão “gateway plugável”

Todo integrador externo é um objeto escolhido por uma variável de settings, com um
`_GATEWAYS = {nome: Classe}` e um `get_*_gateway()` que levanta `ValidationError` para
nome desconhecido, com exceções legadas indicadas na tabela. O default é
`simulado`, mas isso **não garante ausência de rede**: o gateway de e-mail usa o
backend Django e pode enviar por SMTP real quando configurado. Para desenvolvimento,
deixe credenciais externas vazias e confira o backend efetivo.

| Setting | Arquivo | Implementações | Status |
|---|---|---|---|
| `PAGAMENTOS_GATEWAY` | `apps/pagamentos/gateways.py` | `simulado`, `safrapay` | `safrapay` **implementado** (Pix/cartão/boleto na API HML; exige `SAFRAPAY_TOKEN`, sem ele erra claro em vez de cair no simulado). `status_credenciais()` monta o diagnóstico na tela. Credenciamento, token e teste de produção precisam ser conferidos no ambiente. |
| `FNRH_GATEWAY` | `apps/reservas/fnrh_gateway.py` | `simulado`, `serpro` | `serpro` implementado (fluxo criar_reserva → criar_pessoa → adicionar_hospede → checkin, Basic Auth); exige `FNRH_API_URL/USER/SENHA`. Ativação: conferir credenciais SNRHos, dados e homologação no ambiente. |
| `FISCAL_GATEWAY` | `apps/fiscal/gateways.py` | `simulado`, `focus`, `governo` | `focus` e `governo` são **stubs** (`raise NotImplementedError`). `get_gateway()` aqui faz *fallback* silencioso para `simulado` em nome desconhecido. |
| `WHATSAPP_GATEWAY` | `apps/comercial/whatsapp_gateways.py` | `simulado`, `cloud`, `bsp` | `cloud` (Meta Graph API: texto, template, upload/download de mídia, áudio, imagem) implementado; `bsp` é **stub**. |
| `EMAIL_GATEWAY` | `apps/comercial/email_gateways.py` | `simulado`, `ses` | `simulado` usa o `EMAIL_BACKEND` do Django (console em dev); `ses` é **stub** (Fase 4). |
| `MIDIA_GATEWAY` | `apps/comercial/midia_gateways.py` | `simulado`, `meta`, `google` | `meta` (Conversions API, PII sempre com hash) implementado; `google` (Offline Import + sync de gasto) é **stub**. |
| `DECISAO_GATEWAY` | `apps/comercial/decisao_gateway.py` | `simulado`, `jev` | `simulado` decide de forma **determinística** (score/canal local); `jev` chama a API externa (exige `JEV_API_URL`/`JEV_API_KEY`, timeout `JEV_TIMEOUT_MS`). |

Fora do padrão, mas na mesma família: **`PIX_DIRETO`** (flag booleana, não gateway) —
quando ligada, as cobranças Pix saem por um BR Code EMV gerado **localmente**
(`apps/pagamentos/pix_br.py`, CRC-16/CCITT-FALSE) a partir da chave da própria pousada,
sem PSP; como não há PSP, **não há webhook** e a confirmação é manual. Cartão e boleto
continuam pelo `PAGAMENTOS_GATEWAY`.

### 5.4 Regras de dinheiro

1. **`DecimalField` sempre.** Nunca `float` em valor monetário. `MovimentoCaixa.valor`,
   `LancamentoConta.valor`, `Produto.custo_medio` (4 casas), etc.
2. **Imutabilidade dos livros-razão.** `MovimentoCaixa`, `MovimentoEstoque`,
   `LancamentoConta`, `MovimentoEnxoval` (Lavanderia), `LancamentoExtrato` e
   `TransacaoCartao` (Conciliação), `EventoPagamento`, `EventoFiscal`,
   `TrilhaAuditoria`. Os três primeiros implementam explicitamente
   `save()`/`delete()` que levantam `ValidationError`: correção é **movimento inverso**
   (estorno / ajuste / desconto), nunca `UPDATE`/`DELETE`.
3. **Crédito na conta do hóspede tem origem rastreável.** `PagamentoConta` e
   `Adiantamento` vêm do caixa (`movimento_caixa`), do gateway (`cobranca_id`, único por
   cobrança — confirmar duas vezes não credita duas vezes), do faturamento para agência
   ou empresa (`PagamentoConta.conta_receber`, o título a receber no Financeiro) ou de
   um estorno (`estorno_de`, valor negativo). Check-constraints garantem o sinal: crédito > 0 sem `estorno_de`;
   estorno < 0 com `estorno_de`. O saldo é sempre a soma, sem `UPDATE`.
4. **Natureza fiscal obrigatória (a “4ª veia”).** `NaturezaFiscal` (`servico` | `consumo`)
   está em `Produto.natureza` e em `LancamentoConta.natureza` — este **sem default**
   (`clean()` exige). Diária e serviços → SERVIÇO (NFS-e/ISS); produto consumido →
   CONSUMO (NF-e/NFC-e/ICMS). `fiscal.services.emitir` roteia por natureza
   (`_tipo_por_natureza`) e `reservas.services.resumo_fiscal_conta` separa a conta nas
   duas naturezas para a emissão.
5. **Um só formatador** (`moeda.intcomma_brl`) e **um único ponto de recebimento**
   (`receber_no_caixa`), por módulo.
6. **Travas de concorrência** onde há read-modify-write de dinheiro/saldo:
   `estornar_movimento`, `registrar_entrada`, `registrar_saida`, arranjo de camas
   (`_travar_e_resolver_arranjo`) — todas via `apps.nucleo.sistema.travar`.

### 5.5 Auditoria automática (`apps/nucleo/audit.py`)

Ligada em `NucleoConfig.ready()` → `conectar_auditoria_automatica()`.

**Middleware.** `AuditContextMiddleware` publica, por requisição, **quem** e de **qual
IP** num `threading.local()` (`definir_contexto` / `usuario_atual()` / `ip_atual()`,
limpo no `finally`), para que qualquer service — mesmo sem `request` em mãos — saiba a
quem atribuir a ação. O IP vem do primeiro item de `X-Forwarded-For` (Railway) ou de
`REMOTE_ADDR`. Escrita sem login (POST do site, do portal do hóspede, do link de
pagamento e dos webhooks) é atribuída a um usuário de sistema escolhido pelo caminho
(`_portal`, `_pagamentos`, `_whatsapp`; o resto, `_site`); leitura anônima não tem ator.

**Signals por denylist, não allowlist.** `_modelos_para_auditar()` pega **todos** os
models cujo app começa com `apps.` (ignora Django/contrib e tabelas M2M
`auto_created`) e conecta `pre_save`, `post_save` e `post_delete`. São ~109 classes de
model no repositório, menos as exclusões:

```python
MODELOS_EXCLUIDOS = {
    "nucleo.TrilhaAuditoria",      # a própria trilha — evita loop infinito
    "pagamentos.EventoPagamento",  # já é a trilha de webhooks do gateway
}
```

- `pre_save` guarda o snapshot do estado anterior (`_audit_anterior`) para o diff — só
  quando há usuário no contexto (sem ele nada é registrado, então a leitura não
  acontece) e, com `save(update_fields=…)`, só dos campos gravados.
- `post_save` grava `criar` (`{"valores": …}`) ou `editar` (`{"alteracoes": {campo: [antes, depois]}}`);
  `save` sem mudança de campo não gera registro.
- `post_delete` grava `excluir` com o snapshot.
- **Só registra com ator no contexto** — o usuário logado ou, na escrita pública, o
  usuário de sistema. Seed, migration, shell e cron sem contexto não poluem a trilha.
- `CAMPOS_IGNORADOS` lista os campos que nunca entram no diff (carimbos automáticos e
  credenciais, como `password`). Ao criar um campo sensível novo (segredo, token,
  documento), avalie incluí-lo ali ou em `CAMPOS_SENSIVEIS`.
- `CAMPOS_SENSIVEIS = {salario}`: a mudança **é** auditada, mas o valor é redigido
  (`"•••"`) por `redigir_sensiveis()` para quem não tem a área Remuneração.
- `CAMPOS_PII` (documento, CPF, RG, passaporte, nascimento): a trilha grava **que**
  mudou, nunca o valor — `"•••"` já na gravação (o diff compara os valores reais antes de
  mascarar; vazio continua vazio).
- `user_logged_in` / `user_logged_out` → ações `login` / `logout`.

**`registrar_auditoria(usuario, acao, objeto, detalhe=None, ip=None)`** é a via
explícita, usada nos fluxos que carregam intenção/motivo (estorno, cancelamento,
reabertura de caixa, troca de quarto, ajuste de estoque, baixa de conta, resolução de
recado…). Se `usuario`/`ip` vierem `None`, faz fallback para o contexto do middleware.

**`TrilhaAuditoria`** — `usuario` (`SET_NULL`), `acao`, `alvo` (nome da classe),
`alvo_id`, `detalhe` (JSON), `ip`, `criado_em`; 3 índices
(`-criado_em`, `usuario+-criado_em`, `alvo+alvo_id`); **append-only**. A única saída é a
retenção: `manage.py purgar_trilha` apaga o que passou de `TRILHA_RETENCAO_DIAS` (0 =
guardar sempre, o padrão) e registra a própria purga; roda no grupo diário do `rotinas`.

**Leitura** — `apps/auditoria`: `formatacao.frase()` + filtro `|frase_auditoria`
transformam o registro em frase pt-BR (“Abriu o caixa de Reservas — fundo R$ 0,00”),
com o JSON cru no `title`; filtro mês/ano compartilhado (`nucleo.periodos`), usuário
clicável (timeline por operador) e export CSV. Acesso por `@requer_modulo(Modulo.AUDITORIA)`;
**exportar** o CSV exige gerência.

**O que a auditoria automática não cobre** (documentado no próprio código e em
`CLAUDE.md`): só **escritas** — leitura/visualização não gera log; `bulk_create`,
`QuerySet.update()` e SQL cru não passam por signals — onde um `update()` muda estado de
negócio, o registro é explícito (ex.: `expirar_vencidas` grava `expiracao_retencao` por
reserva); e o `pre_save` custa 1 query extra por escrita com ator (as rotinas sem contexto
não pagam esse custo).

### 5.6 Camadas de segurança (o que cada uma faz)

| Camada | Onde | O que faz |
|---|---|---|
| `CSPMiddleware` | `apps/nucleo/security_headers.py` | Adiciona a Content-Security-Policy do projeto. Começa em **report-only** (`CSP_REPORT_ONLY=1`, default): o navegador apenas reporta no console. Com `CSP_REPORT_ONLY=False` o header passa a ser `Content-Security-Policy` (bloqueio). A política libera o que o app usa (unpkg/jsdelivr/cdnjs/GTM/Facebook em `script-src`, Google Fonts em `style-src`/`font-src`, `img-src https:` para fotos, `frame-src https:` para o tour 360°) e fecha `object-src`, `base-uri`, `frame-ancestors` e `form-action`. `report-uri /csp/relatorio/`: cada violação vira uma linha no logger `csp` (tokens das URLs mascarados), para saber o que quebraria antes de ligar o bloqueio. |
| `MFAObrigatorioMiddleware` | `apps/nucleo/security_headers.py` | Superusuário com `mfa_ativo=False` é redirecionado para `mfa_ativar` em qualquer rota que não seja `mfa_ativar`/`login`/`logout`/`/static/`/`/media/`/"Esqueci minha senha". Não roda sob `TESTING` nem com `MFA_OBRIGATORIO=False`. `mfa_obrigatorio(user)` segue `MFA_OBRIGATORIO_PARA`: `superusuario` (padrão), `gerencia` (+ staff) ou `financeiro` (+ áreas Financeiro/Caixa); os demais são opt-in. |
| `LoginComLimite` | `apps/nucleo/auth_views.py` | `LoginView` com rate-limit por IP (10 tentativas / 300 s, via `apps/nucleo/ratelimit.py` sobre o cache do Django), **trava por usuário** (8 senhas erradas para o mesmo usuário, de qualquer IP → 15 min; acerto zera; `LOGIN_TRAVA_POR_CONTA`, desligada sob `TESTING`) e **passo de MFA**: senha correta com `mfa_ativo` não loga — guarda `mfa_pending_user` na sessão e redireciona para `mfa_desafio`. Mensagens em pt-BR (`FormularioEntrada`). |
| Esqueci minha senha | `RecuperarSenha` em `auth_views.py` | `/crm/senha/esqueci/` → e-mail com link de uso único válido por 1 h (`PASSWORD_RESET_TIMEOUT`); mesma resposta exista ou não o e-mail; 5 pedidos / 15 min por IP. |
| Anti-robô | `apps/nucleo/antirrobo.py` + `{% campos_antirrobo %}` | Campo armadilha invisível + carimbo assinado de tempo mínimo (2 s) nos formulários públicos ("Pedir proposta", páginas de captação); robô recebe sucesso falso e nada é criado. |
| MFA (TOTP) | `apps/nucleo/mfa.py`, `mfa_views.py` | `pyotp` com `valid_window=1`; segredo e **códigos de backup com hash do Django** em `Usuario`; QR gerado inline como SVG (`SvgPathImage`); `consumir_backup` é de uso único. |
| Settings de produção | `config/settings.py` | Com `DEBUG=0`: `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` (isentando `^healthz/?$`), cookies `Secure`, HSTS 30 dias com subdomínios e preload. |
| Sempre ligados | `config/settings.py` | Cookies com nome próprio (`vo_testa_sessionid`/`vo_testa_csrftoken`), `SECURE_REFERRER_POLICY="same-origin"` (protege tokens em URL do portal/pagamento), `SECURE_CONTENT_TYPE_NOSNIFF`, sessão de 10 h renovada por atividade, `SameSite=Lax`. |
| `SECRET_KEY` | `config/settings.py` | Em produção (`DEBUG=0` e não `TESTING`), chave ausente ou com o prefixo de dev → `ImproperlyConfigured` na subida. |
| `rate limit` em rotas públicas | `apps/nucleo/ratelimit.py` | `limite_excedido(request, escopo, limite, janela, sufixo)` sobre o cache; usado em login, webhook, link de pagamento e portal. O docstring avisa que com múltiplos workers o `LocMemCache` torna o limite por processo. |
| CSV | `apps/nucleo/export.py` | `sanitizar_celula` neutraliza fórmulas em todo export. |

---

## 6. Rotas

Tudo é declarado em **`config/urls.py`**, que compõe o domínio único:

- **raiz `/`** → site público. `views_lp.home_root` decide: com `HOME_MODO=lp_fundador`
  serve a LP Fundador; senão delega para `apps.site.views.home`. As demais páginas do
  site vêm de `include("apps.site.urls")`, montado também em `""`.
- **`/crm/…`** → todo o sistema interno (inclusive o admin e o login).
- **`/hospede/…`** → portal do hóspede, fora do `/crm`.
- **LPs, captação, descadastro de e-mail e webhook do WhatsApp** → públicos na raiz.
- **mídia** → `re_path(r"^media/(?P<path>.*)$", django.views.static.serve)`, adicionado
  **incondicionalmente** (não só em `DEBUG`), porque o Railway ainda serve a mídia local
  quando o R2 não está configurado.

| Grupo de rotas | App / urlconf | Público | Nota |
|---|---|---|---|
| `/healthz/` | `config/urls.py` | infra | probe do Railway: `SELECT 1` no banco, 503 se falhar; HTTP, isento de SSL redirect |
| `/robots.txt`, `/llms.txt`, `/sitemap.xml` | `apps.site` + `django.contrib.sitemaps` | robôs | SEO |
| `/` + páginas do site | `apps.site.urls` (`app_name="core"`) | hóspede | home, `/quartos/`, `/quarto/<uh_id>/`, legais, `/pedir-proposta/`, fluxo `reservar/…`, `/reserva/<token>/`, `/minha-reserva/…`, `/lab/` (oculto) |
| `/hospede/<token>/…` | `apps.portal.urls` | hóspede (token, sem login) | `home`, `checkin` (pré check-in FNRH), `nps`, `pedir`, `solicitar`, `checkout`, `checkout/pagar`, `checkout/recepcao` |
| `/hospede/recepcao/…` | `apps.portal.urls` | equipe | `@requer_modulo(Modulo.APPSITE)`: QR do portal, QR da FNRH, painel de solicitações |
| `/lp/fundador/`, `/lp/fundador-2/`, `/lp/inauguracao_31_10_2026/` (+ `/lead/`) | `apps.comercial.urls_lp` | público | HTML de `LPs/` servido com as fotos e fontes em base64 trocadas por `/lp/arquivo/<hash>.<ext>` (cache imutável); `/lp/inauguracao/` leva à LP com os `utm_*` |
| `/captacao/<slug>/` | `apps.comercial.urls_publicas` | público | Páginas de Captação geridas no CRM |
| `/captacao/fundador/`, `/captacao/fundador-2/`, `/captacao/inauguracao_31_10_2026/` | `config/urls.py` | público | `RedirectView` para as LPs novas |
| `/privacidade/` | `apps.comercial.views_lp` | público | LGPD |
| `/email/descadastrar/<token>/` | `apps.comercial.urls_email_publico` | público | opt-out de e-mail marketing |
| `/whatsapp/webhook/` | `apps.comercial.urls_whatsapp` | Meta | webhook do WhatsApp Cloud API |
| `/api/nps/v1/…` | `apps.nps.api_urls` (`app_name="nps_api"`) | API | **stub** (3 endpoints); `POST /respostas/` é `csrf_exempt`, os GET exigem login |
| `/crm/admin/…` | `django.contrib.admin` | equipe | admin do Django |
| `/crm/entrar/`, `/crm/sair/` | `LoginComLimite` / `LogoutView` | equipe | login com rate-limit + MFA |
| `/crm/mfa/`, `/crm/mfa/ativar/`, `/crm/mfa/desafio/` | `apps.nucleo.mfa_views` | equipe | configuração, ativação (QR) e desafio TOTP |
| `/crm/…` (raiz do CRM) | `apps.nucleo.urls` (**sem `app_name`** → nomes globais) | equipe | 40 rotas: `dashboard`, `busca_global`, `modulos_central`, funcionários, pessoas/hóspedes/agências/empresas/fornecedores, estrutura/tipos/UHs, `tabela_precos`, temporadas, caixa (abrir/movimento/fechar/sessões/reabrir/estorno), financeiro (lançamentos/contas/baixa), logbook |
| `/crm/reservas/…` | `apps.reservas.urls` | equipe | 43 rotas: mapa, lista, detalhe, check-in/out, no-show e desfazer, FNRH, BOH, grupos, troca de quarto, colchões, kit de contingência, restrições de venda |
| `/crm/estoque/…` | `apps.estoque.urls` | equipe | posição, produtos (lista, novo, editar, kardex), cadastros (categorias e depósitos), entrada, saída, transferência, ajuste, inventários e a contagem |
| `/crm/loja/…` | `apps.loja.urls` | equipe | 6 rotas: `pdv`, `finalizar`, `vendas`, `venda`, `cupom` (80 mm), `cancelar` |
| `/crm/restaurante/…` | `apps.restaurante.urls` | equipe | 11 rotas (comandas, itens, fechamento, transferência, cupom de 80 mm) |
| `/crm/lavanderia/…` | `apps.lavanderia.urls` | equipe | 14 rotas (ordens + rouparia + cupom de 80 mm) |
| `/crm/governanca/…` | `apps.governanca.urls` | equipe | 8 rotas: `painel` (a visão geral da casa), `quartos` (a lista de trabalho, aceita `?estado=`), `discrepancias`, `nova_tarefa` (com `iniciar` abre e já começa), `tarefa_acao`, `status_marcar`, `ronda`, `devolver` (formulário do motivo: modal com HTMX, página sem JS) |
| `/crm/manutencao/…` | `apps.manutencao.urls` | equipe | 6 rotas (painel, nova, detalhe, iniciar, concluir, cancelar) |
| `/crm/escala/…` | `apps.escala.urls` | equipe | 12 rotas: `grade`, `gerar`, `editar`, `publicar`, `relatorio`, `atribuir`, `remover_atribuicao`, `minha`, `turnos`, `ausencias`, `trocas`, `decidir_troca` |
| `/crm/pagamentos/…` | `apps.pagamentos.urls` | equipe + **público** | 15 rotas. Painel/conciliação/criar/detalhe/simular/liquidar/cancelar/estornar são internas; **`/crm/pagamentos/pagar/<token>/`** (+ `confirmar/`, `cartao/`) é o **link de pagamento público, sem login**; `/crm/pagamentos/webhook/` é `csrf_exempt` |
| `/crm/fiscal/…` | `apps.fiscal.urls` | equipe + provedor | 5 rotas (painel, detalhe, emitir, cancelar, **webhook** do Focus validado por `FISCAL_WEBHOOK_TOKEN`) |
| `/crm/conciliacao/…` | `apps.conciliacao.urls` | equipe | 12 rotas (`@requer_area(Area.FINANCEIRO)`) |
| `/crm/relatorios/…` | `apps.relatorios.urls` | gerência | 2 rotas: índice e `<slug:chave>` (14 relatórios) |
| `/crm/auditoria/…` | `apps.auditoria.urls` | gerência | 2 rotas: painel de pendências e trilha |
| `/crm/comercial/…` | `apps.comercial.urls` | equipe | 48 rotas (funil, oportunidade, cotações, atividades, WhatsApp, e-mail, LP Páginas, respostas rápidas, impulsionamento) |
| `/crm/marketing/…` | `apps.marketing.urls` | equipe | 26 rotas (quadro de fases, ficha, peças, etapas, checklist, verba, calendário) |
| `/crm/nps/` | `apps.nps.urls` | equipe | 1 rota (`@requer_area(Area.NPS)`) |
| `/media/<path>` | `django.views.static.serve` | público | mídia local quando o R2 não está ativo |

**Total:** 353 entradas `path()`/`re_path()` somando `config/urls.py` e todos os
urlconfs de app, das quais **24 são `include()`** → **329 rotas terminais declaradas
no projeto**. Uma dessas 302 (`crm/admin/`) monta a árvore inteira do admin do Django,
que tem as suas próprias rotas e não está contada aqui.

---

## 7. Configuração (variáveis de ambiente)

Tudo que varia por ambiente é lido em `config/settings.py` (`.env` em dev via
`python-dotenv`; painel do Railway em produção). Duas flags **não** vêm do ambiente:
`TESTING` (`"test" in sys.argv`) e `PAGAMENTOS_WEBHOOK_CONFIA_CORPO`
(`DEBUG or TESTING`).

### Núcleo / Django

| Variável | Default | O que faz |
|---|---|---|
| `DEBUG` | `0` | `True` só com `"1"`. Governa o bloco de hardening, `MFA_OBRIGATORIO` e a confiança no corpo do webhook. |
| `LOG_LEVEL` | `INFO` (`WARNING` nos testes) | Nível do `LOGGING` que manda tudo para o stdout (logs do Railway). |
| `REDIS_URL` | — | Cache compartilhado em Redis. Vazio: `DatabaseCache` na tabela `nucleo_cache`. Nos testes: memória. |
| `BACKUP_DIR` | — | Pasta do `backup_banco` quando não há R2. Vazio e sem R2: o backup não roda (só avisa). |
| `KIT_CONTINGENCIA_EMAILS` | — | Quem recebe a folha do dia (kit de contingência) toda madrugada, separados por vírgula. Vazio: não envia nada. |
| `ROTINAS_MONITOR_FREQUENTES`, `ROTINAS_MONITOR_DIARIAS` | — | URL de um check do Healthchecks.io (ou compatível) por grupo do `rotinas` ("dead man's switch"): o grupo avisa `/start`, o fim e `/fail`. Vazio: não avisa. Ver 10.4. |
| `DB_JIT` | `0` | `1` religa o JIT do Postgres na conexão do sistema. Desligado por padrão (`-c jit=off`): com tabelas pequenas ainda sem ANALYZE o planejador compilava consultas de 1 ms por 185 ms. |
| `SENTRY_DSN` | — | Liga o Sentry (fora dos testes). Sem PII: `send_default_pii=False`, sem variáveis locais e sem corpo de requisição. Opcionais: `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`; a release vem de `RAILWAY_GIT_COMMIT_SHA`. |
| `SECRET_KEY` | chave de dev versionada | Em produção (`DEBUG=0`, não `TESTING`) é **obrigatória** e não pode começar com `dev-inseguro` — senão `ImproperlyConfigured`. |
| `ALLOWED_HOSTS` | `""` (lista separada por vírgula) | Com `DEBUG=1` e vazio, usa `localhost,127.0.0.1`. Sempre são adicionados os domínios do próprio serviço (`RAILWAY_PUBLIC_DOMAIN`, `RAILWAY_PRIVATE_DOMAIN`), `healthcheck.railway.app` e loopbacks. Sem curinga `.railway.app`: o domínio próprio (ex.: `www.pousadavotesta.com.br`) vai na variável. |
| `RAILWAY_PUBLIC_DOMAIN` | `""` | Injetada pelo Railway; entra em `ALLOWED_HOSTS`. |
| `RAILWAY_PRIVATE_DOMAIN` | `""` | Idem (rede interna). |
| `CSRF_TRUSTED_ORIGINS` | `""` | Origens confiáveis (lista por vírgula). |
| `DATABASE_URL` | `postgres://localhost/crm_vo_testa` | Lida por `dj_database_url.config(conn_max_age=600)`. |

### Segurança

| Variável | Default | O que faz |
|---|---|---|
| `CSP_REPORT_ONLY` | `1` | `1` = header `…-Report-Only` (observa); `0`/outro = CSP que **bloqueia**. |
| `MFA_OBRIGATORIO` | `0` se `DEBUG`, senão `1` | Liga o `MFAObrigatorioMiddleware`. |
| `MFA_OBRIGATORIO_PARA` | `superusuario` | A quem o MFA é obrigatório: `superusuario`, `gerencia` (+ staff) ou `financeiro` (+ áreas Financeiro/Caixa). |
| `TRILHA_RETENCAO_DIAS` | `0` | Retenção da trilha de auditoria (`purgar_trilha`); 0 = guardar sempre. A política de retenção deve ser validada para a operação; o default técnico não define prazo legal. |

### Mídia (Cloudflare R2)

| Variável | Default | O que faz |
|---|---|---|
| `R2_BUCKET` | `""` | Nome do bucket. |
| `R2_ACCESS_KEY_ID` | `""` | Credencial S3. |
| `R2_SECRET_ACCESS_KEY` | `""` | Credencial S3. |
| `R2_ENDPOINT_URL` | `""` | Endpoint da API S3 do R2. |
| `R2_PUBLIC_DOMAIN` | `""` | Domínio público de leitura. |

`USE_R2 = all([as 5])`. Só com as cinco preenchidas o storage default vira
`storages.backends.s3.S3Storage` (prefixo `media/`, sem ACL, sem assinatura na
querystring, `file_overwrite=False`) e `MEDIA_URL` passa a `https://<R2_PUBLIC_DOMAIN>/media/`.
Sem elas, filesystem local — e **o disco do Railway é efêmero**.

### Pagamentos

| Variável | Default | O que faz |
|---|---|---|
| `PAGAMENTOS_GATEWAY` | `simulado` | `simulado` \| `safrapay`. |
| `SAFRAPAY_ENV` | `hml` | `hml` → `payment-hml.safrapay.com.br`; `prod` → `payment.safrapay.com.br`. |
| `SAFRAPAY_GATEWAY_URL` | derivada de `SAFRAPAY_ENV` | Sobrescreve a base da API. |
| `SAFRAPAY_TIMEOUT` | `10` | Segundos de espera pela API. Tempo esgotado, queda na leitura e resposta que não é JSON viram `ValidationError` com mensagem clara. |
| `SAFRAPAY_ID` | `""` | Credencial do portal (3 campos). |
| `SAFRAPAY_CODIGO_ATIVACAO` | `""` | Idem. |
| `SAFRAPAY_TOKEN` | `""` | Merchant Token; sem ele o gateway `safrapay` erra explicitamente. |
| `PIX_DIRETO` | `0` | `1` = Pix por BR Code local, sem PSP e **sem webhook** (baixa manual). |
| `PIX_CHAVE` | `""` | Chave Pix da pousada. |
| `PIX_RECEBEDOR_NOME` | `POUSADA VO TESTA` | Nome no BR Code. |
| `PIX_RECEBEDOR_CIDADE` | `ITA` | Cidade no BR Code. |
| `PAGAMENTOS_TELEFONE_PADRAO` | `4920550005` | Telefone mandado ao gateway quando o pagador não tem (o comercial público da pousada). |

### Reservas e preço

| Variável | Default | O que faz |
|---|---|---|
| `RESERVA_RETENCAO_MINUTOS` | `30` | Minutos que a pré-reserva de canal segura o quarto antes de expirar. |
| `CHECKOUT_TOLERANCIA_ARREDONDAMENTO` | `0.10` | Saldo positivo até este valor é quitado no check-out com um desconto auditado (`ajuste_arredondamento`); `0` desliga. |
| `ACRESCIMO_TARIFA_DUPLO` | `1.6` | Fator sobre a tarifa do tipo para quarto de dois cômodos (arredondado à dezena). `tarifa_override` vence o cálculo. |
| `PRECO_ISS_ALIQUOTA` | `FISCAL_NFSE_ISS_ALIQUOTA` | % de ISS lançado na conta. |
| `PRECO_TAXA_TURISMO_DIARIA` | `4.00` | R$ fixos por noite. |
| `PRECO_SINGLE_FATOR` | `0.70` | Fator para hóspede sozinho. |
| `PRECO_PARCELAS_MAX` | `3` | Máximo de parcelas sem juros na venda. |
| `PRECO_TAXAS_ATIVAS` | `1` (e **forçado off** sob `TESTING`) | Lança ISS + taxa de turismo na conta no check-in. |
| `CANCELAMENTO_ARREPENDIMENTO_DIAS` | `7` | Janela de arrependimento (CDC) a partir da confirmação. |
| `CANCELAMENTO_RETENCAO_PCT` | `10` | % retida depois da janela. |
| `ECA_BLOQUEAR_CHECKIN` | `1` | Check-in recusado com menor sem os pais/responsável nem autorização conferida (ECA, art. 82). |
| `FATURAMENTO_PRAZO_DIAS` | `30` | Vencimento padrão do título a receber quando a conta é faturada para agência/empresa. |
| `COMERCIAL_SINAL_PCT` | `30` | Sinal que o Comercial gera para um lead, em % do valor estimado. |

### FNRH (Embratur/Serpro)

| Variável | Default | O que faz |
|---|---|---|
| `FNRH_BLOQUEAR_CHECKIN` | `1` (e **forçado off** sob `TESTING`) | Exige ficha FNRH completa de cada hóspede para o check-in. |
| `FNRH_GATEWAY` | `simulado` | `simulado` \| `serpro`. |
| `FNRH_API_URL` | `https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2` | Base da API (homologação por padrão). |
| `FNRH_API_USER` | `""` | Basic Auth. |
| `FNRH_API_SENHA` | `""` | Basic Auth. |

### Fiscal

| Variável | Default | O que faz |
|---|---|---|
| `FISCAL_GATEWAY` | `simulado` | `simulado` \| `focus` \| `governo` (os dois últimos, stubs). |
| `FISCAL_REGIME` | `lucro_presumido` | Regime tributário. |
| `FISCAL_NFSE_CODIGO_SERVICO` | `090101` | Código do serviço de hospedagem. |
| `FISCAL_NFSE_ISS_ALIQUOTA` | `4.0` | % de ISS de Itá/SC. |
| `FISCAL_NFCE_HABILITADA` | `0` | Depende de Inscrição Estadual. Desligada, os PDVs (Loja, comanda) mostram o aviso de venda sem NFC-e. |
| `FISCAL_BLOQUEAR_VENDA_SEM_NFCE` | `0` | Com `1` e sem NFC-e, a venda de produto (Loja e fechamento de comanda) é recusada. |
| `FISCAL_IBS_CBS_ATIVO` | `1` | Destaca IBS e CBS no documento fiscal (LC 214/2025). |
| `FISCAL_CBS_ALIQUOTA` | `0.9` | % de CBS (2026: fase de teste). |
| `FISCAL_IBS_ALIQUOTA` | `0.1` | % de IBS (2026: fase de teste). |
| `LGPD_ENCARREGADO_NOME` | `Direção da Pousada Vô Testa` | Encarregado pelos dados, publicado nas políticas de privacidade. |
| `LGPD_ENCARREGADO_EMAIL` | `comercial@pousadavotesta.com.br` | Contato do encarregado. |
| `FISCAL_WEBHOOK_TOKEN` | `""` | Segredo compartilhado validado no webhook do Focus. |

### E-mail

| Variável | Default | O que faz |
|---|---|---|
| `EMAIL_HOST` | `""` | **Vazio = console backend** (dev). Preenchido → SMTP. |
| `EMAIL_PORT` | `587` | Só com `EMAIL_HOST`. |
| `EMAIL_USE_TLS` | `1` | Só com `EMAIL_HOST`. |
| `EMAIL_HOST_USER` | `""` | Conta SMTP (ex.: Zoho `naoresponda@`). |
| `EMAIL_HOST_PASSWORD` | `""` | Senha de app. |
| `DEFAULT_FROM_EMAIL` | `Pousada Vô Testa <naoresponda@pousadavotesta.com.br>` | Remetente transacional. |
| `EMAIL_GATEWAY` | `simulado` | `simulado` (usa o `EMAIL_BACKEND` acima) \| `ses` (stub). |
| `EMAIL_COMERCIAL_FROM` | `Pousada Vô Testa <comercial@pousadavotesta.com.br>` | Remetente do trilho 1:1. |
| `EMAIL_COMERCIAL_REPLY_TO` | `comercial@pousadavotesta.com.br` | Reply-To do 1:1. |
| `EMAIL_COMERCIAL_HOST_USER` | `""` | SMTP dedicado do `comercial@`; vazio = envia pela conta global com Reply-To. |
| `EMAIL_COMERCIAL_HOST_PASSWORD` | `""` | Idem. |
| `EMAIL_TIMEOUT` | `15` | Segundos de espera do SMTP. |
| `EMAIL_ENVIO_ASSINCRONO` | `1` | Envia o 1:1 em thread de fundo; desligar em testes para determinismo. |
| `LEADS_ALERTA_EMAILS` | `""` | Quem é avisado de lead novo (vírgula); vazio → `comercial@`. |
| `LEAD_BOAS_VINDAS` | `1` | Boas-vindas automáticas ao lead de LP/site. |
| `LEAD_BOAS_VINDAS_MAX_DIA` | `100` | Teto diário dessas boas-vindas (uma por pessoa, sempre). |

### Site, SEO e analytics

| Variável | Default | O que faz |
|---|---|---|
| `SITE_PUBLIC_URL` | `http://127.0.0.1:8000` | URL pública usada nos links de e-mail (sem barra final). |
| `HOME_MODO` | `""` | `lp_fundador` faz `/` servir a LP; vazio = site normal. Reversível por env. |
| `GA_MEASUREMENT_ID` | `""` | GA4 do site público; vazio = tag não carrega. |
| `GOOGLE_TAG_ID` | ID GA4 público da pousada (fixado no settings) | Google tag injetada na LP. |
| `GEOIP_CITY_DB` | `""` | Caminho de um `GeoLite2-City.mmdb` (offline, opcional) para estimar a cidade do lead. |

### Mídia paga, WhatsApp e decisão de lead

| Variável | Default | O que faz |
|---|---|---|
| `MIDIA_GATEWAY` | `simulado` | `simulado` \| `meta` \| `google`. |
| `META_PIXEL_ID` | ID público da pousada (fixado no settings) | Pixel do navegador. |
| `META_CAPI_TOKEN` | `""` | Token da Conversions API (**segredo**); vazio = CAPI dormente. |
| `META_CAPI_TEST_CODE` | `""` | `test_event_code` opcional. |
| `META_CAPI_VERSION` | `v21.0` | Versão da Graph API para o CAPI. |
| `META_CRM_NOME` | `Pousada Vô Testa CRM` | Nome do CRM reportado à Meta. |
| `GOOGLE_ADS_CUSTOMER_ID` | `""` | Conta do Google Ads. |
| `GOOGLE_ADS_CONVERSION_ACTION` | `""` | Ação de conversão offline. |
| `WHATSAPP_GATEWAY` | `simulado` | `simulado` \| `cloud` \| `bsp`. |
| `WHATSAPP_CLOUD_TOKEN` | `""` | Token permanente (System User). |
| `WHATSAPP_CLOUD_PHONE_ID` | `""` | Phone Number ID na WABA. |
| `WHATSAPP_VERIFY_TOKEN` | `""` | Segredo do handshake do webhook. |
| `WHATSAPP_APP_SECRET` | `""` | Se definido, o webhook exige `X-Hub-Signature-256`. |
| `WHATSAPP_API_VERSION` | `v21.0` | Versão da Graph API. |
| `WHATSAPP_WABA_ID` | `""` | Para gestão de templates (futuro). |
| `WHATSAPP_TEMPLATE_RETOMADA` | `retomada_lead` | Template aprovado para reabrir conversa fora da janela de 24 h. |
| `WHATSAPP_TEMPLATE_RETOMADA_IDIOMA` | `pt_BR` | Idioma do template. |
| `DECISAO_GATEWAY` | `simulado` | `simulado` \| `jev`. |
| `JEV_API_URL` | `""` | Endpoint do provedor de decisão. |
| `JEV_API_KEY` | `""` | Credencial. |
| `JEV_TIMEOUT_MS` | `800` | Timeout da chamada. |

> `FRIGOBAR_BLOQUEAR_CHECKOUT` foi retirada do `.env.example`: o módulo Frigobar foi
> removido (`nucleo/0036`) e o check-out só exige saldo zerado (`Reserva.fazer_checkout`).

---

## 8. Rodando localmente

Pré-requisitos: Python 3.14, Docker (ou um PostgreSQL local) e Git.

### 8.1 Windows (PowerShell) — ambiente usado neste projeto

O `venv` fica **fora do OneDrive** (a sincronização de milhares de arquivos atrapalha
o ambiente):

```powershell
# 1) Dependências com uv (ou python -m venv + pip)
uv venv --python 3.14 C:\Users\<voce>\.venvs\vo_testa
C:\Users\<voce>\.venvs\vo_testa\Scripts\python.exe -m pip install -r requirements.txt
C:\Users\<voce>\.venvs\vo_testa\Scripts\python.exe -m pip install -r requirements-dev.txt

# 2) PostgreSQL 16 em Docker, numa porta que não briga com nada
docker run -d --name vo_testa_pg -p 127.0.0.1:55432:5432 `
  -e POSTGRES_USER=vo -e POSTGRES_PASSWORD=<sua-senha> -e POSTGRES_DB=crm_vo_testa `
  postgres:16
```

Depois crie o `.env` na raiz do repositório:

```ini
DEBUG=1
DATABASE_URL=postgres://vo:<sua-senha>@127.0.0.1:55432/crm_vo_testa
```

Os comandos a seguir usam `C:\Users\<voce>\.venvs\vo_testa\Scripts\python.exe manage.py …`.

### 8.2 macOS / Linux

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # já inclui requirements.txt

docker run -d --name vo_testa_pg -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=vo -e POSTGRES_PASSWORD=<sua-senha> -e POSTGRES_DB=crm_vo_testa \
  postgres:16
# (ou um Postgres do brew/apt; ajuste a DATABASE_URL)

cp .env.example .env     # e ajuste DEBUG=1 + DATABASE_URL
```

Comandos: `.venv/bin/python manage.py …`.

### 8.3 Migrar

```bash
python manage.py migrate
```

O `migrate` já deixa pronto: os módulos contratados ativos, as 6 formas de pagamento,
o “Almoxarifado central”, as áreas-core dos gerentes, o tipo “Dia na Pousada” com as
unidades `DAY-01..08` (`DAY-05..08` já inativas) e a verba de Marketing.

### 8.4 A ordem de bootstrap

O comando `estrutura_inicial` cria os quatro tipos técnicos de pernoite e os 24
quartos ausentes, sem alterar os tipos/UHs que já existem. Com `--completo`, também
executa `configurar_camas`, `carregar_tarifas` e `sincronizar_vitrine`, que possuem
efeitos próprios sobre os cadastros. Use esse fluxo em banco novo; não presuma que
reexecutar todos os seeds numa operação existente seja uma ação sem mudanças.

Os seeds dependem dos nomes Padrão, Intermediário, Cabana Intermediária, Cabana Hobbit
e Quarto 01 a Quarto 24. Categorias comerciais de materiais históricos não substituem
esses nomes sem revisão dos comandos e migração adequada.

Ordem recomendada para chegar a um dataset utilizável:

```bash
# 0) migrações (seeds automáticos)
python manage.py migrate

# 1) superusuário
python manage.py createsuperuser

# 2) tipos de pernoite + os 24 quartos (e, com --completo, os passos 3 a 5 abaixo)
python manage.py estrutura_inicial --completo

# 3) estrutura derivada: posições de cama, sofá, colchões e estoque global de extras
python manage.py configurar_camas          # (reservas) + singleton ColchoesExtra
#   alternativa equivalente p/ camas: python manage.py popular_camas

# 4) preços aprovados por tipo e por quarto × temporada
python manage.py carregar_tarifas

# 5) vitrine do site (1 VitrineQuarto por UH de hospedagem, marca 9 destaques)
python manage.py sincronizar_vitrine
#   (venda por tipo, legado/day use): python manage.py sincronizar_quartos

# 6) dados de demonstração — opcionais, idempotentes, nesta ordem
python manage.py popular_demo        # temporadas, tarifas, categorias, produtos,
                                     # locais, contas, recados + reservas "[demo]"
python manage.py popular_lotacao     # ~80% de ocupação exercitando Loja/Caixa/Governança
python manage.py popular_manutencao --limpar
python manage.py popular_lavanderia --limpar
python manage.py popular_escala --limpar
python manage.py popular_marketing
python manage.py popular_comercial
python manage.py popular_templates_email
python manage.py popular_respostas_rapidas
python manage.py preparar_escala     # preenche setor (pelo cargo) e sexo (heurística!)
```

Sobre os caixas e a FNRH (comportamento observado ao montar um banco do zero em
20/10/2026): os seeds não acompanharam o **caixa por módulo** nem a **trava da FNRH**.

- `popular_demo` abre a sessão do módulo `nucleo`, mas os recebimentos de reserva
  exigem o caixa do módulo **Reservas** ("Você precisa do caixa de Reservas aberto");
  com os caixas abertos antes, ele falha ao tentar criar a sessão de Loja que já
  existe. Considere-o desatualizado.
- `popular_lotacao` funciona, mas o check-in é recusado pela trava da FNRH: rode com
  `FNRH_BLOQUEAR_CHECKIN=0` no ambiente. As vendas de balcão da Loja só aparecem se
  houver sessão de caixa do módulo `loja` aberta (sem ela o seed engole o erro).
- `popular_lavanderia` exige o caixa de Lavanderia aberto; `popular_escala` exige ao
  menos 6 funcionários.

Para abrir caixas, use `/crm/caixa/abrir/` com o mesmo usuário que os seeds usam.

Os seeds escolhem o operador assim: usuário `gvivan` se existir, senão o primeiro
superusuário. Logo, **crie o superusuário antes dos seeds**.

Além dos tipos/quartos, o outro cadastro **sem seed algum** é o **ponto de atendimento
do Restaurante** (`restaurante.Mesa`): tem de ser criado na tela
`/crm/restaurante/mesas/`. Os demais catálogos vêm dos seeds — `popular_lavanderia` cria
`ServicoLavanderia` + `ItemEnxoval`, `popular_escala` cria os `Turno` do plano, e
`popular_demo` cria temporadas, categorias financeiras, categorias de produto, produtos
e locais de estoque.

### 8.5 Subir

```bash
python manage.py runserver
```

- Site público: <http://127.0.0.1:8000/>
- CRM: <http://127.0.0.1:8000/crm/> (login em `/crm/entrar/`)
- Admin: <http://127.0.0.1:8000/crm/admin/>

### 8.6 MFA em dev

`MFA_OBRIGATORIO` default é `0` quando `DEBUG=1` — o local **não** trava pedindo MFA.
Para exercitar o fluxo, ponha `MFA_OBRIGATORIO=1` no `.env`: qualquer superusuário sem
`mfa_ativo` será redirecionado a `/crm/mfa/ativar/`, que mostra o QR
(`otpauth://`, emissor “CRM Vô Testa”) e os códigos de backup **uma única vez**.
Depois o login passa por `/crm/mfa/desafio/`.

### 8.7 E-mail em dev

Sem `EMAIL_HOST` no ambiente, `EMAIL_BACKEND` é o
`django.core.mail.backends.console.EmailBackend`: todo e-mail (confirmação de reserva,
boas-vindas de lead, proposta do funil) é **impresso no terminal** do `runserver`.
Para envio determinístico em testes, desligue `EMAIL_ENVIO_ASSINCRONO`.

---

## 9. Testes e qualidade

### 9.1 Organização

Os testes ficam **dentro de cada app** e são descobertos pelo runner do Django:

| Arquivo ou família | Conteúdo |
|---|---|
| `apps/nucleo/tests*.py` | Caixa, estoque, acessos, auditoria, MFA, design e componentes |
| `apps/reservas/tests*.py` | Estados, disponibilidade, conta, preços, FNRH, capacidade, relatórios e políticas |
| `apps/reservas/tests_e2e.py` | Integração de services; não é teste de navegador |
| `apps/comercial/tests*.py` | Funil, cotações, canais, LPs e campanhas |
| `apps/site/tests.py` | Motor público, vitrine e comunicações |
| `apps/site/tests_e2e.py` | Interação real com Playwright e Chromium |
| Demais apps | Regras e jornadas de cada módulo |

Não mantenha contagens ou tamanho de arquivos como garantia de cobertura. O resultado
válido é o da execução identificada pelo commit e pelo ambiente.

O único arquivo de testes de navegador é `apps/site/tests_e2e.py` (reserva no site de
ponta a ponta, calendário, home, funil — busca e arrasto —, a LP da Inauguração e o menu
lateral do CRM): importa `playwright.sync_api.sync_playwright` dentro de um `try` e marca
as classes com `@unittest.skipUnless(_PLAYWRIGHT_OK, …)` — **sem Playwright instalado
os testes são pulados, não falham**. No CI eles rodam num job próprio ("Fluxos no
navegador", em `testes.yml`, com `playwright==1.64.0` + Chromium) e com
`E2E_OBRIGATORIO=1`: lá, faltar o Playwright é erro, para o job nunca ficar verde pulando
tudo. Para habilitar localmente:

```bash
pip install playwright && playwright install chromium
```

### 9.2 Como rodar

```bash
python manage.py test                       # tudo (obrigatório antes de commit)
python manage.py test apps.reservas         # um app
python manage.py test apps.nucleo.tests     # um módulo de teste
python manage.py test apps.reservas.tests_precos  # arquivo específico
```

`pytest==9.1.1` está disponível como execução alternativa, mas **a forma padrão é
`manage.py test`** (comentário explícito em `requirements-dev.txt`).

### 9.3 O que muda sob teste

`config/settings.py` define `TESTING = "test" in sys.argv`. A partir disso:

| Setting | Sob teste |
|---|---|
| `SECRET_KEY` obrigatória em produção | checagem desligada |
| `FNRH_BLOQUEAR_CHECKIN` | forçado `False` (as classes de FNRH religam com `@override_settings`) |
| `PRECO_TAXAS_ATIVAS` | forçado `False` (não poluir os totais de conta) |
| `PAGAMENTOS_WEBHOOK_CONFIA_CORPO` | `True` (`DEBUG or TESTING`) |
| `MFAObrigatorioMiddleware` | não age |
| `LoginComLimite` | rate-limit não aplicado (evita flakiness por cache compartilhado) |

### 9.4 Lint, SAST e dependências

- **ruff** (`ruff.toml`): `target-version = py314`, `line-length = 100`,
  exclui `**/migrations/**`, `.venv` e `staticfiles`. Regras: `E4,E7,E9,F,I,UP` +
  subconjunto de alto sinal do flake8-bandit (`S105,S106,S107,S608,S301,S302,S324,S501,S602,S605,S611`).
  `per-file-ignores` solta `E501`/`S10x` em `tests.py`, `tests_e2e.py` e
  `management/commands/*.py`.
  `ruff check apps/ config/` (ou `--fix`).
- **bandit** — SAST completo: `bandit -r apps config -ll -x '*/tests.py,*/tests_e2e.py' --skip B310`.
- **pip-audit** — CVEs nas dependências.
- **detect-secrets** — contra `.secrets.baseline` (falha só em segredo **novo**).
- **semgrep** — `p/django p/python p/secrets`, **report-only** por ora.
- **pre-commit** (`.pre-commit-config.yaml`, instalar com `pre-commit install`):
  `detect-private-key`, `check-added-large-files` (1200 KB), `check-merge-conflict`,
  `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`, `check-json`,
  `detect-secrets`, `bandit`, `ruff` (só as regras de segurança).

### 9.5 CI — `.github/workflows/`

**`testes.yml`**: dispara em **push na `main` e na `dev`** e em **todo
pull request**. Sobe um serviço **PostgreSQL 16** (a trava de overbooking usa
`ExclusionConstraint`/`btree_gist`, que o SQLite não tem), instala o `requirements.txt`
com Python 3.14, confere `makemigrations --check --dry-run` e roda
`manage.py test --noinput`, além do lint. Um segundo job instala Playwright e Chromium
e roda `apps.site.tests_e2e` com `E2E_OBRIGATORIO=1`. Proteção de branch e espera de
checks pelo deploy dependem da configuração externa e precisam ser confirmadas.

**`security.yml`**: dispara em **push na `main`**, em **todo pull request** e por **cron
semanal** (segunda, 09:00 UTC). Dois jobs:

1. **`sast-deps-secrets`** (Python 3.14): `pip-audit` → `bandit` → `ruff` (regras de
   segurança) → `semgrep` (**`continue-on-error: true`**, report-only) →
   `python manage.py check --deploy --fail-level WARNING` com env sintético
   (`DEBUG=0`, SECRET_KEY dummy, `DATABASE_URL=sqlite:///ci.db`).
2. **`gitleaks`**: segredos no histórico completo (`fetch-depth: 0`).

**Limites do CI:** não calcula cobertura nem executa deploy. O job de navegador
roda Playwright; a publicação da aplicação depende da integração/configuração do
ambiente de hospedagem, não de uma etapa de deploy nestes workflows.

`.github/dependabot.yml` abre PRs semanais para `pip` (limite 5, labels
`dependencies`/`security`) e para `github-actions`.

---

## 10. Deploy e operação

### 10.1 Railway

`railway.json`:

```json
{
  "build":  { "builder": "RAILPACK" },
  "deploy": {
    "preDeployCommand": "python manage.py migrate --noinput",
    "startCommand": "python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60",
    "healthcheckPath": "/healthz/",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE"
  }
}
```

- **Migrações no pré-deploy**: rodam uma vez, antes de o container novo entrar no ar; se
  falharem, o deploy é abortado e a versão anterior segue servindo. `collectstatic` roda
  no start; seeds não rodam.
- **Gunicorn** com 2 workers × 4 threads (8 requisições simultâneas) e timeout de 60 s,
  acima do timeout do cliente HTTP dos gateways.
- **Cache compartilhado** (`CACHES`): Redis com `REDIS_URL`; sem ele, `DatabaseCache` na
  tabela `nucleo_cache` (criada pela migration `nucleo.0046`). Vale para os limites de
  tentativa e o token da Safrapay entre workers e deploys.
- **Healthcheck** em `/healthz/` (`config/urls.py`: roda `SELECT 1` e responde 503 se
  o banco não atender, para um container sem banco não substituir o saudável), isento do
  `SECURE_SSL_REDIRECT` por `SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]`, e
  `healthcheck.railway.app` está em `ALLOWED_HOSTS`.
- **Estáticos** servidos por WhiteNoise (`WhiteNoiseMiddleware` logo abaixo do
  `SecurityMiddleware`) com `CompressedManifestStaticFilesStorage` em produção e
  `CompressedStaticFilesStorage` em desenvolvimento; `STATIC_ROOT=staticfiles/`.
- **Logs** (`LOGGING` em `config/settings.py`): tudo vai para o stdout, que o Railway
  mostra nos logs do deploy. `django.request` em ERROR (500 com traceback),
  `django.security` em WARNING e o resto no nível de `LOG_LEVEL` (padrão `INFO`;
  `WARNING` nos testes). Falhas de receivers de sinais saem pelo logger
  `apps.nucleo.sinais`.
- **Publicação:** confirme repositório, branch e integração do ambiente antes do push
  autorizado. Não acione `railway up` como parte de uma atualização de documentação.

### 10.2 Mídia em Cloudflare R2

Com as cinco variáveis `R2_*` no ambiente, `USE_R2` fica `True` e o storage default
passa a S3/R2 (§7). Para levar o que já existe no disco:

```bash
python manage.py migrar_media_r2 [--dry-run]
```

Idempotente — pula o que já está no bucket. Rodar **uma vez** depois de configurar as
variáveis. Sem R2, a mídia vive no disco efêmero do Railway e **somem fotos a cada
deploy**.

### 10.3 E-mail

A configuração documentada de SMTP usa Zoho (`smtp.zoho.com:587`, TLS e senha de
app); a conta ativa não foi verificada nesta revisão. O trilho 1:1 pode ter SMTP próprio
(`EMAIL_COMERCIAL_HOST_USER`/`_PASSWORD`); vazio, sai pela conta global com
`Reply-To: comercial@` — isso evita o `553 Sender is not allowed to relay` do Zoho ao
usar um `From` diferente do login.

### 10.4 Rotinas agendadas (`apps/nucleo/management/commands/rotinas.py`)

`python manage.py rotinas --grupo frequentes|diarias [--so tarefa1,tarefa2]` chama os
comandos do grupo um a um, cada um isolado: a falha de um vai para o log
(`apps.nucleo.management.commands.rotinas`), não impede os outros e faz o comando terminar
com `CommandError`, para o Railway marcar a execução como falha. Se a falha deixou a
conexão de banco inutilizável, ela é fechada e a próxima tarefa reconecta.

**No Railway:** dois serviços de Cron a partir deste repositório, com as mesmas variáveis
do web e o arquivo de config-as-code `deploy/railway.rotinas.json` (`*/10 * * * *`) ou
`deploy/railway.rotinas-diarias.json` (`15 6 * * *`, 03h15 de Brasília), ambos com
`restartPolicyType: NEVER`.

| Comando | App | Grupo | O que faz |
|---|---|---|---|
| `expirar_reservas` | `reservas` | frequentes | Cancela pré-reservas (avulsas e de grupo) com retenção vencida. Backstop: a disponibilidade já ignora vencidas em tempo real e `criar_reserva_site` chama `expirar_vencidas()` antes de alocar. |
| `expirar_recibos_site` | `site` | frequentes | Marca como `expirada` as `site.Reserva` aguardando pagamento com prazo vencido. Era `expirar_reservas`, homônimo do de Reservas e inalcançável pelo nome (o Django resolve nomes iguais pelo primeiro app do `INSTALLED_APPS`). |
| `enviar_fnrh_pendentes` | `reservas` | frequentes | Reenvia à FNRH Digital as reservas `pendente`/`erro` (backstop do envio best-effort do check-in). |
| `enviar_campanhas_email` | `comercial` | frequentes | Dispara campanhas de e-mail agendadas cujo horário chegou (`--id N` força uma). |
| `reenviar_confirmacoes_site` | `site` | frequentes | Manda a confirmação das `site.Reserva` ativas de 10 min a 2 dias atrás que estão sem `confirmacao_enviada_em` (a thread de envio morreu ou o SMTP falhou), até 100 por rodada. |
| `reprocessar_webhooks_whatsapp` | `comercial` | frequentes | Reprocessa os `WebhookWhatsApp` não processados (com mais de 2 min, até 5 tentativas), na ordem de chegada, e apaga os processados há mais de 30 dias. Seguro porque a mensagem é única pelo `wamid`. |
| `reenviar_emails_pendentes` | `comercial` | frequentes | Reenvia `EnvioEmail` (fora de campanha, últimos 2 dias) pendente há mais de 10 min ou com erro e menos de 3 tentativas. O conteúdo fica guardado no `EnvioEmail` só até o e-mail sair. |
| `marcar_no_shows` | `reservas` | diarias | No-show automático, se ligado na Tabela de Preços (`ConfiguracaoReservas.no_show_automatico_noites`: 0 desligado, 1 = madrugada seguinte à entrada, 2 e 3 = com 1 ou 2 dias de tolerância). Confirmada sem check-in vira "não compareceu" pelo usuário de sistema `_auditoria`, com trava de linha; não mexe em dinheiro. Primeiro do grupo, antes do fechamento. |
| `fechar_dia` | `reservas` | diarias | Fechamento do dia de ontem (auditoria noturna): grava o `FechamentoDiario` imutável — ocupação, chegadas, saídas, no-shows, receita pela competência e saldo em aberto. Antes do backup, para ele já levar o fechamento. Idempotente; `--dia AAAA-MM-DD` fecha um dia que ficou para trás. |
| `enviar_conversoes_pendentes` | `comercial` | diarias | Reprocessa conversões de mídia pendentes (idempotente, best-effort). |
| `backup_banco` | `nucleo` | diarias | Cópia do banco para fora do Railway (ver 10.6). |
| `sincronizar_gastos_midia` | `comercial` | diarias | Puxa o gasto das plataformas para as campanhas com `id_externo` (`--dias N`). No-op com `MIDIA_GATEWAY=simulado`. |
| `purgar_trilha` | `nucleo` | diarias | Apaga da trilha o que passou de `TRILHA_RETENCAO_DIAS` (0 = guarda sempre) e registra a própria purga. |
| `gerar_arrumacoes` | `governanca` | diarias | Uma arrumação para cada quarto em que o hóspede continua (quem sai já tem a faxina do check-out). Idempotente. |
| `enviar_kit_contingencia` | `reservas` | diarias | Envia a folha operacional do dia para `KIT_CONTINGENCIA_EMAILS`; vazio = não envia. |

`enviar_campanha_whatsapp` (`comercial`) fica fora: é disparo manual de um template para
uma lista de leads, com pausa e limite, respeitando opt-in.

**Monitor ("dead man's switch").** Com `ROTINAS_MONITOR_FREQUENTES` /
`ROTINAS_MONITOR_DIARIAS` definidas (URL de um check do Healthchecks.io ou compatível),
cada execução do grupo inteiro avisa o começo (`POST <url>/start?rid=…`), o fim
(`POST <url>?rid=…`, com uma linha por tarefa no corpo: "backup_banco: ok em 3,1s") e a
falha (`POST <url>/fail?rid=…`, com "FALHOU (OperationalError)" — só o tipo do erro, nunca
a mensagem, que pode ter dado de hóspede). O mesmo `rid` liga começo e fim. Rodar só
algumas tarefas à mão (`--so`) não avisa; monitor fora do ar (timeout de 10 s) vira aviso
no log e a rotina segue. No Healthchecks: frequentes com período de 10 min e tolerância de
10 min; diárias com o cron `15 6 * * *` (UTC) e tolerância de 1 h.

### 10.5 Comandos de pós-deploy / operação

| Comando | Quando |
|---|---|
| `estrutura_inicial` | Banco novo: cria os tipos de quarto e os 24 quartos; com `--completo`, roda também `configurar_camas`, `carregar_tarifas` e `sincronizar_vitrine`. Idempotente. |
| `sincronizar_vitrine` | **Rodar no deploy** quando houver quarto novo: cria a `VitrineQuarto` que falta e marca os 9 destaques da home. O `migrate` roda sozinho; **este seed não**. |
| `sincronizar_quartos` | Sincroniza os cards por **tipo** (venda por tipo / day use). |
| `migrar_media_r2` | Uma vez, após configurar o R2. |
| `carregar_tarifas` | Quando a tabela de preços aprovada mudar (idempotente). |
| `configurar_camas` / `popular_camas` | Quando a configuração física de camas mudar. |
| `registrar_numero_whatsapp` | Registro do número na Cloud API. |
| `reconciliar_capacidades`, `relatorio_telefones_incompletos` | Diagnóstico de dados. |
| `zerar_funil`, `sanear_demo`, `recentrar_demo`, `limpar_nomes_quartos` | Limpeza de dados de demonstração — **destrutivos, nunca em produção sem conferir**. |
| `preparar_escala` | Seed de setor/sexo dos funcionários (o sexo é **heurística pelo nome** — revisar na tela de Funcionários). |

### 10.6 Backup e restauração (`apps/nucleo/management/commands/backup_banco.py`)

Duas camadas:

1. **Railway** — backup gerenciado do Postgres e PITR (ligar no painel; a janela de
   recuperação só começa a contar depois de ligado).
2. **`backup_banco`**, no grupo `diarias` do `rotinas` — cópia fora do Railway:
   - **formato:** `pg_dump --format=custom` quando o executável existe e aceita a versão do
     servidor; senão `dumpdata --natural-foreign --natural-primary` de todos os modelos
     (menos contenttypes, permissões, sessões e log do admin), em JSON compactado;
   - **destino:** o bucket R2 da mídia, prefixo `backups/AAAA/MM/`, quando as variáveis
     `R2_*` existem; senão `BACKUP_DIR`. Sem nenhum dos dois, `--destino auto` só avisa
     (o disco do container é apagado a cada deploy);
   - **retenção:** apaga do mesmo destino o que tiver mais de `--manter-dias` (padrão 30).

Restauração:

```bash
# .dump (pg_dump)
pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" crm-AAAAMMDD-HHMMSS.dump
# .json.gz (dumpdata), num banco vazio
python manage.py migrate
python manage.py loaddata crm-AAAAMMDD-HHMMSS.json.gz
```

Ensaie a restauração num banco separado (ex.: um Postgres local) antes de precisar dela.

---

## 11. Design system (“Lampião”)

**Premissa fixa** (`CLAUDE.md`): toda tela nova do CRM **nasce** no design system. Nunca
criar estilo paralelo nem hard-codear cor, raio ou sombra.

### 11.1 Tokens — `static/css/app.css` (`:root`)

| Grupo | Tokens |
|---|---|
| Marca | `--noturno` `#04151F`, `--noturno-2`, `--noturno-3`, `--madeira`, `--lampiao` `#E2A84A`, `--lampiao-claro`, `--pergaminho`, `--musgo` |
| Canvas | `--canvas` `#F7F5F1` (branco-quente), `--superficie` `#FFFFFF`, `--superficie-2`, `--papel`, `--papel-carta` |
| Tinta e fios | `--tinta`, `--tinta-suave`, `--fio`, `--fio-forte` |
| Semânticas (com `-bg`) | `--sucesso`, `--alerta`, `--perigo`, `--info`, `--andamento` |
| Elevação | `--sombra-1` (elementos pequenos), `--sombra-2`, `--sombra-3`, `--glow`, `--sombra-cartao` (float suave de cartão) |
| Raio | `--raio-p` 10px, `--raio` 14px, `--raio-g` 20px |
| Tipografia | `--fonte-titulo` (Fraunces), `--fonte-ui` (Hanken Grotesk), `--fonte-marca` (Rosaline, `@font-face` local), `--fonte-mono` (IBM Plex Mono) |
| Layout | `--sidebar-w` (vale agora: `--sidebar-w-aberta` 258px ou `--trilho-w` 72px), `--trilho-centro` (35,5px, o x de todo ícone do menu nos dois estados) e `--sidebar-ico-x`, `--alvo` (30px no mouse, 44px no dedo — botão de recolher e Sair), `--sidebar-topo-h` 116px (o topo do menu tem a mesma altura aberto e recolhido), `--topbar-h` 60px, `--vao-2-1` (vão do `.colunas-2-1`) |

**Para mudar o “look” global, mexa nos tokens** — propaga para tudo.

### 11.2 Componentes-base

- `.cartao` / `.cartao-el` — cartão com hairline + float; `.cartao-topo`,
  `.cartao-descricao`, `.cartao-atalho`.
- `.tabela` / `.quadro` — cabeçalho em maiúsculas discretas, hairlines, hover na linha,
  `.tabela-rol` para rolagem horizontal, `.vazio` para estado vazio.
  **Coluna de número/dinheiro leva `.num` no `<th>` E no `<td>`.**
- `.botao-primario` (dourado), `.botao-neutro`, `.botao-perigo`, `.botao-mini` — nunca
  sublinhados, todos com `:active`.
- `.selo` + variantes (`.selo-ok`, `.selo-ativo`, `.selo-neutro`, `.selo-alerta`,
  `.selo-limpa`, `.selo-suja`, `.selo-em_limpeza`, `.selo-inspecionada`,
  `.selo-tipo-fisica`/`-juridica`) — status com bolinha.
- `.kpi` / `.kpi-destaque` — métrica.
- `.campo`, `.form-cartao`, `.form-inline` — formulários com foco dourado global.
- `.letreiro` — rótulo MAIÚSCULO pequeno com tracking.
- `.chip-limpeza`, `.mapa`, `.paleta-*`, `.toast*`, `.modal-*` — componentes de tela.

**Tipografia (craft):** números sempre `font-variant-numeric: tabular-nums` (já aplicado
em `.tabela`, `.kpi-valor`, `.indicador-valor`, `.mapa`, `.mono-num`); números grandes
com `letter-spacing: -.02em`; rótulos em maiúsculas discretas e tom suave; hierarquia
por peso **e** tamanho.

**Interação:** feedback imediato no toque (`:active`), hover sutil, foco dourado global
nos inputs, e `prefers-reduced-motion` respeitado (cross-fade em vez de slide/spring; a
curva da casa é `cubic-bezier(.2,.8,.2,1)`).

### 11.3 App shell — `templates/base.html`

```
.app
├── .sidebar-backdrop               (mobile)
├── aside.sidebar
│   ├── .sidebar-topo               logotipo + botão recolher (⌘\)
│   ├── button.acao-topo            "Nova reserva" (só com módulo Reservas)
│   ├── nav[hx-boost]               grupos por permissão (§4.6); ícones de componentes/icone_modulo.html
│   └── .sidebar-rodape             avatar + link do MFA (selo "MFA off") + logout (POST)
└── .main
    ├── header.topbar               menu mobile + botão de busca global com <kbd>⌘K</kbd>
    └── main#conteudo.conteudo      {% block conteudo %}
.toasts#toasts                      mensagens do Django viram notificações
#paleta.paleta-overlay              paleta de comandos (dialog)
#modal-reserva.modal-overlay        modal de nova reserva (carregado por fetch)
```

- `<head>`: Google Fonts por `<link>` (em paralelo, não `@import`), `css/app.css?v=mob4`,
  `js/fluid.js`, **HTMX 2.0.4** e **Alpine 3.14.8** (de `static/vendor/`, `defer`).
- A navegação da sidebar usa `hx-boost="true"` com
  `hx-target="#conteudo" hx-select="#conteudo" hx-swap="outerHTML show:window:top transition:true"`.
- **Troca de página**: só a navegação do menu usa View Transition (`transition:true`); a
  transição global do HTMX (`globalViewTransitions`) fica desligada — ela animava cada
  troca parcial e a página inteira, menu incluído. O app.css dá nome próprio a
  `.sidebar` (`menu`), `.topbar` (`topo`) e `.conteudo` (`conteudo`): menu e topo trocam
  sem animação e só o conteúdo faz o cross-fade. `@view-transition { navigation: auto }`
  estende a mesma troca à navegação comum, fora de `prefers-reduced-motion`.
- **Dicas**: `static/js/dicas.js` desenha um balão fixo (`#dica-flutuante`) para todo
  `[data-dica]` — centrado no que se vê do elemento (ou no ponteiro, num elemento largo),
  em cima quando cabe e embaixo quando não, sempre dentro da tela. Mostra no mouse, no
  foco do teclado e, no toque, por 2,5 s. No `.porta` do corredor vira cartão. No trilho,
  `rotularSidebar()` troca o `title` dos itens por `data-dica` com `data-dica-lado="direita"`.
- **Largura**: `.conteudo` para em `--conteudo-max` (1760 px) e centra; acima de 1800 px a
  busca da barra do topo acompanha o começo do conteúdo. `.conteudo-largo` (bloco
  `conteudo_classe`) tira o limite — mapa de reservas e calendário do Marketing.
- **Toasts**: as `messages` do Django são renderizadas como `.toast toast-<tag>`; a
  função JS `toast(msg, tipo)` cria novos; saída automática em 5 s.
- **Feedback de toda ação HTMX**: barra de progresso no topo (`#barra-progresso`) enquanto
  houver requisição em voo, o elemento que disparou fica com aparência de ocupado
  (`.htmx-request`), e sai um toast de erro quando o servidor responde 4xx/5xx (403 vira
  "sem permissão"), quando a conexão cai ou quando estoura o tempo. Sem isso o HTMX não
  avisa nada nesses casos e a pessoa clica de novo.
- **Paleta de comandos**: lista estática de comandos (“Ir para …”, montada dentro dos
  mesmos `{% if user|pode_area %}`) + busca remota com debounce de 160 ms em
  `busca_global`; navegação com ↑/↓/Enter.
- **Atalhos de teclado** (handler único, ignora quando o foco está em input/textarea/select):

| Tecla | Ação |
|---|---|
| `⌘K` / `Ctrl+K` | abre a paleta |
| `/` | abre a paleta |
| `⌘\` / `Ctrl+\` | recolhe/expande a sidebar |
| `Esc` | fecha paleta, modal e sidebar mobile |
| `↑` `↓` `Enter` | navegam/ativam na paleta aberta |
| `N` | nova reserva |

- Ícones são **SVG inline** (sem sprite nem icon font); no rail recolhido o ícone é o
  único identificador, por isso cada módulo tem o seu em `componentes/icone_modulo.html`.
- **Trilho (menu recolhido)**: é o estado padrão (`localStorage.sidebar` diferente de
  `aberta`) e é o menu aberto recortado: cada peça no mesmo x e na mesma altura nos dois
  estados, rótulos e títulos de grupo no fluxo só com opacidade (seguem na árvore de
  acessibilidade; nunca `display:none`), a `.sidebar` com `overflow: hidden` como
  cortina, janelas próprias para o logotipo (`.marca-janela`) e para nome + cápsula
  (`.usuario-texto`), e o botão de recolher e o Sair deslizando com os tokens de
  movimento. Cada item traz `title` no template (vale sem JS); o `rotularSidebar()` o
  troca pela dica da casa, que só aparece no trilho.
  Toda regra `.app.recolhida …` mora num único `@media (width > 820px)` e só mexe em
  opacidade, cor, giro e posição — `test_trilho_so_existe_no_desktop` e
  `test_trilho_nao_redesenha_so_esconde_e_desliza` reprovam o contrário.
- **Gaveta (≤ 820 px)**: abre sempre inteira, qualquer que seja a preferência do
  desktop. Fechada, `visibility:hidden` a tira da ordem de tabulação; aberta, é diálogo —
  `abrirSidebarMobile()` guarda o foco, o Tab circula dentro dela (`caixaAberta()`),
  `body.sem-rolagem` trava a página e `fecharSidebarMobile()` devolve o foco. Fecha no véu,
  no Esc e ao navegar (`htmx:pushedIntoHistory`).
- **Combo de pessoa/quarto**: `posicionar()` abre a lista para cima quando não cabe
  embaixo (`.combo-acima`); a lista nunca passa de 46% da altura da tela.

### 11.4 Componentes compartilhados (`templates/componentes/`)

| Include | Parâmetros | Uso |
|---|---|---|
| `combo_pessoa.html` | `dados`, `dados_id`, `campo`, `placeholder`, `valor_id` | Combobox com busca instantânea e grupos sticky (Hóspedes → Prospecção → Clientes avulsos → Agências e empresas → Funcionários → Fornecedores). Dados de `nucleo.seletores.pessoas_agrupadas` via `json_script`; renderiza um `<input type=hidden name=…>` (o `Form` do Django valida igual). Componente Alpine `comboPessoa` registrado global em `base.html`. |
| `combo_quarto.html` | `dados`, `dados_id`, `campo`, `placeholder`, `valor_id`, `data-url` | Mesmo visual, seções por **ala**; refaz a lista de quartos livres por `fetch` quando as datas do form mudam. |
| `icone_modulo.html` | `codigo` | SVG do módulo para a sidebar/dashboard. |
| `paginacao.html` | `pagina` | Paginador de lista: a view chama `apps.nucleo.paginacao.paginar(request, consulta, por_pagina=50)` (lê `?pagina=`, desempata a ordem pelo `pk`, número inválido vira a primeira página e além do fim vira a última) e o template inclui o componente logo abaixo da tabela. Busca e filtros vão junto pela tag `querystring` do Django; com uma página só, não aparece. Totais e contadores da tela continuam somando a consulta inteira, não a página. |
| `consentimento.html` | — | Aviso de cookies (LGPD) do site, das páginas de captação e das LPs; as tags de medição ficam `type="text/plain" data-consentimento` até o "Aceitar". Classes com prefixo próprio (`aviso-cookies*`): o HTML das LPs não pode reusar nenhuma (teste `test_aviso_nao_reusa_classe_das_lps`). |
| `copiar.html` (tag `{% copiar %}`) | `texto`, `rotulo`, `recado`, `telefone`, `mostrar` | "Copiar" + "Enviar pelo WhatsApp" para tudo o que a equipe manda a alguém (link de pagamento, Pix copia-e-cola, portal, pré check-in, página de captação). O clique é do `static/js/copiar.js` (ouvinte delegado, serve ao que o HTMX troca e ao que o Alpine escreve): Clipboard API e plano B por `execCommand` onde ela não existe (o `http://` da rede local); o rótulo e o `aria-label` viram "Copiado" por 2 s. Sem `recado`, não há WhatsApp; o telefone é normalizado por `nucleo.compartilhar.telefone_whatsapp` (55DDDNÚMERO) e, sem telefone legível, o WhatsApp abre para escolher o contato. |
| `cupom.html` | `cupom` (dict: `titulo`, `origem`, `meta`, `itens`, `subtotal`, `desconto`, `total`, `pagamento`, `aviso`, `voltar`), `imprimir` | Cupom de 80 mm para impressora térmica pelo navegador (Loja, Restaurante, Lavanderia). Página própria, sem o app-shell. |

**Impressão.** O `@media print` do `app.css` tira o app-shell de qualquer tela mandada para a
impressora, e o `@page` geral é A4 retrato (o kit de contingência). O cupom tem página
nomeada (`@page cupom`): 80 mm de largura, margem zero, e a altura é reescrita pelo script
do componente com a altura do próprio cupom antes de imprimir — a bobina corta logo depois
do rodapé. Sem `size` próprio, a página do cupom herdaria o A4 e o driver da térmica
encolheria a folha inteira para caber em 80 mm (teste `CupomTermicoTests`). Térmica só
imprime preto: o cupom usa só `--tinta` e fios tracejados.

### 11.5 O kit “eleg” — `templates/comercial/_estilo_elegante.html`

Kit compartilhado (bloco `<style>`) que estende os tokens para telas de
painel/lista/detalhe. **Padrão para dashboard/lista/detalhe:** envolver a tela em
`<div class="eleg">` e incluir o kit:

```django
{% include "comercial/_estilo_elegante.html" %}
<div class="eleg">
  <div class="kpis">
    <div class="kpi"><span class="n">12</span><span class="l">Reservas</span></div>
    <div class="kpi kpi-destaque">…</div>
  </div>
  <div class="cartao-el">…</div>
  <div class="quadro"><table class="tabela">…</table></div>
</div>
```

Herda botões padronizados (`.botao-primario`/`.botao-neutro`/`.botao-mini` com `:active`
em `scale(.97)`), `.kpis`/`.kpi`/`.kpi-destaque` (número `clamp()` com tracking negativo
e `tabular-nums`), `.cartao-el`, `.quadro`, `.rot`, `.eleg-acoes`, `.eleg-intro`. Usa
`--hairline: var(--fio)` e `--sombra: var(--sombra-cartao)`.

### 11.6 Tailwind no site público

Só o **site** usa Tailwind, em **build estático** (não o Play CDN):

```bash
npx tailwindcss@3 -i tailwind.src.css -o apps/site/static/site/css/tailwind.css --minify
```

`tailwind.config.js` varre `apps/site/templates/**/*.html` e
`apps/site/static/site/js/**/*.js`, e estende o tema com a paleta da marca
(`noturno`, `madeira`, `lampiao`, `pergaminho`, `musgo`) e a fonte `Neco`.
**O CRM não usa Tailwind** — e o site não usa `app.css`.

### 11.7 Regras para uma tela nova do CRM

1. `{% extends "base.html" %}` e preencher `{% block titulo %}` e `{% block conteudo %}`.
2. Painel/lista/detalhe → `<div class="eleg">` + `{% include "comercial/_estilo_elegante.html" %}`.
3. Reusar `.cartao`/`.cartao-el`, `.quadro`/`.tabela`, `.selo*`, `.kpi*`, `.botao-*` —
   nunca criar classes paralelas.
4. Toda coluna de número/dinheiro: `.num` no `<th>` **e** no `<td>`; dinheiro via
   `{{ valor|intcomma_brl }}`.
5. Cor/raio/sombra **só por token**. Mudança global = mexer no `:root` de `app.css`.
6. Mensagens via `django.contrib.messages` (viram toasts automaticamente).
7. Entrada de pessoa/quarto: usar os combos de `templates/componentes/`. Lista que
   pode crescer: `paginar()` na view + `componentes/paginacao.html` — nunca cortar em
   `[:200]`.
8. Ícone novo: adicionar o `{% elif codigo == '…' %}` em `componentes/icone_modulo.html`.

---

## 12. Como criar um novo módulo

Receita extraída de como `apps/manutencao` e `apps/lavanderia` estão ligados hoje.

### Passo 1 — criar o app

`python manage.py startapp meumodulo apps/meumodulo`, e em `apps/meumodulo/apps.py`
definir `default_auto_field`, `name = "apps.meumodulo"`, `label = "meumodulo"` e
`verbose_name`. **Só se houver receivers**, acrescentar
`def ready(self): from . import receivers  # noqa: F401` (como
`GovernancaConfig`/`LavanderiaConfig`/`ComercialConfig`).

### Passo 2 — `INSTALLED_APPS`

`config/settings.py` — acrescentar `"apps.meumodulo"` ao bloco “Módulos do sistema”.
A entrada curta basta (o Django acha o único `AppConfig` do módulo, inclusive com
`ready()`, como em `governanca`/`lavanderia`/`marketing`); use o caminho completo do
`AppConfig` se houver mais de um, como `apps.comercial.apps.ComercialConfig`.

### Passo 3 — catálogo de módulos

`apps/nucleo/modulos.py`:

1. Novo membro em `Modulo` (código ≤ 20 caracteres — é o `max_length` de
   `ModuloContratado.codigo`).
2. Entrada em `APRESENTACAO` com `grupo`, `ordem`, `descricao` e `url_name` (sem
   `url_name` o módulo aparece como “em construção”).
3. Se depender de outro módulo, entrada em `DEPENDENCIAS`.

### Passo 4 — migrações

```bash
python manage.py makemigrations meumodulo
```

A `0001_initial` normalmente depende de `("nucleo", "0010_seed_almoxarifado")` e de
`migrations.swappable_dependency(settings.AUTH_USER_MODEL)` — veja
`apps/manutencao/migrations/0001_initial.py`.

**Alterar o enum `Modulo` muda as `choices` de `ModuloContratado.codigo`** → gera também
uma `AlterField` em `nucleo` (ex.: `nucleo/0035_alter_modulocontratado_codigo.py`).

**Migração de dados para ativar o módulo** (padrão de
`apps/auditoria/migrations/0001_ativar_modulo.py`):

```python
def ativar(apps, schema_editor):
    ModuloContratado = apps.get_model("nucleo", "ModuloContratado")
    ModuloContratado.objects.get_or_create(codigo="meumodulo", defaults={"ativo": True})

def desativar(apps, schema_editor):
    apps.get_model("nucleo", "ModuloContratado").objects.filter(codigo="meumodulo").delete()

class Migration(migrations.Migration):
    dependencies = [("meumodulo", "0001_initial"), ("nucleo", "<última>")]
    operations = [migrations.RunPython(ativar, desativar)]
```

### Passo 5 — rotas

`apps/meumodulo/urls.py` com `app_name = "meumodulo"` (**sempre** namespaced — a sidebar
usa `request.resolver_match.namespace == m.codigo` para marcar o item ativo, então
**o `app_name` deve ser igual ao código do módulo**).

Em `config/urls.py`, dentro do bloco `/crm/`:

```python
path("crm/meumodulo/", include("apps.meumodulo.urls")),
```

### Passo 6 — views com decorators

```python
from apps.nucleo.modulos import Modulo
from apps.nucleo.permissoes import requer_gerencia, requer_modulo

@requer_modulo(Modulo.MEUMODULO)
def painel(request): ...

@requer_modulo(Modulo.MEUMODULO)
@requer_gerencia                      # ações sensíveis: cancelar, estornar, reabrir
def cancelar(request, pk): ...
```

Padrão do `manutencao/views.py`: importar models **do núcleo** (`UH`, `Pessoa`),
`Modulo`/`permissoes`, `nucleo.seletores` para os combos, e falar com o próprio
`services`.

### Passo 7 — `services.py` como interface pública

Toda regra fica aqui, não na view. Para cobrar, chamar
`nucleo.models.receber_no_caixa(..., modulo=Modulo.MEUMODULO)` (gaveta própria) e/ou
`reservas.services.lancar_na_conta`, sempre degradando com `modulo_ativo()` se o módulo
parceiro estiver inativo. Para estoque, só pelas funções do motor. Toda ação sensível
chama `registrar_auditoria(...)` com motivo.

### Passo 8 — menu

Nada a fazer **se** o módulo tem `url_name` no `APRESENTACAO`: `menu_modulos` já o
coloca no grupo certo. Falta só o ícone: adicionar o `{% elif codigo == 'meumodulo' %}`
em `templates/componentes/icone_modulo.html` (sem isso cai no genérico do `{% else %}`).
Para itens extras (como “LP Páginas” e “Respostas rápidas” do Comercial), editar
`templates/base.html`.

### Passo 9 — hook de pendências da Auditoria

Expor em `apps/meumodulo/services.py`:

```python
def pendencias_auditoria():
    return [{
        "area": "Meu Módulo",
        "tipo": "algo_vencido",
        "gravidade": "alta",      # alta | media | baixa
        "descricao": "…",
        "url": _url("meumodulo:detalhe", obj.pk),
    }]
```

E registrar o par `(Modulo.MEUMODULO, "apps.meumodulo.services")` na lista `donos` de
`apps/auditoria/services.py`. `varrer()` só chama módulos ativos e envolve cada
chamada em `try/except` com log — uma falha não derruba a varredura.
Hoje expõem o hook: `reservas`, `manutencao`, `restaurante`, `lavanderia`, `fiscal`,
`comercial`.

### Passo 10 — relatórios (opcional)

Escrever o builder `rel_meumodulo(inicio, fim)` em `apps/relatorios/services.py`
(devolvendo `{"kpis": [...], ...}`) e registrar no dict `RELATORIOS` com `nome`,
`grupo` (“Consolidados” ou “Por módulo”), `builder` e `modulo` — `disponiveis()` esconde
automaticamente quando o módulo está inativo. Opcionalmente, um
`faturamento_periodo(inicio, fim)` no `services` do módulo, como fazem Loja,
Restaurante e Lavanderia.

### Passo 11 — admin, templates, seed e testes

- `apps/meumodulo/admin.py` — registrar os models que a gerência precisa ver.
- `templates/meumodulo/` — telas no design system (§11.7).
- `apps/meumodulo/management/commands/popular_meumodulo.py` — seed idempotente, com
  `--limpar`, no padrão de `popular_manutencao`/`popular_lavanderia`.
- `apps/meumodulo/tests.py` — `TestCase` ativando o módulo no `setUp`
  (`ModuloContratado.objects.update_or_create(codigo=…, defaults={"ativo": True})`) e
  cobrindo **obrigatoriamente** regras de dinheiro e de disponibilidade.

### Passo 12 — sinais, se precisar conversar com outro módulo

- Emitir: `apps/meumodulo/signals.py` com `Signal()` documentando os kwargs; enviar no
  service com `apps.nucleo.sinais.emitir(sinal, sender=..., **dados)`, nunca com
  `send()` direto: um receiver que falhe não pode desfazer a operação (§5.2).
- Ouvir: `apps/meumodulo/receivers.py` com `@receiver(...)` por fora e
  `@receptor_isolado` logo abaixo, **sempre** checando `modulo_ativo(Modulo.MEUMODULO)` no
  começo, e `from . import receivers` no `ready()`.

### Checklist de arquivos a tocar

```
apps/meumodulo/__init__.py  apps.py  models.py  services.py  views.py  urls.py
apps/meumodulo/admin.py     tests.py  [signals.py] [receivers.py]
apps/meumodulo/migrations/0001_initial.py
apps/meumodulo/migrations/0002_ativar_modulo.py
apps/meumodulo/management/commands/popular_meumodulo.py
config/settings.py                         → INSTALLED_APPS
config/urls.py                             → path("crm/meumodulo/", include(...))
apps/nucleo/modulos.py                     → Modulo + APRESENTACAO + DEPENDENCIAS
apps/nucleo/migrations/00XX_alter_modulocontratado_codigo.py
apps/auditoria/services.py                 → lista `donos`
apps/relatorios/services.py                → RELATORIOS (opcional)
templates/componentes/icone_modulo.html    → ícone SVG
templates/meumodulo/*.html
templates/base.html                        → só se houver item extra de menu
```

---

## 13. Glossário

| Termo | Significado neste sistema |
|---|---|
| **UH** | Unidade Habitacional = o quarto físico. Model `nucleo.UH`; 24 de pernoite (`Quarto 01..24`) + as de day use (`DAY-0N`). |
| **TipoUH** | Categoria de quarto com tarifa base e modalidade (`hospedagem` \| `day_use`). Model `nucleo.TipoUH`: “Padrão”, “Intermediário”, “Cabana Intermediária”, “Cabana Hobbit”, “Dia na Pousada”. |
| **Ala** | Localização oficial do quarto, derivada do número (`nucleo/alas.py`): Embaixo da Recepção (01–02), Corredor Engenhocas (03–09), Corredor Histórias (10–15), Condado dos Hobbits (16–24). |
| **Posição de cama** | `nucleo.PosicaoCama`: espaço físico de cama no quarto. 1 posição = 2 pessoas, independente da montagem (casal ou dois solteiros). Mais de uma posição = quarto “duplo”/de dois cômodos. |
| **Diária** | Preço de uma noite. Vem de `reservas.services.tarifa_da_unidade(uh, dia)`, com precedência: `TarifaUnidade` da temporada → `UH.tarifa_override` → tipo × `ACRESCIMO_TARIFA_DUPLO` → `Tarifa` do tipo × classificação → `TipoUH.tarifa_base`. |
| **Temporada** | Faixa do calendário tarifário com classificação (baixa, média, alta, super alta, feriado) e dias da semana aplicáveis. Model `nucleo.Temporada`. |
| **Day use / Dia na Pousada** | Modalidade sem pernoite: mesma reserva, conta e consumo do CRM. `TipoUH.modalidade = day_use` + UHs `DAY-0N`, fora do mapa dos 24. |
| **Folio / conta** | A conta da hospedagem: `reservas.ContaHospedagem` + `LancamentoConta` (diárias, consumos, serviços, descontos) + `PagamentoConta`. O check-out exige saldo zerado. |
| **Natureza fiscal** | SERVIÇO (diária, serviços → NFS-e/ISS) × CONSUMO (produto → NF-e/NFC-e/ICMS). Enum `nucleo.NaturezaFiscal`; obrigatória em `LancamentoConta` e em `Produto`. |
| **Pré-reserva** | Estado que **segura** o quarto sem confirmação. Vinda de canal, nasce com `expira_em = now + RESERVA_RETENCAO_MINUTOS`. |
| **Retenção** | (a) os minutos que a pré-reserva de canal segura o quarto; (b) no cancelamento, o percentual retido (`CANCELAMENTO_RETENCAO_PCT`) depois da janela de arrependimento. |
| **Sinal** | Adiantamento que confirma a reserva. `pagamentos.Cobranca` com finalidade `SINAL`; pago → `reservas.confirmar_reserva` (e, no funil, ganha a oportunidade). |
| **Adiantamento** | Valor recebido antes do check-in, atrelado à reserva e creditado na conta. Model `reservas.Adiantamento`. |
| **Antioverbooking** | `ExclusionConstraint` do PostgreSQL (`reserva_sem_overbooking`, extensão `btree_gist`): duas reservas em estado ativo (`pre_reserva`, `confirmada`, `hospedada`) não podem sobrepor `daterange(checkin, checkout)` na mesma UH. A noite do check-out fica livre. |
| **Sessão de caixa** | `nucleo.SessaoCaixa`: gaveta física de um operador **em um módulo**. Uma aberta por operador × módulo (constraint). |
| **Conferência cega** | Fechamento em que o operador informa o dinheiro contado **sem ver** o esperado; o sistema calcula `diferenca = contado − esperado`. `SessaoCaixa.fechar()`. |
| **Sangria / reforço** | Retirada / aporte de dinheiro no caixa (ambos em dinheiro). Tipos de `MovimentoCaixa`. |
| **Estorno** | Movimento inverso de um recebimento (total ou parcial), com motivo obrigatório, referência ao original e auditoria. Nunca `UPDATE`/`DELETE`. Exige gerência na view. |
| **Kardex** | O livro-razão de estoque: `nucleo.MovimentoEstoque`, imutável, com quantidade sinalizada (positiva entra, negativa sai). Saldo = soma. |
| **Custo médio ponderado** | `Produto.custo_medio`, recalculado a cada `registrar_entrada` sob trava de linha. Saídas baixam por ele. |
| **FNRH** | Ficha Nacional de Registro de Hóspedes (Min. do Turismo/Embratur, Lei 11.771) — uma por hóspede (titular + acompanhantes). Model `reservas.FichaFNRH`; trava de check-in por `FNRH_BLOQUEAR_CHECKIN`. |
| **BOH** | Boletim de Ocupação Hoteleira: agregado mensal por procedência (UF/país), motivo da viagem, meio de transporte e sexo + ocupação (UH-noites, taxa, permanência média). `reservas.services.boh_mensal(ano, mes)`, tela `reservas:boh` com export CSV. |
| **Área-core** | Permissão do núcleo (não é módulo): `Area` em `nucleo/areas.py`, concedida em `Usuario.areas`, checada por `@requer_area`. |
| **Módulo contratado** | `nucleo.ModuloContratado`: a ativação por cliente. Menus/permissões consultam `modulo_ativo()`. |
| **Degradação graciosa** | Um módulo funciona sem os opcionais: a Loja sem Reservas só vende no balcão; os receivers só agem se o módulo estiver ativo. |
| **Gateway plugável** | Integrador externo escolhido por setting, com implementação `simulado` como default (§5.3). |
| **Trilha de auditoria** | `nucleo.TrilhaAuditoria`, append-only: quem, quando, o quê, de onde e (quando cabe) por quê. Alimentada por signals automáticos + chamadas explícitas a `registrar_auditoria`. |
| **Logbook** | Recados do turno: tópicos com conversa e ciclo aberta → em andamento → resolvida. Models `EntradaLogbook`/`ComentarioLogbook`. |
| **Lampião** | Nome do design system do CRM (tokens + componentes em `static/css/app.css`). |
| **eleg** | Kit de estilo elegante (`templates/comercial/_estilo_elegante.html`) para telas de painel/lista/detalhe. |
| **Vitrine** | `site.VitrineQuarto` (OneToOne → UH): camada de marketing do quarto no site (foto, tour 360°, descrição, nota, destaque, ordem). Editada no form de quarto do CRM; seed por `sincronizar_vitrine`. |
| **Colchão extra / berço** | Recursos **globais** e limitados: `reservas.ColchoesExtra` e `reservas.BercoEstoque` (singletons), reservados por noite. |
| **Ponto de atendimento** | `restaurante.Mesa` — mesa, guarda-sol ou bar. **Não há seed**: são cadastrados na tela `restaurante:mesas`. |
| **Enxoval / rouparia** | `lavanderia.ItemEnxoval` + `MovimentoEnxoval`: livro-razão imutável por estado (limpa / em uso / suja / lavando), com `por_faxina` recolhido ao concluir a faxina. |
| **OS** | Ordem de serviço de Manutenção (`manutencao.OrdemServico`): corretiva/preventiva, bloqueia o quarto (`UH.status = BLOQUEADA`), e ao concluir libera e emite `reparo_concluido`. |
