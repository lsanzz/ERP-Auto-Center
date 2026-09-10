from alembic import context
from flask import current_app

db = current_app.extensions['migrate'].db

if context.is_offline_mode():
    context.configure(url=db.engine.url, target_metadata=db.metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=db.metadata,
                          compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
