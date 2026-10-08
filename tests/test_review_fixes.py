"""Fixes from the 2026-10-08 screenshot review: quiz rounds, concept quality, flashcards, memory."""

import csv
import io

from studyloop import ask, concepts, exports, memory, quiz


def test_a_round_never_asks_twice_about_one_sentence(con, sample_book):
    # Before: every one of the 26 topics opened with a choice and a cloze on the same sentence.
    topics = [r[0] for r in con.execute("SELECT id FROM topics")]
    full = 0
    for tid in topics:
        qs = quiz.pick(con, tid, 6)
        rows = [con.execute("SELECT q_start, kind, answer FROM questions WHERE id=?", (q["id"],)).fetchone()
                for q in qs]
        assert len({r["q_start"] for r in rows}) == len(rows)
        blanks = [r["answer"].lower() for r in rows if r["kind"] != "tf"]
        assert len(set(blanks)) == len(blanks)
        full += len(rows) == 6
    assert full >= 0.8 * len(topics)  # the pool reaches for more sentences so rounds stay full


def test_a_round_mixes_kinds_and_moves_on_after_answers(con, sample_book):
    tid = con.execute("SELECT id FROM topics WHERE title='Hydrogen'").fetchone()[0]
    first = quiz.pick(con, tid, 6)
    assert {q["kind"] for q in first} == {"mcq", "cloze", "tf"}
    for q in first:
        quiz.answer(con, q["id"], "x")
    second = {q["id"] for q in quiz.pick(con, tid, 6)}
    assert not second & {q["id"] for q in first}


def test_verbs_and_adjectives_are_not_concepts():
    text = ("I hope the water is warm. We hope to see the water boil. They hope it will. "
            "It is necessary to heat the copper. Heat is necessary. The copper glows. "
            "The copper bends. A copper wire carries the current. The water cools. ")
    other = "The sand settles. Sand is fine. The gravel moves. Gravel and sand mix. "
    terms = {c.term for c in concepts.extract([text, other, other, other])[0][0]}
    assert "copper" in terms and "water" in terms
    assert "hope" not in terms and "necessary" not in terms


def test_a_definition_must_define_the_term_itself():
    s = ["What are those little clouds of wool, the old philosophic wool, as it was called?",
         "Now, this is a metal, a beautiful and bright metal which changes in the air.",
         "Here are a couple of candles commonly called dips."]
    assert concepts._definition("wool", s) is None
    assert concepts._definition("metal", s) is None
    assert concepts._definition("dips", s) == s[2]
    assert concepts._definition("water", ["Water is a thing compounded of two substances."])


def test_flashcards_are_grammatical_and_skip_junk_terms(con, sample_book):
    text, n = exports.flashcards_csv(con, sample_book)
    rows = list(csv.reader(io.StringIO(text)))[1:]
    assert len(rows) == n > 0
    fronts = [r[0] for r in rows]
    assert all(f.startswith("What does the book say about ") and f.endswith("?") for f in fronts)
    for junk in ("hope", "burst", "wool", "metal", "manufacture"):
        assert f"What does the book say about {junk}?" not in fronts
    for front, back, _ in rows:  # the back is about the term on the front
        term = front.removeprefix("What does the book say about ").rstrip("?")
        assert term.lower() in back.lower()


def test_memory_search_groups_a_repeated_question(con, sample_book):
    for _ in range(3):
        ask.ask(con, sample_book, "What is capillary attraction?", use_llm=False)
    ask.ask(con, sample_book, "what is capillary attraction", use_llm=False)
    hits = [h for h in memory.recall(con, "capillary") if h["type"] == "question"]
    assert len(hits) == 1 and hits[0]["count"] == 4


def test_review_does_not_offer_a_topic_with_no_questions(con):
    from conftest import TINY_BOOK

    from studyloop import mastery
    from studyloop.ingest import Converted, add_book

    md = TINY_BOOK.replace("## What a river is", "## Preface\n\nShort note.\n\n## What a river is", 1)
    bid = add_book(con, Converted(md, "Rivers with a preface", "markdown", {}))
    preface = con.execute("SELECT id FROM topics WHERE book_id=? AND title='Preface'", (bid,)).fetchone()[0]
    assert quiz.ensure_pool(con, preface) == 0  # nothing to quiz: the UI says so instead of crashing
    offered = [r["topic_id"] for r in mastery.review_next(con, bid) if r["reason"] == "next new topic"]
    assert offered and preface not in offered
