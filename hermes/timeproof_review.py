"""Hermes job: the human review desk on the team's private Discord channel.

Installed as /opt/data/scripts/timeproof_review.py and run by the Hermes scheduler (no model call).
Each run does two things, in this order:

1. Reads the new messages of the private channel. A message "approve <rev_id> <reason>" or
   "reject <rev_id> <reason>" from an allowed team member is recorded through the TimeProof server
   (POST /api/internal/review/decision), then acknowledged in the channel.
2. If fewer than MAX_OPEN dossiers are waiting for an answer, asks the server for the next
   human_review case and posts its dossier. The case is marked as sent only once Discord accepted it.

Hermes orchestrates, it never judges: this script forwards facts and verdicts, it has no opinion,
publishes nothing and only ever writes in the one private channel. Synthetic cases never leave the server.
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx

ENV_FILE = Path("/opt/data/.env")
STATE_FILE = Path("/opt/data/timeproof_review_state.json")
DISCORD = "https://discord.com/api/v10"
MAX_OPEN = 3        # dossiers waiting for an answer before a new one is posted
VERDICT = re.compile(r"^\s*(approve|reject)\s+#?(\d{1,10})\s*[:\-–,]?\s*(.*)$", re.IGNORECASE | re.DOTALL)


def setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip()
    return value


URL = setting("TIMEPROOF_URL").rstrip("/")
TOKEN = setting("TIMEPROOF_INTERNAL_TOKEN")
BOT_TOKEN = setting("DISCORD_BOT_TOKEN")
CHANNEL = setting("DISCORD_REVIEW_CHANNEL_ID")
ALLOWED = {u.strip() for u in setting("DISCORD_ALLOWED_USERS").split(",") if u.strip()}
MOCK = setting("USE_MOCK").lower() == "true"


def discord(method: str, path: str, **kw):
    """The only function that talks to Discord. In mock mode nothing is sent."""
    if MOCK:
        print(f"[mock] discord {method} {path} {json.dumps(kw.get('json'), ensure_ascii=False)[:300]}")
        return [] if method == "GET" else {"id": "0"}
    r = httpx.request(method, DISCORD + path, timeout=30, headers={
        "Authorization": f"Bot {BOT_TOKEN}", "User-Agent": "DiscordBot (https://timeproof.srv2158940.hstgr.cloud, 1.0)"}, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def server(method: str, path: str, **kw) -> httpx.Response:
    """The only function that talks to the TimeProof server."""
    return httpx.request(method, URL + path, timeout=180, headers={"X-Internal-Token": TOKEN}, **kw)


def say(text: str, reply_to: str | None = None) -> None:
    body = {"content": text[:1990], "allowed_mentions": {"parse": []}, "flags": 4}     # 4 = no link previews
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    discord("POST", f"/channels/{CHANNEL}/messages", json=body)


# ---------- 1. verdicts written by the team ----------

def read_verdicts(state: dict) -> None:
    params = {"limit": 50}
    if state.get("last_message_id"):
        params["after"] = state["last_message_id"]
    messages = discord("GET", f"/channels/{CHANNEL}/messages", params=params) or []
    for m in sorted(messages, key=lambda x: int(x["id"])):
        state["last_message_id"] = m["id"]
        author = m.get("author") or {}
        if author.get("bot") or author.get("id") not in ALLOWED:
            continue
        found = VERDICT.match(m.get("content") or "")
        if not found:
            continue
        verdict, rev_id, reason = found.group(1).lower(), int(found.group(2)), found.group(3).strip()
        if not reason:
            say(f"Not recorded: add a short reason, for example `{verdict} {rev_id} the caption matches the photo`.", m["id"])
            continue
        who = author.get("global_name") or author.get("username") or author["id"]
        r = server("POST", "/api/internal/review/decision",
                   json={"rev_id": rev_id, "verdict": verdict, "reviewer": who[:100], "reason": reason[:1000]})
        if r.status_code == 200:
            previous = r.json().get("previous")
            changed = f" (was: {previous})" if previous not in (None, "pending") else ""
            say(f"Recorded: **{verdict}** for rev {rev_id}, by {plain(who, 60)}{changed}. " "Stored with its history; " + ("the case is now published on the site." if r.json().get("published") and verdict == "approve" else "nothing was published."), m["id"])
            print(f"verdict recorded: {verdict} {rev_id}")
        elif r.status_code == 404:
            say(f"Not recorded: no dossier was sent for rev {rev_id}. Check the number.", m["id"])
        else:
            say(f"Not recorded: the server answered {r.status_code}. Try again in a few minutes.", m["id"])
            print(f"verdict failed: {rev_id} -> HTTP {r.status_code}")


# ---------- 2. the next dossier ----------

MARKDOWN = re.compile(r"([\\`*_~|>\[\]()<@#:])")


def plain(text, limit: int = 300) -> str:
    """Untrusted text (Wikipedia, model output) on one line with Discord formatting switched off, so that
    an edit cannot fake a heading, a link, a mention or one of our own lines inside a dossier."""
    flat = " ".join(str(text or "").split())[:limit]
    return MARKDOWN.sub(r"\\\1", flat)


def quote(text, limit: int = 330) -> str:
    return "> " + plain(text, limit) if text else "> (nothing)"


def dossier_messages(c: dict) -> list[str]:
    """One case as two Discord messages (each under 2,000 characters): the facts, then the two opinions."""
    live = "LIVE, detected " + (c.get("detected_at") or "") if c.get("source") == "live" else "from the dataset"
    t, links, image = c.get("time_online") or {}, c.get("links") or {}, c.get("image_change")
    online = "not computed" if t.get("days") is None else f"{t['days']} days" + (
        ", still online" if t.get("still_online") else "") + (
        f", at most {t['readers_upper_bound']:,} readers" if t.get("readers_upper_bound") else "")
    facts = [
        f"**Human review needed: rev {c['rev_id']}** ({live})",
        f"Article: **{plain(c['article'], 150)}**, edited {c['edited_at']}, kind: {plain(c['kind'], 20)}, account code: {c.get('account_id') or 'n/a'}",
        f"Time online: {online}. Sources removed: {c.get('sources_removed', 0)}.",
    ]
    if image:
        facts.append(f"Image: {plain(image.get('change'), 20)}, file: {plain(image.get('file'), 120)}"
                     + (f", caption before: \"{plain(image['caption_old'], 200)}\"" if image.get("caption_old") else "")
                     + (f", caption after: \"{plain(image['caption_new'], 200)}\"" if image.get("caption_new") else ""))
    for label, fi, en in (("Added", c.get("added_fi"), c.get("added_en")), ("Removed", c.get("removed_fi"), c.get("removed_en"))):
        if fi:
            facts += [f"**{label} (Finnish, quoted from Wikipedia):**", quote(fi), f"**{label} (English, machine translation):**",
                      quote(en) if en else "> (translation unavailable)"]
    facts.append(f"Before: <{links.get('version_before')}>\nAfter: <{links.get('version_after')}>\nDiff: <{links.get('diff')}>")
    nem, gem = c.get("nemotron") or {}, c.get("gemini") or {}
    opinions = [
        f"**Rev {c['rev_id']}: what the two models said**",
        f"**Nemotron** (investigator): {'suspicious' if nem.get('suspicious') else 'not suspicious'}"
        + (f", signals: {plain(', '.join(map(str, nem['signals'])), 150)}" if nem.get("signals") else ""),
        quote(nem.get("report"), 600),
        f"**Gemini** (decider): {plain(gem.get('decision'), 20)}" + (f", confidence {gem['confidence']}" if gem.get("confidence") is not None else ""),
        quote(gem.get("explanation") or gem.get("headline_en"), 500),
        f"**Why it is here:** {c.get('why_they_disagree')}",
        f"**Your call:** `approve {c['rev_id']} <short reason>` (it is a real problem) or `reject {c['rev_id']} <short reason>` (false alarm). Approve {plain(c.get('on_approve') or 'is recorded', 80)}.",
    ]
    return ["\n".join(facts)[:1990], "\n".join(opinions)[:1990]]


def post_next() -> None:
    status = server("GET", "/api/live").json()
    if (status.get("human") or {}).get("pending", 0) >= MAX_OPEN:
        return
    case = server("GET", "/api/internal/review/next", params={"peek": "true"}).json().get("case")
    if not case:
        return
    if case.get("source") not in ("live", "dataset"):
        raise SystemExit("refusing to post a case that is neither live nor from the dataset")
    for text in dossier_messages(case):
        say(text)
    if MOCK:
        return
    # Discord accepted the dossier: only now is the case marked as sent (one dossier per case).
    marked = server("GET", "/api/internal/review/next", params={"translate": "false"}).json().get("case") or {}
    if marked.get("rev_id") != case["rev_id"]:
        print(f"warning: posted rev {case['rev_id']} but the server marked {marked.get('rev_id')}")
    print(f"dossier posted: rev {case['rev_id']}")


def main() -> None:
    missing = [n for n, v in (("TIMEPROOF_URL", URL), ("TIMEPROOF_INTERNAL_TOKEN", TOKEN), ("DISCORD_BOT_TOKEN", BOT_TOKEN),
                              ("DISCORD_REVIEW_CHANNEL_ID", CHANNEL), ("DISCORD_ALLOWED_USERS", ALLOWED)) if not v]
    if missing:
        sys.exit("missing settings: " + ", ".join(missing))
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    try:
        read_verdicts(state)
    finally:
        if not MOCK:
            STATE_FILE.write_text(json.dumps(state))
    post_next()


if __name__ == "__main__":
    main()
