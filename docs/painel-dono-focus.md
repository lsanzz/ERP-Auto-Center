# Painel administrativo do sistema e integração Focus NFe

O painel administrativo fica em `/sistema/login` e usa autenticação própria,
separada dos usuários das oficinas. As contas são armazenadas em
`system_admins`; portanto, um administrador comum do ERP não consegue abrir o
painel, alterar credenciais fiscais nem promover a própria conta.

Em `/sistema/admin`, o proprietário do sistema encontra um resumo e a relação
das empresas cadastradas na Focus NFe, com busca por nome ou documento, situação
remota, cidade, UF, validade do certificado e data da última sincronização. O
botão **Atualizar empresas** consulta todas as páginas disponíveis na Focus e
atualiza o cache local em `managed_companies`.

A configuração central da Focus fica em `/sistema/admin/integracao`. O token
principal, o token de emissão e as demais credenciais são acessíveis somente por
essa autenticação administrativa. Campos de token nunca são devolvidos
preenchidos ao navegador. O token principal também pode ser definido no servidor
pela variável `FOCUS_NFE_TOKEN_PRINCIPAL`, que tem precedência sobre o valor do
banco.

Em **Configurações > Dados da empresa**, salvar persiste primeiro os dados no
ERP. Com a integração habilitada e o cadastro completo, o sistema consulta a
Focus pelo CNPJ/CPF: uma empresa nova é criada com POST e uma existente é
atualizada com PUT. O identificador e o token de emissão do ambiente são obtidos
automaticamente. A consulta antes da criação também evita duplicidade após uma
falha de conexão.

Falhas na Focus preservam os dados locais e deixam a sincronização pendente. O
certificado A1 é validado e enviado pelo mesmo fluxo; o arquivo e a senha ficam
somente em memória durante a requisição e não são persistidos no ERP.

Comandos administrativos:

```text
python -m flask --app run.py criar-admin-sistema --username lucas.admin --name "Lucas - Proprietário"
python -m flask --app run.py atualizar-empresas-focus
```

A migração MySQL `20260907_07` cria `system_admins` e `managed_companies`. Em
instalações com migrações explícitas, execute `python -m flask --app run.py db
upgrade` com `AUTO_CREATE_SCHEMA=false`. No modo legado, o bootstrap existente
cria as tabelas automaticamente; não use os dois modos sobre a mesma base.

Limite atual: o banco operacional do ERP ainda representa uma oficina por
instalação. O painel já agrega todas as empresas existentes na conta Focus, mas
um SaaS multiempresa em um único banco exige adicionar `tenant_id` e isolamento
em todas as tabelas, consultas e rotas operacionais.

Referências oficiais: https://doc.focusnfe.com.br/reference/criar_empresa e
https://doc.focusnfe.com.br/reference/listar_empresas.
