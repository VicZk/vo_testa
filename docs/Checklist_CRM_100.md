# Checklist de ativação e operação — CRM Vô Testa

**Revisão documental: 26/10/2026.** Consulte o [Estado atual](ESTADO_ATUAL.md) para a
base de código revisada. Este checklist separa implementação de comprovação no
ambiente da pousada. Itens desmarcados significam **a confirmar**, não necessariamente
que nunca tenham sido executados.

## 1. O que já existe no código

| Frente | Implementado | Verificação operacional necessária |
|---|---|---|
| Hospedagem | Reserva, grupos, capacidade, FNRH local/BOH, conta e saída | Jornadas com os cadastros, tarifas e regras reais |
| Financeiro | Caixa, recebimentos, estornos, devolução, faturamento e conciliação | Conferência das origens de crédito e fechamento |
| Governança | Tarefas, arrumação, inspeção opcional, ronda e discrepâncias | Fluxo da equipe, liberação de quartos e retrabalho |
| Gestão | Relatórios, pendências, trilha e fechamento diário | Datas, indicadores, exportação e acesso de gerência |
| Contábil/gerencial | Plano de contas, de-para, DRE, fluxo de caixa, fechamento mensal e exportação para o contador | Plano e de-para conferidos com o contador; primeiro fechamento do mês |
| Day pass | Turnos, capacidade, visitantes, caixa e comandas | Capacidade e preços reais (o sistema não presume capacidade física) |
| Comercial/marketing | Funil, cotações, atividades, LPs, e-mail e campanhas | Políticas comerciais, consentimentos e canais ativos |
| Site/portal | Motor de reservas, pré-check-in, extrato e solicitações | Jornada completa em desktop e celular |
| Continuidade | Kit, envio diário opcional e backup | Agendamento, destinatários, recebimento e restauração |

A validação do caixa em 04/07/2026 e as demais auditorias são registros históricos.
Não são marcações automáticas de aprovação para o commit ou ambiente atual.

## 2. Integrações externas

### Pagamentos

- [ ] Confirmar credenciamento, ambiente e token Safrapay; conferir o diagnóstico do CRM.
- [ ] Validar criação, recusa, confirmação, webhook e reflexo na reserva/conta.
- [ ] Conferir estorno/devolução e conciliação conforme origem do recebimento.
- [ ] Se usar Pix direto, confirmar chave/destinatário e treinar a baixa **manual**;
      o botão do hóspede avisando que pagou não comprova recebimento.
- [ ] Para maquininha, conferir lançamento de NSU/autorização e conciliação.

O adapter Safrapay está escrito. As [evidências HML](Implementar_Safrapay.md)
não comprovam habilitação ou liquidação no ambiente de produção.

### WhatsApp e e-mail

- [ ] Conferir WABA, número, token, Phone Number ID, App Secret e templates necessários.
- [ ] Validar webhook, recebimento, envio e mídia com destinatário de teste autorizado.
- [ ] Conferir consentimento/descadastro e responsável pelo atendimento.
- [ ] Validar SMTP, remetente autenticado, Reply-To e reenvio de pendências.
- [ ] Para enviar de verdade, `EMAIL_GATEWAY=smtp` ou `ses`. O padrão, `simulado`,
      não envia nada.

Cloud API e áudio têm implementação. O painel completo de campanhas WhatsApp é
backlog; há comando manual. `delivered`/`read` como estados próprios da mensagem
continuam evolução. SMTP e SES estão implementados; provedores BSP do WhatsApp, não.

### FNRH e fiscal

- [ ] Conferir fichas, códigos de país/cidade e a trava de check-in.
- [ ] Validar credenciais Serpro, homologação, envio e reprocessamento de pendências.
- [ ] Reconfirmar os parâmetros fiscais com o contador (regime: Lucro Presumido).
- [ ] Spedy (NFS-e): conta, chave de API (`SPEDY_API_KEY`), certificado A1 cadastrado
      na Spedy, segredo do retorno (`SPEDY_WEBHOOK_SECRET`) e `FISCAL_GATEWAY=spedy`.
