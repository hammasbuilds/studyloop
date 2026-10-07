"""Urdu and Roman Urdu questions -> English search terms for an English book.

What it does, in order, for every content word of the question:

1. normalise (urdunlp: Arabic/Urdu letter forms, PDF presentation forms, digits);
2. look the word up in a small bilingual study glossary (Urdu script and the common Roman
   spellings, matched through urdunlp's ``roman_key`` and ``stem`` so ``pani``/``paani`` and
   ``jalti``/``jalta``/``jalna`` meet);
3. keep Latin words that occur in the book (Roman Urdu is full of English: "candle kyun jalti hai");
4. otherwise try a consonant-skeleton match against the book's vocabulary, which recovers
   loanwords written phonetically (``آکسیجن`` / ``oksijan`` -> oxygen).

It does not translate sentences. A word that none of the four steps resolves is reported back
as ignored, so the user sees what the search actually used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._vendor import urdunlp as u
from .textutil import STOP, stem

URDU_LETTERS = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

# (english search terms, Urdu spellings, Roman Urdu spellings)
GLOSSARY: list[tuple[str, str, str]] = [
    ("candle wax", "موم", "mom"),
    ("candle", "بتی موم_بتی شمع", "batti mombatti mom_batti shama shamma"),
    ("flame", "شعلہ شعلے لو", "shola sholay shoala shole lau"),
    ("fire burn", "آگ", "aag ag"),
    ("burn burning combustion", "جلنا جلتی جلتا جلتے جلا جل جلانا جلاؤ", "jalna jalti jalta jalte jala jal jalana"),
    ("water", "پانی", "pani paani"),
    ("air", "ہوا", "hawa hava"),
    ("oxygen", "آکسیجن اکسیجن", "oxygen oksijan aksijan"),
    ("hydrogen", "ہائیڈروجن", "hydrogen haidrojan haidrojin"),
    ("carbon charcoal", "کاربن", "carbon karbon"),
    ("carbonic acid carbon dioxide", "کاربن_ڈائی_آکسائیڈ", "carbon_dioxide"),
    ("charcoal coal", "کوئلہ کوئلے", "koyla koyle"),
    ("light", "روشنی", "roshni raushni"),
    ("bright brightness luminous", "چمک چمکدار", "chamak chamakdar"),
    ("heat", "گرمی حرارت", "garmi harart hararat"),
    ("gas", "گیس", "gas"),
    ("acid", "تیزاب ایسڈ", "tezab tezaab acid"),
    ("metal", "دھات دھاتیں", "dhat dhaat dhatain"),
    ("iron", "لوہا لوہے", "loha lohe lohay"),
    ("zinc", "جست زنک", "jast zinc zink"),
    ("chalk marble lime", "چاک چونا", "chalk chuna"),
    ("atmosphere", "فضا ماحول", "fiza fizaa mahol"),
    ("respiration breathing breath", "سانس تنفس", "saans sans tanaffus"),
    ("plants", "پودے پودا پودوں", "paudhe paudha paudhon"),
    ("sugar", "چینی شکر", "cheeni chini shakar"),
    ("lungs", "پھیپھڑے", "phephre phephray"),
    ("smoke", "دھواں", "dhuan dhuwan dhuaan"),
    ("soot", "کالک راکھ", "kalak raakh rakh"),
    ("vapour steam", "بھاپ", "bhaap bhap"),
    ("liquid fluid", "مائع", "maye maae"),
    ("solid", "ٹھوس", "thos thoss"),
    ("chemical chemistry", "کیمیا کیمیائی کیمسٹری", "kimya kimiyai chemistry"),
    ("experiment", "تجربہ تجربے", "tajurba tajurbe tajriba"),
    ("energy", "توانائی", "tawanai tawanaai"),
    ("wick cotton", "بتی دھاگہ", "dhaaga dhaga"),
    ("melt melted", "پگھلنا پگھلتی پگھلتا پگھلا", "pighalna pighalti pighalta pighla"),
    ("battery", "بیٹری", "battery bettery"),
    ("electricity electric", "بجلی", "bijli"),
    ("pressure", "دباؤ", "dabao dabaao"),
    ("weight", "وزن", "wazan wazn"),
    ("bubbles bubble", "بلبلے", "bulbule bulbulay"),
    ("salt", "نمک", "namak"),
    ("earth", "زمین", "zameen zamin"),
    ("substance matter", "مادہ مادے", "madda maada"),
    ("particles", "ذرات", "zarrat zarraat"),
    ("product products", "پیداوار", "paidawar"),
    ("produce produced", "بنتا بنتی بنانا بنتے", "banta banti banana bante"),
    ("sun", "سورج", "suraj sooraj"),
    ("metal platinum", "پلاٹینم", "platinum"),
    ("lecture", "لیکچر", "lecture"),
    ("history", "تاریخ", "tareekh tarikh"),
    ("nature", "فطرت", "fitrat"),
    ("definition meaning", "تعریف مطلب معنی", "tareef matlab mani maani"),
    ("example", "مثال", "misaal misal"),
    ("reason cause because", "وجہ سبب", "wajah wajh sabab"),
    ("difference", "فرق", "farq"),
    ("process", "عمل", "amal"),
    ("property properties", "خصوصیات خاصیت", "khasiyat khasusiyat"),
    ("compound", "مرکب", "murakkab"),
    ("element", "عنصر", "unsar anasir"),
    ("vapor vapour", "بخارات", "bukharat"),
    ("tallow fat", "چربی", "charbi"),
    ("oil", "تیل", "tel teil"),
    ("lamp", "چراغ", "chirag"),
    ("current", "رو", "current"),
    ("temperature", "درجہ_حرارت", "darja_hararat temperature"),
    ("force attraction", "کشش", "kashish"),
    ("shadow", "سایہ", "saya saaya"),
    ("moon", "چاند", "chand"),
    ("sea", "سمندر", "samandar"),
]

# Roman Urdu function words that are not also common English words.
ROMAN_FUNCTION = frozenset(
    """hai hain hota hoti hote kya kyun kyon kyu kaise kese kaisay kaun kon kab kahan kitna kitni kitne
    ka ki ke mein se ko ne tha thi thay aur yeh ye woh wo mujhe mujhey batao bataiye bataye batayen
    samjhao samjhaye samjhain likho nahi nahin bhi sirf kuch sab jo jab tab toh kiya kia hua hui
    hue hoga hogi honge kar karta karti karte karna kaise kisko kisi kis iska iski uska uski
    unka unki inka inki apna apni liye lye wala wali wale""".split()
)
# Words that frame a question without being what it is about.
FILLER = frozenset(
    """need needs use used using work works mean means tell explain describe define definition
    happen happens happening difference example examples please give show know called name
    about says say author book text mention mentions""".split()
)
WH = {
    "why": "کیوں kyun kyon kyu why",
    "how": "کیسے kaise kese kaisay how",
    "what": "کیا kya kia what",
    "who": "کون kaun kon who",
    "when": "کب kab when",
    "where": "کہاں kahan where",
    "how much": "کتنا کتنی کتنے kitna kitni kitne",
}


def skeleton(word: str) -> str:
    """Consonant skeleton used for loanword matching: oksijan, oxygen -> ksjn."""
    w = word.lower()
    for a, b in (("x", "ks"), ("ph", "f"), ("ck", "k"), ("kh", "k"), ("gh", "g"), ("sh", "s"),
                 ("ch", "c"), ("th", "t"), ("q", "k"), ("w", "v"), ("z", "s"), ("c", "k"),
                 ("j", "g"), ("dg", "g")):
        w = w.replace(a, b)
    w = re.sub(r"[aeiouyh]", "", w)
    return re.sub(r"(.)\1+", r"\1", w)


def _keys_for_urdu(token: str) -> set[str]:
    n = u.normalize(token)
    return {n, u.stem(n)}


def _keys_for_roman(token: str) -> set[str]:
    t = token.lower()
    k = u.roman_key(t)
    return {t, k, u.stem(k)}


def _build_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for eng, ur, ro in GLOSSARY:
        for form in ur.split():
            for k in _keys_for_urdu(form.replace("_", " ")) | _keys_for_urdu(form):
                idx.setdefault(k, eng)
        for form in ro.split():
            for k in _keys_for_roman(form):
                idx.setdefault(k, eng)
    return idx


_INDEX = _build_index()
_QWORDS = {}
for _name, _forms in WH.items():
    for _f in _forms.split():
        _QWORDS[u.normalize(_f) if URDU_LETTERS.search(_f) else _f.lower()] = _name


@dataclass
class Analysis:
    original: str
    language: str  # en | ur | roman-ur | mixed
    normalised: str
    terms: list[str] = field(default_factory=list)  # English stems to search with
    mapped: list[dict] = field(default_factory=list)  # {"from", "to", "how"}
    ignored: list[str] = field(default_factory=list)
    intent: str | None = None

    def as_dict(self) -> dict:
        return {
            "original": self.original, "language": self.language, "normalised": self.normalised,
            "terms": self.terms, "mapped": self.mapped, "ignored": self.ignored,
            "intent": self.intent,
        }


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    urdu = sum(1 for c in letters if URDU_LETTERS.match(c))
    if urdu / len(letters) > 0.6:
        return "ur"
    if urdu:
        return "mixed"
    toks = re.findall(r"[a-z']+", text.lower())
    hits = sum(1 for t in toks if t in ROMAN_FUNCTION)
    if hits >= 1 and hits / max(1, len(toks)) >= 0.2:
        return "roman-ur"
    return "en"


@dataclass
class Vocab:
    """The book's English vocabulary: stems for direct matches, skeletons for sound-alikes."""

    stems: set[str] = field(default_factory=set)
    skeletons: dict[str, str] = field(default_factory=dict)


