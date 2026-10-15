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
        ("ational", "ate"), ("ization", "ize"), ("ically", "ic"), ("ness", ""), ("ies", "y"),
        ("sses", "ss"),
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
    """Search tokens: lower-case stems, stop words dropped. A hyphenated compound counts as its
    parts, so "soap bubble" finds "soap-bubble" and "lime water" finds "lime-water"."""
    out = []
    for word in _WORD.findall(text.lower()):
        for m in word.split("-"):
            m = m.strip("'")
            if not m or (not keep_stop and m in STOP):
                continue
            out.append(stem(m))
    return out


_HAS_WORD = re.compile(r"\w")


def count_words(text: str) -> int:
    """Words as a reader counts them: whitespace-separated tokens holding a letter or a digit, so
    markdown markers (``##``, ``-``, ``|``, ``---``) and stray punctuation are not words."""
    return sum(1 for w in text.split() if _HAS_WORD.search(w))


def token_positions(text: str) -> list[tuple[int, str]]:
    """``tokens`` with the index of the word each came from: the parts of "twenty-four" share one
    position, so a hyphenated compound does not push its neighbours apart."""
    out = []
    pos = 0
    for word in _WORD.findall(text.lower()):
        kept = False
        for m in word.split("-"):
            m = m.strip("'")
            if m and m not in STOP:
                out.append((pos, stem(m)))
                kept = True
        pos += kept
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