- [ ] Emitir, consultar e cancelar uma NFS-e no sandbox (`SPEDY_SANDBOX=1`, o padrão)
      antes de passar para produção (`SPEDY_SANDBOX=0`).
- [ ] NFC-e (loja e restaurante): depende da inscrição estadual. Pelo Spedy, o sistema
      ainda não emite; o Focus NFe (`FISCAL_GATEWAY=focus`) tem a NFC-e implementada.
- [ ] Homologar emissão, retorno, falha e cancelamento antes da ativação fiscal real.

Campos tributários e simulador não equivalem a nota autorizada.
Guias: [FNRH](Implementar_FNRH_API.md), [Fiscal](Implementar_fiscal.md) e
[Checklist do contador](Checklist_contador.md).

### Canais (OTAs)

- [ ] Contratar o Channex e conferir as chaves (`CHANNEX_API_KEY` e
      `CHANNEX_WEBHOOK_SECRET`; as de homologação terminam em `_HML`).
- [ ] Mapear quartos e tarifas e conferir a fila de revisões antes de ligar a conexão,
      que começa desligada.
- [ ] Cumprir a certificação do provedor. Guia: [Canais](CANAIS.md).

### Mídia, decisão e serviços auxiliares

- [ ] Conferir tokens/permissões Meta e validar conversões quando utilizados.
- [ ] Validar URL, contrato e disponibilidade JEV se o adapter real for ativado.
- [ ] Conferir R2, URLs de mídia e persistência dos uploads.
- [ ] Confirmar destinatários e recebimento do kit de contingência.

## 3. Dados, acessos e jornadas

- [ ] Conferir as 24 UHs, day use ativo, capacidade, camas, colchões e berços.
- [ ] Validar tarifas, temporadas, restrições de venda, cancelamento e no-show.
- [ ] Revisar fotos, nomes, qualidades e destaques da vitrine.
- [ ] Cadastrar a equipe com módulos/áreas necessários e validar MFA.
- [ ] Percorrer reserva → sinal → FNRH → check-in → consumo → pagamento/faturamento → saída.
- [ ] Percorrer governança → execução → inspeção/retrabalho → quarto disponível.
- [ ] Validar venda avulsa e consumo na conta em loja, restaurante e lavanderia.
- [ ] Conferir manutenção/bloqueio, escala, conciliação e relatórios.
- [ ] Conferir o plano de contas e o de-para com o contador, lançar o primeiro
      fechamento mensal e abrir no Excel o CSV que vai para ele.
- [ ] Validar desktop, celular, teclado, toque e impressão dos documentos utilizados.

## 4. Rotinas e publicação

- [ ] Conferir branch, remoto, diff e escopo autorizado antes de commit/push.
- [ ] Para código, conferir lint, migrações, suíte Django e fluxos de navegador afetados.
- [ ] Conferir o workflow "Segurança" (`security.yml`) verde no commit publicado.
- [ ] Confirmar serviço/branch de deploy, versão ativa e healthcheck.
- [ ] Confirmar serviços cron dos grupos `frequentes` e `diarias`.
- [ ] Validar monitor de começo/fim/falha e alerta por execução ausente.
- [ ] Verificar fechamento diário, arrumações, expirações e reenvios.
- [ ] Confirmar destino de backup e testar restauração em banco separado.
- [ ] Registrar data, commit, ambiente, responsável e resultado de cada homologação.

Comandos de rotina e seeds alteram dados e podem enviar comunicações quando
configurados. Não os execute como simples teste de leitura de ambiente.

## 5. Evolução separada da ativação

Continuam no backlog: CRM do Hóspede, telefonia integrada, painel completo de
campanhas WhatsApp, a comissão de OTA no Contábil (que espera a conexão de Canais) e os
stubs listados no [Estado atual](ESTADO_ATUAL.md), como o Google Ads. A coleta de NPS e a
conexão com Canais/OTAs já existem e saíram do backlog.
