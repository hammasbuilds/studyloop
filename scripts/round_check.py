"""Round 1 correctness check: every feature fed realistic input, every output compared with an
independent computation (re-reading the source text, recounting in SQLite, recomputing a formula
by hand). Prints one row per check and the totals.

    uv run python scripts/round_check.py            # API checks
    uv run --with playwright python scripts/round_check.py --browser   # also "open in the book"

No model is used (use_llm is off). Web import is tested against a page this script serves itself
on 127.0.0.1 (port 8800-8899) with STUDYLOOP_ALLOW_PRIVATE_URLS=1 set for this process only.
"""

from __future__ import annotations

import csv
import http.server
import io
import json
import math
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
os.environ["STUDYLOOP_ALLOW_PRIVATE_URLS"] = "1"
os.environ.pop("STUDYLOOP_LLM", None)

from fastapi.testclient import TestClient  # noqa: E402

from studyloop import db  # noqa: E402
from studyloop.app import create_app  # noqa: E402

ROWS: list[tuple[str, str, str, str, bool]] = []


def check(feature: str, inp: str, expected, got, ok: bool | None = None) -> bool:
    ok = (expected == got) if ok is None else ok
    ROWS.append((feature, inp, str(expected), str(got), ok))
    return ok


def words(text: str) -> int:
    """Independent word count: whitespace tokens that contain a letter or a digit."""
    return sum(1 for w in text.split() if re.search(r"\w", w))


# ---- fixtures ---------------------------------------------------------------------------------

RIVERS_MD = """# A Small Book of Rivers

This little book follows water from the hills to the sea. It was written for a first-year
geography class and keeps each idea short.

## Sources

Every river begins somewhere high. Rain, springs and melting ice all feed it.

### Springs

A spring is water that comes out of the ground where the water table meets the surface. Springs
often feed the first small streams of a river, and many villages were built beside them.

### Glacial melt

- Glaciers melt fastest in late summer.
- Meltwater carries fine rock flour that turns rivers milky.
- A river fed by a glacier is called a glacial river.

## The middle course

In the middle course the slope is gentler, so the river spends its energy moving sideways.

### Meanders

A meander is a bend in a river. Water flows faster on the outside of the bend and erodes the bank,
while slower water on the inside drops sand and gravel. Over many years the bend grows wider.

### Oxbow lakes

When the neck of a meander is cut through during a flood, the old bend is left behind as an oxbow
lake. An oxbow lake slowly fills with silt and plants.

| Feature | Where |
| --- | --- |
| Oxbow lake | Middle course |

## Mouths

A delta is a landform built where a river slows down and drops its sediment into still water.
An estuary is the wide tidal mouth of a river where fresh water mixes with salt water.
"""

NOTES_TXT = """LECTURE 1: WEATHER AND CLIMATE

Weather is the state of the air at one place and time. It changes from hour to
hour. Climate is the average weather of a place over thirty years or more, so it
changes slowly.

Meteorologists measure temperature, pressure, humidity and wind. A barometer
measures air pressure, and falling pressure often means rain is coming.

LECTURE 2: CLOUDS

Clouds form when moist air rises, cools and condenses on tiny particles of dust.
Cumulus clouds are puffy and white; stratus clouds are flat grey sheets that
often bring drizzle.

Cirrus clouds are thin wisps of ice crystals high in the sky. They often arrive
a day before a warm front.
"""

ARTICLE_HTML = """<!doctype html><html><head><title>How deltas form</title></head><body>
<nav>Home | About | Contact us today</nav>
<article><h1>How deltas form</h1>
<p>A delta is a landform that builds up where a river slows down as it enters the sea or a lake and
drops the sediment it was carrying. Over centuries the sediment piles into fan-shaped land.</p>
<h2>Why deltas are fertile</h2>
<p>Deltas are fertile because each flood leaves a fresh layer of silt rich in minerals, which is why
many of the oldest farming societies grew up on them.</p>
<h2>Deltas at risk</h2>
<p>Dams upstream trap sediment, so many deltas now receive less silt than the sea removes, and they
are slowly shrinking.</p>
</article><footer>Copyright notice and cookie banner text</footer></body></html>"""
ARTICLE_BODY = [
    "A delta is a landform that builds up where a river slows down",
    "Deltas are fertile because each flood leaves a fresh layer of silt",
    "Dams upstream trap sediment",
]
ARTICLE_JUNK = ["Contact us today", "cookie banner"]

PASTED = """## Volcanoes

A volcano is an opening in the crust through which molten rock, ash and gas escape. Magma that
reaches the surface is called lava.

## Kinds of volcano

Shield volcanoes have gentle slopes built from runny lava. Stratovolcanoes are steep cones built
from layers of ash and thick lava, and they erupt explosively.
"""


def md_structure(md: str) -> tuple[int, list[int]]:
    """Independent outline of a markdown book: (chapters, topics per chapter) from its ## / ###
    headings, counting a chapter's lead text as one more topic and any text before the first ##
    as an Introduction chapter."""
    lines = md.split("\n")
    chapters: list[int] = []
    lead = False
    front = False
    seen_ch = False
    for ln in lines:
        if ln.startswith("## "):
            if seen_ch:
                chapters[-1] += lead
            chapters.append(0)
            seen_ch, lead = True, False
        elif ln.startswith("### "):
            chapters[-1] += 1
            lead_done = True  # noqa: F841
        elif ln.strip() and not ln.startswith("# "):
            if not seen_ch:
                front = True
            elif chapters[-1] == 0:
                lead = True
    if seen_ch:
        chapters[-1] += lead
    chapters = [c or 1 for c in chapters]
    if front:
        chapters = [1, *chapters]
    return len(chapters), chapters


