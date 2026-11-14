"""Reading and writing our data: exchange JSONL files and the dataset parquet files."""
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Iterator

from config import DATA


def account_hash(user: str | None) -> str | None:
    # Must match Maël's analysis/ exactly, or accounts and candidates cannot be joined.
    return hashlib.sha256(user.encode()).hexdigest()[:16] if user else None


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # A half-written last line after a crash must not stop the whole run.
                print(f"  skipped unreadable line {n} in {path.name}")


def append_jsonl(path: Path, row: dict) -> None:
    """One line at a time and flushed, so a crash loses at most the current case."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def done_rev_ids(path: Path) -> set[int]:
    return {row["rev_id"] for row in read_jsonl(path) if "rev_id" in row}


def write_atomic(path: Path, rows: Iterable[dict] | dict, jsonl: bool = True) -> None:
    """Write to a temp file then swap, so Léopold's importer never reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        if jsonl:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parquet_files() -> list[Path]:
    files = sorted(DATA.glob("versions-*.parquet"))
    if not files:
        raise SystemExit(
            "No data/versions-XX.parquet found. Download at least the first file:\n"
            "  curl -L -o data/versions-01.parquet "
            "https://github.com/MariaDB/mariadb-wikipedia-datasets/releases/download/m-2026-10/versions-01.parquet"
        )
    return files


def iter_versions(columns: list[str], page_ids: set[int] | None = None) -> Iterator[dict]:
    """Every version of every article (or of some articles), batch by batch.

    The text column alone is ~760 MB per file, so we never load a whole table.
    """
    import pyarrow.dataset as ds  # imported here so mock runs and tests need no pyarrow

    for path in parquet_files():
        # Rows are stored article by article, so the filter skips most of each file unread.
        filt = ds.field("page_id").isin(sorted(page_ids)) if page_ids is not None else None
        for batch in ds.dataset(path).to_batches(columns=columns, filter=filt, batch_size=2000):
            yield from batch.to_pylist()
