import os
import re
import html
import sys
from datetime import datetime, date

# Carrega o App e o Banco de Dados do seu ERP
try:
    from run import app
except ImportError:
    try:
        from app import app
    except ImportError:
        print("Erro: Não achou a aplicação Flask. Rode este script na mesma pasta do run.py.")
        sys.exit(1)

from app.models import (
    db, Product, Service, Client, Supplier, WorkOrder, WorkOrderItem, 
    FinancialEntry, PaymentMethod, StockEntry, StockEntryItem
)

# --- CACHE EM MEMÓRIA ---
clients_cache = {}
suppliers_cache = {}
products_code_cache = {}
products_name_cache = {}
services_cache = {}
pm_cache = {}
wo_cache = set()
se_cache = set()

def carregar_caches():
    global clients_cache, suppliers_cache, products_code_cache, products_name_cache, services_cache, pm_cache, wo_cache, se_cache
    clients_cache = {c.nome.strip().upper(): c.id for c in Client.query.all() if c.nome}
    suppliers_cache = {s.nome.strip().upper(): s.id for s in Supplier.query.all() if s.nome}
    
    # Armazena os produtos tanto por nome quanto por código para evitar a duplicação
    products_code_cache = {str(p.codigo).strip().upper(): p.id for p in Product.query.all() if p.codigo}
    products_name_cache = {str(p.nome).strip().upper(): p.id for p in Product.query.all() if p.nome}
    
    services_cache = {s.nome.strip().upper(): s.id for s in Service.query.all() if s.nome}
    pm_cache = {p.nome.strip().upper(): p.id for p in PaymentMethod.query.all() if p.nome}
    wo_cache = set([w.numero for w in WorkOrder.query.all() if w.numero])
    se_cache = set([s.numero_nota for s in StockEntry.query.all() if s.numero_nota])

# --- FUNÇÕES DE AJUDA ---
def limpar_moeda(v):
    if not v: return 0.0
    v = str(v).replace('R$', '').replace(' ', '').strip()
    if not v or v in ['None', 'nan', '']: return 0.0
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.')
    elif ',' in v: v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

def parse_data(d):
    if not d or str(d).strip() in ['None', 'nan', '']: return None
    try: return datetime.strptime(str(d).strip()[:10], '%d/%m/%Y').date()
    except: return None

# --- GERENCIADORES (Tratamento Anti-Duplicação) ---
def get_payment_method(nome):
    nome = str(nome).strip().upper()
    if not nome or nome == 'NONE': nome = 'OUTROS'
    if nome in pm_cache: return pm_cache[nome]
    
    pm = PaymentMethod(nome=nome[:80], tipo='OUTRO')
    db.session.add(pm)
    db.session.flush()
    pm_cache[nome] = pm.id
    return pm.id

def get_client(nome, doc='', telefone='', email='', endereco=''):
    nome_key = str(nome).strip().upper()
    if not nome_key or nome_key == 'NONE': return 1
    if nome_key in clients_cache: return clients_cache[nome_key]
    
    c = Client(nome=str(nome)[:160], cpf_cnpj=str(doc)[:20], telefone=str(telefone)[:30], email=str(email)[:120], endereco=str(endereco)[:255])
    db.session.add(c)
    db.session.flush()
    clients_cache[nome_key] = c.id
    return c.id

def get_supplier(nome, doc='', telefone='', email='', endereco=''):
    nome_key = str(nome).strip().upper()
    if not nome_key or nome_key == 'NONE': return 1
    if nome_key in suppliers_cache: return suppliers_cache[nome_key]
    
    s = Supplier(nome=str(nome)[:160], cnpj_cpf=str(doc)[:20], telefone=str(telefone)[:30], email=str(email)[:120], endereco=str(endereco)[:255])
    db.session.add(s)
    db.session.flush()
    suppliers_cache[nome_key] = s.id
    return s.id

