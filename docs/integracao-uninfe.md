# Integração UniNFe — estado de implementação

O ERP usa uma empresa por instalação/banco. `ManagedCompany` é um espelho
histórico da Focus, não um mecanismo de isolamento multiempresa. Os parâmetros
do monitor pertencem ao `SystemSettings` da instalação.

## Implementado

- Para ERP hospedado e UniNFe no Windows, foi acrescentado um conector de saída
  HTTPS e uma fila de permissões de entrega (`20260924_17`). Configuração e
  limites estão em [conector-uninfe-windows.md](conector-uninfe-windows.md).
  O fluxo remoto inicial cobre emissão e retorno em homologação; não representa
  instalação ou autorização real já concluídas.

- Configurações na tela administrativa: regime/UF/cidade existentes, código
  IBGE, A1/A3, modelos 55/65, pastas, séries, numeração e orientações tributárias.
- Migração `20260922_11` para persistência dos parâmetros.
- Migração `20260924_16` amplia XMLs, respostas e snapshots para `LONGTEXT`
  no MySQL/MariaDB, evitando o limite de 64 KiB de `TEXT`. SQLite continua com
  `TEXT`. O downgrade conserva a capacidade ampliada para não truncar documentos
  históricos. Testados a compilação do DDL MySQL e o armazenamento local de um
  artefato acima de 64 KiB; a aplicação em MySQL real ainda precisa ser validada.
  O limite de pacote do servidor/cliente MySQL também deve comportar os artefatos.
- Migração `20260922_12` para reservas duráveis. A preparação serializa as
  reservas por empresa no MySQL, grava chave, número, série e snapshot com hash
  do XML. Uma retentativa reutiliza a mesma reserva. A combinação
  CNPJ/ambiente/modelo/série/número é única no banco. Alteração de uma nota
  preparada é recusada. O fluxo de homologação conecta preparação e publicador.
- Selecionar UniNFe interrompe a sincronização automática do cadastro com Focus.
- A leitura das configurações não cria mais uma integração Focus a partir de
  variáveis de ambiente antigas, nem substitui token ou ambiente persistidos.
  Sem provedor configurado, salvar a empresa não tenta sincronizar com Focus.
  Configurações legadas explícitas permanecem até a seleção do UniNFe; documentos
  históricos não são apagados. Tokens de gestão legados ainda devem ser removidos
  do ambiente da implantação quando a migração for concluída.
- Com UniNFe configurado, alterações da empresa exigem UF e regime válidos.
  Trocar a UF limpa o IBGE incompatível e solicita o novo município, preservando
  os demais parâmetros do monitor e as regras fiscais.
- Leitura de protocolo com conferência de chave e ambiente, preservação do XML
  processado, tratamento de rejeição/denegação/erro e proteção contra regressão
  de autorização/cancelamento por retorno antigo de emissão.
- Publicação atômica de XML preparado, sem sobrescrever conteúdo divergente.
  O volume precisa suportar hard links; falhas são reportadas, sem fallback
  para publicação parcial.
- Gerador inicial `uninfe_xml.py` para NF-e 55: endereços explícitos, itens,
  descontos por item, ICMSSN102, ICMS00/40, PIS/COFINS NT/Aliq, totais e
  pagamentos sem cartão. Situações não implementadas são recusadas. Esse
  gerador está conectado ao botão de emissão APENAS EM HOMOLOGAÇÃO. A validação XSD local
  usa o pacote da Unimake com revisão fixada (ver `app/schemas/nfe/README.md`),
  tornando opcional apenas a assinatura que o monitor ainda vai produzir.
  Os cenários de teste passam nessa validação; isso não comprova regras de
  negócio nem autorização. Ainda é necessário completar regras antes de uso.
- Os formulários de peças e OS coletam endereço estruturado, código IBGE e
  CPF/CNPJ/IE do destinatário, indicador de consumidor final e pagamento fiscal.
  A origem padrão da mercadoria está nas configurações da empresa.
