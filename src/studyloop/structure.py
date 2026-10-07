"""Markdown -> course: chapters -> topics -> paragraphs, every unit carrying character offsets
into the book's markdown so a quote can always be located in the source.

Where the markdown has headings they are the structure. Where a chapter has no sub-headings it
is cut into topics by lexical cohesion (a TextTiling-style similarity dip between paragraph
windows), and the topics are named from the chapter title's own "A - B - C" list when it has
one, otherwise from the segment's most distinctive words.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .textutil import raw_words, split_sentences, tokens

HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^\s*(```|~~~)")
DASH_SPLIT = re.compile(r"\s+[—–]\s+|\s+--\s+")

MIN_TOPIC_WORDS = 450  # a heading-less chapter shorter than this stays one topic
TARGET_TOPIC_WORDS = 350


@dataclass
class Para:
    start: int
    end: int
    text: str
    kind: str  # text | list | code | table | quote | heading

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class ParsedTopic:
    title: str
    paras: list[Para] = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.paras[0].start if self.paras else 0

    @property
    def end(self) -> int:
        return self.paras[-1].end if self.paras else 0

    @property
    def n_words(self) -> int:
        return sum(p.words for p in self.paras)


@dataclass
class ParsedChapter:
    title: str
    topics: list[ParsedTopic] = field(default_factory=list)


@dataclass
class ParsedBook:
    title: str
    chapters: list[ParsedChapter]


def _classify(block: str) -> str:
    first = block.lstrip().split("\n", 1)[0]
    if FENCE.match(first):
        return "code"
    if HEADING.match(first):
        return "heading"
    lines = [ln for ln in block.split("\n") if ln.strip()]
    if lines and all(ln.lstrip().startswith("|") for ln in lines):
        return "table"
    if lines and all(ln.lstrip().startswith(">") for ln in lines):
        return "quote"
    if lines and all(re.match(r"^\s*([-*+]|\d+[.)])\s+", ln) for ln in lines):
        return "list"
    return "text"


def split_blocks(md: str, lo: int, hi: int) -> list[Para]:
    """Blank-line separated blocks of ``md[lo:hi]`` with absolute offsets; fenced code is one block."""
    paras: list[Para] = []
    pos = lo
    cur_start: int | None = None
    cur_end = lo
    in_fence = False
    for ln in md[lo:hi].split("\n"):
        line_end = pos + len(ln)
        if FENCE.match(ln):
            in_fence = not in_fence
        if ln.strip() or in_fence:
            if cur_start is None:
                cur_start = pos
            cur_end = line_end
        elif cur_start is not None:
            text = md[cur_start:cur_end]
            paras.append(Para(cur_start, cur_end, text, _classify(text)))
            cur_start = None
        pos = line_end + 1
    if cur_start is not None:
        text = md[cur_start:cur_end]
        paras.append(Para(cur_start, cur_end, text, _classify(text)))
    return paras


def _headings(md: str) -> list[tuple[int, str, int, int]]:
    """(level, title, line start, line end) for every ATX heading outside code fences."""
    out = []
    pos = 0
    in_fence = False
    for ln in md.split("\n"):
        if FENCE.match(ln):
            in_fence = not in_fence
        elif not in_fence:
            m = HEADING.match(ln)
            if m:
                title = re.sub(r"[*_`]+", "", m.group(2)).strip()
                if title:
                    out.append((len(m.group(1)), title, pos, pos + len(ln)))
        pos += len(ln) + 1
    return out


def _tf(paras: list[Para]) -> Counter:
    c: Counter = Counter()
    for p in paras:
        c.update(tokens(p.text))
    return c


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def split_long(paras: list[Para], limit: int = 140, target: int = 90) -> list[Para]:
    """Cut paragraphs over ``limit`` words into runs of whole sentences of about ``target`` words.

    A lecture transcript is a few enormous paragraphs; topic boundaries need finer units. The
    pieces keep absolute offsets, so quotes and highlights still index the original markdown.
    """
    out: list[Para] = []
    for p in paras:
        if p.kind != "text" or p.words <= limit:
            out.append(p)
            continue
        spans = split_sentences(p.text)
        run_start = None
        run_end = 0
        count = 0
        for a, b in spans:
            if run_start is None:
                run_start = a
            run_end = b
            count += len(p.text[a:b].split())
            if count >= target:
                out.append(Para(p.start + run_start, p.start + run_end, p.text[run_start:run_end], "text"))
                run_start, count = None, 0
        if run_start is not None:
            piece = Para(p.start + run_start, p.start + run_end, p.text[run_start:run_end], "text")
            if out and out[-1].end <= piece.start and piece.words < 30 and out[-1].kind == "text":
                prev = out[-1]
                out[-1] = Para(prev.start, piece.end, p.text[prev.start - p.start : run_end], "text")
            else:
                out.append(piece)
    return out


def tile(paras: list[Para], k: int) -> list[list[Para]]:
    """Cut ``paras`` into at most ``k`` runs at the deepest cohesion dips.

    Each run keeps at least ~60 words and two paragraphs when the text allows it.
    """
    n = len(paras)
    if k <= 1 or n < 4:
        return [paras]
    w = 3
    tfs = [_tf([p]) for p in paras]
    gaps: list[tuple[float, int]] = []  # (similarity, index of first paragraph after the gap)
    for i in range(1, n):
        left: Counter = Counter()
        right: Counter = Counter()
        for t in tfs[max(0, i - w) : i]:
            left.update(t)
        for t in tfs[i : i + w]:
            right.update(t)
        gaps.append((_cos(left, right), i))
    words = [p.words for p in paras]
    floor = max(60.0, 0.45 * sum(words) / k)
    cuts: list[int] = []

    def ok(i: int) -> bool:
        bounds = sorted([0, *cuts, i, n])
        for a, b in zip(bounds, bounds[1:], strict=False):
            if b - a < 2 or sum(words[a:b]) < floor:
                return False
        return True

    for _, i in sorted(gaps):
        if len(cuts) >= k - 1:
            break
        if ok(i):
            cuts.append(i)
    bounds = sorted([0, *cuts, n])
    return [paras[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]


def _name_segments(segs: list[list[Para]], chapter_title: str) -> list[str]:
    tfs = [_tf(s) for s in segs]
    df: Counter = Counter()
    for t in tfs:
        df.update(set(t))
    surface: dict[str, Counter] = {}
    for s in segs:
        for p in s:
            for w in raw_words(p.text):
                tk = tokens(w)
                if tk:
                    surface.setdefault(tk[0], Counter())[w.lower()] += 1
    banned = set(tokens(chapter_title))
    names = []
    for t in tfs:
        scored = sorted(
            (
                (v * math.log(1 + len(tfs) / df[k]), k)
                for k, v in t.items()
                if len(k) > 3 and k not in banned
            ),
            reverse=True,
        )
        picks = [surface[k].most_common(1)[0][0].capitalize() for _, k in scored[:3]]
        names.append(", ".join(picks) or "Section")
    return names


def split_title(title: str) -> tuple[str, list[str]]:
    """``Lecture I: The Flame - Its Sources - Structure`` -> (``Lecture I``, [hints...])."""
    parts = [p.strip() for p in DASH_SPLIT.split(title) if p.strip()]
    if len(parts) < 3:
        return title, []
    label, _, rest = parts[0].partition(":")
    if rest.strip():
        return label.strip(), [rest.strip(), *parts[1:]]
    return parts[0], parts[1:]


def _group_hints(hints: list[str], k: int) -> list[str]:
    if k >= len(hints):
        return hints[:k]
    per = len(hints) / k
    return [" / ".join(hints[round(i * per) : round((i + 1) * per)]) for i in range(k)]


def segment_chapter(title: str, paras: list[Para]) -> tuple[str, list[ParsedTopic]]:
    """Return (chapter title, topics) for a chapter that has no sub-headings."""
    label, hints = split_title(title)
    shown = f"{label}: {hints[0]}" if hints and label != hints[0] else title
    body = split_long([p for p in paras if p.kind != "heading"] or paras)
    total = sum(p.words for p in body)
    if total < MIN_TOPIC_WORDS and not (hints and total >= 200):
        return shown, [ParsedTopic(title=shown, paras=body)]
    k = len(hints) if hints else round(total / TARGET_TOPIC_WORDS)
    k = max(2, min(k, 8, max(1, len(body) // 2)))
    segs = tile(body, k)
    if len(segs) == 1:
        return shown, [ParsedTopic(title=shown, paras=body)]
    names = _group_hints(hints, len(segs)) if hints else _name_segments(segs, title)
    seen: Counter = Counter()
    topics = []
    for n, s in zip(names, segs, strict=True):
        seen[n] += 1
        topics.append(ParsedTopic(title=n if seen[n] == 1 else f"{n} (continued)", paras=s))
    return shown, topics


def parse_course(md: str, fallback_title: str = "Untitled") -> ParsedBook:
    heads = _headings(md)
    title = fallback_title
    body_start = 0
    if heads and heads[0][0] == 1 and sum(1 for h in heads if h[0] == 1) == 1:
        title = heads[0][1]
        body_start = heads[0][3] + 1
        heads = heads[1:]
    if not heads:
        paras = split_blocks(md, body_start, len(md))
        ctitle, topics = segment_chapter(title, paras)
        return ParsedBook(title, [ParsedChapter(ctitle, topics)] if paras else [])
    ch_level = min(h[0] for h in heads)
    chap_idx = [i for i, h in enumerate(heads) if h[0] == ch_level]
    chapters: list[ParsedChapter] = []
    front = [p for p in split_blocks(md, body_start, heads[chap_idx[0]][2]) if p.kind != "heading"]
    if sum(p.words for p in front) >= 60:
        chapters.append(ParsedChapter("Introduction", [ParsedTopic("Introduction", front)]))
    for n, ci in enumerate(chap_idx):
        ctitle, c_end = heads[ci][1], heads[ci][3]
        nxt = chap_idx[n + 1] if n + 1 < len(chap_idx) else len(heads)
        region_end = heads[nxt][2] if nxt < len(heads) else len(md)
        subs = [i for i in range(ci + 1, nxt) if heads[i][0] == ch_level + 1]
        if not subs:
            paras = split_blocks(md, c_end + 1, region_end)
            if any(p.kind == "text" for p in paras):
                title_out, topics = segment_chapter(ctitle, paras)
                chapters.append(ParsedChapter(title_out, topics))
            continue
        topics = []
        lead = [p for p in split_blocks(md, c_end + 1, heads[subs[0]][2]) if p.kind != "heading"]
        if sum(p.words for p in lead if p.kind == "text") >= 40:
            topics.append(ParsedTopic("Overview", lead))
        for j, si in enumerate(subs):
            s_end = heads[subs[j + 1]][2] if j + 1 < len(subs) else region_end
            paras = split_blocks(md, heads[si][3] + 1, s_end)
            if any(p.kind == "text" for p in paras):
                topics.append(ParsedTopic(heads[si][1], paras))
        if topics:
            chapters.append(ParsedChapter(ctitle, topics))
    return ParsedBook(title, chapters)
