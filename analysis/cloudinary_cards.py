"""Evidence cards for image cases, made by Cloudinary (Cloudinary challenge).

For each chosen image case, this script:
  1. downloads the thumbnail of the file version that was online on the day of the edit
     (with our descriptive User-Agent: Wikimedia refuses some servers that fetch by themselves);
  2. uploads it to Cloudinary with its evidence as metadata (rev_id, article, captions, author,
     license) and tags, so the media library itself is a searchable archive of the cases;
  3. builds an "evidence card" URL: Cloudinary resizes the picture to a 1200x630 share image and
     writes the old caption, the new caption, the date and the author/license credit on it.

Writes data/exchange/cloudinary.jsonl (one line per case, written as soon as it is done;
cases already there are skipped on a rerun).

Usage (from the repository root):
    python analysis/cloudinary_cards.py --rev-id 24139572        # one case
    python analysis/cloudinary_cards.py --suspicious --limit 20  # image cases judged suspicious
.env: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET (or CLOUDINARY_URL).
With USE_MOCK=true nothing is sent: fake answers, written to cloudinary-mock.jsonl.
"""

import argparse
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

ANALYSIS = "data/exchange/analysis.jsonl"
DEMO = "analysis/demo_cases.json"
OUT = "data/exchange/cloudinary.jsonl"
FOLDER = "timeproof"
CARD_W, CARD_H = 1200, 630          # size used by link previews (Open Graph)
MAX_CAPTION = 140                   # characters per caption: about 5 lines in the right-hand column


def credentials() -> dict:
    url = os.environ.get("CLOUDINARY_URL", "")
    if url.startswith("cloudinary://"):
        p = urlparse(url)
        return {"cloud": p.hostname, "key": p.username, "secret": p.password}
    return {"cloud": os.environ.get("CLOUDINARY_CLOUD_NAME", ""), "key": os.environ.get("CLOUDINARY_API_KEY", ""),
            "secret": os.environ.get("CLOUDINARY_API_SECRET", "")}


def sign(params: dict, secret: str) -> str:
    """Cloudinary signature: sorted 'key=value' pairs joined by '&', plus the secret, SHA-1."""
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((payload + secret).encode()).hexdigest()


def context_value(text: str) -> str:
    # In Cloudinary context metadata, '|' separates entries and '=' separates key and value.
    return str(text or "").replace("\\", "\\\\").replace("|", "\\|").replace("=", "\\=")


