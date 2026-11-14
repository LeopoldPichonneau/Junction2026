"""Find Wikipedia edits worth investigating (step 1 of the analysis module).

Reads the revision parquet files in batches, compares each version of an article
with the previous one, and writes one line per suspicious edit to
data/exchange/candidates.jsonl (format: docs/TIMEPROOF-PLAN-SAMEDI.md, section 4.1).

Usage (from the repository root):
    python analysis/find_candidates.py --page-id 1150
    python analysis/find_candidates.py data/versions-01.parquet

Notes on the choices made here:
- One line per rev_id: the database uses rev_id as a primary key, so an edit that
  triggers several detectors gets a single line with the strongest `kind`.
- Reverts, null edits, minor edits and declared bots produce no line, but they still
  become the "previous version" that the next edit is compared with.
- `user_is_new` means "this edit was made within 7 days of the account's first edit
  in the files given on the command line". It is not the real account creation date.
- Coordination (same text pushed by several accounts on several articles) is not
  done yet: it is the next step, after this script is checked on real data.
"""

import argparse
import difflib
import hashlib
import html
import json
import re
import sys
import time
from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

DEFAULT_INPUT = "data/versions-01.parquet"
DEFAULT_OUTPUT = "data/exchange/candidates.jsonl"
COLUMNS = ["page_id", "title", "rev_id", "timestamp", "user", "anonymous",
           "comment", "minor", "sha1", "text"]
# Small batches: some articles have versions of 100+ kB of wikitext each.
BATCH_SIZE = 200
MAX_DIFF_CHARS = 1500       # keeps Nemotron prompts small (page blanking removes everything)
NEW_ACCOUNT_DAYS = 7

# --- Wikitext parsing -------------------------------------------------------------

FILE_PREFIX = re.compile(r"\[\[\s*(Tiedosto|Kuva|File|Image)\s*:", re.I)
REF_TAG = re.compile(r"<ref[\s>]", re.I)
INVALID_FILE_NAME = re.compile(r"[\[\]{}<>|#\n]")
PLACEHOLDER_FILES = {"esimerkki.jpg", "example.jpg"}

# Display options of an image link: they are not part of the caption.
IMAGE_OPTIONS = {
    "thumb", "thumbnail", "frame", "framed", "frameless", "border", "left", "right",
    "center", "centre", "none", "upright", "baseline", "middle", "sub", "super",
    "top", "text-top", "bottom", "text-bottom",
    "pienoiskuva", "pienois", "kehys", "kehyksetön", "reunus", "vasen", "oikea",
    "keskitetty", "keskellä", "keski", "ei mitään", "pysty", "pystykuva",
}
IMAGE_OPTION_PATTERN = re.compile(
    r"^(\d*\s*x?\s*\d+\s*px|(alt|link|linkki|page|sivu|class|lang|upright|pystykuva)\s*=.*)$",
    re.I | re.S,
)

# Finnish inflects nouns (sota -> sodan, sodassa), so we match stems, not words.
WATCHED_TERMS = {
    "vapaussota": re.compile(r"vapausso[td]\w*", re.I),
    "sisällissota": re.compile(r"sisällisso[td]\w*", re.I),
    "kansalaissota": re.compile(r"kansalaisso[td]\w*", re.I),
    "luokkasota": re.compile(r"luokkaso[td]\w*", re.I),
    "punakapina": re.compile(r"punakapin\w*", re.I),
    "veljessota": re.compile(r"veljesso[td]\w*", re.I),
}


def file_links(text: str):
    """Yield (start, end, inner) for every [[File:...]] link.

    Captions can contain [[links]], so brackets are counted instead of using a regex.
    """
    i = 0
    while (m := FILE_PREFIX.search(text, i)):
        depth, j = 0, m.start()
        while j < len(text):
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
        if depth != 0:              # unclosed link: give up on it, keep scanning after the prefix
            i = m.end()
            continue
        yield m.start(), j, text[m.end():j - 2]
        i = j


def split_top_level(inner: str) -> list[str]:
    """Split on '|' only outside nested [[...]] and {{...}}.

    A plain split("|") would cut a caption like 'Kuva [[A|B]]' into 'B]]'.
    """
    parts, depth, start, k = [], 0, 0, 0
    while k < len(inner):
        two = inner[k:k + 2]
        if two in ("[[", "{{"):
            depth += 1
            k += 2
        elif two in ("]]", "}}"):
            depth = max(0, depth - 1)
            k += 2
        elif inner[k] == "|" and depth == 0:
            parts.append(inner[start:k])
            start = k + 1
            k += 1
        else:
            k += 1
    parts.append(inner[start:])
    return parts


def is_image_option(part: str) -> bool:
    p = part.strip()
    return p.lower() in IMAGE_OPTIONS or bool(IMAGE_OPTION_PATTERN.match(p))


