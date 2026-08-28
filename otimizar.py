from sqlalchemy import text
from app import create_app
from app.models import db

app = create_app()

with app.app_context():
    print("Iniciando otimização profunda do PostgreSQL...")
    
    # Abre uma conexão autocommit dedicada fora de qualquer bloco de transação
    with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("VACUUM ANALYZE;"))
        
    print("PostgreSQL otimizado com sucesso! Estatísticas e índices atualizados.")