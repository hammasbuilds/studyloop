"""Quizzes per topic: cloze, multiple choice from the text, true/false from stated facts.

Without a model everything is rule-based and deterministic: a question is a real sentence of the
book with a key concept blanked (cloze, multiple choice) or swapped for another concept of the
same book (the false half of true/false). The sentence's character span is stored, so the answer
explanation can quote the source. With an LLM configured, extra multiple-choice questions can be
generated, and each is kept only if its supporting quote is found in the topic text.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3

from . import db, mastery, memory
from . import llm as llm_mod
from .textutil import locate, split_sentences, stem

BAD_START = re.compile(
    r"^(it|this|that|these|those|they|he|she|his|her|its|their|such|so|thus|hence|therefore|"
    r"but|and|or|yet|then|there|here|also|however|now then|well|which|who|what|why|how)\b", re.I
)
BAD_CONTENT = re.compile(r"\[Illustration|\bFig\.|\bfig\.|http|\(\w\)|^\s*\d+\.\s|\bibid\b|_{2,}")
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand"]


def qid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def _usable(sent: str) -> bool:
    words = len(sent.split())
    if not 9 <= words <= 34 or not sent.rstrip().endswith("."):
        return False
    if BAD_START.match(sent.strip().lstrip("“\"'(")) or BAD_CONTENT.search(sent):
        return False
    if sent.count("“") != sent.count("”") or sent.count("(") != sent.count(")"):
        return False
    return not re.search(r"\b(?:Mr|Mrs|Dr)\.$", sent)


def _find_term(sent: str, term: str) -> tuple[int, int] | None:
    body = r"\s+".join(re.escape(w) for w in term.split())
    m = re.search(r"(?<![A-Za-z\-])" + body + r"[a-z]{0,2}(?![A-Za-z\-])", sent, re.I)
    return (m.start(), m.end()) if m else None


def _distractors(concepts: list[str], answer: str, sent: str, n: int, rng: random.Random) -> list[str]:
    """Other concepts from the book that fit the blank by shape and do not occur in the sentence."""
    low = sent.lower()
    ans_stem = stem(answer.split()[-1])
    want = len(answer.split())
    pool = [
        c for c in concepts
        if stem(c.split()[-1]) != ans_stem and c.lower() not in low
        and not any(stem(w) in {stem(x) for x in re.findall(r"[a-z]+", low)} for w in c.split())
    ]
    plural = answer.lower().endswith("s") and not answer.lower().endswith("ss")
    shaped = [c for c in pool if (c.lower().endswith("s") and not c.lower().endswith("ss")) == plural]
    pool = shaped if len(shaped) >= n else pool  # keep "singular/plural" from giving the answer away
    same = [c for c in pool if len(c.split()) == want]
    rng.shuffle(same)
    rest = [c for c in pool if c not in same]
    rng.shuffle(rest)
    return (same + rest)[:n]


def _match_case(word: str, template: str) -> str:
    return word[:1].upper() + word[1:] if template[:1].isupper() else word


def generate_for_topic(con: sqlite3.Connection, topic_id: int) -> int:
    """Create the rule-based question pool for a topic (idempotent). Returns the pool size."""
    t = con.execute('SELECT * FROM topics WHERE id=?', (topic_id,)).fetchone()
    md = con.execute("SELECT markdown FROM books WHERE id=?", (t["book_id"],)).fetchone()["markdown"]
    concepts = [c["term"] for c in json.loads(t["concepts"])]
    book_concepts: list[str] = []
    for r in con.execute("SELECT concepts FROM topics WHERE book_id=?", (t["book_id"],)):
        book_concepts.extend(c["term"] for c in json.loads(r["concepts"]))
    book_concepts = list(dict.fromkeys(book_concepts))
    text = md[t["start"] : t["end"]]
    sents = [(a + t["start"], b + t["start"]) for a, b in split_sentences(text)]
    sents = [(a, b) for a, b in sents if _usable(md[a:b])]
    rng = random.Random(qid("seed", topic_id))
    used: set[int] = set()
    made = 0
    # Each topic concept first; then a second sentence per concept and the book's other concepts that
    # occur here, until the topic has enough distinct sentences for a full round (a round never asks
    # two questions on one sentence, see pick).
    extra = concepts + [c for c in book_concepts if c not in concepts]
    for i, term in enumerate(concepts + extra):
        if i >= len(concepts) and len(used) >= 8:
            break
        best = None
        for a, b in sents:
            if a in used:
                continue
            sent = md[a:b]
            span = _find_term(sent, term)
            if span and span[0] > 0:  # a blank at the very start gives no lead-in
                # Prefer a definition-like sentence, then a shorter one.
                score = (bool(re.search(r"\b(called|known as|is|are|means)\b", sent)), -len(sent))
                if best is None or score > best[0]:
                    best = (score, a, b, span)
        if best is None:
            continue
        _, a, b, (s0, s1) = best
        used.add(a)
        sent = md[a:b]
        surface = sent[s0:s1]
        blanked = sent[:s0] + "_____" + sent[s1:]
        accept = list(dict.fromkeys([surface.lower(), term.lower()]))
        hint = f"{surface[0]}{'·' * (len(surface) - 1)}"
        # cloze
        con.execute(
            "INSERT OR IGNORE INTO questions(id, book_id, topic_id, kind, prompt, options, answer, "
            "accept, explanation, q_start, q_end, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid("cloze", topic_id, a), t["book_id"], topic_id, "cloze", blanked,
             json.dumps({"hint": hint}), surface, json.dumps(accept), "", a, b, "rules"),
        )
        made += 1
        # multiple choice
        dis = _distractors(book_concepts, term, sent, 3, rng)
        if len(dis) == 3:
            opts = [surface] + [_match_case(d, surface) for d in dis]
            order = random.Random(qid("mcq", topic_id, a))
            order.shuffle(opts)
            con.execute(
                "INSERT OR IGNORE INTO questions(id, book_id, topic_id, kind, prompt, options, "
                "answer, accept, explanation, q_start, q_end, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid("mcq", topic_id, a), t["book_id"], topic_id, "mcq", blanked,
                 json.dumps(opts), surface, json.dumps([surface.lower()]), "", a, b, "rules"),
            )
            made += 1
            # true / false: half the pool keeps the sentence, half swaps the concept
            if len(used) % 2 == 0:
                false = sent[:s0] + _match_case(dis[0], surface) + sent[s1:]
                stmt, ans = false, "false"
            else:
                stmt, ans = sent, "true"
            con.execute(
                "INSERT OR IGNORE INTO questions(id, book_id, topic_id, kind, prompt, options, "
                "answer, accept, explanation, q_start, q_end, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid("tf", topic_id, a), t["book_id"], topic_id, "tf", stmt,
                 json.dumps(["true", "false"]), ans, json.dumps([ans]), "", a, b, "rules"),
            )
            made += 1
    # Number-swap statements from stated facts (digits or number words).
    for a, b in sents:
        sent = md[a:b]
        m = re.search(r"\b(\d{1,4})\b", sent)
        if m and not re.search(r"\d{1,4}\s*[.)]\s", sent[: m.end() + 2]) and a not in used and made < 40:
            n = int(m.group(1))
            fake = n + rng.choice([-2, -1, 1, 2, 5]) if n > 2 else n + rng.choice([1, 2, 3])
            if fake == n or fake < 0:
                continue
            used.add(a)
            con.execute(
                "INSERT OR IGNORE INTO questions(id, book_id, topic_id, kind, prompt, options, answer, "
                "accept, explanation, q_start, q_end, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid("tfn", topic_id, a), t["book_id"], topic_id, "tf",
                 sent[: m.start()] + str(fake) + sent[m.end() :], json.dumps(["true", "false"]),
                 "false", json.dumps(["false"]), "", a, b, "rules"),
            )
            made += 1
    con.commit()
    return made


def ensure_pool(con: sqlite3.Connection, topic_id: int) -> int:
    n = con.execute("SELECT COUNT(*) FROM questions WHERE topic_id=?", (topic_id,)).fetchone()[0]
    if n == 0:
        generate_for_topic(con, topic_id)
        n = con.execute("SELECT COUNT(*) FROM questions WHERE topic_id=?", (topic_id,)).fetchone()[0]
    return n


def public(q: sqlite3.Row) -> dict:
    """What the client may see: never the answer."""
    opts = json.loads(q["options"])
    d = {"id": q["id"], "topic_id": q["topic_id"], "kind": q["kind"], "prompt": q["prompt"],
         "source": q["source"]}
    if q["kind"] == "cloze":
        d["hint"] = opts.get("hint") if isinstance(opts, dict) else None
    else:
        d["options"] = opts
    return d


def pick(con: sqlite3.Connection, topic_id: int, n: int = 6) -> list[dict]:
    """Next ``n`` questions: never-answered first, then last-missed, then least recently answered;
    kinds interleaved so a session mixes cloze, choice and true/false."""
    ensure_pool(con, topic_id)
    rows = con.execute(
        "SELECT q.*, (SELECT COUNT(*) FROM attempts a WHERE a.question_id=q.id) AS n_att, "
        "(SELECT a.correct FROM attempts a WHERE a.question_id=q.id ORDER BY a.id DESC LIMIT 1) AS last_ok, "
        "(SELECT MAX(a.ts) FROM attempts a WHERE a.question_id=q.id) AS last_ts "
        "FROM questions q WHERE q.topic_id=? ORDER BY q.q_start, q.id", (topic_id,)
    ).fetchall()

    def key(r):
        return (r["n_att"] > 0, r["last_ok"] == 1 if r["n_att"] else False, r["last_ts"] or 0)

    by_kind: dict[str, list] = {}
    for r in sorted(rows, key=key):
        by_kind.setdefault(r["kind"], []).append(r)
    # One question per source sentence per round: the cloze, choice and true/false built on a
    # sentence share its blank, so asking two of them gives the second answer away. A blanked word
    # already asked about on another sentence is used only when nothing else is left.
    out, kinds = [], ["mcq", "cloze", "tf"]
    used_spans: set[int] = set()
    used_answers: set[str] = set()

    def fresh(r, strict: bool) -> bool:
        if r["q_start"] in used_spans:
            return False
        return not (strict and r["kind"] != "tf" and r["answer"].lower() in used_answers)

    for strict in (True, False):
        i = 0
        while len(out) < n and i < 3 * max(1, len(rows)):
            k = kinds[i % len(kinds)]
            i += 1
            cand = next((r for r in by_kind.get(k, []) if fresh(r, strict)), None)
            if cand is None:
                continue
            by_kind[k].remove(cand)
            out.append(cand)
            used_spans.add(cand["q_start"])
            if cand["kind"] != "tf":
                used_answers.add(cand["answer"].lower())
    return [public(r) for r in out]


def _norm_answer(s: str) -> str:
    s = re.sub(r"[^\w\s\-]", "", s.lower())
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diff) <= 1:
            return True
        i = diff[0]  # one swapped pair of neighbours also counts as a single typo
        return len(diff) == 2 and diff[1] == i + 1 and a[i] == b[i + 1] and a[i + 1] == b[i]
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


def grade(question: sqlite3.Row, response: str) -> bool:
    r = _norm_answer(response)
    if not r:
        return False
    if question["kind"] == "tf":
        return r in ("true", "false") and r == question["answer"]
    if question["kind"] == "mcq":
        return _norm_answer(question["answer"]) == r
    for acc in json.loads(question["accept"]):
        a = _norm_answer(acc)
        if r == a or [stem(w) for w in r.split()] == [stem(w) for w in a.split()]:
            return True
        if len(a) >= 6 and _edit1(r, a):
            return True
    return False


def answer(con: sqlite3.Connection, question_id: str, response: str) -> dict | None:
    q = con.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if q is None:
        return None
    ok = grade(q, response)
    repeat = con.execute("SELECT 1 FROM attempts WHERE question_id=? LIMIT 1", (q["id"],)).fetchone() is not None
    sid = memory.session(con)
    con.execute(
        "INSERT INTO attempts(question_id, topic_id, book_id, session_id, response, correct, ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (q["id"], q["topic_id"], q["book_id"], sid, response, int(ok), db.now()),
    )
    kind = "llm" if q["source"] == "llm" else q["kind"]
    state = mastery.observe(con, q["topic_id"], kind, ok, repeat)
    md = con.execute("SELECT markdown FROM books WHERE id=?", (q["book_id"],)).fetchone()["markdown"]
    quote = md[q["q_start"] : q["q_end"]]
    memory.record(con, "quiz", book_id=q["book_id"], topic_id=q["topic_id"],
                  payload={"question_id": q["id"], "kind": q["kind"], "correct": ok})
    return {
        "correct": ok, "answer": q["answer"], "kind": q["kind"],
        "quote": quote, "start": q["q_start"], "end": q["q_end"],
        "line": md.count("\n", 0, q["q_start"]) + 1,
        "statement_is_true": (q["answer"] == "true") if q["kind"] == "tf" else None,
        "mastery": mastery.describe(state),
    }


# ---- optional: model-written questions, kept only when their evidence is in the text ----------

LLM_SYSTEM = "You write exam questions that can be answered from one passage. Never invent facts."


def llm_generate(con: sqlite3.Connection, topic_id: int, client, n: int = 4) -> dict:
    t = con.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    md = con.execute("SELECT markdown FROM books WHERE id=?", (t["book_id"],)).fetchone()["markdown"]
    text = md[t["start"] : t["end"]][:6000]
    prompt = (
        f"Passage:\n{text}\n\nWrite {n} multiple-choice questions testing understanding of this "
        'passage. Reply with JSON only: [{"question": "...", "options": ["a","b","c","d"], '
        '"answer_index": 0, "quote": "<words copied exactly from the passage that prove the answer>"}]'
    )
    try:
        data = llm_mod.parse_json(client.complete(prompt, system=LLM_SYSTEM, max_tokens=1200))
    except llm_mod.LLMError as exc:
        return {"added": 0, "rejected": 0, "error": str(exc)}
    added = rejected = 0
    for item in data if isinstance(data, list) else []:
        try:
            opts = [str(o).strip() for o in item["options"]]
            idx = int(item["answer_index"])
            span = locate(text, str(item["quote"]))
            if not (2 <= len(opts) <= 6 and len(set(opts)) == len(opts) and 0 <= idx < len(opts)
                    and span and str(item["question"]).strip()):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        a, b = t["start"] + span[0], t["start"] + span[1]
        con.execute(
            "INSERT OR IGNORE INTO questions(id, book_id, topic_id, kind, prompt, options, answer, "
            "accept, explanation, q_start, q_end, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid("llm", topic_id, item["question"]), t["book_id"], topic_id, "mcq",
             str(item["question"]).strip(), json.dumps(opts), opts[idx], json.dumps([opts[idx].lower()]),
             "", a, b, "llm"),
        )
        added += 1
    con.commit()
    return {"added": added, "rejected": rejected, "error": None}