def normalize_file_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.replace("_", " ")).strip()
    return name[:1].upper() + name[1:]


def images(text: str) -> dict[str, str]:
    """{file_name: cleaned caption} for every image link in the wikitext."""
    out = {}
    for _, _, inner in file_links(text):
        parts = split_top_level(inner)
        name = normalize_file_name(parts[0])
        # Skip broken links and the sample file the edit toolbar inserts ("Esimerkki.jpg").
        if not name or INVALID_FILE_NAME.search(name) or name.lower() in PLACEHOLDER_FILES:
            continue
        captions = [p for p in parts[1:] if p.strip() and not is_image_option(p)]
        out[name] = clean_inline(captions[-1]) if captions else ""
    return out


def count_refs(text: str) -> int:
    # Must run on raw wikitext: cleaning removes the <ref> tags.
    return len(REF_TAG.findall(text))


LINK = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]]*)\]\]")
CATEGORY = re.compile(r"\[\[\s*(Luokka|Category)\s*:[^\]]*\]\]", re.I)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
TABLE = re.compile(r"\{\|(?:(?!\{\|).)*?\|\}", re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)
REF_BLOCK = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
HTML_TAG = re.compile(r"<[^>]+>")
EXTERNAL_LINK = re.compile(r"\[https?://\S+\s*([^\]]*)\]")


def remove_nested(pattern: re.Pattern, text: str) -> str:
    # Templates and tables nest, so remove innermost first until nothing changes.
    while True:
        new = pattern.sub("", text)
        if new == text:
            return text
        text = new


