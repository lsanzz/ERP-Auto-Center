# ERP hospedado e UniNFe no Windows

## Estado atual

Implementação inicial de **homologação**, não liberada para emissão real em produção.
O ERP prepara a nota e mantém uma fila no banco. O programa `uninfe_connector.py`,
executado no Windows, busca tarefas por HTTPS, publica os XMLs na pasta do UniNFe
e devolve protocolos/XMLs processados ao ERP. Não há servidor HTTP no Windows,
redirecionamento de portas ou acesso remoto ao certificado. O computador precisa
estar ligado, conectado à internet e com o UniNFe em execução.

Cada instalação/banco do ERP continua atendendo uma empresa. Não compartilhar
uma credencial entre empresas nem usar a mesma configuração em dois computadores.
Os caminhos locais utilizados são os do arquivo do conector, nunca caminhos
arbitrários recebidos pela API. A1/A3 continuam configurados no monitor Windows.

## Hospedagem (administrador)

1. Fazer backup do banco e aplicar as migrações até `20260924_17` no ambiente de
   homologação, com `AUTO_CREATE_SCHEMA=false`. As migrações não foram aplicadas
   automaticamente ao banco da instalação.
2. Definir `UNINFE_TRANSPORT=remote`, `UNINFE_CONNECTOR_ID` com uma identificação
   exclusiva de 8 a 80 caracteres (letras, números, hífen ou sublinhado) e
   `UNINFE_CONNECTOR_TOKEN` com uma credencial aleatória forte (pelo menos 32
   caracteres; preferir 32 bytes aleatórios codificados em hexadecimal).
3. Configurar HTTPS. Se houver proxy reverso, configurar somente proxies
   confiáveis para que o aplicativo reconheça a conexão HTTPS. Não liberar a
   API em HTTP e não confiar indiscriminadamente em cabeçalhos enviados pelo cliente.
4. Reiniciar o aplicativo. Se as emissões usam a fila assíncrona do ERP, manter
   também o processador `jobs-worker` em execução.
5. Nas configurações da empresa, selecionar UniNFe, homologação, documentos,
   certificado, município e as regras fornecidas pelo contador. A hospedagem
   não tenta abrir as pastas Windows no modo remoto.

Tratar o token como senha: não incluí-lo no Git, em URLs, capturas de tela ou
mensagens de suporte. A revogação é feita alterando/removendo a variável na
hospedagem e reiniciando o aplicativo. Atualizar a cópia no Windows ao rotacionar.

## Windows

1. Instalar/configurar UniNFe e certificado para a empresa em homologação.
2. Disponibilizar uma cópia deste projeto e um ambiente Python com suas
   dependências (`requirements.txt`). O conector reutiliza a validação e o
   transporte do ERP, mas não precisa de credenciais do banco hospedado.
3. Criar um arquivo local `connector.json`, ajustando URL e pastas existentes:

```json
{
  "erp_url": "https://erp.exemplo.com",
  "connector_id": "oficina-windows-01",
  "send_directory": "C:\\UniNFe\\Empresa\\Envio",
  "return_directory": "C:\\UniNFe\\Empresa\\Retorno",
  "authorized_directory": "C:\\UniNFe\\Empresa\\Autorizados"
}
```

4. Definir `UNINFE_CONNECTOR_TOKEN` no ambiente da conta que executará o programa,
   com a mesma credencial da hospedagem. Restringir o acesso a essa conta e às
   pastas fiscais. Não executar com privilégios de administrador sem necessidade.
5. Executar `python uninfe_connector.py --config connector.json --once` para uma
   rodada, ou sem `--once` para consultar a fila a cada 15 segundos. O programa
   deve permanecer aberto; instalação como serviço/tarefa agendada não é automática.

## Garantias e limites

- Autenticação exclusiva por token e identidade do conector, sem sessão de navegador.
- HTTP e redirecionamentos não são aceitos pelo cliente; respostas não ficam em cache.
- A autorização de entrega é consumida no banco **antes** da publicação. Repetir
  a requisição não concede nova publicação, mesmo se o monitor já consumiu o arquivo.
- Isso favorece não duplicar envios: se cair a conexão após consumir a autorização
  e antes de publicar, a tarefa pode ficar inconclusiva. Verificar monitor, pastas
  e situação fiscal; não apagar a tarefa nem criar outra nota para forçar reenvio.
- O ERP confere chave e ambiente dos retornos e não aceita um simples status
  `AUTORIZADO` informado pelo cliente. A fila só encerra uma autorização depois
  de arquivar o XML processado; um protocolo isolado não substitui o XML.
- XMLs até 10 MiB. Dimensionar também limites HTTP/proxy e `max_allowed_packet`
  do MySQL. O volume de envio precisa suportar a publicação atômica por hard link.
- Nesta etapa, o conector transporta emissão e seus retornos. Cancelamento remoto,
  solicitação remota explícita de consulta, recuperação assistida e DANFE ainda
  não estão concluídos. Cancelamento remoto é recusado antes de gerar evento.
- Notas reservadas antes da mudança conservam o transporte anterior. Não alterar
  snapshots ou copiar filas para reenviar notas já tentadas.

Os testes automatizados usam pastas temporárias e API local. Ainda é necessário
validar o fluxo real com hospedagem HTTPS, MySQL, UniNFe e SEFAZ em homologação.
