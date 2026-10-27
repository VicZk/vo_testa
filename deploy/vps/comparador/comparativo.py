"""Aba "Comparativo" da cópia atualizada na VPS: o que mudou da versão anterior para esta.

Página de apresentação, só da VPS: entra pelo settings_vps.py com COMPARATIVO_VERSOES=1,
e o item do menu vem do nova.js, como o "Versão anterior". O conteúdo é uma curadoria
técnica do CHANGELOG, com o trecho de código de cada conserto (trechos.py).
`tela` é o nome de URL da tela onde dá para ver o item; o link da versão anterior é o
mesmo caminho lá. Nos textos, `crase` vira código.
"""

import difflib
import re

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import get_script_prefix, reverse

try:
    from . import trechos as t  # deploy.vps.comparador.comparativo (testes)
except ImportError:
    import trechos as t  # /opt/comparador no PYTHONPATH (VPS)

ANTERIOR = "https://votesta-original.195-200-0-150.sslip.io"
FORK = "https://github.com/VicZk/vo_testa"

INTRO = (
    "A base e a arquitetura são do Gefferson: núcleo + módulos contratáveis (`modulo_ativo`, "
    "`@requer_modulo`), caixa com movimentos imutáveis, o `ExclusionConstraint` contra overbooking "
    "e o `travar()` para escrita concorrente. De 20 a 26/10/2026, a branch `dev` do fork "
    "(VicZk/vo_testa) somou mais de 380 commits sobre essa base. Aqui está o que mudou em relação "
    "ao `main` que está no ar (`85e19bf`), com o trecho de código de cada conserto: `−` é a linha "
    "da versão anterior e `+`, a da atualizada. “Ver antes” abre a mesma tela na versão anterior, "
    "em outra aba."
)
RODAPE = (
    "Contagens feitas no código das duas versões em 26/10/2026 (`git grep`, fora testes e "
    "migrations); consultas e tempos medidos no banco local com os dados de exemplo (no Railway, "
    "cada consulta ainda paga a rede). Os trechos são colados do código sem retoque e conferidos "
    "linha a linha no git das duas versões (`deploy/vps/comparador/conferir_trechos.py`). O detalhe "
    "de cada item está no CHANGELOG do fork."
)

# A mesma medida nas duas versões. Cada uma tem a sua escala (nada de eixo comum entre
# medidas diferentes); "menos é melhor" fica dito no texto.
EM_NUMEROS = [
    {"titulo": "Testes automatizados", "destaque": "Quase 3× mais",
     "explica": "Runner do Django contra PostgreSQL 16, no CI a cada push (`testes.yml`).",
     "antes": 977, "agora": 2863, "antes_txt": "977", "agora_txt": "2.863"},
    {"titulo": "Testes de ponta a ponta", "destaque": "35× mais",
     "explica": "Playwright + Chromium (`apps/site/tests*e2e.py`), obrigatórios no CI com "
                "`E2E_OBRIGATORIO=1`.",
     "antes": 8, "agora": 282, "antes_txt": "8", "agora_txt": "282"},
    {"titulo": "Restrições no banco", "destaque": "Quase 3× mais",
     "explica": "`CheckConstraint`, `UniqueConstraint` e `ExclusionConstraint` nos models: a regra "
                "vale mesmo fora da tela.",
     "antes": 21, "agora": 60, "antes_txt": "21", "agora_txt": "60"},
    {"titulo": "Travas de linha", "destaque": "15× mais",
     "explica": "Chamadas a `select_for_update()`: escrita de dinheiro e estoque serializada no banco.",
     "antes": 5, "agora": 77, "antes_txt": "5", "agora_txt": "77"},
    {"titulo": "Consultas SQL ao abrir um lead", "destaque": "8× menos",
     "explica": "N+1 no painel de quartos (temporada, tarifa e configuração por quarto × noite). "
                "Tempo: 481 ms → 69 ms. Menos é melhor.",
     "antes": 444, "agora": 56, "antes_txt": "444", "agora_txt": "56"},
    {"titulo": "Consultas na busca de quartos", "destaque": "18× menos",
     "explica": "Motor de disponibilidade do site, 3 noites; com 7 noites, 682 → 24. Menos é melhor.",
     "antes": 334, "agora": 18, "antes_txt": "334", "agora_txt": "18"},
    {"titulo": "HTML da LP da inauguração", "destaque": "24× menor",
     "explica": "Sete fontes e quinze imagens embutidas no HTML viraram arquivos próprios, com cache.",
     "antes": 2100, "agora": 89, "antes_txt": "2,1 MB", "agora_txt": "89 KB"},
    {"titulo": "Primeira pintura da LP no 4G fraco", "destaque": "10× mais rápida",
     "explica": "Antes, 4,2 s de tela vazia; a carga completa caiu de 10,9 s para 5,6 s.",
     "antes": 4.2, "agora": 0.4, "antes_txt": "4,2 s", "agora_txt": "0,4 s"},
    {"titulo": "Alvos de toque abaixo de 44 px", "destaque": "De 223 para 2",
     "explica": "Varredura de todas as telas. Os 2 restantes são links no meio de uma frase, isentos "
                "pela regra de alvo em linha do WCAG (2.5.5).",
     "antes": 223, "agora": 2, "antes_txt": "223", "agora_txt": "2"},
]

