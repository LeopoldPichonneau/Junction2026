"""Live watcher: follow new Finnish Wikipedia edits on our articles, one run per call.

Runs inside the server container (it needs MariaDB), triggered every few minutes by the
Hermes Agent scheduler through POST /api/internal/watch, or by hand:
    docker compose exec -T server python watch.py
    docker compose exec -T server python watch.py --since-hours 6     # first run: how far back to look

One run:
  1. read fi.wikipedia RecentChanges since the saved cursor (read-only API);
  2. keep the edits on our articles, fetch every revision we miss for those pages and store
     them in `article` with their REAL Wikipedia time (the dataset stops on 2026-10-01, so a
     page is caught up from its stored head: an edit is always compared with its true parent);
  3. run the candidate filters of analysis/find_candidates.py on the edits of the live window;
  4. send candidates through the usual scripts, unchanged: analysis/fetch_images.py,
     analysis/run_nemotron.py (2 calls at once), decision/decide.py (two-opinion rule);
  5. import the result. Files: data/exchange/live-{candidates,analysis,decisions}.jsonl, same
     formats as the batch files plus "source": "live" and "detected_at" on each candidate.

The watcher never judges and never publishes: `flag`, `human_review` and `publish` come from
decision/decide.py. It never writes to Wikipedia.

With USE_MOCK=true no request leaves the machine: one realistic fake edit is produced, the
models are mocked by their own scripts, files get a "-mock" suffix and every database change
is rolled back at the end (a dry run of the real code path).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from db import connect

REPO = Path(os.environ.get("REPO_DIR", "/repo"))            # analysis/ and decision/ are mounted here
EXCHANGE = Path(os.environ.get("DATA_DIR", "/data")) / "exchange"
USE_MOCK = os.environ.get("USE_MOCK", "true").strip().lower() == "true"
SUFFIX = "-mock" if USE_MOCK else ""
CANDIDATES = EXCHANGE / f"live-candidates{SUFFIX}.jsonl"
# run_nemotron.py adds "-mock" itself in mock mode, so it is given the plain name.
ANALYSIS_ARG = EXCHANGE / "live-analysis.jsonl"
ANALYSIS = EXCHANGE / f"live-analysis{SUFFIX}.jsonl"
DECISIONS = EXCHANGE / f"live-decisions{SUFFIX}.jsonl"
RUNS = EXCHANGE / f"live-runs{SUFFIX}.jsonl"
IMAGES = EXCHANGE / "images.jsonl"

API_URL = "https://fi.wikipedia.org/w/api.php"
LOCK_NAME = "timeproof_watch"
ONE_US = timedelta(microseconds=1)
MAX_RC_PAGES = 20            # 20 x 500 edits per run: far above a normal 10-minute window
MAX_REVISIONS_PER_PAGE = 300  # catch-up bound for one article in one run
NEMOTRON_PER_RUN = 20        # queue: the rest waits for the next run
NEMOTRON_WORKERS = 2         # shared server (docs/TECH.md section 7)
NEW_ACCOUNT_DAYS = 7

sys.path.insert(0, str(REPO / "analysis"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_state (
  id TINYINT UNSIGNED PRIMARY KEY,
  rc_timestamp DATETIME NOT NULL, rc_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
  last_check DATETIME(6) NOT NULL, last_ok BOOL NOT NULL DEFAULT 1,
  data JSON NOT NULL
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING
"""


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- Wikimedia: the only function that calls it ----------

_mock_base_text = ""         # stored text of the mock article, so the fake edit is a real diff


def wiki_api(params: dict) -> dict:
    """Read-only call to the fi.wikipedia API. Retries politely on 429 / 5xx."""
    if USE_MOCK:
        return mock_answer(params)
    headers = {"User-Agent": os.environ["WIKI_USER_AGENT"]}
    params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
    for attempt in range(4):
        r = httpx.get(API_URL, params=params, headers=headers, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After", "0") or 0) or 5 * (attempt + 1)
            log(f"  HTTP {r.status_code} from Wikipedia, waiting {wait} s")
            time.sleep(min(wait, 60))
            continue
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            if body["error"].get("code") == "maxlag":      # servers are busy: be a good citizen
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"Wikipedia API error: {body['error'].get('code')}")
        return body
    raise RuntimeError("Wikipedia API keeps refusing: try again at the next run")


