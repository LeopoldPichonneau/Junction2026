"""Readers exposed without double counting.

Each published case has its own estimate (readers_est = daily page views of the article while
the case was online). Summing them counts twice the readers of an article where two cases were
online at the same time. Here, for each article, the periods when at least one published case
was online are merged first, and the views of that merged time are counted once.

Writes data/exchange/readers.json:
  {"sum_of_cases": ..., "unique": ..., "checked": ..., "per_article": [...], "method": ...}
"sum_of_cases" is recomputed the same way as decision/exposure.py, and must match the
readers_est already published; if it does not, the file says so and the site keeps the sum.

Usage (from the repository root, real page views):
    USE_MOCK=false python decision/readers.py
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

import config
from dataio import read_jsonl
from exposure import fetch_daily_views, views_between


def when(value: str | None) -> datetime | None:
    """'2025-04-14T21:55Z' or '2025-04-14' -> aware datetime (UTC)."""
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    if len(value) == 10:
        value += "T00:00:00+00:00"
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def periods(exposure: dict) -> list[tuple[datetime, datetime]]:
    """Online periods of one case, minus the gaps found by hand, clipped to the page view data."""
    a = max(when(exposure["live_from"]), config.PAGEVIEWS_START)
    b = when(exposure.get("live_until")) or config.DATASET_END
    spans = [(a, b)] if b > a else []
    for gap in exposure.get("gaps") or []:
        g0, g1 = when(gap[0] if isinstance(gap, list) else gap.get("from")), when(gap[1] if isinstance(gap, list) else gap.get("until"))
        cut = []
        for s, e in spans:
            if g1 <= s or g0 >= e:
                cut.append((s, e))
                continue
            if g0 > s:
                cut.append((s, g0))
            if g1 < e:
                cut.append((g1, e))
        spans = cut
    return spans


def merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def main() -> None:
    if config.USE_MOCK:
        sys.exit("Run with USE_MOCK=false: in mock mode the page views are invented.")
    decisions = [d for d in read_jsonl(config.EXCHANGE / "decisions.jsonl")
                 if d.get("decision") == "flag" and d.get("publish") and not d.get("synthetic")]
    known = [d for d in decisions if (d.get("exposure") or {}).get("readers_est") is not None]

    by_title = defaultdict(list)
    recomputed, published = 0.0, 0
    for d in known:
        ex = d["exposure"]
        titles = ex.get("titles") or [d["title"]]
        if len(titles) != 1:
            sys.exit(f"rev {d['rev_id']}: several titles, not handled here")
        views = fetch_daily_views(titles[0])
        spans = periods(ex)
        recomputed += sum(views_between(views, s, e) for s, e in spans)
        published += ex["readers_est"]
        by_title[titles[0]].extend(spans)

    unique, per_article = 0.0, []
    for title, spans in sorted(by_title.items()):
        merged = merge(spans)
        views = fetch_daily_views(title)
        n = sum(views_between(views, s, e) for s, e in merged)
        unique += n
        per_article.append({"title": title, "cases": sum(1 for d in known if (d["exposure"].get("titles") or [d["title"]])[0] == title),
                            "readers_unique": int(round(n))})

    gap = abs(recomputed - published) / published if published else 1
    result = {
        "cases_with_readers": len(known),
        "cases_without_readers": len(decisions) - len(known),
        "sum_of_cases": published,
        "sum_recomputed": int(round(recomputed)),
        "checked": gap <= 0.02,
        "unique": int(round(unique)),
        "per_article": sorted(per_article, key=lambda r: -r["readers_unique"]),
        "method": "Daily page views of the article (Wikimedia, since July 2015), counted once for any moment when at "
                  "least one published case was online on it. Still an upper bound: a page view is not a reader of the passage.",
    }
    out = config.EXCHANGE / "readers.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"published sum {published:,} · recomputed {int(recomputed):,} ({gap:.2%} apart) · "
          f"unique {int(unique):,} · {'OK' if result['checked'] else 'NOT CHECKED: the site keeps the sum'} -> {out}")


if __name__ == "__main__":
    main()
