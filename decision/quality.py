"""Reliability numbers for the pitch and the "Detection quality" panel.

    python decision/quality.py campaign       # 1. plant the labelled fake campaign (give the file to Maël)
    python decision/quality.py review-sheet   # 2. pick 20 real "flag" cases to check by hand
    python decision/quality.py report         # 3. compute data/exchange/quality.json from real files

Every number in quality.json is counted from files; anything we have not measured yet is null.
The fake campaign is labelled "synthetic": true end to end and is never published.
"""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone

import config
from dataio import account_hash, read_jsonl, write_atomic

CAMPAIGN_FILE = config.EXCHANGE / "synthetic_candidates.jsonl"
REVIEW_SHEET = config.DATA / "manual_review.csv"  # under data/: it may show account-free but real cases

# Real articles, invented edits. rev_ids start at 900 000 000, far above any real fi.wikipedia rev_id
# in the dataset, so they can never collide with real versions.
ARTICLES = [(1150, "Suomen sisällissota"), (1256, "Talvisota"),
            (6021, "Carl Gustaf Emil Mannerheim"), (1275, "Urho Kekkonen")]
FAKE_ACCOUNTS = ["synthetic-account-1", "synthetic-account-2", "synthetic-account-3"]
# One-sided sentences pushed by the fake accounts (Finnish, as the real data):
#  - "The war of liberation was the Finnish people's united fight against Russian Bolshevism."
#  - "The Reds' crimes are the main reason for the prison camps."
CAMPAIGN_SENTENCES = [
    "Vapaussota oli Suomen kansan yhtenäinen taistelu venäläistä bolševismia vastaan.",
    "Punaisten rikokset ovat vankileirien pääasiallinen syy.",
]


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def _line(i: int, page_id: int, title: str, when: datetime, kind: str, account: str, **extra) -> dict:
    return {
        "rev_id": 900_000_000 + i, "page_id": page_id, "title": title,
        "timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind,
        # "synthetic" is the ONLY label, and decide.py strips it before asking a model:
        # anything else that gives the test away would make the "caught" figure meaningless.
        "account_hash": account_hash(account), "user_is_new": True, "synthetic": True,
        "comment": "täsmennys",  # "clarification", an ordinary-looking edit summary
        "added": "", "removed": "", "image": None, "refs_removed": 0, **extra,
    }


def campaign() -> None:
    """10 text edits by 3 fake accounts on 4 articles in 10 days + up to 3 misleading captions."""
    t0 = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
    rows, i = [], 0
    for n in range(10):
        page_id, title = ARTICLES[n % len(ARTICLES)]
        account = FAKE_ACCOUNTS[n % len(FAKE_ACCOUNTS)]
        when = t0 + timedelta(days=n, hours=n % 5)
        i += 1
        if n < 6:  # the same sentence on several articles by several accounts = coordination
            rows.append(_line(i, page_id, title, when, "coordination", account,
                              added=CAMPAIGN_SENTENCES[n % 2]))
        else:      # reframing of the 1918 war
            rows.append(_line(i, page_id, title, when, "framing", account,
                              added="vapaussota", removed="sisällissota"))

    # Misleading captions: a real photo given the caption of ANOTHER real photo. We reuse Maël's
    # real image candidates so the picture exists and Nemotron can look at it.
    real = [c for c in read_jsonl(config.EXCHANGE / "candidates.jsonl")
            if c.get("kind") == "image" and not c.get("synthetic") and (c.get("image") or {}).get("thumb_url")
            and (c["image"].get("caption_new") or "").strip()]
    if len(real) < 2:
        print("  No real image candidates with a thumbnail yet: caption cases skipped. "
              "Rerun once Maël's candidates.jsonl has thumbnails.")
    for n in range(min(3, len(real) - 1 if len(real) > 1 else 0)):
        photo, other = real[n], real[(n + 1) % len(real)]
        if norm(photo["image"]["caption_new"]) == norm(other["image"]["caption_new"]):
            continue
        i += 1
        rows.append(_line(i, photo["page_id"], photo["title"], t0 + timedelta(days=10 - n), "image",
                          FAKE_ACCOUNTS[n], image={
                              "change": "recaptioned", "file": photo["image"]["file"],
                              "caption_old": photo["image"]["caption_new"],
                              "caption_new": other["image"]["caption_new"],
                              "thumb_url": photo["image"]["thumb_url"]}))

    write_atomic(CAMPAIGN_FILE, rows)
    print(f"Planted {len(rows)} synthetic edits in {CAMPAIGN_FILE}\n"
          "Give this file to Maël: his run_nemotron.py processes it like candidates.jsonl, "
          "and the results go through decide.py like any case (they are never published).\n"
          "Maël must NOT send the 'synthetic' field to Nemotron, or the test grades itself.")