# Impacto alto primeiro. Segurança fica sem código: esta página é aberta e a versão no ar
# ainda é a anterior.
CORRECOES = [
    {"grave": True, "area": "Pagamentos → Reservas", "titulo": "Pagamento online vira crédito na conta",
     "antes": "`confirmar_pagamento` marcava a `Cobranca` como paga e gravava o `EventoPagamento`, "
              "mas não lançava crédito na conta: o Pix ou o cartão pago no site não abatia o saldo, "
              "e o check-out cobrava de novo.",
     "agora": "A confirmação chama `registrar_pagamento_online`, a interface pública de Reservas: "
              "`Adiantamento` antes do check-in, `PagamentoConta` com a conta aberta. `cobranca_id` "
              "é único, então webhook repetido não credita duas vezes.",
     "tela": "reservas:lista", "codigo": t.PAGAMENTO_ONLINE},
    {"grave": True, "area": "Caixa → Reservas", "titulo": "Estorno de caixa desfaz o crédito na conta",
     "antes": "`estornar_movimento` criava o movimento inverso no caixa, mas o `PagamentoConta` "
              "espelhado na reserva ficava: o dinheiro saía da gaveta, a conta seguia quitada e o "
              "check-out fechava sem cobrar.",
     "agora": "Gancho `ao_estornar` no núcleo: Reservas registra no `AppConfig.ready()` uma função que "
              "roda na mesma transação do estorno e lança o crédito negativo (`estorno_de`). Conta já "
              "fechada levanta `ValidationError` e nada é estornado. O núcleo segue sem importar o módulo.",
     "tela": "caixa", "codigo": t.ESTORNO},
    {"grave": True, "area": "Formulários de R$", "titulo": "R$ 650,00 não chega mais como R$ 65.000,00",
     "antes": "A máscara `mascara-reais` tira os pontos no submit, contando com o formato pt-BR. O "
              "valor que vinha do servidor saía cru (`\"650.00\"`), perdia o ponto e chegava como "
              "`65000`: no «Ganhar» do Comercial, a diária da cotação virava R$ 65.000,00.",
     "agora": "`ReaisInput.format_value` escreve o valor do servidor no formato da máscara "
              "(`\"650,00\"`), num widget único do núcleo. E a conversão passou para os eventos "
              "`formdata` e `htmx:configRequest`: o campo visível não muda, e um reenvio depois de "
              "erro de rede não multiplica de novo.",
     "tela": "comercial:funil", "codigo": t.REAIS},
    {"grave": True, "area": "Operação", "titulo": "Rotinas agendadas de verdade",
     "antes": "`expirar_reservas`, `enviar_fnrh_pendentes`, `enviar_campanhas_email`, "
              "`enviar_conversoes_pendentes` e `sincronizar_gastos_midia` existiam como comandos, mas "
              "nenhum serviço os agendava (o único cron é o `cron-financeiro.yml`, das capturas "
              "contábeis, de 24/10). Pré-reserva vencida seguia bloqueando a UH.",
     "agora": "`manage.py rotinas --grupo frequentes` (`*/10 * * * *`) e `--grupo diarias` "
              "(`15 6 * * *`, 03:15 em Brasília), em dois serviços cron do Railway. Cada tarefa roda "
              "isolada, com o tempo no log, e o grupo avisa início, fim e falha ao Healthchecks "
              "(`ROTINAS_MONITOR_*`). Entraram `backup_banco`, `fechar_dia` e `purgar_trilha`.",
     "codigo": t.ROTINAS},
    {"grave": True, "area": "Fiscal · NFS-e", "titulo": "ISS fora da própria base de cálculo",
     "antes": "`lancar_taxas` lançava o ISS e a taxa de turismo como `Tipo.SERVICO`, e "
              "`resumo_fiscal_conta` usava o total de serviço como base: o ISS de 4% incidia sobre o "
              "próprio ISS e sobre a taxa, e a nota declarava repasse como serviço.",
     "agora": "Tipo próprio, `Tipo.TAXA`: o valor continua na conta do hóspede, mas sai da base "
              "(`servico - taxas`). A migration `reservas.0024` reclassificou os lançamentos antigos, "
              "com `RunPython` reversível.",
     "tela": "fiscal:painel", "codigo": t.ISS},
    {"grave": True, "area": "Loja · PDV", "titulo": "Venda idempotente no balcão",
     "antes": "`finalizar_venda` não tinha chave de idempotência: clique duplo, ou reenvio depois de a "
              "conexão cair, criava duas `Venda`, cobrava duas vezes no caixa e baixava o estoque em dobro.",
     "agora": "O PDV gera um UUID por carrinho (`Venda.chave`, `unique=True`). O reenvio devolve a venda "
              "já gravada; dois envios simultâneos esbarram na unicidade (`IntegrityError`) e o segundo "
              "recebe a venda do primeiro. As travas seguem a ordem de `pk`, sem deadlock entre carrinhos.",
     "tela": "loja:pdv", "codigo": t.LOJA},
    {"grave": True, "area": "Estoque", "titulo": "Inventário aplica a diferença, não o saldo antigo",
     "antes": "`Inventario.aplicar` gravava `quantidade_contada` como saldo absoluto, até no item que "
              "ninguém contou: uma venda feita durante a contagem era apagada no «Aplicar». E o clique "
              "duplo na entrada dobrava o saldo e deslocava o custo médio.",
     "agora": "Aplica `saldo atual + diferença`, só nos itens contados (`somente_contados=True`), com "
              "inventário e produtos travados em ordem de `pk`. A trava do produto contra corrida no "
              "custo médio já vinha da versão anterior; faltava reconhecer o mesmo envio duas vezes, e as "
              "entradas ganharam `MovimentoEstoque.chave`, a mesma idempotência da Loja.",
     "tela": "estoque:posicao", "codigo": t.INVENTARIO},
    {"grave": True, "area": "LGPD · Landing pages", "titulo": "GA4 e Meta Pixel só depois do «Aceitar»",
     "antes": "As LPs de captação (`captacao_publica.html` e `captacao_blueprint.html`) executavam "
              "`fbevents.js` e `gtag.js` no carregamento, sem aviso de cookies; o `<noscript>` do Pixel "
              "disparava até sem JavaScript.",
     "agora": "As tags ficam como `<script type=\"text/plain\" data-consentimento>`, que o navegador não "
              "executa, e o `consentimento.js` as recria como scripts de verdade só no «Aceitar». No "
              "«Recusar» nada carrega, e a escolha fica no `localStorage`, com um cookie de reserva.",
     "tela": "lp:inauguracao", "codigo": t.CONSENTIMENTO},
    {"grave": True, "area": "Reservas · Cancelamento", "titulo": "“10%”, não “1E+1%”, e termos iguais ao cálculo",
     "antes": "`Decimal.normalize()` escreve 10 como `1E+1`: a política mostrava “retemos 1E+1% do "
              "valor total”, e o motivo do cancelamento gravava “reter 1E+1%”. Os termos prometiam 90% "
              "em 7 dias; o cálculo devolvia 100%, como pede o art. 49 do CDC.",
     "agora": "`pct_br()` no núcleo, com `format(…, \"f\")`; termos gerados da mesma configuração do "
              "cálculo; e a reserva guarda o aceite: data, hora e o texto que estava na tela.",
     "tela": "core:termos_servico", "codigo": t.PERCENTUAL},
    {"area": "Caixa", "titulo": "Fechamento e recebimento serializados",
     "antes": "`SessaoCaixa.fechar()` calculava o esperado sem travar a sessão, e `receber_no_caixa` "
              "buscava a sessão aberta sem `FOR UPDATE`: um recebimento simultâneo (outra aba) podia "
              "cair numa sessão já conferida, fora da conferência cega.",
     "agora": "Os dois rodam em `transaction.atomic`, com a sessão travada (`travar(self)` e "
              "`select_for_update()`): o recebimento entra antes e conta, ou chega depois e é recusado. "
              "O estorno de um caixa já fechado vai para a sessão aberta de hoje, sem reabrir a conferência.",
     "tela": "caixa", "codigo": t.CAIXA},
    {"area": "Reservas · Sinais", "titulo": "Check-in e check-out atômicos, receptores isolados",
     "antes": "`fazer_checkin` e `fazer_checkout` rodavam sem `transaction.atomic` nem trava, e o "
              "`quarto_liberado` saía por `send()`: uma exceção num receptor (Governança, Lavanderia) "
              "subia para o check-out e deixava a reserva pela metade.",
     "agora": "Os dois são atômicos e travam reserva e conta. O sinal sai por `emitir()` (`send_robust` "
              "+ log), e cada receptor entre módulos leva `@receptor_isolado`, que roda num savepoint: no "
              "PostgreSQL, um erro de banco aborta a transação inteira.",
     "codigo": t.CHECKOUT},
    {"area": "Relatórios", "titulo": "Receita por competência e ocupação só de quartos",
     "antes": "`relatorio_producao` e `relatorio_ocupacao` filtravam por `criado_em__date`: as diárias, "
              "lançadas no check-in, de uma estadia de 28/10 a 3/11 caíam todas em outubro. E as UHs de "
              "day use entravam na disponibilidade, baixando a ocupação e distorcendo ADR e RevPAR.",
     "agora": "`LancamentoConta.competencia` (a noite de cada diária, migration `reservas.0028`) e "
              "`.exclude(tipo__modalidade=day_use)`: ocupação, ADR e RevPAR contam as mesmas noites.",
     "tela": ("relatorios:relatorio", "ocupacao"), "codigo": t.COMPETENCIA},
    {"area": "Segurança", "titulo": "Limite de tentativas de login",
     "antes": "A trava contra tentativa de senha por força bruta nem sempre segurava o limite configurado.",
     "agora": "O limite vale para o sistema inteiro, pelo tempo definido. O detalhe fica num relatório "
              "à parte, porque a versão no ar ainda é a anterior."},
    {"area": "Segurança", "titulo": "Trilha de auditoria sem dado pessoal",
     "antes": "Alguns registros da trilha guardavam mais dado pessoal do que deviam.",
     "agora": "O diff mascara documento e nascimento (`CAMPOS_PII`), a trilha segue dizendo quem fez o "
              "quê, e os registros antigos foram saneados."},
]

