"""Two findings for the pitch and the "Detection quality" panel, from files we already have (no AI call).

1. Long tail: how long each suspicious edit stayed online, by how watched the article is
   (number of versions in the data = how many people edit, and so watch, the article).
2. Repeat actors: accounts behind several suspicious edits, and how often suspicious edits
   come from new accounts compared with all analysed edits.

Reads data/exchange/analysis.jsonl and the parquet files; writes data/exchange/insights.json
(one summary object) and data/exchange/case-durations.jsonl (one line per suspicious edit).
Only account hashes are used, never names.

Usage (from the repository root):
    python analysis/insights.py data/versions-01.parquet
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

import pyarrow.parquet as pq

from find_candidates import (clean_article, count_refs, images, is_declared_bot,
                             iter_versions, term_counts)

ANALYSIS = "data/exchange/analysis.jsonl"
INSIGHTS = "data/exchange/insights.json"
DURATIONS = "data/exchange/case-durations.jsonl"
DATA_END = datetime(2026, 10, 1)     # end of the dataset (docs/TECH.md): "still online" is counted to here
# Buckets of article attention, by number of versions in the data.
BUCKETS = [("heavily edited (1000+ versions)", 1000), ("medium (200-999)", 200), ("rarely edited (<200)", 0)]


def bucket(n_versions: int) -> str:
    return next(name for name, low in BUCKETS if n_versions >= low)


class Page:
    """Versions of one article after the suspicious edit, with features computed on demand."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.index = {r["rev_id"]: i for i, r in enumerate(rows)}
        self._terms, self._refs, self._images = {}, {}, {}

    def terms(self, k):
        if k not in self._terms:
            self._terms[k] = term_counts(clean_article(self.rows[k]["text"] or ""))
        return self._terms[k]

    def refs(self, k):
        if k not in self._refs:
            self._refs[k] = count_refs(self.rows[k]["text"] or "")
        return self._refs[k]

    def images(self, k):
        if k not in self._images:
            self._images[k] = images(self.rows[k]["text"] or "")
        return self._images[k]


