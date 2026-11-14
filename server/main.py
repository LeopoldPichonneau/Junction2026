"""TimeProof API + static site (formats: docs/TECH.md, section 11).

No public response ever contains a Wikipedia account name (`user`), and synthetic test
cases are filtered out of every response.
"""
import json
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from db import connect
from wikitext import clean

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="TimeProof API")

# Only cases both models agreed on, that the decider chose to publish, and never the test campaign.
PUBLIC = "d.decision = 'flag' AND d.publish = 1 AND c.synthetic = 0"


@contextmanager
def db():
    conn = connect()
    try:
        yield conn.cursor()
    finally:
        conn.close()


def j(value) -> dict:
    if value is None:
        return {}
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def links(rev_id: int) -> dict:
    return {"version": f"https://fi.wikipedia.org/?oldid={rev_id}",
            "diff": f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={rev_id}"}


@app.get("/api/health")
def health():
    with db() as cur:
        cur.execute("SELECT 1 AS ok")
        return {"ok": cur.fetchone()["ok"] == 1}


@app.get("/api/stats")
def stats():
    with db() as cur:
        cur.execute("SELECT COUNT(*) AS articles, COALESCE(SUM(versions), 0) AS versions FROM article_stats")
        s = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM candidate WHERE synthetic = 0")
        candidates = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM analysis a JOIN candidate c USING (rev_id) WHERE c.synthetic = 0")
        analysed = cur.fetchone()["n"]
        cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(d.readers_est), 0) AS readers "
                    f"FROM decision d JOIN candidate c USING (rev_id) WHERE {PUBLIC}")
        pub = cur.fetchone()
    return {"articles": int(s["articles"]), "versions": int(s["versions"]),
            "candidates": int(candidates), "analysed": int(analysed),
            "published": int(pub["n"]), "readers_exposed_est": int(pub["readers"])}


def shown_thumb(image: dict) -> str | None:
    """Wikimedia images may only be shown with their author and licence: no credit, no picture."""
    if image.get("author") and image.get("license"):
        return image.get("thumb_url")
    return None


def case_summary(row: dict) -> dict:
    c, d = j(row["c_data"]), j(row["d_data"])
    image = c.get("image") or {}
    return {"rev_id": row["rev_id"], "page_id": row["page_id"], "title": row["title"],
            "date": day(row["edited_at"]),
            "signal_type": d.get("signal_type") or row["kind"],
            "headline_en": d.get("headline_en"), "summary_en": d.get("summary_en"),
            "confidence": row["confidence"], "days_live": row["days_live"],
            "readers_est": row["readers_est"],
            "still_online": None if row["still_online"] is None else bool(row["still_online"]),
            "image_thumb": shown_thumb(image),
            # The list shows a thumbnail only with its credit: send it along, never one without the other.
            "image_author": image.get("author") if shown_thumb(image) else None,
            "image_license": image.get("license") if shown_thumb(image) else None}


CASE_SELECT = ("SELECT c.rev_id, c.page_id, c.title, c.kind, c.edited_at, c.account_hash, "
               "c.data AS c_data, d.decision, d.confidence, d.days_live, d.readers_est, "
               "d.still_online, d.data AS d_data FROM decision d JOIN candidate c USING (rev_id) ")


@app.get("/api/cases")
def cases(since: str | None = Query(None, pattern=r"^\d+d$", description="e.g. 7d")):
    sql, params = CASE_SELECT + f"WHERE {PUBLIC}", []
    if since:
        sql += " AND c.edited_at >= %s"
        params.append(datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=int(since[:-1])))
    # Most readers first; unknown audience (before July 2015) after known ones.
    sql += " ORDER BY d.readers_est IS NULL, d.readers_est DESC, d.confidence DESC"
    with db() as cur:
        cur.execute(sql, params)
        return [case_summary(r) for r in cur.fetchall()]


