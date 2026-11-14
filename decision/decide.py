"""Gemini makes the final call on each case examined by Nemotron.

Reads  data/exchange/analysis.jsonl   (format 4.2, written by analysis/)
Writes data/exchange/decisions.jsonl  (format 4.3; exposure is added later by exposure.py)

    python decision/decide.py                                   # real run
    python decision/decide.py --input decision/sample/analysis.sample.jsonl   # try it -> decisions.test.jsonl

With USE_MOCK=true nothing is sent to Google and the output file name gets ".mock".
Safe to stop and restart: rev_ids already in the output file are skipped.
"""
import argparse
import hashlib
import json
import time

import config
from dataio import append_jsonl, done_rev_ids, read_jsonl

PROMPT_VERSION = "v2"  # bump when DECIDER_PROMPT changes, and log the change in PROMPT-LOG.md

# v2: v1 summaries accused editors ("falsely", "fabricates", "a common tactic"), which our public
# site must never do. v2 keeps the same decision rules but forces factual, attributed wording.
DECIDER_PROMPT = """You make the final call on one edit to a Finnish Wikipedia article about the history of Finland,
given the evidence and an investigator's report. The investigator can be wrong: check its claims
against the evidence (added/removed text, captions). Texts are Finnish; write in English for a general reader.
"flag" = likely narrative manipulation, "dismiss" = ordinary editing, "human_review" = unclear.
False positives are costly: when in doubt, choose human_review.

headline_en, summary_en and explanation are published as-is, so write them as a careful fact-checker:
- Describe what changed: quote the old and new wording (Finnish, with an English translation) and say
  why the change matters for how readers understand the event.
- Do not judge intent. Never write that someone lied, falsified, fabricated, deceived or used a tactic.
- Use cautious wording for anything the evidence alone does not show ("appears to", "may").
- Attribute what only the investigator saw ("according to the image analysis, the photo shows...").
- Never name or describe any account or editor.
- headline_en: neutral and factual, max 90 characters, without words such as "false", "fake",
  "propaganda", "manipulation" or "distort".
- "publish": true only if a reader could check the case from the linked Wikipedia versions.
Answer with JSON only:
{"decision": "flag"|"dismiss"|"human_review", "confidence": 0.0-1.0, "publish": true|false,
 "signal_type": "framing"|"image"|"sources"|"coordination",
 "headline_en": "max 90 characters", "summary_en": "2-4 sentences", "explanation": "why"}"""

DECISIONS = {"flag", "dismiss", "human_review"}
SIGNAL_TYPES = {"framing", "image", "sources", "coordination"}
MAX_FIELD_CHARS = 4000  # long diffs cost tokens and add nothing the report does not already say