NOVIDADES = [
    {"area": "Governança", "titulo": "Arrumação no toque",
     "texto": "`governanca:painel` mostra a casa inteira; `governanca:quartos` segue o ciclo de "
              "`services.CICLO` com um próximo passo por quarto; a camareira trabalha na "
              "`governanca:minha_fila`, e “Distribuir a fila” usa `escala.services.usuarios_de_turno`. "
              "`abrir_faxina` e `iniciar_tarefa` travam a linha.",
     "tela": "governanca:painel"},
    {"area": "Governança", "titulo": "Ronda e discrepâncias",
     "texto": "A ronda registra vago, com mala ou sem mala por UH e cruza com o status da recepção; a "
              "divergência vira pendência em `governanca:discrepancias`, como o hóspede que saiu sem "
              "check-out.",
     "tela": "governanca:discrepancias"},
    {"area": "Reservas", "titulo": "Restrições de venda",
     "texto": "`RestricaoVenda`: estadia mínima, sem chegada (CTA), sem saída (CTD) e stop sell, por "
              "quarto, por tipo ou na casa inteira (`CheckConstraint` de escopo exclusivo). Site e "
              "formulário respeitam; só a gerência passa do stop sell, com motivo na trilha.",
     "tela": "reservas:restricoes"},
    {"area": "Relatórios", "titulo": "Receita vendida",
     "texto": "Carteira (OTB), pickup diário, ritmo de vendas por antecedência e custo de distribuição "
              "por canal, a partir de um motor único em Reservas.",
     "tela": ("relatorios:relatorio", "carteira")},
    {"area": "Auditoria", "titulo": "Fechamento do dia",
     "texto": "`fechar_dia`, na rotina diária, grava um `FechamentoDiario` que não muda mais: ocupação, "
              "chegadas, saídas, no-shows e receita por competência, com totais do mês e CSV.",
     "tela": "auditoria:fechamentos"},
    {"area": "Reservas", "titulo": "No-show automático",
     "texto": "`marcar_no_shows` roda antes do `fechar_dia`, com tolerância configurável na Tabela de "
              "Preços; a UH volta à venda, e dá para desfazer.",
     "tela": "tabela_precos"},
    {"area": "Reservas", "titulo": "Faturamento para agência ou empresa",
     "texto": "O saldo vira título a receber no Financeiro (vencimento padrão em 30 dias), e um "
              "`PagamentoConta` de origem “faturado” (`conta_receber`) quita a conta; o consumo pessoal "
              "pode ficar com o hóspede."},
    {"area": "Recepção", "titulo": "Kit de contingência",
     "texto": "Folha A4 (`reservas:kit`) com hóspedes, saldos, chegadas com telefone, saídas e a "
              "situação das 24 UHs; a rotina `enviar_kit_contingencia` manda uma cópia por e-mail toda "
              "madrugada.",
     "tela": "reservas:kit"},
    {"area": "Day pass", "titulo": "Day pass por turno",
     "texto": "App `daypass`: turnos com capacidade, ingressos, controle de entrada e saída, caixa "
              "próprio e comanda do grupo.",
     "tela": "daypass:painel"},
    {"area": "Canais", "titulo": "Channel manager",
     "texto": "App `canais`: conexão Channex, mapeamento de quartos e tarifas, fila de revisões e "
              "publicação de disponibilidade, tarifas e restrições, com rotina própria a cada minuto "
              "(`--grupo canais`). Pronto e desligado até a homologação.",
     "tela": "canais:painel"},
    {"area": "Estoque", "titulo": "Compras, lotes e validade",
     "texto": "Recebimento por embalagem, com fator de conversão, lotes com validade, ficha técnica dos "
              "pratos e baixa pelo motor do núcleo; as conversões ficam congeladas no histórico.",
     "tela": "estoque:notas"},
    {"area": "Lavanderia", "titulo": "Lavanderia como fila",
     "texto": "Etapas recebida → lavando → pronta, com a hora de cada transição e o histórico do enxoval.",
     "tela": "lavanderia:painel"},
    {"area": "Reservas · ECA", "titulo": "Menor de idade na FNRH",
     "texto": "A ficha registra o vínculo do menor (pais, responsável legal ou adulto autorizado), e o "
              "check-in exige a autorização quando o vínculo pede."},
]

