# coding: utf-8
import os
import sys
import re
from decimal import Decimal
from datetime import datetime
from bs4 import BeautifulSoup
from flask import current_app
from sqlalchemy import or_

from app import create_app, db
from app.models import FinancialEntry, WorkOrder, WorkOrderItem

def parse_decimal_br(val_str: str) -> Decimal:
    """Converte string 'R$ 1.500,00' para Decimal('1500.00')."""
    if not val_str:
        return Decimal('0.00')
    cleaned = re.sub(r'[^\d,-]', '', str(val_str))
    cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return Decimal(cleaned)
    except:
        return Decimal('0.00')

def parse_date_br(date_str: str):
    """Converte 'DD/MM/YYYY' para datetime.date."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip()[:10], '%d/%m/%Y').date()
    except:
        return None

def process_financial_file(filepath: str, entry_type: str):
    print(f"Processando {filepath} como {entry_type}...")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        soup = BeautifulSoup(f, 'lxml')
    
    # Busca todas as trs, o financeiro do vhsys tem a estrutura mais simples
    trs = soup.find_all('tr')
    count = 0
    for tr in trs:
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 13:
            continue
        
        texts = [td.get_text(strip=True) for td in tds]
        
        # Ignora header row
        if texts[0] == 'Vencimento' or texts[0].startswith('Vencimento'):
            continue
            
        venc_str = texts[0]
        nome_pessoa = texts[1]
        nome_lancamento = texts[2]
        
        if entry_type == 'PAGAR' and len(tds) >= 14:
            situacao = texts[6]
            valor_original = parse_decimal_br(texts[7])
        else: # RECEBER
            situacao = texts[5]
            valor_original = parse_decimal_br(texts[6])
        
        # Status parsing
        sit_lower = situacao.lower()
        if 'pago' in sit_lower or 'recebido' in sit_lower:
            status = 'LIQUIDADO'
        elif 'cancelado' in sit_lower:
            status = 'CANCELADO'
        else:
            status = 'PENDENTE'
            
        # Description
        desc = nome_pessoa
        if not desc or desc == '-':
            desc = nome_lancamento
            
        entry = FinancialEntry(
            entry_type=entry_type,
            descricao=desc,
            categoria='Ordens de Serviço' if entry_type == 'RECEBER' else 'Despesas',
            valor=valor_original,
            vencimento=parse_date_br(venc_str),
            status=status,
            installment_number=1,
            installment_total=1
        )
        db.session.add(entry)
        count += 1
        
    db.session.commit()
    print(f"{count} lançamentos financeiros inseridos.")


def process_work_orders(filepath: str):
    print(f"Processando {filepath} como Ordens de Serviço...")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        soup = BeautifulSoup(f, 'lxml')
        
    trs = soup.find_all('tr')
    current_os = None
    count_os = 0
    count_items = 0
    
    for tr in trs:
        tds = tr.find_all('td', recursive=False)
        
        # Linha de OS tem 15 colunas
        if len(tds) == 15:
            texts = [td.get_text(strip=True) for td in tds]
            if texts[0] == 'OS' or not texts[0].isdigit():
                continue
                
            numero_os = texts[0]
            cliente = texts[1]
            # Valor Total
            total_os = parse_decimal_br(texts[6])
            data_os = parse_date_br(texts[8])
            situacao = texts[13]
            obs = texts[14]
            
            # Status mapping
            sit_lower = situacao.lower()
            status = 'ORCAMENTO'
            if 'atendido' in sit_lower or 'finalizado' in sit_lower or 'faturado' in sit_lower:
                status = 'FINALIZADA'
            elif 'aberto' in sit_lower or 'andamento' in sit_lower:
                status = 'EM_ANDAMENTO'
            elif 'cancelado' in sit_lower:
                status = 'CANCELADA'
                
            from app.models import Client
            dummy_client = Client.query.filter_by(nome='Cliente VHSys (Importado)').first()
            if not dummy_client:
                dummy_client = Client(nome='Cliente VHSys (Importado)')
                db.session.add(dummy_client)
                db.session.commit()

            current_os = WorkOrder(
                numero=numero_os,
                client_id=dummy_client.id,
                client_nome=cliente,
                created_at=data_os,
                observacoes=obs,
                status=status,
                total_servicos=Decimal('0'),
                total_pecas=Decimal('0'),
                total_geral=total_os
            )
            db.session.add(current_os)
            count_os += 1
            
        # Linha de Item tem 6 colunas
        elif len(tds) == 6 and current_os is not None:
            texts = [td.get_text(strip=True) for td in tds]
            if texts[0].startswith('TipoQtde.') or texts[0] == '':
                continue
                
            nome_item = texts[0]
            tipo_item = texts[1]  # Produto ou Serviço
            qtde = parse_decimal_br(texts[2])
            valor_unit = parse_decimal_br(texts[3])
            
            if qtde <= 0:
                qtde = Decimal('1')
                
            item_type = 'PECA' if tipo_item.lower() == 'produto' else 'SERVICO'
            
            item = WorkOrderItem(
                work_order=current_os,
                item_type=item_type,
                descricao=nome_item,
                quantidade=qtde,
                valor_unitario=valor_unit,
                total=qtde * valor_unit
            )
            db.session.add(item)
            
            if item_type == 'PECA':
                current_os.total_pecas += item.total
            else:
                current_os.total_servicos += item.total
                
            count_items += 1

    db.session.commit()
    print(f"{count_os} Ordens de Serviço inseridas com {count_items} itens.")

def main():
    app = create_app()
    with app.app_context():
        # APAGA TUDO
        from app.models import WorkOrderStatusHistory, WorkOrderPayment
        print('Limpando lançamentos financeiros atuais...')
        FinancialEntry.query.delete()
        print('Limpando ordens de serviço e itens atuais...')
        WorkOrderItem.query.delete()
        WorkOrderStatusHistory.query.delete()
        WorkOrderPayment.query.delete()
        WorkOrder.query.delete()
        db.session.commit()
        
        # IMPORTA
        process_financial_file('ContasPag-20260901151315.html', 'PAGAR')
        process_financial_file('ContasRec-20260901151355.html', 'RECEBER')
        process_work_orders('OrdemServico-20260901151421.html')
        
        print('IMPORTAÇÃO CONCLUÍDA!')

if __name__ == '__main__':
    main()
