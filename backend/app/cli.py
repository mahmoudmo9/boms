"""Command-line entry points used by the Windows scripts and for development.

    python -m app.cli db-init [--superuser postgres]   create/repair app role + database (superuser)
    python -m app.cli migrate                          alembic upgrade head (app role)
    python -m app.cli seed                             insert missing base data
    python -m app.cli create-user USERNAME             password read from stdin
    python -m app.cli set-password                     password read from stdin
"""

import argparse
import getpass
import sys
from pathlib import Path

from app.core.config import get_config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read_password(prompt: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline().rstrip("\r\n")


def cmd_db_init(args) -> None:
    from app.core import dbadmin
    from app.core.secrets import get_secret

    cfg = get_config()
    with dbadmin.superuser_connect(args.superuser) as conn:
        dbadmin.ensure_role(conn, cfg.db_user, get_secret("db_password"))
        if dbadmin.database_exists(conn, cfg.db_name):
            print(f"Database {cfg.db_name} exists; role password refreshed.")
        else:
            dbadmin.create_database(conn, cfg.db_name, cfg.db_user)
            print(f"Database {cfg.db_name} created.")


def alembic_config():
    from alembic.config import Config

    return Config(str(BACKEND_DIR / "alembic.ini"))


def cmd_migrate(_args) -> None:
    from alembic import command

    command.upgrade(alembic_config(), "head")
    print("Migrations at head.")


def cmd_seed(_args) -> None:
    from app.core.db import get_engine, new_session
    from app.modules.events import service as events
    from app.modules.system.seed_data import seed

    with get_engine().begin() as conn:
        counts = seed(conn)
    with new_session() as db:
        events.record(db, "base_data", "seed", "base_data.seeded", counts, source="script", actor="system")
        db.commit()
    print(f"Seeded: {counts}")


def cmd_create_user(args) -> None:
    from app.core.db import new_session
    from app.modules.system import users

    password = _read_password("Password: ")
    with new_session() as db:
        users.create_user(db, args.username, password, source="script")
        db.commit()
    print(f"User {args.username} created.")


def cmd_set_password(_args) -> None:
    from app.core.db import new_session
    from app.modules.system import users

    password = _read_password("New password: ")
    with new_session() as db:
        users.reset_password(db, password, source="script")
        db.commit()
    print("Password changed.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("db-init")
    p.add_argument("--superuser", default="postgres")
    p.set_defaults(func=cmd_db_init)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.set_defaults(func=cmd_create_user)
    sub.add_parser("set-password").set_defaults(func=cmd_set_password)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
