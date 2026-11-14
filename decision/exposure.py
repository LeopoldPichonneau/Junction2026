"""Exposure score: how long a suspicious version stayed online, and roughly how many readers saw it.

Reads  data/exchange/decisions.jsonl + analysis.jsonl, and data/versions-XX.parquet
Writes data/exchange/exposure.jsonl, then adds an "exposure" field to every matching line of
       decisions.jsonl (rewritten in one go). Run it AFTER decide.py has finished.

    python decision/exposure.py

When does a case end? At the first later version where
  - the text goes back to exactly what it was before the edit (same sha1 = a revert), or
  - the suspicious content, as it appears in the suspect version itself, is gone:
      image   : that caption / that file is no longer there (or the removed file is back)
      sources : the number of <ref> is back to at least what it was before the edit
      framing, coordination : fewer than half of the words whose count this edit raised keep that count
If neither happens, the case is "still online" up to the end of the dataset (2026-10-01).
If our parser cannot see the change in the suspect version, only a revert ends it ("tracked_by": "revert only").

Readers are a ceiling (views of the whole article during that time, "≈"), use the article title
of each period (articles get renamed), and are null before July 2015 (no pageview data).
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import config
from dataio import iter_versions, read_jsonl, write_atomic

IMAGE_PREFIX = re.compile(r"\[\[\s*(Tiedosto|Kuva|File|Image)\s*:", re.I)
REF = re.compile(r"<ref[\s>]", re.I)
WORD = re.compile(r"\w{4,}", re.UNICODE)  # short words are too common to prove anything
MISSING = object()


def images(text: str) -> dict[str, str]:
    """{file name: caption}; captions can hold [[links]], so brackets are counted (same as analysis/)."""
    out, i = {}, 0
    while m := IMAGE_PREFIX.search(text, i):
        depth, j = 0, m.start()
        while j < len(text) - 1:
            if text.startswith("[[", j):
                depth += 1
                j += 2
            elif text.startswith("]]", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        parts = text[m.end():j - 2].split("|")
        name = norm_file(parts[0])
        if name:
            out[name] = parts[-1].strip() if len(parts) > 1 else ""
        i = j
    return out


def norm_file(name: str | None) -> str:
    name = (name or "").strip().replace("_", " ")
    return name[:1].upper() + name[1:]


def norm_caption(text: str | None) -> str:
    return " ".join((text or "").split())


def words(text: str | None) -> set[str]:
    return {w.lower() for w in WORD.findall(text or "")}


def word_counts(text: str, tracked: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for w in WORD.findall(text):
        w = w.lower()
        if w in tracked:
            counts[w] = counts.get(w, 0) + 1
    return counts


# ---------- pageviews (the only external call in this file) ----------

def fetch_daily_views(title: str) -> dict[str, int]:
    """{'YYYYMMDD': views} for the whole period with data, cached on disk per title."""
    folder = config.CACHE / ("pageviews-mock" if config.USE_MOCK else "pageviews")
    path = folder / (hashlib.sha1(title.encode()).hexdigest()[:16] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["views"]

    if config.USE_MOCK:
        # Plausible daily numbers (a few hundred), stable per title, clearly not real.
        seed = int(hashlib.sha1(title.encode()).hexdigest()[:6], 16)
        day, views = config.PAGEVIEWS_START, {}
        while day < config.DATASET_END:
            views[day.strftime("%Y%m%d")] = 100 + (seed + day.toordinal() * 37) % 400
            day += timedelta(days=1)
    else:
        import httpx

        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/fi.wikipedia/"
               f"all-access/user/{quote(title.replace(' ', '_'), safe='')}/daily/"
               f"{config.PAGEVIEWS_START:%Y%m%d}00/{config.DATASET_END:%Y%m%d}00")
        r = httpx.get(url, headers={"User-Agent": config.WIKI_USER_AGENT}, timeout=60)
        if r.status_code == 404:  # no views recorded under this title (e.g. an old name)
            views = {}
        else:
            r.raise_for_status()
            views = {item["timestamp"][:8]: item["views"] for item in r.json().get("items", [])}

    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"title": title, "views": views}), encoding="utf-8")
    return views


def views_between(series: dict[str, int], a: datetime, b: datetime) -> float:
    """Views from a to b, counting partial first and last days pro rata."""
    total, day = 0.0, datetime(a.year, a.month, a.day, tzinfo=timezone.utc)
    while day < b:
        nxt = day + timedelta(days=1)
        overlap = (min(b, nxt) - max(a, day)).total_seconds()
        if overlap > 0:
            total += series.get(day.strftime("%Y%m%d"), 0) * overlap / 86400
        day = nxt
    return total


# ---------- per-case presence checks ----------

def features(case: dict, text: str):
    """The small piece of each version we keep for one case (we never keep whole texts)."""
    kind, image = case.get("kind"), case.get("image")
    if kind == "image" and image:
        return images(text).get(norm_file(image.get("file")), MISSING)
    if kind == "sources":
        return len(REF.findall(text))
    return word_counts(text, case["_words"])


def make_check(case: dict, before, at_edit):
    """Build the "is the suspicious content still there?" test, anchored on the suspect version
    itself as our own parser reads it (not on analysis/'s strings, which may be cleaned differently).
    Returns None when the suspect version does not show the change: then only a revert ends the case."""
    kind, image = case.get("kind"), case.get("image")
    if kind == "image" and image:
        if image.get("change") == "removed":
            if at_edit is not MISSING:
                return None
            return lambda now: now is MISSING
        if at_edit is MISSING:  # e.g. an image inside an infobox, which our parser does not see
            return None
        if image.get("change") == "recaptioned":
            caption = norm_caption(at_edit)
            return lambda now: now is not MISSING and norm_caption(now) == caption
        return lambda now: now is not MISSING  # added / swapped: the new file is still shown
    if kind == "sources":
        if before is None or at_edit >= before:
            return None
        return lambda now: now < before
    before = before or {}
    # Words whose count went up with this edit; a word that was already there is tracked by count.
    introduced = {w: n for w, n in at_edit.items() if n > before.get(w, 0)}
    if not introduced:
        return None
    return lambda now: sum(now.get(w, 0) >= n for w, n in introduced.items()) * 2 >= len(introduced)


def exposure_for(case: dict, versions: list[tuple]) -> dict:
    """versions: [(timestamp, rev_id, title, sha1, {rev_id: feature}), ...] sorted by time."""
    rev = case["rev_id"]
    k = next((i for i, v in enumerate(versions) if v[1] == rev), None)
    if k is None:
        return {"error": "revision not found in the parquet files"}
    parent = versions[k - 1] if k > 0 else None
    before = parent[4].get(rev) if parent else None
    start = versions[k][0]
    still_there = make_check(case, before, versions[k][4].get(rev))

    end_index, end = None, config.DATASET_END
    for j in range(k + 1, len(versions)):
        v = versions[j]
        if (parent and v[3] == parent[3]) or (still_there and not still_there(v[4].get(rev))):
            end_index, end = j, v[0]
            break

    # Title of each period, because pageviews are counted per title.
    last = end_index if end_index is not None else len(versions)
    periods = []
    for j in range(k, last):
        a = versions[j][0]
        b = versions[j + 1][0] if j + 1 < len(versions) else config.DATASET_END
        b = min(b, end)
        if periods and periods[-1][0] == versions[j][2]:
            periods[-1][2] = b
        else:
            periods.append([versions[j][2], a, b])

    readers = None
    if end > config.PAGEVIEWS_START:
        readers = 0.0
        for title, a, b in periods:
            a = max(a, config.PAGEVIEWS_START)
            if b > a:
                readers += views_between(fetch_daily_views(title), a, b)

    return {
        "live_from": start.date().isoformat(),
        "live_until": None if end_index is None else end.date().isoformat(),
        "still_online": end_index is None,
        "days_live": round((end - start).total_seconds() / 86400, 1),
        "readers_est": None if readers is None else int(round(readers)),
        "readers_partial": readers is not None and start < config.PAGEVIEWS_START,
        "ended_by": None if end_index is None else
        ("revert" if parent and versions[end_index][3] == parent[3] else "content removed"),
        # "revert only" = the change was not visible to our parser, so only an exact revert can end
        # the case: days and readers may be overestimated. Shown so nobody quotes it blindly.
        "tracked_by": "content" if still_there else "revert only",
        "titles": sorted({p[0] for p in periods}),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--decisions", default=str(config.exchange_file("decisions.jsonl")))
    p.add_argument("--analysis", default=str(config.EXCHANGE / "analysis.jsonl"))
    p.add_argument("--all", action="store_true", help="also compute dismissed cases (more pageview calls)")
    p.add_argument("--no-merge", action="store_true", help="only write exposure.jsonl")
    args = p.parse_args()

    from pathlib import Path
    decisions = list(read_jsonl(Path(args.decisions)))
    if not decisions:
        raise SystemExit(f"No decisions in {args.decisions}. Run decide.py first.")
    wanted = {d["rev_id"] for d in decisions
              if not d.get("synthetic") and (args.all or d.get("decision") != "dismiss")}
    cases = {c["rev_id"]: c for c in read_jsonl(Path(args.analysis)) if c.get("rev_id") in wanted}
    missing = wanted - cases.keys()
    if missing:
        print(f"  {len(missing)} decisions have no line in {Path(args.analysis).name}; skipped")

    by_page: dict[int, list[dict]] = defaultdict(list)
    for c in cases.values():
        c["_words"] = words(c.get("added"))
        by_page[c["page_id"]].append(c)
    print(f"{'MOCK' if config.USE_MOCK else 'REAL'} run: {len(cases)} cases on {len(by_page)} articles")

    pages: dict[int, list[tuple]] = defaultdict(list)
    cols = ["page_id", "title", "rev_id", "timestamp", "sha1", "text"]
    for row in iter_versions(cols, set(by_page)):
        text = row["text"] or ""
        feats = {c["rev_id"]: features(c, text) for c in by_page[row["page_id"]]}
        pages[row["page_id"]].append((row["timestamp"], row["rev_id"], row["title"], row["sha1"], feats))

    results = {}
    for page_id, page_cases in by_page.items():
        versions = sorted(pages.get(page_id, []), key=lambda v: (v[0], v[1]))
        for c in page_cases:
            try:
                results[c["rev_id"]] = exposure_for(c, versions)
            except Exception as e:  # e.g. pageviews API down: keep going, report it on the case
                results[c["rev_id"]] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            e = results[c["rev_id"]]
            print(f"  {c['rev_id']}: " + (e.get("error") or
                  f"{e['days_live']} days, ≈{e['readers_est']} readers, "
                  f"{'still online' if e['still_online'] else 'ended by ' + e['ended_by']}"))

    write_atomic(config.exchange_file("exposure.jsonl"),
                 ({"rev_id": r, "exposure": e} for r, e in results.items()))
    if not args.no_merge:
        for d in decisions:
            if d["rev_id"] in results:
                d["exposure"] = results[d["rev_id"]]
        write_atomic(Path(args.decisions), decisions)
        print(f"Added exposure to {len(results)} lines of {Path(args.decisions).name}")


if __name__ == "__main__":
    main()
