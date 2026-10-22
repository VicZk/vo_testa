# Emissão fiscal — CRM Pousada Vô Testa

Estado do código em 22/10/2026. O adaptador Focus NFe v2 está implementado para
NFS-e Nacional e NFC-e. A operação real depende do cadastro do emitente no
provedor, credenciais, parâmetros revisados e ensaio no ambiente escolhido.
Testes automatizados com respostas controladas não comprovam homologação fiscal.

## Configuração

Escolha `FISCAL_GATEWAY=focus`. O modo `simulado` produz documentos de demonstração
sem validade fiscal. Integração direta com o governo e outros provedores não estão
disponíveis neste código; nomes desconhecidos geram erro explícito.

| Variável | Uso |
| --- | --- |
| `FISCAL_FOCUS_URL` | `https://homologacao.focusnfe.com.br` ou `https://api.focusnfe.com.br` |
| `FISCAL_FOCUS_TOKEN` | Token do emitente e ambiente; não incluir em código, relatórios ou prints |
| `FISCAL_EMITENTE_CNPJ` | CNPJ do emitente cadastrado no provedor |
| `FISCAL_MUNICIPIO_IBGE` | Município de emissão e prestação no perfil disponível |
| `FISCAL_DPS_SERIE` | Série exclusiva deste sistema, entre 1 e 49999 |
| `FISCAL_DPS_NUMERO_INICIAL` | Início da faixa reservada; o número usa a base mais o ID do documento menos um |
| `FISCAL_NFSE_CODIGO_SERVICO` | Código nacional de seis dígitos para hospedagem |
| `FISCAL_NFSE_COMPLEMENTOS` | Objeto JSON de complementos revisados pelo responsável fiscal |
| `FISCAL_NFCE_HABILITADA` | Padrão 0; habilitar após cadastro do emitente, IE, CSC e certificado no provedor |
| `FISCAL_WEBHOOK_TOKEN` | Segredo do header `Authorization` no retorno para `/crm/fiscal/webhook/` |

O perfil NFS-e disponível usa Lucro Presumido, operação tributável sem retenção e
prestação no município configurado. Outros enquadramentos precisam de adaptação
validada; não basta alterar um rótulo. Dados históricos de julho de 2026 indicavam
hospedagem `090101`, ISS de 4% e IE ainda pendente. Esses dados não foram reconfirmados
com o contador nesta implementação. Confira o [checklist contábil](Checklist_contador.md).

A URL, o CNPJ emitente e o provedor ficam vinculados ao documento. Trocar o ambiente não permite
consultar ou cancelar documentos antigos no ambiente novo. O token pode ser
rotacionado para a mesma conta; confira a identidade do emitente ao fazer isso.

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
2. Confira cadastro de tomador, códigos dos serviços e tributação de produtos.
3. Emita uma NFS-e de hospedagem e, se habilitada, uma NFC-e de venda/comanda.
4. Confira total, itens, tomador, XML/PDF e situação no painel do provedor.
5. Ensaie rejeição, consulta após resposta perdida, reenvio sem duplicação e cancelamento.
6. Registre o resultado em **Operação e integrações**, sem CPF, chaves ou dados de cartão.
7. Ao mudar credenciais/ambiente, repita o ensaio; o registro anterior fica desatualizado.

O painel distingue configuração presente de ensaio declarado. Não realiza emissão de
teste automaticamente nem afirma que o fisco autorizou uma operação sem retorno válido.

Contratos de referência: [NFS-e Nacional](https://doc.focusnfe.com.br/reference/emitir_dps_nacional)
e [NFC-e](https://doc.focusnfe.com.br/reference/emitir_nfce).
