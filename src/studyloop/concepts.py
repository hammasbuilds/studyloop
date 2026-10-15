"""Key concepts per topic, a one-line summary and defining sentences. No model needed.

A concept is a word or two-word phrase that is frequent in the topic but not in every topic
(tf x idf over the book's topics), boosted when the author emphasised it (bold/italic) or
defined it ("X is called ...", "known as X"). A word the book uses mostly as a verb or an adjective
("I hope", "is necessary") is not a concept: the word before each use is the evidence.
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
    minds examination produced produce fresh burst measure measures fluted shaped indifferent""".split()
)
# Function words the stopword list leaves out; never a concept on their own or inside a phrase.
FUNCTION = frozenset(
    """till unless whilst within without behind beyond upwards downwards towards toward quite
    rather almost perhaps indeed instead besides around across along beside onto amongst among
    present inside outside beneath underneath nearly however none nevertheless moreover otherwise
    whatever whenever wherever somewhat already always often sometimes together enough""".split()
)
# Irregular past participles: they follow "is/are" like adjectives and never name a thing.
PARTICIPLES = frozenset(
    """built known shown seen given taken made done gone grown thrown drawn blown worn torn born
    kept left sent spent lost held told sold brought bought caught taught thought found bound
    ground wound split spread shut struck stuck hung led fed bred laid paid said heard meant
    understood written driven risen frozen chosen broken spoken stolen fallen""".split()
)
# Words ending in -ic that are things, not qualities.
IC_NOUNS = frozenset("arsenic logic music topic fabric clinic panic mechanic critic tunic".split())
NUMBER = re.compile(
    r"^(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|"
    r"fifty|sixty|seventy|eighty|ninety|hundred|thousand)(?:-\w+)?$"
)
ADJ_SUFFIX = ("less", "ful")
# Word-class evidence from the word before: a determiner points to a noun, a pronoun, modal or
# "to" to a verb ("I hope", "to melt"), a copula or degree word to an adjective ("is necessary").
_DET = frozenset(
    "the a an this that these those its our their his her my your some any no each every of in on "
    "with by from into such".split()
)
_VERB_PREV = frozenset(
    "i we you they he she it will shall can may must should would could to not did do does let "
    "cannot might who which".split()
)
_ADJ_PREV = frozenset("is are was were be been being very so too quite rather become becomes seem seems".split())
_TOK = re.compile(r"[A-Za-z][A-Za-z\-']*|[.,;:!?—]")