- O formulário de peças permite selecionar NFC-e quando habilitada. Modelo 65
  usa série/contador próprios e exige consumidor final, operação interna,
  finalidade normal e presença compatível. Testes locais validam o XML e a
  publicação na pasta. QR Code é delegado ao monitor: `TaskNFeRecepcao.cs` do
  UniNFe configura a versão e CSC/ID Token e chama a autorização NFCe da DLL.
  Ainda falta comprovar a execução com o monitor real instalado.
- Tributação ampliada: CSOSN 101 (crédito informado), CSOSN 500 e CST 60
  (ST previamente retida), incluindo CEST e campos por item na tela fiscal.
  Grupos ST parcialmente preenchidos são recusados. Valores retidos não são
  adicionados ao imposto ou total da operação atual. Cobrança de nova ST,
  FCP/ICMS efetivo e outros enquadramentos ainda exigem implementação.
- Frete, seguro, despesas e desconto global são rateados proporcionalmente ao
  valor líquido dos itens, em centavos pelo maior resto; os totais reconciliam
  com o pagamento. Frete exige modalidade explícita. Quantidades/preços com
  precisão superior à do XML são rejeitados, sem arredondamento silencioso.
- Cancelamento em homologação usa evento 110111, justificativa e protocolo do
  XML autorizado. Pedido e resposta têm campos próprios na reserva (migração
  `20260923_14`); a nota permanece pendente até confirmação 135/155. Retorno 136
  não cancela a nota. Retentativa não republica evento já tentado; completar
  recuperação explícita de eventos rejeitados/inconclusivos ainda é necessária.
  O `procEventoNFe` confirmado é arquivado separadamente (migração
  `20260923_15`); XML de autorização é preservado.

## Referências para a próxima etapa tributária

O pacote fixado contém `IBSCBS` como `TTribNFe`, com CST, cClassTrib e a escolha
`gIBSCBS` (`TCIBS_NFe`). Essa escolha exige vBC, gIBSUF, gIBSMun, vIBS e gCBS,
com grupos opcionais para redução/diferimento/devolução e tributações especiais.
`IBSCBSTot` usa `TIBSCBSMonoTot`. Configurar somente uma alíquota não implementa
esses cálculos: faltam classificação, base, regras de totalização vigentes e
grupos especiais. Não considerar o suporte IBS/CBS concluído.

## Ainda necessário para emissão utilizável

O fluxo local de homologação foi exercitado com monitor/retorno simulados,
incluindo falha inconclusiva e retentativa sem republicação. Nenhuma chamada à
SEFAZ foi feita. Produção permanece bloqueada explicitamente até completar as
regras fiscais. Consultas usam as pastas preservadas na reserva, mesmo se a
configuração da empresa mudar. Migração `20260922_13` registra a tentativa de
publicação antes da interação com o monitor.

- Gerador de XML 4.00 completo, validação XSD e regras tributárias por operação,
  incluindo os campos vigentes de IBS/CBS quando aplicáveis.
- Integrar a reserva transacional com o gerador e garantir commit antes de
  publicação; testar concorrência no MySQL, além dos testes unitários SQLite.
- Recuperação operacional de publicação inconclusiva: a retentativa consulta
  retornos sem republicar automaticamente; completar consulta de situação e
  ação explícita para reenvio quando comprovada a ausência do documento.
- Endereço estruturado e código IBGE do destinatário; não reutilizar os
  fallbacks de endereço existentes na implementação Focus.
- Configurar e testar QR Code/CSC no monitor Windows. O ERP produz XML anterior
  à assinatura; não armazena nem calcula segredos CSC nesta implementação.
- Consulta de situação por arquivo e correlação completa de lote/recibo,
  cancelamento, inutilização e recuperação de envios inconclusivos.
- Remoção das dependências restantes de Focus nas telas e rotas. Preservar
  documentos históricos e seus XMLs.
- DANFE, testes end-to-end, validação com schemas oficiais, migração de banco e
  instalação documentada do monitor/worker. Testes locais do protocolo não
  representam uma autorização em homologação da SEFAZ.

Certificados privados e senhas ficam no monitor Windows. A configuração do ERP
guarda apenas tipo/referência; cadastrar esses campos não instala o certificado.

Referência do contrato de arquivos:
https://github.com/Unimake/Uninfe/blob/main/docs/servicos/nfe/autorizacao.md
