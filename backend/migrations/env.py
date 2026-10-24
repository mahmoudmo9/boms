"""Alembic environment. Migrations are hand-written SQL; they run as the app role."""

from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_config


def run_migrations_online() -> None:
    url = context.config.attributes.get("url") or get_config().db_url()
    engine = create_engine(url)
    with engine.connect() as connection:
        # core is on the path so uuidv7() resolves to the core.uuidv7 shim on
        # PostgreSQL < 18 (pg_catalog.uuidv7 always wins on 18+).
        connection.exec_driver_sql('SET search_path TO "$user", public, core')
        connection.commit()
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported")
run_migrations_online()
