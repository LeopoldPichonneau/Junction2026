"""Import the team's exchange files (data/exchange/*.jsonl) into MariaDB.

Usage (inside the server container):
    python import_jsonl.py                 # all four files found in /data/exchange
    python import_jsonl.py --only decisions

Safe to re-run: rows are upserted. A decision is rewritten only when it changed, because
`decision` is system-versioned and every UPDATE leaves a history row (proof of when a case
was published or withdrawn).
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from db import connect

EXCHANGE = Path(os.environ.get("DATA_DIR", "/data")) / "exchange"
KINDS = {"framing", "image", "sources", "coordination"}
DECISIONS = {"flag", "dismiss", "human_review"}
ACCOUNT_KINDS = {"declared_bot", "bot_like", "throwaway", "single_purpose", "normal"}


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  {path.name}:{n} skipped (bad JSON: {e})")


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def parse_ts(value: str) -> str:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")


def candidate_row(d: dict):
    if d.get("kind") not in KINDS:
        raise ValueError(f"unknown kind {d.get('kind')!r}")
    return (int(d["rev_id"]), int(d["page_id"]), d.get("title"), d["kind"],
            parse_ts(d["timestamp"]), d.get("account_hash"), bool(d.get("synthetic", False)), dump(d))


def analysis_row(d: dict):
    nem = d.get("nemotron") or {}
    model = nem.get("model") or d.get("model") or os.environ.get("NEMOTRON_MODEL", "nemotron")
    suspicious = nem.get("suspicious")
    return (int(d["rev_id"]), model, None if suspicious is None else bool(suspicious), dump(d))


def decision_row(d: dict):
    decision = d.get("decision")
    if decision not in DECISIONS:
        decision = "human_review"            # two-opinion rule: anything unexpected goes to review
    exp = d.get("exposure") or {}
    still = exp.get("still_online", d.get("still_online"))
    if still is None and exp:
        still = exp.get("live_until") is None
    readers = exp.get("readers_est")
    return (int(d["rev_id"]), decision, decision == "flag" and bool(d.get("publish")),
            d.get("confidence"), exp.get("days_live"),
            None if readers is None else int(readers), None if still is None else bool(still), dump(d))


def account_row(d: dict):
    if d.get("kind") not in ACCOUNT_KINDS:
        raise ValueError(f"unknown account kind {d.get('kind')!r}")
    return (d["account_hash"], d["kind"], d.get("score"), dump(d))


TABLES = {
    "candidates": ("candidate", candidate_row,
                   "INSERT INTO candidate (rev_id, page_id, title, kind, edited_at, account_hash, synthetic, data) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE page_id=VALUES(page_id), "
                   "title=VALUES(title), kind=VALUES(kind), edited_at=VALUES(edited_at), "
                   "account_hash=VALUES(account_hash), synthetic=VALUES(synthetic), data=VALUES(data)"),
    "analysis": ("analysis", analysis_row,
                 "INSERT INTO analysis (rev_id, model, suspicious, data) VALUES (%s,%s,%s,%s) "
                 "ON DUPLICATE KEY UPDATE model=VALUES(model), suspicious=VALUES(suspicious), data=VALUES(data)"),
    "decisions": ("decision", decision_row,
                  "INSERT INTO decision (rev_id, decision, publish, confidence, days_live, readers_est, "
                  "still_online, data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                  "decision=VALUES(decision), publish=VALUES(publish), confidence=VALUES(confidence), "
                  "days_live=VALUES(days_live), readers_est=VALUES(readers_est), "
                  "still_online=VALUES(still_online), data=VALUES(data)"),
    "accounts": ("account_profile", account_row,
                 "INSERT INTO account_profile (account_hash, kind, score, data) VALUES (%s,%s,%s,%s) "
                 "ON DUPLICATE KEY UPDATE kind=VALUES(kind), score=VALUES(score), data=VALUES(data)"),
}


def import_file(conn, name: str) -> None:
    table, to_row, sql = TABLES[name]
    path = EXCHANGE / f"{name}.jsonl"
    if not path.exists():
        print(f"{name}: {path} not found, skipped")
        return
    rows, bad = [], 0
    for d in read_jsonl(path):
        try:
            rows.append(to_row(d))
        except (KeyError, ValueError, TypeError) as e:
            bad += 1
            print(f"  {name}: line skipped ({e!r})")

    with conn.cursor() as cur:
        if name == "decisions":
            cur.execute("SELECT rev_id, data FROM decision")
            existing = {r["rev_id"]: json.loads(r["data"]) for r in cur.fetchall()}
            rows = [r for r in rows if existing.get(r[0]) != json.loads(r[-1])]
        for i in range(0, len(rows), 500):
            cur.executemany(sql, rows[i:i + 500])
    conn.commit()
    print(f"{name}: {len(rows)} rows written into {table}, {bad} bad lines")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=list(TABLES), action="append")
    args = ap.parse_args()
    conn = connect()
    try:
        for name in args.only or TABLES:
            import_file(conn, name)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
