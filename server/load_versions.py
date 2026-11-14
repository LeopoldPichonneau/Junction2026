"""Load one versions-XX.parquet file into the system-versioned `article` table.

Each revision becomes a history row dated with its real Wikipedia timestamp, by writing
row_start/row_end ourselves (system_versioning_insert_history = 1), as in the official
MariaDB example (mariadb-system-versioning-wikipedia, MIT).

Usage (inside the server container):
    python load_versions.py /data/versions-01.parquet [--pages 1150,1256]

Safe to re-run after a crash: articles already in the table are skipped.
"""
import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq

from db import connect

COLUMNS = ["page_id", "title", "rev_id", "parent_id", "user", "anonymous",
           "comment", "minor", "sha1", "bytes", "text", "timestamp"]
# Batches are bounded by text size, not row count: some revisions are hundreds of KB.
MAX_BATCH_BYTES = 8 * 1024 * 1024
ONE_US = timedelta(microseconds=1)

INSERT_COLS = ("page_id, title, rev_id, parent_id, user, anonymous, comment, minor, "
               "sha1, len, text, row_start")
INSERT_HISTORY = f"INSERT INTO article ({INSERT_COLS}, row_end) VALUES ({', '.join(['%s'] * 13)})"
INSERT_CURRENT = f"INSERT INTO article ({INSERT_COLS}) VALUES ({', '.join(['%s'] * 12)})"


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def fmt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")


def as_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def iter_articles(path: str, pages: set[int] | None):
    """Yield (page_id, [rows]) one article at a time; the file is sorted by article."""
    pf = pq.ParquetFile(path)
    current, rows, seen, skip = None, [], set(), False
    for batch in pf.iter_batches(batch_size=500, columns=COLUMNS):
        for row in batch.to_pylist():
            pid = row["page_id"]
            if pages and pid not in pages:
                continue
            if pid != current:
                if rows:
                    yield current, rows
                # Re-inserting an article would clash with its current row: skip a second block.
                skip = pid in seen
                if skip:
                    log(f"WARNING page {pid} appears twice in {path}; second block skipped")
                seen.add(pid)
                current, rows = pid, []
            if not skip:
                rows.append(row)
    if rows:
        yield current, rows


def prepare(rows: list[dict]) -> list[dict]:
    """Sort, drop duplicate rev_ids, and make start times strictly increasing."""
    uniq = {r["rev_id"]: r for r in rows}.values()
    out = sorted(uniq, key=lambda r: (as_utc(r["timestamp"]), r["rev_id"]))
    prev = None
    for r in out:
        ts = as_utc(r["timestamp"])
        # Two edits in the same second would give a zero-length period: nudge by 1 µs.
        if prev is not None and ts <= prev:
            ts = prev + ONE_US
        r["start"] = ts
        prev = ts
    return out


def values(r: dict) -> list:
    return [r["page_id"], r["title"], r["rev_id"], r["parent_id"], r["user"],
            bool(r["anonymous"]), r["comment"], bool(r["minor"]), r["sha1"],
            r["bytes"], r["text"] or "", fmt(r["start"])]


def timeline(rows: list[dict]) -> Counter:
    """Edits and reverts per month. A revert restores the sha1 of an earlier, non-adjacent revision."""
    edits, reverts, seen, prev_sha = Counter(), Counter(), set(), None
    for r in rows:
        month = r["start"].strftime("%Y-%m")
        edits[month] += 1
        sha = r["sha1"]
        if sha and sha != prev_sha and sha in seen:
            reverts[month] += 1
        if sha:
            seen.add(sha)
        prev_sha = sha
    return {m: (edits[m], reverts[m]) for m in edits}


def load_article(conn, page_id: int, rows: list[dict]) -> int:
    rows = prepare(rows)
    with conn.cursor() as cur:
        batch, size = [], 0
        for r, nxt in zip(rows, rows[1:]):
            batch.append(values(r) + [fmt(nxt["start"])])
            size += len(r["text"] or "")
            if size >= MAX_BATCH_BYTES:
                cur.executemany(INSERT_HISTORY, batch)
                batch, size = [], 0
        if batch:
            cur.executemany(INSERT_HISTORY, batch)
        # The latest revision has no end: MariaDB keeps it as the current row.
        cur.execute(INSERT_CURRENT, values(rows[-1]))

        last = rows[-1]
        cur.execute(
            "REPLACE INTO article_stats (page_id, title, versions, first_edit, last_edit) "
            "VALUES (%s, %s, %s, %s, %s)",
            (page_id, last["title"], len(rows), rows[0]["start"].date(), last["start"].date()))
        cur.execute("DELETE FROM article_timeline WHERE page_id = %s", (page_id,))
        cur.executemany(
            "INSERT INTO article_timeline (page_id, month, edits, reverts) VALUES (%s, %s, %s, %s)",
            [(page_id, m, e, rv) for m, (e, rv) in sorted(timeline(rows).items())])
    return len(rows)


def already_loaded(conn, page_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM article FOR SYSTEM_TIME ALL WHERE page_id = %s LIMIT 1", (page_id,))
        return cur.fetchone() is not None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parquet")
    ap.add_argument("--pages", help="comma-separated page_ids to load (default: all)")
    args = ap.parse_args()
    pages = {int(p) for p in args.pages.split(",")} if args.pages else None

    conn = connect(dict_rows=False)
    with conn.cursor() as cur:
        cur.execute("SET SESSION system_versioning_insert_history = 1")
    t0, n_articles, n_versions, skipped = time.time(), 0, 0, 0
    log(f"start {args.parquet}")
    try:
        for page_id, rows in iter_articles(args.parquet, pages):
            if already_loaded(conn, page_id):
                skipped += 1
                continue
            t = time.time()
            try:
                n = load_article(conn, page_id, rows)
                conn.commit()          # one transaction per article: a crash loses at most one
            except Exception as e:     # keep going; the article can be retried by re-running
                conn.rollback()
                log(f"ERROR page {page_id}: {e!r}")
                continue
            n_articles += 1
            n_versions += n
            log(f"page {page_id} '{rows[-1]['title']}': {n} versions in {time.time() - t:.1f}s "
                f"(total {n_articles} articles, {n_versions} versions)")
    finally:
        with conn.cursor() as cur:
            cur.execute("SET SESSION system_versioning_insert_history = 0")
        conn.close()
    log(f"done {args.parquet}: {n_articles} articles, {n_versions} versions, "
        f"{skipped} already loaded, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