INTERFACE = [
    {"titulo": "Visão geral que decide pelo espaço",
     "texto": "Chegadas e saídas empilhadas, com a lista vazia numa linha só, e os recados do turno num "
              "trilho lateral com `position: sticky`. Quem decide é uma container query sobre o "
              "conteúdo, não um `@media` da janela: com o menu aberto ou recolhido, o painel se ajeita "
              "ao espaço que sobra.",
     "tela": "dashboard", "codigo": t.PAINEL_CSS},
    {"titulo": "Menu sem reflow",
     "texto": "O menu recolhido é o menu aberto recortado: na troca só mudam opacidade, cor, giro e "
              "posição, então nada reflui. No celular, abre por cima, como gaveta.",
     "tela": "reservas:mapa"},
    {"titulo": "Pílula só para o que pede ação",
     "texto": "Status neutro vira `.selo` (bolinha + texto); a cápsula preenchida fica para o que pede "
              "ação (`.selo--acao`) e para os estados críticos. Eram 252 pílulas nas telas; são 28.",
     "tela": "pessoas"},
    {"titulo": "Feito para o dedo",
     "texto": "Alvo de no mínimo 44 px em `pointer: coarse`, modal que vira gaveta de baixo com as "
              "ações presas ao pé (altura em `dvh`), toast no topo e nenhuma rolagem lateral de 320 a "
              "1440 px.",
     "tela": "reservas:lista"},
    {"titulo": "Só tokens",
     "texto": "Cor, raio, sombra e movimento saem dos tokens (`--lampiao`, `--raio-p`, "
              "`--sombra-cartao`, `--mov-*`); o `CorSoPorTokenTests` barra hex e rgba nos templates do "
              "CRM, e números usam `tabular-nums`.",
     "tela": "auditoria:trilha"},
    {"titulo": "Copiar e mandar pelo WhatsApp",
     "texto": "`{% copiar %}` (`componentes/copiar.html` + `copiar.js`): “Copiar” com plano B e "
              "“Enviar pelo WhatsApp” com a mensagem pronta, para link de pagamento, Pix e pré check-in.",
     "tela": "pagamentos:painel"},
]

