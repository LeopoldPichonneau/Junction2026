"""Run prompt v1 (docs/TECH.md, section 7) on edits already answered with v2, for the prompt log.

v2 answers are read from data/exchange/analysis.jsonl; v1 answers are appended to
data/exchange/prompt-v1.jsonl (one line per edit, skipped when already there).
Run it when the main batch is finished: the Nemotron server is shared and slow.

Usage (from the repository root):
    python analysis/compare_prompts.py --rev-id 24234965 --rev-id 463331
    python analysis/compare_prompts.py --show
"""

import argparse
import json
import sys
import time

import httpx

import run_nemotron as rn
from env import load_env, nemotron_config, use_mock

V1_OUT = "data/exchange/prompt-v1.jsonl"

# Copied verbatim from docs/TECH.md section 7 (Friday's starting point).
V1_PROMPT = """You investigate one edit to a Finnish Wikipedia article about the history of Finland.
Texts are in Finnish; reason over them and answer in English.
Decide whether this edit looks like an attempt to push a narrative (one-sided reframing,
misleading image or caption, removal of sources, coordinated editing) rather than ordinary
editing (new facts, style, sourcing, vandalism cleanup). Be conservative: most edits are ordinary.
If an image is attached, describe what it actually shows and say whether the caption matches it.
Answer with JSON only:
{"suspicious": true|false, "signals": ["…"], "report": "3-6 sentences a human can check",
 "image_findings": {"what_it_shows": "…", "caption_matches": true|false|null} | null}"""

# v1 sent the whole candidates.jsonl line; drop only the v2 answer that analysis.jsonl adds.
V1_DROP = {"nemotron"}


def run_v1(row: dict) -> dict:
    """Same call path as v2 (rn.ask_nemotron), so only the prompt and the input differ."""
    message = json.dumps({k: v for k, v in row.items() if k not in V1_DROP}, ensure_ascii=False)
    image_url = (row.get("image") or {}).get("thumb_url")
    started = time.time()
    raw = rn.ask_nemotron(V1_PROMPT, message, image_url)
    report = rn.clean_report(raw, bool(image_url))
    report["seconds"] = round(time.time() - started, 1)
    return {"rev_id": row["rev_id"], "prompt": "v1", "nemotron": report}


def show() -> None:
    v2 = {r["rev_id"]: r for r in rn.read_jsonl(rn.ANALYSIS)}
    for r1 in rn.read_jsonl(V1_OUT):
        r2 = v2.get(r1["rev_id"])
        if not r2:
            continue
        a, b = r1["nemotron"], r2["nemotron"]
        print(f"rev {r1['rev_id']} ({r2['kind']})")
        print(f"  v1 suspicious={a['suspicious']} ({a['seconds']} s): {a['report']}")
        print(f"  v2 suspicious={b['suspicious']} ({b['seconds']} s): {b['report']}")
        if a["image_findings"] or b["image_findings"]:
            print(f"  v1 image: {a['image_findings']}")
            print(f"  v2 image: {b['image_findings']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rev-id", type=int, action="append", default=[])
    parser.add_argument("--show", action="store_true", help="print v1 and v2 answers side by side")
    args = parser.parse_args()
    load_env()
    if args.show:
        show()
        return
    if use_mock():
        sys.exit("USE_MOCK=true: the prompt log needs real answers.")
    rn.CONFIG.update(nemotron_config())
    v2 = {r["rev_id"]: r for r in rn.read_jsonl(rn.ANALYSIS)}
    done = {r["rev_id"] for r in rn.read_jsonl(V1_OUT)}
    todo = [v2[i] for i in args.rev_id if i in v2 and i not in done]
    missing = [i for i in args.rev_id if i not in v2]
    if missing:
        print("No v2 answer yet (run run_nemotron.py first):", missing)
    with open(V1_OUT, "a", encoding="utf-8") as out:
        for row in todo:     # one at a time: the server is shared
            try:
                result = run_v1(row)
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"  rev {row['rev_id']} failed: {type(e).__name__}: {str(e)[:200]}")
                continue
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  rev {row['rev_id']}: v1 suspicious={result['nemotron']['suspicious']} "
                  f"({result['nemotron']['seconds']} s)")


if __name__ == "__main__":
    main()
