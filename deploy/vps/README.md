# Instalação isolada da VPS

O Dockerfile desta pasta usa cliente PostgreSQL 16 para o banco PostgreSQL 16 da
instalação. Copie-o como `Dockerfile.vps` no contexto do build existente, junto
do `entrypoint.sh` e do arquivo de exclusões já usados pelo deploy.

No serviço `pousada-web`, mantenha o volume de mídia e acrescente:

```yaml
volumes:
  - ./media:/app/media
  - ./automatic-backups:/app/backups
```

Crie `automatic-backups` com permissão 0700 e defina `BACKUP_DIR=/app/backups`
no arquivo de ambiente protegido da instalação. O comando grava arquivos com
permissão 0600. Essa pasta deve ficar fora da raiz de arquivos servidos pelo proxy.
Recrie somente o serviço web; não é necessário reiniciar o PostgreSQL.

A rotina diária existente chama `backup_banco`. Confira a execução manual e o
estado no painel **Operação e integrações** após o deploy. Os parâmetros
`BACKUP_R2_*` preparam cópia externa em bucket privado separado da mídia; configure
também os destinatários do kit e o monitor das rotinas antes da operação definitiva.

Para ensaiar recuperação, use o dump gerado pelo comando e confira o manifesto
SHA-256. Restaure com `pg_restore --exit-on-error --no-owner --no-acl` em um
PostgreSQL 16 novo, sem portas públicas e sem conexão com serviços externos.
Confira migrations e contagens agregadas das tabelas de negócio. Não exponha dados
de hóspedes ou credenciais nos logs do ensaio. Remova apenas o ambiente descartável
identificado para o teste e preserve o dump verificado conforme a retenção.

Preserve Dockerfile, compose, arquivo de ambiente e imagem anterior em diretório
protegido antes de alterar a instalação. Um retorno à imagem anterior precisa
considerar as migrations já aplicadas; não restaure o banco por cima da operação
ativa sem um procedimento explícito de recuperação.