GENERIC = frozenset(
    "thing things time times part parts case cases place way ways kind sort number point "
    "lecture chapter section figure example course matter fact fact certain different same "
    "great small large little first second third next last good form body occasion success "
    "search experience presence relation hours hour portion operations operation processes "
    "preparation heap sides side hands hand finger fingers edge game power powers intensity "
    "instance instances direction directions extent abundance union phenomena years year".split()
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


def _surface_counts(text: str) -> tuple[Counter, Counter, Counter, dict[str, Counter]]:
    """(unigram counts, bigram counts, capitalised-mid-sentence counts, surface forms).

    Unigrams are counted per stem, so "spring" and "springs" are one concept with one count; the
    surface forms seen for each stem are returned so the commonest one can be shown. A bigram is
    keyed on its first word and the stem of its last ("oxbow lake", "oxbow lakes").
    """
    uni: Counter = Counter()
    bi: Counter = Counter()
    caps: Counter = Counter()
    surface: dict[str, Counter] = {}
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
                k = stem(lw)
                uni[k] += 1
                surface.setdefault(k, Counter())[lw] += 1
                if w[0].isupper() and i > 0:
                    caps[k] += 1
                if prev is not None and prev[1] == i - 1 and sent[prev[2] : pos].strip() == "":
                    bi[(prev[0], k)] += 1
                    surface.setdefault(f"{prev[0]} {k}", Counter())[f"{prev[0]} {lw}"] += 1
                prev = (lw, i, pos + len(w))
            else:
                prev = None
    return uni, bi, caps, surface


def word_class_evidence(texts: list[str]) -> dict[str, tuple[float, int]]:
    """Per lower-case word: (noun evidence, verb or adjective evidence) over the whole book.

    A determiner before the word counts 1 when the word ends the phrase ("the current.") and 0.5
    when another content word follows ("the dark part", a modifier). No tagger, no model.
    """
    noun: Counter = Counter()
    other: Counter = Counter()
    for text in texts:
        toks = [t.lower() for t in _TOK.findall(text)]
        for i, t in enumerate(toks):
            prev = toks[i - 1] if i else "."
            nxt = toks[i + 1] if i + 1 < len(toks) else "."
            if prev in _DET:
                noun[t] += 0.5 if nxt[0].isalpha() and nxt not in STOP else 1.0
            elif prev in _VERB_PREV or prev in _ADJ_PREV:
                other[t] += 1
    return {w: (noun[w], other[w]) for w in set(noun) | set(other)}


def _not_a_noun(
    word: str, ev: dict[str, tuple[float, int]], forms: Counter | None = None, modifier: bool = False
) -> bool:
    """True when the book uses the word mostly as a verb or an adjective (hope, melt, necessary).

    ``forms`` (every surface of the word's stem) pools the evidence: "the springs" counts for
    "spring". ``modifier`` is the first word of a phrase, which may be an adjective or a participle
    ("carbonic acid", "chemical action", "known quantity")."""
    if word in FUNCTION or NUMBER.match(word) or word.endswith(ADJ_SUFFIX):
        return True
    if not modifier and (word in PARTICIPLES or ("-" in word and word.split("-")[-1] in PARTICIPLES)):
        return True  # "built", "well-known": a verb form, not a thing
    if not modifier and word.endswith(("ic", "ical")) and word not in IC_NOUNS:
        return True  # "metallic", "chemical": adjectives
    if word.endswith(("er", "est")) and any(word[:-k] in WEAK for k in (1, 2, 3, 4)):
        return True  # larger, smallest, bigger: a comparison, not a thing
    n, o = _evidence(forms, ev) if forms else ev.get(word, (0.0, 0))
    return o > 0 and o >= n


def _evidence(forms: Counter, ev: dict[str, tuple[float, int]]) -> tuple[float, int]:
    n = sum(ev.get(f, (0.0, 0))[0] for f in forms)
    o = sum(ev.get(f, (0.0, 0))[1] for f in forms)
    return n, o


def _shown(forms: Counter) -> str:
    """The surface to show: the commonest, and the shorter (singular) one on a tie."""
    return sorted(forms.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]


def extract(
    topic_texts: list[str], top_k: int = 8, titles: list[str] | None = None
) -> tuple[list[list[Concept]], list[str]]:
    """Concepts for every topic text, plus a one-sentence summary per topic.

    ``titles`` (the topics' headings) is evidence too: a word the heading names is a concept of
    its topic even when the text uses it once ("### Meanders" over "A meander is a bend").
    """
    n = len(topic_texts)
    titles = titles or [""] * n
    cleaned = [_clean(t) for t in topic_texts]
    counts = [_surface_counts(t) for t in cleaned]
    ev = word_class_evidence(cleaned)
    df: Counter = Counter()
    for uni, bi, _, _ in counts:
        df.update(set(uni))
        df.update({f"{a} {b}" for (a, b) in bi})
    out: list[list[Concept]] = []
    summaries: list[str] = []
    for text, title, (uni, bi, caps, surface) in zip(cleaned, titles, counts, strict=True):
        emph = {m.group(2).strip().lower() for m in EMPH.finditer(text)}
        emph_stems = {" ".join(stem(x) for x in e.split()) for e in emph}
        named = {stem(w.lower()) for w in WORD.findall(title)}
        sentences = [text[a:b] for a, b in split_sentences(text)]
        cands: dict[str, tuple[float, int]] = {}
        for k, tf in uni.items():
            forms = surface[k]
            w = _shown(forms)
            d = df[k]
            if n >= 4 and d / n > 0.7:
                continue
            boost = 2.0 if k in emph_stems else 1.0
            if boost == 1.0 and _not_a_noun(w, ev, forms):
                continue
            in_title = k in named
            if boost == 1.0 and not in_title and w.endswith(("ing", "ed")):
                continue  # "burning", "heated": a verb form, unless the heading names it ("Springs")
            if tf < 2 and boost == 1.0 and not (
                (in_title and _evidence(forms, ev)[0] > 0) or _defines(w, sentences)
            ):
                continue  # once is enough when the heading names it or a sentence defines it
            if in_title:
                boost *= 1.5
            if w.endswith(NOUNISH):
                boost *= 1.3
            if sum(_evidence(forms, ev)) == 0:
                boost *= 0.7  # never seen after a determiner, pronoun or copula: weak evidence
            proper = 0.6 if caps[k] >= max(1, tf * 0.7) else 1.0
            s = (1 + math.log(tf)) * math.log(1 + n / d) * boost * proper
            cands[w] = (s, tf)
        for (a, b), tf in bi.items():
            forms = surface[f"{a} {b}"]
            key = _shown(forms)
            last = key.split()[1]
            if tf < 2 and key not in emph:
                continue
            if key not in emph and tf / min(uni[stem(a)], uni[b]) < 0.4:
                continue  # the two words mostly occur apart: not a collocation
            if key not in emph and (
                a.endswith(("ed", "ing")) or last.endswith(("ed", "ing"))
                or (a.endswith("s") and not a.endswith(("ss", "us", "is", "ics")))
            ):
                continue  # verb + noun, or a plural + word: rarely a term
            if key not in emph and (_not_a_noun(a, ev, modifier=True) or _not_a_noun(last, ev, surface[b])):
                continue  # "send steam", "water weighs", "quite full", "five cubes"
            d = df[f"{a} {b}"]
            boost = 2.0 if key in emph else 1.0
            if stem(a) in named and b in named:
                boost *= 1.5
            s = 1.6 * (1 + math.log(tf)) * math.log(1 + n / d) * boost
            cands[key] = (s, tf)
        for e in emph:
            if e not in cands and 3 <= len(e) <= 40 and e not in STOP:
                cands[e] = (2.5, 1)
        ranked = sorted(cands.items(), key=lambda kv: -kv[1][0])
        chosen: list[Concept] = []
        for term, (s, tf) in ranked:
            parts = {stem(x) for x in term.split()}
            if any(stem(term) == stem(c.term) for c in chosen):
                continue
            # A unigram already inside a chosen phrase, or a phrase built on a chosen word, adds nothing.
            if any(
                (len(parts) == 1 and stem(term) in {stem(x) for x in c.term.split()})
                or (len(c.term.split()) == 1 and stem(c.term) in parts and tf <= 3)
                for c in chosen
            ):
                continue
            chosen.append(Concept(term, s, tf, _definition(term, sentences)))
            if len(chosen) >= top_k:
                break
        out.append(chosen)
        summaries.append(_summary(sentences, chosen))
    return out, summaries


_NAMING = r"(?:called|termed|known as|named|we call|is said to be|defined as)"


def _best_definition(term: str, sentences: list[str]) -> tuple[int, int, str] | None:
    """A sentence that defines the term itself: "known as T", "T is a ...", "T means", "T, that is".

    The defining words must sit next to the term. "...clouds of wool, as it was called" or "this is
    a metal" mention the term in a sentence that defines something else, and give no flashcard.
    """
    t = r"\b" + re.escape(term).replace(" ", r"\s+") + r"(?:s|es)?\b"
    q = "[“”\"']?"
    patterns = [
        (3, re.compile(_NAMING + r"\s+(?:the\s+|a\s+|an\s+)?" + q + t, re.I)),
        (3, re.compile(t + q + r"\s*,?\s+(?:is|are|was|were)\s+" + _NAMING, re.I)),
        (3, re.compile(t + q + r"\s+(?:means|signifies)\b", re.I)),
        (2, re.compile(r"^\W*(?:the\s+)?" + t + q + r"\s+(?:is|are|was|were)\s+(?:a|an|the|what|that|made|nothing)\b", re.I)),
        (2, re.compile(t + q + r"\s*(?:,|—|:|\()\s*(?:that is|i\.e\.|namely)\s", re.I)),
        # The term as the subject of its sentence: a description, weaker than a definition.
        (1, re.compile(r"^\W*(?:(?:now|so|then|but|and|here),?\s+)?(?:the\s+|this\s+|our\s+|a\s+|an\s+)?" + t + q
                       + r"\s+(?:is|are|was|were|has|have|will|can|does|do|gives|give|contains|consists|becomes|"
                       r"burns|forms|acts|combines|unites|makes|produces)\b", re.I)),
    ]
    best: tuple[int, int, str] | None = None
    for s in sentences:
        words = len(s.split())
        if not 6 <= words <= 45:
            continue
        score = max((w for w, p in patterns if p.search(s)), default=0)
        if score and (best is None or (score, -words) > best[:2]):
            best = (score, -words, s.strip())
    return best


def _defines(term: str, sentences: list[str]) -> bool:
    """A sentence whose subject is the term ("A delta is a landform ...") or that names it at the
    end of a clause ("... is called lava."). Stricter than ``_definition``: "is called an infinite
    loop" defines the phrase, not "infinite", and "a loop that never ends is called" defines nothing
    called "ends"."""
    t = re.escape(term).replace(r"\ ", r"\s+") + r"(?:s|es)?"
    subject = re.compile(r"^\W*(?:an?\s+|the\s+)?" + t + r"\s+(?:is|are)\s+(?:an?|the)\s", re.I)
    named = re.compile(_NAMING + r"\s+(?:an?\s+|the\s+)?" + t + r"\s*(?:[.,;:)]|$)", re.I)
    return any(subject.search(s) or named.search(s) for s in sentences)


def _definition(term: str, sentences: list[str]) -> str | None:
    best = _best_definition(term, sentences)
    return best[2] if best else None





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
    return _plain(best or sentences[0].strip())


_MARK = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")  # an underscore inside a word (snake_case) stays


def _plain(sentence: str) -> str:
    """The summary is shown as plain text: emphasis markers go, including one left open where
    a sentence split an italic paragraph ("*Michael Faraday, a course of six lectures ...")."""
    return re.sub(r"\s+", " ", _MARK.sub("", sentence)).strip()
