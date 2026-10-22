# Integração com a API FNRH Digital (Embratur/Serpro)

**Revisado em 22/10/2026:** adapter implementado contra o [contrato oficial REST v2](https://fnrh.turismo.serpro.gov.br/FNRH_API/rest/v2/swagger.json), com criação, entrada, saída, cancelamento, no-show e reenvio de pendências. Os testes de contrato usam transporte substituído; a homologação com credenciais do estabelecimento continua necessária.

Fonte: [Documentação da API FNRH v2 (gov.br, 09/03/2026)](https://www.gov.br/turismo/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/ficha-nacional-de-registro-de-hospedes/modulo-meio-de-hospedagem/meios-de-hospedagem-com-pms/documentacao-api-v2-20260309.pdf)

## Como funciona a API

- **Autenticação:** HTTP Basic Auth (`usuário:senha` → Base64). Sem certificado A1.
- **Base URLs:**
  - Produção: `https://fnrh.turismo.serpro.gov.br/FNRH_API/rest/v2`
  - Homologação: `https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2`
- **Fluxo (estratégia B — empurramos nossos dados):**
  1. `POST /reservas` → devolve `reserva_id`
  2. `POST /pessoas` (por hóspede) → devolve `pessoa_id`
  3. `POST /reservas/{id}/hospedes` (com bloco `fnrh`: motivo + transporte)
  4. `POST /reservas/{id}/checkin` (lote) — e `/checkout`, `/cancelar`, `/noshow`
- **Domínios** (`GET /dominios/...`): listas canônicas de códigos (motivo, transporte,
  gênero, tipo de documento, etc.). Os choices de `FichaFNRH` **já usam esses ids**
  como valor — sem de-para.

## O que já está pronto no CRM

- `apps/reservas/fnrh_gateway.py` — `simulado` + `serpro` (HTTP real via urllib) + de-para.
- `services.enviar_fnrh(reserva)` — orquestra, idempotente, best-effort.
- Gatilhos: entrada, saída, cancelamento, no-show e alterações da reserva marcam pendência; o cron reprocessa.
- Os identificadores de reserva, pessoa e vínculo são persistidos a cada etapa. Uma trava temporária impede envio simultâneo. Confirmações perdidas são conciliadas por consulta antes de repetir criação.
- Entrada e saída enviam os horários reais registrados, como `text/plain`, e confirmam o estado remoto por consulta. Alterações da reserva usam `PUT /reservas/{id}`. O contrato não oferece atualização de pessoa: correções pessoais já enviadas precisam de conciliação na plataforma oficial.
- Campos de sincronização em `Reserva` e `FichaFNRH`.
- Cron: `manage.py enviar_fnrh_pendentes` (rodar a cada poucos minutos).
- UI: status + botão "Reenviar" no detalhe da reserva.

## Para ligar em produção

1. **Obter credenciais SNRHos** (usuário/senha) — cadastro do estabelecimento no sistema
   do Ministério do Turismo, via Cadastur.
2. **Testar em homologação** primeiro:
   ```env
   FNRH_GATEWAY=serpro
   FNRH_API_URL=https://hom-lowcode.serpro.gov.br/FNRH_API/rest/v2
   FNRH_API_USER=...
   FNRH_API_SENHA=...
   FNRH_CPF_SOLICITANTE=...
   ```
3. **Conferir os cadastros:** nacionalidade e país de residência usam códigos ISO separados; país desconhecido gera pendência, sem assumir Brasil. Cidade brasileira exige código IBGE. O CPF do solicitante deve estar autorizado para o estabelecimento.
4. **Virar a chave** para produção (`FNRH_API_URL` de produção) após validar em HML.

## Checklist de campos por hóspede (mínimo aceito)

nome · data_nascimento · tipo+número de documento (CPF nacional / PASSAPORTE estrangeiro)
· país (ISO) · motivo da viagem · meio de transporte · is_principal (titular).

## Ambientes e conciliação

O CRM distingue simulação, homologação e produção. Ao sair de uma origem reconhecidamente simulada, descarta os identificadores sintéticos. Identificadores antigos sem origem ou de outra base bloqueiam o envio até conciliação.

`manage.py conciliar_fnrh_legado --reserva ID --origem simulado` mostra a proposta sem alteração. Para origem `serpro`, consulta e confere o código remoto `VT-ID`. Somente `--aplicar` registra a origem. Não classifique identificadores reais como simulados.

Antes de ativar, ensaie brasileiro residente no exterior, estrangeiro residente no Brasil, titular e acompanhantes; repetição do envio, horários de entrada/saída, cancelamento, no-show e retomada após interrupção. Confira os resultados na plataforma oficial. Os testes automatizados não enviam dados ao governo.
