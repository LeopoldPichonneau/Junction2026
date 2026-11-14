"""Visual evidence made by Cloudinary (Cloudinary challenge).

1. Archive (--archive, needs the API keys). For each published image case, this script:
   - downloads the picture as it was on the day of the edit, and for a replaced picture the one
     that was there before (with our descriptive User-Agent: Wikimedia refuses servers that
     fetch by themselves, Cloudinary's fetch included);
   - uploads them to Cloudinary with the evidence as metadata (rev_id, article, date, side,
     caption, author, license) and tags, so the media library itself is a searchable archive;
   - keeps the perceptual hash (pHash) Cloudinary computes, to recognise the same picture
     under another file name.

2. Before / after (--compare, needs the cloud name only: no file is sent). For each archived
   image case, builds the two sides of a slider: the picture before and the picture after, at
   the same size and framing, each with the caption Wikipedia showed at that time.

Writes data/exchange/cloudinary.jsonl (one line per case and per step, written as soon as it
is done; the server merges the lines of a case, the last value of each field wins).

Usage (from the repository root):
    python analysis/cloudinary_cards.py --archive                 # every published image case
    python analysis/cloudinary_cards.py --compare                 # before / after pictures
    python analysis/cloudinary_cards.py --archive --compare --rev-id 24139572   # one case
.env: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET (or CLOUDINARY_URL).
With USE_MOCK=true nothing is sent: fake answers, written to cloudinary-mock.jsonl.
"""

import argparse
import glob
import hashlib
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from env import load_env, use_mock

CANDIDATES = "data/exchange/candidates.jsonl"
DECISIONS = "data/exchange/decisions.jsonl"
IMAGES = "data/exchange/images.jsonl"
DEMO = "analysis/demo_cases.json"
OUT = "data/exchange/cloudinary.jsonl"
FOLDER = "timeproof"
BACKGROUND = f"{FOLDER}/card_background"
PRESET = "timeproof-evidence"          # upload preset: the settings every archived picture shares
MAX_CAPTION = 140


def credentials() -> dict:
    url = os.environ.get("CLOUDINARY_URL", "")
    if url.startswith("cloudinary://"):
        p = urlparse(url)
        return {"cloud": p.hostname, "key": p.username, "secret": p.password}
    return {"cloud": os.environ.get("CLOUDINARY_CLOUD_NAME", ""), "key": os.environ.get("CLOUDINARY_API_KEY", ""),
            "secret": os.environ.get("CLOUDINARY_API_SECRET", "")}


def sign(params: dict, secret: str) -> str:
    """Cloudinary signature: sorted 'key=value' pairs joined by '&', plus the secret, SHA-1.
    A '&' inside a value (a caption can have one) is signed as %26, so it is not read as a separator."""
    payload = "&".join(f"{k}={str(params[k]).replace('&', '%26')}" for k in sorted(params))
    return hashlib.sha1((payload + secret).encode()).hexdigest()


def context_value(text: str) -> str:
    # In Cloudinary context metadata, '|' separates entries and '=' separates key and value.
    return str(text or "").replace("\\", "\\\\").replace("|", "\\|").replace("=", "\\=")


