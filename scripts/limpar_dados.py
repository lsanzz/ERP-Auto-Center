import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.models import db, WorkOrder, Client, FinancialEntry

app = create_app()

with app.app_context():
    print("Iniciando limpeza total de Clientes, OS e Lançamentos...")

    # 1. Apaga Lançamentos (Necessário antes da OS)
    entradas = FinancialEntry.query.all()
    for entry in entradas: db.session.delete(entry)

    # 2. Apaga Ordens de Serviço (Necessário antes do Cliente)
    ordens = WorkOrder.query.all()
    for os in ordens: db.session.delete(os)
    
    # 3. Apaga Clientes
    clientes = Client.query.all()
    for cli in clientes: db.session.delete(cli)

    db.session.commit()
    print(f"Limpeza Concluída! Você apagou {len(clientes)} Clientes, {len(ordens)} O.S. e {len(entradas)} Contas financeiras do banco.")