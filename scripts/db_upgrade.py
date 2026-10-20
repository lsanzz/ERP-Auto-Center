"""Aplica as migrations do Alembic no banco configurado no .env.

A hospedagem cPanel não tem shell: rode este arquivo pelo campo "Execute python script"
do Setup Python App (equivale a `flask --app run.py db upgrade`). Faça backup do banco antes.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from flask_migrate import current, heads, upgrade  # noqa: E402

from run import app  # noqa: E402

with app.app_context():
    print('Revisão atual do banco:')
    current()
    print('Revisão mais nova do código:')
    heads()
    upgrade()
    print('Depois do upgrade:')
    current()
