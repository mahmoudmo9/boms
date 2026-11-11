"""The Claude Code CLI behind the «اشتراک Claude» provider (v0.10.0 section 0.1.2): where it is, who is signed in,
the visible sign-in console, sign-out, and running it with no window.

BOMS runs as ``pythonw`` (no console), so every console program it starts would flash a window. Status checks, sign-out
and every AI call therefore start the CLI with ``CREATE_NO_WINDOW``; only «ورود به Claude» opens a console on purpose
(``CREATE_NEW_CONSOLE``, kept open with ``cmd /k`` until the owner closes it).

The sign-in belongs to a Windows account: the CLI stores it under that account's profile (``%USERPROFILE%\\.claude``).
``status()`` reports the account BOMS runs under and that folder, and names other profiles on the PC that hold a
sign-in, so a sign-in made under another account is explained instead of looking like a failure."""
import getpass
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
CREDENTIALS_FILE = ".credentials.json"
STATUS_TIMEOUT = 20

_RUNNER: Callable | None = None       # tests replace the process call: fn(args, visible) -> (exit code, stdout)
_WINDOWS: bool | None = None          # tests force the platform


def set_runner(fn: Callable | None, windows: bool | None = None) -> None:
    global _RUNNER, _WINDOWS
    _RUNNER, _WINDOWS = fn, windows


def is_windows() -> bool:
    return os.name == "nt" if _WINDOWS is None else _WINDOWS


def cli_path() -> str | None:
    """``BOMS_CLAUDE_CLI`` when set (a separately installed CLI, or the stand-in of the browser check), else the CLI
    bundled in the SDK wheel, else one on PATH."""
    override = os.environ.get("BOMS_CLAUDE_CLI")
    if override:
        return override if Path(override).is_file() else None
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude")
    return str(bundled) if bundled.exists() else shutil.which("claude")


def sdk_version() -> str | None:
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    return getattr(claude_agent_sdk, "__version__", None)


def hidden_flags() -> int:
    return CREATE_NO_WINDOW if is_windows() else 0


def _run_hidden(args: list[str]) -> tuple[int, str]:
    if _RUNNER:
        return _RUNNER(args, False)
    try:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=STATUS_TIMEOUT, stdin=subprocess.DEVNULL, creationflags=hidden_flags())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, done.stdout or ""


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def other_accounts(home: Path | None = None) -> list[str]:
    """Other profiles on this PC that hold a Claude sign-in (best effort: unreadable profiles are skipped)."""
    home = home or Path.home()
    found = []
    try:
        siblings = sorted(home.parent.iterdir())
    except OSError:
        return []
    for profile in siblings:
        try:
            if profile != home and (profile / ".claude" / CREDENTIALS_FILE).is_file():
                found.append(profile.name)
        except OSError:
            continue
    return found


def status() -> dict:
    """State of the sign-in block: ``no_sdk``, ``no_cli``, ``signed_in``, ``other_account`` (signed out here, but another
    Windows account on this PC is signed in) or ``signed_out``."""
    out: dict = {"sdk": sdk_version() is not None, "sdk_version": sdk_version(), "cli": cli_path(),
                 "account": getpass.getuser(), "config_dir": str(config_dir()), "logged_in": False,
                 "auth_method": None, "email": None, "other_accounts": [], "can_open_console": is_windows(),
                 "detail": None}
    if not out["sdk"]:
        return {**out, "state": "no_sdk"}
    if not out["cli"]:
        return {**out, "state": "no_cli"}
    code, text = _run_hidden([out["cli"], "auth", "status", "--json"])
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {}
        out["detail"] = text.strip()[:300] or None
    if not isinstance(data, dict):
        data = {}
    out["logged_in"] = bool(data.get("loggedIn"))
    out["auth_method"] = data.get("authMethod")
    out["email"] = data.get("email")
    if data.get("configDirectory"):
        out["config_dir"] = str(data["configDirectory"])
    if code != 0 and not data and not out["detail"]:
        out["detail"] = f"exit {code}"
    if out["logged_in"]:
        return {**out, "state": "signed_in"}
    out["other_accounts"] = other_accounts()
    return {**out, "state": "other_account" if out["other_accounts"] else "signed_out"}


def login_command(cli: str) -> str:
    """One ``cmd`` line: the outer quotes are the documented ``cmd /k "…"`` form, so a path with spaces works."""
    return f'cmd.exe /d /k ""{cli}" auth login --claudeai"'


def open_login_console() -> dict:
    """«ورود به Claude»: a visible console running the CLI's sign-in; it stays open until the owner closes it."""
    from app.core.errors import AppError

    cli = cli_path()
    if not cli:
        raise AppError("claude_cli_missing", "The Claude Code CLI was not found on this PC", status=409)
    if not is_windows():
        raise AppError("claude_login_unavailable", "The sign-in window opens only on the Windows PC that runs BOMS",
                       {"command": f'"{cli}" auth login --claudeai'}, status=409)
    command = login_command(cli)
    if _RUNNER:
        _RUNNER(command, True)
    else:
        try:
            subprocess.Popen(command, creationflags=CREATE_NEW_CONSOLE, cwd=str(Path.home()), close_fds=True)
        except OSError as exc:
            raise AppError("claude_login_failed", f"The sign-in window could not be opened: {exc}", status=500) from None
    return {"opened": True, "account": getpass.getuser(), "config_dir": str(config_dir())}


def logout() -> dict:
    from app.core.errors import AppError

    cli = cli_path()
    if not cli:
        raise AppError("claude_cli_missing", "The Claude Code CLI was not found on this PC", status=409)
    code, text = _run_hidden([cli, "auth", "logout"])
    if code != 0:
        raise AppError("claude_logout_failed", "Signing out did not succeed", {"detail": text.strip()[:300]}, status=502)
    return status()


class NoWindowAnyio:
    """Stands in for the ``anyio`` module inside the SDK's transport: identical, except that ``open_process`` adds
    ``CREATE_NO_WINDOW`` (the SDK gives no option for it, and the CLI is a console program)."""

    def __init__(self, real, flags: int):
        self._real, self._flags = real, flags

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def open_process(self, command, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | self._flags
        return await self._real.open_process(command, **kwargs)


def hide_sdk_windows() -> bool:
    """Make every CLI process the SDK starts windowless. Idempotent; a no-op off Windows."""
    if not is_windows():
        return False
    try:
        from claude_agent_sdk._internal.transport import subprocess_cli
    except ImportError:
        return False
    if not isinstance(subprocess_cli.anyio, NoWindowAnyio):
        subprocess_cli.anyio = NoWindowAnyio(subprocess_cli.anyio, CREATE_NO_WINDOW)
    return True
