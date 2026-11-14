"""Account profiles, without AI: our answer to the "bots and bad actors" part of Hostinger.

Reads  data/versions-XX.parquet (no text column, so it is fast)
Writes data/exchange/accounts.jsonl          (format 4.3 bis, one account per line, no names)
       data/exchange/accounts_summary.json   (counts used by quality.py)

    python decision/accounts.py

The rules are starting points from docs/TECH.md section 10: look at the output and tune them.
"""
import argparse
import json
import re
import statistics
from collections import defaultdict
from datetime import timedelta

import config
from dataio import account_hash, iter_versions, write_atomic

# Topics where narrative pushing is most likely (war, 1918, presidents, Karelia...). Tune freely.
SENSITIVE_TITLE = re.compile(
    r"sota|sisällis|kapina|vankileir|terror|karjal|presidentti|kekkonen|mannerheim|"
    r"ryti|paasikivi|jääkär|suojeluskun|punakaart|lapuan|itsenäis|miehity|evakko",
    re.I,
)
KIND_SCORE = {"bot_like": 0.7, "throwaway": 0.6, "single_purpose": 0.4, "normal": 0.1, "declared_bot": 0.0}


def fetch_declared_bots() -> set[str]:
    """The only external call here: Finnish Wikipedia's official bot accounts, cached on disk."""
    cache = config.CACHE / "declared_bots.txt"
    if cache.exists():
        return set(cache.read_text(encoding="utf-8").splitlines())
    if config.USE_MOCK:
        return set()  # the "name ends with bot" rule still applies

    import httpx

    names, params = set(), {"action": "query", "format": "json", "list": "allusers",
                            "augroup": "bot", "aulimit": "500"}
    with httpx.Client(headers={"User-Agent": config.WIKI_USER_AGENT}, timeout=60) as client:
        while True:
            data = client.get("https://fi.wikipedia.org/w/api.php", params=params).json()
            names |= {u["name"] for u in data.get("query", {}).get("allusers", [])}
            if "continue" not in data:
                break
            params |= data["continue"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(names)), encoding="utf-8")
    return names


def repeat_reasons() -> dict[str, str]:
    """{account_hash: readable reason} for the accounts in Maël's top_repeat_accounts.

    Only adds a reason: being flagged several times by the investigator is a hint, not proof,
    so it never changes the account's kind or score on its own.
    """
    path = config.EXCHANGE / "insights.json"
    if not path.exists():
        return {}
    top = (json.loads(path.read_text(encoding="utf-8")).get("accounts") or {}).get("top_repeat_accounts") or []
    out = {}
    for a in top:
        n, arts = a.get("suspicious_edits"), a.get("articles")
        first, last = str(a.get("first", ""))[:4], str(a.get("last", ""))[:4]
        years = first if first == last else f"{first}-{last}"
        out[a["account_hash"]] = (f"{n} edit{'s' if n != 1 else ''} flagged by the investigator across "
                                  f"{arts} article{'s' if arts != 1 else ''} ({years})")
    return out


def load_edits() -> dict[int, list[tuple]]:
    """{page_id: [(timestamp, rev_id, user, sha1, anonymous, title), ...] sorted by time}."""
    pages: dict[int, list[tuple]] = defaultdict(list)
    cols = ["page_id", "title", "rev_id", "timestamp", "user", "anonymous", "sha1"]
    for n, row in enumerate(iter_versions(cols), 1):
        pages[row["page_id"]].append((row["timestamp"], row["rev_id"], row["user"], row["sha1"],
                                      bool(row["anonymous"]), row["title"]))
        if n % 100_000 == 0:
            print(f"  {n:,} versions read")
    for edits in pages.values():
        edits.sort(key=lambda e: (e[0], e[1]))
    return pages


def max_edits_in_one_hour(times: list) -> int:
    best, start = 0, 0
    for end in range(len(times)):
        while times[end] - times[start] > timedelta(hours=1):
            start += 1
        best = max(best, end - start + 1)
    return best