def analyse(question: str, vocab: Vocab | None = None) -> Analysis:
    vocab = vocab or Vocab()
    q = u.fix_spacing(u.normalize(question)) if URDU_LETTERS.search(question) else question
    lang = detect_language(question)
    a = Analysis(question, lang, q)
    if lang == "en":
        a.terms = _unique(stem(t) for t in re.findall(r"[A-Za-z][A-Za-z'\-]*", q.lower())
                          if t not in STOP and t not in FILLER and len(t) > 1)
        for w in re.findall(r"[A-Za-z]+", q.lower()):
            if w in ("why", "how", "what", "who", "when", "where"):
                a.intent = a.intent or w
        return a
    toks = [
        t.strip("؟،۔؛")
        for t in re.findall(
            r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+|[A-Za-z][A-Za-z'\-]*", q
        )
    ]
    toks = [t for t in toks if t]
    seen: list[str] = []
    skip = set()
    for i, pair in enumerate(zip(toks, toks[1:], strict=False)):
        # "موم بتی" / "mom batti" read as one word in the glossary.
        joined = pair[0] + "_" + pair[1]
        keys = _keys_for_urdu(joined) if URDU_LETTERS.search(joined) else _keys_for_roman(joined)
        hit = next((_INDEX[k] for k in keys if k in _INDEX), None)
        if hit:
            seen.append(hit)
            a.mapped.append({"from": f"{pair[0]} {pair[1]}", "to": hit, "how": "glossary"})
            skip.update({i, i + 1})
    for i, tok in enumerate(toks):
        if i in skip:
            continue
        is_urdu = bool(URDU_LETTERS.search(tok))
        low = u.normalize(tok) if is_urdu else tok.lower()
        if low in _QWORDS:
            a.intent = a.intent or _QWORDS[low]
            continue
        keys = _keys_for_urdu(tok) if is_urdu else _keys_for_roman(tok)
        hit = next((_INDEX[k] for k in keys if k in _INDEX), None)
        if hit:
            seen.append(hit)
            a.mapped.append({"from": tok, "to": hit, "how": "glossary"})
            continue
        if not is_urdu:
            if low in ROMAN_FUNCTION or low in STOP:
                continue
            if stem(low) in vocab.stems:
                seen.append(low)
                a.mapped.append({"from": tok, "to": low, "how": "english word"})
                continue
        elif u.is_stopword(low):
            continue
        sk = skeleton(low if not is_urdu else u.transliterate_to_roman(low))
        word = vocab.skeletons.get(sk) if len(sk) >= 3 else None
        if word:
            seen.append(word)
            a.mapped.append({"from": tok, "to": word, "how": "sound-alike"})
        else:
            a.ignored.append(tok)
    stems: list[str] = []
    for phrase in seen:
        stems.extend(stem(w) for w in phrase.split() if w not in STOP)
    a.terms = _unique(stems)
    return a


def book_vocab(words: list[str]) -> Vocab:
    from collections import Counter

    cnt = Counter(w.lower() for w in words if len(w) > 3 and w.lower() not in STOP)
    v = Vocab(stems={stem(w) for w in cnt})
    for w, _ in cnt.most_common():
        sk = skeleton(w)
        if len(sk) >= 3:
            v.skeletons.setdefault(sk, w)
    return v


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
