"""Superuser-level database administration.

Used only by the install/restore scripts (through ``app.cli``) and by the test
suite. The running app never connects as superuser.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql

EXTENSIONS = ("pg_trgm", "unaccent")


@contextmanager
def superuser_conn(conninfo: dict, dbname: str = "postgres") -> Iterator[psycopg.Connection]:
    with psycopg.connect(**{**conninfo, "dbname": dbname}, autocommit=True) as conn:
        yield conn


def role_exists(conninfo: dict, role: str) -> bool:
    with superuser_conn(conninfo) as conn:
        return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def database_exists(conninfo: dict, name: str) -> bool:
    with superuser_conn(conninfo) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def ensure_role(conninfo: dict, role: str, password: str) -> None:
    """Create (or reset the password of) the non-superuser app role.

    CREATEDB is needed for the restore test, which restores into a temporary database.
    """
    verb = "ALTER" if role_exists(conninfo, role) else "CREATE"
    with superuser_conn(conninfo) as conn:
        conn.execute(
            sql.SQL("{} ROLE {} LOGIN NOSUPERUSER CREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
            )
        )


def create_database(conninfo: dict, name: str, owner: str) -> None:
    with superuser_conn(conninfo) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
    with superuser_conn(conninfo, name) as conn:
        for ext in EXTENSIONS:
            conn.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(ext)))


def drop_database(conninfo: dict, name: str) -> None:
    with superuser_conn(conninfo) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def drop_role(conninfo: dict, role: str) -> None:
    with superuser_conn(conninfo) as conn:
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
