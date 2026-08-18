import csv
import sys
import os
from decimal import Decimal

# Adiciona a pasta raiz ao path para importar a aplicação do ERP
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db, Service
from app.utils import parse_decimal

app = create_app()

def importar():
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'produtos_184258.csv'))
    
    if not os.path.exists(csv_path):
        print(f"Erro: O arquivo {csv_path} não foi encontrado.")
        return

    with app.app_context():
        print("Lendo o arquivo CSV de serviços...")
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            novos = 0
            atualizados = 0
            
            for row in reader:
                tipo = row.get('Tipo (Produto/Servico)', '').strip()
                
                # Importa apenas se for do tipo Serviço
                if tipo.lower() == 'servico':
                    nome = row.get('Nome do Produto (120)', '').strip()
                    preco_str = row.get('Valor Venda (Tabela Padrão)', '0').strip()
                    preco_base = parse_decimal(preco_str)
                    ativo = row.get('Situação (Ativo/Inativo)', 'Ativo').strip().lower() == 'ativo'
                    
                    if not nome:
                        continue
                        
                    # Verifica se o serviço já existe no banco
                    servico_existente = Service.query.filter(db.func.lower(Service.nome) == nome.lower()).first()
                    
                    if servico_existente:
                        servico_existente.preco_base = preco_base
                        servico_existente.ativo = ativo
                        atualizados += 1
                    else:
                        novo_servico = Service(
                            nome=nome,
                            descricao=f"Importado automaticamente do sistema antigo",
                            preco_base=preco_base,
                            ativo=ativo
                        )
                        db.session.add(novo_servico)
                        novos += 1
                        
            db.session.commit()
            print(f"\n✅ Importação concluída com sucesso!")
            print(f"-> {novos} novos serviços adicionados.")
            print(f"-> {atualizados} serviços atualizados.")

if __name__ == '__main__':
    importar()