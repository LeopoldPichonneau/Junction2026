"""Turn raw wikitext into readable plain text for the time machine.

Images and references are removed here, so analysis code must read the raw wikitext instead.
"""
import re

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF_PAIR = re.compile(r"<ref[^>/]*>.*?</ref\s*>", re.S | re.I)
_REF_SELF = re.compile(r"<ref[^>]*/>", re.I)
_TABLE = re.compile(r"\{\|.*?\|\}", re.S)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")          # innermost first, looped for nesting
_FILE_PREFIX = re.compile(r"\[\[\s*(Tiedosto|Kuva|File|Image|Luokka|Category)\s*:", re.I)
_LINK = re.compile(r"\[\[([^\[\]|]*)\|([^\[\]]*)\]\]")
_LINK_PLAIN = re.compile(r"\[\[([^\[\]|]*)\]\]")
_EXT_LINK = re.compile(r"\[(?:https?:)?//[^\s\]]+\s+([^\]]*)\]")
_EXT_BARE = re.compile(r"\[(?:https?:)?//[^\s\]]+\]")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BLANKS = re.compile(r"\n{3,}")


def _drop_bracketed(text: str, prefix: re.Pattern) -> str:
    """Remove [[File:...]] links; their captions may contain [[links]], so count brackets."""
    out, i = [], 0
    while (m := prefix.search(text, i)):
        out.append(text[i:m.start()])
        depth, j = 0, m.start()
        while j < len(text):
            if text.startswith("[[", j):
                depth += 1; j += 2
            elif text.startswith("]]", j):
                depth -= 1; j += 2
                if depth == 0:
                    break
            else:
                j += 1
        i = j
    out.append(text[i:])
    return "".join(out)


def clean(text: str) -> str:
    text = _COMMENT.sub("", text or "")
    text = _REF_PAIR.sub("", text)
    text = _REF_SELF.sub("", text)
    text = _TABLE.sub("", text)
    for _ in range(20):                       # templates nest; stop when nothing changes
        new = _TEMPLATE.sub("", text)
        if new == text:
            break
        text = new
    text = _drop_bracketed(text, _FILE_PREFIX)
    text = _LINK.sub(r"\2", text)
    text = _LINK_PLAIN.sub(r"\1", text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _EXT_BARE.sub("", text)
    text = _HEADING.sub(lambda m: "#" * len(m.group(1)) + " " + m.group(2), text)
    text = text.replace("'''", "").replace("''", "")
    text = _TAG.sub("", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()