MOCK_PAGE_ID = int(os.environ.get("MOCK_PAGE_ID", "1150"))
MOCK_REV_ID = 999_000_001


def mock_answer(params: dict) -> dict:
    """One realistic fake edit: the 1918 war renamed in the lead, as in real rev 24234965."""
    stamp = iso(utcnow() - timedelta(minutes=3))
    if params.get("list") == "recentchanges":
        return {"query": {"recentchanges": [
            {"type": "edit", "ns": 0, "title": "Mock article", "pageid": MOCK_PAGE_ID,
             "revid": MOCK_REV_ID, "old_revid": 0, "rcid": 1, "timestamp": stamp}]}}
    text = _mock_base_text
    # Only prose paragraphs: templates and infoboxes are cleaned away before words are compared.
    lines, left = text.split("\n"), 2
    for i, para in enumerate(lines):
        if left and len(para) > 200 and para[:1].isalpha() and re.search(r"[Ss]isällissota", para):
            lines[i] = re.sub(r"[Ss]isällissota", "vapaussota", para, count=1)
            left -= 1
    swapped = "\n".join(lines)
    if swapped == text:
        swapped = re.sub(r"<ref[\s>].*?</ref>", "", text, count=1, flags=re.S | re.I)
    if swapped == text:
        swapped = text + "\n\nVuoden 1918 sotaa kutsutaan vapaussodaksi."
    return {"query": {"pages": [{"pageid": MOCK_PAGE_ID, "title": "Mock article", "revisions": [
        {"revid": MOCK_REV_ID, "parentid": 0, "timestamp": stamp, "user": "MockEditor",
         "comment": "mock edit", "minor": False, "size": len(swapped.encode()),
         "slots": {"main": {"content": swapped}}}]}]}}


