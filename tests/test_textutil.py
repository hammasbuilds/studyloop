from studyloop.textutil import locate, split_sentences, stem, tokens


def test_stem_joins_inflections():
    assert stem("burns") == stem("burning") == stem("burn") == "burn"
    assert stem("candles") == stem("candle")
    assert stem("produced") == stem("produce")
    assert stem("gas") == "gas" and stem("glass") == "glass"


def test_tokens_drop_stopwords():
    assert tokens("What is the flame of a candle?") == [stem("flame"), stem("candle")]
    assert "the" not in tokens("the candle")


def test_sentences_keep_abbreviations_and_offsets():
    text = "Mr. Field brought candles. They burn well! Do they? Yes."
    spans = split_sentences(text)
    parts = [text[a:b] for a, b in spans]
    assert parts[0] == "Mr. Field brought candles."
    assert parts[1] == "They burn well!"
    assert len(parts) == 4


def test_locate_exact_and_whitespace_tolerant():
    src = "A river  is a\nnatural stream. Another sentence."
    a, b = locate(src, "A river is a natural stream.")
    assert src[a:b] == "A river  is a\nnatural stream."
    assert locate(src, "a RIVER is a natural stream.") is not None
    assert locate(src, "a lake is a natural stream.") is None
    assert locate(src, "   ") is None