ENGENHARIA = [
    {"titulo": "Suíte no CI a cada push",
     "texto": "O `testes.yml` é novo: ruff, `makemigrations --check`, a suíte contra PostgreSQL 16 e o "
              "job “Fluxos no navegador” (Playwright + Chromium), em todo push da `dev` e em PR. Na "
              "versão anterior, a suíte rodava só na máquina de quem desenvolve.",
     "codigo": t.CI},
    {"titulo": "Segurança no CI",
     "texto": "O `security.yml` do Gefferson (pip-audit, bandit, ruff de segurança, semgrep, "
              "`check --deploy` e gitleaks) roda também na `dev`; o semgrep passou de “só relatório” a "
              "bloqueante, e o gitleaks ganhou um `.gitleaks.toml`."},
    {"titulo": "Backup e rotinas monitoradas",
     "texto": "`backup_banco` toda madrugada, com 30 dias de retenção, e um ensaio de restauração que "
              "conferiu os totais. Cada grupo de rotinas avisa início, fim e falha a um check do "
              "Healthchecks.io."},
    {"titulo": "Acesso e trilha",
     "texto": "A verificação em duas etapas (TOTP, `apps/nucleo/mfa.py`) já vinha da versão anterior; "
              "entrou o “Esqueci minha senha” por e-mail, e as ações sem login (site, portal, webhook, "
              "cron) assinam a trilha com `usuario_de_sistema()`."},
    {"titulo": "Desempenho com teto",
     "texto": "`assertNumQueries` trava o número de consultas das telas críticas, e o PostgreSQL conecta "
              "com o JIT desligado: ele compilava por 185 ms uma consulta de 1,4 ms."},
    {"titulo": "Homologação lado a lado",
     "texto": "Cópia em viczk.cloud/votesta (Docker + nginx, sob `URL_PREFIX`), com dados de exemplo e "
              "integrações em modo simulado; a versão anterior roda ao lado, para comparar."},
]

