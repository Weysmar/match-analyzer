"""Alembic's entry point. The connection comes from `ma_db.migrate`."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

engine = create_engine(context.config.attributes["url"], poolclass=NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
