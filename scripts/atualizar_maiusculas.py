import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from app.models import db, Product, Service, WorkOrderItem, BudgetItem, Client

app = create_app()

with app.app_context():
    print("Convertendo registros para letras maiúsculas...")

    for p in Product.query.all():
        if p.nome: p.nome = p.nome.upper()
        if p.categoria: p.categoria = p.categoria.upper()
        if p.marca: p.marca = p.marca.upper()

    for s in Service.query.all():
        if s.nome: s.nome = s.nome.upper()
        if s.descricao: s.descricao = s.descricao.upper()

    for item in WorkOrderItem.query.all():
        if item.descricao: item.descricao = item.descricao.upper()

    for item in BudgetItem.query.all():
        if item.descricao: item.descricao = item.descricao.upper()

    for c in Client.query.all():
        if c.nome: c.nome = c.nome.upper()

    db.session.commit()
    print("✅ Sucesso! Todos os cadastros foram convertidos para maiúsculas.")