import re

import pytest

from studyloop import urdu
from studyloop.textutil import stem
from studyloop.urdu import analyse, book_vocab, detect_language, skeleton

VOCAB = book_vocab(
    re.findall(
        r"[A-Za-z]+", "candle burns flame oxygen hydrogen water carbonic acid river sediment levee"
    )
)


def test_language_detection():
    assert detect_language("What is hydrogen?") == "en"
    assert detect_language("ہائیڈروجن کیا ہے") == "ur"
    assert detect_language("pani kaise banta hai") == "roman-ur"
    assert detect_language("candle kyun jalti hai") == "roman-ur"
    assert detect_language("hydrogen in the candle") == "en"


@pytest.mark.parametrize(
    "q,expect",
    [
        ("موم بتی کیوں جلتی ہے؟", {"candl", "burn"}),
        ("mom batti kyun jalti hai", {"candl", "burn"}),
        ("pani kaise banta hai", {"water"}),
        ("پانی کیا ہے", {"water"}),
        ("shola kya hai", {"flam"}),
    ],
)
def test_urdu_and_roman_urdu_map_to_english_terms(q, expect):
    a = analyse(q, VOCAB)
    assert expect <= set(a.terms), a
    assert a.ignored == []


def test_intent_from_question_word():
    assert analyse("موم بتی کیوں جلتی ہے؟", VOCAB).intent == "why"
    assert analyse("pani kaise banta hai", VOCAB).intent == "how"
    assert analyse("What is hydrogen?", VOCAB).intent == "what"


def test_loanword_matches_by_sound():
    a = analyse("آکسیجن کیا ہے", VOCAB)
    assert "oxygen" in a.terms or "oxygen" in [m["to"] for m in a.mapped]
    assert skeleton("oksijan") == skeleton("oxygen")


def test_unknown_words_are_reported_not_silently_dropped():
    a = analyse("zindagi kya hai", VOCAB)
    assert "zindagi" in a.ignored and a.terms == []


def test_english_question_drops_stopwords_and_filler():
    a = analyse("Can you tell me what a levee is?", VOCAB)
    assert a.terms == [stem("levee")]


def test_glossary_has_no_empty_entries():
    for eng, ur, ro in urdu.GLOSSARY:
        assert eng.strip() and ur.strip() and ro.strip()
