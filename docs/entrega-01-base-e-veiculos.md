# Entrega 01 — Base técnica e cadastro de veículos

Implementação iniciada em 05/09/2026. Esta entrega cobre parte da fase 0 e o núcleo da fase 1 do plano; as fases seguintes continuam pendentes.

## Disponível nesta entrega

- Menu **Veículos**, cadastro/edição, pesquisa por placa, descrição, chassi, cliente e telefone.
- Categorias automóvel, moto, caminhão, utilitário, ônibus, máquina e outro.
- Dados técnicos, proprietário atual, situação ativa/inativa e histórico de proprietários.
- Registro de quilometragem com data e usuário, validação cronológica e controle de edições concorrentes.
- Prontuário com OS e orçamentos vinculados, em ordem cronológica e paginados.
- Seletor de veículos por cliente nas telas de orçamento e OS, com preenchimento de placa/descrição.
- `vehicle_id` na API existente; validação do vínculo e preservação na conversão orçamento → OS.
- Simulação e importação idempotente dos documentos antigos, com relatório de conflitos.
- Indicadores de OS abertas sem limitação à data de entrada; entradas de hoje em indicador separado.
- Recebimentos líquidos do dia incluindo ajustes; ranking restrito a serviços em OS finalizadas/entregues.
- Correção dos filtros de status nos relatórios e remoção das funções duplicadas de serviços/histórico/caixa.
- Proteção CSRF nos formulários e na API baseada em sessão, invalidação de acesso para usuários inativos e configuração de cookies.
- Flask-Migrate/Alembic, baseline congelada e opção de desativar alterações de schema durante a inicialização.

Os dados digitados manualmente em OS/orçamento continuam aceitos. Novos veículos são cadastrados pelo menu Veículos; o sistema não cria um cadastro automaticamente a cada texto digitado em uma OS.

## Instalação e ativação

Instale as dependências atualizadas no ambiente da aplicação:

```powershell
rtk python -m pip install -r requirements.txt
```

Reinicie o processo da aplicação após atualizar o código. Com a configuração legada padrão (`AUTO_CREATE_SCHEMA=true`), a inicialização cria as tabelas novas e acrescenta os vínculos opcionais. Ela não importa nem une os dados antigos automaticamente.

Antes de executar atualizações no banco real, tenha backup restaurável. Os testes desta entrega usam SQLite isolado em memória; o banco configurado da oficina não foi migrado durante o desenvolvimento.

### Banco novo gerenciado por migrações

Com `DATABASE_URL` apontando para o banco novo e vazio:

```powershell
$env:AUTO_CREATE_SCHEMA = 'false'
rtk python -m flask --app run db upgrade
```

O cadastro inicial de administrador deve seguir o procedimento da instalação. Não habilite os usuários/senhas de demonstração em produção.

### Banco existente

Para esta primeira transição, o caminho compatível é executar a inicialização legada com o novo código em uma cópia de homologação, validar dados e testar a restauração. A criação é aditiva; os campos antigos de placa/descrição permanecem.

Depois de aplicado o mesmo procedimento à instalação, adote a baseline:

```powershell
$env:AUTO_CREATE_SCHEMA = 'false'
rtk python -m flask --app run adotar-baseline
```

Esse comando verifica presença de tabelas/colunas e recusa um banco já versionado. Não é uma auditoria completa de tipos, índices e constraints. Em particular, instalações MySQL antigas precisam de verificação das FKs no processo de homologação. Não execute `db upgrade` com a baseline inicial em um banco legado não adotado: as tabelas já existem.

Nas próximas entregas, mantenha `AUTO_CREATE_SCHEMA=false` e use revisões Alembic incrementais. A baseline inicial tem downgrade para banco vazio; não execute esse downgrade numa instalação com dados que deseja preservar.

### Importação do histórico

```powershell
rtk python -m flask --app run fleet importar-legado
rtk python -m flask --app run fleet importar-legado --aplicar
```

O primeiro comando simula e desfaz a transação; o segundo persiste os vínculos. Ambos mostram números de cadastros, vínculos e conflitos. Não há chamadas a provedores externos.

Regras: cliente + placa normalizada; sem placa válida permanece manual; descrições divergentes vão para revisão; repetir o comando não duplica os vínculos. Os textos históricos originais não são sobrescritos.

## API e sessão

Clientes da API que usam cookies devem buscar `GET /api/csrf` e enviar `X-CSRFToken` em POST/PATCH/PUT/DELETE, inclusive no login. Após o login, obtenha um novo token: a sessão é renovada.

Exemplo de corpo de orçamento/OS:

```json
{"client_id": 1, "vehicle_id": 12}
```

O veículo deve pertencer ao cliente e estar ativo. Um vínculo histórico já existente permanece consultável após transferência de proprietário. Omitir `vehicle_id` mantém compatibilidade com clientes antigos; alterações de placa/cliente podem desvincular um cadastro incompatível. Enviar `vehicle_id: null` remove o vínculo sem apagar o texto histórico.

Não existe ainda API pública de cadastro completo de veículos nem versionamento `/api/v1`; a busca da interface está em `GET /veiculos/buscar?client_id=...&q=...` e requer login.

## Segurança de produção

Configure `APP_ENV=production`, uma `SECRET_KEY` aleatória de pelo menos 32 caracteres e acesso HTTPS. Nesse ambiente a aplicação recusa chaves curtas e habilita cookie Secure. A chave deve ser compartilhada pelos processos da mesma instalação.

CSRF não substitui permissões, trilha global de auditoria, rate limit ou cofre de segredos. Esses itens da fase 0 continuam no backlog. Cadastros e leituras são acessíveis aos usuários autenticados; inativação/reativação é exclusiva do administrador.

## Verificação

```powershell
rtk python -m unittest discover -v
```

A suíte cobre os fluxos existentes, proteção CSRF, veículos, validações, proprietários, concorrência de formulário, leitura de odômetro, importação simulada/idempotente, dashboard, OS/estoque/recebíveis e upgrade/downgrade em SQLite. O XML do teste é fictício e autocontido.

A interface também foi exercitada no navegador com banco temporário e dados de demonstração. Validações com MySQL no ambiente de homologação, provedores fiscais e dispositivos físicos continuam necessárias antes de publicar a atualização.

## Próxima entrega

1. Completar a agenda semanal e apontamento de horas.
2. Complementos de auditoria e testes de concorrência em MySQL.
3. Inspeção configurável com anexos.

Depois: inspeção com anexos, aprovação digital, razão de estoque, compras, financeiro gerencial e integrações conforme o plano principal.
