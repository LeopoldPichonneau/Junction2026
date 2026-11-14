"""How the names of the 1918 war changed over time (no AI call).

For each month, takes the last version of each article as it stood at the end of that month
(an article that was not edited keeps its previous state) and counts the watched terms
(vapaussota, sisällissota, kansalaissota, luokkasota, punakapina, veljessota, all inflections).

Writes data/exchange/term-timeline.json:
  - "article": month by month, for one article (default 1150, Suomen sisällissota);
  - "corpus": month by month, summed over every article of the files given.

Usage (from the repository root):
    python analysis/term_timeline.py data/versions-01.parquet
"""

import argparse
import json

from find_candidates import WATCHED_TERMS, clean_article, iter_versions, term_counts

OUT = "data/exchange/term-timeline.json"
FOCUS_PAGE = 1150
# Neutral or academic names vs names that take a side (White: liberation / rebellion; Red: class war).
GROUPS = {"neutral": ["sisällissota", "kansalaissota", "veljessota"],
          "white_framing": ["vapaussota", "punakapina"],
          "red_framing": ["luokkasota"]}


def month_end_counts(rows_of_article):
    """{month: term counts of the last version saved in that month} for one article."""
    by_month = {}
    for row in rows_of_article:                 # rows are oldest first: the last one wins
        by_month[row["timestamp"].strftime("%Y-%m")] = row
    return {m: (r["rev_id"], term_counts(clean_article(r["text"] or ""))) for m, r in by_month.items()}


def months_between(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def with_groups(counts: dict) -> dict:
    groups = {g: sum(counts[t] for t in terms) for g, terms in GROUPS.items()}
    total = sum(groups.values())
    return {"counts": counts, "groups": groups,
            "white_share": round(groups["white_framing"] / total, 3) if total else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="parquet files")
    parser.add_argument("--page-id", type=int, default=FOCUS_PAGE, help="article for the detailed curve")
    args = parser.parse_args()

    per_article, titles = {}, {}
    current, rows = None, []

    def flush():
        if rows:
            per_article[current] = month_end_counts(rows)

    for row in iter_versions(args.inputs, None):
        if row["page_id"] != current:
            flush()
            current, rows = row["page_id"], []
        titles[row["page_id"]] = row["title"]
        # Keep only the text we need: one version per month survives month_end_counts.
        if rows and rows[-1]["timestamp"].strftime("%Y-%m") == row["timestamp"].strftime("%Y-%m"):
            rows[-1] = row
        else:
            rows.append(row)
    flush()

    all_months = sorted({m for months in per_article.values() for m in months})
    timeline = months_between(all_months[0], all_months[-1])

    def carried(article_months: dict) -> dict:
        """Month -> (rev_id, counts), carrying the last known state through months without edits."""
        out, last = {}, None
        for m in timeline:
            last = article_months.get(m, last)
            if last is not None:
                out[m] = last
        return out

    focus = carried(per_article.get(args.page_id, {}))
    article = [{"month": m, "rev_id": rev, **with_groups(c)} for m, (rev, c) in focus.items()]

    corpus = []
    states = {pid: carried(months) for pid, months in per_article.items()}
    for m in timeline:
        total = {t: 0 for t in WATCHED_TERMS}
        articles = 0
        for st in states.values():
            if m in st:
                articles += 1
                for t, n in st[m][1].items():
                    total[t] += n
        corpus.append({"month": m, "articles": articles, **with_groups(total)})

    result = {
        "article": {"page_id": args.page_id, "title": titles.get(args.page_id), "months": article},
        "corpus": {"articles": len(per_article), "months": corpus},
        "groups": GROUPS,
        "notes": {"method": "state of each article at the end of each month; inflected forms counted by stem",
                  "white_share": "white_framing / all watched terms",
                  "source": "Finnish Wikipedia revision history (CC BY-SA 4.0), MariaDB dataset M"},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    for label, series in (("article", article), ("corpus", corpus)):
        print(f"--- {label}")
        for p in series:
            if p["month"].endswith("-01") or p is series[-1]:
                print(p["month"], p["groups"], "white_share", p["white_share"])


if __name__ == "__main__":
    main()
