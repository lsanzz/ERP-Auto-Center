# Homologação fiscal (NF-e de peças e NFS-e de serviços)

O código de emissão existe (Focus NFe e UniNFe), mas **nenhuma nota foi emitida de verdade ainda**. Antes de vender a emissão fiscal, siga este roteiro com uma oficina piloto. Tudo começa em **homologação**: notas de teste, sem valor fiscal.

## O que você precisa providenciar
- [ ] Certificado digital **A1** (arquivo .pfx) da oficina piloto, dentro da validade, e a senha dele.
- [ ] Conta na **Focus NFe** (recomendado para hospedagem na nuvem) com o token de homologação. Alternativa: UniNFe num computador Windows da oficina, veja `docs/conector-uninfe-windows.md`.
- [ ] Do **contador** da oficina:
  - regime tributário (Simples, Presumido ou Real) e CRT;
  - CFOP de venda de peças, dentro e fora do estado;
  - CSOSN/CST e alíquotas;
  - NCM das peças mais vendidas;
  - código do serviço municipal (LC 116, normalmente 14.01, manutenção de veículos);
  - alíquota de ISS;
  - inscrição municipal.
- [ ] Confirmar se a **prefeitura** da oficina é atendida pela Focus para NFS-e (veja a lista de municípios no site da Focus). Algumas cidades exigem credenciamento prévio no portal da prefeitura.

## Passo a passo no sistema
1. `/sistema/admin/integracao`: informe o token **de homologação** e deixe o ambiente em **HOMOLOGACAO**.
2. **Configurações → Dados da empresa:** preencha CNPJ, IE, IM, endereço completo com código IBGE, regime e CNAE. Salve: a empresa é criada ou atualizada na Focus automaticamente.
3. Envie o certificado A1 em **Configurações → Dados da empresa → Certificado digital**.
4. Nos produtos de teste, preencha NCM e CFOP.
5. Inicie o processador de tarefas (veja [implantacao.md](implantacao.md), item "Tarefas em segundo plano"). Sem ele, as consultas de retorno não andam.

## Testes obrigatórios (marque cada um)
| # | Teste | Resultado esperado |
|---|---|---|
| 1 | NF-e de 1 peça, cliente pessoa física do mesmo estado | Autorizada; XML e DANFE disponíveis em Fiscal |
| 2 | NF-e com 3 peças, cliente CNPJ com IE, outro estado | Autorizada com CFOP interestadual |
| 3 | NF-e com NCM inválido | Rejeitada com a mensagem da SEFAZ visível ao usuário |
| 4 | Cancelamento da nota do teste 1 dentro do prazo | Status CANCELADA |
| 5 | NFS-e de uma O.S. só com serviços | Autorizada pela prefeitura |
| 6 | NFS-e com peças e serviços (nota conjugada, se a cidade aceitar) | Conferir o comportamento; o sistema ainda não gera nota conjugada |
| 7 | Queda de internet durante a emissão | Nenhuma nota duplicada; a consulta posterior atualiza o status |
| 8 | Certificado vencido | Erro claro, sem travar a O.S. |

Anote o número, a chave e o print de cada teste numa pasta da oficina piloto.

## Ir para produção
1. Com o contador, confira as notas de teste: valores, impostos e dados do destinatário.
2. Troque o token pelo **de produção** e o ambiente para **PRODUCAO**.
3. Emita a primeira nota real de valor baixo e confira na SEFAZ ou no portal da prefeitura.
4. A partir daí, libere a emissão para essa oficina.

## Ainda não existe no sistema
- NFC-e (cupom ao consumidor);
- nota conjugada;
- inutilização de numeração;
- manifestação do destinatário;
- boleto.

Não ofereça esses itens na venda até serem desenvolvidos e homologados.
