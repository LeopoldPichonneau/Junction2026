"""Loaded names of the 1918 war that are still online, and since when (no AI call).

A review list for volunteers: in the last version of each article, every occurrence of a
term that takes a side (White: "vapaussota" = war of liberation, "punakapina" = red rebellion;
Red: "luokkasota" = class war), with its sentence and the date since which that exact passage
has been online without interruption.

Two passes over the parquet files, so memory stays low even for long articles:
1. the last version of each article gives the passages to follow;
2. every version is checked for each passage, to find when its current unbroken run began.

Writes data/exchange/still-online.json. Usage (from the repository root):
    python analysis/still_online.py data/versions-01.parquet
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime

import pyarrow.parquet as pq

from find_candidates import clean_inline, iter_versions

OUT = "data/exchange/still-online.json"
DATA_END = datetime(2026, 10, 1)
LOADED = {
    "vapaussota": ("white", re.compile(r"vapausso[td]\w*", re.I)),
    "punakapina": ("white", re.compile(r"punakapin\w*", re.I)),
    "luokkasota": ("red", re.compile(r"luokkaso[td]\w*", re.I)),
}
# Characters of raw wikitext just BEFORE the term that identify the passage: text after the
# term (a new list item, a name added nearby) would break the match for no real change.
CONTEXT = 20
QUOTES = "\"”“«»„"


def passages(text: str) -> list[dict]:
    """Each loaded term in the text, with a short raw key (to follow it) and a readable sentence."""
    found = []
    for term, (side, rx) in LOADED.items():
        for m in rx.finditer(text):
            key = text[max(0, m.start() - CONTEXT): m.end()]
            start = max(text.rfind(". ", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
            end_dot = text.find(". ", m.end())
            end_nl = text.find("\n", m.end())
            end = min(x for x in (end_dot, end_nl, len(text)) if x != -1)
            sentence = clean_inline(text[start:end + 1])[:300]
            # Book titles in citation templates and quotations are legitimate uses of the term:
            # flag them so the review list starts with the article's own wording.
            in_template = text.rfind("{{", 0, m.start()) > text.rfind("}}", 0, m.start())
            in_quotes = sum(text[start:m.start()].count(q) for q in QUOTES) % 2 == 1
            found.append({"term": term, "side": side, "word": m.group(0), "key": key, "sentence": sentence,
                          "in_citation": in_template, "in_quotes": in_quotes,
                          "own_wording": not (in_template or in_quotes)})
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="parquet files")
    args = parser.parse_args()

    versions = Counter()
    for path in args.inputs:
        versions.update(pq.read_table(path, columns=["page_id"])["page_id"].to_pylist())

    # Pass 1: the passages present in the last version of each article.
    last = {}
    for row in iter_versions(args.inputs, None):
        last[row["page_id"]] = {"title": row["title"], "text": row["text"] or ""}
    follow = {pid: passages(v["text"]) for pid, v in last.items()}
    follow = {pid: ps for pid, ps in follow.items() if ps}
    titles = {pid: last[pid]["title"] for pid in follow}
    del last

    # Pass 2: for each passage, the start of its current unbroken run.
    run_start = {}
    for row in iter_versions(args.inputs, sorted(follow)):
        text = row["text"] or ""
        for i, p in enumerate(follow[row["page_id"]]):
            k = (row["page_id"], i)
            if p["key"] in text:
                run_start.setdefault(k, (row["rev_id"], row["timestamp"]))
            else:
                run_start.pop(k, None)

    items = []
    for pid, ps in follow.items():
        for i, p in enumerate(ps):
            rev, since = run_start.get((pid, i), (None, None))
            items.append({
                "page_id": pid, "title": titles[pid], "term": p["term"], "side": p["side"], "word": p["word"],
                "own_wording": p["own_wording"], "in_citation": p["in_citation"], "in_quotes": p["in_quotes"],
                "sentence": p["sentence"], "since": since.strftime("%Y-%m-%d") if since else None,
                "since_rev_id": rev, "days_online": round((DATA_END - since).days) if since else None,
                "article_versions": versions[pid],
                "links": {"since": f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={rev}" if rev else None},
            })
    # Quiet articles first: fewer versions means fewer people watching.
    items.sort(key=lambda x: (not x["own_wording"], x["article_versions"], -(x["days_online"] or 0)))
    result = {
        "items": items,
        "summary": {
            "occurrences": len(items), "articles": len(follow),
            "by_term": dict(Counter(x["term"] for x in items)),
            "own_wording": sum(x["own_wording"] for x in items),
            "articles_under_200_versions": len({x["page_id"] for x in items if x["article_versions"] < 200}),
        },
        "notes": {"state": f"last version of each article in the data (data ends {DATA_END:%Y-%m-%d})",
                  "since": "first version of the current unbroken presence of this exact passage",
                  "caution": "a loaded term can be legitimate (a quotation, a book title, a section about the "
                             "names of the war): this is a list to review, not a list of manipulations"},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(result["summary"], ensure_ascii=False))
    for x in items[:25]:
        print(f"{x['title'][:28]:28} v={x['article_versions']:<5} {x['word']:<18} since {x['since']} "
              f"({x['days_online']} d) | {x['sentence'][:110]}")


if __name__ == "__main__":
    main()
