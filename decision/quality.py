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
INSIGHTS_FILE = config.EXCHANGE / "insights.json"  # written by analysis/ (Maël), no AI in it
SMALL_GROUP = 30  # below this many cases, a share or a median says little: the sentence says so
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
    real, seen = [], set()
    for c in read_jsonl(config.EXCHANGE / "candidates.jsonl"):
        img = c.get("image") or {}
        caption = (img.get("caption_new") or "").strip()
        # A real photo (not a logo or map) with a descriptive caption, one per file.
        if (c.get("kind") == "image" and not c.get("synthetic") and img.get("thumb_url")
                and img.get("change") in ("added", "recaptioned", "replaced") and len(caption) >= 25
                and str(img.get("file", "")).lower().endswith((".jpg", ".jpeg")) and img["file"] not in seen):
            seen.add(img["file"])
            real.append(c)
    # Deterministic shuffle, so the campaign does not depend on the order of Maël's file.
    real.sort(key=lambda c: hashlib.sha256(str(c["rev_id"]).encode()).hexdigest())
    if len(real) < 2:
        print("  No real image candidates with a thumbnail yet: caption cases skipped. "
              "Rerun once Maël's candidates.jsonl has thumbnails.")
    for n in range(min(3, len(real) - 1 if len(real) > 1 else 0)):
        photo = real[n]
        # The misleading caption comes from a photo of ANOTHER article, so it cannot match by chance.
        other = next((o for o in real[n + 1:] if o["page_id"] != photo["page_id"]
                      and norm(o["image"]["caption_new"]) != norm(photo["image"]["caption_new"])), None)
        if other is None:
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


def _read_sheet() -> list[dict]:
    if not REVIEW_SHEET.exists():
        return []
    # Excel (French settings) saves with ";" and a BOM: accept both, or the count is silently 0.
    with REVIEW_SHEET.open(encoding="utf-8-sig", errors="replace") as f:
        head = f.readline()
        f.seek(0)
        return list(csv.DictReader(f, delimiter=";" if head.count(";") > head.count(",") else ","))


