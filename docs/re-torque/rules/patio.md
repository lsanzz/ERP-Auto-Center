# Rules: Pátio

### R-001 Cada box mostra uma única ação, que depende da etapa do carro
- Given um carro em um box
- When a etapa é diagnóstico, aguardando aprovação ou em reparo
- Then o cartão oferece, nesta ordem, enviar orçamento, iniciar reparo (depois de aprovado) ou marcar como pronto
- Evidence: [obs EV-001]
- Feature: F-001 · Screen: S-001

### R-002 O progresso do box é tempo decorrido sobre tempo vendido
- Given um carro em reparo com horas de mão de obra vendidas
- When o painel é exibido
- Then mostra o tempo decorrido, as horas vendidas e a porcentagem entre os dois
- Evidence: [obs EV-001]
- Feature: F-001 · Screen: S-001

### R-003 O KPI de prontos soma o valor a receber
- Given carros na etapa pronto
- When o painel é exibido
- Then o cartão mostra a quantidade e a soma dos valores das OS
- Evidence: [obs EV-002]
- Feature: F-002 · Screen: S-001

### R-004 Estoque baixo lista peças com saldo abaixo do mínimo
- Given peças com saldo menor que o mínimo
- When o painel é exibido
- Then lista código, local, saldo/mínimo e pedido em aberto
- Evidence: [obs EV-002]
- Feature: F-005 · Screen: S-001

| Probe | Input | Result | Evidence |
|---|---|---|---|
| Leitura da tela | Abrir `#/floor` | Ações por etapa e totais visíveis | [obs EV-002] |
