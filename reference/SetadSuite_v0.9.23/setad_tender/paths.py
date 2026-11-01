from pathlib import Path
import os
import sys

APP_NAME = 'SetadTenderManager'

def app_data_dir() -> Path:
    if os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path

def asset_path(name: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base / 'assets' / name
