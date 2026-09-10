# Operação em produção

## Implantação

1. Gere um backup consistente e confirme que o arquivo não está vazio.
2. Restaure o backup em homologação e execute `flask --app run.py db upgrade`.
3. Rode os testes de fumaça: login, criação de cliente, leitura de OS, estoque, financeiro e `/api/health`.
4. Na janela de implantação, interrompa os processos que gravam dados.
5. Execute `flask --app run.py db upgrade` uma única vez.
6. Inicie aplicação e worker, verifique logs e saúde e só então libere tráfego.

Não use `db.create_all()` em produção. `AUTO_CREATE_SCHEMA=false` é o padrão e deve ser explícito no ambiente.

## Backup e restauração

Agende `scripts/backup_mysql.sh` diariamente com `BACKUP_DIR` apontando para armazenamento fora do servidor da aplicação. O padrão retém 14 dias; altere com `BACKUP_RETENTION_DAYS`.

Todo mês, restaure o backup mais recente em um banco isolado, aplique migrations e valide contagens de clientes, OS, lançamentos financeiros e soma de estoque. Um backup só é confiável depois de um teste de restauração.

## Processos

- Aplicação: Gunicorn com timeout compatível com o proxy reverso.
- Worker: `flask --app run.py jobs-worker`; use um supervisor para reinício automático.
- MySQL: não exponha a porta à internet.
- Anexos: monte `instance/uploads` em volume persistente e inclua-o numa política separada de backup.

## Monitoramento

Monitore código HTTP, latência, `GET /api/health`, espaço em disco, conexões MySQL e tarefas em `async_jobs` com status `FALHOU`. Propague `X-Request-ID` no proxy para correlacionar uma solicitação entre as camadas.

Alertas mínimos:

- health check indisponível por 2 minutos;
- erros HTTP 500 acima do normal;
- nenhum backup válido nas últimas 26 horas;
- falha definitiva de tarefa assíncrona;
- certificado fiscal próximo do vencimento;
- uso de disco acima de 80%.

## Recuperação

Em caso de falha de migration, não improvise alterações manuais no schema. Interrompa gravações, preserve logs e banco, restaure o backup validado se necessário e execute a versão anterior da aplicação. Alterações financeiras, fiscais ou de estoque devem ser revertidas por lançamentos de estorno auditáveis, nunca por exclusão direta.
