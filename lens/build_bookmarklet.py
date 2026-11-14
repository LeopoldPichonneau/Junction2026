"""Build the TimeProof Lens bookmarklet from the pipeline's exchange files.

The Lens cannot call our server (HTTPS Wikipedia page -> HTTP VPS is blocked as mixed content),
so the published cases are inlined into the bookmark itself.

Usage (from the repository root):
    python lens/build_bookmarklet.py                                   # real files in data/exchange/
    python lens/build_bookmarklet.py --analysis lens/mock/analysis.mock.jsonl \
        --decisions lens/mock/decisions.mock.jsonl                     # mock data, labelled "Sample data"
    python lens/build_bookmarklet.py --site http://<vps-address>       # where "Read the evidence" points
    python lens/build_bookmarklet.py --site https://<site> --check-live  # keep only what today's pages show

Each case carries short "needles": the suspicious text if it is still online, otherwise the text the
edit had removed (it came back when the edit was undone). The bookmark also counts every published
case per article, so the Lens can say how many it could not outline. Wikipedia's CSP blocks any call
to our server from its pages, which is why the data is inlined rather than fetched from the API.

Outputs: lens/bookmarklet.txt (paste as a bookmark URL), lens/install.html (drag the link
to the bookmarks bar) and web/lens.json (the site's Lens page offers the same bookmark). Standard library only.
"""

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PLACEHOLDER = "/*__TIMEPROOF_DATA__*/ null"
# A bookmark that is too long can be truncated by the browser: keep the inlined data small.
MAX_CASES = 40
WARN_LENGTH = 30_000


def read_jsonl(path: Path, stats: dict, label: str) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped"].append(f"{label} line {n}: not valid JSON")
                continue
            if not isinstance(row, dict) or "rev_id" not in row:
                stats["skipped"].append(f"{label} line {n}: no rev_id")
                continue
            rows.append(row)
    return rows


NEEDLE_MIN_WORDS = 5     # under 5 words a match on a long article is too likely to be a coincidence
NEEDLE_MAX_WORDS = 10    # a prefix of a passage matches wherever the passage does: keeps the bookmark short
MAX_NEEDLES = 2


def plain(text: str) -> str:
    """Wikitext fragment -> the words a reader sees on the page."""
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", " ", text, flags=re.S)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)      # [[target|label]] -> label
    text = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|'{2,}|={2,}|^\s*[*#:;]+", " ", text, flags=re.M)
    return re.sub(r"\s+", " ", html.unescape(text).replace(" ", " ")).strip()


# ---------- Optional check against today's Wikipedia (--check-live) ----------
UA = "TimeProofBot/0.1 (https://hackjunction.com; Junction 2026 hackathon prototype)"


