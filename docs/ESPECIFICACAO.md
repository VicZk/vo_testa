# Especificação — CRM/PMS Pousada Vô Testa

**Versão documental: 1.0 · revisão em 21/10/2026.**
Esta especificação descreve o código publicado da fork `VicZk/vo_testa`.
O [Estado atual](ESTADO_ATUAL.md) identifica a base revisada, as diferenças locais
e os limites das integrações. A especificação de julho/2026 fica preservada no
histórico Git; suas propostas não devem ser tratadas como funcionalidades prontas.

## 1. Visão geral

Sistema integrado para a Pousada Vô Testa, em Itá/SC, cobrindo hospedagem,
day use, restaurante, loja, lavanderia, governança, manutenção, equipe, financeiro,
comercial, marketing e relacionamento durante a estadia.

A configuração inicial usa 24 quartos de pernoite e quatro unidades ativas de day
use. Há oito registros históricos de day use; `DAY-05` a `DAY-08` foram inativados.
Quatro tipos técnicos de pernoite alimentam os seeds. Nomes comerciais de suítes,
capacidade e preços devem ser conferidos nos cadastros da instalação.

**Estratégia:** núcleo e módulos ativáveis por instalação. O catálogo prepara a
evolução do produto; não há isolamento multiempresa/multihotel de um SaaS no banco atual.

### Princípios

1. Disponibilidade pertence a Reservas; dinheiro e estoque pertencem ao núcleo.
2. Services concentram regras de negócio; sinais conectam eventos entre módulos.
3. Ativação e permissões determinam acesso e comportamento.
4. Valores monetários usam `Decimal`; correções financeiras e de estoque mantêm trilha.
5. Escritas concorrentes sensíveis usam transação, trava e idempotência quando aplicável.
6. Ações sem login usam autores de sistema; dados sensíveis são mascarados na auditoria.
7. Interface e relatórios distinguem serviço, consumo, receita por competência e recebimentos.

A referência de mercado é o [estudo Desbravador](REFERENCIA_DESBRAVADOR.md).
Novas funcionalidades devem considerar como o trabalho é executado pela equipe,
o comportamento existente e referências atuais, antes de definir novas telas.

## 2. Stack e execução

| Camada | Implementação atual |
|---|---|
| Backend | Python 3.14 e Django 6; pins em `requirements.txt` |
| Banco | PostgreSQL; CI e ambiente de referência usam a versão 16 |
| Interface interna | Templates Django, HTMX e Alpine.js; bibliotecas locais em `static/vendor/` |
| Site | Templates Django e CSS Tailwind compilado |
| Servidor | Gunicorn e WhiteNoise; configuração Railway versionada |
| Cache | Redis opcional; sem URL, cache compartilhado no PostgreSQL |
| Rotinas | Management commands e dois grupos cron; não usa Celery |
| APIs | Views Django, webhooks e adapters próprios; DRF não está instalado |
| Validação | Runner Django, PostgreSQL real, Playwright/Chromium em job próprio e checks de segurança |

Instalação, comandos e ambiente estão no [README](../README.md);
detalhamento técnico em [Arquitetura](ARQUITETURA.md).

## 3. Mapa funcional

O projeto instala 19 apps. Nem todo app é módulo comercial; `portal`, `nps` e
`conciliacao`, por exemplo, têm papéis próprios. Catálogo e dependências declaradas:
[apps/nucleo/modulos.py](../apps/nucleo/modulos.py).

| Frente | Implementação |
|---|---|
| Núcleo | Pessoas, UHs/tipos, temporadas, configuração, usuários, acessos, caixa, financeiro, estoque, logbook e dashboard |
| Reservas | Disponibilidade, mapa, grupos, conta, tarifas, FNRH/BOH, camas extras, restrições e fechamento |
| Governança | Limpeza, arrumação, inspeção opcional, ronda e discrepâncias |
| Manutenção e escala | Chamados/ordens de serviço, bloqueios, tarefas recorrentes, turnos, ausências e publicação |
| Loja, restaurante e lavanderia | Vendas/comandas/serviços, consumos na conta e integração com estoque/caixa |
| Pagamentos e conciliação | Cobranças, baixas, eventos, OFX e cartão |
| Comercial e marketing | Funil, atividades, cotações, canais, LPs, campanhas, peças, orçamento e acompanhamento |
| Site e portal | Reserva pública, páginas de pagamento, pré-check-in, extrato e solicitações |
| Relatórios e auditoria | Indicadores, CSV, pendências, trilha e fechamento diário |
| Fiscal | Modelos e fluxo simulado; emissão real pendente |
| NPS | Proposta e endpoints stub; coleta persistida pendente |

