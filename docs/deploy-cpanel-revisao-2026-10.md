# Deploy da revisão de out/2026 no cPanel (sem terminal)

Leva cerca de 20 minutos. Faça fora do horário de atendimento.

## 1. Backup (obrigatório)
1. **cPanel → phpMyAdmin**: selecione o banco do ERP → **Exportar** → Rápido → SQL → Executar. Guarde o arquivo no seu computador.
2. **Gerenciador de Arquivos**: na pasta do sistema, selecione tudo → **Compactar** → baixe o `.zip`. É a versão antiga, para voltar atrás se precisar.

## 2. Enviar o código novo
Escolha **uma** das opções:
- **Git Version Control** (se o repositório já estiver ligado ao cPanel): abra o repositório → **Pull or Deploy** → **Update from Remote** (branch `master`).
- **Upload manual**: no GitHub, abra `lsanzz/ERP-Auto-Center` → **Code → Download ZIP** (branch `master`). No Gerenciador de Arquivos, envie o zip para a pasta do sistema e **Extrair**, substituindo os arquivos. Não apague `.env`, `instance/` nem a pasta de uploads.

## 3. Dependências
**Setup Python App** → abra o app → em "Configuration files" escolha `requirements.txt` → **Run Pip Install**. Isso instala o Werkzeug 3.1.9 (correção de segurança) e o `beautifulsoup4`.

## 4. Banco de dados
**Setup Python App** → campo **Execute python script** → `scripts/apply_review_2026_10.py` → **Run Script**.
A saída deve terminar com `Pronto.` e listar `criada:` ou `já existe:` para:
- `assistant_states`
- três colunas `subscription_*`
- `mfa_secret_encrypted`

Pode rodar de novo sem problema.

## 5. Configurações (`.env` na pasta do sistema, pelo Gerenciador de Arquivos → Editar)
Acrescente as linhas abaixo e preencha:
```
SUPPORT_WHATSAPP=+55 19 9XXXX-XXXX
SUPPORT_EMAIL=seu-email@dominio.com
SYSTEM_ADMIN_PATH=/painel-<letras-e-números-aleatórios>
# Opcional: só se você tiver IP fixo
# SYSTEM_ADMIN_ALLOWED_IPS=200.100.50.25
# Só se o site passar pela Cloudflare
# TRUSTED_PROXY_COUNT=1
```

## 6. Reiniciar e conferir
1. **Setup Python App → Restart**.
2. Abra o sistema, faça login e abra uma O.S. e o Financeiro.
3. Abra `https://SEU-DOMINIO/api/health`. Deve mostrar `"status": "ok"`.
4. Painel do dono: `https://SEU-DOMINIO/painel-.../login` (o caminho que você pôs em `SYSTEM_ADMIN_PATH`). No primeiro acesso, ele mostra a chave para cadastrar no aplicativo autenticador do celular. **Guarde essa chave.**

## Se algo der errado
- Erro ao abrir qualquer página: veja `stderr.log` na pasta do app. Se não resolver, extraia o `.zip` antigo do passo 1 e reinicie.
- Os dados não correm risco: o script do passo 4 só **acrescenta** tabela e colunas, não altera nem apaga nada.