def get_product(nome, codigo=None, preco=0, custo=0):
    nome_key = str(nome).strip().upper()
    cod_key = str(codigo).strip().upper() if codigo else None
    
    # 1. Se tem código e ele já existe, devolve o ID sem criar duplicidade
    if cod_key and cod_key in products_code_cache:
        return products_code_cache[cod_key]
        
    # 2. Se não tem código, mas já criamos um produto com esse nome antes
    if not cod_key and nome_key in products_name_cache:
        return products_name_cache[nome_key]
        
    if not nome_key and not cod_key: return 1
    
    # 3. Se não tem código, gera um único para ele
    if not cod_key:
        counter = len(products_code_cache) + 10000
        cod_key = f"PROD-{counter}"
        while cod_key in products_code_cache:
            counter += 1
            cod_key = f"PROD-{counter}"
            
    # Garantia final direta no banco
    p = Product.query.filter_by(codigo=cod_key[:40]).first()
    if p:
        products_code_cache[cod_key] = p.id
        return p.id
        
    p = Product(nome=str(nome)[:120], codigo=cod_key[:40], preco_venda=preco, custo=custo, estoque_atual=0)
    db.session.add(p)
    db.session.flush()
    
    products_code_cache[cod_key] = p.id
    products_name_cache[nome_key] = p.id
    return p.id

def get_service(nome, preco=0):
    nome_key = str(nome).strip().upper()
    if not nome_key: return 1
    if nome_key in services_cache: return services_cache[nome_key]
    
    s = Service(nome=str(nome)[:120], preco_base=preco)
    db.session.add(s)
    db.session.flush()
    services_cache[nome_key] = s.id
    return s.id

def status_financeiro(status_str):
    if 'PAGO' in str(status_str).upper(): return 'LIQUIDADO'
    return 'PENDENTE'

# --- EXTRATORES HTML ---
def extract_simples(caminho):
    if not os.path.exists(caminho): return []
    with open(caminho, 'r', encoding='utf-8') as f: html_content = f.read()
    
    thead = html_content[html_content.find('<thead>'):html_content.find('</thead>')]
    headers = [html.unescape(re.sub(r'<[^>]+>', '', h).strip()) for h in re.findall(r'<th[^>]*>.*?<div[^>]*>(.*?)</div>.*?</th>', thead, re.DOTALL)]
    
    tbody = html_content[html_content.find('<tbody>'):html_content.rfind('</tbody>')]
    linhas = []
    for block in tbody.split('<tr class="table-row-body"')[1:]:
        tds = [html.unescape(re.sub(r'<[^>]+>', '', td).replace('&nbsp;', '').strip()) for td in re.findall(r'<td[^>]*>.*?<div[^>]*>(.*?)</div>.*?</td>', block[:block.find('</tr>')], re.DOTALL)]
        if len(tds) == len(headers): linhas.append(dict(zip(headers, tds)))
    return linhas

def extract_com_itens(caminho):
    if not os.path.exists(caminho): return []
    with open(caminho, 'r', encoding='utf-8') as f: html_content = f.read()
    
    thead = html_content[html_content.find('<thead>'):html_content.find('</thead>')]
    headers_main = [html.unescape(re.sub(r'<[^>]+>', '', h).strip()) for h in re.findall(r'<th[^>]*>.*?<div[^>]*>(.*?)</div>.*?</th>', thead, re.DOTALL)]
    
    matches = re.finditer(r'<tr class="table-row-body" data-id="([^"]+)"[^>]*>(.*?)</tr>\s*<tr class="Table_L1" data-id="\1">\s*<td[^>]*>.*?<div class="subtable".*?<table[^>]*>.*?<thead>(.*?)</thead>.*?<tbody>(.*?)</tbody>.*?</table>', html_content, re.DOTALL)
    
    registros = []
    for m in matches:
        main_tds = [html.unescape(re.sub(r'<[^>]+>', '', td).replace('&nbsp;', '').strip()) for td in re.findall(r'<td[^>]*>.*?<div[^>]*>(.*?)</div>.*?</td>', m.group(2), re.DOTALL)]
        ths = [html.unescape(re.sub(r'<[^>]+>', '', th).strip()) for th in re.findall(r'<th[^>]*>.*?<div[^>]*>(.*?)</div>.*?</th>', m.group(3), re.DOTALL)]
        
        items = []
        for itr in re.finditer(r'<tr class="table-row-body"[^>]*>(.*?)</tr>', m.group(4), re.DOTALL):
            itds = [html.unescape(re.sub(r'<[^>]+>', '', td).replace('&nbsp;', '').strip()) for td in re.findall(r'<td[^>]*>.*?<div[^>]*>(.*?)</div>.*?</td>', itr.group(1), re.DOTALL)]
            if len(itds) == len(ths): items.append(dict(zip(ths, itds)))
        
        if len(main_tds) == len(headers_main):
            registros.append({'main': dict(zip(headers_main, main_tds)), 'items': items})
    return registros

