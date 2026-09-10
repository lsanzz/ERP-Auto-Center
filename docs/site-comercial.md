# Site comercial LS Hub

Primeira versão em `marketing.py`, `website/templates/` e `website/static/`.
O site usa Flask e as dependências já presentes no projeto. A aplicação pública
é independente de `app.create_app`: não importa os modelos do ERP, não inicia
migrations operacionais e não consulta dados reais das oficinas.

## Prévia local

```powershell
rtk proxy .venv\Scripts\python.exe -m flask --app marketing:create_app run --host 127.0.0.1 --port 5010
```

Abra `http://127.0.0.1:5010`. O processo público possui apenas as rotas de página
principal, demonstração, confirmação, privacidade, assets, robots e sitemap.
O botão de login aponta para `https://app.lshub.com.br`.

## Entregue

- Página responsiva com apresentação, recursos, jornada, planos, implantação, dúvidas e contato.
- Identidade em preto, branco e cinzas seguindo a referência DESIGN.md fornecida.
- Composição tipográfica sem prints, fotos ou simulações de telas, conforme pedido atualizado.
- Animações de entrada, feedback de botões e expansão de dúvidas, respeitando movimento reduzido.
- Planos Essencial, Profissional e Gestão sob consulta, sem cobrança automática.
- Menu móvel, seleção de plano no formulário, perguntas expansíveis e navegação por teclado.
- WhatsApp `+55 19 99274-4148` e e-mail `lucastango40@gmail.com`, fornecidos pelo proprietário.
- Registro persistente de pedidos de demonstração, validação no servidor, CSRF,
  proteção contra repetição, limite por conexão e campo antispam.
- Origem UTM registrada somente com o pedido; não há analytics de terceiros.
- Confirmação real somente após o pedido ter sido salvo.
- Aviso de privacidade descrevendo o comportamento implementado.
- Exportação local de leads e testes do fluxo comercial.

O formulário registra as solicitações no servidor. **Não envia notificações por
e-mail nem mensagens automáticas no WhatsApp.** E-mail e WhatsApp funcionam como
links de contato direto; uma integração de notificação será uma etapa posterior.

## Configuração

Variáveis opcionais, exceto pela chave obrigatória em produção:

| Variável | Uso |
| --- | --- |
| `MARKETING_ENV` | `production` ativa cookies HTTPS e HSTS |
| `MARKETING_SECRET_KEY` | Chave independente e persistente para a sessão pública |
| `MARKETING_WHATSAPP` | Número com país e DDD; padrão informado pelo proprietário |
| `MARKETING_EMAIL` | E-mail comercial; padrão informado pelo proprietário |
| `MARKETING_LEGAL_NAME` | Razão social real a exibir no rodapé e aviso |
| `MARKETING_CNPJ` | CNPJ real a exibir no rodapé |
| `MARKETING_LEADS_DATABASE` | Caminho absoluto do banco exclusivo de contatos comerciais |

Na execução local, a chave é gerada se não estiver configurada; reiniciar o
processo invalida as sessões existentes. Em produção, configure uma chave
aleatória persistente de pelo menos 32 bytes, diferente da chave do ERP.

Os contatos são armazenados em SQLite, por padrão em
`instance/website/leads.db`, fora dos arquivos públicos e já ignorado pelo Git.
**O ERP continua usando MySQL.** Este armazenamento separado serve a uma instância
do site com volume inicial de vendas. Use disco persistente local ao servidor;
não use uma pasta de rede/OneDrive em produção. Para réplicas ou múltiplos
servidores, migre os leads e os contadores para um armazenamento compartilhado.

O SQLite fecha cada conexão após a transação e evita duplicidade pelo identificador
de submissão. O limite permite dez tentativas válidas de sessão por endereço de
conexão em uma hora, persistindo entre reinícios. IPs não são guardados em texto
no controle de tentativas. Cabeçalhos de IP enviados pelo navegador não são
confiados. Ao publicar atrás de proxy, configure o encaminhamento de IP apenas
para o proxy confiável; caso contrário, visitantes podem compartilhar o limite
do endereço do proxy. Não habilite `ProxyFix` sem conhecer a quantidade de proxies.

## Consultar os interessados

Não existe rota pública de listagem. No servidor, execute:

```powershell
rtk proxy .venv\Scripts\python.exe -m flask --app marketing:create_app export-leads instance\website\leads-export.csv
```

O destino precisa ser novo: a exportação não sobrescreve arquivos. O CSV inclui
contato, oficina, plano, dificuldade e origem da campanha, com neutralização de
fórmulas para abertura em planilhas. A equipe comercial precisa consultar esses
pedidos enquanto não houver notificação automática. Inclua o banco de contatos
na rotina de backup, restrinja acesso ao servidor e defina a retenção operacional.

## Publicação em lshub.com.br

O desenvolvimento não modifica DNS nem a hospedagem existente.

1. Configure uma aplicação Python separada para o domínio principal, usando
   `marketing:create_app()` como aplicação WSGI. No cPanel/Passenger, o arquivo
   de entrada pode importar `create_app` de `marketing` e definir
   `application = create_app()`.
2. Configure chave persistente, ambiente de produção, caminho de dados persistente
   e dados jurídicos reais. Preços e condições contratuais precisam ser definidos
   antes de trocar os planos sob consulta por uma contratação direta.
3. Sirva HTTPS em `lshub.com.br` e redirecione `www.lshub.com.br` para o domínio
   principal, preservando caminho e parâmetros UTM.
4. Mantenha `app.lshub.com.br` encaminhado à aplicação atual do ERP.
5. Confira o formulário no ambiente publicado e a exportação do pedido antes
   de iniciar campanhas. Configure notificações se a equipe não consultar o CSV.

Em servidor Linux com Gunicorn já previsto nas dependências:

```text
gunicorn 'marketing:create_app()' --bind 127.0.0.1:5010 --workers 2
```

Use proxy HTTPS e supervisão de processo. O servidor de desenvolvimento é apenas
para prévia local. Não existe uso de credenciais fiscais ou acesso de administrador
do ERP por esta aplicação pública.

## Verificação

```powershell
rtk proxy .venv\Scripts\python.exe -m unittest tests.test_marketing -v
```

Os testes criam bancos temporários e verificam captura, validação, autorização,
reenvio, limite persistente, links internos, assets, ausência de rotas privadas
e exportação. Não acessam a base de produção do ERP.