@app.get("/api/cases/{rev_id}")
def case(rev_id: int):
    with db() as cur:
        cur.execute(CASE_SELECT + f"WHERE {PUBLIC} AND c.rev_id = %s", (rev_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "case not found or not published")
        cur.execute("SELECT model, data FROM analysis WHERE rev_id = %s", (rev_id,))
        a = cur.fetchone()
        acc = None
        if row["account_hash"]:
            cur.execute("SELECT kind, data FROM account_profile WHERE account_hash = %s", (row["account_hash"],))
            acc = cur.fetchone()

    c, d = j(row["c_data"]), j(row["d_data"])
    nem = j(a["data"]).get("nemotron", {}) if a else {}
    image = c.get("image")
    exp = d.get("exposure") or {}
    out = case_summary(row)
    out.pop("image_thumb"); out.pop("image_author"); out.pop("image_license")
    out.pop("days_live"); out.pop("readers_est"); out.pop("still_online")
    out.update({
        "added": c.get("added"), "removed": c.get("removed"),
        "image": None if not image else {
            "file": image.get("file"), "thumb_url": shown_thumb(image),
            "caption_old": image.get("caption_old"), "caption_new": image.get("caption_new"),
            "author": image.get("author"), "license": image.get("license")},
        "investigator": None if not a else {
            "model": a["model"], "report": nem.get("report"), "signals": nem.get("signals", []),
            "image_findings": nem.get("image_findings")},
        # decision/decide.py writes the model under "decider_model".
        "decider": {"model": d.get("decider_model") or d.get("model") or os.environ.get("GEMINI_MODEL") or "gemini",
                    "decision": row["decision"], "explanation": d.get("explanation")},
        "exposure": {"live_from": exp.get("live_from") or day(row["edited_at"]),
                     "live_until": exp.get("live_until"),
                     "days_live": row["days_live"], "readers_est": row["readers_est"],
                     "still_online": None if row["still_online"] is None else bool(row["still_online"])},
        "account": None if not acc else {"kind": acc["kind"], "reasons": j(acc["data"]).get("reasons", [])},
        "links": links(rev_id),
    })
    return out


@app.get("/api/quality")
def quality():
    path = DATA_DIR / "exchange" / "quality.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/articles")
def articles():
    with db() as cur:
        cur.execute("SELECT page_id, title, versions, first_edit, last_edit FROM article_stats "
                    "ORDER BY versions DESC")
        return [{**r, "first_edit": day(r["first_edit"]), "last_edit": day(r["last_edit"])}
                for r in cur.fetchall()]


def parse_as_of(value: str) -> datetime:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value += "T00:00:00"
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "as_of must look like 2015-06-01 or 2015-06-01T12:00:00Z")
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


@app.get("/api/articles/{page_id}")
def article(page_id: int, as_of: str | None = None):
    with db() as cur:
        if as_of:
            ts = parse_as_of(as_of)
            # MariaDB needs a full date and time here, never a bare date.
            cur.execute("SELECT title, rev_id, row_start, text FROM article "
                        "FOR SYSTEM_TIME AS OF TIMESTAMP %s WHERE page_id = %s",
                        (ts.strftime("%Y-%m-%d %H:%M:%S.%f"), page_id))
        else:
            cur.execute("SELECT title, rev_id, row_start, text FROM article WHERE page_id = %s", (page_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "article not found at that date")
    return {"page_id": page_id, "title": row["title"], "rev_id": row["rev_id"],
            "as_of": as_of or None,
            "saved_at": row["row_start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "text": clean(row["text"])}


@app.get("/api/articles/{page_id}/timeline")
def article_timeline(page_id: int):
    with db() as cur:
        cur.execute("SELECT 1 FROM article_stats WHERE page_id = %s", (page_id,))
        if not cur.fetchone():
            raise HTTPException(404, "article not found")
        cur.execute("SELECT month, edits, reverts FROM article_timeline WHERE page_id = %s ORDER BY month",
                    (page_id,))
        return cur.fetchall()


# API routes are declared first, so they win over the static site.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