def change_gone(page: Page, case: dict, i: int, k: int) -> bool:
    """Is the suspicious change no longer in version k? (i = the suspicious version)"""
    if page.rows[k]["sha1"] and page.rows[k]["sha1"] == page.rows[i - 1]["sha1"]:
        return True                                     # plain revert to the text before
    kind = case["kind"]
    if kind == "framing":
        before, after, now = page.terms(i - 1), page.terms(i), page.terms(k)
        raised = [t for t in after if after[t] > before[t]]
        changed = [t for t in after if after[t] != before[t]]
        return any(now[t] < after[t] for t in raised) or all(now[t] == before[t] for t in changed)
    if kind == "sources":
        return page.refs(k) >= page.refs(i - 1)
    if kind == "image":
        img, now = case["image"], page.images(k)
        if img["change"] == "removed":
            return img["file"] in now
        return now.get(img["file"]) != page.images(i).get(img["file"])
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="parquet files")
    args = parser.parse_args()

    with open(ANALYSIS, encoding="utf-8") as f:
        analysed = [json.loads(line) for line in f if line.strip()]
    real = [r for r in analysed if not r.get("synthetic")]
    suspicious = [r for r in real if r["nemotron"]["suspicious"]]
    by_page = defaultdict(list)
    for r in suspicious:
        by_page[r["page_id"]].append(r)

    # Cheap pass without text: versions per article, declared-bot edits.
    versions, bot_edits = Counter(), 0
    for path in args.inputs:
        t = pq.read_table(path, columns=["page_id", "user"])
        versions.update(t["page_id"].to_pylist())
        bot_edits += sum(is_declared_bot(u) for u in t["user"].to_pylist())

    # Read the text of the articles with suspicious edits, one article at a time.
    durations = []
    current, rows = None, []

    def flush():
        if not rows:
            return
        page = Page(rows)
        for case in by_page[current]:
            i = page.index.get(case["rev_id"])
            if i is None or i == 0:
                continue
            start = rows[i]["timestamp"]
            end = next((k for k in range(i + 1, len(rows)) if change_gone(page, case, i, k)), None)
            until = rows[end]["timestamp"] if end is not None else DATA_END
            durations.append({
                "rev_id": case["rev_id"], "page_id": case["page_id"], "title": case["title"],
                "kind": case["kind"], "account_hash": case["account_hash"],
                "user_is_new": case["user_is_new"], "live_from": start.strftime("%Y-%m-%d"),
                "live_until": None if end is None else until.strftime("%Y-%m-%d"),
                "ended_by_rev_id": None if end is None else rows[end]["rev_id"],
                "days_online": round((until - start).total_seconds() / 86400, 2),
                "still_online": end is None,
                "article_versions": versions[case["page_id"]],
                "article_bucket": bucket(versions[case["page_id"]]),
            })

    for row in iter_versions(args.inputs, sorted(by_page)):
        if row["page_id"] != current:
            flush()
            current, rows = row["page_id"], []
        rows.append({k: row[k] for k in ("rev_id", "timestamp", "sha1", "text")})
    flush()

    with open(DURATIONS, "w", encoding="utf-8") as out:
        for d in sorted(durations, key=lambda d: -d["days_online"]):
            out.write(json.dumps(d, ensure_ascii=False) + "\n")

    # 1. Long tail
    long_tail = []
    for name, _ in BUCKETS:
        days = [d["days_online"] for d in durations if d["article_bucket"] == name]
        if days:
            long_tail.append({
                "bucket": name, "suspicious_edits": len(days),
                "median_days_online": round(statistics.median(days), 2),
                "share_online_over_1_day": round(sum(x > 1 for x in days) / len(days), 3),
                "share_online_over_30_days": round(sum(x > 30 for x in days) / len(days), 3),
                "still_online": sum(d["still_online"] for d in durations if d["article_bucket"] == name),
            })

    # 2. Repeat actors and new accounts
    per_account = defaultdict(list)
    for r in suspicious:
        if r["account_hash"]:
            per_account[r["account_hash"]].append(r)
    repeat = []
    for h, cases in per_account.items():
        if len(cases) >= 2:
            dates = sorted(c["timestamp"][:10] for c in cases)
            repeat.append({"account_hash": h, "suspicious_edits": len(cases),
                           "articles": len({c["page_id"] for c in cases}),
                           "kinds": dict(Counter(c["kind"] for c in cases)),
                           "first": dates[0], "last": dates[-1],
                           "rev_ids": sorted(c["rev_id"] for c in cases)})
    repeat.sort(key=lambda a: (-a["articles"], -a["suspicious_edits"]))
    new_all = sum(r["user_is_new"] for r in real) / len(real)
    new_susp = sum(r["user_is_new"] for r in suspicious) / len(suspicious)
    anonymous = sum(r["account_hash"] is None for r in suspicious)

    insights = {
        "generated_from": {"analysed_edits": len(real), "suspicious_edits": len(suspicious),
                           "with_duration": len(durations), "data_end": DATA_END.strftime("%Y-%m-%d")},
        "long_tail": long_tail,
        "accounts": {
            "share_new_accounts_all_analysed": round(new_all, 3),
            "share_new_accounts_suspicious": round(new_susp, 3),
            "suspicious_without_account_hash": anonymous,
            "repeat_accounts": len(repeat),
            "repeat_accounts_multi_article": sum(a["articles"] >= 2 for a in repeat),
            "top_repeat_accounts": repeat[:15],
        },
        "declared_bot_edits_excluded": bot_edits,
        "notes": {
            "article_bucket": "number of versions of the article in the data, a proxy for how many people watch it",
            "days_online": "until the first later version where the suspicious change is gone (same rule per kind as "
                           "the detection), or until the end of the data",
            "new_account": "edit made within 7 days of the account's first edit in the data files",
        },
    }
    with open(INSIGHTS, "w", encoding="utf-8") as f:
        json.dump(insights, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: insights[k] for k in ("generated_from", "long_tail", "declared_bot_edits_excluded")},
                     ensure_ascii=False, indent=1))
    acc = insights["accounts"]
    print({k: acc[k] for k in acc if k != "top_repeat_accounts"})
    for a in acc["top_repeat_accounts"][:8]:
        print(a)


if __name__ == "__main__":
    sys.exit(main())