def review_sheet(n: int = 20) -> None:
    flags = [d for d in read_jsonl(config.EXCHANGE / "decisions.jsonl")
             if d.get("decision") == "flag" and not d.get("synthetic")]
    if not flags:
        raise SystemExit("No real 'flag' decisions yet (decisions.jsonl). Come back after decide.py.")
    # Deterministic pick, so two teammates get the same 20 cases.
    flags.sort(key=lambda d: hashlib.sha256(str(d["rev_id"]).encode()).hexdigest())
    REVIEW_SHEET.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_SHEET.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rev_id", "title", "headline_en", "diff_link", "correct (yes/no)", "note"])
        for d in flags[:n]:
            w.writerow([d["rev_id"], d.get("title"), d.get("headline_en"),
                        f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={d['rev_id']}", "", ""])
    print(f"Wrote {min(n, len(flags))} cases to {REVIEW_SHEET}. Open each diff link, fill "
          "'correct' with yes or no, then run: python decision/quality.py report")


def report() -> None:
    decisions = list(read_jsonl(config.EXCHANGE / "decisions.jsonl"))
    if any(d.get("decided_by") == "mock" for d in decisions):
        raise SystemExit("decisions.jsonl contains mock decisions: refusing to publish numbers from them.")
    if not decisions:
        raise SystemExit("No data/exchange/decisions.jsonl yet: nothing to measure.")
    decisions = [d for d in decisions if not d.get("sample")]
    real = [d for d in decisions if not d.get("synthetic")]
    synth = [d for d in decisions if d.get("synthetic")]
    planted = list(read_jsonl(CAMPAIGN_FILE))

    reviewed = correct = 0
    if REVIEW_SHEET.exists():
        # Excel (French settings) saves with ";" and a BOM: accept both, or the count is silently 0.
        with REVIEW_SHEET.open(encoding="utf-8-sig", errors="replace") as f:
            head = f.readline()
            f.seek(0)
            for r in csv.DictReader(f, delimiter=";" if head.count(";") > head.count(",") else ","):
                answer = (r.get("correct (yes/no)") or "").strip().lower()
                if answer in ("yes", "no", "y", "n", "kyllä", "ei", "oui", "non"):
                    reviewed += 1
                    correct += answer in ("yes", "y", "kyllä", "oui")

    accounts_summary = config.EXCHANGE / "accounts_summary.json"
    acc = json.loads(accounts_summary.read_text(encoding="utf-8")) if accounts_summary.exists() else {}
    if acc.get("mock"):
        acc = {}

    quality = {
        "synthetic_campaign": {
            "planted": len(planted) or None,
            "examined": len(synth) or None,
            "seen_as_suspicious_by_nemotron": sum(d.get("nemotron_suspicious") is True for d in synth) if synth else None,
            "caught": sum(d.get("decision") == "flag" for d in synth) if synth else None,
            "sent_to_human_review": sum(d.get("decision") == "human_review" for d in synth) if synth else None,
        },
        "manual_review": {"reviewed": reviewed or None, "correct": correct if reviewed else None},
        "decisions": {k: sum(d.get("decision") == k for d in real) for k in ("flag", "human_review", "dismiss")},
        "published": sum(bool(d.get("publish")) for d in real),
        "downgraded_by_two_model_rule": sum(bool(d.get("disagreement")) for d in real),
        "declared_bots_excluded": acc.get("declared_bots_excluded"),
        "suspicious_accounts": acc.get("suspicious_accounts"),
        "notes": {
            "synthetic_campaign": f"{len(planted)} fake edits planted and labelled as synthetic, "
                                  "run through the same pipeline, never shown publicly",
            "manual_review": "flagged cases checked by hand by the team against the Wikipedia diff",
            "downgraded_by_two_model_rule": "one model saw manipulation, the other did not: sent to a human instead of published",
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out = config.EXCHANGE / "quality.json"
    write_atomic(out, quality, jsonl=False)
    print(json.dumps(quality, indent=2, ensure_ascii=False))
    print(f"Wrote {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["campaign", "review-sheet", "report"])
    args = p.parse_args()
    {"campaign": campaign, "review-sheet": review_sheet, "report": report}[args.step]()


if __name__ == "__main__":
    main()
