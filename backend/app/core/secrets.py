"""Secret lookup.

On Windows secrets live in Windows Credential Manager (via ``keyring``) under the
service name ``BOMS``. On other platforms (dev machines) they are read from
environment variables. An environment variable always wins, so tests and
scripts can override a value without touching the credential store.

Secret values are never logged and never included in error messages.
"""

import os
import sys

SERVICE = "BOMS"

# secret name -> environment variable
ENV_NAMES = {
    "db_password": "BOMS_DB_PASSWORD",
    "session_key": "BOMS_SESSION_KEY",
    "archive_password": "BOMS_ARCHIVE_PASSWORD",
}


class SecretMissing(RuntimeError):
    pass


def get_secret(name: str, required: bool = True) -> str | None:
    env_name = ENV_NAMES[name]
    value = os.environ.get(env_name)
    if not value and sys.platform == "win32":
        import keyring

        value = keyring.get_password(SERVICE, name)
    if not value and required:
        raise SecretMissing(
            f"Secret '{name}' is not set (Credential Manager entry {SERVICE}/{name} "
            f"or environment variable {env_name})"
        )
    return value or None


def set_secret(name: str, value: str) -> None:
    """Store a secret in Credential Manager. Only valid on Windows."""
    if sys.platform != "win32":
        raise RuntimeError(f"Set the environment variable {ENV_NAMES[name]} instead")
    import keyring

    keyring.set_password(SERVICE, name, value)


# ---- named secrets (v0.9.0: AI provider keys) -------------------------------------------------------------------------

def env_name_for(name: str) -> str:
    """``ai.anthropic`` -> ``BOMS_SECRET_AI_ANTHROPIC`` (dev machines and tests use the environment)."""
    import re

    return "BOMS_SECRET_" + re.sub(r"[^A-Za-z0-9]+", "_", name).upper().strip("_")


def get_named_secret(name: str) -> str | None:
    """A secret named by configuration (an AI provider key). Never logged, never stored in the database or files."""
    value = os.environ.get(env_name_for(name))
    if not value and sys.platform == "win32":
        import keyring

        value = keyring.get_password(SERVICE, name)
    return value or None


def set_named_secret(name: str, value: str | None) -> None:
    """Store (or with ``None`` remove) a named secret in Credential Manager. Only valid on Windows."""
    if sys.platform != "win32":
        raise RuntimeError(f"Set the environment variable {env_name_for(name)} instead")
    import keyring

    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass
