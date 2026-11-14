"""Routes of the live watcher (server/watch.py).

POST /api/internal/watch   starts one watcher run. Called by the Hermes Agent scheduler on the
                           same VPS; needs the X-Internal-Token header (INTERNAL_TOKEN in .env).
GET  /api/live             public: is the watcher running, when did it last check, how many
                           edits it saw. Counts only: an unpublished case is never listed.

Human review desk (same token, used by Hermes to brief the team's private Discord channel):
GET  /api/internal/review/next       the next human_review case as a dossier of facts, and marks
                                     it "pending". Live cases first, then the most exposed. Never
                                     a synthetic case, one dossier per case, at most N per hour.
POST /api/internal/review/decision   records approve / reject, who and why, in the versioned
                                     table human_decision. It never changes `decision.publish`:
                                     publication stays with the rule in decision/decide.py.
"""
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from db import connect


def public_account_id(account_hash: str) -> str:
    """Same keyed code as main.py's Accounts page (ACCOUNT_ID_KEY), so a reviewer can find the account there."""
    import hmac
    key = os.environ.get("ACCOUNT_ID_KEY", "").encode()
    return hmac.new(key, account_hash.encode(), "sha256").hexdigest()[:12] if key else "unavailable"

router = APIRouter()
LOG_FILE = Path(os.environ.get("DATA_DIR", "/data")) / "logs" / "watch.log"
INTERVAL_MIN = int(os.environ.get("WATCH_INTERVAL_MIN", "10"))
LOCK_NAME = "timeproof_watch"
REVIEWS_PER_HOUR = int(os.environ.get("REVIEWS_PER_HOUR", "10"))

# Versioned: every change of a human verdict (pending -> approve / reject, or a later change of
# mind) keeps its history row, so our own verdicts can be audited with FOR SYSTEM_TIME ALL.
HUMAN_DECISION_SCHEMA = """
CREATE TABLE IF NOT EXISTS human_decision (
  rev_id INT UNSIGNED PRIMARY KEY,
  verdict ENUM('pending','approve','reject') NOT NULL DEFAULT 'pending',
  reviewer VARCHAR(100), reason TEXT,
  posted_at DATETIME NOT NULL, decided_at DATETIME,
  data JSON NOT NULL
) CHARACTER SET utf8mb4 WITH SYSTEM VERSIONING
"""


def check_token(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected:
        raise HTTPException(503, "INTERNAL_TOKEN is not set on the server")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "bad token")


def watcher_running(cur) -> bool:
    cur.execute("SELECT IS_USED_LOCK(%s) AS holder", (LOCK_NAME,))
    return cur.fetchone()["holder"] is not None


@router.post("/api/internal/watch")
def start_watch(x_internal_token: str | None = Header(None)):
    check_token(x_internal_token)
    conn = connect()
    try:
        with conn.cursor() as cur:
            if watcher_running(cur):
                return {"started": False, "reason": "a run is still working"}
    finally:
        conn.close()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as log:
        # Detached: a run can last minutes (Nemotron), the caller polls GET /api/live instead.
        subprocess.Popen([sys.executable, str(Path(__file__).with_name("watch.py"))],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return {"started": True}


@router.get("/api/live")
def live_status():
    conn = connect()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT last_check, last_ok, data FROM watch_state WHERE id = 1")
                row = cur.fetchone()
            except Exception:           # table not created yet: the watcher never ran
                row = None
            if not row:
                return {"enabled": False}
            running = watcher_running(cur)
    finally:
        conn.close()
    data = json.loads(row["data"]) if isinstance(row["data"], (str, bytes)) else (row["data"] or {})
    last = data.get("last_run") or {}
    human = human_counts()
    return {
        "enabled": True, "running": running,
        "last_check": row["last_check"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_ok": bool(row["last_ok"]),
        "interval_minutes": INTERVAL_MIN,
        "watching_since": data.get("started_at"),
        "runs": data.get("runs", 0),
        "totals": data.get("totals") or {},
        "cases": data.get("cases") or {},
        **({"human": human} if human else {}),
        # Counts only, so that an edit still under review is not pointed at in public.
        "last_run": {k: last.get(k) for k in ("at", "seconds", "wikipedia_edits_seen", "edits_on_our_articles",
                                               "stored", "candidates")}
        | {"errors": len(last.get("errors") or []), "models_waiting": bool(last.get("models_waiting_for"))},
    }


# ---------- human review desk ----------

def jload(value) -> dict:
    if value is None:
        return {}
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def human_counts() -> dict | None:
    """Dossiers sent and human verdicts, or None before the review desk has ever been used."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT verdict, COUNT(*) AS n FROM human_decision GROUP BY verdict")
            except Exception:
                return None
            by = {r["verdict"]: r["n"] for r in cur.fetchall()}
    finally:
        conn.close()
    return {"dossiers_sent": sum(by.values()), "approve": by.get("approve", 0),
            "reject": by.get("reject", 0), "pending": by.get("pending", 0)}


def why_disagree(nemotron_suspicious, gemini_decision) -> str:
    if nemotron_suspicious is True and gemini_decision == "dismiss":
        return "Nemotron (investigator) found the edit suspicious; Gemini (decider) judged it ordinary editing."
    if nemotron_suspicious is True and gemini_decision == "human_review":
        return "Nemotron (investigator) found the edit suspicious; Gemini (decider) could not decide and asked for a human."
    if nemotron_suspicious is False and gemini_decision == "flag":
        return "Nemotron (investigator) saw nothing suspicious; Gemini (decider) wanted to flag it."
    if nemotron_suspicious is False:
        return "Nemotron (investigator) saw nothing suspicious; Gemini (decider) was unsure and asked for a human."
    return "One of the two opinions is missing or unusable, so the rule sends the case to a human."


@router.get("/api/internal/review/next")
def review_next(peek: bool = False, x_internal_token: str | None = Header(None)):
    check_token(x_internal_token)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(HUMAN_DECISION_SCHEMA)
            cur.execute("SELECT COUNT(*) AS n FROM human_decision WHERE posted_at > UTC_TIMESTAMP() - INTERVAL 1 HOUR")
            sent = cur.fetchone()["n"]
            if sent >= REVIEWS_PER_HOUR and not peek:
                return {"case": None, "reason": f"rate limit: {sent} dossiers in the last hour (max {REVIEWS_PER_HOUR})"}
            # Live cases first, then the most exposed. Synthetic test cases never leave the server.
            cur.execute(
                "SELECT c.rev_id, c.page_id, c.title, c.kind, c.edited_at, c.account_hash, c.data AS c_data, "
                "d.days_live, d.readers_est, d.still_online, d.data AS d_data, a.data AS a_data "
                "FROM decision d JOIN candidate c USING (rev_id) LEFT JOIN analysis a USING (rev_id) "
                "LEFT JOIN human_decision h USING (rev_id) "
                "WHERE d.decision = 'human_review' AND c.synthetic = 0 AND h.rev_id IS NULL "
                "ORDER BY JSON_VALUE(c.data, '$.source') <=> 'live' DESC, d.readers_est IS NULL, "
                "d.readers_est DESC, d.days_live DESC, c.edited_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return {"case": None, "reason": "no case is waiting for human review"}
            c, d, a = jload(row["c_data"]), jload(row["d_data"]), jload(row["a_data"])
            if c.get("synthetic") or d.get("synthetic") or c.get("mock"):
                raise HTTPException(500, "refusing to send a synthetic or mock case")
            cur.execute("SELECT parent_id FROM article FOR SYSTEM_TIME ALL WHERE rev_id = %s LIMIT 1", (row["rev_id"],))
            parent = (cur.fetchone() or {}).get("parent_id")
            nem, image = a.get("nemotron") or {}, c.get("image") or {}
            rev = row["rev_id"]
            dossier = {
                "rev_id": rev, "article": row["title"], "edited_at": row["edited_at"].strftime("%Y-%m-%d %H:%M UTC"),
                "source": c.get("source") or "dataset", "detected_at": c.get("detected_at"),
                "kind": row["kind"],
                # The keyed code of the Accounts page, never the raw hash (sha256 of the name, reversible by guessing).
                "account_id": public_account_id(row["account_hash"]) if row["account_hash"] else None,
                "added_fi": c.get("added"), "removed_fi": c.get("removed"),
                "sources_removed": c.get("refs_removed") or 0,
                "image_change": None if not image else {k: image.get(k) for k in ("change", "file", "caption_old", "caption_new")},
                "nemotron": {"suspicious": nem.get("suspicious"), "signals": nem.get("signals"), "report": nem.get("report"),
                             "image_findings": nem.get("image_findings")},
                "gemini": {"decision": d.get("gemini_decision"), "confidence": d.get("confidence"),
                           "headline_en": d.get("headline_en"), "explanation": d.get("explanation")},
                "why_they_disagree": why_disagree(d.get("nemotron_suspicious"), d.get("gemini_decision")),
                "time_online": {"days": row["days_live"], "still_online": None if row["still_online"] is None else bool(row["still_online"]),
                                "readers_upper_bound": row["readers_est"]},
                "links": {"version_after": f"https://fi.wikipedia.org/?oldid={rev}",
                          "version_before": f"https://fi.wikipedia.org/?oldid={parent}" if parent else None,
                          "diff": f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={rev}"},
                "how_to_answer": f"approve {rev} <short reason>   or   reject {rev} <short reason>",
            }
            if not peek:
                cur.execute("INSERT INTO human_decision (rev_id, verdict, posted_at, data) VALUES (%s, 'pending', UTC_TIMESTAMP(), %s)",
                            (rev, json.dumps({"why_they_disagree": dossier["why_they_disagree"]})))
                conn.commit()
            return {"case": dossier}
    finally:
        conn.close()


class HumanVerdict(BaseModel):
    rev_id: int
    verdict: str = Field(pattern="^(approve|reject)$")
    reviewer: str = Field(min_length=1, max_length=100)     # Discord name of the team member
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/api/internal/review/decision")
def review_decision(v: HumanVerdict, x_internal_token: str | None = Header(None)):
    check_token(x_internal_token)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(HUMAN_DECISION_SCHEMA)
            cur.execute("SELECT verdict FROM human_decision WHERE rev_id = %s", (v.rev_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "no dossier was sent for this rev_id")
            cur.execute("UPDATE human_decision SET verdict = %s, reviewer = %s, reason = %s, decided_at = UTC_TIMESTAMP() "
                        "WHERE rev_id = %s", (v.verdict, v.reviewer.strip(), v.reason.strip(), v.rev_id))
            conn.commit()
            # Publication is not touched here: it stays with the two-opinion rule of decision/decide.py.
            return {"recorded": True, "rev_id": v.rev_id, "verdict": v.verdict, "previous": row["verdict"],
                    "published": False}
    finally:
        conn.close()