def review_sheet(n: int = 20) -> None:
    flags = [d for d in read_jsonl(config.EXCHANGE / "decisions.jsonl")
             if d.get("decision") == "flag" and not d.get("synthetic")]
    if not flags:
        raise SystemExit("No real 'flag' decisions yet (decisions.jsonl). Come back after decide.py.")
    if REVIEW_SHEET.exists() and any(r.get("correct (yes/no)", "").strip() for r in _read_sheet()):
        # A filled sheet is a human's work: never overwrite it silently.
        raise SystemExit(f"{REVIEW_SHEET} already has answers. Rename it first if you really want a new sheet.")
    # Deterministic pick, so two teammates get the same 20 cases.
    flags.sort(key=lambda d: hashlib.sha256(str(d["rev_id"]).encode()).hexdigest())
    cases = {c["rev_id"]: c for c in read_jsonl(config.EXCHANGE / "analysis.jsonl")}

    def cut(text, size=400):
        text = " ".join((text or "").split())
        return text if len(text) <= size else text[:size] + " […]"

    REVIEW_SHEET.parent.mkdir(parents=True, exist_ok=True)
    # ";" and a BOM: French Excel then opens it in columns, with the Finnish accents right.
    with REVIEW_SHEET.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["n", "rev_id", "article", "type", "titre (Gemini)", "résumé (Gemini)", "avis Nemotron",
                    "texte ajouté (finnois)", "texte retiré (finnois)", "légende avant", "légende après",
                    "lien diff", "correct (yes/no)", "note"])
        for i, d in enumerate(flags[:n], 1):
            c = cases.get(d["rev_id"], {})
            img = c.get("image") or {}
            w.writerow([i, d["rev_id"], d.get("title"), d.get("kind"), d.get("headline_en"),
                        cut(d.get("summary_en"), 600), cut((c.get("nemotron") or {}).get("report"), 600),
                        cut(c.get("added")), cut(c.get("removed")),
                        cut(img.get("caption_old"), 200), cut(img.get("caption_new"), 200),
                        f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={d['rev_id']}", "", ""])
    print(f"Wrote {min(n, len(flags))} cases to {REVIEW_SHEET}. Open each diff link, fill "
          "'correct' with yes or no, then run: python decision/quality.py report")


SUSPICIOUS_MEANS = ("\"Suspicious\" means judged suspicious by the investigator model (Nemotron), "
                    "not confirmed manipulation.")


def pct(share: float) -> str:
    return f"{share * 100:.0f}%"


def duration(days: float) -> str:
    if days < 1 / 24:
        return f"{max(1, round(days * 24 * 60))} minutes"
    if days < 1:
        return f"{round(days * 24)} hours"
    return f"{days:g} days"


def insights_sections() -> dict:
    """long_tail and repeat_accounts, copied as-is from Maël's insights.json, plus one English
    sentence per figure for the Detection quality page. Never the per-account list: account
    hashes next to their revision ids would let anyone find the names in Wikipedia's history."""
    if not INSIGHTS_FILE.exists():
        return {}
    ins = json.loads(INSIGHTS_FILE.read_text(encoding="utf-8"))
    source = ins.get("generated_from", {})
    notes = ins.get("notes", {})
    end = source.get("data_end", "the end of the data")
    out: dict = {}

    if ins.get("long_tail"):
        buckets = []
        for b in ins["long_tail"]:
            n = b["suspicious_edits"]
            sentences = {
                "suspicious_edits": f"{n} edits judged suspicious by the investigator on {b['bucket']} articles.",
                "median_days_online": f"Half of them stayed online less than {duration(b['median_days_online'])}.",
                "share_online_over_1_day": f"{pct(b['share_online_over_1_day'])} stayed online more than a day.",
                "share_online_over_30_days": f"{pct(b['share_online_over_30_days'])} stayed online more than 30 days.",
                "still_online": f"{b['still_online']} were still online on {end}.",
            }
            if n < SMALL_GROUP:
                sentences["caveat"] = f"Only {n} cases in this group: these figures are indicative, not conclusive."
            buckets.append({**b, "sentences": sentences})
        out["long_tail"] = {
            "buckets": buckets,
            "definition": SUSPICIOUS_MEANS + " Articles are grouped by their number of versions in the data, "
                          "a proxy for how many people watch them.",
            "source": {"file": INSIGHTS_FILE.name, **source},
        }

    acc = {k: v for k, v in (ins.get("accounts") or {}).items() if k != "top_repeat_accounts"}
    if acc:
        sentences = {}
        if "share_new_accounts_all_analysed" in acc:
            sentences["share_new_accounts_all_analysed"] = (
                f"{pct(acc['share_new_accounts_all_analysed'])} of all analysed edits came from new accounts.")
        if "share_new_accounts_suspicious" in acc:
            sentences["share_new_accounts_suspicious"] = (
                f"{pct(acc['share_new_accounts_suspicious'])} of the edits judged suspicious came from new accounts.")
        if "repeat_accounts" in acc:
            sentences["repeat_accounts"] = (
                f"{acc['repeat_accounts']} accounts made at least 2 edits judged suspicious.")
        if "repeat_accounts_multi_article" in acc:
            sentences["repeat_accounts_multi_article"] = (
                f"{acc['repeat_accounts_multi_article']} of them did so on more than one article.")
        out["repeat_accounts"] = {
            **acc,
            "sentences": sentences,
            "definition": SUSPICIOUS_MEANS + " New account: " + notes.get("new_account", "a recent account")
                          + ". A repeated pattern is a hint, not proof, and no account is ever named.",
            "source": {"file": INSIGHTS_FILE.name, **source},
        }
    return out


def time_online_section(decisions: list[dict]) -> dict:
    """How far our automatic time-online estimate (exposure.jsonl) agrees with Maël's independent
    one (case-durations.jsonl). Counted from the files, never typed in."""
    mine = {r["rev_id"]: r["exposure"] for r in read_jsonl(config.EXCHANGE / "exposure.jsonl")
            if isinstance(r.get("exposure"), dict) and "days_live" in r["exposure"]}
    other = {r["rev_id"]: r for r in read_jsonl(config.EXCHANGE / "case-durations.jsonl") if "days_online" in r}
    common = [r for r in other if r in mine]
    if not common:
        return {}
    agree = sum(abs(mine[r]["days_live"] - other[r]["days_online"]) <= 1 for r in common)
    return {"time_online": {
        "compared": len(common),
        "agree_within_1_day": agree,
        "checked_by_hand": sum(bool((d.get("exposure") or {}).get("verified")) for d in decisions),
        "sentence": f"Time online is an automatic estimate; two methods agree within a day on "
                    f"{agree} of {len(common)} cases.",
    }}


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
    for r in _read_sheet():
        answer = (r.get("correct (yes/no)") or "").strip().lower()
        if answer in ("yes", "no", "y", "n", "kyllä", "ei", "oui", "non"):
            reviewed += 1
            correct += answer in ("yes", "y", "kyllä", "oui")

    accounts_summary = config.EXCHANGE / "accounts_summary.json"
    acc = json.loads(accounts_summary.read_text(encoding="utf-8")) if accounts_summary.exists() else {}
    if acc.get("mock"):
        acc = {}

    # web/app.js shows every top-level block it knows and every unknown top-level number or
    # string as a card: so a block appears only once it is measured (never "null / 13"), and
    # bookkeeping lives under "details" (an object, which the page ignores).
    quality: dict = {}
    if synth:
        quality["synthetic_campaign"] = {
            "planted": len(planted) or len(synth),
            "caught": sum(d.get("decision") == "flag" for d in synth),
        }
    if reviewed:
        quality["manual_review"] = {"reviewed": reviewed, "correct": correct}
    quality["downgraded_by_two_model_rule"] = sum(bool(d.get("disagreement")) for d in real)
    for key in ("declared_bots_excluded", "suspicious_accounts"):
        if isinstance(acc.get(key), int):
            quality[key] = acc[key]
    quality["notes"] = {
        "synthetic_campaign": f"{len(planted) or len(synth)} fake edits planted and labelled as synthetic, "
                              "run through the same pipeline, never shown publicly.",
        "manual_review": "Flagged cases checked by hand by the team against the Wikipedia diff.",
        "downgraded_by_two_model_rule": "One model saw manipulation, the other did not: sent to a human instead of published.",
    }
    # Objects, not numbers: the page ignores them until Eléa adds a block that reads the sentences.
    quality.update(insights_sections())
    quality.update(time_online_section(real))
    quality["details"] = {
        "synthetic_examined": len(synth),
        "synthetic_seen_as_suspicious_by_nemotron": sum(d.get("nemotron_suspicious") is True for d in synth),
        "synthetic_sent_to_human_review": sum(d.get("decision") == "human_review" for d in synth),
        "decisions": {k: sum(d.get("decision") == k for d in real) for k in ("flag", "human_review", "dismiss")},
        "published": sum(bool(d.get("publish")) for d in real),
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