def external_call(kind: str, **kw) -> dict | bytes:
    """The only function that talks to outside services (Wikimedia, Cloudinary)."""
    if use_mock():
        if kind == "download":
            return b"mock image bytes"
        if kind == "check":
            return {"status": 200, "content_type": "image/png", "error": ""}
        if kind == "preset":
            return {"message": "created", "name": kw["params"]["name"]}
        return {"public_id": kw["params"]["public_id"], "version": 1, "width": 800, "height": 600, "phash": "0" * 16,
                "secure_url": f"https://res.cloudinary.com/{kw['cloud']}/image/upload/v1/{kw['params']['public_id']}.jpg"}
    if kind == "download":
        r = httpx.get(kw["url"], headers={"User-Agent": os.environ.get("WIKI_USER_AGENT", "")},
                      follow_redirects=True, timeout=60)
        r.raise_for_status()
        return r.content
    if kind == "check":      # ask Cloudinary for a delivery URL once: it builds (and caches) the result
        r = httpx.get(kw["url"], timeout=180)
        return {"status": r.status_code, "content_type": r.headers.get("content-type"),
                "error": r.headers.get("x-cld-error", "")}
    if kind == "preset":     # Admin API: create the preset, or update it when the name is taken (409)
        url = f"https://api.cloudinary.com/v1_1/{kw['cloud']}/upload_presets"
        r = httpx.post(url, data=kw["params"], auth=(kw["key"], kw["secret"]), timeout=60)
        if r.status_code == 409:
            settings = {k: v for k, v in kw["params"].items() if k != "name"}
            r = httpx.put(f"{url}/{kw['params']['name']}", data=settings, auth=(kw["key"], kw["secret"]), timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Cloudinary preset refused: HTTP {r.status_code} {r.text[:200]}")
        return r.json()
    # The asset type is in the address: these are always pictures.
    for attempt in range(4):
        r = httpx.post(f"https://api.cloudinary.com/v1_1/{kw['cloud']}/image/upload",
                       data=kw["params"], files={"file": ("image", kw["content"])}, timeout=120)
        if r.status_code != 420 or "limit" not in r.text.lower():      # 420 = rate limited: wait and retry
            break
        time.sleep(5 * (attempt + 1))
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudinary upload refused: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def read_jsonl(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def merged(path: str) -> dict[int, dict]:
    """{rev_id: every field written so far for that case} (the last value of each field wins)."""
    out: dict[int, dict] = {}
    for row in read_jsonl(path):
        out.setdefault(row["rev_id"], {}).update({k: v for k, v in row.items() if v is not None})
    return out


def published_cases() -> tuple[dict, dict]:
    """({rev_id: candidate}, {rev_id: decision}) for public cases only: never a synthetic one."""
    decisions = {d["rev_id"]: d for d in read_jsonl(DECISIONS)
                 if d.get("decision") == "flag" and d.get("publish") and not d.get("synthetic")}
    cases = {c["rev_id"]: c for c in read_jsonl(CANDIDATES) if c["rev_id"] in decisions and not c.get("synthetic")}
    return cases, {rev: decisions[rev] for rev in cases}


# ---------- 1. Archive: the pictures, kept with their evidence ----------

def one_pixel_png(rgb: tuple[int, int, int]) -> bytes:
    """A 1x1 PNG of one colour (standard library only): Cloudinary scales it into the slider background."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"\x00" + bytes(rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def ensure_preset(cred: dict) -> None:
    """One upload preset holds what every archived picture shares, so it can be changed in the
    Cloudinary console without touching this script."""
    external_call("preset", cloud=cred["cloud"], key=cred["key"], secret=cred["secret"], params={
        "name": PRESET, "unsigned": "false",
        "asset_folder": FOLDER,            # where it shows in the Media Library (the public id alone does not place it)
        "allowed_formats": "jpg,png,gif,webp,tiff,svg",
        "overwrite": "true", "invalidate": "true",   # a rerun replaces the picture and refreshes cached copies
        "unique_filename": "false", "use_filename": "false",
        "phash": "true",                   # perceptual hash: the same picture under another name gets the same value
        "tags": "timeproof"})


def upload(cred: dict, content: bytes, public_id: str, tags: list[str], context: dict) -> dict:
    """Signed upload: only what changes per picture is in the request, the rest is in the preset."""
    params = {
        "upload_preset": PRESET,
        "public_id": public_id,
        "timestamp": str(int(time.time())),
        "tags": ",".join(tags),
        "context": "|".join(f"{k}={context_value(v)}" for k, v in context.items() if v not in (None, "")),
    }
    signed = {**params, "api_key": cred["key"], "signature": sign(params, cred["secret"])}
    return external_call("upload", cloud=cred["cloud"], params=signed, content=content)


def version_at(info: dict, timestamp: str) -> dict | None:
    """The file version that was online at `timestamp` (ISO dates compare as text)."""
    for v in sorted(info.get("versions", []), key=lambda v: v["timestamp"], reverse=True):
        if v["timestamp"] <= timestamp:
            return v
    return None


def previous_files(cases: list[dict], parquet: list[str]) -> dict[int, dict]:
    """{rev_id: {"file": picture the new one took the place of, "moved": still in the article}},
    read from the two versions themselves, with the same pairing rule as find_candidates.py
    (files gone and files that came, in alphabetical order). "moved" matters: a picture pushed
    down into a gallery was not removed, and we must not say it was."""
    from find_candidates import images as wikitext_images, iter_versions   # needs pyarrow: only here

    wanted = {c["rev_id"]: c["image"]["file"] for c in cases}
    last_text, out = {}, {}
    for row in iter_versions(parquet, sorted({c["page_id"] for c in cases})):
        page = row["page_id"]
        if row["rev_id"] in wanted and page in last_text:
            old, new = wikitext_images(last_text[page] or ""), wikitext_images(row["text"] or "")
            gone, came = sorted(old.keys() - new.keys()), sorted(new.keys() - old.keys())
            file = wanted[row["rev_id"]]
            if file in came and came.index(file) < len(gone):
                old_file = gone[came.index(file)]
                text = (row["text"] or "").replace("_", " ").lower()
                out[row["rev_id"]] = {"file": old_file, "moved": old_file.replace("_", " ").lower() in text}
        last_text[page] = row["text"]
    return out


def archive(cred: dict, out_path: str, only: list[int] | None, parquet: list[str]) -> None:
    cases, _ = published_cases()
    chosen = [c for c in cases.values()
              if c["kind"] == "image" and (c.get("image") or {}).get("thumb_url") and (not only or c["rev_id"] in only)]
    info = {r["file"]: r for r in read_jsonl(IMAGES)}
    replaced = [c for c in chosen if c["image"]["change"] == "replaced"]
    before_file = previous_files(replaced, parquet) if replaced and parquet else {}
    print(f"archiving {len(chosen)} published image case(s), {len(before_file)} with the picture before" + (" (MOCK)" if use_mock() else ""))
    ensure_preset(cred)
    upload(cred, one_pixel_png((17, 24, 39)), BACKGROUND, ["timeproof", "background"], {"use": "slider background"})

    def keep(case: dict, side: str, file: str, url: str, caption: str | None, author: str, license_: str, version: str | None) -> dict:
        public_id = f"{FOLDER}/rev_{case['rev_id']}" + ("_before" if side == "before" else "")
        up = upload(cred, external_call("download", url=url), public_id,
                    ["timeproof", "evidence", side, case["image"]["change"]],
                    {"rev_id": case["rev_id"], "article": case["title"], "edited": case["timestamp"], "side": side,
                     "file": file, "file_version": version, "caption": caption, "author": author, "license": license_,
                     "source": f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={case['rev_id']}"})
        time.sleep(0.5)
        return {"public_id": up["public_id"], "archived_url": up["secure_url"], "phash": up.get("phash")}

    with open(out_path, "a", encoding="utf-8") as out:
        for case in chosen:
            img, rev = case["image"], case["rev_id"]
            # No credit, no picture: Wikimedia images may only be shown with author and license.
            if not (img.get("author") and img.get("license")):
                print(f"  rev {rev}: author or license unknown, not archived")
                continue
            try:
                after = keep(case, "after", img["file"], img["thumb_url"], img.get("caption_new"),
                             img["author"], img["license"], img.get("version_timestamp"))
                line = {"rev_id": rev, "kind": "image", "change": img["change"], "file": img["file"], **after,
                        "image_auto_url": f"https://res.cloudinary.com/{cred['cloud']}/image/upload/c_limit,w_800/f_auto/q_auto/{after['public_id']}",
                        "original_url": (info.get(img["file"]) or {}).get("description_url")
                                        or "https://commons.wikimedia.org/wiki/File:" + quote(img["file"].replace(" ", "_")),
                        "author": img["author"], "license": img["license"], "version_timestamp": img.get("version_timestamp")}
                found = before_file.get(rev) or {}
                old = info.get(found.get("file", ""))
                version = version_at(old, case["timestamp"]) if old else None
                if old and version and version.get("thumb_url") and old.get("author") and old.get("license"):
                    before = keep(case, "before", old["file"], version["thumb_url"], img.get("caption_old"),
                                  old["author"], old["license"], version["timestamp"])
                    line.update({"before_file": old["file"], "before_moved": found["moved"], "before_public_id": before["public_id"],
                                 "before_archived_url": before["archived_url"], "before_phash": before["phash"],
                                 "before_original_url": old.get("description_url"),
                                 "before_author": old["author"], "before_license": old["license"]})
                elif rev in before_file:
                    # Named, but not shown: without an author on record we may not display it.
                    line.update({"before_file": found["file"], "before_moved": found["moved"]})
                    print(f"  rev {rev}: picture before ({found['file']}) has no dated version or no credit, kept out")
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                print(f"  rev {rev}: failed: {e}")
                continue
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  rev {rev} {case['title']}: {img['change']}, phash {line['phash']}"
                  + (f", before {line['before_file']} phash {line['before_phash']}" if line.get("before_public_id") else "")
                  + (" (moved inside the article, not removed)" if line.get("before_moved") else ""))


# ---------- 2. Before / after pictures, composed by Cloudinary ----------
# No file is sent here: each side is the archived picture on a fixed canvas, with the caption
# Wikipedia showed under it at that time, written on it by Cloudinary as text layers.

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
RED, GREEN, WHITE, DIM = "FCA5A5", "86EFAC", "FFFFFF", "94A3B8"
TEXT_CREDIT = "Text: Finnish Wikipedia, CC BY-SA 4.0"


def text_layer(text: str) -> str:
    """Encode a text for a Cloudinary text overlay: URL-encoded, and commas and slashes
    double-escaped, because Cloudinary reads them as separators inside a URL."""
    return quote(text, safe="").replace("%2C", "%252C").replace("%2F", "%252F")


def shorten(text: str | None, n: int = MAX_CAPTION) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def layer(text: str, font: str, color: str, width: int, x: int, y: int, gravity: str = "north_west") -> list[str]:
    """One text block placed at a fixed spot, wrapped to `width` pixels."""
    return [f"l_text:{font}:{text_layer(text)},co_rgb:{color},w_{width},c_fit",
            f"fl_layer_apply,g_{gravity},x_{x},y_{y}"]


def day_text(value: str | None) -> str:
    """'2019-09-27T21:53Z' -> '27 Sep 2019'."""
    if not value:
        return ""
    y, m, d = str(value)[:10].split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def image_credit(author: str | None, license_: str | None, room: int = 160) -> str:
    # The whole author credit must stay readable (the licence requires it); it may wrap on two lines.
    return f"{shorten(author or 'unknown author', room)}, {license_ or 'license unknown'}"


def compare_url(cloud: str, picture_id: str, caption: str, label: str, color: str, credit: str) -> str:
    """One side of the before/after slider: a picture at a fixed size and framing, with the
    caption Wikipedia showed under it at that time."""
    steps = ["c_scale,w_1200,h_800",      # the background is one pixel: stretching it is the point
             f"l_{picture_id.replace('/', ':')}", "c_fit,w_1100,h_520", "fl_layer_apply,g_north,y_30"]
    steps += layer(label, "Arial_24_bold", color, 1100, 50, 578)
    steps += layer(shorten(caption, 200), "Arial_30_bold", WHITE, 1100, 50, 616)
    steps += layer(f"Image: {credit} · {TEXT_CREDIT}", "Arial_16", DIM, 1100, 50, 16, "south_west")
    steps += ["f_auto", "q_auto"]
    return f"https://res.cloudinary.com/{cloud}/image/upload/{'/'.join(steps)}/{BACKGROUND}"


def make_comparisons(cloud: str, out_path: str, only: list[int] | None) -> None:
    """The two sides of the before/after slider for every archived image case that has both:
    two different pictures when the edit replaced one, the same picture twice when only the
    words under it changed. Hand-made English translations are added for the demo cases."""
    with open(DEMO, encoding="utf-8") as f:
        demos = {d["rev_id"]: d for d in json.load(f)["cases"]}
    cases, _ = published_cases()
    kept = merged(out_path)
    targets = [rev for rev, r in kept.items()
               if rev in cases and r.get("public_id") and r.get("archived_url") and (not only or rev in only)]
    print(f"{len(targets)} archived image case(s) on cloud {cloud}" + (" (MOCK)" if use_mock() else ""))
    with open(out_path, "a", encoding="utf-8") as out:
        for rev in targets:
            case, keep, demo = cases[rev], kept[rev], demos.get(rev) or {}
            img = case.get("image") or {}
            replaced = img.get("change") == "replaced"
            before_id = keep.get("before_public_id") if replaced else keep["public_id"]
            if not before_id:
                print(f"  rev {rev} {case['title']}: no picture before in the archive, no slider")
                continue
            before = demo.get("before_fi") or img.get("caption_old")
            after = demo.get("after_fi") or img.get("caption_new")
            credit_after = image_credit(img.get("author"), img.get("license"))
            credit_before = image_credit(keep.get("before_author"), keep.get("before_license")) if replaced else credit_after
            edited = day_text(str(case["timestamp"])[:10])
            what = "PICTURE" if replaced else "CAPTION"
            said = lambda text, file: text or f"(no caption) File: {file}"
            line = {"rev_id": rev, "kind": "image", "compare": img.get("change"),
                    "before_url": compare_url(cloud, before_id, said(before, keep.get("before_file") if replaced else img.get("file")),
                                              f"{what} BEFORE · until {edited}", RED, credit_before),
                    "after_url": compare_url(cloud, keep["public_id"], said(after, img.get("file")),
                                             f"{what} AFTER · edit of {edited}", GREEN, credit_after),
                    "before_caption": before, "after_caption": after,
                    "before_caption_en": demo.get("before_en"), "after_caption_en": demo.get("after_en"),
                    "archived_url": keep["archived_url"], "author": img.get("author"), "license": img.get("license")}
            # Cloudinary builds a picture on the first request: ask for both now, so a wrong layer
            # is caught here and the first visitor does not wait.
            failed = None
            for key in ("before_url", "after_url"):
                answer = external_call("check", url=line[key])
                if answer["status"] != 200 or not str(answer.get("content_type", "")).startswith("image/"):
                    failed = f"{key}: HTTP {answer['status']} {answer.get('content_type')} {answer.get('error', '')}"
                    break
            if failed:
                print(f"  rev {rev} {case['title']}: NOT written, {failed[:200]}")
                continue
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  rev {rev} {case['title']}: slider ({'two pictures' if replaced else 'same picture, two captions'}), checked")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", action="store_true", help="upload the pictures of the published image cases (needs the keys)")
    parser.add_argument("--compare", action="store_true", help="the two sides of the before/after slider (needs the cloud name only)")
    parser.add_argument("--rev-id", type=int, action="append", help="only these cases")
    parser.add_argument("--cloud", help="cloud name for --compare (default: CLOUDINARY_CLOUD_NAME)")
    parser.add_argument("--parquet", nargs="*", default=sorted(glob.glob("data/versions-*.parquet")),
                        help="history files, to find the picture a replaced one took the place of")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    load_env()
    if not (args.archive or args.compare):
        parser.error("choose --archive, --compare or both")
    if use_mock():
        args.out = args.out.replace(".jsonl", "-mock.jsonl")

    cred = credentials()
    if args.archive:
        if use_mock():
            cred = {"cloud": cred["cloud"] or "mock-cloud", "key": "mock", "secret": "mock"}
        elif not all(cred.values()):
            sys.exit("Missing in .env: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET (or CLOUDINARY_URL).")
        archive(cred, args.out, args.rev_id, args.parquet)
    if args.compare:
        cloud = args.cloud or cred["cloud"] or ("mock-cloud" if use_mock() else "")
        if not cloud:
            sys.exit("Give --cloud or CLOUDINARY_CLOUD_NAME in .env.")
        make_comparisons(cloud, args.out, args.rev_id)


if __name__ == "__main__":
    main()
