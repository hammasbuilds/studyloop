"""Ask the book: answers come only from the book, and every quote is located in the source.

Retrieval is BM25 over the book's passages (the vendored agent-memory implementation). The
extractive answer is the best-matching sentences, verbatim. An optional LLM may write the answer
instead, but its quotes are re-located in the retrieved passages (the rag-forge rule): a quote
that cannot be found is dropped, and an answer left with no verified quote falls back to the
extractive one.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field

from . import llm as llm_mod
from . import memory, urdu
from ._vendor.bm25 import BM25
from .concepts import DEFINE
from .textutil import locate, split_sentences, tokens

ABSTAIN_BELOW = 0.55  # idf-weighted share of the question's terms one passage must contain
MAX_SENTENCES = 3
TOP_PASSAGES = 6
PHRASE_GAP = 3  # question words that sit side by side must be this close (in content words)
PHRASE_PENALTY = ABSTAIN_BELOW - 0.01


@dataclass
class PassageRec:
    id: int
    topic_id: int
    start: int
    end: int
    text: str
    toks: list[str]


@dataclass
class Index:
    book_id: int
    markdown: str
    passages: list[PassageRec]
    bm25: BM25
    vocab: urdu.Vocab
    topics: dict[int, dict] = field(default_factory=dict)


_CACHE: dict[int, Index] = {}


def invalidate(book_id: int | None = None) -> None:
    if book_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(book_id, None)


def get_index(con: sqlite3.Connection, book_id: int) -> Index:
    if book_id in _CACHE:
        return _CACHE[book_id]
    row = con.execute("SELECT markdown FROM books WHERE id=?", (book_id,)).fetchone()
    if row is None:
        raise KeyError(book_id)
    md = row["markdown"]
    passages = []
    for p in con.execute(
        'SELECT id, topic_id, start, "end" FROM passages WHERE book_id=? ORDER BY id', (book_id,)
    ):
        text = md[p["start"] : p["end"]]
        passages.append(PassageRec(p["id"], p["topic_id"], p["start"], p["end"], text, tokens(text)))
    topics = {}
    for t in con.execute(
        "SELECT t.id, t.title, t.ord, c.title AS chapter, c.id AS chapter_id FROM topics t "
        "JOIN chapters c ON c.id = t.chapter_id WHERE t.book_id=?", (book_id,)
    ):
        topics[t["id"]] = dict(t)
    vocab = urdu.book_vocab(re.findall(r"[A-Za-z]+", md))
    idx = Index(book_id, md, passages, BM25([p.toks for p in passages]), vocab, topics)
    _CACHE[book_id] = idx
    return idx


def _phrase_supported(terms: list[str], passages: list[PassageRec]) -> bool:
    """A question of three or more content words ("boiling point of mercury") names a phrase.
    Finding every word scattered across a paragraph ("boiling the mercury ... pointing out") is
    not an answer: at least one neighbouring pair of question words must also be neighbours in a
    passage. Shorter questions are left to the coverage test."""
    if len(terms) < 3:
        return True
    pairs = list(zip(terms, terms[1:], strict=False))
    for p in passages:
        pos: dict[str, list[int]] = {}
        for i, t in enumerate(p.toks):
            pos.setdefault(t, []).append(i)
        for a, b in pairs:
            if any(abs(i - j) <= PHRASE_GAP for i in pos.get(a, ()) for j in pos.get(b, ())):
                return True
    return False


def _idf(idx: Index, term: str) -> float:
    """A term the book never uses counts as the rarest possible one: it must be covered or the
    answer's support drops, which is what makes an off-topic question abstain."""
    return idx.bm25.idf.get(term) or math.log(1 + (idx.bm25.n + 0.5) / 0.5)


def retrieve(idx: Index, terms: list[str], k: int = TOP_PASSAGES) -> list[tuple[PassageRec, float]]:
    if not terms or not idx.passages:
        return []
    scores = idx.bm25.scores(terms)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return [(idx.passages[i], scores[i]) for i in order if scores[i] > 0]


