import sys
import os

# Adiciona a pasta raiz do projeto ao caminho do Python
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db, WorkOrder, FinancialEntry

app = create_app()

with app.app_context():
    print("Iniciando varredura para desfazer a importação...")

    # 1. Apagar as Ordens de Serviço importadas
    # Usamos o padrão de texto que o importador colocou nas observações para encontrar as exatas
    os_importadas = WorkOrder.query.filter(
        WorkOrder.observacoes.like('%Vendedor responsável na época:%') | 
        WorkOrder.observacoes.like('%Importado do sistema antigo%')
    ).all()
    
    qtd_os = len(os_importadas)
    for os_obj in os_importadas:
        db.session.delete(os_obj) 
        # Nota: O ERP já está configurado para apagar os "itens" vinculados automaticamente quando a O.S. é apagada.

    # 2. Apagar os Lançamentos Financeiros (Entradas) importados
    # Usamos o padrão de texto da descrição e a categoria
    fin_importados = FinancialEntry.query.filter(
        FinancialEntry.descricao.like('Entrada #%'),
        FinancialEntry.categoria == 'Fornecedores'
    ).all()
    
    qtd_fin = len(fin_importados)
    for fin_obj in fin_importados:
        db.session.delete(fin_obj)

    # Executa a exclusão no banco de dados
    db.session.commit()
    
    print(f"\n✅ Desfeito com sucesso!")
    print(f"-> {qtd_os} Ordens de Serviço foram apagadas.")
    print(f"-> {qtd_fin} Lançamentos Financeiros de Entrada foram apagados.")