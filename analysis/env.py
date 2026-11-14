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


# Backup when the event's Verda server is down (docs/TECH.md section 2).
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
NVIDIA_CALLS_PER_MINUTE = 35    # the documented limit is about 40 per key: keep a margin


def nemotron_config() -> dict:
    """Where to send Nemotron calls, chosen by NEMOTRON_PROVIDER=verda (default) or nvidia."""
    provider = os.environ.get("NEMOTRON_PROVIDER", "verda").strip().lower()
    if provider == "nvidia":
        return {"provider": "nvidia",
                "base_url": os.environ.get("NVIDIA_BASE_URL", NVIDIA_BASE_URL),
                "key": os.environ.get("NVIDIA_API_KEY", ""),
                "key_name": "NVIDIA_API_KEY",
                "model": os.environ.get("NVIDIA_MODEL", NVIDIA_MODEL),
                "calls_per_minute": int(os.environ.get("NVIDIA_CALLS_PER_MINUTE", NVIDIA_CALLS_PER_MINUTE))}
    if provider != "verda":
        raise SystemExit(f"NEMOTRON_PROVIDER must be 'verda' or 'nvidia', not {provider!r}")
    return {"provider": "verda",
            "base_url": os.environ.get("NEMOTRON_BASE_URL", ""),
            "key": os.environ.get("VERDA_INFERENCE_KEY", ""),
            "key_name": "VERDA_INFERENCE_KEY",
            "model": os.environ.get("NEMOTRON_MODEL", ""),
            "calls_per_minute": None}
