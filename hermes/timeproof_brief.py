"""Hermes job: figures for the hourly situation brief written by the Hermes agent.

Installed as /opt/data/scripts/timeproof_brief.py. The Hermes scheduler runs it every hour and hands
its output to the agent's model, which writes a short brief for the team's private Discord channel.

The output is numbers and fixed labels only, taken from the public counters of GET /api/live. No
Wikipedia text, no model text, no reviewer text ever reaches the agent, so nothing in an edit can steer
it. The agent reports; it judges no case and decides nothing.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ENV_FILE = Path("/opt/data/.env")


def setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip()
    return value


def number(value) -> int:
    """Counters only: anything that is not a number becomes 0, so no text can slip through."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def main() -> None:
    url = setting("TIMEPROOF_URL").rstrip("/")
    if not url:
        sys.exit("missing setting: TIMEPROOF_URL")
    d = httpx.get(url + "/api/live", timeout=30).json()
    t, c, h, last = d.get("totals") or {}, d.get("cases") or {}, d.get("human") or {}, d.get("last_run") or {}
    try:
        checked = datetime.strptime(str(d.get("last_check")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        minutes_ago = int((datetime.now(timezone.utc) - checked).total_seconds() // 60)
    except ValueError:
        minutes_ago = -1
    lines = [
        ("time_now_utc", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
        ("minutes_since_last_check", minutes_ago),
        ("last_check_succeeded", "yes" if d.get("last_ok") is True else "no"),
        ("errors_in_last_check", number(last.get("errors"))),
        ("checks_since_start", number(d.get("runs"))),
        ("wikipedia_edits_read", number(t.get("wikipedia_edits_seen"))),
        ("edits_on_our_articles", number(t.get("edits_on_our_articles"))),
        ("versions_stored", number(t.get("stored"))),
        ("skipped_reverts", number(t.get("skipped_revert"))),
        ("skipped_minor_edits", number(t.get("skipped_minor"))),
        ("skipped_bots", number(t.get("skipped_bot"))),
        ("live_candidates", number(c.get("candidates"))),
        ("live_examined_by_nemotron", number(c.get("analysed"))),
        ("live_dismissed", number(c.get("dismiss"))),
        ("live_sent_to_human_review", number(c.get("human_review"))),
        ("live_flagged_by_both_models", number(c.get("flag"))),
        ("live_published_after_human_approval", number(c.get("published"))),
        ("dossiers_sent_to_discord", number(h.get("dossiers_sent"))),
        ("human_approve", number(h.get("approve"))),
        ("human_reject", number(h.get("reject"))),
        ("dossiers_waiting_for_an_answer", number(h.get("pending"))),
    ]
    print("\n".join(f"{k}: {v}" for k, v in lines))


if __name__ == "__main__":
    main()
