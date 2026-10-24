"""Secret lookup: Windows Credential Manager via keyring, env vars as fallback.

Secret names: db_password, session_key, archive_password.
An environment variable BOMS_<NAME> (e.g. BOMS_DB_PASSWORD) takes precedence;
it is meant for tests, dev runs and non-Windows machines. Secret values are
never logged or included in error messages.
"""

import os
import sys

SERVICE = "BOMS"


class SecretMissing(RuntimeError):
    pass


def get_secret(name: str, required: bool = True) -> str | None:
    value = os.environ.get("BOMS_" + name.upper())
    if value:
        return value
    if sys.platform == "win32":
        import keyring

        value = keyring.get_password(SERVICE, name)
        if value:
            return value
    if required:
        raise SecretMissing(f"Secret '{name}' is not configured (Credential Manager service '{SERVICE}').")
    return None


def set_secret(name: str, value: str) -> None:
    import keyring

    keyring.set_password(SERVICE, name, value)
