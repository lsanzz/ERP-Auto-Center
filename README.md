# ERP Auto Center

ERP Auto Center é um sistema de gestão desenvolvido para **oficinas mecânicas (Auto Center)**, criado para centralizar e automatizar toda a operação da empresa em uma única plataforma. O projeto foi desenvolvido sob medida para atender às necessidades do negócio, proporcionando maior organização, controle e eficiência nos processos administrativos e operacionais.

A plataforma reúne em um único ambiente o gerenciamento de clientes, ordens de serviço, orçamentos, peças, serviços, financeiro, documentos fiscais e equipe, permitindo que toda a rotina da oficina seja administrada de forma prática e segura.

## 🚀 Principais funcionalidades

### 📋 Gestão de clientes

- Cadastro completo de clientes
- Consulta rápida de informações
- Histórico de atendimentos

### 🔧 Ordens de Serviço

- Abertura de O.S.
- Controle dos serviços executados
- Inclusão de peças utilizadas
- Acompanhamento do andamento dos serviços
- Emissão de documentos em PDF

### 💰 Orçamentos

- Criação de orçamentos
- Inclusão de peças e serviços
- Conversão para Ordem de Serviço

### 🛠 Gestão de serviços

- Cadastro de serviços
- Organização dos procedimentos realizados pela oficina

### 📦 Controle de peças

- Cadastro de produtos
- Controle de estoque
- Utilização de peças nas Ordens de Serviço

### 💳 Financeiro

- Controle de receitas
- Registro de pagamentos
- Acompanhamento financeiro da oficina

### 💵 Formas de pagamento

- Cadastro e gerenciamento das formas de pagamento aceitas

### 👨‍🔧 Funcionários

- Cadastro de colaboradores
- Controle de acesso por níveis de permissão
- Área administrativa para gerenciamento da equipe

### 📄 Fiscal

- Importação de XML de Nota Fiscal Eletrônica (NF-e)
- Organização de documentos fiscais
- Integração com Focus NFe para emissão e importação de NF-e

## Configuração da Focus NFe

A integração fiscal fica salva no banco pela tela **Fiscal** após a primeira configuração. Para não depender de preenchimento manual em nenhuma instalação, também é possível configurar pelo `.env`:

```env
FOCUS_NFE_TOKEN=seu_token_focus
FOCUS_NFE_ENVIRONMENT=HOMOLOGACAO
FOCUS_NFE_BASE_URL=
FOCUS_NFE_COMPANY_NAME=Razao Social Ltda
FOCUS_NFE_COMPANY_DOCUMENT=00000000000000
FOCUS_NFE_STATE_REGISTRATION=
FOCUS_NFE_MUNICIPAL_REGISTRATION=
FOCUS_NFE_TAX_REGIME=
FOCUS_NFE_DEFAULT_NATURE=Venda
FOCUS_NFE_WEBHOOK_URL=
```

Se `FOCUS_NFE_BASE_URL` ficar vazio, o sistema usa automaticamente `https://homologacao.focusnfe.com.br` em homologação e `https://api.focusnfe.com.br` em produção.

### 📊 Dashboard

- Visão geral da operação
- Indicadores e informações importantes para gestão

## 🛠 Tecnologias utilizadas

- Python
- Flask
- SQLAlchemy
- HTML
- CSS
- Jinja2
- SQLite
- Bootstrap (interface personalizada)

## 🎯 Sobre o projeto

O ERP Auto Center foi desenvolvido como uma solução personalizada para atender às necessidades de uma oficina mecânica, substituindo controles manuais e processos descentralizados por um sistema integrado.

Seu objetivo é facilitar o gerenciamento das operações diárias, oferecendo mais organização, produtividade e controle sobre clientes, serviços, estoque, financeiro e documentos fiscais.

---

**ERP Auto Center** demonstra a aplicação de tecnologias web na criação de um sistema de gestão empresarial voltado para oficinas mecânicas, reunindo em uma única plataforma os principais processos necessários para uma administração eficiente e profissional.
