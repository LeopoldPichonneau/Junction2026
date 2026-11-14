"""Hermes Agent scheduled job: trigger one TimeProof watcher run and report what it found.

Installed in the Hermes container as ~/.hermes/scripts/timeproof_watch.py and scheduled with
    hermes cron create "every 10m" --name timeproof-watch --no-agent --script timeproof_watch.py
(--no-agent: no model call, so the watch never depends on a quota). Hermes only orchestrates:
it starts the run and relays the outcome. Detection and decisions stay in TimeProof's own
pipeline (two-opinion rule in decision/decide.py). Nothing is ever written to Wikipedia.

Output rule of Hermes: empty stdout = silent. A message is printed only when the run produced
a new candidate, a new decision or an error, so the team channel is not flooded.

Needs in the Hermes .env: TIMEPROOF_URL, TIMEPROOF_INTERNAL_TOKEN.
"""
import os
import sys
import time
from pathlib import Path

import httpx

WAIT_SECONDS = 240      # a run with Nemotron calls can be longer: the next tick reports it


def setting(name: str) -> str:
    """Environment first, then the Hermes .env file (scripts do not always inherit it)."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = Path(os.environ.get("HERMES_HOME", str(Path.home()))) / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def main() -> None:
    base, token = setting("TIMEPROOF_URL").rstrip("/"), setting("TIMEPROOF_INTERNAL_TOKEN")
    if not base or not token:
        print("TimeProof watcher: TIMEPROOF_URL or TIMEPROOF_INTERNAL_TOKEN is missing in the Hermes .env")
        return
    with httpx.Client(timeout=30) as http:
        before = http.get(f"{base}/api/live").json()
        r = http.post(f"{base}/api/internal/watch", headers={"X-Internal-Token": token})
        if r.status_code != 200:
            print(f"TimeProof watcher: could not start a run (HTTP {r.status_code})")
            return
        deadline = time.time() + WAIT_SECONDS
        after = before
        while time.time() < deadline:
            time.sleep(5)
            after = http.get(f"{base}/api/live").json()
            if not after.get("running") and after.get("runs", 0) > before.get("runs", 0):
                break
        else:
            return          # still working (model calls): silent, the next tick will report

    run, cases, old = after.get("last_run") or {}, after.get("cases") or {}, before.get("cases") or {}
    new = {k: cases.get(k, 0) - old.get(k, 0) for k in ("candidates", "flag", "human_review", "dismiss")}
    if not (run.get("errors") or any(v > 0 for v in new.values())):
        return              # nothing new on our articles: stay silent
    lines = [f"TimeProof live watch · {run.get('at', '')}",
             f"{run.get('wikipedia_edits_seen', 0)} new edits on fi.wikipedia, "
             f"{run.get('edits_on_our_articles', 0)} on our articles, {new['candidates']} new candidate(s)."]
    if new["flag"] or new["human_review"] or new["dismiss"]:
        lines.append(f"Decisions (two-model rule): {new['flag']} flag, {new['human_review']} human review, "
                     f"{new['dismiss']} dismissed.")
    if run.get("errors"):
        lines.append(f"{run['errors']} error(s) in this run: see data/logs/watch.log on the VPS.")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:      # a failed tick must say so once, not crash the scheduler
        print(f"TimeProof watcher: tick failed ({type(e).__name__}: {str(e)[:200]})")
        sys.exit(0)