def live_text(title: str, cache: dict) -> str | None:
    """Today's article as a reader sees it (lower-case, references dropped), or None if unreachable."""
    if title not in cache:
        from urllib.request import Request, urlopen
        url = "https://fi.wikipedia.org/api/rest_v1/page/html/" + quote(title.replace(" ", "_"), safe="")
        try:
            page = urlopen(Request(url, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8")
        except Exception as e:      # the Lens still works without the check: keep the case unverified
            print(f"  live check skipped for {title}: {e}", file=sys.stderr)
            cache[title] = None
            return None
        page = re.sub(r'<sup[^>]*class="[^"]*reference[^"]*"[^>]*>.*?</sup>', " ", page, flags=re.S)
        files = " ".join(re.findall(r'(?:Tiedosto|File|Kuva):([^"#?]+)', page))
        body = html.unescape(re.sub(r"<[^>]+>", " ", page)).replace(" ", " ")
        cache[title] = re.sub(r"\s+", " ", body).lower() + " " + unquote(files).replace("_", " ").lower()
    return cache[title]


def keep_located(cases: list[dict], titles: dict, stats: dict) -> list[dict]:
    """Keep only the needles found on today's page; drop cases with nothing left to outline."""
    cache, kept = {}, []
    for c in cases:
        text = live_text(titles[c["rev_id"]], cache)
        if text is None:
            kept.append(c)
            continue
        c["needles"] = [n for n in c["needles"] if n in text]
        has_file = bool(c["file"]) and c["file"].replace("_", " ").lower() in text
        if not c["needles"] and not has_file:
            stats["dropped"].append(f"rev {c['rev_id']}: nothing left on today's page")
            continue
        kept.append(c)
    return kept


def needles(text: str | None) -> list[str]:
    """Distinctive passages to look for on today's page, longest first, lower-cased."""
    if not text:
        return []
    parts = [plain(p) for p in re.split(r"\s*(?:…|\.\.\.)\s*", text)]
    sentences = [s for p in parts for s in re.split(r"(?<=[.!?])\s+", p)]
    out = []
    for frag in sorted(set(parts + sentences), key=len, reverse=True):
        words = frag.lower().split()
        if len(words) < NEEDLE_MIN_WORDS:
            continue
        short = " ".join(words[:NEEDLE_MAX_WORDS])
        if not any(short in o or o in short for o in out):
            out.append(short)
        if len(out) == MAX_NEEDLES:
            break
    return out


def build_cases(analysis: list[dict], decisions: list[dict], pages: set[int] | None, stats: dict) -> tuple[list[dict], dict, dict]:
    by_rev = {row["rev_id"]: row for row in analysis}
    cases = []
    totals: dict[int, int] = {}
    titles: dict[int, str] = {}
    for d in decisions:
        a = by_rev.get(d["rev_id"])
        if a is None:
            stats["skipped"].append(f"rev {d['rev_id']}: decision without analysis line")
            continue
        # Same public filter as the API: flagged, publishable, never the synthetic test campaign.
        if d.get("decision") != "flag" or d.get("publish") is not True:
            stats["dropped"].append(f"rev {d['rev_id']}: decision={d.get('decision')} publish={d.get('publish')}")
            continue
        if a.get("synthetic"):
            stats["dropped"].append(f"rev {d['rev_id']}: synthetic test case")
            continue
        if pages and a.get("page_id") not in pages:
            continue
        exposure = d.get("exposure") or {}
        image = a.get("image") or {}
        online = bool(exposure.get("still_online", exposure.get("live_until") is None))
        totals[a.get("page_id")] = totals.get(a.get("page_id"), 0) + 1
        titles[a["rev_id"]] = a.get("title") or ""
        # Still online: the suspicious text is on today's page. Undone: the edit was reverted, so
        # what it removed is back. The Lens says which of the two it outlines.
        side = "added" if online else "removed"
        kind = "image" if image.get("file") else "text"
        found = needles(a.get(side))
        if kind == "image":
            found = needles(image.get("caption_new" if online else "caption_old")) + found
        if kind == "text" and not found:
            stats["dropped"].append(f"rev {d['rev_id']}: nothing distinctive to find on today's page")
            continue
        # Copy only what the Lens shows: nothing else (never an account) can leak into the bookmark.
        cases.append({
            "rev_id": a["rev_id"],
            "page_id": a.get("page_id"),
            "kind": kind,
            "side": side,
            "file": image.get("file") if kind == "image" else None,
            "needles": found[:MAX_NEEDLES],
            "headline": d.get("headline_en") or "",
            "date": (a.get("timestamp") or exposure.get("live_from") or "")[:10],
            "days": round(exposure.get("days_live") or 0, 2),
            "readers": exposure.get("readers_est"),
            "online": online,
            "readers_sort": exposure.get("readers_est") or 0,
        })
    cases.sort(key=lambda c: (c["readers_sort"], c["days"]), reverse=True)
    for c in cases:
        del c["readers_sort"]
    return cases, totals, titles


def strip_comments(js: str) -> str:
    """Drop // comments (the source has no '//' inside strings) and blank lines."""
    out = []
    for line in js.splitlines():
        line = re.sub(r"(^|\s)//.*$", "", line).rstrip()
        if line.strip():
            out.append(line.strip())
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analysis", type=Path, default=ROOT / "data/exchange/analysis.jsonl")
    ap.add_argument("--decisions", type=Path, default=ROOT / "data/exchange/decisions.jsonl")
    ap.add_argument("--site", default="http://localhost:5500", help="base URL of the TimeProof site")
    ap.add_argument("--pages", default="", help="comma-separated page_ids to keep (demo articles), default all")
    ap.add_argument("--check-live", action="store_true",
                    help="read today's articles on fi.wikipedia.org and keep only what the Lens can outline")
    args = ap.parse_args()

    for p in (args.analysis, args.decisions):
        if not p.exists():
            print(f"Missing file: {p}", file=sys.stderr)
            return 1

    mock = "mock" in args.analysis.name.lower() or "mock" in args.decisions.name.lower()
    pages = {int(x) for x in args.pages.split(",") if x.strip()} or None
    stats = {"skipped": [], "dropped": []}
    analysis = read_jsonl(args.analysis, stats, args.analysis.name)
    decisions = read_jsonl(args.decisions, stats, args.decisions.name)
    cases, totals, titles = build_cases(analysis, decisions, pages, stats)
    if args.check_live:
        cases = keep_located(cases, titles, stats)
    cases = cases[:MAX_CASES]

    # "totals" = every published case per article, so the panel can say how many it could not locate.
    data = {"mock": mock, "site": args.site, "built": date.today().isoformat(), "cases": cases,
            "totals": {str(k): v for k, v in totals.items()}}
    source = (HERE / "lens.js").read_text(encoding="utf-8")
    if PLACEHOLDER not in source:
        print("Placeholder not found in lens.js", file=sys.stderr)
        return 1
    # ensure_ascii keeps the bookmark pure ASCII (Finnish letters become \u escapes).
    code = strip_comments(source.replace(PLACEHOLDER, json.dumps(data, ensure_ascii=True, separators=(",", ":"))))

    # Percent-encode what a URL cannot carry (%, #, spaces, newlines, quotes...).
    encoded = quote(code, safe="()[]{};,=:!*+-./?&<>|~_$@'^")
    bookmarklet = "javascript:" + encoded
    if unquote(encoded) != code:
        print("Encoding round trip failed", file=sys.stderr)
        return 1

    (HERE / "bookmarklet.txt").write_text(bookmarklet, encoding="ascii")
    (HERE / "install.html").write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Install TimeProof Lens</title>\n</head>\n"
        "<body style=\"font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#1c1d22\">\n"
        "<h1 style=\"font-family:Georgia,serif\">Install the TimeProof Lens</h1>\n"
        "<ol>\n<li>Show the bookmarks bar (Ctrl+Shift+B).</li>\n"
        "<li>Drag this button onto the bookmarks bar:</li>\n</ol>\n"
        f"<p><a href=\"{html.escape(bookmarklet, quote=True)}\" style=\"display:inline-block;background:#3687eb;color:#fff;"
        "font-weight:600;padding:10px 20px;border-radius:999px;text-decoration:none\">TimeProof Lens</a></p>\n"
        "<ol start=\"3\">\n<li>Open a Finnish Wikipedia article, for example "
        "<a href=\"https://fi.wikipedia.org/wiki/Vuosaari\">Vuosaari</a>, and click the bookmark.</li>\n"
        "<li>Click it again to turn the Lens off.</li>\n</ol>\n"
        + ("<p style=\"background:#2b2d33;color:#ffd84d;padding:8px 12px;border-radius:6px;font-weight:600\">"
           "This build uses sample data: not real findings.</p>\n" if mock else "")
        + "</body>\n</html>\n",
        encoding="utf-8",
    )

    # The site's Lens page reads this file to offer the same bookmark (web/ is what gets deployed).
    (ROOT / "web" / "lens.json").write_text(
        json.dumps({"href": bookmarklet, "mock": mock, "built": data["built"], "cases": len(cases)}, ensure_ascii=True),
        encoding="ascii",
    )

    print(f"Read {len(analysis)} analysis lines, {len(decisions)} decisions.")
    print(f"Kept {len(cases)} published case(s){' (MOCK data)' if mock else ''}, site = {args.site}")
    for reason in stats["dropped"]:
        print("  dropped:", reason)
    for reason in stats["skipped"]:
        print("  skipped:", reason)
    print(f"Bookmarklet length: {len(bookmarklet):,} characters -> lens/bookmarklet.txt, lens/install.html, web/lens.json")
    if len(bookmarklet) > WARN_LENGTH:
        print("  warning: long bookmark, some browsers may truncate it; keep fewer cases (--pages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
