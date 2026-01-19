# config.py
from pathlib import Path

from kivy.utils import platform

if platform == "android":
    from android.storage import app_storage_path
    CONFIG_DIR = Path(app_storage_path()) / ".config/celebrations"
else:
    CONFIG_DIR = Path.home() / ".config/celebrations"

CONFIG_PATH = CONFIG_DIR / "birthdays.json"
