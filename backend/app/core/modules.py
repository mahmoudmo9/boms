"""Discovery of per-module plug-in files (``handlers.py``, ``searchable.py``)."""

import importlib
import pkgutil


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