def coverage(md: str, spans: list[tuple[int, int]]) -> tuple[int, int, int]:
    """(content characters, characters in no topic, characters in more than one topic), counting
    the non-space characters of every line that is not a chapter/topic heading (#, ##, ###). A long
    paragraph may be shared by two topics at a sentence boundary; each character still belongs to
    exactly one."""
    cover = [0] * (len(md) + 1)
    for s, e in spans:
        for i in range(s, e):
            cover[i] += 1
    pos = 0
    n = lost = dup = 0
    for ln in md.split("\n"):
        a = pos
        pos += len(ln) + 1
        if not ln.strip() or re.match(r"#{1,3} ", ln):
            continue
        for i, ch in enumerate(ln, a):
            if ch.isspace():
                continue
            n += 1
            lost += cover[i] == 0
            dup += cover[i] > 1
    return n, lost, dup


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    port = next(p for p in range(8850, 8900) if socket.socket().connect_ex(("127.0.0.1", p)) != 0)
    handler = lambda *a, **k: _Quiet(*a, directory=str(directory), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


# ---- 1. library ------------------------------------------------------------------------------

def check_library(c: TestClient, con: sqlite3.Connection, work: Path) -> dict[str, int]:
    from booktoskill.samplepdf import tiny_book, write_pdf

    ids: dict[str, int] = {}

    def add(name: str, **kw) -> dict:
        r = c.post("/api/books", **kw)
        assert r.status_code == 202, r.text
        bid = r.json()["id"]
        ids[name] = bid
        return c.get(f"/api/books/{bid}").json()

    def outline_checks(name: str, b: dict, source_words: Counter | None = None) -> None:
        md = con.execute("SELECT markdown FROM books WHERE id=?", (b["id"],)).fetchone()[0]
        check("library", f"{name}: status", "ready", b["status"])
        topics = con.execute('SELECT start, "end", n_words, title FROM topics WHERE book_id=? ORDER BY ord',
                             (b["id"],)).fetchall()
        check("library", f"{name}: card chapters = DB chapters",
              con.execute("SELECT COUNT(*) FROM chapters WHERE book_id=?", (b["id"],)).fetchone()[0],
              b["chapters"])
        check("library", f"{name}: card topics = DB topics", len(topics), b["progress"]["topics"])
        check("library", f"{name}: card words = words in the stored text", words(md), b["n_words"])
        bad = [t[3] for t in topics if words(md[t[0]:t[1]]) != t[2]]
        check("library", f"{name}: topic word counts = words in each topic's span", [], bad)
        n, lost, dup = coverage(md, [(t[0], t[1]) for t in topics])
        check("library", f"{name}: content chars in no topic / in two ({n} chars)", (0, 0), (lost, dup))
        if source_words is not None:
            mdw = Counter(w.lower() for w in re.findall(r"[A-Za-z]+", md))
            missing = sorted((source_words - mdw).elements())
            check("library", f"{name}: source words missing from the book text", [], missing[:12])

    # markdown file
    b = add("markdown", files={"file": ("a-small-book-of-rivers.md", RIVERS_MD.encode(), "text/markdown")})
    exp_ch, exp_t = md_structure(RIVERS_MD)
    got_t = [len(ch["topics"]) for ch in b["course"]]
    check("library", "markdown: chapters (from ## headings + front text)", exp_ch, b["chapters"])
    check("library", "markdown: topics per chapter (### + lead text)", exp_t, got_t)
    check("library", "markdown: chapter titles = ## headings",
          ["Introduction", *re.findall(r"^## (.+)$", RIVERS_MD, re.M)], [ch["title"] for ch in b["course"]])
    outline_checks("markdown", b, Counter(w.lower() for w in re.findall(r"[A-Za-z]+", RIVERS_MD)))

    # plain text file
    b = add("text", files={"file": ("weather-notes.txt", NOTES_TXT.encode(), "text/plain")})
    check("library", "text: chapters = LECTURE lines", 2, b["chapters"])
    check("library", "text: chapter titles = the LECTURE lines",
          ["lecture 1: weather and climate", "lecture 2: clouds"], [ch["title"].lower() for ch in b["course"]])
    src = Counter(w.lower() for w in re.findall(r"[A-Za-z]+", NOTES_TXT))
    outline_checks("text", b, src)
    md = con.execute("SELECT markdown FROM books WHERE id=?", (b["id"],)).fetchone()[0]
    check("library", "text: hard-wrapped lines re-joined (a sentence split over two lines)",
          True, "It changes from hour to hour." in md)

    # HTML file
    b = add("html", files={"file": ("deltas.html", ARTICLE_HTML.encode(), "text/html")})
    md = con.execute("SELECT markdown FROM books WHERE id=?", (b["id"],)).fetchone()[0]
    check("library", "html: chapters = lead text + one per <h2>",
          ["Introduction", "Why deltas are fertile", "Deltas at risk"], [ch["title"] for ch in b["course"]])
    check("library", "html: article sentences kept", [], [s for s in ARTICLE_BODY if s not in " ".join(md.split())])
    check("library", "html: nav/footer dropped", [], [s for s in ARTICLE_JUNK if s in md])
    outline_checks("html", b)

    # pasted text
    b = add("pasted", data={"text": PASTED, "title": "Volcanoes in brief"})
    check("library", "pasted: title", "Volcanoes in brief", b["title"])
    check("library", "pasted: chapters = ## headings", 2, b["chapters"])
    outline_checks("pasted", b, Counter(w.lower() for w in re.findall(r"[A-Za-z]+", PASTED)))

    # web address
    site = work / "site"
    site.mkdir()
    (site / "deltas.html").write_text(ARTICLE_HTML, encoding="utf-8")
    srv, port = serve(site)
    try:
        b = add("web", data={"url": f"http://127.0.0.1:{port}/deltas.html"})
    finally:
        srv.shutdown()
    md = con.execute("SELECT markdown FROM books WHERE id=?", (b["id"],)).fetchone()[0]
    check("library", "web: title from <title>", "How deltas form", b["title"])
    check("library", "web: chapters = lead text + one per <h2>",
          ["Introduction", "Why deltas are fertile", "Deltas at risk"], [ch["title"] for ch in b["course"]])
    check("library", "web: article sentences kept", [], [s for s in ARTICLE_BODY if s not in " ".join(md.split())])
    check("library", "web: nav/footer dropped", [], [s for s in ARTICLE_JUNK if s in md])
    outline_checks("web", b)

    # PDF (book-to-skill's six-page sample whose correct text is known)
    pdf = write_pdf(work / "a-tiny-book.pdf", tiny_book(), title="A Tiny Book")
    b = add("pdf", files={"file": ("a-tiny-book.pdf", pdf.read_bytes(), "application/pdf")})
    md = con.execute("SELECT markdown FROM books WHERE id=?", (b["id"],)).fetchone()[0]
    flat = " ".join(md.split())
    check("library", "pdf: chapter titles", ["Getting Started", "Next Steps"],
          [re.sub(r"^(?:Chapter\s+)?\d+[.:]?\s*", "", ch["title"]) for ch in b["course"]])
    must = ["This book is a small test of the whole pipeline", "Programmers write assignments all the time",
            "A loop that never ends is called an infinite loop", "This chapter introduces loops and functions",
            "performs a computation is a function", "write small functions that each do one thing"]
    check("library", "pdf: body sentences kept (dehyphenated)", [], [s for s in must if s not in flat])
    check("library", "pdf: running headers / figure labels dropped", [],
          [s for s in ("2 Chapter 1. Getting Started", "fig label 42", "2.2. Functions 5") if s in flat])
    pdf_topics = [t["title"] for ch in b["course"] for t in ch["topics"]]
    check("library", "pdf: section headings become topics",
          True, all(any(x in t for t in pdf_topics) for x in ("Assignment", "Glossary", "Loops", "Functions")),
          )
    outline_checks("pdf", b)
    # every sentence of the chapter leads is reachable by a topic (and so by ask and quiz)
    tspans = con.execute('SELECT start, "end" FROM topics WHERE book_id=?', (b["id"],)).fetchall()
    for s in ("This book is a small test", "This chapter introduces loops"):
        i = md.find(s)
        check("library", f"pdf: '{s}...' is inside a topic", True, any(a <= i < e for a, e in tspans))

    # sample book
    r = c.post("/api/books/sample")
    ids["sample"] = r.json()["id"]
    b = c.get(f"/api/books/{ids['sample']}").json()
    outline_checks("sample", b)
    return ids


# ---- 2. course outline -----------------------------------------------------------------------

def _occurs(term: str, text: str) -> int:
    body = r"\s+".join(re.escape(w) for w in term.split())
    return len(re.findall(r"(?<![A-Za-z])" + body + r"(?:s|es)?(?![A-Za-z])", text, re.I))


# Words judged by hand (reading the topics they came from) as not key concepts: verb forms,
# adjectives, adverbs and empty nouns. Every one of them was shown as a concept at some point.
NOT_CONCEPTS = frozenset(
    """built inside outside well-known chemical metallic indifferent however none years occasion
    success search experience presence relation hours measure melt ends infinite fresh burst
    striking passing living freezing ascending fluted shaped portion operations processes
    preparation heap""".split()
)
# Terms each small book defines in so many words ("A meander is a bend"): (book, topic, term).
DEFINED = [
    ("markdown", "Springs", "spring"), ("markdown", "Meanders", "meander"),
    ("markdown", "Oxbow lakes", "oxbow lake"), ("markdown", "Mouths", "delta"),
    ("markdown", "Mouths", "estuary"), ("text", "LECTURE 1: WEATHER AND CLIMATE", "weather"),
    ("text", "LECTURE 1: WEATHER AND CLIMATE", "climate"), ("html", "Introduction", "delta"),
    ("pasted", "Volcanoes", "volcano"), ("pasted", "Volcanoes", "lava"),
    ("pdf", "2.1 Loops", "loop"),
]


def check_outline(c: TestClient, con: sqlite3.Connection, ids: dict[str, int]) -> list[str]:
    all_terms: list[str] = []
    by_topic: dict[tuple[str, str], list[str]] = {}
    for name, bid in ids.items():
        b = c.get(f"/api/books/{bid}").json()
        md = con.execute("SELECT markdown FROM books WHERE id=?", (bid,)).fetchone()[0]
        absent, bad_def, bad_sum, n = [], [], [], 0
        marked: list[str] = []
        for ch in b["course"]:
            for t in ch["topics"]:
                row = con.execute('SELECT start, "end" FROM topics WHERE id=?', (t["id"],)).fetchone()
                text = md[row[0]:row[1]]
                flat = " ".join(text.split())
                by_topic[(name, t["title"])] = [x["term"] for x in t["concepts"]]
                for cpt in t["concepts"]:
                    n += 1
                    all_terms.append(cpt["term"])
                    if _occurs(cpt["term"], text) == 0:
                        absent.append(cpt["term"])
                    if cpt["definition"] and (" ".join(cpt["definition"].split()) not in flat
                                              or _occurs(cpt["term"], cpt["definition"]) == 0):
                        bad_def.append(cpt["term"])
                plain = " ".join(re.sub(r"\*+|(?<!\w)_+|_+(?!\w)", "", text).split())
                if t["summary"] and " ".join(t["summary"].split()) not in plain:
                    bad_sum.append(t["title"])
                if re.search(r"\*|(?<!\w)_|_(?!\w)", t["summary"]):
                    marked.append(t["summary"][:40])
        check("outline", f"{name}: concepts that do not occur in their topic ({n} concepts)", [], absent[:10])
        check("outline", f"{name}: definitions not a sentence of the topic containing the term", [], bad_def[:10])
        check("outline", f"{name}: summaries not a sentence of their topic", [], bad_sum[:10])
        check("outline", f"{name}: summaries showing raw markdown emphasis markers", [], marked[:5])
    junk = sorted({x for x in all_terms if x.lower() in NOT_CONCEPTS})
    check("outline", f"all books: hand-judged non-concepts shown ({len(all_terms)} concepts)", [], junk)
    missed = [f"{b}/{t}: {term}" for b, t, term in DEFINED if term not in by_topic.get((b, t), [])]
    check("outline", f"defined terms that are not a concept of their topic ({len(DEFINED)})", [], missed)
    return all_terms


# ---- 3. ask the book -------------------------------------------------------------------------

# Questions about the sample book with the place that answers them, found by reading the book:
# a hit is a citation that overlaps one of the gold phrases.
ASK_EN = [
    ("What is capillary attraction?", ["capillary attraction"]),
    ("How are dip candles made?", ["dipped into melted tallow"]),
    ("What is a stearin candle made of?", ["made of stearin from tallow"]),
    ("Where does paraffin come from?", ["bogs of Ireland"]),
    ("Where does spermaceti come from?", ["spermaceti whale"]),
    ("Where does the Japanese wax come from?", ["substance brought from Japan"]),
    ("How is the cup of the candle formed?", ["cup is formed by this beautifully regular ascending current"]),
    ("Why does ice float on water?", ["ice weighs the lighter"]),
    ("What is the condensable part of the product of a candle?", ["nothing but water"]),
    ("How do you make hydrogen?", ["bits of zinc, and sulphuric or muriatic acid"]),
    ("How much does a cubic foot of hydrogen weigh?", ["cubic foot weighs one-twelfth of an ounce"]),
    ("What does a pint of nitrogen weigh?", ["pint of nitrogen weighs"]),
    ("In what proportion do oxygen and hydrogen make water?",
     ["two volumes of hydrogen", "proportion in which they occur in water"]),
    ("What is air made of?", ["two things of which it is composed"]),
    ("Does nitrogen burn?", ["which will not burn them"]),
    ("What happens to a soap bubble in carbonic acid?", ["soap-bubble, which of course will be filled with air"]),
    ("How much carbonic acid does respiration make in London?", ["5,000,000 pounds"]),
    ("How much carbon does a man convert in a day by respiration?", ["seven ounces of carbon"]),
    ("Why is a coal-gas flame bright?", ["coal-gas owes its brightness"]),
    ("Does iron get heavier when it burns?", ["makes the iron heavier"]),
    ("Is carbonic acid heavier than air?", ["heavier than the atmosphere", "greater weight of the carbonic acid"]),
    ("What is gunpowder made of?", ["gunpowder is composed of carbon"]),
    ("Why does a kettle rattle when water boils?", ["steam rising from the boiling water"]),
    ("Why can a candle not burn in my breath?", ["nature of my breath is such that a candle cannot burn"]),
    ("What do plants absorb?", ["absorb carbon"]),
]
ASK_UR = [
    ("capillary attraction kya hai?", ["capillary attraction"]),
    ("pani kaise banta hai", ["produces water", "produced water", "water produced", "produced from the combustion"]),
    ("hydrogen kaise banai jati hai?", ["bits of zinc, and sulphuric or muriatic acid", "make hydrogen"]),
    ("gunpowder kis cheez se bana hai?", ["gunpowder is composed of carbon"]),
    ("پانی کس چیز سے بنتا ہے؟", ["two volumes of hydrogen", "proportion in which they occur in water",
                              "combining with the hydrogen, produces water", "nothing but water"]),
    ("ہائیڈروجن کیسے بنتی ہے؟", ["bits of zinc, and sulphuric or muriatic acid", "make hydrogen"]),
    ("کیا نائٹروجن جلتی ہے؟", ["which will not burn them"]),
    ("پودے کیا جذب کرتے ہیں؟", ["absorb carbon"]),
]
OFF_BOOK = [
    "Who won the 1998 world cup?", "What is the capital of France?", "How do I train a neural network?",
    "What is the boiling point of mercury?", "Who wrote Hamlet?", "How many people live in Tokyo?",
    "What is the speed of light?", "How do vaccines work?", "What is inflation?",
    "Explain the French Revolution.", "How do I bake bread?", "What is machine learning?",
    "Who painted the Mona Lisa?", "What is the tallest mountain on Earth?",
    "How does the stock market work?", "What causes earthquakes?", "Who invented the telephone?",
    "What is the population of Pakistan?", "How do airplanes fly?", "What is the melting point of iron?",
    "پاکستان کا دارالحکومت کیا ہے؟", "cricket world cup kis ne jeeta?", "کرکٹ کا ورلڈ کپ کس نے جیتا؟",
]


def _gold_spans(md: str, phrases: list[str]) -> list[tuple[int, int]]:
    flat_idx = [i for i, ch in enumerate(md)]
    out = []
    for ph in phrases:
        for m in re.finditer(re.escape(ph), md):
            out.append((m.start(), m.end()))
    _ = flat_idx
    return out


def check_ask(c: TestClient, con: sqlite3.Connection, bid: int) -> list[dict]:
    md = con.execute("SELECT markdown FROM books WHERE id=?", (bid,)).fetchone()[0]
    topics = {r[0]: r for r in con.execute(
        'SELECT t.id, t.start, t."end", t.title, c.title FROM topics t JOIN chapters c ON c.id=t.chapter_id '
        "WHERE t.book_id=?", (bid,))}
    passages = con.execute('SELECT start, "end" FROM passages WHERE book_id=?', (bid,)).fetchall()

    def passage_of(a: int, b: int) -> set[tuple[int, int]]:
        return {(s, e) for s, e in passages if a < e and s < b}

    cites_all: list[dict] = []
    bad_quote = bad_line = bad_topic = n_cites = 0
    hits = {"en": [0, 0, 0], "ur": [0, 0, 0]}
    for lang, items in (("en", ASK_EN), ("ur", ASK_UR)):
        for q, gold in items:
            gs = _gold_spans(md, gold)
            assert gs, f"gold phrase not in the book: {gold}"
            r = c.post("/api/ask", json={"book_id": bid, "question": q, "use_llm": False}).json()
            exact = any(cc["start"] < ge and gs_ < cc["end"] for cc in r["citations"] for gs_, ge in gs)
            gold_p = set().union(*(passage_of(a, b) for a, b in gs))
            hit = any(passage_of(cc["start"], cc["end"]) & gold_p for cc in r["citations"])
            hits[lang][0] += hit
            hits[lang][1] += 1
            hits[lang][2] += exact
            first = r["citations"][0]["quote"][:60] if r["citations"] else r["message"][:60]
            check("ask", f"[{lang}] {q}", "passage with: " + gold[0][:30],
                  ("HIT " if exact else "passage " if hit else "miss ") + first, hit)
            for cc in r["citations"]:
                n_cites += 1
                cites_all.append(cc)
                bad_quote += md[cc["start"]:cc["end"]] != cc["quote"]
                bad_line += md.count("\n", 0, cc["start"]) + 1 != cc["line"]
                t = topics.get(cc["topic_id"])
                bad_topic += not (t and t[1] <= cc["start"] and cc["end"] <= t[2]
                                  and t[3] == cc["topic"] and t[4] == cc["chapter"])
            if r["answered"] and r["mode"] == "extractive":
                joined = " ".join(f"{cc['quote']} [{cc['n']}]" for cc in r["citations"])
                check("ask", f"[{lang}] answer text = the cited quotes: {q[:30]}", True, r["answer"] == joined)
    for lang in hits:
        h, n, x = hits[lang]
        print(f"ask [{lang}]: right passage cited {h}/{n}, the gold sentence itself cited {x}/{n}")
    check("ask", f"quotes equal book text at [start:end] ({n_cites} citations)", 0, bad_quote)
    check("ask", "line number = newlines before start + 1", 0, bad_line)
    check("ask", "citation topic/chapter = the topic whose span holds the quote", 0, bad_topic)
    wrong = []
    for q in OFF_BOOK:
        r = c.post("/api/ask", json={"book_id": bid, "question": q, "use_llm": False}).json()
        if r["answered"] or "does not say" not in r["message"]:
            wrong.append(f"{q} -> {r['message'] or r['answer'][:40]}")
    check("ask", f"off-book questions answered 'the book does not say' ({len(OFF_BOOK)})", [], wrong)
    return cites_all



# ---- 4. quizzes ------------------------------------------------------------------------------

def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fill(prompt: str, word: str) -> str:
    return prompt.replace("_____", word, 1)


def _book_sentences(md: str) -> set[str]:
    from studyloop.textutil import split_sentences

    return {" ".join(md[a:b].split()) for a, b in split_sentences(md)}


def check_quiz(c: TestClient, con: sqlite3.Connection, ids: dict[str, int]) -> None:
    for name in ("sample", "markdown", "text", "pasted", "pdf"):
        bid = ids[name]
        md = con.execute("SELECT markdown FROM books WHERE id=?", (bid,)).fetchone()[0]
        sentences = _book_sentences(md)
        topic_ids = [r[0] for r in con.execute("SELECT id FROM topics WHERE book_id=? ORDER BY ord", (bid,))]
        for tid in topic_ids:
            c.get(f"/api/topics/{tid}")  # builds the pool the way the reader page does
        qs = con.execute("SELECT * FROM questions WHERE book_id=?", (bid,)).fetchall()
        n = {"cloze": 0, "mcq": 0, "tf": 0}
        bad_blank, bad_opts, near_dup, dis_true, tf_wrong, tf_false_in_book = [], [], [], [], [], []
        multiline: list[str] = []
        for q in qs:
            n[q["kind"]] += 1
            src = " ".join(md[q["q_start"]:q["q_end"]].split())
            prompt = " ".join(q["prompt"].split())
            if q["kind"] in ("cloze", "mcq"):
                if _fill(prompt, " ".join(q["answer"].split())) != src:
                    bad_blank.append(prompt[:50])
            if q["kind"] in ("cloze", "mcq"):
                shown = [q["answer"]] + (json.loads(q["options"]) if q["kind"] == "mcq" else [])
                hint = json.loads(q["options"]).get("hint", "") if q["kind"] == "cloze" else q["answer"]
                if any("\n" in x or x != x.strip() for x in shown) or len(hint) != len(q["answer"]):
                    multiline.append(repr(q["answer"]))
            if q["kind"] == "mcq":
                opts = json.loads(q["options"])
                if sum(o == q["answer"] for o in opts) != 1 or len({o.lower() for o in opts}) != len(opts):
                    bad_opts.append(prompt[:50])
                for o in opts:
                    if o == q["answer"]:
                        continue
                    a, b = o.lower(), q["answer"].lower()
                    if _lev(a, b) <= 2 or a in b or b in a or a.rstrip("s") == b.rstrip("s"):
                        near_dup.append(f"{q['answer']}/{o}")
                    if " ".join(_fill(prompt, o).split()) in sentences:
                        dis_true.append(f"{q['answer']}/{o}")
            if q["kind"] == "tf":
                is_src = prompt == src
                if (q["answer"] == "true") != is_src:
                    tf_wrong.append(prompt[:50])
                if q["answer"] == "false" and prompt in sentences:
                    tf_false_in_book.append(prompt[:50])
        tot = len(qs)
        check("quiz", f"{name}: blank filled with the answer = the source sentence ({tot} questions, {n})",
              [], bad_blank[:5])
        check("quiz", f"{name}: choice options hold the answer once, all distinct", [], bad_opts[:5])
        check("quiz", f"{name}: answers/options on one line, hint as long as the answer", [], multiline[:5])
        check("quiz", f"{name}: distractors that are near-duplicates of the answer", [], near_dup[:8])
        check("quiz", f"{name}: distractors that make a true sentence of the book", [], dis_true[:5])
        check("quiz", f"{name}: true/false answer = whether the statement is the source sentence", [], tf_wrong[:5])
        check("quiz", f"{name}: 'false' statements that are sentences of the book", [], tf_false_in_book[:5])
        # rounds: no sentence asked twice in a round
        repeats = []
        for tid in topic_ids:
            r = c.get(f"/api/topics/{tid}/quiz?n=6").json()["questions"]
            starts = [con.execute("SELECT q_start FROM questions WHERE id=?", (x["id"],)).fetchone()[0] for x in r]
            if len(starts) != len(set(starts)):
                repeats.append(tid)
            if any("answer" in x or "accept" in x for x in r):
                repeats.append(f"leak {tid}")
        check("quiz", f"{name}: rounds that ask two questions on one sentence ({len(topic_ids)} topics)", [], repeats)


GRADING = [
    # (typed, answer, accept, expected) -- typed answers to a fill-in-the-blank
    ("Flame", "flame", ["flame"], True), ("flame.", "flame", ["flame"], True),
    ("  FLAME ", "flame", ["flame"], True), ("flames", "flame", ["flame"], True),
    ("the flame", "flame", ["flame"], True), ("candle", "candles", ["candles"], True),
    ("candles", "candle", ["candle"], True), ("oxygen", "hydrogen", ["hydrogen"], False),
    ("hydrogn", "hydrogen", ["hydrogen"], True), ("carbonic acid", "carbonic acid", ["carbonic acid"], True),
    ("Carbonic-acid", "carbonic acid", ["carbonic acid"], True), ("acid", "carbonic acid", ["carbonic acid"], False),
    ("carbon", "carbonic", ["carbonic"], False), ("", "flame", ["flame"], False),
    ("wax", "wick", ["wick"], False), ("wicks", "wick", ["wick"], True),
    ("glasses", "glass", ["glass"], True), ("bodies", "body", ["body"], True),
    ("lime water", "lime-water", ["lime-water"], True), ("metals", "metal", ["metal"], True),
]


def check_grading(con: sqlite3.Connection) -> None:
    from studyloop import quiz

    wrong = []
    for typed, ans, acc, exp in GRADING:
        row = {"kind": "cloze", "answer": ans, "accept": json.dumps(acc)}
        if quiz.grade(row, typed) != exp:
            wrong.append(f"{typed!r} for {ans!r}")
    check("quiz", f"typed-answer grading: case, punctuation, plurals, typos, hyphens ({len(GRADING)} cases)",
          [], wrong)
    mcq = {"kind": "mcq", "answer": "Oxygen", "accept": "[]"}
    tf = {"kind": "tf", "answer": "false", "accept": "[]"}
    got = [quiz.grade(mcq, "Oxygen"), quiz.grade(mcq, "oxygen"), quiz.grade(mcq, "Hydrogen"),
           quiz.grade(tf, "False"), quiz.grade(tf, "true")]
    check("quiz", "choice / true-false grading", [True, True, False, True, False], got)


# ---- 5. review and mastery -------------------------------------------------------------------

DOC_PRIOR, DOC_LEARN, DOC_SLIP = 0.30, 0.10, 0.20
DOC_GUESS = {"cloze": 0.15, "mcq": 0.30, "tf": 0.55}
DAY = 86400.0


def hand_bkt(p: float, ok: bool, g: float) -> float:
    if ok:
        post = p * (1 - DOC_SLIP) / (p * (1 - DOC_SLIP) + (1 - p) * g)
    else:
        post = p * DOC_SLIP / (p * DOC_SLIP + (1 - p) * (1 - g))
    return post + (1 - post) * DOC_LEARN


def hand_interval(p: float, ok: bool, prev: float, mastered_runs: int) -> float:
    if not ok or p < 0.5:
        return 10 / 1440
    if p < 0.8:
        return 1.0
    if p < 0.95:
        return 2.0
    return min(90.0, max(4.0, prev * 2.2)) if mastered_runs else 4.0


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def check_mastery(c: TestClient, con: sqlite3.Connection, ids: dict[str, int], clock: Clock) -> None:
    bid = ids["sample"]
    topics = [r[0] for r in con.execute("SELECT id FROM topics WHERE book_id=? ORDER BY ord", (bid,))]
    usable = [t for t in topics if con.execute("SELECT COUNT(*) FROM questions WHERE topic_id=?", (t,)).fetchone()[0] >= 6]
    tA, tB, tC, tD = usable[1], usable[2], usable[3], usable[4]

    def answer(tid: int, ok: bool, kind: str | None = None) -> tuple[dict, dict]:
        rows = con.execute("SELECT * FROM questions WHERE topic_id=? ORDER BY id", (tid,)).fetchall()
        seen = {r[0] for r in con.execute("SELECT DISTINCT question_id FROM attempts")}
        cand = [r for r in rows if (kind is None or r["kind"] == kind)]
        q = next((r for r in cand if r["id"] not in seen), cand[0])
        if ok:
            resp = q["answer"]
        else:
            resp = {"tf": "true" if q["answer"] == "false" else "false"}.get(q["kind"], "zzzz wrong")
        return dict(q), c.post("/api/quiz/answer", json={"question_id": q["id"], "response": resp}).json()

    # A: a scripted run over four days, recomputed by hand after every answer
    p, attempts, recent, interval, runs, last = DOC_PRIOR, 0, "", 0.0, 0, None
    script = [(0.0, True, "cloze"), (0.01, True, "mcq"), (0.02, False, "tf"), (0.03, True, "cloze"),
              (1.0, True, "mcq"), (1.01, True, "cloze"), (1.02, True, "tf"), (3.0, True, "cloze"),
              (3.01, True, "mcq"), (3.02, True, "cloze"), (9.0, True, "mcq")]
    t0 = clock.t
    bad = []
    for day, ok, kind in script:
        clock.t = t0 + day * DAY
        q, r = answer(tA, ok, kind)
        repeat = con.execute("SELECT COUNT(*) FROM attempts WHERE question_id=?", (q["id"],)).fetchone()[0] > 1
        base = p
        if attempts:
            stab = max(interval, 10 / 1440) / -math.log(0.9)
            base = p * math.exp(-(clock.t - last) / DAY / stab)
        g = max(DOC_GUESS[q["kind"]], 0.6) if repeat else DOC_GUESS[q["kind"]]
        p = hand_bkt(base, r["correct"], g)
        attempts += 1
        recent = (recent + ("1" if r["correct"] else "0"))[-8:]
        solid = p >= 0.95 and attempts >= 8 and len(recent) >= 8 and recent.count("1") >= 6
        runs = runs + 1 if (solid and r["correct"]) else (0 if not r["correct"] else runs)
        shown = p if solid else min(p, 0.94)
        interval = hand_interval(shown, r["correct"], interval, runs)
        last = clock.t
        m = con.execute("SELECT * FROM mastery WHERE topic_id=?", (tA,)).fetchone()
        if r["correct"] != ok:
            bad.append(f"day {day}: graded {r['correct']} for a {'right' if ok else 'wrong'} answer")
        if abs(m["p_known"] - p) > 1e-9 or abs(m["interval_days"] - interval) > 1e-9 \
                or abs(m["due_ts"] - (clock.t + interval * DAY)) > 1e-6:
            bad.append(f"day {day}: p {m['p_known']:.4f} vs {p:.4f}, interval {m['interval_days']} vs {interval}")
    check("mastery", f"BKT P(known), interval and due date recomputed by hand ({len(script)} answers)", [], bad)
    m = con.execute("SELECT * FROM mastery WHERE topic_id=?", (tA,)).fetchone()
    ans = con.execute("SELECT correct FROM attempts WHERE topic_id=? ORDER BY id", (tA,)).fetchall()
    check("mastery", "attempts / correct counts = attempts table",
          (len(ans), sum(a[0] for a in ans)), (m["attempts"], m["correct"]))

    # B: weak (two wrong answers), C: due and overdue, D: shaky but not due
    clock.t += 0.5 * DAY
    answer(tB, False)
    answer(tB, False)
    for _ in range(3):
        answer(tC, True, "cloze")
    for _ in range(2):
        answer(tD, True, "tf")
    clock.t += 5 * DAY
    answer(tD, True, "cloze")
    clock.t += 0.2 * DAY
    now = clock.t
    nxt = c.get(f"/api/review/next?book_id={bid}&limit=50").json()
    # Independent order from the stated rule: due or weak topics (weakest-and-latest first), then the
    # first unstarted topic that has questions, then the rest that are not mastered, least recalled first.
    rows = []
    for t in topics:
        r = con.execute("SELECT * FROM mastery WHERE topic_id=?", (t,)).fetchone()
        ordv = con.execute("SELECT ord FROM topics WHERE id=?", (t,)).fetchone()[0]
        if r is None:
            rows.append((t, ordv, None))
            continue
        stab = max(r["interval_days"], 10 / 1440) / -math.log(0.9)
        rec = r["p_known"] * math.exp(-(now - r["last_ts"]) / DAY / stab)
        due_in = (r["due_ts"] - now) / DAY
        solid = (r["p_known"] >= 0.95 and r["attempts"] >= 8 and len(r["recent"]) >= 8
                 and r["recent"].count("1") >= 6)
        rows.append((t, ordv, (r["p_known"], rec, due_in, solid)))
    due = [(t, o, s) for t, o, s in rows if s and (s[2] <= 0 or s[0] < 0.6)]
    due.sort(key=lambda x: (x[2][1] - 0.05 * max(0.0, -x[2][2]), x[1]))
    first_new = next(t for t, o, s in rows if s is None
                     and con.execute("SELECT COUNT(*) FROM questions WHERE topic_id=?", (t,)).fetchone()[0])
    rest = sorted([(t, o, s) for t, o, s in rows if s and not (s[2] <= 0 or s[0] < 0.6) and not s[3]],
                  key=lambda x: x[2][1])
    expected = [t for t, _, _ in due] + [first_new] + [t for t, _, _ in rest]
    check("review", "review-next order = due/weak, then next new topic, then shaky",
          expected, [r["topic_id"] for r in nxt])
    sch = c.get(f"/api/review/schedule?book_id={bid}").json()
    grp_bad = []
    for g, items in sch.items():
        if g == "now":
            continue
        for r in items:
            d = r["due_in_days"]
            want = "overdue" if d < -1 else "today" if d <= 1 else "this_week" if d <= 7 else "later"
            if want != g:
                grp_bad.append(f"{r['topic']}: {d} in {g}")
    check("review", "schedule groups follow due dates", [], grp_bad)
    return None


# ---- 6. memory, notes, settings, exports, dashboard ---------------------------------------------

def check_memory(c: TestClient, con: sqlite3.Connection, ids: dict[str, int], path: Path) -> None:
    bid = ids["sample"]
    tid = con.execute("SELECT id FROM topics WHERE book_id=? ORDER BY ord LIMIT 1 OFFSET 2", (bid,)).fetchone()[0]
    n1 = c.post("/api/notes", json={"topic_id": tid, "text": "Capillary attraction lifts melted wax up the wick."}).json()
    n2 = c.post("/api/notes", json={"book_id": bid, "text": "Faraday: a candle makes water and carbonic acid."}).json()
    n3 = c.post("/api/notes", json={"topic_id": tid, "text": "=SUM(A1) is a formula, not a note"}).json()
    check("notes", "create: note stored with its topic and book", (tid, bid),
          tuple(con.execute("SELECT topic_id, book_id FROM notes WHERE id=?", (n1["id"],)).fetchone()))
    c.put(f"/api/notes/{n2['id']}", json={"text": "Faraday: a burning candle makes water and carbonic acid."})
    check("notes", "update: text changed in the database", "Faraday: a burning candle makes water and carbonic acid.",
          con.execute("SELECT text FROM notes WHERE id=?", (n2["id"],)).fetchone()[0])
    listed = {n["id"] for n in c.get(f"/api/notes?book_id={bid}").json()}
    check("notes", "list = notes rows of the book", {r[0] for r in con.execute("SELECT id FROM notes WHERE book_id=?", (bid,))}, listed)
    c.delete(f"/api/notes/{n3['id']}")
    check("notes", "delete: row gone", 0, con.execute("SELECT COUNT(*) FROM notes WHERE id=?", (n3["id"],)).fetchone()[0])
    check("notes", "topic page shows the topic's notes", [n1["id"]], [n["id"] for n in c.get(f"/api/topics/{tid}").json()["notes"]])

    hits = c.get("/api/memory/search", params={"q": "wick"}).json()
    check("memory", "search 'wick' finds the note that says wick", True, any(h["type"] == "note" and h["id"] == n1["id"] for h in hits))
    for q in ("what is capillary attraction", "What is Capillary  Attraction?!"):
        c.post("/api/ask", json={"book_id": bid, "question": q, "use_llm": False})
    hits = c.get("/api/memory/search", params={"q": "capillary"}).json()
    asked = [h for h in hits if h["type"] == "question"]
    check("memory", "search 'capillary' finds the asked question", True,
          any("capillary" in (h["question"] or "").lower() for h in asked))
    n_cap = sum(1 for (pl,) in con.execute("SELECT payload FROM events WHERE kind='ask'")
                if " ".join(json.loads(pl)["question"].lower().split()).rstrip("?.! ") == "what is capillary attraction")
    check("memory", "a repeated question is one hit with its count", n_cap,
          next((h["count"] for h in asked if (h["question"] or "").lower().startswith("what is capillary")), None))
    hits = c.get("/api/memory/search", params={"q": "zebra"}).json()
    check("memory", "search for a word in nothing stored finds nothing", [], hits)
    hist = c.get(f"/api/history?book_id={bid}&limit=500").json()
    check("memory", "history = ask events of the book", con.execute(
        "SELECT COUNT(*) FROM events WHERE kind='ask' AND book_id=?", (bid,)).fetchone()[0], len(hist))

    # settings persist across a restart (a new app on the same database file)
    c.put("/api/settings", json={"daily_goal": 25, "theme": "dark", "use_llm": False})
    s2 = TestClient(create_app(path, sync_import=True)).get("/api/settings").json()
    check("settings", "saved settings read back after a restart", {"daily_goal": 25, "theme": "dark", "use_llm": False},
          {k: s2[k] for k in ("daily_goal", "theme", "use_llm")})
    c.put("/api/settings", json={"daily_goal": 12})
    s3 = c.get("/api/settings").json()
    check("settings", "changing one setting keeps the others", (12, "dark", False), (s3["daily_goal"], s3["theme"], s3["use_llm"]))

    # notes export
    md_notes = c.get(f"/api/books/{bid}/notes.md").text
    secs = re.split(r"^## ", md_notes, flags=re.M)
    title = con.execute("SELECT title FROM books WHERE id=?", (bid,)).fetchone()[0]
    check("export", "notes.md title line", f"# My notes: {title}", md_notes.split("\n")[0])
    trow = con.execute("SELECT t.title, c.title FROM topics t JOIN chapters c ON c.id=t.chapter_id WHERE t.id=?", (tid,)).fetchone()
    sec = next((s for s in secs if s.startswith(f"{trow[1]} / {trow[0]}")), "")
    check("export", "notes.md: the topic note sits under its chapter / topic heading", True,
          "Capillary attraction lifts melted wax up the wick." in sec)
    whole = next((s for s in secs if s.startswith("Whole book")), "")
    check("export", "notes.md: the book note sits under 'Whole book' with its edited text", True,
          "a burning candle makes water" in whole)
    n_notes = con.execute("SELECT COUNT(*) FROM notes WHERE book_id=?", (bid,)).fetchone()[0]
    in_md = sum(1 for r in con.execute("SELECT text FROM notes WHERE book_id=?", (bid,)) if r[0] in md_notes)
    check("export", "notes.md holds every note of the book", n_notes, in_md)
    qsec = next((s for s in secs if s.startswith("Questions I asked")), "")
    check("export", "notes.md lists every question asked about the book",
          con.execute("SELECT COUNT(*) FROM events WHERE kind='ask' AND book_id=?", (bid,)).fetchone()[0],
          sum(1 for ln in qsec.split("\n") if ln.startswith("- ")))

    # flashcards
    r = c.get(f"/api/books/{bid}/flashcards.csv")
    body = r.content.decode("utf-8")
    check("export", "flashcards.csv starts with a UTF-8 BOM (Excel/Anki read Urdu and dashes)", True, body.startswith("﻿"))
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    check("export", "flashcards.csv header", ["Front", "Back", "Source"], rows[0])
    cards = rows[1:]
    exp = []
    seen: set[str] = set()
    for t in con.execute("SELECT t.title, t.concepts, c.title FROM topics t JOIN chapters c ON c.id=t.chapter_id "
                         "WHERE t.book_id=? ORDER BY t.ord", (bid,)):
        for cpt in json.loads(t[1]):
            if cpt["definition"] and cpt["term"].lower() not in seen:
                seen.add(cpt["term"].lower())
                exp.append(cpt["term"])
    check("export", "flashcards: one card per defined concept (= X-Cards header)", (len(exp), len(exp)),
          (len(cards), int(r.headers["X-Cards"])))
    flat = " ".join(con.execute("SELECT markdown FROM books WHERE id=?", (bid,)).fetchone()[0].split())
    bad = [cd[0] for cd in cards if cd[1].lstrip("'") not in flat or len(cd) != 3]
    check("export", "flashcards: every Back is the book's own sentence", [], bad[:5])
    bad = [cd[0] for cd in cards if not any(cd[0] == f"What does the book say about {t}?" for t in exp)]
    check("export", "flashcards: every Front names a defined concept", [], bad[:5])


def check_dashboard(c: TestClient, con: sqlite3.Connection, clock: Clock) -> None:
    d = c.get("/api/dashboard").json()
    now = clock.t
    t = d["totals"]
    # mastered, from the attempts table rather than the stored state
    mastered = 0
    for (tid,) in con.execute("SELECT DISTINCT topic_id FROM attempts"):
        m = con.execute("SELECT p_known FROM mastery WHERE topic_id=?", (tid,)).fetchone()
        last8 = [r[0] for r in con.execute("SELECT correct FROM attempts WHERE topic_id=? ORDER BY id DESC LIMIT 8", (tid,))]
        n_all = con.execute("SELECT COUNT(*) FROM attempts WHERE topic_id=?", (tid,)).fetchone()[0]
        mastered += m[0] >= 0.95 and n_all >= 8 and len(last8) == 8 and sum(last8) >= 6
    check("dashboard", "topics mastered", mastered, t["mastered"])
    check("dashboard", "topics (all ready books)", con.execute(
        "SELECT COUNT(*) FROM topics t JOIN books b ON b.id=t.book_id WHERE b.status='ready'").fetchone()[0], t["topics"])
    check("dashboard", "reviews due now", con.execute(
        "SELECT COUNT(*) FROM mastery WHERE attempts>0 AND due_ts<=?", (now,)).fetchone()[0], t["due"])
    n, right = con.execute("SELECT COUNT(*), SUM(correct) FROM attempts").fetchone()
    check("dashboard", "answer accuracy", round(right / n, 4), d["activity"]["accuracy"])
    check("dashboard", "questions asked = logged asks", con.execute(
        "SELECT COUNT(*) FROM events WHERE kind='ask'").fetchone()[0], t["questions_asked"])
    check("dashboard", "notes", con.execute("SELECT COUNT(*) FROM notes").fetchone()[0], t["notes"])
    # streak: consecutive local days with an answer, ending today (or yesterday if today is quiet)
    days = {time.strftime("%Y-%m-%d", time.localtime(r[0])) for r in con.execute("SELECT ts FROM attempts")}
    import datetime as dt

    day = dt.date.fromtimestamp(now)
    if day.isoformat() not in days:
        day -= dt.timedelta(days=1)
    streak = 0
    while day.isoformat() in days:
        streak += 1
        day -= dt.timedelta(days=1)
    check("dashboard", "day streak", streak, d["activity"]["streak"])
    per_day = Counter(time.strftime("%Y-%m-%d", time.localtime(r[0])) for r in con.execute("SELECT ts FROM attempts"))
    series_bad = [s["date"] for s in d["activity"]["series"] if s["answered"] != per_day.get(s["date"], 0)]
    check("dashboard", "answers per day (14-day chart)", [], series_bad)
    check("dashboard", "answered today", per_day.get(dt.date.fromtimestamp(now).isoformat(), 0), d["activity"]["today"])


# ---- 7. "open in the book" in a real browser ----------------------------------------------------

def check_highlight(path: Path, cites: list[dict]) -> None:
    """Open every cited quote's "open in the book" link in headless Edge and compare the
    highlighted text with the quote (markdown emphasis markers removed on both sides)."""
    import uvicorn
    from playwright.sync_api import sync_playwright

    port = next(p for p in range(8800, 8850) if socket.socket().connect_ex(("127.0.0.1", p)) != 0)
    server = uvicorn.Server(uvicorn.Config(create_app(path, sync_import=True), host="127.0.0.1",
                                           port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    def norm(x: str) -> str:
        return " ".join(re.sub(r"[*_`]", "", x).split())

    seen: set[tuple[int, int]] = set()
    bad, n = [], 0
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="msedge", headless=True)
            page = br.new_page()
            for cc in cites:
                if (cc["start"], cc["end"]) in seen:
                    continue
                seen.add((cc["start"], cc["end"]))
                n += 1
                page.goto(f"http://127.0.0.1:{port}/#/topic/{cc['topic_id']}?hl={cc['start']}-{cc['end']}")
                page.wait_for_selector("#reading")
                got = norm(" ".join(page.eval_on_selector_all("mark.hl", "els => els.map(e => e.textContent)")))
                if got != norm(cc["quote"]):
                    bad.append(f"{cc['quote'][:40]!r} -> {got[:40]!r}")
            br.close()
    finally:
        server.should_exit = True
    check("ask", f"'open in the book' highlights exactly the quote ({n} links, headless Edge)", [], bad[:5])


def main() -> None:
    browser = "--browser" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="studyloop_round_"))
    path = work / "s.sqlite3"
    app = create_app(path, sync_import=True)
    c = TestClient(app)
    con = db.connect(path)
    t0 = time.time()
    clock = Clock(time.time())
    db.CLOCK = clock
    ids = check_library(c, con, work)
    check_outline(c, con, ids)
    cites = check_ask(c, con, ids["sample"])
    check_quiz(c, con, ids)
    check_grading(con)
    check_mastery(c, con, ids, clock)
    check_memory(c, con, ids, path)
    check_dashboard(c, con, clock)
    if browser:
        check_highlight(path, cites)
    report(t0)


def report(t0: float) -> None:
    w = [max(len(r[i]) for r in ROWS) for i in range(4)]
    w = [min(x, m) for x, m in zip(w, (10, 70, 40, 40), strict=True)]
    print(f"{'feature':<{w[0]}}  {'input':<{w[1]}}  {'expected':<{w[2]}}  {'got':<{w[3]}}  verdict")
    for f, i, e, g, ok in ROWS:
        print(f"{f:<{w[0]}}  {i[:w[1]]:<{w[1]}}  {e[:w[2]]:<{w[2]}}  {g[:w[3]]:<{w[3]}}  {'ok' if ok else 'WRONG'}")
    bad = sum(1 for r in ROWS if not r[4])
    print(f"\n{len(ROWS)} checks, {len(ROWS) - bad} right, {bad} wrong  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