def _citation(idx: Index, n: int, start: int, end: int) -> dict:
    """Build a citation and prove the quote: the stored text is the source slice itself."""
    quote = idx.markdown[start:end]
    span = locate(idx.markdown, quote)
    assert span is not None and idx.markdown[span[0] : span[1]] == quote
    pid = next((p.topic_id for p in idx.passages if p.start <= start < p.end), None)
    topic = idx.topics.get(pid or -1, {})
    return {
        "n": n, "quote": quote, "start": start, "end": end,
        "line": idx.markdown.count("\n", 0, start) + 1,
        "topic_id": pid, "topic": topic.get("title"), "chapter": topic.get("chapter"),
        "verified": True,
    }


def _clean_quote_span(md: str, a: int, b: int) -> tuple[int, int]:
    """Trim list bullets / quote markers from the start of a sentence span."""
    m = re.match(r"\s*(?:[-*+>]|\d+[.)])\s+", md[a:b])
    return (a + m.end(), b) if m else (a, b)


def extractive(
    idx: Index, terms: list[str], intent: str | None
) -> tuple[list[tuple[int, int]], float]:
    """Best sentences as absolute (start, end) spans, plus the share of question terms covered."""
    hits = retrieve(idx, terms)
    if not hits:
        return [], 0.0
    top = hits[0][1]
    weights = {t: _idf(idx, t) for t in set(terms)}
    total_w = sum(weights.values()) or 1.0
    cands: list[tuple[float, int, int, set[str]]] = []
    for p, score in hits:
        for a, b in split_sentences(p.text):
            sent = p.text[a:b]
            words = len(sent.split())
            if words < 5 or words > 70:
                continue
            toks = set(tokens(sent))
            matched = {t for t in weights if t in toks}
            if not matched:
                continue
            cov = sum(weights[t] for t in matched) / total_w
            s = 0.7 * cov + 0.3 * (score / top)
            if intent in (None, "what") and DEFINE.search(sent):
                s += 0.08
            if 8 <= words <= 40:
                s += 0.04
            ca, cb = _clean_quote_span(idx.markdown, p.start + a, p.start + b)
            cands.append((s, ca, cb, matched))
    cands.sort(key=lambda c: -c[0])
    chosen: list[tuple[float, int, int, set[str]]] = []
    covered: set[str] = set()
    for c in cands:
        if any(not (c[2] <= x[1] or c[1] >= x[2]) for x in chosen):
            continue
        new = c[3] - covered
        if chosen and not new and len(chosen) >= 1 and c[0] < chosen[0][0] * 0.8:
            continue
        chosen.append(c)
        covered |= c[3]
        if len(chosen) >= MAX_SENTENCES:
            break
    # Support is judged on one passage, not on the union of sentences: a question whose words are
    # only ever found in different places ("boiling point" here, "mercury" there) is not answered.
    support = max(
        sum(weights[t] for t in weights if t in p.toks) / total_w for p, _ in hits
    )
    if not _phrase_supported(terms, [p for p, _ in hits]):
        support = min(support, PHRASE_PENALTY)
    chosen.sort(key=lambda c: c[1])
    return [(c[1], c[2]) for c in chosen], support


LLM_SYSTEM = (
    "You answer questions about one book. Use ONLY the numbered passages. If they do not answer "
    "the question, set supported to false. Never use outside knowledge."
)


def _llm_prompt(question: str, hits: list[tuple[PassageRec, float]]) -> str:
    ps = "\n\n".join(f"[{i + 1}] {p.text}" for i, (p, _) in enumerate(hits))
    return (
        f"Passages:\n{ps}\n\nQuestion: {question}\n\n"
        'Reply with JSON only: {"supported": true|false, "answer": "<2-4 sentences>", '
        '"quotes": [{"passage": <number>, "quote": "<words copied exactly from that passage>"}]}'
    )