BASE = [
    {"titulo": "Overbooking impedido pelo banco",
     "texto": "`ExclusionConstraint` sobre `daterange(checkin, checkout)`: duas reservas ativas não "
              "ocupam a mesma UH em noites sobrepostas, nem numa corrida entre duas recepções. Segue "
              "igual na atualizada.",
     "codigo": t.OVERBOOKING},
    {"titulo": "Módulos contratáveis",
     "texto": "`modulo_ativo()` + `@requer_modulo`: módulo não contratado responde 404; usuário sem o "
              "módulo, 403. Toda view de módulo do fork nasce com o decorator, e o módulo novo de "
              "Canais entrou no mesmo catálogo (`apps/nucleo/modulos.py`).",
     "codigo": t.MODULOS},
    {"titulo": "Escrita concorrente",
     "texto": "`travar(obj)`: `SELECT … FOR UPDATE` + `refresh_from_db()`. A atualizada o usa em mais de "
              "90 pontos; foi a peça-chave dos consertos de caixa, check-out, estoque e pagamentos.",
     "codigo": t.TRAVAR},
]

DO_ORIGINAL = [
    {"area": "24/10", "titulo": "Contábil e gerencial",
     "texto": "App `contabil` (`Modulo.CONTABIL`): plano de contas com de-para (`resolver_conta`), "
              "capturas por competência, `FechamentoMensal` e DRE por soma, com CSV. No fork, as "
              "capturas rodam na `rotina_contabil` (grupo `diarias`) e conversam com caixa, estoque "
              "(CMV) e day pass.",
     "tela": "contabil:painel"},
    {"area": "25/10", "titulo": "NFS-e pelo Spedy",
     "texto": "`apps/fiscal/spedy.py`: NFS-e assíncrona com `integrationId` = `gateway_id`, retorno "
              "assinado no padrão Standard Webhooks e cancelamento que só fecha na confirmação "
              "(`CancelamentoPendente`). Regime Lucro Presumido em `settings.EMPRESA_*`.",
     "tela": "fiscal:painel"},
    {"area": "21/10", "titulo": "Comercial",
     "texto": "Reabrir ou mover lead ganho ou perdido (área `comercial_fechados`), diária da tabela no "
              "«Ganhar» com a diferença na linha do tempo, sinal em R$ ou % e o resumo financeiro na "
              "reserva.",
     "tela": "comercial:funil"},
    {"area": "20 e 21/10", "titulo": "Reservas e preços",
     "texto": "Meia diária de 6 a 15 anos, ajustes no day use, regras de preço, tarifa não reembolsável "
              "e o comando `zerar_reservas`.",
     "tela": "tabela_precos"},
    {"area": "Mão dupla", "titulo": "De volta para o original",
     "texto": "Quatro consertos que também valem para o `main` (R$ ×100, “1E+1%”, termos × cálculo e o "
              "aviso de cookies) estão prontos como patches sobre o `main` dele. E todo dia uma rotina "
              "confere o que ele publica e propõe trazer para cá, sempre com revisão."},
]

