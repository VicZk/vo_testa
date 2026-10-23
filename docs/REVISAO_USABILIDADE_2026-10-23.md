# Revisão de interface e uso — 23/10/2026

Revisão da fork `VicZk/vo_testa`, para publicação em `dev`, a partir de
`7e425c4`. Complementa a [revisão de 22/10](REVISAO_USABILIDADE_2026-10-22.md).
O trabalho teve duas etapas: consistência visual/navegação e execução de tarefas
com criação, erro, correção, repetição e concorrência.

## Ambiente e cobertura

PostgreSQL local isolado, dados fictícios e Chromium real automatizado. Envios
externos foram bloqueados ou substituídos pelos simuladores do aplicativo.
As capturas foram inspecionadas; medições de geometria complementam a revisão
visual, sem substituir a leitura e a interação.

A matriz do menu contém **37 rotas em 320, 390, 768 e 1440 px: 148 renderizações**.
Todas responderam 200 sem exceção JavaScript, transbordamento do documento ou
controles fora da região visível/rolável. São 148 capturas de topo e 74 páginas
completas. Tabelas/abas com rolagem própria foram consideradas deliberadamente:
isso não significa que todas as colunas estejam simultaneamente visíveis.

| Grupo | Telas da matriz |
|---|---|
| Recepção | Painel, Reservas, Governança, APP/Site, Recados do turno |
| Operação | Manutenção, Estoque, Loja, Restaurante Piscina, Lavanderia, Escala |
| Financeiro | Pagamentos Online, Fiscal, Caixa, Lançamentos, Contas a pagar/receber, Sessões de caixa, Conciliação |
| Relacionamento | Comercial, LP Páginas, Respostas rápidas, Marketing, NPS |
| Pessoas | Hóspedes, Agências, Empresas, Fornecedores, Pessoas, Funcionários |
| Gestão | Canais/OTAs, Auditoria, Relatórios, Quartos & tipos, Tabela de preços, Temporadas, Módulos, Operação e integrações |

Há cenários adicionais com dados preenchidos e nomes/valores longos, páginas de
detalhe, mensagens de erro, menu aberto e recolhido, teclado, histórico,
preferência por movimento reduzido e ausência de JavaScript nos formulários.

## Interface e navegação

- O conteúdo recebe a transição; topo e menus conservam posição. Menus internos
  compartilham comportamento, sem duplicar a navegação da Governança. Voltar e
  avançar restauram controles, gráficos e ações das reservas.
- A busca Ctrl/Cmd+K tem contorno contínuo, foco por teclado e dimensões próprias
  para celular. Alterações pendentes, formulários e carrinho participam da
  confirmação de saída.
- Reservas mostram registros legíveis no celular. A ficha organiza ações por
  etapa e opções secundárias; abrir/fechar painéis devolve o foco corretamente.
- Painel apresenta chegadas/saídas antes dos gráficos, com hóspedes, quartos,
  situação, saldo e atalhos para as verificações existentes de entrada/saída.
  Previsão de diárias, sinal, crédito, conta aberta/ausente e cobrança de grupo
  têm significados distintos. Day Use conserva o fluxo próprio.
- NPS, Financeiro e Pagamentos mostram valores, situação e descrição em cartões
  no celular. Períodos, caixa e categorias usam filtros compactos.
- Preços permite filtrar ala/quarto sem desabilitar nem perder os valores dos
  demais quartos. Erro oculto revela o campo; Salvar acompanha a rolagem.
  Com 26 quartos, a página inicial a 390 px passou de 20.886 para 4.049 px.
- Gráficos usam Chart.js local e inicialização única, com restauração após
  troca HTMX/histórico e destruição das instâncias removidas.

## Uso real e falhas corrigidas