def classify(user: str, a: dict, bots: set[str]) -> tuple[str, list[str], float]:
    times = sorted(a["times"])
    edits, articles = len(times), len(a["articles"])
    sensitive = len(a["sensitive"])
    revert_rate = a["reverted"] / edits if edits else 0.0
    reasons: list[str] = []

    if user in bots or user.lower().endswith("bot"):
        return "declared_bot", ["official bot account (benign, excluded)"], 0.0

    burst = max_edits_in_one_hour(times)
    gaps = [(b - a_).total_seconds() for a_, b in zip(times, times[1:])]
    regular = len(gaps) >= 9 and statistics.mean(gaps) > 0 and \
        statistics.pstdev(gaps) < 0.1 * statistics.mean(gaps)
    span_days = (times[-1] - times[0]).total_seconds() / 86400

    if burst >= 20 or regular:
        kind = "bot_like"
        if burst >= 20:
            reasons.append(f"{burst} edits within one hour")
        if regular:
            reasons.append(f"{edits} edits at very regular intervals (~{statistics.mean(gaps) / 60:.0f} min apart)")
    elif span_days <= 7 and sensitive >= 3:
        kind = "throwaway"
        reasons.append(f"active for {max(span_days, 0.1):.1f} days only, on {sensitive} sensitive articles")
    elif edits >= 10 and articles <= 2:
        kind = "single_purpose"
        reasons.append(f"{edits} edits, all on {articles} article{'s' if articles > 1 else ''}")
    else:
        kind = "normal"

    if kind != "normal":
        if sensitive and kind != "throwaway":
            reasons.append(f"edits {sensitive} sensitive article{'s' if sensitive > 1 else ''}")
        if a["reverted"]:
            reasons.append(f"{revert_rate:.0%} of edits reverted by another account")
    score = min(1.0, KIND_SCORE[kind] + 0.3 * revert_rate)
    return kind, reasons, round(score, 2)


def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        bots = fetch_declared_bots()
    except Exception as e:  # the list is a bonus: the "name ends with bot" rule still works
        print(f"  WARNING: could not fetch the official bot list ({type(e).__name__}); using the name rule only")
        bots = set()
    pages = load_edits()

    acc: dict[str, dict] = defaultdict(lambda: {"times": [], "articles": set(), "sensitive": set(),
                                                "reverted": 0, "anonymous": False})
    for page_id, edits in pages.items():
        for i, (ts, _rev, user, sha1, anon, title) in enumerate(edits):
            if not user:
                continue
            a = acc[user]
            a["times"].append(ts)
            a["articles"].add(page_id)
            a["anonymous"] |= anon
            if title and SENSITIVE_TITLE.search(title):
                a["sensitive"].add(page_id)
            # Reverted = the next version, by someone else, restores the text from before this edit.
            if 0 < i < len(edits) - 1:
                nxt, prev = edits[i + 1], edits[i - 1]
                if nxt[3] == prev[3] and sha1 != prev[3] and nxt[2] != user:
                    a["reverted"] += 1

    repeats = repeat_reasons()
    rows, counts = [], defaultdict(int)
    for user, a in acc.items():
        kind, reasons, score = classify(user, a, bots)
        if account_hash(user) in repeats:
            reasons.append(repeats[account_hash(user)])
        counts[kind] += 1
        times = sorted(a["times"])
        rows.append({
            "account_hash": account_hash(user), "kind": kind, "declared_bot": kind == "declared_bot",
            "anonymous": a["anonymous"], "score": score, "reasons": reasons,
            "edits": len(times), "articles": len(a["articles"]),
            "sensitive_articles": len(a["sensitive"]), "reverted": a["reverted"],
            "first_seen": times[0].date().isoformat(), "last_seen": times[-1].date().isoformat(),
        })
    rows.sort(key=lambda r: -r["score"])

    out = config.exchange_file("accounts.jsonl")
    write_atomic(out, rows)
    summary = {"accounts": len(rows), "by_kind": dict(counts),
               "declared_bots_excluded": counts["declared_bot"],
               "suspicious_accounts": counts["bot_like"] + counts["throwaway"] + counts["single_purpose"],
               "mock": config.USE_MOCK}
    write_atomic(config.exchange_file("accounts_summary.json"), summary, jsonl=False)
    print(f"Wrote {len(rows):,} accounts to {out}: {dict(counts)}")
    if repeats:
        found = sum(1 for r in rows if r["account_hash"] in repeats)
        print(f"  repeat-flag reason added to {found} of the {len(repeats)} accounts listed in insights.json")


if __name__ == "__main__":
    main()
