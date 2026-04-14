# API

A API REST continua a mesma nesta etapa.

## Infraestrutura de banco
Agora o sistema suporta PostgreSQL sem alterar os endpoints.

## Variável de ambiente
```env
DATABASE_URL=postgresql://postgres:1905@localhost:5432/erp_oficina
```

## Compatibilidade
Os endpoints existentes seguem iguais, mas agora operam corretamente sobre PostgreSQL em ambiente multiusuário.
