# Implantação de uma oficina nova

Modelo adotado: **uma instalação (aplicação + banco MySQL) por oficina**. Os dados de cada oficina ficam isolados, o que é o mais seguro e o mais simples de vender e explicar.

## 1. Antes
- [ ] Contrato assinado ([contrato-assinatura.md](contrato-assinatura.md)) e Anexo I preenchido.
- [ ] Dados da oficina: CNPJ, endereço, logotipo, usuários (nome e perfil).
- [ ] Exportação do sistema anterior (planilhas ou CSV), se houver migração.

## 2. Criar o ambiente
1. Subdomínio: `nomedaoficina.lshub.com.br`.
2. No cPanel: crie o banco MySQL e o usuário, e uma "Python App" apontando para `passenger_wsgi.py`.
3. Crie o arquivo `.env` com estas variáveis, todas novas e exclusivas desta oficina:
   ```
   APP_ENV=production
   DATABASE_URL=mysql+pymysql://USUARIO:SENHA@localhost/BANCO
   SECRET_KEY=<64 caracteres aleatórios>
   INITIAL_ADMIN_PASSWORD=<senha forte, entregue ao dono por canal seguro>
   TRUSTED_HOSTS=nomedaoficina.lshub.com.br
   TURNSTILE_SITE_KEY=...
   TURNSTILE_SECRET_KEY=...
   SUPPORT_WHATSAPP=+55 19 9XXXX-XXXX
   SUPPORT_EMAIL=suporte@lshub.com.br
   TRUSTED_PROXY_COUNT=1   # só se passar pela Cloudflare
   SYSTEM_ADMIN_PATH=/painel-<algo-aleatório>
   SYSTEM_ADMIN_ALLOWED_IPS=<seu IP fixo ou faixa da sua operadora>
   ```
   Um `SECRET_KEY` aleatório se gera com: `python -c "import secrets; print(secrets.token_hex(32))"`.
4. Instale as dependências e rode `flask --app run.py db upgrade`.
5. Crie o seu acesso de dono do sistema: `flask --app run.py criar-admin-sistema --username SEU_USUARIO --name "SEU NOME"` (mostra uma senha temporária; troque no primeiro acesso).
6. No painel do dono do sistema (`SYSTEM_ADMIN_PATH`/admin), defina o **plano** e o **Pago até**.

## 3. Tarefas em segundo plano (obrigatório)
Importações e consultas fiscais rodam no processador de tarefas. No cPanel, que não mantém processos rodando, crie um **Cron Job a cada minuto**:
```
* * * * * cd ~/APP && ~/virtualenv/APP/3.11/bin/flask --app run.py jobs-worker >> ~/logs/jobs.log 2>&1
```
Sem opções, o comando processa todas as tarefas da fila e encerra; execuções sobrepostas não pegam a mesma tarefa. Em VPS, use o systemd com `jobs-worker --watch`.

## 4. Backup (obrigatório)
Cron diário às 3h:
```
0 3 * * * cd ~/APP && BACKUP_DIR=~/backups scripts/backup_mysql.sh
```
Copie a pasta de backups para fora do servidor (Google Drive, S3 ou outro). Todo mês, restaure um backup num banco de teste e confira se abre.

## 5. Configuração com o cliente (1 a 2 horas)
1. Primeiro login como `admin` e troca imediata da senha. Ative a verificação em duas etapas.
2. Configurações → Dados da empresa, horários, prefixos de O.S. e orçamento.
3. Contas bancárias e formas de pagamento (com a conta padrão de cada uma).
4. Usuários e perfis.
5. Migração de dados (Configurações → Migração de dados) e conferência das contagens com o cliente.
6. Treinamento: abrir O.S., lançar recebimento, pátio, estoque, financeiro e o assistente de IA.

## 6. Depois
- [ ] Monitor do `/api/health` cadastrado.
- [ ] Primeiro backup conferido.
- [ ] Ligação ou mensagem de acompanhamento em 7 dias e em 30 dias.
