"""Command line used by the Windows scripts and by developers.

    python -m app.cli init-db        # superuser: create role + database + extensions
    python -m app.cli migrate        # run Alembic migrations to head
    python -m app.cli seed           # insert missing base data
    python -m app.cli create-user    # create the single app user
    python -m app.cli set-password   # reset the app user's password
    python -m app.cli backup --kind pre_update
    python -m app.cli restore-test
    python -m app.cli restore --backup-dir E:\\BOMS-Backup   # superuser; clean PC only

Passwords are read from environment variables (for scripts) or prompted for;
they are never accepted as command-line arguments.
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from app.core import dbadmin
from app.core.config import get_config
from app.core.db import new_session
from app.core.secrets import get_secret

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str | None = None) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if url:
        cfg.attributes["url"] = url
    return cfg


def superuser_conninfo() -> dict:
    env = os.environ
    return {
        "host": env.get("BOMS_PG_SUPERUSER_HOST", get_config().db_host),
        "port": int(env.get("BOMS_PG_SUPERUSER_PORT", get_config().db_port)),
        "user": env.get("BOMS_PG_SUPERUSER", "postgres"),
        "password": env.get("BOMS_PG_SUPERUSER_PASSWORD") or getpass.getpass("PostgreSQL superuser password: "),
    }


def _password(env_name: str, prompt: str) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    first = getpass.getpass(prompt)
    if first != getpass.getpass("Repeat: "):
        sys.exit("Passwords do not match")
    return first


def cmd_init_db(_: argparse.Namespace) -> None:
    config = get_config()
    conninfo = superuser_conninfo()
    dbadmin.ensure_role(conninfo, config.db_user, get_secret("db_password"))
    if dbadmin.database_exists(conninfo, config.db_name):
        print(f"Database {config.db_name} already exists")
    else:
        dbadmin.create_database(conninfo, config.db_name, config.db_user)
        print(f"Created database {config.db_name} owned by {config.db_user}")


def cmd_migrate(args: argparse.Namespace) -> None:
    command.upgrade(alembic_config(), args.revision)


def cmd_seed(_: argparse.Namespace) -> None:
    from app.modules.system.seed import seed_base_data

    with new_session() as db:
        counts = seed_base_data(db, source="script")
        db.commit()
    print(f"Seed inserted: {counts}")


def cmd_create_user(args: argparse.Namespace) -> None:
    from app.modules.system import users

    password = _password("BOMS_INITIAL_PASSWORD", "App password: ")
    with new_session() as db:
        if users.get_user(db) is not None:
            print("User already exists; use set-password to change the password")
            return
        users.create_user(db, args.username, password, source="script", language=args.language)
        db.commit()
    print(f"Created user {args.username}")


def cmd_set_password(_: argparse.Namespace) -> None:
    from app.modules.system import users

    password = _password("BOMS_INITIAL_PASSWORD", "New app password: ")
    with new_session() as db:
        users.set_password(db, password, source="script")
        db.commit()
    print("Password changed")


def cmd_store_secret(args: argparse.Namespace) -> None:
    """Store a secret in Windows Credential Manager; the value comes from BOMS_SECRET_VALUE."""
    from app.core.secrets import set_secret

    value = os.environ.get("BOMS_SECRET_VALUE")
    if not value:
        sys.exit("BOMS_SECRET_VALUE is not set")
    set_secret(args.name, value)
    print(f"Stored secret {args.name}")


def cmd_has_secret(args: argparse.Namespace) -> None:
    sys.exit(0 if get_secret(args.name, required=False) else 1)


def cmd_status(_: argparse.Namespace) -> None:
    """Exit 0 if the database is reachable and migrated; print the revision."""
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().connect() as conn:
        print(conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar())


def cmd_backup(args: argparse.Namespace) -> None:
    from app.modules.system import backup

    run_id = backup.run_backup(args.kind, source="script")
    print(f"Backup succeeded: {run_id}")


def cmd_restore_test(_: argparse.Namespace) -> None:
    from app.modules.system import backup

    result = backup.restore_test(source="script")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "passed":
        sys.exit(2)


def cmd_restore(args: argparse.Namespace) -> None:
    from app.modules.system import backup

    result = backup.full_restore(superuser_conninfo(), Path(args.backup_dir),
                                 Path(args.dump) if args.dump else None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    p = sub.add_parser("migrate")
    p.add_argument("revision", nargs="?", default="head")
    p.set_defaults(func=cmd_migrate)
    sub.add_parser("seed").set_defaults(func=cmd_seed)
    p = sub.add_parser("create-user")
    p.add_argument("--username", default="admin")
    p.add_argument("--language", choices=["fa", "en"], default="fa")
    p.set_defaults(func=cmd_create_user)
    sub.add_parser("set-password").set_defaults(func=cmd_set_password)
    p = sub.add_parser("store-secret")
    p.add_argument("name", choices=["db_password", "session_key", "archive_password"])
    p.set_defaults(func=cmd_store_secret)
    p = sub.add_parser("has-secret")
    p.add_argument("name", choices=["db_password", "session_key", "archive_password"])
    p.set_defaults(func=cmd_has_secret)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p = sub.add_parser("backup")
    p.add_argument("--kind", choices=["manual", "nightly", "pre_update"], default="manual")
    p.set_defaults(func=cmd_backup)
    sub.add_parser("restore-test").set_defaults(func=cmd_restore_test)
    p = sub.add_parser("restore", help="disaster recovery onto a clean PC")
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--dump", help="specific .dump file (default: latest in <backup-dir>/db)")
    p.set_defaults(func=cmd_restore)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