# --- MÓDULOS DE IMPORTAÇÃO ---
def importar_pessoas():
    print("-> 1/4: Clientes e Fornecedores...")
    for r in extract_simples('Clientes-20260827230901.html'):
        nome = str(r.get('Nome do Cliente/Fornecedor', '')).strip()
        if not nome or 'Total' in nome: continue
        
        doc = str(r.get('CNPJ/CPF', ''))
        tipo = str(r.get('Tipo de Cadastro', ''))
        end = f"{r.get('Endereço','')} {r.get('Número','')} - {r.get('Bairro','')}, {r.get('Cidade','')}"
        
        if 'Fornecedor' in tipo: get_supplier(nome, doc, r.get('Telefone'), r.get('E-mail'), end)
        else: get_client(nome, doc, r.get('Telefone'), r.get('E-mail'), end)
    db.session.commit()

def importar_os():
    print("-> 2/4: Ordens de Serviço (Lendo Peças e Serviços Separadamente)...")
    for r in extract_com_itens('OrdemServico-20260827230324.html'):
        main = r['main']
        numero_os = str(main.get('OS', ''))
        if not numero_os.isdigit() or numero_os in wo_cache: continue
        
        cli_nome = str(main.get('Cliente', '')).strip()
        nova_os = WorkOrder(
            numero=numero_os[:20],
            client_id=get_client(cli_nome),
            client_nome=cli_nome[:160],
            status='CONCLUIDA' if 'Atendido' in str(main.get('Situação', '')) else 'ABERTA',
            total_servicos=limpar_moeda(main.get('Valor Serviços')),
            total_pecas=limpar_moeda(main.get('Valor Produtos')),
            total_geral=limpar_moeda(main.get('Valor Total')),
            data_entrada=parse_data(main.get('Data da OS')) or date.today()
        )
        db.session.add(nova_os)
        db.session.flush()
        wo_cache.add(numero_os)
        
        for item in r['items']:
            nome_item = item.get('', item.get('Produto', '')).strip()
            if not nome_item: continue
            
            tipo_item = str(item.get('Tipo', 'Produto')).upper()
            is_service = 'SERVI' in tipo_item
            
            v_unit = limpar_moeda(item.get('Valor Unitário', 0))
            qtde = limpar_moeda(item.get('Qtde.', 1))
            v_total = limpar_moeda(item.get('Valor Total', 0))
            
            if is_service:
                ref_id = get_service(nome_item, preco=v_unit)
                item_type = 'SERVICO'
            else:
                ref_id = get_product(nome_item, preco=v_unit)
                item_type = 'PECA'
                
            db.session.add(WorkOrderItem(
                work_order_id=nova_os.id,
                item_type=item_type,
                reference_id=ref_id,
                descricao=nome_item[:255],
                quantidade=qtde,
                valor_unitario=v_unit,
                total=v_total
            ))
    db.session.commit()

