# Preservação de formulários após erros

Formulários Django com validação própria devem renderizar o mesmo formulário
vinculado ao POST, incluindo erros por campo. Formulários HTMX só fecham o modal
após confirmação explícita da ação; HTTP 200, sozinho, não indica sucesso de negócio.

Nas ações tradicionais que usam `messages.error` e redirecionam, o atributo
`data-preservar-erros` ativa `static/js/formularios.js`. O navegador mantém o DOM
original enquanto envia. Campos, seleções e arquivos permanecem disponíveis se a
validação falhar. O aviso aparece no formulário e recebe foco. Só há navegação após
o servidor devolver a URL de sucesso.

`RespostaFormularioMiddleware` traduz novas mensagens de erro dessas requisições
em JSON 422 e transforma o redirecionamento de sucesso em JSON com a URL de destino.
Mensagens anteriores não fazem uma ação bem-sucedida parecer recusada. Os headers
de proteção e as verificações de login, permissão e CSRF continuam aplicados.
Sem o cabeçalho opt-in, permanece o contrato HTTP original de cada view.
Sessão expirada mantém os controles e orienta renovar o login em outra aba.
No site, a mudança de disponibilidade reapresenta os contatos e permite corrigir
datas; "Editar dados" volta ao formulário preenchido usando POST, sem contatos na URL.

Valores monetários são normalizados na carga enviada, sem alterar os campos
visíveis. Isso evita multiplicar um valor por cem ao reenviar após erro. Falhas
de rede não provocam reenvio automático: a tela mantém os dados e orienta conferir
o resultado, porque o servidor pode ter concluído uma operação cuja resposta se perdeu.

O fluxo não guarda rascunhos em sessão, localStorage ou banco. Na tela pública de
cartão, uma recusa mantém os campos somente na página atual. O número do cartão e
o código de segurança não são devolvidos em JSON nem persistidos como rascunho.

Os testes permanentes cobrem erro de validação, falha de rede, arquivo selecionado,
valor monetário no reenvio, resposta a recado resolvido em outra estação e modal
que continua aberto após uma recusa. Os fluxos de sucesso também precisam navegar
e registrar a operação uma única vez.
