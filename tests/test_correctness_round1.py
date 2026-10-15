"""Regression tests for the round-1 correctness findings (scripts/round_check.py). Each one fails
on the code before the fix."""

from __future__ import annotations

import json

from studyloop import ask, concepts, quiz, urdu
from studyloop.ingest import Converted, add_book
from studyloop.structure import parse_course
from studyloop.textutil import count_words, tokens

RIVERS = """# Rivers

This little book follows water from the hills to the sea, one short idea at a time.

## Sources

Every river begins somewhere high. Rain and springs feed it.

### Springs

A spring is water that comes out of the ground where the water table meets the surface. Springs
often feed the first small streams of a river.

### Glacial melt

- Glaciers melt fastest in late summer.
- Meltwater carries fine rock flour.

### Meanders

A meander is a bend in a river. Water flows faster on the outside of the bend and erodes the bank.

## Mouths

A delta is a landform built where a river slows down and drops its sediment into still water.
An estuary is the wide tidal mouth of a river where fresh water mixes with salt water.
"""


def _topic_texts(md: str) -> dict[str, str]:
    book = parse_course(md)
    return {t.title: md[t.start : t.end] for c in book.chapters for t in c.topics}


def test_short_preface_chapter_lead_and_list_section_are_kept():
    texts = _topic_texts(RIVERS)
    joined = "\n".join(texts.values())
    assert "This little book follows water" in joined  # preface under 60 words
    assert "Every river begins somewhere high" in joined  # chapter lead under 40 words
    assert "Glaciers melt fastest" in joined  # a section that is only a list
    assert "Introduction" in texts and "Overview" in texts and "Glacial melt" in texts


def test_html_article_lead_paragraph_is_a_topic():
    md = "# How deltas form\n\nA delta is a landform built where a river slows down.\n\n## Why deltas are fertile\n\nEach flood leaves silt."
    texts = _topic_texts(md)
    assert any("A delta is a landform" in t for t in texts.values())


def test_word_counts_ignore_markdown_markers(con):
    md = "# T\n\n## Part one\n\n- alpha beta\n- gamma\n\n| a | b |\n| --- | --- |\n\nText --- here."
    assert count_words(md) == 10  # T Part one alpha beta gamma a b Text here
    bid = add_book(con, Converted(md, "T", "markdown", {}))
    assert con.execute("SELECT n_words FROM books WHERE id=?", (bid,)).fetchone()[0] == count_words(md)
    n = con.execute("SELECT n_words FROM topics WHERE book_id=?", (bid,)).fetchone()[0]
    assert n == 7  # alpha beta gamma a b Text here, and "|"/"-"/"---" are not words


def test_concepts_merge_plurals_and_take_terms_the_text_defines():
    texts = _topic_texts(RIVERS)
    names = list(texts)
    cons, _ = concepts.extract([texts[n] for n in names], titles=names)
    by = {n: [c.term for c in cs] for n, cs in zip(names, cons, strict=True)}
    assert "spring" in by["Springs"]  # "spring" once + "springs" once is one concept seen twice
    assert "meander" in by["Meanders"]  # named by the heading, defined once
    assert {"delta", "estuary"} <= set(by["Mouths"])  # each defined once: "A delta is a ..."


def test_verb_forms_adjectives_and_adverbs_are_not_concepts():
    text = ("The cones are built from ash. The cones are built from lava. Inside the cone it is hot. "
            "Inside the cone gas collects. A well-known cone is steep. Another well-known cone is wide. "
            "The chemical change is fast. The chemical change is slow. The chemical action of acid works. "
            "The chemical action of heat works.")
    other = "Clouds form over the sea. Wind moves clouds over land. Rain falls from clouds."
    terms = {c.term for c in concepts.extract([text, other, other, other])[0][0]}
    assert not terms & {"built", "inside", "well-known", "chemical"}
    assert "chemical action" in terms or "cone" in terms  # a phrase may still start with an adjective


def test_hyphenated_compounds_are_searchable_by_their_parts():
    assert tokens("a soap-bubble") == tokens("a soap bubble")


def test_ask_soap_bubble_finds_the_hyphenated_passage(con, sample_book):
    r = ask.ask(con, sample_book, "What happens to a soap bubble in carbonic acid?", use_llm=False)
    assert r["answered"] and any("soap-bubble" in c["quote"] for c in r["citations"])


