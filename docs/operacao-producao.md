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

## Variáveis desta revisão (22/10/2026)

- `TZ`: o sistema assume `America/Sao_Paulo` quando a variável não está definida, para "hoje" ser o dia da oficina. Só defina outro valor se a oficina estiver em outro fuso.
- `TRUSTED_PROXY_COUNT`: número de proxies na frente do sistema (ex.: `1` com Cloudflare ou proxy reverso). Sem isso, atrás de proxy todos os usuários aparecem com o mesmo IP e 5 senhas erradas de uma pessoa bloqueiam o login de todos. Deixe vazio quando o acesso for direto.
- Migration `20261022_19` cria `assistant_states` (conversa e propostas do assistente de IA, antes guardadas no cookie). Rode `flask --app run.py db upgrade` antes de subir esta versão.

## Painel do dono do sistema (privado)

- Senha + **código do aplicativo autenticador obrigatório** (configurado no primeiro login). A sessão expira após 30 minutos parada, e 5 erros bloqueiam o IP por 15 minutos.
- `SYSTEM_ADMIN_PATH`: endereço secreto do painel (ex.: `/painel-k8w3q`). Sem a variável, fica em `/sistema`. Fora do endereço certo, a resposta é 404.
- `SYSTEM_ADMIN_ALLOWED_IPS`: IPs ou faixas autorizados, separados por vírgula (ex.: `189.10.20.30,2804:abcd::/32`). Qualquer outro IP recebe 404, como se o painel não existisse. Atrás de Cloudflare, defina também `TRUSTED_PROXY_COUNT`.
- Criar o acesso: `flask --app run.py criar-admin-sistema --username SEU_USUARIO`. Mostra uma senha temporária uma única vez.
- Esqueceu a senha ou perdeu o celular: `flask --app run.py redefinir-acesso-admin-sistema --username SEU_USUARIO` gera uma senha nova e zera o autenticador. Só funciona com acesso ao servidor.
- Migration `20261022_21` adiciona o autenticador aos administradores do sistema.
