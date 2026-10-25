# Emissão fiscal — CRM Pousada Vô Testa

Estado do código em 25/10/2026. Há dois adaptadores: Focus NFe v2 (NFS-e Nacional e
NFC-e) e Spedy (NFS-e pelo Ambiente Nacional). A operação real depende do cadastro do
emitente no provedor, credenciais, parâmetros revisados e ensaio no ambiente escolhido.
Testes automatizados com respostas controladas não comprovam homologação fiscal.

## Configuração

Escolha `FISCAL_GATEWAY=focus` ou `FISCAL_GATEWAY=spedy`. O modo `simulado` produz
documentos de demonstração sem validade fiscal. Integração direta com o governo e outros
provedores não estão disponíveis neste código; nomes desconhecidos geram erro explícito.

### Focus NFe

| Variável | Uso |
| --- | --- |
| `FISCAL_FOCUS_URL` | `https://homologacao.focusnfe.com.br` ou `https://api.focusnfe.com.br` |
| `FISCAL_FOCUS_TOKEN` | Token do emitente e ambiente; não incluir em código, relatórios ou prints |
| `FISCAL_EMITENTE_CNPJ` | CNPJ do emitente cadastrado no provedor |
| `FISCAL_MUNICIPIO_IBGE` | Município de emissão e prestação no perfil disponível (Itá/SC: `4208005`) |
| `FISCAL_DPS_SERIE` | Série exclusiva deste sistema, entre 1 e 49999 |
| `FISCAL_DPS_NUMERO_INICIAL` | Início da faixa reservada; o número usa a base mais o ID do documento menos um |
| `FISCAL_NFSE_CODIGO_SERVICO` | Código nacional de seis dígitos para hospedagem |
| `FISCAL_NFSE_COMPLEMENTOS` | Objeto JSON de complementos revisados pelo responsável fiscal |
| `FISCAL_NFCE_HABILITADA` | Padrão 0; habilitar após cadastro do emitente, IE, CSC e certificado no provedor |
| `FISCAL_WEBHOOK_TOKEN` | Segredo do header `Authorization` no retorno para `/crm/fiscal/webhook/` |

### Spedy

| Variável | Uso |
| --- | --- |
| `SPEDY_API_KEY` | Chave da empresa no ambiente (header `X-Api-Key`); não incluir em código, relatórios ou prints |
| `SPEDY_SANDBOX` | Padrão 1 (`sandbox-api.spedy.com.br`); 0 = produção (`api.spedy.com.br`) |
| `SPEDY_WEBHOOK_SECRET` | Segredo da conta (`whsec_…`, `GET /v1/webhooks/secret`) que assina os retornos |
| `FISCAL_NFSE_CODIGO_SERVICO` | Código nacional da hospedagem (`090101`), enviado em `nationalTaxationCode` |
| `FISCAL_NFSE_LC116` | Item da LC 116 da hospedagem (`9.01`), em `federalServiceCode`; os outros serviços usam o item tirado do próprio código |
| `FISCAL_NFSE_ISS_ALIQUOTA` | ISS em % (`4.0`), em `total.issRate` |

No Spedy, a emissão é assíncrona: o POST só aceita a nota, e o documento fica
**Processando** até o retorno (`invoice.status_changed`) ou a consulta. A referência do
sistema vai em `integrationId` (até 36 caracteres): reenviar com ela atualiza a mesma
nota, sem criar outra, e é assim também que se corrige uma rejeição de cadastro. O id do
Spedy volta na resposta e fica guardado para consultar, cancelar e montar os links de
PDF e XML. O retorno só é aceito com a assinatura do Spedy (`webhook-id`,
`webhook-timestamp` e `webhook-signature`: HMAC-SHA256 com o segredo da conta, até 5
minutos de diferença no carimbo). Entrega atrasada de "na fila" não desfaz um fecho, e
nota de outro sistema da mesma conta é ignorada. O cancelamento também é assíncrono: o
pedido entra na trilha de auditoria (quem, quando e por quê) e a nota só fica
**Cancelada** com a confirmação. A NFC-e pelo Spedy ainda não existe (espera a IE).
Preço de entrada levantado em out/2026: R$ 74/mês com 1.800 notas/ano, sandbox grátis.

### Emitente e regime

Dados do contrato social (2ª alteração, JUCESC 02/09/2026) e do comprovante de inscrição
municipal de Itá, também em `settings.EMPRESA_*`: POUSADA VO TESTA LTDA (fantasia POUSADA
VÔ TESTA) · CNPJ 26.003.246/0001-00 · Inscrição Municipal 4829 · sem Inscrição Estadual ·
Lago Azul, Itá/SC · município IBGE `4208005` (não 4208302, que é Itapema) · CEP
89760-000 · CNAE 55.10-8-01 (Hotéis) · Ltda unipessoal · porte ME.

O perfil NFS-e disponível usa Lucro Presumido, confirmado pelo contador em out/2026 (CST,
não CSOSN; PIS 0,65% e COFINS 3% cumulativos), operação tributável sem retenção e
prestação no município configurado. Outros enquadramentos precisam de adaptação
validada; não basta alterar um rótulo. Hospedagem `090101` e ISS de 4% vêm dos dados de
julho de 2026; sem IE, a NFC-e fica bloqueada. Confira o
[checklist contábil](Checklist_contador.md).