def importar_entradas():
    print("-> 3/4: Entradas e Estoque de Peças...")
    for r in extract_com_itens('Entrada-20260827231202.html'):
        main = r['main']
        numero = str(main.get('Entrada', ''))
        if not numero.isdigit() or numero in se_cache: continue
        
        nova_entrada = StockEntry(
            supplier_id=get_supplier(main.get('Fornecedor', '')),
            numero_nota=numero[:50],
            valor_total=limpar_moeda(main.get('Valor Total')),
            data_entrada=parse_data(main.get('Data da entrada')) or date.today()
        )
        db.session.add(nova_entrada)
        db.session.flush()
        se_cache.add(numero)
        
        for item in r['items']:
            nome_item = item.get('Produto', '').strip()
            if not nome_item: continue
            
            cod = str(item.get('Código', ''))
            v_unit = limpar_moeda(item.get('Valor Unitário', 0))
            
            ref_id = get_product(nome_item, codigo=cod if cod else None, custo=v_unit)
            
            db.session.add(StockEntryItem(
                stock_entry_id=nova_entrada.id,
                product_id=ref_id,
                quantidade=limpar_moeda(item.get('Qtde.', 1)),
                custo_unitario=v_unit,
                total_item=limpar_moeda(item.get('Valor Total', 0))
            ))
    db.session.commit()

def importar_financeiro():
    print("-> 4/4: Financeiro (Receitas e Despesas)...")
    for r in extract_simples('ContasRec-20260827230807.html'):
        venc = parse_data(r.get('Vencimento'))
        if venc:
            status_txt = str(r.get('Situação', '')).upper()
            db.session.add(FinancialEntry(
                entry_type='RECEBER',
                descricao=str(f"{r.get('Nome da Receita', '')} - {r.get('Cliente', '')}")[:255],
                valor=limpar_moeda(r.get('Valor Original')),
                vencimento=venc,
                status='LIQUIDADO' if 'PAGO' in status_txt else 'PENDENTE',
                payment_method_id=get_payment_method(r.get('Forma de Pagamento'))
            ))

    for r in extract_simples('ContasPag-20260827230550.html'):
        venc = parse_data(r.get('Vencimento'))
        if venc:
            status_txt = str(r.get('Situação', '')).upper()
            db.session.add(FinancialEntry(
                entry_type='PAGAR',
                descricao=str(f"{r.get('Nome da Despesa', '')} - {r.get('Fornecedor', '')}")[:255],
                categoria=str(r.get('Categoria', ''))[:80],
                valor=limpar_moeda(r.get('Valor Original')),
                vencimento=venc,
                status='LIQUIDADO' if 'PAGO' in status_txt else 'PENDENTE',
                payment_method_id=get_payment_method(r.get('Forma de Pagamento'))
            ))

    db.session.commit()


# --- INICIAR ---
if __name__ == '__main__':
    with app.app_context():
        print("\n⏳ PREPARANDO AMBIENTE (ISSO PODE LEVAR ALGUNS SEGUNDOS)...\n")
        
        # Garante clientes e fornecedores usando a forma atualizada (SQLAlchemy 2.0)
        if not db.session.get(Client, 1): db.session.add(Client(id=1, nome="CLIENTE PADRÃO GERAL"))
        if not db.session.get(Supplier, 1): db.session.add(Supplier(id=1, nome="FORNECEDOR PADRÃO GERAL"))
        if not db.session.get(Product, 1): db.session.add(Product(id=1, codigo="P-GERAL", nome="PEÇA DIVERSA", preco_venda=0))
        if not db.session.get(Service, 1): db.session.add(Service(id=1, nome="MÃO DE OBRA DIVERSA", preco_base=0))
        db.session.commit()

        carregar_caches()

        print("🚀 INICIANDO IMPORTAÇÃO DE DADOS 🚀")
        importar_pessoas()
        importar_os()
        importar_entradas()
        importar_financeiro()
        
        print("\n✅ MIGRAÇÃO 100% CONCLUÍDA COM SUCESSO! ✅\n")