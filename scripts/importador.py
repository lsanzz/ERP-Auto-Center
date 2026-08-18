import json
import sys
import os

# Aponta para a pasta base do sistema
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db, Product
from app.fiscal import import_external_payload

app = create_app()

with app.app_context():
    print("Iniciando injeção no banco de dados...")

    # 1. Injetar as Entradas (Catálogo de Peças + Financeiro)
    caminho_entradas = os.path.join(os.path.dirname(__file__), 'importacao_entradas.json')
    if os.path.exists(caminho_entradas):
        with open(caminho_entradas, 'r', encoding='utf-8') as f:
            dados_entradas = json.load(f)
            
            # A. Salvar todas as peças no Catálogo do ERP
            produtos = dados_entradas.get('produtos', [])
            novos = 0
            atualizados = 0
            for p in produtos:
                produto_existente = Product.query.filter_by(codigo=p['codigo']).first()
                if produto_existente:
                    produto_existente.custo = p['custo'] # Atualiza o custo da peça se já existir
                    atualizados += 1
                else:
                    novo_produto = Product(
                        codigo=p['codigo'],
                        nome=p['nome'],
                        unidade=p['unidade'],
                        custo=p['custo'],
                        preco_venda=p['preco_venda'],
                        ativo=True
                    )
                    db.session.add(novo_produto)
                    novos += 1
            
            db.session.flush()
            print(f"-> Catálogo de Peças: {novos} novos cadastros, {atualizados} atualizados.")
            
            # B. Salvar Contas a Pagar no Financeiro
            resultado_fin = import_external_payload({"financial_entries": dados_entradas.get('financial_entries', [])})
            print(f"-> Contas a Pagar processadas: {resultado_fin['financial_entries']}")
    else:
        print("-> Arquivo importacao_entradas.json não encontrado. Pulando...")

    # 2. Injetar as Ordens de Serviço
    caminho_os = os.path.join(os.path.dirname(__file__), 'importacao_os.json')
    if os.path.exists(caminho_os):
        with open(caminho_os, 'r', encoding='utf-8') as f:
            dados_os = json.load(f)
            resultado_os = import_external_payload(dados_os)
            print(f"-> O.S. importadas: {resultado_os['work_orders']}")
    else:
        print("-> Arquivo importacao_os.json não encontrado. Pulando...")

    # Finaliza e salva tudo
    db.session.commit()
    print("\n✅ Sucesso absoluto! O.S., Peças e Lançamentos Financeiros foram importados.")