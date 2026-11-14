"""Read the .env file at the repository root (no extra dependency needed)."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Put KEY=value lines into os.environ, without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:                 # inline comment, as in .env.example
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


def use_mock() -> bool:
    return os.environ.get("USE_MOCK", "false").strip().lower() == "true"
