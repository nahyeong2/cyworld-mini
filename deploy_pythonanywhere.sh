#!/usr/bin/env bash
set -euo pipefail

cd /home/nahyeong2/cyworld-mini

python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

mkdir -p /home/nahyeong2/.config
if [ ! -f /home/nahyeong2/.config/miniroom.env ]; then
  .venv/bin/python - <<'PY'
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

target = Path('/home/nahyeong2/.config/miniroom.env')
target.write_text(
    'APP_ENV=production\n'
    f'SECRET_KEY={secrets.token_urlsafe(64)}\n'
    f'TOTP_ENCRYPTION_KEY={Fernet.generate_key().decode("ascii")}\n',
    encoding='utf-8',
)
target.chmod(0o600)
PY
fi

.venv/bin/python -c "import app; print('Miniroom server setup complete')"
