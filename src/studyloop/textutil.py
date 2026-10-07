"""Small text helpers shared by outline building, retrieval and quiz generation."""

from __future__ import annotations

import re

STOP = frozenset(
    """a about above after again against all also am an and any are aren't as at be because been
    before being below between both but by can can't cannot could did do does doing don't down
    during each few for from further had has have having he her here hers herself him himself his
    how i if in into is it its itself just let me more most my myself no nor not now of off on once
    only or other ought our ours ourselves out over own same shall she should so some such than
    that the their theirs them themselves then there these they this those through to too under
    until up upon us very was we were what when where which while who whom why will with would you
    your yours yourself yourselves one two may must thus yet shall therefore whose whether many much
    even every ever still say said say says see seen make made get got go goes going come came like
    well let us way thing things upon though although""".split()
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]|\d+(?:\.\d+)?")
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
_ABBREV = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc|Fig|fig|No|no|Vol|vol|cf|i\.e|e\.g|Sir|Messrs)\.$"
)


def _strip_e(w: str) -> str:
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def stem(word: str) -> str:
    """A deliberately small suffix stripper: burn/burns/burning, candle/candles meet."""
    w = word.lower()
    if len(w) <= 3:
        return w
    for suf, rep in (
        ("ational", "ate"), ("ization", "ize"), ("ically", "ic"), ("ies", "y"), ("sses", "ss"),
        ("ings", ""), ("ing", ""), ("edly", ""), ("ed", ""), ("ly", ""), ("es", ""), ("s", ""),
    ):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            if suf == "s" and w.endswith(("ss", "us", "is")):
                return _strip_e(w)
            base = w[: -len(suf)] + rep
            if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return _strip_e(base)
    return _strip_e(w)


def tokens(text: str, *, keep_stop: bool = False) -> list[str]:
    out = []
    for m in _WORD.findall(text.lower()):
        m = m.strip("-'")
        if not m or (not keep_stop and m in STOP):
            continue
        out.append(stem(m))
    return out


def raw_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text) if w]


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) inside ``text``, whitespace trimmed."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENT_SPLIT.finditer(text):
        end = m.start() + len(text[m.start() : m.end()].rstrip())
        chunk = text[pos:end]
        if _ABBREV.search(chunk.rstrip()):
            continue
        s = pos + (len(chunk) - len(chunk.lstrip()))
        if end > s:
            spans.append((s, end))
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        s = pos + (len(tail) - len(tail.lstrip()))
        spans.append((s, pos + len(tail.rstrip())))
    return spans


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate(haystack: str, needle: str) -> tuple[int, int] | None:
    """Find ``needle`` in ``haystack`` tolerating only whitespace and case differences.

    Re-implements the quote location of rag-forge (generate/citations.py): the returned span
    indexes the *original* haystack, so ``haystack[a:b]`` is the real source text.
    """
    needle = needle.strip()
    if not needle:
        return None
    i = haystack.find(needle)
    if i != -1:
        return i, i + len(needle)
    idx: list[int] = []
    chars: list[str] = []
    prev_space = True
    for k, ch in enumerate(haystack):
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
                idx.append(k)
            prev_space = True
        else:
            chars.append(ch.lower())
            idx.append(k)
            prev_space = False
    target = normalise_space(needle).lower()
    pos = "".join(chars).find(target)
    if pos == -1:
        return None
    return idx[pos], idx[pos + len(target) - 1] + 1
