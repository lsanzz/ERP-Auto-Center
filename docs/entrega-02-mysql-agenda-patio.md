# Entrega 02 — MySQL, agenda e pátio

O sistema passa a exigir MySQL fora dos testes automatizados. A conexão deve usar `mysql+pymysql`, tabelas InnoDB e charset `utf8mb4`.

## Funcionalidades

- agenda diária com cliente, veículo, responsável, horário e serviço previsto;
- cadastro de boxes, elevadores e outros recursos;
- bloqueio de conflito do mesmo recurso ou responsável no mesmo período;
- conversão do agendamento em OS;
- prazo prometido e recurso associados à OS;
- quadro do pátio por etapa, com motivo de espera e destaque de atraso;
- histórico das etapas percorridas pela OS.

## Configuração MySQL

```env
DATABASE_URL=mysql+pymysql://erp:SENHA@127.0.0.1:3306/erp_auto_center?charset=utf8mb4
AUTO_CREATE_SCHEMA=false
APP_ENV=production
SECRET_KEY=uma-chave-aleatoria-com-pelo-menos-32-caracteres
```

Para um banco versionado na revisão anterior:

```powershell
rtk python -m flask --app run db upgrade
```

Para banco legado, siga primeiro o processo de homologação e adoção descrito na entrega 01. Faça backup restaurável antes de aplicar alterações. A revisão `20260905_02` cria agenda, recursos, histórico de etapas e colunas operacionais da OS.

O `docker-compose.yml` agora fornece MySQL 8.4 apenas em `127.0.0.1:3306`; defina `MYSQL_PASSWORD` e `MYSQL_ROOT_PASSWORD` antes de iniciá-lo.

## Limites desta entrega

- a agenda atual é diária; visão semanal e recorrência ficam para a evolução seguinte;
- conflito é protegido com locks de linha no MySQL/InnoDB;
- a suíte local usa SQLite somente como teste isolado; validação de migração contra uma instância MySQL é necessária no ambiente de homologação;
- ainda faltam apontamento de horas, inspeção digital, aprovação online, razão de estoque e financeiro gerencial.