No Contábil, o tributo sobre a receita do "Fechar o mês" é PIS/COFINS/ISS (conta
`3.1.02.01`, "(-) Impostos sobre a receita"). O pró-labore fica em R$ 0: o contrato
(cláusula 16ª) não prevê pró-labore, e o sócio se remunera por distribuição de lucros,
que não é despesa.

O ambiente (URL ou sandbox/produção), o CNPJ emitente e o provedor ficam vinculados ao
documento. Trocar o ambiente não permite consultar ou cancelar documentos antigos no
ambiente novo. O token ou a chave podem ser rotacionados para a mesma conta; confira a
identidade do emitente ao fazer isso.

## NFS-e da conta

Na reserva ou no grupo, use **Preparar NFS-e**. As diárias usam a classificação
configurada para hospedagem. Lavanderia e demais serviços exigem classificação
explícita pela gerência, conferida com o responsável fiscal. O sistema agrupa os
lançamentos por código e emite uma nota por grupo. Produtos de consumo não entram
nessa nota. Taxas da conta não são automaticamente tratadas como hospedagem.

Descontos são distribuídos entre os grupos e itens em centavos, mantendo o total.
A emissão guarda os IDs dos lançamentos, valores, classificação e dados enviados.
Classificações ficam bloqueadas quando já existe documento não cancelado para a conta.
O cadastro do tomador deve conter nome e CPF/CNPJ. O sistema não inventa documento.

## NFC-e de venda ou comanda

A origem deve estar fechada. Use **Cadastro fiscal de produtos**, no painel Fiscal,
para preencher NCM, CFOP, CST/CSOSN, origem, PIS, COFINS e complementos orientados pelo
contador. Campos obrigatórios incompletos impedem envio. A gerência precisa confirmar
a conferência dos dados; isso não substitui validação tributária pelo responsável.

A emissão usa os itens e valores da venda/comanda, sem repetir baixa de estoque nem
recebimento. Descontos são rateados. Para Pix é necessário selecionar a modalidade
fiscal efetivamente usada; venda na conta usa pagamento posterior. NFC-e desabilitada
impede emissão. A política de bloquear a própria venda sem NFC-e continua configurável
por `FISCAL_BLOQUEAR_VENDA_SEM_NFCE`.

Alterações no cadastro do produto só afetam novas emissões. Para rejeição corrigível,
a gerência pode revisar o cadastro e **Reenviar cadastro corrigido**: o sistema consulta
o provedor, exige rejeição confirmada, preserva a referência e valida que o total da
origem não mudou. Denegação não é tratada como rejeição corrigível.

## Falhas, retorno e cancelamento

Cada emissão recebe uma referência persistida antes da chamada externa. Uma restrição
no banco impede duas notas ativas do mesmo tipo para a mesma origem. Chamadas concorrentes
são protegidas por reivindicação da operação. O envio de rede ocorre fora da trava da conta.

Se houver timeout, não crie outra nota: consulte o documento. O reenvio usa a mesma
referência e consulta o provedor antes de enviar. Webhook exige autenticação e aplica
transições válidas; status autorizado precisa de número ou chave retornado. Erros de
rede não exibem dados pessoais nem o corpo bruto da resposta.

O cancelamento exige motivo, chamada ao provedor e confirmação posterior por consulta.
Sem confirmação, a nota permanece registrada. Venda/comanda com documento fiscal ativo
não pode ser cancelada antes da conciliação fiscal. Documento emitido não pode ser
reescrito ou apagado pelo Admin. Valores IBS/CBS mostrados pelo CRM são estimativas;
a apuração e o documento autorizado devem ser conferidos com o responsável fiscal.

## Ensaio antes da operação

1. Configure emitente, certificado, município, série e credenciais de homologação no provedor.
   No Spedy: cadastre a empresa e o certificado A1 no painel, crie o webhook
   (`POST /v1/webhooks`, evento `invoice.status_changed`, URL `/crm/fiscal/webhook/`) e
   copie o segredo da conta para `SPEDY_WEBHOOK_SECRET`.
2. Confira cadastro de tomador, códigos dos serviços e tributação de produtos.
3. Emita uma NFS-e de hospedagem e, se habilitada, uma NFC-e de venda/comanda.
4. Confira total, itens, tomador, XML/PDF e situação no painel do provedor.
5. Ensaie rejeição, consulta após resposta perdida, reenvio sem duplicação e cancelamento.
6. Registre o resultado em **Operação e integrações**, sem CPF, chaves ou dados de cartão.
7. Ao mudar credenciais/ambiente, repita o ensaio; o registro anterior fica desatualizado.

O painel distingue configuração presente de ensaio declarado. Não realiza emissão de
teste automaticamente nem afirma que o fisco autorizou uma operação sem retorno válido.

Contratos de referência: Focus [NFS-e Nacional](https://doc.focusnfe.com.br/reference/emitir_dps_nacional)
e [NFC-e](https://doc.focusnfe.com.br/reference/emitir_nfce); Spedy
[criar](https://docs.spedy.com.br/api-reference/nfs-e/criar-nfs-e.md),
[consultar](https://docs.spedy.com.br/api-reference/nfs-e/obter-nfs-e.md) e
[cancelar NFS-e](https://docs.spedy.com.br/api-reference/nfs-e/cancelar-nfs-e.md),
[ciclo de vida](https://docs.spedy.com.br/guides/ciclo-de-vida-da-nota.md) e
[assinatura do retorno](https://docs.spedy.com.br/webhooks/assinatura.md).
