"""Superuser-only database administration, used by install/restore scripts and tests.

The application itself never connects as superuser. The superuser password is
taken from libpq's usual sources (PGPASSWORD or pgpass.conf) or passed in.
"""

import psycopg
from psycopg import sql

from app.core.config import get_config

# Deterministic, OS-independent locale so that lower()/regex behave the same on every PC.
CREATE_DB = (
    "CREATE DATABASE {db} OWNER {role} TEMPLATE template0 ENCODING 'UTF8' "
    "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8' LOCALE 'C'"
)


def superuser_connect(superuser: str = "postgres", password: str | None = None, dbname: str = "postgres"):
    cfg = get_config()
    return psycopg.connect(
        host=cfg.db_host, port=cfg.db_port, user=superuser, password=password, dbname=dbname, autocommit=True
    )


def ensure_role(conn, role: str, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    conn.execute(
        sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )


def database_exists(conn, dbname: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone() is not None


def create_database(conn, dbname: str, owner: str) -> None:
    conn.execute(sql.SQL(CREATE_DB).format(db=sql.Identifier(dbname), role=sql.Identifier(owner)))
    with superuser_connect(conn.info.user, conn.info.password, dbname) as db:
        # Both extensions are "trusted", but creating them as superuser avoids depending on that.
        db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        db.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def drop_database(conn, dbname: str) -> None:
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))


def drop_role(conn, role: str) -> None:
    conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