PROXIMOS = [
    {"titulo": "Decidir a versão de produção",
     "texto": "O ensaio de 26/10 migrou o banco do `main` (`85e19bf`) para a `dev` sem erro: 82 "
              "migrações e telas respondendo 200. Para trocar: os dois serviços cron no Railway "
              "(`deploy/railway.rotinas*.json`), as variáveis novas e backup antes do deploy."},
    {"titulo": "Integrações reais",
     "texto": "Spedy (conta, chave e certificado), NFC-e (depende da inscrição estadual), Channex, "
              "SMTP ou SES e WhatsApp Cloud. Hoje, tudo em modo simulado."},
    {"titulo": "Primeiro fechamento com o contador",
     "texto": "Fechar o mês no Contábil com ele e validar o IBS e a CBS da reforma tributária."},
    {"titulo": "Regras de receita",
     "texto": "Tolerância do no-show automático (sugestão: 1 dia), custo por canal e a comissão de OTA, "
              "que é stub até o módulo Canais."},
    {"titulo": "Governança com a equipe",
     "texto": "Validar com a camareira e a supervisão os rótulos de `services.CICLO` e liberar a área "
              "para quem usa a fila."},
    {"titulo": "Antes de abrir, em 31/10",
     "texto": "`zerar_reservas`, a restrição do Réveillon, `ROTINAS_MONITOR_*` no ar, os e-mails do kit "
              "e o encarregado de dados da LGPD."},
]

TEXTOS = ("antes", "agora", "texto", "explica")


def _partes(texto):
    # [(é código?, trecho)]: o template escreve cada trecho com o escape normal.
    return [(i % 2 == 1, trecho) for i, trecho in enumerate(re.split(r"`([^`]+)`", texto)) if trecho]


