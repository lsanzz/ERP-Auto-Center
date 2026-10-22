# Suporte ao cliente — Anexo III

## Canais
| Canal | Uso | Configuração no sistema |
|---|---|---|
| WhatsApp [NÚMERO] | Dúvidas e problemas do dia a dia | Variável `SUPPORT_WHATSAPP` (aparece no menu Perfil, nas páginas de erro e na tela de assinatura suspensa) |
| E-mail [E-MAIL] | Pedidos formais, LGPD, financeiro | Variável `SUPPORT_EMAIL` |

**Horário:** segunda a sexta, das [8h às 18h]; sábado, das [8h às 12h]. Fora desse horário, só incidentes **críticos**.

## Severidades e prazos
| Severidade | Exemplo | Primeira resposta | Solução ou contorno |
|---|---|---|---|
| **Crítica** | Sistema fora do ar; ninguém consegue logar; saldo bancário errado | 1 hora (inclusive fora do horário) | 4 horas |
| **Alta** | Uma função essencial parada (não abre O.S., não emite nota) | 4 horas úteis | 1 dia útil |
| **Média** | Erro com contorno; relatório divergente | 1 dia útil | 5 dias úteis |
| **Baixa** | Dúvida, sugestão, ajuste visual | 2 dias úteis | Próxima versão |

## Roteiro de atendimento
1. **Registrar:** cliente, usuário, tela, o que fez, o que esperava, print. Guarde numa planilha ou ferramenta de chamados (Trello, Notion ou HubSpot gratuito) com número, data, severidade e status.
2. **Reproduzir:** entre como o usuário, com permissão dele, ou consulte a **Auditoria** (`/operacao/auditoria`) para ver o que foi feito.
3. **Corrigir dados:** sempre por **estorno** ou edição pelo sistema. Nunca altere o banco direto: isso apaga o rastro da auditoria.
4. **Responder:** diga o que aconteceu e o que foi feito, em linguagem simples.
5. **Encerrar:** depois de o cliente confirmar. Se foi falha do sistema, crie um teste automatizado para ela não voltar.

## Respostas rápidas
- **"Esqueci a senha":** o administrador da oficina redefine em Configurações → Usuários. Se o próprio administrador esqueceu, você redefine pelo servidor.
- **"Login bloqueado":** foram 5 tentativas erradas; o bloqueio libera sozinho em 15 minutos.
- **"Apareceu 'outra pessoa alterou'":** duas pessoas salvaram o mesmo registro. Recarregue a página e refaça a alteração.
- **"Assinatura suspensa":** confirme o pagamento e atualize o campo **Pago até** em `/sistema/admin`.
- **"Cliente pediu os dados / pediu para ser apagado (LGPD)":** na ficha do cliente, use **Exportar dados (LGPD)** ou **Anonimizar cliente**. O prazo legal de resposta é de 15 dias.

## Monitoramento (para você saber antes do cliente)
- Cadastre `https://[DOMINIO]/api/health` num monitor gratuito (UptimeRobot ou Better Stack) com alerta no seu WhatsApp ou e-mail a cada 1 minuto.
- Configure o e-mail de falha do cron de backup (veja [implantacao.md](implantacao.md)).
