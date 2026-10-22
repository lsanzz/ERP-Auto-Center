# Política de Privacidade — LS Hub (sistema)

**Versão [1.0] — [DATA]** · Responsável: [RAZÃO SOCIAL], CNPJ [CNPJ] · Encarregado (DPO): [NOME], [E-MAIL]

> O site comercial já tem um aviso de privacidade próprio (`website/templates/privacy.html`). Esta política cobre o **sistema** usado pelas oficinas.

## 1. Papéis
- **Dados dos usuários das oficinas** (nome, login, perfil, IP, registros de acesso): a LS Hub é a **controladora**.
- **Dados dos clientes das oficinas** (nome, CPF/CNPJ, telefone, e-mail, endereço, veículos, placas, O.S.): a oficina é a **controladora**, e a LS Hub é a **operadora**, que trata esses dados só para prestar o serviço, conforme o [Acordo de Tratamento de Dados](acordo-tratamento-dados.md).

## 2. Que dados tratamos e por quê
| Dado | Finalidade | Base legal (LGPD art. 7º) |
|---|---|---|
| Login, senha (guardada só como hash), perfil | Dar acesso e controlar permissões | Execução de contrato |
| IP, data e hora de acessos e ações | Segurança, prevenção de fraude e auditoria | Legítimo interesse; cumprimento de obrigação legal (Marco Civil, art. 15) |
| Dados de clientes e veículos da oficina | Prestar o serviço contratado pela oficina | Conforme a base legal definida pela oficina (em regra, execução de contrato com o cliente final) |
| Dados fiscais (notas, XML) | Emissão e guarda de documentos fiscais | Cumprimento de obrigação legal |
| Texto enviado ao assistente de IA | Gerar a resposta pedida | Execução de contrato |

## 3. Com quem compartilhamos
São os suboperadores que nos ajudam a prestar o serviço:
- **Hospedagem:** [NOME DO PROVEDOR, PAÍS].
- **Emissão fiscal:** Focus NFe e/ou UniNFe, além da SEFAZ e das prefeituras.
- **Consulta de CNPJ:** CNPJá.
- **Consulta de placas:** [PROVEDOR].
- **Proteção contra robôs no login:** Cloudflare Turnstile.
- **Assistente de IA:** Groq (EUA). Recebe só o texto da conversa e os dados consultados naquele pedido. Não usamos esses dados para treinar modelos.

Não vendemos dados.

## 4. Transferência internacional
Alguns fornecedores (por exemplo, Groq e Cloudflare) processam dados fora do Brasil, com cláusulas contratuais e garantias de proteção compatíveis com a LGPD (art. 33).

## 5. Por quanto tempo guardamos
- **Dados da oficina:** durante o contrato e por até 30 dias depois, para exportação. Em seguida são apagados, com os backups expirando em até 60 dias.
- **Registros de acesso:** 6 meses (Marco Civil da Internet).
- **Documentos fiscais e financeiros:** pelo prazo exigido pela legislação tributária (em regra, 5 anos), sob guarda da oficina.

## 6. Segurança
- Conexão sempre criptografada (HTTPS).
- Senhas guardadas com hash.
- Verificação em duas etapas disponível.
- Permissões por perfil.
- Bloqueio de tentativas repetidas de login.
- Registro de auditoria.
- Backup diário com teste de restauração.
- Segredos fora do código.

## 7. Direitos dos titulares
O titular pode pedir confirmação, acesso, correção, anonimização, eliminação, portabilidade e informação sobre compartilhamento (art. 18).

**Clientes de uma oficina** fazem esse pedido à própria oficina. No sistema, o administrador da oficina tem, na ficha do cliente:
- **Exportar dados (LGPD):** atende ao pedido de acesso e portabilidade.
- **Anonimizar cliente:** atende ao pedido de eliminação. Mantém apenas O.S., financeiro e notas, que precisam ser guardados por lei.

Se receber um pedido diretamente, a LS Hub o encaminha à oficina em até 5 dias úteis.

## 8. Incidentes
Em caso de incidente de segurança com risco aos titulares, a LS Hub avisa as oficinas afetadas em até 48 horas, para que elas comuniquem a ANPD e os titulares quando necessário (art. 48).

## 9. Contato
Encarregado (DPO): [NOME] · [E-MAIL].
