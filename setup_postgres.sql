-- ========================================
-- TABELA: clients
-- ========================================
CREATE TABLE clients (
id SERIAL PRIMARY KEY,
nome VARCHAR(160) NOT NULL,
cpf_cnpj VARCHAR(20),
telefone VARCHAR(30),
email VARCHAR(120),
endereco VARCHAR(255),
observacoes TEXT,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL
);

INSERT INTO clients VALUES
(1,'Cliente Exemplo','12345678900','11988887777','[cliente@example.com](mailto:cliente@example.com)','Rua das Oficinas, 100 - Centro - São Paulo/SP','Cliente criado automaticamente para demonstração.','2026-04-12 03:58:00.210558','2026-04-12 03:58:00.210566');

-- ========================================
-- TABELA: bank_accounts
-- ========================================
CREATE TABLE bank_accounts (
id SERIAL PRIMARY KEY,
nome VARCHAR(120) NOT NULL,
banco VARCHAR(120),
agencia VARCHAR(30),
conta VARCHAR(40),
saldo_inicial NUMERIC(12,2) NOT NULL,
saldo_atual NUMERIC(12,2) NOT NULL,
ativo BOOLEAN NOT NULL,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL
);

INSERT INTO bank_accounts VALUES
(1,'Conta Principal','Banco do Brasil','1234-5','98765-4',5000,5000,true,'2026-04-12 03:58:00.208731','2026-04-12 03:58:00.208737'),
(2,'Caixa PIX','Inter','0001','112233-0',1500,1500,true,'2026-04-12 03:58:00.208738','2026-04-12 03:58:00.208739');

-- ========================================
-- TABELA: payment_methods
-- ========================================
CREATE TABLE payment_methods (
id SERIAL PRIMARY KEY,
nome VARCHAR(80) NOT NULL UNIQUE,
tipo VARCHAR(30) NOT NULL,
permite_parcelamento BOOLEAN NOT NULL,
parcelas_maximas INTEGER NOT NULL,
ativo BOOLEAN NOT NULL,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL
);

INSERT INTO payment_methods VALUES
(1,'Dinheiro','DINHEIRO',false,1,true,'2026-04-12 03:58:00.212366','2026-04-12 03:58:00.212368'),
(2,'Pix','PIX',false,1,true,'2026-04-12 03:58:00.212369','2026-04-12 03:58:00.212369'),
(3,'Cartão de Débito','DEBITO',false,1,true,'2026-04-12 03:58:00.212369','2026-04-12 03:58:00.212370'),
(4,'Cartão de Crédito','CREDITO',true,12,true,'2026-04-12 03:58:00.212370','2026-04-12 03:58:00.212370');

-- ========================================
-- TABELA: employees
-- ========================================
CREATE TABLE employees (
id SERIAL PRIMARY KEY,
nome VARCHAR(120) NOT NULL,
funcao VARCHAR(80) NOT NULL,
telefone VARCHAR(30),
email VARCHAR(120),
ativo BOOLEAN NOT NULL,
observacoes TEXT,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL
);

INSERT INTO employees VALUES
(1,'Administrador','Gerente','11999990000','[admin@autocenter.local](mailto:admin@autocenter.local)',true,NULL,'2026-04-12 03:58:00.211508','2026-04-12 03:58:00.211510'),
(2,'Mecânico Demo','Mecânico','11999991111','[mecanico@autocenter.local](mailto:mecanico@autocenter.local)',true,NULL,'2026-04-12 03:58:00.211511','2026-04-12 03:58:00.211511');

-- ========================================
-- TABELA: budgets
-- ========================================
CREATE TABLE budgets (
id SERIAL PRIMARY KEY,
client_id INTEGER NOT NULL,
numero VARCHAR(20) NOT NULL UNIQUE,
status VARCHAR(30) NOT NULL,
placa VARCHAR(10),
veiculo_descricao VARCHAR(160),
subtotal NUMERIC(12,2) NOT NULL,
desconto NUMERIC(12,2) NOT NULL,
total NUMERIC(12,2) NOT NULL,
observacoes TEXT,
validade DATE,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL,
FOREIGN KEY (client_id) REFERENCES clients(id)
);

INSERT INTO budgets VALUES
(1,1,'ORC-00001','ABERTO','ABC1D23','Volkswagen Gol 1.6 2019',260,0,260,'Orçamento de exemplo gerado na carga inicial.',NULL,'2026-04-12 03:58:00.217124','2026-04-12 03:58:00.223774');

-- ========================================
-- TABELA: budget_items
-- ========================================
CREATE TABLE budget_items (
id SERIAL PRIMARY KEY,
budget_id INTEGER NOT NULL,
item_type VARCHAR(20) NOT NULL,
reference_id INTEGER,
descricao VARCHAR(255) NOT NULL,
quantidade NUMERIC(12,2) NOT NULL,
valor_unitario NUMERIC(12,2) NOT NULL,
desconto NUMERIC(12,2) NOT NULL,
total NUMERIC(12,2) NOT NULL,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL,
FOREIGN KEY (budget_id) REFERENCES budgets(id)
);

INSERT INTO budget_items VALUES
(1,1,'SERVICO',1,'Troca de óleo',1,80,0,80,'2026-04-12 03:58:00.220732','2026-04-12 03:58:00.220735'),
(2,1,'PECA',1,'Óleo 5W30',4,45,0,180,'2026-04-12 03:58:00.220735','2026-04-12 03:58:00.220736');

-- ========================================
-- TABELA: financial_entries
-- ========================================
CREATE TABLE financial_entries (
id SERIAL PRIMARY KEY,
entry_type VARCHAR(20) NOT NULL,
descricao VARCHAR(255) NOT NULL,
categoria VARCHAR(80),
valor NUMERIC(12,2) NOT NULL,
vencimento DATE NOT NULL,
payment_receipt_at DATE,
status VARCHAR(20) NOT NULL,
payment_method_id INTEGER,
installment_number INTEGER NOT NULL,
installment_total INTEGER NOT NULL,
reference_type VARCHAR(30),
reference_id INTEGER,
bank_account_id INTEGER,
created_at TIMESTAMP NOT NULL,
updated_at TIMESTAMP NOT NULL,
FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id),
FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id)
);