def llm_answer(idx: Index, question: str, terms: list[str], client) -> dict | None:
    hits = retrieve(idx, terms, k=5)
    if not hits:
        return None
    reply = client.complete(_llm_prompt(question, hits), system=LLM_SYSTEM)
    data = llm_mod.parse_json(reply)
    if not isinstance(data, dict):
        return None
    if data.get("supported") is False:
        return {"supported": False, "answer": "", "citations": [], "dropped": 0}
    cites: list[dict] = []
    dropped = 0
    for q in data.get("quotes") or []:
        text = (q.get("quote") or "").strip() if isinstance(q, dict) else ""
        if not text:
            continue
        order = []
        num = q.get("passage")
        if isinstance(num, int) and 1 <= num <= len(hits):
            order.append(hits[num - 1][0])
        order += [p for p, _ in hits if p not in order]
        for p in order:
            span = locate(p.text, text)
            if span:
                a, b = p.start + span[0], p.start + span[1]
                if not any(c["start"] == a and c["end"] == b for c in cites):
                    cites.append(_citation(idx, len(cites) + 1, a, b))
                break
        else:
            dropped += 1
    return {"supported": True, "answer": str(data.get("answer", "")).strip(),
            "citations": cites, "dropped": dropped}


def ask(
    con: sqlite3.Connection, book_id: int, question: str, *, use_llm: bool = True, client=None
) -> dict:
    question = question.strip()
    idx = get_index(con, book_id)
    a = urdu.analyse(question, idx.vocab)
    result: dict = {
        "question": question, "analysis": a.as_dict(), "answered": False, "mode": "extractive",
        "answer": "", "citations": [], "dropped_quotes": 0, "message": "", "support": 0.0,
        "related": [],
    }
    if not a.terms:
        result["message"] = "I could not find any searchable words in that question."
    else:
        client = client if client is not None else (llm_mod.get_client() if use_llm else None)
        spans, support = extractive(idx, a.terms, a.intent)
        result["support"] = round(support, 3)
        hits = retrieve(idx, a.terms, k=8)
        seen: list[int] = []
        for p, _ in hits:
            if p.topic_id not in seen:
                seen.append(p.topic_id)
        result["related"] = [
            {"topic_id": t, "topic": idx.topics[t]["title"], "chapter": idx.topics[t]["chapter"]}
            for t in seen[:4] if t in idx.topics
        ]
        if not spans or support < ABSTAIN_BELOW:
            result["message"] = "The book does not say. Nothing in it answers that question."
        else:
            used_llm = False
            if client is not None:
                try:
                    out = llm_answer(idx, question, a.terms, client)
                except llm_mod.LLMError as exc:
                    out = None
                    result["message"] = f"model unavailable ({exc}); showing the extractive answer"
                if out is not None and out["supported"] is False:
                    result["message"] = "The book does not say. The model found no support in the passages."
                    _log(con, book_id, result)
                    return result
                if out and out["citations"]:
                    result.update(
                        answered=True, mode=f"llm:{client.name}", answer=out["answer"],
                        citations=out["citations"], dropped_quotes=out["dropped"],
                    )
                    used_llm = True
                elif out is not None:
                    result["dropped_quotes"] = out["dropped"]
                    result["message"] = "The model's quotes could not be found in the book; showing the extractive answer."
            if not used_llm:
                cites = [_citation(idx, i + 1, s, e) for i, (s, e) in enumerate(spans)]
                result.update(
                    answered=True, mode="extractive", citations=cites,
                    answer=" ".join(f"{c['quote']} [{c['n']}]" for c in cites),
                )
    _log(con, book_id, result)
    return result


def _log(con: sqlite3.Connection, book_id: int, r: dict) -> None:
    memory.record(
        con, "ask", book_id=book_id,
        payload={
            "question": r["question"], "language": r["analysis"]["language"],
            "answered": r["answered"], "mode": r["mode"], "terms": r["analysis"]["terms"],
            "citations": [{"quote": c["quote"][:200], "start": c["start"], "end": c["end"],
                           "topic_id": c["topic_id"]} for c in r["citations"]],
            "answer": r["answer"][:1200], "support": r["support"],
        },
    )
