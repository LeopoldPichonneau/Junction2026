"""Build the TimeProof Lens bookmarklet from the pipeline's exchange files.

The Lens cannot call our server (HTTPS Wikipedia page -> HTTP VPS is blocked as mixed content),
so the published cases are inlined into the bookmark itself.

Usage (from the repository root):
    python lens/build_bookmarklet.py                                   # real files in data/exchange/
    python lens/build_bookmarklet.py --analysis lens/mock/analysis.mock.jsonl \
        --decisions lens/mock/decisions.mock.jsonl                     # mock data, labelled "Sample data"
    python lens/build_bookmarklet.py --site http://<vps-address>       # where "Read the evidence" points

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


def build_cases(analysis: list[dict], decisions: list[dict], pages: set[int] | None, stats: dict) -> list[dict]:
    by_rev = {row["rev_id"]: row for row in analysis}
    cases = []
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
        kind = "image" if a.get("kind") == "image" and image.get("file") else "text"
        # Copy only what the Lens shows: nothing else (never an account) can leak into the bookmark.
        cases.append({
            "rev_id": a["rev_id"],
            "page_id": a.get("page_id"),
            "kind": kind,
            "file": image.get("file") if kind == "image" else None,
            "text": (a.get("added") or "")[:400] if kind == "text" else None,
            "headline": d.get("headline_en") or "",
            "date": (a.get("timestamp") or exposure.get("live_from") or "")[:10],
            "days": exposure.get("days_live") or 0,
            "readers": exposure.get("readers_est"),
            "online": bool(exposure.get("still_online", exposure.get("live_until") is None)),
            "readers_sort": exposure.get("readers_est") or 0,
        })
    cases.sort(key=lambda c: (c["readers_sort"], c["days"]), reverse=True)
    for c in cases:
        del c["readers_sort"]
    return cases[:MAX_CASES]


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
    cases = build_cases(analysis, decisions, pages, stats)

    data = {"mock": mock, "site": args.site, "built": date.today().isoformat(), "cases": cases}
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
        "<a href=\"https://fi.wikipedia.org/wiki/Suomen_sis%C3%A4llissota\">Suomen sis&auml;llissota</a>, and click the bookmark.</li>\n"
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
