"""English titles of the articles, so the Time machine can be searched in English.

The English title is the one Wikipedia itself gives: the title of the English Wikipedia article
linked to the Finnish one (language links). Nothing is machine-translated, and an article with
no English counterpart simply has no English title.

Writes data/exchange/titles-en.jsonl: {"page_id": ..., "title": ..., "title_en": ...}, one line
per article that has an English title (written batch by batch; a rerun skips what is done).

Usage (from the repository root):
    python analysis/english_titles.py data/versions-*.parquet
With USE_MOCK=true nothing is sent: fake titles, written to titles-en-mock.jsonl.
"""

import argparse
import json
import time
from pathlib import Path

import pyarrow.dataset as ds

from env import load_env, use_mock
from fetch_images import wiki_api          # the only function that talks to Wikimedia

OUT = "data/exchange/titles-en.jsonl"
BATCH = 50              # API limit for titles per request
PAUSE_SECONDS = 0.3     # stay well below "a few requests per second" (TECH.md section 9)


def article_titles(paths: list[str]) -> dict[int, str]:
    """{page_id: current title} (the title of the last version of each article)."""
    titles = {}
    for batch in ds.dataset(paths, format="parquet").to_batches(columns=["page_id", "title"], batch_size=50_000):
        for page_id, title in zip(batch.column("page_id").to_pylist(), batch.column("title").to_pylist()):
            titles[page_id] = title
    return titles


def english_for(titles: list[str]) -> dict[str, str]:
    """{Finnish title: English title} for one batch, following renames and redirects."""
    if use_mock():
        return {t: f"[EN] {t}" for t in titles}
    params = {"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
              "prop": "langlinks", "lllang": "en", "lllimit": "500", "titles": "|".join(titles)}
    found, moves = {}, []
    for _ in range(10):                      # long answers come in several parts
        data = wiki_api(params)
        part = data.get("query", {})
        moves += part.get("normalized", []) + part.get("redirects", [])
        for page in part.get("pages", []):
            for link in page.get("langlinks", []):
                found[page["title"]] = link["title"]
        if "continue" not in data:
            break
        params = {**params, **data["continue"]}
    final = {t: t for t in titles}           # the API answers under the title it ended on
    for step in moves:
        for asked, current in final.items():
            if current == step["from"]:
                final[asked] = step["to"]
    return {asked: found[now] for asked, now in final.items() if now in found}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="parquet files")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    load_env()
    out_path = args.out.replace(".jsonl", "-mock.jsonl") if use_mock() else args.out

    titles = article_titles(args.inputs)
    asked_path = Path(out_path + ".asked")   # page ids already asked, with or without an English title
    asked = set(json.loads(asked_path.read_text())) if asked_path.exists() else set()
    todo = [(pid, t) for pid, t in sorted(titles.items()) if pid not in asked]
    print(f"{len(titles):,} articles, {len(asked):,} already asked, {len(todo):,} to ask" + (" (MOCK)" if use_mock() else ""))
    written = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            english = english_for([t for _, t in batch])
            for pid, title in batch:
                if title in english:
                    out.write(json.dumps({"page_id": pid, "title": title, "title_en": english[title]}, ensure_ascii=False) + "\n")
                    written += 1
            out.flush()
            asked.update(pid for pid, _ in batch)
            asked_path.write_text(json.dumps(sorted(asked)))
            if (i // BATCH) % 40 == 0:
                print(f"  {i + len(batch):,} asked, {written:,} English titles so far")
            if not use_mock():
                time.sleep(PAUSE_SECONDS)
    print(f"done: {written:,} new English titles -> {out_path}")


if __name__ == "__main__":
    main()
