# Migração de dados

Acesso de administrador: **Configurações → Migração de dados** (`/configuracoes/migracao`).

## Preparar a instalação

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app run.py db upgrade
```

O envio e a confirmação iniciam automaticamente um processador em segundo plano.
Não é necessário abrir outro terminal para gerar a prévia. A tela também oferece
**Reativar processamento** para uma fila pendente após reiniciar a aplicação.

Em produção, pode-se usar um worker supervisionado no mesmo ambiente da aplicação
(`.\.venv\Scripts\python.exe -m flask --app run.py jobs-worker --watch`).
Para usar exclusivamente esse serviço, configure `MIGRATION_AUTO_WORKER=False`. `--watch`
mantém o processo aguardando novos arquivos; `--once` processa uma tarefa e encerra.
Uma importação grande cria uma tarefa por lote, portanto uma única execução de `--once`
não conclui necessariamente o arquivo inteiro. Configure reinício automático do serviço.
O comportamento anterior (sem opções: drenar a fila e encerrar) foi preservado.

A aplicação e todos os workers precisam compartilhar o diretório privado
`instance/data_migrations` (ou o caminho de `MIGRATION_STORAGE` na configuração Flask).
Ele não pode ser publicado pelo servidor web. O proxy deve permitir envios de 100 MB;
somente a rota de envio de migração recebe esse limite. As outras rotas mantêm o limite
original de 12 MB. A recuperação das duas leituras pendentes gerou apenas prévias, sem gravar cadastros.

## Como importar

1. Exporte um cadastro por arquivo no sistema antigo. Envie até 20 arquivos do mesmo
   destino por vez, somando no máximo 100 MB por requisição. Limite de 500.000 registros,
   150 colunas, 16.000 caracteres por célula e 60 KB por registro.
2. Selecione o cadastro de destino e informe o nome do sistema de origem. Para repetir
   importações financeiras, mantenha exatamente o mesmo nome de origem.
3. A leitura ocorre na fila. Depois abra o arquivo no histórico, confira as sugestões
   de correspondência e associe as demais colunas. “Atualizar prévia” mostra a conversão
   de até 20 registros, comparando valores originais e convertidos antes da confirmação.
   Ao alterar as colunas, atualize e confira a prévia novamente antes de importar.
   Isso não grava cadastros nem garante que os demais registros
   sejam válidos; a validação completa ocorre durante a importação.
4. Confirme a revisão e inicie a importação. É possível sair da página. Os resultados
   mostram importados, duplicados ignorados e linhas com erro. O relatório CSV contém
   todas as linhas com a posição original, resultado, motivo e valores originais.
5. Corrija somente os registros rejeitados e envie novamente. Lotes já gravados não são
   desfeitos por erros posteriores. A retomada de uma falha de processamento preserva
   o último lote confirmado. A função nunca sobrescreve cadastros existentes.

## Cadastros e regras

| Destino | Campos obrigatórios | Identificação de duplicados |
| --- | --- | --- |
| Clientes | Nome | CPF/CNPJ; sem documento, nome |
| Fornecedores | Nome | CPF/CNPJ; sem documento, nome |
| Produtos | Código e nome | Código |
| Serviços | Nome | Nome |
| Veículos | Documento do cliente, placa e descrição | Placa |
| Ordens de serviço | Número, data e uma identificação do cliente | Número da OS |
| Contas a pagar/receber | Valor e vencimento | Tipo + sistema de origem + ID informado ou chave calculada da linha |

Clientes e fornecedores com documento são comparados com os registros existentes,
removendo pontuação do documento. Sem documento, nomes iguais são tratados como
duplicados; homônimos devem receber documento para serem diferenciados. Placas e códigos
são normalizados. O histórico de chaves também protege contra reenvios posteriores.

Importe os clientes antes dos veículos. Um documento deve localizar exatamente um cliente;
nenhum vínculo é feito por um ID numérico presumido do outro sistema. O estoque inicial só
é registrado para produtos novos, junto de uma movimentação `SALDO_INICIAL` e seu autor.

Importe clientes e veículos antes das ordens de serviço. A ordem pode localizar o cliente
por CPF/CNPJ, pelo nome ou por uma coluna combinada como `MARILZA ASTRA DSN-4667`. Nesse
último caso, o sistema escolhe o nome de cliente existente que corresponde ao maior prefixo,
extrai a placa e usa o restante como descrição do veículo. Se não houver exatamente um
cliente compatível, a linha é rejeitada para evitar vínculo incorreto. A placa vincula o
veículo quando houver exatamente um veículo correspondente para aquele cliente. O vendedor
é associado a um funcionário de mesmo nome quando existir e também fica registrado nas
observações de origem. `Atendido`, `finalizado`, `faturado` e `concluído` viram
`FINALIZADA`; cancelamentos viram `CANCELADA`; registros em andamento viram
`EM_ANDAMENTO`; as demais situações entram como `ABERTA`. Os totais consolidados são
preservados. Essa exportação não contém o detalhamento de peças e serviços, portanto ela
cria a ordem sem itens individuais.

O financeiro aceita **títulos em aberto**, que entram como `PENDENTE`, sem movimentar
saldo bancário ou registrar pagamento. Quando houver identificador na origem, cada parcela
deve ter o seu; sem essa coluna, uma chave estável é calculada com os valores da linha.
“Nome da Receita” e “Nome da Despesa” são reconhecidos como descrição. Se não houver campo
equivalente, usa-se cliente, fornecedor, categoria ou um texto padrão. Se emissão/competência
forem omitidas, usa-se vencimento/emissão, respectivamente.
O destino financeiro não importa pagamentos ou notas fiscais.

Há modelos CSV de cabeçalho por destino na própria tela. Colunas extras podem ser
ignoradas. Relações ou entidades não listadas exigem um adaptador específico; não se
presume compatibilidade universal com qualquer exportação de qualquer sistema.

## Formatos

### Completar OS a partir de HTML detalhado

Para exportações com tabelas de produtos/serviços vinculadas à OS por `data-parent`,
use `scripts/complete_detailed_orders.py arquivo.html` para conferir, e acrescente
`--apply` para gravar. O comando cria OS ausentes e acrescenta apenas os itens que
faltam, respeitando quantidades repetidas. Também preenche campos vazios e preserva
pagamentos. Valores divergentes em itens já cadastrados ficam preservados e são
identificados no resultado. Cada alteração registra o estado anterior e os IDs dos
itens adicionados na auditoria. Esse comando é específico para o HTML detalhado;
a tela genérica de migração continua destinada às tabelas de resumo.

### Recuperar pagamentos de OS pelo contas a receber

O relatório de contas a receber pode identificar uma OS na coluna `Nome da Receita`
(por exemplo, `Ordem de Serviço 8708`) e informar sua forma de pagamento. O comando
abaixo confere o número, o total, a placa quando disponível e os pagamentos existentes:

```powershell
.\.venv\Scripts\python.exe scripts/reconcile_os_payments.py "caminho\ContasRec.html"
```

Acrescente `--apply` para gravar as correspondências conferidas. Pagamentos divididos
entre formas diferentes são registrados separadamente com os valores originais.
O comando preenche apenas pagamentos ausentes, registra auditoria e pode ser repetido
sem duplicar dados. Divergências de valor ou pagamentos existentes conflitantes ficam
pendentes. Ele não cria títulos financeiros, não registra baixas e não altera saldos.
O arquivo precisa conter o total completo da OS para confirmar a correspondência;
parcelamentos não são deduzidos de um relatório que possa estar filtrado.

### Separação automática nas ordens de serviço

A prévia e a gravação usam as mesmas regras para separar cliente, veículo e placa.
Placas antigas e Mercosul são reconhecidas com hífen, espaço ou sem separador.
Nomes compostos são preservados usando o cliente cadastrado correspondente ao maior
prefixo. Quando nenhum cliente único é localizado, aplica-se a compatibilidade do
importador antigo: a OS fica ligada ao cadastro auxiliar `Cliente VHSys (Importado)`,
enquanto o nome extraído permanece na própria OS. A coluna explícita de placa precisa
ser compatível com a placa presente no texto combinado.

OS e títulos financeiros aceitam a coluna Forma de pagamento. Nas OS, também se lê
`Pagamento: PIX` ou `Forma de pagamento: PIX` nas observações quando não existe valor
na coluna própria. O nome é associado a uma forma ativa cadastrada, ignorando acentos,
caixa e pontuação. Nomes desconhecidos são exibidos para correção antes da importação.
Sem essa informação na origem, o pagamento permanece sem preenchimento.

- CSV, TSV e TXT: dados delimitados, com escolha de separador ou detecção automática.
  Campos entre aspas e quebras de linha internas são aceitos. UTF-8 é o padrão;
  Windows-1252 e Latin-1 estão disponíveis para exportações antigas.
- HTML/HTM: tabelas de dados; selecione o número da tabela e a linha de cabeçalho.
  Scripts não são executados e o conteúdo é escapado na interface. Tabelas com
  mesclagem vertical (`rowspan`) devem ser exportadas novamente sem essa mesclagem.
- XLS: arquivos binários antigos e relatórios HTML salvos com extensão `.xls` são aceitos.
  O conteúdo é detectado antes da leitura; o sistema não confia somente na extensão.
- XLSX: selecione o número da aba e a linha de cabeçalho. O leitor usa o modo
  [read-only do openpyxl](https://openpyxl.readthedocs.io/en/latest/optimized.html),
  com limite de 256 MB descompactados. Fórmulas precisam ter resultados calculados
  salvos pelo Excel/LibreOffice; a importação não executa nem recalcula fórmulas.
- PDF, imagens, JSON, XML e arquivos compactados não são aceitos por
  esta função. Converta para um dos formatos tabulares suportados.

Datas: `DD/MM/AAAA`, `DD-MM-AAAA` ou `AAAA-MM-DD`. Valores: `1.234,56` ou `1234.56`,
com até duas casas decimais. Identificadores devem ser exportados como texto para
preservar zeros à esquerda; zeros já perdidos pelo sistema de origem não são recuperáveis.

## Processamento, falhas e operação

A leitura mantém apenas um lote de 500 registros em memória e grava a área de preparação
no banco. Na importação, consultas de duplicidade são agrupadas; inserções são feitas
em massa por conjunto de campos. Checkpoint, resultados por linha, chaves de deduplicação,
cadastros e movimentos de estoque compartilham a transação do lote. Conflitos excepcionais
de banco usam savepoints para identificar a linha rejeitada, preservando as demais.

O worker usa a fila existente, com bloqueio `SKIP LOCKED` no MySQL e bloqueio da migração
durante cada lote de importação. Erros transitórios têm até cinco tentativas. Após falha
definitiva, a tela oferece retomada de importação. Um erro de leitura exige corrigir o
arquivo/opções e fazer um novo envio.

Se o processo for encerrado abruptamente, a fila existente pode deixar a tarefa como
`PROCESSANDO`. Pare os workers antes da recuperação administrativa, confirme que a tarefa
não está mais em execução e recoloque **somente a tarefa interrompida** como `PENDENTE`,
com `available_at` no presente. Reinicie o serviço. A leitura retoma pela última posição
preparada; a importação retoma pelo checkpoint transacional. Não execute dois workers
com SQLite; esse banco é usado apenas nos testes.

Arquivos originais e linhas de preparação são privados, mas persistem para auditoria e
relatório. Planeje espaço em disco/banco e política de retenção antes de grandes cargas.
Inclua esse diretório nos backups protegidos. Não remova as chaves de deduplicação enquanto
quiser impedir reenvios. Não há exclusão automática ou desfazer migração nesta versão.

## Design e validação

Referência principal: design já existente em `base.html` e `configuracoes/index.html`.
A pesquisa Refero ao vivo retornou assinatura indisponível; foram usadas as referências
locais `craft-details.md` e `visual-workflow.md` como complemento.

| Decisão | Referência | Aplicação |
| --- | --- | --- |
| Tipografia, cores, bordas e superfícies | Design do ERP | Tokens existentes, azul para ações e etapa ativa |
| Painel principal com orientação lateral | Configurações existentes | Envio à esquerda, regras/modelos à direita |
| Etapas e revisão explícita | Fluxo solicitado + craft de formulários | Arquivo → colunas → resultados |
| Foco, rótulos e avisos assíncronos | Craft details | Controles semânticos, `focus-visible`, `aria-live` |
| Memória e interface limitadas | Craft de performance | Lotes, prévia de 20 registros, histórico paginado |

Sem imagens decorativas; ícone de envio vetorial simples. Interface conferida no navegador
em desktop e celular. Os testes usam somente dados sintéticos e SQLite isolado; valide
a migration e a carga no MySQL de homologação antes da implantação.

## Validação dos exemplos de setembro de 2026

Os dez arquivos fornecidos passaram por envio, preparação e renderização da prévia
em banco isolado: OS (33 linhas por formato), bancos (5), contas a receber (51),
contas a pagar (60) e entradas (31). Essa validação confirma a leitura tabular;
bancos e documentos de entrada ainda não possuem destinos próprios para gravação.
A associação de colunas permanece editável para exportações de outros sistemas.
