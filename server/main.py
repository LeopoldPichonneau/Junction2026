"""TimeProof API + static site (formats: docs/TECH.md, section 11).

No public response ever contains a Wikipedia account name (`user`), and synthetic test
cases are filtered out of every response.
"""
import difflib
import html
import json
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from db import connect
from wikitext import clean

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
WEB_DIR = Path(__file__).parent / "web"
# The team's hand-checked English translations of the demo cases (analysis/demo_cases.json).
DEMO_CASES = Path(os.environ.get("DEMO_CASES", "/analysis/demo_cases.json"))

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


_file_cache: dict[Path, tuple[float, object]] = {}


def read_cached(path: Path, parse):
    """Parse a file once, and again only when it changes on disk (files in data/exchange/ are replaced)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _file_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    value = parse(path.read_text(encoding="utf-8"))
    _file_cache[path] = (mtime, value)
    return value


def exchange_json(name: str) -> dict:
    return read_cached(DATA_DIR / "exchange" / name, json.loads) or {}


def cloudinary_cards() -> dict:
    """{rev_id: line of data/exchange/cloudinary.jsonl} (written by analysis/cloudinary_cards.py)."""
    def parse(text):
        lines = (json.loads(l) for l in text.splitlines() if l.strip())
        return {int(l["rev_id"]): l for l in lines if l.get("rev_id")}
    return read_cached(DATA_DIR / "exchange" / "cloudinary.jsonl", parse) or {}


def translations() -> dict:
    """{rev_id: before/after in Finnish and English}, only for the hand-translated demo cases."""
    def parse(text):
        keys = ("before_fi", "before_en", "after_fi", "after_en")
        return {int(c["rev_id"]): {k: c.get(k) for k in keys} for c in json.loads(text).get("cases", [])}
    return read_cached(DEMO_CASES, parse) or {}


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
        cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(d.readers_est), 0) AS readers, "
                    f"COUNT(d.readers_est) AS known "
                    f"FROM decision d JOIN candidate c USING (rev_id) WHERE {PUBLIC}")
        pub = cur.fetchone()
    # decision/readers.py: the same page views, each moment of an article counted once.
    # Only used when its recomputed sum matched the published one ("checked").
    uniq = exchange_json("readers.json")
    unique = uniq.get("unique") if uniq.get("checked") and uniq.get("sum_of_cases") == int(pub["readers"]) else None
    return {"articles": int(s["articles"]), "versions": int(s["versions"]),
            "candidates": int(candidates), "analysed": int(analysed),
            "published": int(pub["n"]), "readers_exposed_est": int(pub["readers"]),
            "readers_unique_est": unique,
            "readers_unique_note": uniq.get("method") if unique is not None else None,
            # A sum over cases: two cases live on the same article on the same day count its
            # readers twice. Daily page views per article are not exported, so we say so.
            "readers_is_upper_bound": True,
            "readers_note": "upper bound, may count the same reader several times",
            "readers_known_cases": int(pub["known"]),
            "readers_unknown_cases": int(pub["n"]) - int(pub["known"]),
            "readers_unknown_reason": "Wikipedia page views exist only from July 2015"}


def shown_thumb(image: dict) -> str | None:
    """Wikimedia images may only be shown with their author and licence: no credit, no picture."""
    if image.get("author") and image.get("license"):
        return image.get("thumb_url")
    return None


def case_summary(row: dict) -> dict:
    c, d = j(row["c_data"]), j(row["d_data"])
    image = c.get("image") or {}
    exp = d.get("exposure") or {}
    card = cloudinary_cards().get(row["rev_id"]) or {}
    return {"rev_id": row["rev_id"], "page_id": row["page_id"], "title": row["title"],
            "date": day(row["edited_at"]),
            "signal_type": d.get("signal_type") or row["kind"],
            # Both opinions, until the team picks one for signal_type (they differ on 41 of 97 cases).
            "detected_signal": row["kind"], "decider_signal": d.get("signal_type"),
            "headline_en": d.get("headline_en"), "summary_en": d.get("summary_en"),
            "confidence": row["confidence"], "days_live": row["days_live"],
            "readers_est": row["readers_est"],
            "still_online": None if row["still_online"] is None else bool(row["still_online"]),
            "verified": bool(exp.get("verified")),
            "image_thumb": shown_thumb(image),
            # The list shows a thumbnail only with its credit: send it along, never one without the other.
            "image_author": image.get("author") if shown_thumb(image) else None,
            "image_license": image.get("license") if shown_thumb(image) else None,
            # Same rule for the Cloudinary copy of that image.
            "image_auto_url": card.get("image_auto_url") if shown_thumb(image) else None,
            "evidence_card_url": card.get("evidence_card_url")}


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


def published_case(cur, rev_id: int) -> dict:
    cur.execute(CASE_SELECT + f"WHERE {PUBLIC} AND c.rev_id = %s", (rev_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "case not found or not published")
    return row


@app.get("/api/cases/{rev_id}")
def case(rev_id: int):
    with db() as cur:
        row = published_case(cur, rev_id)
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
                     "still_online": None if row["still_online"] is None else bool(row["still_online"]),
                     # Times are to the minute; "verified" = checked by hand (decision/verified_exposure.json).
                     "verified": bool(exp.get("verified")),
                     "ended_by": exp.get("ended_by"),        # revert / content removed / verified by hand
                     "ended_by_rev_id": exp.get("ended_by_rev_id"),
                     "ended_by_link": (f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={exp['ended_by_rev_id']}"
                                       if exp.get("ended_by_rev_id") else None),
                     "tracked_by": exp.get("tracked_by")},
        "account": None if not acc else {"kind": acc["kind"], "reasons": j(acc["data"]).get("reasons", [])},
        # Only the hand-translated demo cases have one; never machine-made here.
        "translation": translations().get(rev_id),
        "links": links(rev_id),
    })
    return out


# ---- Real diff of a case: its version against the one before, from the versioned table ----

_TOKENS = re.compile(r"\s+|[^\s]+")


def _segments(ops: list[tuple[str, str]]) -> list[dict]:
    """Merge neighbours with the same op so the site gets few, long segments."""
    out: list[dict] = []
    for op, text in ops:
        if not text:
            continue
        if out and out[-1]["op"] == op:
            out[-1]["text"] += text
        else:
            out.append({"op": op, "text": text})
    return out


def word_diff(old: str, new: str) -> list[dict]:
    a, b = _TOKENS.findall(old), _TOKENS.findall(new)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(("equal", "".join(a[i1:i2])))
        else:
            ops.append(("delete", "".join(a[i1:i2])))
            ops.append(("insert", "".join(b[j1:j2])))
    return _segments(ops)


def paragraph_diff(old: str, new: str) -> list[list[dict]]:
    """Paragraphs first (fast on long articles), then words inside the changed paragraphs only."""
    a = [p for p in old.split("\n") if p.strip()]
    b = [p for p in new.split("\n") if p.strip()]
    changed = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        changed.append(word_diff("\n".join(a[i1:i2]), "\n".join(b[j1:j2])))
    return changed


@app.get("/api/cases/{rev_id}/diff")
def case_diff(rev_id: int):
    with db() as cur:
        row = published_case(cur, rev_id)               # 404 for unpublished and test cases
        # Never select user or comment: edit summaries can name accounts.
        cur.execute("SELECT rev_id, parent_id, row_start, text FROM article FOR SYSTEM_TIME ALL "
                    "WHERE page_id = %s AND rev_id = %s", (row["page_id"], rev_id))
        new = cur.fetchone()
        if not new:
            raise HTTPException(404, "this version is not in the database")
        old = None
        if new["parent_id"]:
            cur.execute("SELECT rev_id, row_start, text FROM article FOR SYSTEM_TIME ALL "
                        "WHERE page_id = %s AND rev_id = %s", (row["page_id"], new["parent_id"]))
            old = cur.fetchone()
        if not old:                                     # no parent id, or parent missing: take the version before
            cur.execute("SELECT rev_id, row_start, text FROM article FOR SYSTEM_TIME ALL "
                        "WHERE page_id = %s AND row_start < %s ORDER BY row_start DESC LIMIT 1",
                        (row["page_id"], new["row_start"]))
            old = cur.fetchone()

    paragraphs = paragraph_diff(clean(old["text"]) if old else "", clean(new["text"]))
    return {"rev_id": rev_id, "parent_rev_id": old["rev_id"] if old else None,
            "saved_at": new["row_start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "parent_saved_at": old["row_start"].strftime("%Y-%m-%dT%H:%M:%SZ") if old else None,
            # False when the change is only in references, images or templates, which the
            # readable text leaves out: the site should then keep showing added / removed.
            "text_changed": bool(paragraphs),
            "paragraphs": paragraphs,
            "translation": translations().get(rev_id),
            "links": links(rev_id)}


@app.get("/api/quality")
def quality():
    return exchange_json("quality.json")


@app.get("/api/terms")
def terms():
    """How the 1918 war is named month by month (analysis/term_timeline.py); {} until it is generated."""
    return exchange_json("term-timeline.json")


@app.get("/api/articles")
def articles(q: str | None = Query(None, max_length=100, description="part of the title"),
             limit: int | None = Query(None, ge=1, le=100)):
    """Without parameters: every article (the current site builds its list from it).
    With q and/or limit: the most edited matches only, 20 by default."""
    sql, params = "SELECT page_id, title, versions, first_edit, last_edit FROM article_stats", []
    if q and q.strip():
        like = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += " WHERE title LIKE %s"
        params.append(f"%{like}%")
    sql += " ORDER BY versions DESC"
    if q or limit:
        sql += " LIMIT %s"
        params.append(limit or 20)
    with db() as cur:
        cur.execute(sql, params)
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


@app.get("/case/{rev_id}", response_class=HTMLResponse)
def case_page(rev_id: int, request: Request):
    """case.html with its preview (og:) tags already in the HTML, for links shared in chats
    and social networks, whose previews never run JavaScript."""
    page = WEB_DIR / "case.html"
    if not page.exists():
        raise HTTPException(404, "site not found")
    with db() as cur:
        s = case_summary(published_case(cur, rev_id))   # 404 for unpublished and test cases
    title = f"{s['headline_en'] or s['title']} · TimeProof"
    summary = s["summary_en"] or "A change to Finnish Wikipedia that TimeProof can prove."
    if len(summary) > 200:
        summary = summary[:197].rsplit(" ", 1)[0] + "…"
    image = s["evidence_card_url"] or s["image_auto_url"] or s["image_thumb"]
    e = lambda v: html.escape(v, quote=True)
    # Behind Traefik the request looks like plain http: prefer the public host when it is set.
    host = os.environ.get("PUBLIC_HOST")
    site = f"https://{host}" if host else str(request.base_url).rstrip("/")
    tags = ['<base href="/">',
            f'<meta property="og:type" content="article">',
            f'<meta property="og:site_name" content="TimeProof">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(summary)}">',
            f'<meta property="og:url" content="{e(site)}/case/{rev_id}">',
            f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">']
    if image:
        tags.append(f'<meta property="og:image" content="{e(image)}">')
    # The site reads ?rev_id= (web/app.js, pageCase): give it that address before app.js runs.
    tags.append(f'<script>history.replaceState(null,"","/case.html?rev_id={rev_id}")</script>')
    text = page.read_text(encoding="utf-8")
    text = text.replace("<title>Case · TimeProof</title>", f"<title>{e(title)}</title>", 1)
    text = text.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  ' + "\n  ".join(tags), 1)
    return text


# API routes are declared first, so they win over the static site.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
