"""Key concepts per topic, a one-line summary and defining sentences. No model needed.

A concept is a word or two-word phrase that is frequent in the topic but not in every topic
(tf x idf over the book's topics), boosted when the author emphasised it (bold/italic) or
defined it ("X is called ...", "known as X").
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .textutil import STOP, split_sentences, stem

WORD = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
EMPH = re.compile(r"(?<![*\w])(\*\*|__|\*|_)([A-Za-z][A-Za-z \-]{2,40}?)\1(?![*\w])")
DEFINE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:called|termed|known as|named)\b|\b(?:called|termed|known as|"
    r"defined as|we call|is said to be|means)\b|\b(?:is|are)\s+(?:a|an|the)\b",
    re.I,
)
STRONG_DEFINE = re.compile(
    r"\b(?:called|termed|known as|defined as|we call|is said to be|means)\b", re.I
)
NOUNISH = ("tion", "sion", "ment", "ity", "ness", "ance", "ence", "ism", "ics", "ure", "gen",
           "ide", "ium", "ate", "ogy", "ics", "ron", "ine", "one", "ase", "ose", "ent", "er", "or")
WEAK = frozenset(
    """keeps runs cast curious beautiful careful carefully according varying middle kinds shews
    shew shown shows takes taken puts goes gets gives given look looks seems seem become becomes
    called named known think thought found find finds tell told asked ask pass passes passed
    remain remains remained appear appears appeared bring brings brought hold holds held
    begin begins began turn turns turned light lights lighted great large small little long
    short high low good better best whole several certain various other another same first
    second third last next particular perfectly perfect proper properly regular regularly
    illustrations illustration experiment experiments subject subjects towards changes lower
    minds examination produced produce""".split()
)
GENERIC = frozenset(
    "thing things time times part parts case cases place way ways kind sort number point "
    "lecture chapter section figure example course matter fact fact certain different same "
    "great small large little first second third next last good form body".split()
)


@dataclass
class Concept:
    term: str
    score: float
    tf: int
    definition: str | None = None

    def as_dict(self) -> dict:
        return {
            "term": self.term,
            "score": round(self.score, 3),
            "tf": self.tf,
            "definition": self.definition,
        }


def _clean(md: str) -> str:
    md = re.sub(r"`[^`]*`", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    return md


def _surface_counts(text: str) -> tuple[Counter, Counter, Counter]:
    """(unigram stem counts, bigram stem-pair counts, capitalised-mid-sentence counts)."""
    uni: Counter = Counter()
    bi: Counter = Counter()
    caps: Counter = Counter()
    for a, b in split_sentences(text):
        sent = text[a:b]
        ws = [(m.group(0), m.start()) for m in WORD.finditer(sent)]
        prev = None
        for i, (w, pos) in enumerate(ws):
            lw = w.lower()
            keep = (
                lw not in STOP and lw not in GENERIC and lw not in WEAK and len(lw) >= 4
                and not lw.endswith("ly")
            )
            if keep:
                uni[lw] += 1
                if w[0].isupper() and i > 0:
                    caps[lw] += 1
                if prev is not None and prev[1] == i - 1 and sent[prev[2] : pos].strip() == "":
                    bi[(prev[0], lw)] += 1
                prev = (lw, i, pos + len(w))
            else:
                prev = None
    return uni, bi, caps


def extract(
    topic_texts: list[str], top_k: int = 8
) -> tuple[list[list[Concept]], list[str]]:
    """Concepts for every topic text, plus a one-sentence summary per topic."""
    n = len(topic_texts)
    cleaned = [_clean(t) for t in topic_texts]
    counts = [_surface_counts(t) for t in cleaned]
    df: Counter = Counter()
    for uni, bi, _ in counts:
        df.update(set(uni))
        df.update({f"{a} {b}" for (a, b) in bi})
    out: list[list[Concept]] = []
    summaries: list[str] = []
    for text, (uni, bi, caps) in zip(cleaned, counts, strict=True):
        emph = {m.group(2).strip().lower() for m in EMPH.finditer(text)}
        sentences = [text[a:b] for a, b in split_sentences(text)]
        cands: dict[str, tuple[float, int]] = {}
        for w, tf in uni.items():
            d = df[w]
            if n >= 4 and d / n > 0.7:
                continue
            boost = 2.0 if w in emph else 1.0
            if tf < 2 and boost == 1.0:
                continue
            if boost == 1.0 and w.endswith(("ing", "ed")):
                continue
            if w.endswith(NOUNISH):
                boost *= 1.3
            proper = 0.6 if caps[w] >= max(1, tf * 0.7) else 1.0
            s = (1 + math.log(tf)) * math.log(1 + n / d) * boost * proper
            cands[w] = (s, tf)
        for (a, b), tf in bi.items():
            key = f"{a} {b}"
            if tf < 2 and key not in emph:
                continue
            if key not in emph and tf / min(uni[a], uni[b]) < 0.4:
                continue  # the two words mostly occur apart: not a collocation
            if key not in emph and (
                a.endswith(("ed", "ing")) or b.endswith(("ed", "ing"))
                or (a.endswith("s") and not a.endswith(("ss", "us", "is", "ics")))
            ):
                continue  # verb + noun, or a plural + word: rarely a term
            d = df[key]
            boost = 2.0 if key in emph else 1.0
            s = 1.6 * (1 + math.log(tf)) * math.log(1 + n / d) * boost
            cands[key] = (s, tf)
        for e in emph:
            if e not in cands and 3 <= len(e) <= 40 and e not in STOP:
                cands[e] = (2.5, 1)
        ranked = sorted(cands.items(), key=lambda kv: -kv[1][0])
        chosen: list[Concept] = []
        for term, (s, tf) in ranked:
            parts = term.split()
            if any(stem(term) == stem(c.term) for c in chosen):
                continue
            # A unigram already inside a chosen phrase, or a phrase built on a chosen word, adds nothing.
            if any(
                (len(parts) == 1 and term in c.term.split())
                or (len(c.term.split()) == 1 and c.term in parts and tf <= 3)
                for c in chosen
            ):
                continue
            chosen.append(Concept(term, s, tf, _definition(term, sentences)))
            if len(chosen) >= top_k:
                break
        out.append(chosen)
        summaries.append(_summary(sentences, chosen))
    return out, summaries


def _definition(term: str, sentences: list[str]) -> str | None:
    pat = re.compile(r"\b" + re.escape(term) + r"\w*\b", re.I)
    best: tuple[int, str] | None = None
    for s in sentences:
        words = len(s.split())
        if not 6 <= words <= 45:
            continue
        m = pat.search(s)
        if not m:
            continue
        score = 0
        if STRONG_DEFINE.search(s):
            score += 2
        elif DEFINE.search(s):
            score += 1
        if m.start() < 40:
            score += 1
        if best is None or score > best[0]:
            best = (score, s.strip())
    return best[1] if best and best[0] >= 2 else None


def _summary(sentences: list[str], concepts: list[Concept]) -> str:
    if not sentences:
        return ""
    weight = {c.term: c.score for c in concepts}
    best, best_s = "", -1.0
    for i, s in enumerate(sentences):
        words = len(s.split())
        if not 8 <= words <= 40:
            continue
        low = s.lower()
        score = sum(w for t, w in weight.items() if t in low) / math.sqrt(words)
        score *= 1.15 if i < 3 else 1.0
        if score > best_s:
            best, best_s = s.strip(), score
    return best or sentences[0].strip()
