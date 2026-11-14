"""Settings shared by the decision scripts: repo paths, .env values, mock mode.

Scripts run outside Docker on our laptops, where nothing loads .env for us and
python-dotenv is not on the allowed list, so we read it ourselves.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
EXCHANGE = DATA / "exchange"
CACHE = DATA / "cache"
SAMPLE = Path(__file__).resolve().parent / "sample"

# The dataset stops here; "still online" is measured up to this date, not the PC clock
# (some team PCs have a wrong clock, and the parquet files know nothing after it).
DATASET_END = datetime(2026, 10, 1, tzinfo=timezone.utc)
# Wikimedia pageview data starts on this day.
PAGEVIEWS_START = datetime(2015, 7, 1, tzinfo=timezone.utc)

# Finnish titles in a Windows console would otherwise crash print().
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:  # inline comment, e.g. APP_PORT=8000   # 80 on the VPS
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)  # a real environment variable wins


_load_dotenv(REPO / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value not in ("", None) else default


# No key needed in mock mode, so the default is true: a fresh clone works out of the box.
USE_MOCK = (env("USE_MOCK", "true") or "true").lower() in ("1", "true", "yes")

WIKI_USER_AGENT = env(
    "WIKI_USER_AGENT",
    "TimeProofBot/0.1 (https://hackjunction.com; Junction 2026 hackathon prototype)",
)


def exchange_file(name: str) -> Path:
    """Canonical exchange file, or its .mock twin so mock output never poses as real data."""
    path = EXCHANGE / name
    return path.with_name(path.stem + ".mock" + path.suffix) if USE_MOCK else path