def sha1_base36(hex_sha1: str | None) -> str | None:
    """The API gives SHA-1 in hex; the dataset (and MediaWiki's database) store base 36, 31 chars."""
    if not hex_sha1:
        return None
    n, out = int(hex_sha1, 16), ""
    while n:
        n, d = divmod(n, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[d] + out
    return out.rjust(31, "0")


def recent_changes(cursor_ts: datetime, cursor_rcid: int) -> tuple[list[dict], bool]:
    """Article edits after the cursor, oldest first. Second value: False if the bound was hit."""
    out, cont = [], {}
    for _ in range(MAX_RC_PAGES):
        body = wiki_api({"action": "query", "list": "recentchanges", "rcnamespace": "0",
                         "rctype": "edit", "rcdir": "newer", "rcstart": iso(cursor_ts),
                         "rclimit": "500", "rcprop": "ids|timestamp|title", **cont})
        for rc in body.get("query", {}).get("recentchanges", []):
            # rcstart is inclusive: drop what the previous run already handled.
            if (parse_ts(rc["timestamp"]), rc["rcid"]) > (cursor_ts, cursor_rcid):
                out.append(rc)
        cont = body.get("continue") or {}
        if not cont:
            return out, True
    return out, False


def missing_revisions(page_id: int, head_ts: datetime, head_rev: int) -> tuple[str | None, list[dict]]:
    """Every revision of the page after our stored head, oldest first, with its text."""
    title, out, cont = None, [], {}
    while len(out) < MAX_REVISIONS_PER_PAGE:
        body = wiki_api({"action": "query", "prop": "revisions", "pageids": str(page_id),
                         "rvdir": "newer", "rvstart": iso(head_ts), "rvlimit": "50", "rvslots": "main",
                         "rvprop": "ids|timestamp|user|comment|sha1|size|flags|content", **cont})
        pages = body.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            break                                           # deleted or moved away: nothing to store
        title = pages[0].get("title") or title
        for rev in pages[0].get("revisions", []):
            ts = parse_ts(rev["timestamp"])
            if rev["revid"] != head_rev and (ts, rev["revid"]) > (head_ts.replace(microsecond=0), head_rev):
                out.append(rev)
        cont = body.get("continue") or {}
        if not cont:
            break
        time.sleep(0.3)                                     # a few requests per second at most
    out.sort(key=lambda r: (r["timestamp"], r["revid"]))
    return title, out


# ---------- database ----------

def commit(conn) -> None:
    if not USE_MOCK:            # mock = dry run: everything is rolled back at the end
        conn.commit()


def load_state(cur, since_hours: float) -> dict:
    cur.execute("SELECT rc_timestamp, rc_id, data FROM watch_state WHERE id = 1")
    row = cur.fetchone()
    if row:
        data = json.loads(row["data"]) if isinstance(row["data"], (str, bytes)) else row["data"]
        return {"ts": row["rc_timestamp"], "rcid": int(row["rc_id"]), "data": data or {}, "first": False}
    return {"ts": (utcnow() - timedelta(hours=since_hours)).replace(microsecond=0), "rcid": 0,
            "data": {"started_at": iso(utcnow()), "totals": {}}, "first": True}


def save_state(cur, state: dict, ok: bool) -> None:
    cur.execute(
        "INSERT INTO watch_state (id, rc_timestamp, rc_id, last_check, last_ok, data) "
        "VALUES (1, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE rc_timestamp = VALUES(rc_timestamp), "
        "rc_id = VALUES(rc_id), last_check = VALUES(last_check), last_ok = VALUES(last_ok), data = VALUES(data)",
        (state["ts"], state["rcid"], utcnow(), ok, json.dumps(state["data"], ensure_ascii=False)))


def our_pages(cur, page_ids: set[int]) -> set[int]:
    found, ids = set(), sorted(page_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        cur.execute(f"SELECT page_id FROM article_stats WHERE page_id IN ({','.join(['%s'] * len(chunk))})", chunk)
        found.update(r["page_id"] for r in cur.fetchall())
    return found


def store_revision(cur, page_id: int, title: str, rev: dict, sha1: str | None, text: str,
                   ts: datetime, is_revert: bool) -> None:
    """New current row; MariaDB archives the previous one. Both get the edit's real time:
    system versioning stamps rows with the session clock, so the clock is set to Wikipedia's."""
    epoch = (ts - datetime(1970, 1, 1)).total_seconds()
    cur.execute(f"SET timestamp = {epoch:.6f}")
    try:
        cur.execute(
            "UPDATE article SET title = %s, rev_id = %s, parent_id = %s, user = %s, anonymous = %s, "
            "comment = %s, minor = %s, sha1 = %s, len = %s, text = %s WHERE page_id = %s",
            (title, rev["revid"], rev.get("parentid") or None, rev.get("user"), is_anonymous(rev),
             rev.get("comment") or "", bool(rev.get("minor")), sha1, rev.get("size"), text, page_id))
    finally:
        cur.execute("SET timestamp = DEFAULT")
    # The precomputed tables behind /api/articles and the timeline must follow.
    cur.execute("UPDATE article_stats SET versions = versions + 1, last_edit = %s, title = %s WHERE page_id = %s",
                (ts.date(), title, page_id))
    cur.execute("INSERT INTO article_timeline (page_id, month, edits, reverts) VALUES (%s, %s, 1, %s) "
                "ON DUPLICATE KEY UPDATE edits = edits + 1, reverts = reverts + VALUES(reverts)",
                (page_id, ts.strftime("%Y-%m"), int(is_revert)))


def is_anonymous(rev: dict) -> bool:
    user = rev.get("user") or ""
    return bool(rev.get("anon") or rev.get("temp") or user.startswith("~"))


def is_new_account(cur, rev: dict, ts: datetime) -> bool:
    """Same meaning as find_candidates.py: within 7 days of the account's first edit in OUR data."""
    user = rev.get("user")
    if not user or is_anonymous(rev):
        return False
    cur.execute("SELECT MIN(row_start) AS first FROM article FOR SYSTEM_TIME ALL WHERE user = %s", (user,))
    first = cur.fetchone()["first"]
    return first is None or ts - first <= timedelta(days=NEW_ACCOUNT_DAYS)


# ---------- candidates (filters of analysis/find_candidates.py, one revision at a time) ----------

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass                                    # a line cut by a crash: ignored
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def sync_page(conn, page_id: int, window_start: datetime, known: set[int], run: dict) -> None:
    """Catch one article up with Wikipedia and write the live candidates found on the way."""
    global _mock_base_text
    import find_candidates as fc        # the team's filters, imported, not copied

    cur = conn.cursor()
    cur.execute("SELECT rev_id, title, sha1, text, row_start FROM article WHERE page_id = %s", (page_id,))
    head = cur.fetchone()
    if not head:
        return
    _mock_base_text = head["text"] or ""
    title, revisions = missing_revisions(page_id, head["row_start"], head["rev_id"])
    title = head["title"] if USE_MOCK or not title else title
    prev_ts, prev_sha, prev_text = head["row_start"], head["sha1"], head["text"] or ""
    prev_state = None                   # parsed form of prev_text, built only when needed

    for rev in revisions:
        slot = (rev.get("slots") or {}).get("main") or {}
        if "content" not in slot:       # text hidden by Wikipedia's admins: nothing to store or judge
            run["hidden"] += 1
            continue
        text = slot["content"]
        sha1 = sha1_base36(rev.get("sha1"))
        ts = parse_ts(rev["timestamp"])
        if ts <= prev_ts:               # same second as the previous version: keep periods non-empty
            ts = prev_ts + ONE_US
        live = ts >= window_start       # older ones only fill the gap since the dataset's end

        null_edit = bool(sha1) and sha1 == prev_sha
        is_revert = False
        if sha1 and not null_edit:
            cur.execute("SELECT 1 FROM article FOR SYSTEM_TIME ALL WHERE page_id = %s AND sha1 = %s LIMIT 1",
                        (page_id, sha1))
            is_revert = cur.fetchone() is not None

        line, state = None, None
        user = rev.get("user")
        if not live:
            run["backfilled"] += 1
        else:
            run["edits_on_our_articles"] += 1
            if null_edit:
                run["skipped_null"] += 1
            elif is_revert:
                run["skipped_revert"] += 1
            elif rev.get("minor"):
                run["skipped_minor"] += 1
            elif fc.is_declared_bot(user):
                run["skipped_bot"] += 1
            elif rev["revid"] not in known:
                if prev_state is None:
                    prev_state = fc.parse_state({}, prev_text)
                state = fc.parse_state({}, text)
                img = fc.image_changes(prev_state["images"], state["images"])
                refs_removed = max(0, prev_state["refs"] - state["refs"])
                kind = fc.pick_kind(img, refs_removed, prev_state["terms"] != state["terms"])
                if kind:
                    added, removed = fc.word_diff(prev_state["clean"], state["clean"])
                    names = {user, user.replace(" ", "_")} if user else set()
                    line = {
                        "rev_id": rev["revid"], "page_id": page_id, "title": title,
                        "timestamp": iso(ts), "kind": kind,
                        "account_hash": fc.account_hash(user),
                        "user_is_new": is_new_account(cur, rev, ts),
                        "synthetic": False,
                        "comment": fc.scrub_comment(rev.get("comment"), names),
                        "added": added, "removed": removed,
                        "image": img[0] if img else None,
                        "refs_removed": refs_removed,
                        "source": "live", "detected_at": iso(utcnow()),
                    }
                    if USE_MOCK:
                        line["mock"] = True
                else:
                    run["not_candidate"] += 1

        # The candidate is written before the database commit: after a crash in between, the
        # rerun stores the revision again and the line is not duplicated (rev_id already known).
        if line:
            append_jsonl(CANDIDATES, line)
            known.add(line["rev_id"])
            run["candidates"] += 1
            run["candidate_rev_ids"].append(line["rev_id"])
        store_revision(cur, page_id, title, rev, sha1, text, ts, is_revert)
        run["stored"] += 1
        prev_ts, prev_sha, prev_text, prev_state = ts, sha1, text, state
    commit(conn)
    cur.close()


# ---------- the usual scripts, unchanged ----------

def run_script(args: list[str], timeout: int) -> bool:
    log("  $ python " + " ".join(str(a) for a in args))
    try:
        p = subprocess.run([sys.executable, *map(str, args)], cwd=REPO, timeout=timeout,
                           capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        log(f"  timed out after {timeout} s (the next run resumes: results are written line by line)")
        return False
    for out_line in (p.stdout + p.stderr).strip().splitlines()[-12:]:
        log("    " + out_line[:300])
    return p.returncode == 0


def run_models(run: dict) -> None:
    """Candidates -> Nemotron -> decision/decide.py. Each script skips what it already did."""
    candidates = read_jsonl(CANDIDATES)
    if not USE_MOCK:
        nemotron_key = "NVIDIA_API_KEY" if os.environ.get("NEMOTRON_PROVIDER", "").lower() == "nvidia" \
            else "VERDA_INFERENCE_KEY"
        missing = [k for k in (nemotron_key, "GEMINI_API_KEY", "GEMINI_MODEL") if not os.environ.get(k)]
        if missing:
            # Not an error of the run: candidates stay queued in the file until the keys are set.
            run["models_waiting_for"] = missing
            log(f"  models skipped, missing in .env: {', '.join(missing)} (candidates stay queued)")
            return
    analysed = {r["rev_id"] for r in read_jsonl(ANALYSIS)}
    decided = {r["rev_id"] for r in read_jsonl(DECISIONS)}
    if any(c["rev_id"] not in analysed for c in candidates):
        if any(c.get("image") and "thumb_url" not in c["image"] for c in candidates):
            # Thumbnail, author and licence of the image as it was on the day of the edit.
            run_script([REPO / "analysis/fetch_images.py", "--candidates", CANDIDATES, "--images", IMAGES], 300)
        ok = run_script([REPO / "analysis/run_nemotron.py", "--candidates", CANDIDATES, "--out", ANALYSIS_ARG,
                         "--limit", NEMOTRON_PER_RUN, "--workers", NEMOTRON_WORKERS], 1500)
        if not ok:
            run["errors"].append("run_nemotron.py failed or timed out")
    if any(r["rev_id"] not in decided for r in read_jsonl(ANALYSIS)):
        ok = run_script([REPO / "decision/decide.py", "--input", ANALYSIS, "--output", DECISIONS], 600)
        if not ok:
            run["errors"].append("decide.py failed or timed out")


def import_live(conn) -> None:
    """Same row builders and SQL as import_jsonl.py, on the live files."""
    from import_jsonl import TABLES
    cur = conn.cursor()
    for name, path in (("candidates", CANDIDATES), ("analysis", ANALYSIS), ("decisions", DECISIONS)):
        _table, to_row, sql = TABLES[name]
        rows = []
        for d in read_jsonl(path):
            try:
                rows.append(to_row(d))
            except (KeyError, ValueError, TypeError) as e:
                log(f"  {path.name}: line skipped ({e!r})")
        if name == "decisions" and rows:
            # `decision` is versioned: rewrite a row only when it changed.
            cur.execute("SELECT rev_id, data FROM decision WHERE rev_id IN (%s)" % ",".join(["%s"] * len(rows)),
                        [r[0] for r in rows])
            same = {r["rev_id"]: json.loads(r["data"]) for r in cur.fetchall()}
            rows = [r for r in rows if same.get(r[0]) != json.loads(r[-1])]
        if name == "decisions" and rows:
            # Live edits are untrusted text read by the models minutes after it was written: a live flag
            # goes on the site only once a team member approved it on the review desk (server/live.py).
            # The rule's own answer stays in `data`; only the `publish` column is held back.
            try:
                cur.execute("SELECT rev_id FROM human_decision WHERE verdict = 'approve'")
                approved = {r["rev_id"] for r in cur.fetchall()}
            except Exception:
                approved = set()
            rows = [r if r[0] in approved else (r[0], r[1], False, *r[3:]) for r in rows]
        if rows:
            cur.executemany(sql, rows)
    commit(conn)
    cur.close()


def live_totals() -> dict:
    """Counted from the files on every run, so the figures can never drift from the cases."""
    decisions = read_jsonl(DECISIONS)
    return {"candidates": len(read_jsonl(CANDIDATES)), "analysed": len(read_jsonl(ANALYSIS)),
            **{d: sum(r.get("decision") == d for r in decisions) for d in ("flag", "human_review", "dismiss")},
            "published": published_live(decisions)}


def published_live(decisions: list[dict]) -> int:
    """Live flags really on the site: the rule said publish and a human approved."""
    wanted = [int(r["rev_id"]) for r in decisions if r.get("decision") == "flag" and r.get("publish")]
    if not wanted:
        return 0
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM decision WHERE publish = 1 AND rev_id IN (%s)" % ",".join(["%s"] * len(wanted)), wanted)
            return int(cur.fetchone()["n"])
    finally:
        conn.close()


# ---------- one run ----------

COUNTERS = ("wikipedia_edits_seen", "edits_on_our_articles", "stored", "backfilled", "hidden",
            "skipped_null", "skipped_revert", "skipped_minor", "skipped_bot", "not_candidate", "candidates")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since-hours", type=float, default=float(os.environ.get("WATCH_FIRST_HOURS", "6")),
                    help="first run only: how far back to read RecentChanges")
    ap.add_argument("--no-models", action="store_true", help="store and filter only (no Nemotron / Gemini)")
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute("SELECT GET_LOCK(%s, 0) AS got", (LOCK_NAME,))
    if cur.fetchone()["got"] != 1:
        log("another run is still working: nothing to do")
        return

    started = time.time()
    run = {c: 0 for c in COUNTERS} | {"candidate_rev_ids": [], "errors": [], "mock": USE_MOCK}
    state = load_state(cur, args.since_hours)
    window_start = state["ts"]
    log(f"{'MOCK ' if USE_MOCK else ''}run: reading RecentChanges since {iso(window_start)}")
    try:
        changes, complete = recent_changes(state["ts"], state["rcid"])
        run["wikipedia_edits_seen"] = len(changes)
        ours = our_pages(cur, {rc["pageid"] for rc in changes})
        known = {r["rev_id"] for r in read_jsonl(CANDIDATES)}
        for page_id in sorted(ours):
            try:
                sync_page(conn, page_id, window_start, known, run)
            except Exception as e:      # one bad article must not stop the others
                conn.rollback()
                run["errors"].append(f"page {page_id}: {type(e).__name__}: {str(e)[:200]}")
                log(f"  page {page_id} failed:\n{traceback.format_exc(limit=3)}")
        if changes:
            last = changes[-1]
            state["ts"], state["rcid"] = parse_ts(last["timestamp"]), last["rcid"]
        if not complete:
            log("  more changes are waiting: the next run continues from the cursor")
        log(f"  {len(changes)} article edits on fi.wikipedia, {len(ours)} of our articles touched, "
            f"{run['stored']} versions stored, {run['candidates']} candidates")
        if not args.no_models:
            run_models(run)
            import_live(conn)
    except Exception as e:
        conn.rollback()
        run["errors"].append(f"{type(e).__name__}: {str(e)[:300]}")
        log(f"run failed:\n{traceback.format_exc(limit=4)}")

    run["seconds"] = round(time.time() - started, 1)
    run["at"] = iso(utcnow())
    totals = state["data"].setdefault("totals", {})
    for c in COUNTERS:
        totals[c] = totals.get(c, 0) + run[c]
    state["data"]["runs"] = state["data"].get("runs", 0) + 1
    state["data"]["cases"] = live_totals()
    state["data"]["last_run"] = run
    save_state(cur, state, ok=not run["errors"])
    commit(conn)
    if USE_MOCK:
        conn.rollback()
        log("MOCK: database changes rolled back")
    append_jsonl(RUNS, run)
    cur.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
    conn.close()
    log("done " + json.dumps({k: v for k, v in run.items() if v not in (0, [], False)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
