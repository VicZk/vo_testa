# Checklist de ativação e operação — CRM Vô Testa

**Revisão documental: 21/10/2026.** Consulte o [Estado atual](ESTADO_ATUAL.md) para a
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
- [ ] Conferir a configuração antes de qualquer teste de campanha:
      `EMAIL_GATEWAY=simulado` pode enviar por SMTP real.

Cloud API e áudio têm implementação. O painel completo de campanhas WhatsApp é
backlog; há comando manual. `delivered`/`read` como estados próprios da mensagem
continuam evolução. SES e BSP são stubs.

### FNRH e fiscal

- [ ] Conferir fichas, códigos de país/cidade e a trava de check-in.
- [ ] Validar credenciais Serpro, homologação, envio e reprocessamento de pendências.
- [ ] Reconfirmar parâmetros fiscais com o contador e requisitos do provider escolhido.
- [ ] Implementar o provider fiscal real: `focus` e `governo` ainda são stubs.
- [ ] Homologar emissão, retorno, falha e cancelamento antes da ativação fiscal real.

Campos tributários e simulador não equivalem a nota autorizada.
Guias: [FNRH](Implementar_FNRH_API.md), [Fiscal](Implementar_fiscal.md) e
[Checklist do contador](Checklist_contador.md).

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
- [ ] Validar desktop, celular, teclado, toque e impressão dos documentos utilizados.

## 4. Rotinas e publicação

- [ ] Conferir branch, remoto, diff e escopo autorizado antes de commit/push.
- [ ] Para código, conferir lint, migrações, suíte Django e fluxos de navegador afetados.
- [ ] Confirmar serviço/branch de deploy, versão ativa e healthcheck.
- [ ] Confirmar serviços cron dos grupos `frequentes` e `diarias`.
- [ ] Validar monitor de começo/fim/falha e alerta por execução ausente.
- [ ] Verificar fechamento diário, arrumações, expirações e reenvios.
- [ ] Confirmar destino de backup e testar restauração em banco separado.
- [ ] Registrar data, commit, ambiente, responsável e resultado de cada homologação.

Comandos de rotina e seeds alteram dados e podem enviar comunicações quando
configurados. Não os execute como simples teste de leitura de ambiente.

## 5. Evolução separada da ativação

Continuam no backlog: coleta NPS/CRM do Hóspede, Canais/OTAs, telefonia integrada,
painel completo de campanhas WhatsApp e os providers/stubs listados no
[Estado atual](ESTADO_ATUAL.md). Os commits locais de interface identificados naquela
revisão foram publicados depois, no décimo primeiro bloco do [CHANGELOG](../CHANGELOG.md).
