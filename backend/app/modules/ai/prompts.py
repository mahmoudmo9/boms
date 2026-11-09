"""Prompts live in the repo: ``ai/prompts/<task>/<version>.md``; the latest version is used and its id
(``extraction/v1``) is logged with every call. A prompt file starts with a ``# system`` part and may have a ``# user``
part with ``{placeholders}``."""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / "prompts"


@dataclass
class Prompt:
    version: str
    system: str
    user: str

    def render(self, **values) -> str:
        text = self.user
        for key, value in values.items():
            text = text.replace("{" + key + "}", str(value))
        return text


def versions(task: str) -> list[str]:
    folder = ROOT / task
    if not folder.is_dir():
        return []
    return sorted((p.stem for p in folder.glob("v*.md")), key=lambda v: int(re.sub(r"\D", "", v) or 0))


@lru_cache(maxsize=64)
def load(task: str, version: str | None = None) -> Prompt:
    found = versions(task)
    if not found:
        raise KeyError(f"no prompt for task {task}")
    version = version or found[-1]
    text = (ROOT / task / f"{version}.md").read_text(encoding="utf-8")
    parts = re.split(r"^# (system|user)\s*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return Prompt(f"{task}/{version}", sections.get("system", text.strip()), sections.get("user", "{input}"))