def ask_gemini(case: dict) -> dict:
    """The only place that talks to Gemini. Returns the parsed JSON answer, or raises."""
    if config.USE_MOCK:
        return _mock_answer(case)

    import httpx

    key, model = config.env("GEMINI_API_KEY"), config.env("GEMINI_MODEL")
    if not key or not model:
        raise SystemExit("Set GEMINI_API_KEY and GEMINI_MODEL in .env (or USE_MOCK=true).")
    base = config.env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": DECIDER_PROMPT},
            {"role": "user", "content": json.dumps(_evidence(case), ensure_ascii=False)},
        ],
    }
    for attempt in range(4):
        r = httpx.post(base.rstrip("/") + "/chat/completions",
                       headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(5 * 2**attempt)  # rate limit or overload: wait 5, 10, 20 s
            continue
        r.raise_for_status()
        text = r.json()["choices"][0]["message"].get("content") or ""
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    raise RuntimeError("Gemini kept refusing")


def _evidence(case: dict) -> dict:
    """What Gemini sees: the case without our bookkeeping, long texts trimmed."""
    # Test labels must never reach the model, or the reliability test would grade itself.
    out = {k: v for k, v in case.items() if k not in ("synthetic", "sample", "expected", "account_hash")}
    for k in ("added", "removed"):
        if isinstance(out.get(k), str) and len(out[k]) > MAX_FIELD_CHARS:
            out[k] = out[k][:MAX_FIELD_CHARS] + " […]"
    return out


def _mock_answer(case: dict) -> dict:
    # Mostly agrees with Nemotron, sometimes not, so the two-opinion rule gets exercised.
    suspicious = (case.get("nemotron") or {}).get("suspicious")
    roll = int(hashlib.sha256(str(case.get("rev_id")).encode()).hexdigest()[:4], 16) % 10
    decision = ("flag" if roll < 7 else "human_review") if suspicious else ("dismiss" if roll < 8 else "flag")
    kind = case.get("kind") if case.get("kind") in SIGNAL_TYPES else "framing"
    return {
        "decision": decision, "confidence": round(0.5 + roll / 20, 2), "publish": decision == "flag",
        "signal_type": kind,
        "headline_en": f"[MOCK] {kind} change on {case.get('title', 'an article')}",
        "summary_en": "[MOCK] Placeholder summary written without calling Gemini.",
        "explanation": "[MOCK] No model was called.",
    }


def two_opinion_rule(nemotron_suspicious, gemini_decision) -> str:
    """Applied in code, never left to a model: flag only when both models agree."""
    if gemini_decision == "flag" and nemotron_suspicious is True:
        return "flag"
    if gemini_decision == "dismiss" and nemotron_suspicious is False:
        return "dismiss"
    return "human_review"  # disagreement, missing opinion, or an answer outside the 3 values


def in_sample(rev_id, rate: float) -> bool:
    # Deterministic, so a restarted run picks the same non-suspect cases.
    return int(hashlib.sha256(f"sample:{rev_id}".encode()).hexdigest()[:8], 16) % 10_000 < rate * 10_000


def decide(case: dict, sample_rate: float) -> dict:
    nemotron = case.get("nemotron") or {}
    suspicious = nemotron.get("suspicious")
    suspicious = suspicious if isinstance(suspicious, bool) else None  # anything odd = no opinion
    synthetic = bool(case.get("synthetic"))
    sample = bool(case.get("sample"))

    row = {
        "rev_id": case["rev_id"], "page_id": case.get("page_id"), "title": case.get("title"),
        "kind": case.get("kind"), "synthetic": synthetic, **({"sample": True} if sample else {}),
        "prompt_version": PROMPT_VERSION,
        "nemotron_suspicious": suspicious,
    }

    # Cost control: only suspects, unclear cases and a small sample of the rest go to Gemini.
    if suspicious is False and not synthetic and not in_sample(case["rev_id"], sample_rate):
        return row | {"decision": "dismiss", "confidence": None, "publish": False,
                      "signal_type": case.get("kind"), "headline_en": None, "summary_en": None,
                      "explanation": "Investigator found nothing suspicious; not sampled for a second opinion.",
                      "decided_by": "rule", "gemini_decision": None, "disagreement": False}

    try:
        answer = ask_gemini(case)
        error = None
        if not isinstance(answer, dict):
            raise ValueError("answer is not a JSON object")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        # A broken answer becomes a human review, never a crash or a flag.
        # (json.JSONDecodeError is a ValueError. Network errors are not caught here:
        # main() skips the case so a rerun retries it.)
        answer, error = {}, f"{type(e).__name__}: {e}"[:300]

    gemini_decision = answer.get("decision") if answer.get("decision") in DECISIONS else None
    final = two_opinion_rule(suspicious, gemini_decision)
    confidence = answer.get("confidence")
    confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else None
    signal = answer.get("signal_type") if answer.get("signal_type") in SIGNAL_TYPES else case.get("kind")
    headline = (answer.get("headline_en") or "").strip()[:90] or None

    return row | {
        "decision": final,
        "confidence": confidence,
        # The synthetic test campaign and the hand-written samples must never reach the public site.
        "publish": final == "flag" and answer.get("publish") is True and not synthetic and not sample,
        "signal_type": signal,
        "headline_en": headline,
        "summary_en": (answer.get("summary_en") or "").strip() or None,
        "explanation": (answer.get("explanation") or "").strip() or None,
        "decided_by": "mock" if config.USE_MOCK else "gemini",
        "decider_model": "mock" if config.USE_MOCK else config.env("GEMINI_MODEL"),
        "gemini_decision": gemini_decision,
        # One model saw manipulation, the other did not: counted in the quality panel.
        "disagreement": final == "human_review" and (suspicious is True or gemini_decision == "flag"),
        **({"error": error} if error else {}),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    canonical_input = config.EXCHANGE / "analysis.jsonl"
    p.add_argument("--input", default=str(canonical_input))
    p.add_argument("--output", default=None,
                   help="default: decisions.jsonl for the real analysis.jsonl, decisions.test.jsonl for any other input")
    p.add_argument("--sample-rate", type=float, default=0.05,
                   help="share of non-suspect cases sent to Gemini anyway, to measure disagreement")
    p.add_argument("--limit", type=int, default=None, help="stop after N new cases (for a first try)")
    args = p.parse_args()

    from pathlib import Path
    src = Path(args.input)
    if args.output:
        dst = Path(args.output)
    elif src.resolve() == canonical_input.resolve():
        dst = config.exchange_file("decisions.jsonl")
    else:
        # A test input (samples...) must never land in the file Léopold imports and publishes.
        dst = config.exchange_file("decisions.test.jsonl")
    if not src.exists():
        raise SystemExit(f"{src} not found. Try: --input decision/sample/analysis.sample.jsonl")
    first = next(read_jsonl(src), None)
    if first is not None and "nemotron" not in first:
        # candidates.jsonl has no investigator report: sending it would spend Gemini credits
        # on thousands of human_review rows.
        raise SystemExit(f"{src.name} has no 'nemotron' field: decide.py needs analysis.jsonl "
                         "(after Nemotron), not candidates.jsonl.")
    done = done_rev_ids(dst)
    print(f"{'MOCK' if config.USE_MOCK else 'REAL'} run: {src.name} -> {dst}  ({len(done)} already done)")

    counts: dict[str, int] = {}
    new = failures = 0
    for case in read_jsonl(src):
        if "rev_id" not in case or case["rev_id"] in done:
            continue
        try:
            row = decide(case, args.sample_rate)
            failures = 0
        except Exception as e:  # network / HTTP error: nothing written, the next run retries
            failures += 1
            print(f"  {case['rev_id']}: call failed ({type(e).__name__}: {str(e)[:200]})")
            if failures >= 5:
                raise SystemExit("5 failures in a row: check GEMINI_API_KEY, GEMINI_MODEL and the network.")
            continue
        append_jsonl(dst, row)
        done.add(case["rev_id"])
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
        new += 1
        print(f"  {row['rev_id']}: {row['decision']:<12} by {row['decided_by']}"
              + (f"  ({row['error']})" if row.get("error") else ""))
        if args.limit and new >= args.limit:
            break
    print(f"Done: {new} new decisions {counts}")


if __name__ == "__main__":
    main()
