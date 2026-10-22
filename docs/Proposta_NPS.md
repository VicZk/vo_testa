# NPS pós-estadia — Portal do Hóspede e CRM

A coleta está implementada em `apps/nps`, com resposta persistida por estadia,
painel por período, cálculo de NPS e registro de acompanhamento pela equipe.
A janela padrão é de 90 dias depois do check-out efetivo (`NPS_JANELA_DIAS`).

O envio exige consentimento explícito e voluntário para uso da avaliação pela equipe e contato sobre o relato. A versão do texto aceito e a data da resposta ficam registradas. A API exige `consentimento: true`, inclusive em lançamentos pela recepção. Isso não concede opt-in de marketing.

## Fluxo operacional

1. A equipe abre Relacionamento → NPS e obtém o link de uma estadia encerrada.
2. O hóspede abre `/hospede/<token>/nps/`, informa nota de 0 a 10 e comentário opcional.
3. A primeira opinião fica preservada. Repetir o mesmo envio é idempotente;
   tentar substituir a opinião retorna conflito.
4. A equipe filtra o período e registra o contato e as providências no acompanhamento.

O portal da estadia encerrada direciona à pesquisa. Pedidos e outros serviços da
estadia continuam indisponíveis após o check-out. Tokens rotacionados, inexistentes
ou fora da janela não concedem acesso. O link não é publicado nem enviado automaticamente.

## Contrato da API

| Método e endereço | Autenticação | Resultado |
|---|---|---|
| `POST /api/nps/v1/respostas/` | `token` opaco no JSON ou sessão da equipe com CSRF e área NPS | 201 criada; 200 repetição igual; 409 tentativa de alteração |
| `GET /api/nps/v1/respostas/<reserva_id>/` | Sessão CRM com área NPS | Resposta da estadia ou 404 |
| `GET /api/nps/v1/resumo/?de=YYYY-MM-DD&ate=YYYY-MM-DD` | Sessão CRM com área NPS | Contagens e score do período |

Corpo de criação: `token` (ou `reserva_id` para equipe), `nota`, `comentario`
opcional e `canal` (`portal`, `email`, `whatsapp`, `equipe`). O canal `equipe`
exige sessão interna. A API rejeita JSON que não seja objeto, corpos acima de
16 KiB, notas fracionárias, valores fora de 0–10 e comentários acima de 2.000
caracteres. Dados inválidos retornam 400; estadias inelegíveis retornam 404.
As superfícies públicas exigem o módulo Portal ativo. Há limite de tentativas,
CSRF no formulário público e proteção de cache nas respostas.

## Cálculo e integridade

`NPS = 100 × (promotores − detratores) / total`. Promotores: 9–10; passivos:
7–8; detratores: 0–6. Sem respostas, o score é nulo, exibido como traço.
A reserva é travada durante o registro, e a relação única impede duplicidade.
Acompanhamento registra texto, data e operador, preservando a opinião do hóspede.
O envio automático de convites e campanhas por faixa são evoluções separadas.