def test_made_of_question_quotes_the_composed_of_sentence(con, sample_book):
    r = ask.ask(con, sample_book, "What is gunpowder made of?", use_llm=False)
    assert any("gunpowder is composed of carbon" in c["quote"] for c in r["citations"])
    r = ask.ask(con, sample_book, "gunpowder kis cheez se bana hai?", use_llm=False)
    assert any("gunpowder is composed of carbon" in c["quote"] for c in r["citations"])


def test_how_to_make_question_quotes_the_making_sentence(con, sample_book):
    for q in ("How do you make hydrogen?", "ہائیڈروجن کیسے بنتی ہے؟"):
        r = ask.ask(con, sample_book, q, use_llm=False)
        assert any("bits of zinc" in c["quote"] for c in r["citations"]), q


def test_how_is_water_made_quotes_a_sentence_about_producing_water(con, sample_book):
    for q in ("pani kaise banta hai", "How is water made?"):
        r = ask.ask(con, sample_book, q, use_llm=False)
        assert any("produce" in c["quote"] and "water" in c["quote"].lower() for c in r["citations"][:1]), q


def test_cues_never_answer_an_off_book_question(con, sample_book):
    for q in ("How do you make a cake?", "What is the moon made of?", "How do you make a website?"):
        r = ask.ask(con, sample_book, q, use_llm=False)
        assert not r["answered"], q


def test_a_hyphenated_number_does_not_split_a_phrase(con, sample_book):
    # "A man in twenty-four hours converts ..." keeps "man ... converts" within the phrase gap
    r = ask.ask(con, sample_book, "How much carbon does a man convert in a day by respiration?", use_llm=False)
    assert r["answered"] and any("seven ounces of carbon" in c["quote"] for c in r["citations"])


def test_roman_urdu_grammar_word_ne_is_not_a_glossary_word():
    a = urdu.analyse("cricket world cup kis ne jeeta?")
    assert all(m["from"] != "ne" for m in a.mapped)
    assert urdu.analyse("maye kya hai").mapped[0]["to"] == "liquid fluid"  # the real word still maps


def test_question_with_only_unknown_words_says_the_book_does_not_say(con, sample_book):
    r = ask.ask(con, sample_book, "پاکستان کا دارالحکومت کیا ہے؟", use_llm=False)
    assert not r["answered"] and "does not say" in r["message"]
    r = ask.ask(con, sample_book, "???", use_llm=False)
    assert "searchable words" in r["message"]


def test_hard_wrapped_answer_is_one_line_with_a_matching_hint(con):
    md = ("# B\n\n## Lakes\n\nWhen the neck of a meander is cut through during a flood, the old bend is left as an oxbow\n"
          "lake. An oxbow lake slowly fills with silt and plants over many years of floods.\n\n"
          "An oxbow lake is a curved lake. Oxbow lakes are common on wide flat plains near rivers.\n\n"
          "## Hills\n\nHills are raised land. Hills erode under rain and wind over many thousands of years.")
    bid = add_book(con, Converted(md, "B", "markdown", {}))
    for (tid,) in con.execute("SELECT id FROM topics WHERE book_id=?", (bid,)).fetchall():
        quiz.ensure_pool(con, tid)
    rows = con.execute("SELECT kind, answer, options FROM questions WHERE book_id=? AND kind='cloze'", (bid,)).fetchall()
    assert rows
    for _kind, ans, opts in rows:
        assert "\n" not in ans and len(json.loads(opts)["hint"]) == len(ans)


def test_distractor_is_never_a_compound_of_the_answer():
    import random

    out = quiz._distractors(["air-pump", "flame", "wick", "zinc"], "pump",
                            "The pump draws the water up the pipe.", 4, random.Random(1))
    assert "air-pump" not in out and sorted(out) == ["flame", "wick", "zinc"]
    out = quiz._distractors(["nitric acid", "flame", "wick", "zinc"], "acid", "The acid eats the metal away.",
                            3, random.Random(1))
    assert "nitric acid" not in out


def test_summary_is_plain_text_without_emphasis_markers():
    from studyloop.concepts import _summary

    s = _summary(["*Michael Faraday, a course of six lectures delivered before a juvenile audience."], [])
    assert s == "Michael Faraday, a course of six lectures delivered before a juvenile audience."
