# Documentação do projeto

**Revisada em 21/10/2026.** Este índice cobre os arquivos Markdown do repositório e
identifica o papel dos materiais complementares. Para entender o sistema, comece
pelo [README principal](../README.md) e pelo [Estado atual](ESTADO_ATUAL.md).

**Referência atual** descreve código e operação prevista. **Plano** contém trabalho
futuro ou passos de ativação. **Histórico** preserva decisões e evidências da data
original. Uma checklist marcada ou um teste antigo não comprova o ambiente atual.

## Produto, arquitetura e desenvolvimento

| Documento | Uso |
|---|---|
| [Estado atual](ESTADO_ATUAL.md) | Base de código, diferenças locais, integrações e limites |
| [Especificação](ESPECIFICACAO.md) | Escopo funcional implementado e evolução |
| [Arquitetura](ARQUITETURA.md) | Stack, configuração, interfaces, operação e desenvolvimento |
| [Módulos e fluxos](MODULOS_E_FLUXOS.md) | Models, estados, services, telas e fluxos ponta a ponta |
| [Convenções de desenvolvimento](../CLAUDE.md) | Regras de código, UI e publicação |
| [Changelog](../CHANGELOG.md) | Histórico de entregas; evidências pertencem à versão registrada |
| [Revisão de usabilidade de 22/10](REVISAO_USABILIDADE_2026-10-22.md) | Revisão em andamento, cobertura por fluxo e evidências das entregas |
| [Checklist de ativação](Checklist_CRM_100.md) | Verificações da instalação, integrações e operação |
| [Ideias](IMPLEMENTAR_Ideias.md) | Backlog; não representa funcionalidade concluída |

## Integrações e operação

| Documento | Classificação e leitura |
|---|---|
| [FNRH Digital](Implementar_FNRH_API.md) | Guia de integração; adapter escrito, ativação/homologação a validar |
| [Safrapay](Implementar_Safrapay.md) | Guia e evidências HML datadas; não atesta produção |
| [Decisão SafraPay](SafraPay/DECISAO.md) | Histórico da estratégia de contratação e maquininha |
| [Pacote de evidências Safrapay](../evidencias/safrapay/README.md) | Registro HML de 01/10/2026 |
| [Resposta Safrapay](../evidencias/safrapay/Resposta_Safrapay_2026-10-01.md) | Texto de resposta preparado naquela homologação |
| [Fiscal](Implementar_fiscal.md) | Plano e dados fiscais históricos; providers reais ainda pendentes |
| [Checklist do contador](Checklist_contador.md) | Perguntas e parâmetros para validação contábil atual |
| [Produtos para NCM](Produtos_para_NCM.md) | Modelo de levantamento; não substitui classificação fiscal validada |
| [WhatsApp Meta](Implementar_WhatsApp_Meta.md) | Procedimento de ativação; validar estado da conta e API |
| [CRM e WhatsApp](Marketing/CRM_WhatsApp.md) | Fluxos e evolução da integração |
| [Áudio WhatsApp](WhatsAppAPI/Plano_Audio_WhatsApp.md) | Plano com implementação incorporada; consultar código e matriz atual |
| [Campanhas/opt-in WhatsApp](WhatsAppAPI/Plano_Campanhas_e_Optin_WhatsApp.md) | Backlog de painel/captação; há comando manual de campanha |
| [Evidência WhatsApp 141008](Evidencia_WhatsApp_141008.md) | Registro histórico de erro externo |
| [E-mail](PLANEJAMENTO_EMAIL.md) | Planejamento e decisões; SMTP Django existe, SES é stub |
| [E-mail de leads](Marketing/Gestor_email_leads_funil.md) | Fluxo implementado e plano de evolução |
| [E-mail em massa](Marketing/Gestor_Email_MKT_Massa.md) | Campanhas implementadas; provider SES ainda pendente |
| [Impulsionamento](Marketing/Gestor_Impulsionamento_CRM.md) | Recursos implementados e fases futuras de mídia |
| [Landing pages](Marketing/Gestor_LPs.md) | Guia/plano do gestor de LPs e captação |
| [JEV](JEV_CRM_TEST.md) | Plano de validação do adapter de decisão; serviço externo a confirmar |
| [Telefonia de vendas](Implementar_Telefonia_Vendas.md) | Projeto futuro; não há app operacional de telefonia |
| [Estrutura NAS](Estrutura_NAS.md) | Referência de infraestrutura externa; não é inventário verificado |