Frigobar foi retirado do catálogo. CRM do Hóspede e Canais/OTAs continuam como
entradas para evolução futura, sem integração operacional completa.

## 4. Núcleo

### 4.1 Cadastros e configuração

Pessoa é a base comum para hóspedes, clientes, fornecedores, funcionários e empresas.
UHs e tipos determinam a estrutura; temporadas e tarifas determinam preços.
A configuração persistida de Reservas é administrada pela Tabela de Preços.

Seeds oferecem uma estrutura inicial, não garantem que o banco operacional tenha
os mesmos quartos ativos, valores ou regras. Configuração já persistida não é
substituída automaticamente por mudança de defaults de ambiente.

### 4.2 Acessos

O usuário possui módulos e áreas. Views usam `requer_modulo`, `requer_area` ou
`requer_gerencia`; módulos inativos e falta de acesso são tratados separadamente.
Gerência usa `is_staff`/`is_superuser` nos controles correspondentes. O sistema
possui MFA e limites de autenticação configuráveis; isso não equivale a uma matriz
completa de cargos por módulo.

### 4.3 Caixa e financeiro

Sessões de caixa pertencem ao operador e módulo. Há abertura, recebimento, sangria,
reforço, fechamento com conferência cega, reabertura e estorno auditado.

Créditos na conta do hóspede têm origem definida: caixa, cobrança online, conta a
receber ou estorno de outro crédito. Os services preservam esses vínculos.
Dinheiro online não deve ser contado outra vez como entrada da gaveta.
Faturamento, devolução e estorno precisam seguir o fluxo correspondente à origem.

### 4.4 Estoque

Produto, local, movimento e inventário pertencem ao núcleo. Entradas, saídas,
transferências e ajustes usam services, com saldo por local e custo médio.
Os módulos consumidores movimentam esse mesmo estoque, sem saldos paralelos.

### 4.5 Auditoria e continuidade

A trilha registra mudanças e operações sensíveis; campos pessoais/salário têm
tratamento de exibição próprio. Signals não capturam automaticamente toda escrita
em lote ou SQL direto, que exige registro explícito.

O kit de contingência reúne hospedados, chegadas, saídas e situação dos quartos,
com impressão e envio diário opcional. Backup de banco é uma rotina separada e
precisa de destino e agendamento configurados.

## 5. Hospedagem e operação

### 5.1 Reservas, FNRH e conta

O fluxo cobre pré-reserva, confirmação, check-in, hospedagem, check-out,
cancelamento e no-show. A disponibilidade considera datas, UHs e bloqueios,
com restrição no PostgreSQL contra sobreposição de reservas ativas.

Grupos coordenam reservas; camas, sofás, colchões extras e berços compõem capacidade
e montagem. Restrições de venda podem limitar estadias e entradas/saídas por
período/tipo. Os detalhes de prioridade, estados e validações estão em
[Módulos e fluxos](MODULOS_E_FLUXOS.md).

A FNRH local guarda a ficha por hóspede, permite preenchimento na recepção ou portal
e participa da trava de check-in. O envio Serpro é integração separada, com status
e reprocessamento; possuir ficha local não comprova envio ao governo. BOH é agregado
mensal com exportação.

Diárias são lançadas no check-in com competência por noite; o fechamento diário
consolida o dia, não é um motor que cobra novamente toda noite.
Consumos e serviços dos setores entram na conta. O check-out depende da liquidação
ou faturamento e das tolerâncias/regras configuradas.

### 5.2 Governança, manutenção e equipe

Governança registra tarefas de saída/arrumação, atribuição, andamento e conclusão.
A inspeção opcional pode devolver a tarefa para retrabalho. Rondas registram
situação física e permitem identificar discrepâncias com a recepção.

