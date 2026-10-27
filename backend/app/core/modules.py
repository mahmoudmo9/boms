"""Discovery of per-module plug-in files (``handlers.py``, ``searchable.py``)."""

import importlib
import pkgutil


_hooks_loaded = False


def load_hooks() -> None:
    """Import every module's ``hooks.py`` once: later modules register themselves with earlier ones there
    (for example quotes -> sourcing item status, costing sheet usage, command center)."""
    global _hooks_loaded
    if not _hooks_loaded:
        _hooks_loaded = True
        load_module_parts("hooks")


def load_module_parts(part: str) -> list[str]:
    """Import ``app.modules.<module>.<part>`` for every module that has one."""
    import app.modules

    loaded = []
    for info in pkgutil.iter_modules(app.modules.__path__):
        name = f"app.modules.{info.name}.{part}"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        loaded.append(name)
    return loaded