| Área | Problema reproduzido e comportamento final | Evidência reproduzível |
|---|---|---|
| Navegação | Voltar antes do fim da troca restaurava a rolagem, mas o término da navegação anterior a zerava. O menu agora posiciona o topo junto da troca, preservando o histórico | `tests_movimento_e2e.py`, com término HTMX atrasado e retorno antecipado |
| Manutenção | Faltava anexar a nota; conclusão e documento agora são atômicos. Arquivo inválido preserva campos/arquivo e não conclui a OS nem lança custo parcial | `tests_documentos.py`, `tests_usabilidade.py`, `tests_manutencao_documentos_e2e.py` |
| Manutenção | Histórico e busca recuperam OS concluída/cancelada, inclusive por número de nota. Bloqueio futuro não aparece como bloqueio atual | `tests_documentos.py`, `tests_manutencao_documentos_e2e.py` |
| Escala | IDs/datas/enums inválidos causavam erro interno ou gravação indevida. Entradas inválidas são recusadas antes de mutação | `tests_usabilidade.py`, `tests_escala_uso_e2e.py` |
| Escala | Falha ao decidir troca deixava alteração parcial; decisão antiga podia sobrescrever a atual. Transação e revalidação preservam a atribuição | `tests_usabilidade.py` |
| Escala | Solicitação e aprovação concorrentes travavam funcionário/atribuição em ordem inversa; passaram a usar a mesma ordem | `tests_concorrencia_uso.py` com conexões PostgreSQL distintas |
| Caixa | Após movimentar um caixa específico, a tela voltava para outro módulo; o módulo selecionado agora é mantido | `tests_controles_e2e.py` |
| Contas | Descrição no limite excedia o lançamento derivado; falha/reenvio/baixa simultânea podiam deixar inconsistência. A baixa usa trava/transação e preserva a descrição original | `tests_baixa_contas.py`, `tests_usabilidade_operacional_e2e.py` |
| Pagamentos | Valor líquido/taxa/data inválidos e atualização parcial podiam alterar a liquidação incorretamente; validação e preservação corrigidas. Confirmar fica acessível após erro | `tests_conciliacao_validacao.py`, `tests_usabilidade_operacional_e2e.py` |
| Cartão | Reimportar CSV duplicava transações. Chave única e deduplicação preservam novas transações legítimas e reaproveitam registros antigos idênticos | `tests_importacao_cartao.py`, `tests_usabilidade_operacional_e2e.py` |
| Funcionários | Login duplicado deixava Pessoa/Funcionário parcial; acesso concedido pela ficha nascia inativo. Cadastro/acesso são atômicos e situação é explícita | `tests_funcionarios_fluxo.py`, `tests_cadastros_nps_e2e.py` |
| Cadastros e NPS | Agência/Empresa inválidas são corrigidas sem perder dados; NPS exige consentimento, resposta única e tratamento com autoria | `tests_cadastros_nps_e2e.py` |

Também foram exercitados estoque, venda, comanda, rouparia, dependências de
módulos, campanhas/leads, reserva de canal e emissão fiscal simuladas. As
regressões existentes permanecem no CI junto dos novos testes. A descoberta
automática usa `apps.site --pattern='tests*e2e.py'`, com Playwright obrigatório.

## Documentos privados de manutenção

O número da nota e o arquivo são opcionais ao concluir. Depois, a equipe com
acesso ao módulo pode adicionar documentos pela própria OS, inclusive no
histórico. Formatos: PDF, PNG, JPG/JPEG e XML; até **10 MiB por arquivo e 10
documentos por OS**. O mesmo conteúdo enviado novamente para a mesma OS não
duplica o documento.

O servidor confere tamanho e conteúdo, estrutura/páginas de PDF, integridade da
imagem e XML sem DTD/entidades. PDFs criptografados e arquivos inválidos são
recusados. Nome é saneado; download exige sessão e permissão de Manutenção,
confere o vínculo com a OS e usa resposta como anexo, sem cache nem URL pública.
Esta validação não é um serviço de análise antivírus.

Os bytes ficam na tabela `manutencao.DocumentoOrdemServico`, junto de tamanho,
hash, autoria e data. Não passam pelo armazenamento público de mídia/R2. O
backup PostgreSQL inclui os documentos; listas adiam a leitura do conteúdo
binário. É necessário considerar esse volume no dimensionamento dos backups.

## Migrações e publicação

- `manutencao.0006_documentos_privados`: tabela de documentos privados.
- `conciliacao.0003_transacaocartao_chave_importacao`: chave opcional/única para
  deduplicação. Duplicações históricas não são apagadas automaticamente.

As duas migrações são aditivas. A publicação usa somente a fork autorizada,
suítes aprovadas, backup PostgreSQL verificável e substituição apenas do
serviço web. O manifesto dos arquivos do commit permite conferir fonte,
imagem construída e contêiner ativo; recursos públicos são conferidos por hash.
O histórico de execução do CI e o registro de deploy identificam a versão.

## Limites da evidência

Cobertura corresponde às telas e cenários descritos, sem prometer ausência de
todo defeito possível. Auditoria visual/funcional local, CI e conferência de
produção são evidências distintas. Não foram enviados e-mails/WhatsApp reais,
cobrados pagamentos, emitidas notas oficiais ou sincronizada uma OTA real.
Contratação, credenciais e homologação desses provedores continuam sujeitas à
validação própria da instalação.
