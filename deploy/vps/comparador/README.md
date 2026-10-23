# Comparador entre instalações

Estes arquivos são servidos diretamente pelo Nginx em `/_comparar.js`, com o
prefixo `/votesta` na instalação atualizada. Não são carregados pelo Django nem
publicados automaticamente pelo build da aplicação.

- `antiga.js`: origem anterior → `https://viczk.cloud/votesta`, botão **Versão atualizada**.
- `nova.js`: origem atualizada → `https://votesta-original.195-200-0-150.sslip.io`, botão **Versão anterior**.

Os dois preservam caminho, query e fragmento. O link possui destino real desde a
montagem e é atualizado após navegação/restauração HTMX. Uma delegação em captura
atualiza o destino também ao clicar, sem cancelar o comportamento nativo do link;
isso preserva teclado, modificadores, clique do meio e menu de contexto.

O histórico HTMX pode restaurar HTML sem os listeners dos nós anteriores.
Por isso a lógica de navegação pertence ao `document`, e o observador do estado
da sidebar é reconectado quando o elemento `#app` é recriado.

`apps.site.tests_comparador_e2e` verifica o fluxo nos dois sentidos com Chromium
e HTMX reais, usando somente respostas fictícias interceptadas pelo Playwright.
O teste não usa servidor, banco ou credenciais de produção.

A publicação é uma operação separada e autorizada: preservar os scripts ativos,
conferir os dois arquivos e seus hashes, substituí-los atomicamente no diretório
do comparador e verificar os URLs públicos e o fluxo de histórico no navegador.
Não é necessário reiniciar a aplicação ou alterar as configurações de Nginx.