## Hospedagem e estrutura física

| Documento | Classificação e leitura |
|---|---|
| [Configuração dos quartos](Reservas/CONFIGURACAO_QUARTOS.md) | Decisões de capacidade e montagem incorporadas ao modelo |
| [Estoque de colchões](Reservas/PLANO_ESTOQUE_COLCHOES.md) | Plano e registro de implementação; conferir inventário real |
| [Descritivo dos quartos](Descritivo_Quartos/descritivo-quartos-vo-testa.md) | Referência física/comercial; não é snapshot atual do banco |
| [Parâmetros CRM](Descritivo_Quartos/Parametros_CRM.md) | Proposta histórica de modelagem; prevalecem especificação e código atuais |
| [Descritivo na conversa](Descritivo_Quartos/DESCRITIVO-NA-CONVERSA.md) | Notas históricas que acompanham o material original |
| [Precificação](Precificação/precificação.md) | Estudo comercial datado; tarifas vigentes devem ser consultadas no CRM |

## Comercial e marketing

| Documento | Classificação e leitura |
|---|---|
| [Plano comercial](Plano_Comercial.md) | Estratégia e decisões de operação |
| [Manual da vendedora](Comercial/Manual_Vendedora.md) | Referência operacional; alinhar com políticas e configuração vigentes |
| [Religar funil — fase 6](Comercial/Religar_Funil_Fase6.md) | Checklist/procedimento de uma etapa específica |
| [Plano de inauguração](Marketing/Plano_Marketing_Inauguracao.md) | Campanha e planejamento datados; não confirma agenda realizada |
| [Calendário editorial](Marketing/Calendario_Editorial_Inauguracao.md) | Planejamento editorial da campanha |
| [Base MKT](Marketing/MKT/README.md) | Índice de conhecimento comercial, com limites dos snapshots |
| [Serviços e preços](Marketing/MKT/01_servicos_e_precos.md) | Referência comercial; confirmar tarifas e disponibilidade no CRM |
| [Guia de marca](Marketing/MKT/02_guia_de_marca.md) | Identidade, tom e público |
| [Leads e funil](Marketing/MKT/03_leads_e_funil.md) | Leitura/exportação de snapshot; dados pessoais não são documentação pública |
| [LP Fundador](Marketing/MKT/04_lp_fundador.md) | Estratégia e copy da campanha |
| [Calendário MKT](Marketing/MKT/05_calendario.md) | Calendário planejado; conferir datas antes de uso |
| [Proposta NPS](Proposta_NPS.md) | Backlog, sem coleta persistida implementada |

## Auditorias, estudos e roteiros históricos

| Documento | Escopo original |
|---|---|
| [Auditoria CRM](Auditoria_CRM.md) | Achados e entregas da auditoria registrada |
| [Auditoria de layout](Auditoria_Layout_CRM.md) | Revisão de interface da época |
| [Auditoria de segurança](Auditoria_Seguranca_CRM.md) | Revisão técnica com evidências datadas |
| [Threat model de pagamentos/FNRH](pagamentos-fnrh-threat-model.md) | Modelo de ameaças e decisões da revisão original |
| [Referência Desbravador](REFERENCIA_DESBRAVADOR.md) | Pesquisa externa da época; não representa oferta atual do fornecedor |
| [Roteiro de design](../ROTEIRO.md) | Handoff e etapas históricas de implementação |
| [Roteiro de marketing](../ROTEIRO-MARKETING.md) | Plano original; diversas funcionalidades já foram implementadas |
| [Prompt de handoff](Marketing/marketing_handoff/PROMPT.md) | Material histórico de delegação, não instrução operacional atual |

## Materiais complementares e manutenção

PDFs, DOCX, imagens, planilhas de referência e anexos de fornecedores permanecem
como materiais da data original. Não foram regenerados nesta revisão. A documentação
em Markdown acima é o mapa para interpretar esses arquivos.

Ao alterar uma regra, atualize a especificação e o fluxo correspondente. Ao concluir
uma integração, registre separadamente implementação, homologação e ambiente ativo.
Ao publicar código, registre a nova base no Estado atual.
Mantenha evidências antigas datadas; não reescreva resultados passados como testes novos.

Não inclua `.env`, credenciais, bancos, logs, CSVs/JSONs com hóspedes ou leads reais
em documentação pública. Use exemplos sintéticos para demonstrar comandos e fluxos.
