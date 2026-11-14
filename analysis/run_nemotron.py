"""Ask Nemotron to investigate each candidate edit (step 3).

Reads data/exchange/candidates.jsonl and appends to data/exchange/analysis.jsonl the same
line plus a "nemotron" report (format: docs/TIMEPROOF-PLAN-SAMEDI.md, section 4.2).
Each answer is written as soon as it arrives; rev_ids already in analysis.jsonl are
skipped, so the script can be stopped and restarted at any time.

Order: changed captions first, then replaced images, sources, framing, added/removed
images; inside each group, article 1150 (the 1918 war) first.

Usage (from the repository root):
    python analysis/run_nemotron.py --limit 10
    python analysis/run_nemotron.py --rev-id 24234965 --rev-id 463331
With USE_MOCK=true in .env, no request is sent and realistic fake reports are used
(written to analysis-mock.jsonl so they never mix with real results).
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from env import load_env, nemotron_config, use_mock

CANDIDATES = "data/exchange/candidates.jsonl"
ANALYSIS = "data/exchange/analysis.jsonl"
FOCUS_PAGE = 1150               # Suomen sisällissota: the core of the demo
MAX_WORKERS = 4                 # shared server: never more than 4 calls at once
STOP_AFTER_FAILURES = 10        # with 4 parallel calls, a short burst of 500s already gives 3-4 failures

PROMPT_VERSION = "v4"           # history and measured reasons: analysis/PROMPT-LOG.md
INVESTIGATOR_PROMPT = """You investigate one edit to a Finnish Wikipedia article about the history of Finland.
Texts are in Finnish; reason over them and answer in English.
Decide whether this edit looks like an attempt to push a narrative (one-sided reframing,
misleading image or caption, removal of sources, coordinated editing) rather than ordinary
editing (new facts, style, sourcing, vandalism cleanup). Be conservative: most edits are ordinary.
Obvious vandalism (insults, slurs, nonsense words, jokes, blanking) is not narrative pushing:
nobody would believe it, and it is usually reverted within minutes. For vandalism, answer
"suspicious": false and put "vandalism" in "signals". Keep "suspicious": true for edits that could
plausibly change what a reader believes about history.
The edit is given as JSON: "added" and "removed" are the words that changed, with separate
passages joined by " … "; "image" describes an image change with the old and new captions;
"refs_removed" is the number of <ref> citations removed.
In the report, quote the exact Finnish words that matter, with an English translation, so a
human can check your claim against the edit.
If an image is attached, describe what it actually shows and say whether the caption matches it.
Answer with JSON only:
{"suspicious": true|false, "signals": ["..."], "report": "3-6 sentences a human can check",
 "image_findings": {"what_it_shows": "...", "caption_matches": true|false|null} | null}"""

# Fields sent to the model: the account hash and ids would only add noise.
PROMPT_FIELDS = ["title", "timestamp", "kind", "user_is_new", "comment", "added", "removed", "refs_removed"]
KIND_ORDER = {"recaptioned": 0, "replaced": 1, "coordination": 2, "sources": 3, "framing": 4,
              "added": 5, "removed": 6}


CONFIG: dict = {}               # set in main() from .env (Verda or NVIDIA backup)
_rate_lock = threading.Lock()
_next_call_at = 0.0


def wait_for_rate_limit() -> None:
    """Space calls out when the provider has a per-minute limit (NVIDIA backup)."""
    global _next_call_at
    per_minute = CONFIG.get("calls_per_minute")
    if not per_minute:
        return
    with _rate_lock:
        now = time.time()
        wait = _next_call_at - now
        _next_call_at = max(now, _next_call_at) + 60 / per_minute
    if wait > 0:
        time.sleep(wait)


def image_as_data_url(url: str) -> str:
    """Download the thumbnail ourselves, for providers that do not fetch image links."""
    r = httpx.get(url, headers={"User-Agent": os.environ.get("WIKI_USER_AGENT", "")},
                  follow_redirects=True, timeout=30)
    r.raise_for_status()
    kind = r.headers.get("content-type", "image/jpeg").split(";")[0]
    return f"data:{kind};base64,{base64.b64encode(r.content).decode()}"


def extract_json(text: str) -> dict:
    """The model may write reasoning (possibly with braces) before the JSON: find the object that parses."""
    end = text.rfind("}")
    start = text.find("{")
    while 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    raise ValueError(f"no JSON object in the answer: {text[:120]!r}")


def ask_nemotron(prompt: str, edit: str, image_url: str | None) -> dict:
    """The only function that calls Nemotron. Returns the parsed JSON answer."""
    if use_mock():
        time.sleep(0.05)
        return mock_report(image_url)
    # Sent inline by default: when the server fetched Wikimedia links itself, 47 of 104 image
    # calls failed with HTTP 500 on Saturday; the same edits passed once sent inline.
    if image_url and os.environ.get("NEMOTRON_IMAGE_AS_DATA", "true").lower() == "true":
        image_url = image_as_data_url(image_url)
    content = edit if not image_url else [
        {"type": "text", "text": edit},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    wait_for_rate_limit()
    r = httpx.post(
        CONFIG["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {CONFIG['key']}"},
        # The model reasons before answering: 2000 tokens left empty or cut-off answers on Saturday.
        json={"model": CONFIG["model"], "temperature": 0.6, "top_p": 0.95, "max_tokens": 6000,
              "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": content}]},
        # 1-3 s when the shared server is quiet, but we measured 20-220 s under load on Saturday.
        timeout=300,
    )
    r.raise_for_status()
    return extract_json(r.json()["choices"][0]["message"].get("content") or "")


def mock_report(image_url: str | None) -> dict:
    return {"suspicious": False, "signals": ["mock: ordinary wording change"],
            "report": "MOCK REPORT. The edit rewords one sentence without changing its meaning. "
                      "No sources are removed. This is a simulated answer for offline development.",
            "image_findings": {"what_it_shows": "mock: a black-and-white group photo", "caption_matches": True}
            if image_url else None}


def clean_report(raw: dict, has_image: bool) -> dict:
    """Keep only the expected keys with the expected types, whatever the model wrote."""
    findings = raw.get("image_findings")
    if has_image and isinstance(findings, dict):
        matches = findings.get("caption_matches")
        findings = {"what_it_shows": str(findings.get("what_it_shows", "")),
                    "caption_matches": matches if isinstance(matches, bool) else None}
    else:
        findings = None
    signals = raw.get("signals")
    return {
        "suspicious": raw.get("suspicious") is True,
        "signals": [str(s) for s in signals] if isinstance(signals, list) else [],
        "report": str(raw.get("report", "")),
        "image_findings": findings,
        "model": "mock" if use_mock() else CONFIG["model"],
        "prompt_version": PROMPT_VERSION,
    }


def investigate(row: dict) -> dict:
    edit = {k: row.get(k) for k in PROMPT_FIELDS}
    image = row.get("image")
    if image:
        edit["image"] = {k: image.get(k) for k in ("change", "file", "caption_old", "caption_new")}
    image_url = image.get("thumb_url") if image else None
    message = json.dumps(edit, ensure_ascii=False)
    last_error = None
    for attempt in range(3):
        try:
            started = time.time()
            raw = ask_nemotron(INVESTIGATOR_PROMPT, message, image_url)
            report = clean_report(raw, bool(image_url))
            report["seconds"] = round(time.time() - started, 1)
            return {**row, "nemotron": report}
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            time.sleep(10 * (attempt + 1))     # 500 errors came in bursts: give the server time
    raise RuntimeError(f"rev {row['rev_id']}: {type(last_error).__name__}: {str(last_error)[:200]}")


def priority(row: dict) -> tuple:
    change = (row.get("image") or {}).get("change")
    group = KIND_ORDER.get(change if row["kind"] == "image" else row["kind"], 9)
    return (group, row["page_id"] != FOCUS_PAGE, row["timestamp"])


def read_jsonl(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", default=CANDIDATES)
    parser.add_argument("--out", default=ANALYSIS)
    parser.add_argument("--limit", type=int, required=True, help="how many new candidates to send (no default on purpose)")
    parser.add_argument("--rev-id", type=int, action="append", help="only these edits")
    parser.add_argument("--page-id", type=int, action="append", help="only these articles")
    parser.add_argument("--kind", action="append", choices=["image", "sources", "framing", "coordination"],
                        help="only these kinds of candidates")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    load_env()
    if args.workers > MAX_WORKERS:
        sys.exit(f"At most {MAX_WORKERS} parallel calls: the server is shared between teams.")
    if use_mock():
        args.out = args.out.replace(".jsonl", "-mock.jsonl")
    else:
        CONFIG.update(nemotron_config())
        if not (CONFIG["key"] and CONFIG["base_url"] and CONFIG["model"]):
            sys.exit(f"Missing in .env for provider {CONFIG['provider']}: {CONFIG['key_name']}, URL or model")
        print(f"Provider: {CONFIG['provider']} · model {CONFIG['model']}")

    done = {r["rev_id"] for r in read_jsonl(args.out)}
    rows = [r for r in read_jsonl(args.candidates)
            if r["rev_id"] not in done
            and (not args.rev_id or r["rev_id"] in args.rev_id)
            and (not args.page_id or r["page_id"] in args.page_id)
            and (not args.kind or r["kind"] in args.kind)]
    rows.sort(key=priority)
    rows = rows[:args.limit]
    print(f"{len(done)} already in {args.out}; sending {len(rows)}" + (" (MOCK)" if use_mock() else ""))

    ok = failed = suspicious = failed_in_a_row = 0
    with open(args.out, "a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(investigate, r) for r in rows]
        for future in as_completed(futures):
            try:
                result = future.result()
            except RuntimeError as e:
                failed += 1
                failed_in_a_row += 1
                print("  failed:", e)      # not written: it will be retried on the next run
                if failed_in_a_row >= STOP_AFTER_FAILURES:
                    # The shared server is probably down: stop instead of hammering it.
                    print(f"{STOP_AFTER_FAILURES} failures in a row: stopping. Check the server, then run again.")
                    pool.shutdown(cancel_futures=True)
                    break
                continue
            failed_in_a_row = 0
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            ok += 1
            suspicious += result["nemotron"]["suspicious"]
            n = result["nemotron"]
            print(f"  {ok + failed}/{len(rows)} rev {result['rev_id']} {result['kind']}: "
                  f"{'SUSPICIOUS' if n['suspicious'] else 'ordinary'} ({n['seconds']} s)")
    print(f"Done: {ok} written ({suspicious} suspicious), {failed} failed -> {args.out}")


if __name__ == "__main__":
    main()