def clean_inline(text: str) -> str:
    """Wiki markup -> readable text, for a short piece such as a caption."""
    text = remove_nested(TEMPLATE, text)
    text = LINK.sub(r"\1", text)
    text = LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = HTML_TAG.sub("", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def caption_key(caption: str) -> str:
    """Form used to decide whether a caption really changed.

    Ignores case, spacing and punctuation, so a fixed comma or a non-breaking space
    is not reported as a new caption, while a changed word or number still is.
    """
    return re.sub(r"[\W_]+", " ", caption).casefold().strip()


def clean_article(text: str) -> str:
    """Wiki markup -> readable text, keeping line breaks so paragraphs can be diffed."""
    text = COMMENT.sub("", text)
    text = REF_BLOCK.sub("", text)
    pieces, last = [], 0
    for start, end, _ in file_links(text):
        pieces.append(text[last:start])
        last = end
    pieces.append(text[last:])
    text = "".join(pieces)
    text = remove_nested(TEMPLATE, text)
    text = remove_nested(TABLE, text)
    text = CATEGORY.sub("", text)
    text = LINK.sub(r"\1", text)
    text = EXTERNAL_LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = HTML_TAG.sub("", text)
    return text


def term_counts(clean_text: str) -> dict[str, int]:
    return {term: len(rx.findall(clean_text)) for term, rx in WATCHED_TERMS.items()}


# --- Comparing two versions -------------------------------------------------------

def word_diff(old_clean: str, new_clean: str) -> tuple[str, str]:
    """Return (added, removed) text, comparing word by word inside changed paragraphs only.

    Diffing whole articles word by word would turn a fixed typo into a whole paragraph.
    """
    old_p = [p.strip() for p in old_clean.split("\n") if p.strip()]
    new_p = [p.strip() for p in new_clean.split("\n") if p.strip()]
    added, removed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_p, new_p, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old_w = " ".join(old_p[i1:i2]).split()
        new_w = " ".join(new_p[j1:j2]).split()
        if len(old_w) * len(new_w) > 4_000_000:     # huge rewrite: word diff would be too slow
            removed.append(" ".join(old_w))
            added.append(" ".join(new_w))
            continue
        sm = difflib.SequenceMatcher(None, old_w, new_w, autojunk=False)
        for t, a1, a2, b1, b2 in sm.get_opcodes():
            if t in ("replace", "delete"):
                removed.append(" ".join(old_w[a1:a2]))
            if t in ("replace", "insert"):
                added.append(" ".join(new_w[b1:b2]))
    return shorten(" … ".join(added)), shorten(" … ".join(removed))


def shorten(text: str) -> str:
    return text if len(text) <= MAX_DIFF_CHARS else text[:MAX_DIFF_CHARS] + " […]"


IMAGE_CHANGE_PRIORITY = ["recaptioned", "replaced", "added", "removed"]


def image_changes(old: dict[str, str], new: dict[str, str]) -> list[dict]:
    """All image changes between two versions, strongest first."""
    changes = []
    for name in old.keys() & new.keys():
        if old[name] and new[name] and caption_key(old[name]) != caption_key(new[name]):
            changes.append({"change": "recaptioned", "file": name,
                            "caption_old": old[name], "caption_new": new[name]})
    gone = sorted(old.keys() - new.keys())
    came = sorted(new.keys() - old.keys())
    # A file removed and another added in the same edit is treated as a replacement.
    while gone and came:
        g, c = gone.pop(0), came.pop(0)
        changes.append({"change": "replaced", "file": c,
                        "caption_old": old[g] or None, "caption_new": new[c] or None})
    for c in came:
        changes.append({"change": "added", "file": c, "caption_old": None, "caption_new": new[c] or None})
    for g in gone:
        changes.append({"change": "removed", "file": g, "caption_old": old[g] or None, "caption_new": None})
    changes.sort(key=lambda ch: IMAGE_CHANGE_PRIORITY.index(ch["change"]))
    for ch in changes:
        ch["thumb_url"] = None          # filled in by fetch_images.py (step 2)
    return changes


# --- Accounts and privacy ---------------------------------------------------------

def account_hash(user: str | None) -> str | None:
    # Same formula as docs/TECH.md section 6, so it matches decision/accounts.py.
    return hashlib.sha256(user.encode()).hexdigest()[:16] if user else None


def is_declared_bot(user: str | None) -> bool:
    return bool(user) and user.lower().endswith("bot")


USER_LINK = re.compile(
    r"\[\[\s*(Käyttäjä|User|Keskustelu käyttäjästä|User talk|Toiminnot:Muokkaukset"
    r"|Special:Contributions|Toiminnot:Contributions)\s*[:/][^\]]*\]\]", re.I)
USER_WORD = re.compile(r"\b(käyttäjän|käyttäjältä|käyttäjälle|käyttäjä|user)\s+(\S+)", re.I)
IP_ADDRESS = re.compile(r"\b(\d{1,3}(\.\d{1,3}){3}|[0-9a-f]{1,4}(:[0-9a-f]{0,4}){3,7})\b", re.I)
COMMENT_TOKEN = re.compile(r"[^\s\[\]|:,;()/]+")


def scrub_comment(comment: str | None, known_users: set[str]) -> str:
    """Edit summaries can name accounts (undo messages, user links): remove them.

    The patterns catch the usual wording; the known-account check catches free text
    such as "version made by <name>".
    """
    if not comment:
        return ""
    comment = USER_LINK.sub("[user]", comment)
    comment = USER_WORD.sub(r"\1 [user]", comment)
    comment = IP_ADDRESS.sub("[ip]", comment)
    tokens = COMMENT_TOKEN.findall(comment)
    names = set()
    for n in range(1, 5):               # account names can be a few words long
        for k in range(len(tokens) - n + 1):
            candidate = " ".join(tokens[k:k + n])
            if len(candidate) >= 3 and candidate in known_users:
                names.add(candidate)
    for name in sorted(names, key=len, reverse=True):
        comment = comment.replace(name, "[user]")
    return comment


def first_edit_dates(paths: list[str]) -> dict[str, object]:
    """First edit of every account in the given files (cheap: no text column read)."""
    first = {}
    for path in paths:
        table = pq.read_table(path, columns=["user", "timestamp"])
        grouped = table.group_by("user").aggregate([("timestamp", "min")])
        for user, ts in zip(grouped["user"].to_pylist(), utc_naive(grouped["timestamp_min"]).to_pylist()):
            if user is not None and (user not in first or ts < first[user]):
                first[user] = ts
    return first


# --- Main loop --------------------------------------------------------------------

def iter_versions(paths: list[str], page_ids: list[int] | None):
    dataset = ds.dataset(paths, format="parquet")
    flt = pc.field("page_id").isin(page_ids) if page_ids else None
    for batch in dataset.to_batches(columns=COLUMNS, filter=flt, batch_size=BATCH_SIZE):
        columns = {name: batch.column(name) for name in COLUMNS}
        columns["timestamp"] = utc_naive(columns["timestamp"])
        lists = {name: col.to_pylist() for name, col in columns.items()}
        for i in range(batch.num_rows):
            yield {name: values[i] for name, values in lists.items()}


def utc_naive(timestamps):
    # Converting tz-aware timestamps to Python needs a time zone database, which is
    # missing on Windows. The stored values are UTC, so we drop the zone label instead.
    return pc.cast(timestamps, pa.timestamp("ms"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", default=[DEFAULT_INPUT], help="parquet files")
    parser.add_argument("--page-id", type=int, action="append", help="only these articles (repeatable)")
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    started = time.time()
    first_edit = first_edit_dates(args.inputs)
    # Account names appear with spaces or underscores: match both in comments.
    known_users = set(first_edit) | {u.replace(" ", "_") for u in first_edit}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    stats = {"versions": 0, "first_version": 0, "null_edit": 0, "revert": 0, "minor": 0, "bot": 0,
             "compared": 0, "versions_with_image_change": 0, "recaptioned": 0, "replaced": 0,
             "versions_removing_refs": 0, "refs_removed": 0, "versions_changing_terms": 0,
             "out_of_order": 0}
    kinds = {"image": 0, "sources": 0, "framing": 0}

    current_page, finished_pages = None, set()
    prev = None  # state of the previous version of the current article

    with open(args.out, "w", encoding="utf-8") as out:
        for row in iter_versions(args.inputs, args.page_id):
            stats["versions"] += 1
            if row["page_id"] != current_page:
                if row["page_id"] in finished_pages:
                    sys.exit(f"Input is not grouped by article (page {row['page_id']} seen twice).")
                if current_page is not None:
                    finished_pages.add(current_page)
                current_page, prev = row["page_id"], None

            text = row["text"] or ""
            state = {"sha1": row["sha1"], "timestamp": row["timestamp"]}

            if prev is None:
                # Article creation: nothing to compare with, it only becomes the baseline.
                stats["first_version"] += 1
                state = parse_state(state, text)
                state["seen"] = {row["sha1"]} if row["sha1"] else set()
                prev = state
                continue
            if row["timestamp"] < prev["timestamp"]:
                stats["out_of_order"] += 1
            if row["sha1"] and row["sha1"] == prev["sha1"]:
                # Null edit: same text as just before.
                stats["null_edit"] += 1
                prev = {**prev, "timestamp": row["timestamp"]}
                continue
            if row["sha1"] and row["sha1"] in prev["seen"]:
                # Revert to an earlier text: not a new claim, but the next edit is compared with it.
                stats["revert"] += 1
                state = parse_state(state, text)
                state["seen"] = prev["seen"]
                prev = state
                continue

            state = parse_state(state, text)
            state["seen"] = prev["seen"]
            if row["sha1"]:
                state["seen"].add(row["sha1"])

            # Statistics over every real (non-revert) edit, to compare with Friday's counts.
            stats["compared"] += 1
            img = image_changes(prev["images"], state["images"])
            refs_removed = max(0, prev["refs"] - state["refs"])
            terms_changed = prev["terms"] != state["terms"]
            if img:
                stats["versions_with_image_change"] += 1
                stats["recaptioned"] += sum(ch["change"] == "recaptioned" for ch in img)
                stats["replaced"] += sum(ch["change"] == "replaced" for ch in img)
            if refs_removed:
                stats["versions_removing_refs"] += 1
                stats["refs_removed"] += refs_removed
            if terms_changed:
                stats["versions_changing_terms"] += 1

            user = row["user"]
            if row["minor"]:
                stats["minor"] += 1
            elif is_declared_bot(user):
                stats["bot"] += 1
            else:
                kind = pick_kind(img, refs_removed, terms_changed)
                if kind:
                    kinds[kind] += 1
                    added, removed = word_diff(prev["clean"], state["clean"])
                    line = {
                        "rev_id": row["rev_id"],
                        "page_id": row["page_id"],
                        "title": row["title"],
                        "timestamp": row["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "kind": kind,
                        "account_hash": account_hash(user),
                        "user_is_new": is_new_account(user, row, first_edit),
                        "synthetic": False,
                        "comment": scrub_comment(row["comment"], known_users),
                        "added": added,
                        "removed": removed,
                        "image": img[0] if img else None,
                        "refs_removed": refs_removed,
                    }
                    out.write(json.dumps(line, ensure_ascii=False) + "\n")
                    out.flush()     # a crash later on keeps everything written so far
            prev = state

    print(f"Done in {time.time() - started:.0f} s -> {args.out}")
    print("Candidates by kind:", kinds, "total", sum(kinds.values()))
    print("Stats:", json.dumps(stats, indent=1))


def parse_state(state: dict, text: str) -> dict:
    clean = clean_article(text)
    state.update(clean=clean, images=images(text), refs=count_refs(text), terms=term_counts(clean))
    return state


def pick_kind(img: list[dict], refs_removed: int, terms_changed: bool) -> str | None:
    # Priority from docs/TECH.md section 6: captions and replacements first.
    if img and img[0]["change"] in ("recaptioned", "replaced"):
        return "image"
    if refs_removed:
        return "sources"
    if terms_changed:
        return "framing"
    if img:
        return "image"
    return None


def is_new_account(user: str | None, row: dict, first_edit: dict) -> bool:
    # IPs and temporary accounts (~2026-...) have no account history worth measuring.
    if not user or row["anonymous"] or user.startswith("~") or user not in first_edit:
        return False
    return row["timestamp"] - first_edit[user] <= timedelta(days=NEW_ACCOUNT_DAYS)


if __name__ == "__main__":
    main()
