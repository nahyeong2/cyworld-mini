import os
import sys
from pathlib import Path


PROJECT_DIR = Path("/home/nahyeong2/cyworld-mini")
ENV_FILE = Path("/home/nahyeong2/.config/miniroom.env")

if ENV_FILE.exists():
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

os.environ.setdefault("APP_ENV", "production")

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app import app as application
