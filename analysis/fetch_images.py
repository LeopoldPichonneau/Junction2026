"""Get thumbnail, author and license of every image found by find_candidates.py (step 2).

For each image file named in data/exchange/candidates.jsonl, asks the Wikipedia API
(batches of 50 titles, descriptive User-Agent from .env) and:
  1. appends one line per file to data/exchange/images.jsonl (a cache: files already
     there are not asked again, so the script can be stopped and restarted);
  2. fills image.thumb_url, image.author and image.license in candidates.jsonl.

Usage (from the repository root):
    python analysis/fetch_images.py --page-id 1150
    python analysis/fetch_images.py
With USE_MOCK=true in .env, no request is sent and realistic fake answers are used.
"""

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

from env import load_env, use_mock

API_URL = "https://fi.wikipedia.org/w/api.php"
CANDIDATES = "data/exchange/candidates.jsonl"
IMAGES = "data/exchange/images.jsonl"
BATCH = 50              # API limit for titles per request
PAUSE_SECONDS = 0.5     # stay well below "a few requests per second" (TECH.md section 9)


def wiki_api(params: dict) -> dict:
    """The only function that talks to Wikimedia. Retries politely on 429 / 5xx."""
    if use_mock():
        return mock_answer(params)
    headers = {"User-Agent": os.environ["WIKI_USER_AGENT"]}
    for attempt in range(4):
        r = httpx.get(API_URL, params=params, headers=headers, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After", "0") or 0) or 5 * (attempt + 1)
            print(f"  HTTP {r.status_code}, waiting {wait} s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Wikipedia API keeps refusing: stop and try again later")


def mock_answer(params: dict) -> dict:
    pages = []
    for title in params["titles"].split("|"):
        name = title.split(":", 1)[1]
        pages.append({"ns": 6, "title": title, "missing": True, "known": True, "imagerepository": "shared",
                      "imageinfo": [{"thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/{name}/800px-{name}",
                                     "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
                                     "extmetadata": {"Artist": {"value": "<a href=\"#\">Mock Photographer</a>"},
                                                     "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]})
    return {"query": {"pages": pages}}


def plain_text(value: str | None) -> str | None:
    """extmetadata values are HTML snippets: keep only the readable text."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()
    return text[:200] or None


def without_tracking(url: str | None) -> str | None:
    # The API adds ?utm_source=... to every link; the bare URL works the same.
    return url.split("?utm_", 1)[0] if url else None


def fetch_batch(files: list[str]) -> list[dict]:
    titles = {f"Tiedosto:{f}": f for f in files}
    data = wiki_api({"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                     "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "800",
                     "iiextmetadatafilter": "Artist|Credit|LicenseShortName|LicenseUrl",
                     "titles": "|".join(titles)})
    query = data.get("query", {})
    # Follow the API's renames so each answer finds the file name we asked for.
    final = {t: t for t in titles}
    for step in query.get("normalized", []) + query.get("redirects", []):
        for t, current in final.items():
            if current == step["from"]:
                final[t] = step["to"]
    pages = {p["title"]: p for p in query.get("pages", [])}

    records = []
    for title, name in titles.items():
        page = pages.get(final[title], {})
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        records.append({
            "file": name,
            # "missing" alone only means "no local page": files on Commons still have imageinfo.
            "found": bool(info),
            "thumb_url": without_tracking(info.get("thumburl")),
            "description_url": info.get("descriptionurl"),
            # Old public-domain photos often have no Artist; Credit then names the source.
            "author": plain_text(meta.get("Artist", {}).get("value"))
                      or plain_text(meta.get("Credit", {}).get("value")),
            "credit": plain_text(meta.get("Credit", {}).get("value")),
            "license": plain_text(meta.get("LicenseShortName", {}).get("value")),
            "license_url": meta.get("LicenseUrl", {}).get("value"),
        })
    return records


def read_jsonl(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def update_candidates(path: str, cache: dict[str, dict]) -> int:
    """Write the image info into candidates.jsonl (via a temporary file, so a crash keeps the old one)."""
    rows, filled = read_jsonl(path), 0
    for row in rows:
        img = row.get("image")
        if img and img["file"] in cache:
            info = cache[img["file"]]
            img["thumb_url"] = info["thumb_url"]
            img["author"] = info["author"]
            img["license"] = info["license"]
            filled += bool(info["thumb_url"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return filled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", default=CANDIDATES)
    parser.add_argument("--images", default=IMAGES)
    parser.add_argument("--page-id", type=int, action="append", help="only images of these articles")
    args = parser.parse_args()
    load_env()
    if use_mock():
        # Fake answers must never end up in the real cache or in candidates.jsonl.
        args.images = args.images.replace(".jsonl", "-mock.jsonl")
    elif not os.environ.get("WIKI_USER_AGENT"):
        sys.exit("WIKI_USER_AGENT is missing from .env (without it Wikimedia answers 429).")

    candidates = read_jsonl(args.candidates)
    wanted = []
    for row in candidates:
        if row.get("image") and (not args.page_id or row["page_id"] in args.page_id):
            if row["image"]["file"] not in wanted:
                wanted.append(row["image"]["file"])
    cache = {r["file"]: r for r in read_jsonl(args.images)}
    todo = [f for f in wanted if f not in cache]
    print(f"{len(wanted)} image files, {len(wanted) - len(todo)} already in {args.images}, {len(todo)} to ask"
          + (" (MOCK)" if use_mock() else ""))

    with open(args.images, "a", encoding="utf-8") as out:
        for start in range(0, len(todo), BATCH):
            for record in fetch_batch(todo[start:start + BATCH]):
                cache[record["file"]] = record
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()     # a crash later on keeps the batches already answered
            print(f"  {min(start + BATCH, len(todo))}/{len(todo)}")
            time.sleep(PAUSE_SECONDS)

    got = [cache[f] for f in wanted]
    print(f"Found: {sum(r['found'] for r in got)}/{len(got)} · with author: {sum(bool(r['author']) for r in got)}"
          f" · with license: {sum(bool(r['license']) for r in got)}")
    if use_mock():
        print(f"MOCK: {args.candidates} left untouched")
        return
    filled = update_candidates(args.candidates, cache)
    print(f"{args.candidates}: thumb_url filled on {filled} lines")


if __name__ == "__main__":
    main()
