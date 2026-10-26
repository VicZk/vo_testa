# Comparador entre instalações

Os dois `.js` são servidos diretamente pelo Nginx em `/_comparar.js`, com o
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

## Acesso sem senha e tela que não existe do outro lado

As duas cópias abrem sem senha, para comparar a mesma tela nas duas versões sem entrar
de novo. Quem faz isso é o `acesso_livre.py`, carregado pelo `settings_vps.py` (a
configuração do projeto mais esse middleware). O código que vai para a produção não muda.

- A tela de entrada, aberta pelo navegador, entra direto como `ACESSO_LIVRE_USUARIO`
  (hoje `teste`, que existe nos dois bancos) e segue para o `next`. Toda tela do CRM
  pedida sem sessão já passa por ali, então se cai na própria tela.
- Depois de "Sair", a entrada pede senha por 15 min, para testar outro usuário.
- Na troca de versão, a tela que não existe do outro lado sobe um nível por vez até
  achar uma que exista, com o aviso "Esta tela não existe nesta versão".

Os dois bancos só têm dados fictícios e os gateways estão em `simulado`. Se isso mudar,
volte a pedir senha antes.

Na VPS, os dois arquivos `.py` ficam em `/var/www/pousada-compare/django/`, montados em
`/opt/comparador` pelos dois composes, e o `.env` de cada cópia tem:

    PYTHONPATH=/opt/comparador
    DJANGO_SETTINGS_MODULE=settings_vps
    ACESSO_LIVRE_USUARIO=teste

Para voltar a pedir senha, tirar as três linhas e recriar o container
(`docker-compose up -d pousada-web`, `docker-compose up -d pousada-original-web`).
Arquivo `.py` alterado: copiar para a pasta e recriar os dois containers. Testes em
`apps.site.tests_acesso_livre`.

## Publicação dos scripts

A publicação é uma operação separada e autorizada: preservar os scripts ativos,
conferir os dois arquivos e seus hashes, substituí-los atomicamente no diretório
do comparador e verificar os URLs públicos e o fluxo de histórico no navegador.
Não é necessário reiniciar a aplicação ou alterar as configurações de Nginx.
