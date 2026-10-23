# Estado atual do projeto

**Revisão documental: 21/10/2026.** Voltar ao [README](../README.md) ou ao
[índice da documentação](README.md). Este registro diferencia código publicado,
trabalho local e ativação de serviços externos.

## Base da revisão

| Referência | Estado conferido |
|---|---|
| Repositório | Fork pública `VicZk/vo_testa`, branch `dev` |
| Base de código publicada revisada | [`3e30a11fa18ffbefb08136fa2b83ca4560dd8b1e`](https://github.com/VicZk/vo_testa/tree/3e30a11fa18ffbefb08136fa2b83ca4560dd8b1e) |
| Publicação seguinte | Décimo primeiro e décimo segundo blocos do [CHANGELOG](../CHANGELOG.md), no mesmo dia: os nove commits de interface listados abaixo, a Governança didática com a visão geral, o Estoque redesenhado e a usabilidade (copiar e mandar pelo WhatsApp, as ações da reserva numa barra, datas e valores corrigidos nos formulários) |
| Natureza da revisão documental | Documentação (`784c208`); a publicação de código veio no bloco seguinte |
| Produção e contas externas | Não consultadas nesta revisão |

As contagens e durações de testes nas auditorias e no changelog são evidências
datadas. Não foram reexecutadas como parte desta revisão de texto.

## Funcionalidades na base publicada

| Área | O que existe |
|---|---|
| Hospedagem | Reservas, grupos, disponibilidade, mapa, preços por temporada, camas extras, day use, FNRH/BOH, conta, check-in e check-out |
| Regras de venda | Restrições por período/tipo, sinal/cancelamento, tolerância de arredondamento e no-show configurável |
| Financeiro | Caixa por operador e módulo, conferência, estorno, adiantamento, crédito online, faturamento e devolução |
| Operação | Estoque e inventário, loja, restaurante, lavanderia, manutenção e escala |
| Governança | Visão geral da casa, lista com o ciclo do quarto e um próximo passo por linha, tarefas, arrumações, inspeção opcional, ronda, discrepâncias e três relatórios |
| Gestão | Pendências, trilha de auditoria, fechamento diário e conciliação OFX/cartão |
| Receita | Carteira de reservas (OTB), pickup, ritmo de vendas e custo de distribuição |
| Continuidade | Kit imprimível de hospedados/chegadas/saídas/quartos, envio diário opcional e backup por rotina |
| Atendimento | Comercial, oportunidades, cotações, atividades, WhatsApp, e-mail, LPs e campanhas |
| Público | Site, motor de reservas, portal por token, pré-check-in, extrato e solicitações |

Detalhes: [Especificação](ESPECIFICACAO.md) e [Módulos e fluxos](MODULOS_E_FLUXOS.md).
Complemento operacional de 22/10: recebimento com conversão de embalagens, lotes,
validade, perdas e fichas técnicas foram incorporados ao estoque. O
[manual de compras](ESTOQUE_COMPRAS.md) separa as funções do sistema do controle
auxiliar de solicitação/aprovação e da conferência financeira.
Quartos, temporadas e tabela de preços validam o envio completo antes de gravar.
Em erro, a edição permanece preenchida e o cadastro anterior fica preservado.
Na tabela, deixar uma tarifa inteira vazia remove a exceção; um campo ausente
na requisição não apaga as demais tarifas. Percentuais conservam duas casas.
O catálogo usa 27 ícones locais por nome/categoria, com escolha manual e prévia
no cadastro; Loja, Restaurante e Estoque compartilham essa identificação.
A estrutura inicial é de 24 quartos, quatro tipos técnicos de pernoite e quatro
unidades de day use ativas. Os cadastros efetivos da instalação determinam a operação.

## Integrações e limites

| Integração | Implementação | Limite de interpretação |
|---|---|---|
| Safrapay | Pix/cartão/boleto, diagnóstico de credenciais, timeout e tratamento de falhas | Evidências HML não comprovam liberação ou liquidação em produção |
| Pix direto | Código Pix gerado localmente e baixa manual | Não há webhook de confirmação desse Pix |
| FNRH Digital / Serpro | Adapter real e reenvio de pendências | Credenciais, códigos de cadastro e homologação precisam de validação |
| Fiscal (atualização 22/10) | Focus NFe v2, NFS-e por classificação de serviço e NFC-e de vendas/comandas; consulta, reenvio e cancelamento confirmados | Credenciais e homologação real pendentes; modo simulado não tem validade fiscal |
| WhatsApp (atualização 22/10) | Cloud API, mídia, webhook assinado e estados; provedores BSP indisponíveis | WABA, número, token, templates e entrega real dependem da conta |
| E-mail (atualização 22/10) | SMTP, SES e simulador sem envio externo | Envio exige provedor real configurado; aceitação não comprova entrega |
| Canais/OTAs (atualização 22/10) | Channex: mapeamento, fila durável, notificações assinadas, revisões de reservas e envio de disponibilidade/tarifas/restrições | Conexão desativada por padrão; contratação, credenciais e certificação/homologação reais pendentes; ver [guia](CANAIS.md) |
| Mídia paga | Meta CAPI e recursos de campanhas; Google é stub | Permissões, credenciais e resultados externos não foram conferidos |
| Decisão comercial | Simulador determinístico e adapter JEV | Contrato e disponibilidade do serviço externo precisam ser validados |
| R2, backup e monitor | Implementações opcionais por configuração | O código não comprova ativação nem restauração bem-sucedida de backup |

NPS possui coleta persistida pós-estadia, API autenticada por token/sessão, cálculo por período e acompanhamento no CRM. Veja `Proposta_NPS.md`.
CRM do Hóspede é evolução de catálogo. Telefonia/WebRTC continua
planejada. Frigobar foi removido do catálogo e não possui app ativo.

## Melhorias publicadas depois da revisão

Os nove commits abaixo existiam só no checkout local na hora da revisão documental e
foram publicados no décimo primeiro bloco do [CHANGELOG](../CHANGELOG.md), junto com o
Estoque redesenhado (`202a059` a `00b4d0a`, merge `1381a71`: posição com indicadores e
cartão por depósito, movimentação com prévia e chave de envio contra clique duplo,
contagem que aplica só o contado — migração `nucleo.0050`) e os commits `85543e0` e
seguintes:

| Commit local | Mudança |
|---|---|
| `6f66d4f` | Transição de navegação concentrada no conteúdo |
| `f649111` | Padronização dos tooltips |
| `fa79ddb` | Ajustes de textos da interface |
| `45f9417` | Melhor aproveitamento de monitores largos |
| `6eab595` | Ciclo de governança, próxima ação e fila da equipe |
| `e275059` | Nova visão geral gráfica de governança |
| `d2d858d` | Integração das melhorias de governança |
| `c218532` | Correção de acionamento duplicado por toque |
| `1f1aab6` | Refinos de governança no celular, textos e hover |

Este é um **snapshot datado**. A cada publicação de código, o CHANGELOG registra o
que entrou; atualize esta página quando a base revisada mudar.

## Como interpretar os documentos

- **README, especificação, arquitetura e módulos:** referência do código publicado.
- **Guias de integração:** código e passos de ativação; a matriz acima prevalece
  sobre planos ou resultados históricos mantidos nesses guias.
- **Checklists:** uma revisão textual não comprova homologação; itens sem evidência
  atual continuam pendentes de confirmação.
- **Auditorias, roteiros, estudos e evidências:** registros datados preservados para
  rastreabilidade, não atestados atuais de produção.
- **PDFs, DOCX, imagens e materiais de fornecedores:** referências da data de origem;
  não foram regenerados nesta revisão.
