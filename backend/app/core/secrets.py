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