def _diff(antes, agora):
    a, b = antes.strip("\n").splitlines(), agora.strip("\n").splitlines()
    recuo = min((len(linha) - len(linha.lstrip()) for linha in a + b if linha.strip()), default=0)
    a, b = [linha[recuo:] for linha in a], [linha[recuo:] for linha in b]
    if not a:  # código novo: tudo entra
        return [{"tipo": "add", "texto": linha} for linha in b]
    linhas = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            linhas += [{"tipo": "omit" if linha.strip() == "…" else "", "texto": linha}
                       for linha in a[i1:i2]]
        else:
            linhas += [{"tipo": "rem", "texto": linha} for linha in a[i1:i2]]
            linhas += [{"tipo": "add", "texto": linha} for linha in b[j1:j2]]
    return linhas


def _bloco(bloco):
    titulo = bloco["arquivo"]
    if antigo := bloco.get("arquivo_antes"):
        titulo = f"{antigo} → {titulo}"
    if bloco.get("demo"):
        link, link_txt = "", ""
        linhas = [{"tipo": "", "texto": linha} for linha in bloco["agora"].strip("\n").splitlines()]
    else:
        commit = bloco.get("commit")
        link = f"{FORK}/commit/{commit}" if commit else f"{FORK}/blob/dev/{bloco['arquivo']}"
        link_txt = f"commit {commit}" if commit else "ver na dev"
        linhas = _diff(bloco["antes"], bloco["agora"])
    return {"titulo": titulo, "nota": bloco.get("nota", ""), "link": link, "link_txt": link_txt,
            "linhas": linhas}


def _preparar(itens):
    prefixo = get_script_prefix()
    resultado = []
    for item in itens:
        item = dict(item)
        for chave in TEXTOS:
            if isinstance(item.get(chave), str):  # em EM_NUMEROS, antes/agora são números
                item[chave] = _partes(item[chave])
        if tela := item.get("tela"):
            nome, *args = (tela,) if isinstance(tela, str) else tela
            item["agora_url"] = reverse(nome, args=args)
            item["antes_url"] = f"{ANTERIOR}/{item['agora_url'][len(prefixo):]}"
        if codigo := item.get("codigo"):
            item["codigo"] = [_bloco(bloco) for bloco in codigo]
        resultado.append(item)
    return resultado


def _dividir(itens):
    itens = _preparar(itens)
    return [i for i in itens if i.get("codigo")], [i for i in itens if not i.get("codigo")]


def _com_barras(medidas):
    # Largura em % como texto: o SVG pede ponto decimal, e número passado ao template
    # sairia com vírgula. 1,5% de mínimo para a barra de "2" não sumir.
    resultado = []
    for m in _preparar(medidas):
        maior = max(m["antes"], m["agora"])
        resultado.append({**m, "barras": [
            {"rotulo": rotulo, "txt": m[f"{chave}_txt"], "agora": chave == "agora",
             "pct": f"{max(m[chave] / maior * 100, 1.5):.1f}"}
            for chave, rotulo in (("antes", "Antes"), ("agora", "Agora"))
        ]})
    return resultado


@login_required
def comparativo(request):
    correcoes_codigo, correcoes = _dividir(CORRECOES)
    interface_codigo, interface = _dividir(INTERFACE)
    engenharia_codigo, engenharia = _dividir(ENGENHARIA)
    return render(request, "vps/comparativo.html", {
        "nav_ativa": "comparativo",
        "anterior": f"{ANTERIOR}/crm/",
        "intro": _partes(INTRO),
        "rodape": _partes(RODAPE),
        "em_numeros": _com_barras(EM_NUMEROS),
        "n_correcoes": len(CORRECOES),
        "n_alto": sum(1 for c in CORRECOES if c.get("grave")),
        "correcoes_codigo": correcoes_codigo,
        "correcoes": correcoes,
        "novidades": _preparar(NOVIDADES),
        "interface_codigo": interface_codigo,
        "interface": interface,
        "engenharia_codigo": engenharia_codigo,
        "engenharia": engenharia,
        "base": _preparar(BASE),
        "do_original": _preparar(DO_ORIGINAL),
        "proximos": _preparar(PROXIMOS),
    })
