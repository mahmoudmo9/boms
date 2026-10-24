from alembic import context
from sqlalchemy import create_engine

from app.core.db import app_db_url

config = context.config


def run_migrations_online() -> None:
    # Tests and scripts may hand over an open connection; otherwise connect as the app role.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(app_db_url())
    with engine.connect() as conn:
        context.configure(connection=conn, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
run_migrations_online()