O painel e suas regras estão documentados em [Módulos e fluxos](MODULOS_E_FLUXOS.md):
a entrada é a visão geral da casa (quartos em blocos pelo estado da limpeza, progresso do
dia, o que pede ação, chegadas e carga das camareiras) e a lista de trabalho mostra o
ciclo A limpar › Em limpeza › Limpo › Pronto com um próximo passo por quarto.

Manutenção registra chamados e ordens, podendo bloquear a UH; há recorrência em
ordens de serviço. Escala trabalha turnos, atribuições, ausências, trocas e publicação.
Esses recursos não comprovam, por si, adoção operacional pela equipe.

### 5.3 Vendas e lavanderia

Loja e restaurante atendem venda avulsa ou consumo na hospedagem. Restaurante usa
comandas e fluxo de pedidos. Lavanderia distingue rouparia interna e serviços ao
hóspede. Movimentos de estoque, caixa e conta devem passar pelas interfaces dos
módulos responsáveis.

### 5.4 Site e portal

O site oferece vitrine e motor de reservas ligados à disponibilidade do PMS.
O portal usa token da hospedagem para pré-check-in, extrato, pedidos/solicitações
e jornada de saída. Solicitações não eliminam as validações da operação interna.
O atalho de NPS não representa uma pesquisa com respostas persistidas.

## 6. Comercial e marketing

LPs, captação e cadastros alimentam pessoas/leads e oportunidades. O funil registra
etapa, responsável, atividades, contato, cotação e conversão em reserva.
WhatsApp e e-mail possuem trilhas próprias; consentimentos e descadastro devem ser
respeitados pelos envios.

Marketing organiza campanhas, fases, peças, orçamento e calendário, apoiado nos
dados do Comercial. O código inclui envio de campanhas de e-mail e comando manual
de campanha WhatsApp. Um painel completo de campanhas WhatsApp e os planos de
telefonia continuam evoluções; os roteiros históricos não comprovam implementação.

## 7. Gestão, relatórios e integrações

### 7.1 Relatórios e auditoria operacional

Além de produção, ocupação, caixa e faturamento por setor, há relatórios de carteira
(OTB), pickup, ritmo de vendas e custo de distribuição. Carteira, pickup e ritmo
abrem o próximo mês por padrão; pickup usa janelas de 7, 14 ou 30 dias.
Governança tem relatórios de faxinas, inspeção e discrepâncias.

Auditoria reúne pendências, trilha e fechamento diário. Conciliação cruza OFX e
cartão com registros do CRM; não transforma automaticamente qualquer linha de
extrato em movimento financeiro.

### 7.2 Integrações

Safrapay, Serpro, WhatsApp Cloud, Meta e JEV têm adapters; precisam de configuração
e comprovação externa adequadas. Pix direto confirma manualmente.
Fiscal real, SES, Google e BSP têm limites/stubs descritos no
[Estado atual](ESTADO_ATUAL.md#integrações-e-limites).

O nome `EMAIL_GATEWAY=simulado` não impede envio real: o adapter usa o backend Django,
incluindo SMTP quando configurado. Testes e demonstrações devem usar configuração
compatível com o efeito desejado.

Campos fiscais, inclusive IBS/CBS, não são autorização de emissão ou homologação
tributária. A classificação e os parâmetros aplicáveis precisam ser validados com
o responsável fiscal e o provider implementado.

## 8. Evolução e critérios de entrega

Continuam fora da implementação operacional completa: coleta NPS/CRM do Hóspede,
channel manager/OTAs, telefonia integrada, providers fiscais reais e os demais
stubs da matriz de integrações. Ideias adicionais estão em
[IMPLEMENTAR_Ideias](IMPLEMENTAR_Ideias.md) e nos planos temáticos, sempre como backlog.

Uma entrega deve manter código, migrações, comportamento de interface e documentação
coerentes. Regras financeiras e de disponibilidade exigem testes; mudanças de UI
exigem interação real em desktop e celular. Contagens antigas de testes não
substituem a validação do commit em entrega.

Publicação na fork, integração com o original e deploy são etapas distintas,
sujeitas ao escopo autorizado. Consulte as [convenções](../CLAUDE.md), o
[README](../README.md) e o [checklist operacional](Checklist_CRM_100.md).
