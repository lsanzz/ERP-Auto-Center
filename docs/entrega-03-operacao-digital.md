# Entrega 03 — Operação digital integrada

## Implementado

- inspeção detalhada por O.S., quilometragem, conclusão obrigando a revisão de todos os itens e fotos JPG/PNG/WEBP;
- portal público responsivo para aprovação ou recusa do orçamento, com token armazenado somente como hash, validade, revogação automática do link anterior e evidências da resposta;
- reserva de peças por item da O.S., bloqueio por saldo disponível, consumo transacional e razão de movimentos;
- ajuste manual autorizado e rastreabilidade de saldos iniciais, edição e entradas XML;
- garantia criada automaticamente na finalização da O.S.;
- auditoria de alterações e limitação de tentativas de login;
- painel financeiro com vencidos e projeção de caixa para 30 dias;
- migration MySQL `20260906_03` e testes de regressão.

## Operação

1. Acesse uma O.S. e abra **Inspeção** para preencher o laudo e anexar evidências.
2. Em um orçamento, use **Gerar link para cliente** e envie o endereço exibido.
3. Na O.S., use **Reservar peças**. Após finalizar, a baixa de estoque consome as reservas e registra os movimentos.
4. Consulte **Estoque** no menu. Administradores encontram **Auditoria** dentro de **Configurações**.

## Banco MySQL

Em uma base nova e vazia, com `AUTO_CREATE_SCHEMA=false`, aplique:

```powershell
python -m flask --app run db upgrade
```

Em banco existente, faça backup e execute primeiro em uma cópia de homologação. A migration não foi aplicada automaticamente ao banco de produção.

## Limites que dependem de integração externa

- envio automático por WhatsApp/e-mail precisa da escolha do provedor e das credenciais;
- emissão fiscal efetiva usa a configuração fiscal existente e depende das credenciais do provedor;
- conciliação bancária automática depende do banco/Open Finance ou de um formato de extrato definido;
- multiempresa, filiais e cobrança SaaS dependem de decisão de produto e regras de isolamento.
