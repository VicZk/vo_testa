# Canais e OTAs

O módulo prepara a distribuição pela Channex e mantém a disponibilidade física
no motor de Reservas. Inicia desativado, sem credenciais. Testes automatizados
usam respostas fictícias: não comprovam contratação, certificação do PMS,
homologação nem atualização real de Booking, Airbnb ou qualquer outro canal.

## Preparar a operação

1. Contratar/configurar o provedor e definir quem confere reservas e divergências.
2. Usar homologação em uma instalação isolada, com banco e pessoas fictícias.
   Habilitar Reservas e Canais, criar a conexão e informar estabelecimento,
   responsável e período de publicação. Manter vendas fechadas nesta etapa.
3. Cadastrar as categorias externas e os planos de tarifa. Esta versão mapeia um
   plano de tarifa por categoria, para uma ocupação definida. Uma unidade física
   só pertence a uma categoria na conexão; uma conexão fica ativa por vez.
4. Agrupar unidades com a mesma tarifa para a ocupação publicada. Definir limite
   e margem de segurança, conferir camas e verificar a prévia por data.
5. Ensaiar disponibilidade, preço, restrições, nova reserva, alteração e
   cancelamento conforme o roteiro atual do provedor. Registrar as evidências
   no módulo e conferir o resultado nas OTAs antes de abrir vendas.

O horizonte padrão é de 500 dias, ajustável entre 1 e 500. O envio usa o total
da cotação do PMS, inclusive tributos configurados. O plano
de tarifa externo deve corresponder à ocupação e ao preço bruto publicados.
Uma categoria com preços diferentes, camas não configuradas ou ocupação que
depende do estoque compartilhado de colchões fica sem oferta até o ajuste.

## Configuração do servidor

| Variável | Uso |
|---|---|
| `CHANNEX_API_KEY_HML` | Credencial do ambiente `https://staging.channex.io/api/v1` |
| `CHANNEX_API_KEY` | Credencial de produção em `https://app.channex.io/api/v1` |
| `CHANNEX_WEBHOOK_SECRET_HML` | Segredo HMAC das notificações de homologação |
| `CHANNEX_WEBHOOK_SECRET` | Segredo HMAC das notificações de produção |
| `CANAIS_HOMOLOGACAO_APLICAR` | Padrão `0`; `1` somente na instalação isolada para ensaiar a aplicação no PMS |
| `ROTINAS_MONITOR_CANAIS` | Monitor externo da rotina de um minuto |

As chaves ficam no ambiente do servidor, nunca nos formulários ou no repositório.
Registrar no provedor o webhook `canais:webhook`, com ambiente `homologacao` ou
`producao`; a URL inclui o prefixo da instalação. No prefixo `/votesta`, produção
usa `/votesta/crm/canais/webhook/producao/`. O webhook verifica
`x-hmac-timestamp` e `x-hmac-signature-256` sobre `timestamp.corpo-original`;
aceita as duas assinaturas de rotação e janela de cinco minutos.

Executar `python manage.py rotinas --grupo canais` a cada minuto, em um processo
separado das rotinas de dez minutos. O arquivo Railway está em
`deploy/railway.rotinas-canais.json`; na VPS, usar o agendador do serviço ativo.
Sem conexão ativa, o comando não chama a API. Há trava para impedir dois workers
simultâneos e nenhuma transação do banco permanece aberta durante chamadas HTTP.

## Recebimento e conferência

O aviso autenticado guarda somente as identidades do estabelecimento e da
revisão. O worker busca o conteúdo pelo feed autenticado, persiste os dados
operacionais e só então confirma a captura ao provedor. Repetição é idempotente;
revisões antigas não sobrescrevem a versão mais recente.

Por padrão, a equipe aplica as revisões pela fila. A aplicação automática é uma
opção explícita da conexão e exige validação da configuração. A operação inteira
de múltiplos quartos é atômica: falta de vaga não deixa uma reserva parcial.

Moeda diferente de real, recebimento pela OTA, serviços/tributos adicionais,
idades ausentes, alteração de quarto/identidade, intervenção da recepção ou
financeiro já vinculado exigem conferência manual. A equipe ajusta o PMS e
informa as reservas correspondentes; datas, composição, categoria e valor são
verificados antes de resolver a pendência. Cancelamento não produz estorno de
dinheiro automaticamente. O vínculo manual preserva a trilha de cada revisão.

Dados de cartão, garantia e notas livres do provedor não são persistidos. Reserva
externa não autoriza e-mail/WhatsApp comercial e não cria recebimento no caixa.
Homologação permanece separada das reservas operacionais, salvo a opção explícita
na instalação isolada indicada acima.

## Publicação e falhas

Reservas, tarifas, restrições, camas, unidades e bloqueios de manutenção alimentam
uma geração durável dentro da transação. Mudanças durante o envio continuam
pendentes para a rodada seguinte. O worker também consulta o feed periodicamente
e renova o período na virada do dia; sem alterações não recompõe o mapa inteiro.

A publicação sequencia fechamento de disponibilidade, tarifas/restrições e
reabertura das quantidades calculadas. Uma falha no feed ou pendência de reserva
mantém a oferta calculada zerada. Se a API estiver indisponível, o sistema não
consegue garantir o fechamento remoto: o responsável deve conferir os canais.
Falhas repetidas aguardam 1, 2, 4, 8, 16 e depois 30 minutos; um pedido manual não
ignora essa espera. Nenhum envio interrompido é tratado como concluído.

“Aceito pelo provedor” significa que as tarefas foram recebidas. A tela separa
esse estado da conferência feita pela equipe nas OTAs. Alterar credenciais,
responsável, horizonte ou mapeamento invalida a validação anterior. Para encerrar
uma conexão publicada, fechar vendas, aguardar o envio, conferir os canais e
registrar o resultado antes de desligá-la; o módulo respeita a mesma sequência.

Até a homologação real, manter vendas externas fechadas ou adotar conferência
manual nominal por turno, com responsável e limite de unidades definido. Nenhum
operador deve presumir atualização automática com base apenas na presença de
credenciais ou no aceite de uma tarefa.

## Evidências de implementação

Os testes cobrem transporte, seleção de dados, repetição, ordem de revisões,
recebimento após commit, aplicação atômica, disputa pela última unidade,
notificações HMAC, retomada, espera progressiva, alterações durante HTTP,
permissões e fluxos no navegador. As telas são medidas em 320, 390, 414, 768,
821 e 1440 pixels, incluindo nomes extensos e preservação de formulários.
As contagens da suíte e a versão efetivamente publicada pertencem ao registro
da entrega, não à configuração externa do provedor.

Referências oficiais consultadas em 22/10/2026: [certificação PMS](https://docs.channex.io/api-v.1-documentation/pms-certification-tests),
[boas práticas](https://docs.channex.io/guides/best-practices-guide),
[reservas](https://docs.channex.io/api-v.1-documentation/bookings-collection),
[ARI](https://docs.channex.io/api-v.1-documentation/ari),
[webhooks](https://docs.channex.io/api-v.1-documentation/webhook-collection).