def external_call(kind: str, **kw) -> dict | bytes:
    """The only function that talks to outside services (Wikimedia, Cloudinary)."""
    if use_mock():
        if kind == "download":
            return b"mock image bytes"
        return {"public_id": kw["params"]["public_id"], "version": 1, "width": 800, "height": 600,
                "secure_url": f"https://res.cloudinary.com/{kw['cloud']}/image/upload/v1/{kw['params']['public_id']}.jpg"}
    if kind == "download":
        r = httpx.get(kw["url"], headers={"User-Agent": os.environ.get("WIKI_USER_AGENT", "")},
                      follow_redirects=True, timeout=60)
        r.raise_for_status()
        return r.content
    r = httpx.post(f"https://api.cloudinary.com/v1_1/{kw['cloud']}/image/upload",
                   data=kw["params"], files={"file": ("image", kw["content"])}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudinary upload refused: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


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


def blocks(header: str, before: str, before_en: str | None, after: str, after_en: str | None,
           footer: str, x: int, w: int, roomy: bool) -> list[str]:
    """Title, header, before (red) and after (green) with optional English lines, footer.
    Each block has a fixed height so a long text can never run over the next one."""
    y_after = 300 if roomy else 330
    steps = layer("TimeProof", "Arial_34_bold", "FFFFFF", w, x, 28)
    steps += layer(header, "Arial_20", "CBD5E1", w, x, 78)
    steps += layer(before, "Arial_26_bold", "FCA5A5", w, x, 130)
    if before_en:
        steps += layer(before_en, "Arial_19_italic", "FECACA", w, x, 225 if roomy else 235)
    steps += layer(after, "Arial_26_bold", "86EFAC", w, x, y_after)
    if after_en:
        steps += layer(after_en, "Arial_19_italic", "BBF7D0", w, x, y_after + (95 if roomy else 105))
    steps += layer(footer, "Arial_16", "94A3B8", w, x, 22, "south_west")
    return steps


def card_url(cloud: str, public_id: str, case: dict, demo: dict | None = None) -> str:
    """Evidence card: the picture of the day on the left (never covered: it is the evidence),
    old and new caption on the right, date and author/license credit written on it."""
    img = case["image"]
    before = f"BEFORE: {shorten((demo or {}).get('before_fi') or img.get('caption_old')) or '(no caption)'}"
    after = (f"AFTER ({case['timestamp'][:10]}): "
             f"{shorten((demo or {}).get('after_fi') or img.get('caption_new')) or '(no caption)'}")
    online = f" · {demo['online']}" if demo else ""
    footer = shorten(f"Finnish Wikipedia rev {case['rev_id']}{online} · "
                     f"Image: {img.get('author') or 'unknown author'}, {img.get('license') or 'license unknown'}", 200)
    header = f"{case['title']} · Finnish Wikipedia · edited {case['timestamp'][:10]}"
    half = CARD_W // 2
    steps = [f"c_pad,w_{half},h_{CARD_H},b_rgb:111827", f"c_pad,w_{CARD_W},h_{CARD_H},g_west,b_rgb:111827"]
    steps += blocks(header, before, (demo or {}).get("before_en"), after, (demo or {}).get("after_en"),
                    footer, half + 30, half - 60, roomy=False)
    steps.append("f_auto,q_auto")
    return f"https://res.cloudinary.com/{cloud}/image/upload/{'/'.join(steps)}/{public_id}"


def text_card_url(cloud: str, background_id: str, demo: dict) -> str:
    """Evidence card for a text edit: the exact Finnish passage before and after, with English."""
    before = f"BEFORE: {shorten(demo['before_fi'], 230)}"
    after = (f"AFTER ({demo['date']}): {shorten(demo['after_fi'], 230)}" if demo.get("after_fi")
             else f"AFTER ({demo['date']}): passage deleted")
    header = f"{demo['title']} · Finnish Wikipedia · edited {demo['date']} · signal: {demo['kind']}"
    footer = f"Finnish Wikipedia rev {demo['rev_id']} · {demo['online']} · Text: CC BY-SA 4.0"
    steps = [f"c_scale,w_{CARD_W},h_{CARD_H}"]
    steps += blocks(header, before, demo.get("before_en"), after, demo.get("after_en"), footer, 40, CARD_W - 80,
                    roomy=True)
    steps.append("f_auto,q_auto")
    return f"https://res.cloudinary.com/{cloud}/image/upload/{'/'.join(steps)}/{background_id}"


def one_pixel_png(rgb: tuple[int, int, int]) -> bytes:
    """A 1x1 PNG of one colour (standard library only): Cloudinary scales it into the card background."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"\x00" + bytes(rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def upload(cred: dict, content: bytes, public_id: str, tags: list[str], context: dict) -> dict:
    params = {
        "public_id": public_id,
        "overwrite": "true",
        "timestamp": str(int(time.time())),
        "tags": ",".join(tags),
        "context": "|".join(f"{k}={context_value(v)}" for k, v in context.items()),
    }
    signed = {**params, "api_key": cred["key"], "signature": sign(params, cred["secret"])}
    return external_call("upload", cloud=cred["cloud"], params=signed, content=content)


def process(case: dict, cred: dict, demo: dict | None = None) -> dict:
    img = case["image"]
    content = external_call("download", url=img["thumb_url"])
    up = upload(cred, content, f"{FOLDER}/rev_{case['rev_id']}", ["timeproof", case["kind"], img["change"]], {
        "rev_id": case["rev_id"], "article": case["title"], "edited": case["timestamp"],
        "file": img["file"], "caption_old": img.get("caption_old"), "caption_new": img.get("caption_new"),
        "author": img.get("author"), "license": img.get("license"),
        "source": f"https://fi.wikipedia.org/w/index.php?diff=prev&oldid={case['rev_id']}"})
    return {"rev_id": case["rev_id"], "public_id": up["public_id"], "version": up.get("version"),
            "image_url": up["secure_url"],
            "image_auto_url": f"https://res.cloudinary.com/{cred['cloud']}/image/upload/f_auto,q_auto,w_800/{up['public_id']}",
            "evidence_card_url": card_url(cred["cloud"], up["public_id"], case, demo),
            "card_size": [CARD_W, CARD_H], "author": img.get("author"), "license": img.get("license"),
            "demo": bool(demo)}


def process_text_demo(demo: dict, cred: dict, background_id: str) -> dict:
    return {"rev_id": demo["rev_id"], "public_id": background_id, "image_url": None, "image_auto_url": None,
            "evidence_card_url": text_card_url(cred["cloud"], background_id, demo),
            "card_size": [CARD_W, CARD_H], "author": None, "license": "CC BY-SA 4.0 (text)", "demo": True}


def read_jsonl(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_demo_cards(cred: dict, out_path: str, done: set) -> None:
    """Cards for the hand-verified demo cases: picture cards for image cases, text cards otherwise."""
    with open(DEMO, encoding="utf-8") as f:
        demos = json.load(f)["cases"]
    analysed = {r["rev_id"]: r for r in read_jsonl(ANALYSIS)}
    background_id = f"{FOLDER}/card_background"
    upload(cred, one_pixel_png((17, 24, 39)), background_id, ["timeproof", "background"], {"use": "card background"})
    with open(out_path, "a", encoding="utf-8") as out:
        for demo in demos:
            if demo["rev_id"] in done:
                continue
            case = analysed.get(demo["rev_id"])
            if demo["kind"] == "image" and case and (case.get("image") or {}).get("thumb_url"):
                line = process(case, cred, demo)
            else:
                line = process_text_demo(demo, cred, background_id)
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  rev {demo['rev_id']} {demo['title']}: {line['evidence_card_url'][:100]}…")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rev-id", type=int, action="append", help="these cases")
    parser.add_argument("--suspicious", action="store_true", help="image cases judged suspicious by Nemotron")
    parser.add_argument("--demo", action="store_true", help="the hand-verified demo cases of analysis/demo_cases.json")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    load_env()

    cred = credentials()
    if use_mock():
        args.out = args.out.replace(".jsonl", "-mock.jsonl")
        cred = {"cloud": cred["cloud"] or "mock-cloud", "key": "mock", "secret": "mock"}
    elif not all(cred.values()):
        sys.exit("Missing in .env: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET (or CLOUDINARY_URL).")

    done = {r["rev_id"] for r in read_jsonl(args.out)}
    if args.demo:
        make_demo_cards(cred, args.out, done)
        return
    cases = [r for r in read_jsonl(ANALYSIS)
             if not r.get("synthetic") and r["kind"] == "image" and (r.get("image") or {}).get("thumb_url")
             and r["rev_id"] not in done
             and ((args.rev_id and r["rev_id"] in args.rev_id)
                  or (args.suspicious and r["nemotron"]["suspicious"]))]
    cases = cases[:args.limit]
    print(f"{len(done)} already in {args.out}; making {len(cases)} cards" + (" (MOCK)" if use_mock() else ""))
    with open(args.out, "a", encoding="utf-8") as out:
        for case in cases:
            try:
                line = process(case, cred)
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                print(f"  rev {case['rev_id']}: failed: {e}")
                continue
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  rev {case['rev_id']} {case['title']}: {line['evidence_card_url'][:110]}…")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
