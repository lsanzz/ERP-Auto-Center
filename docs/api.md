# API

A API REST continua a mesma nesta etapa.

## Infraestrutura de banco
O sistema utiliza MySQL 8.4/InnoDB sem alterar os endpoints existentes.

## Variável de ambiente
```env
DATABASE_URL=mysql+pymysql://erp:SENHA@127.0.0.1:3306/erp_auto_center?charset=utf8mb4
```

## Compatibilidade
Os endpoints existentes seguem iguais e as operações críticas usam locks de linha no MySQL em ambiente multiusuário.
