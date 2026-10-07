import json

from studyloop import ask, llm
from studyloop.textutil import locate


class FakeLLM:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, prompt, system="", max_tokens=700):
        self.prompts.append(prompt)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def test_extractive_answer_quotes_are_exact_source_slices(con, tiny_book):
    r = ask.ask(con, tiny_book, "What is a delta?", use_llm=False)
    assert r["answered"] and r["mode"] == "extractive"
    md = con.execute("SELECT markdown FROM books WHERE id=?", (tiny_book,)).fetchone()[0]
    assert r["citations"]
    for c in r["citations"]:
        assert md[c["start"] : c["end"]] == c["quote"]
        assert locate(md, c["quote"]) == (c["start"], c["end"])
        assert c["verified"] and c["line"] >= 1 and c["topic"]
    assert "delta" in r["citations"][0]["quote"].lower()


def test_off_topic_question_abstains(con, tiny_book):
    qs = ("Who won the 1998 world cup?", "How do I train a neural network?", "What is the weather today")
    for q in qs:
        r = ask.ask(con, tiny_book, q, use_llm=False)
        assert not r["answered"] and r["citations"] == [], q
        assert "does not say" in r["message"]


def test_question_whose_words_are_in_different_places_abstains(con, tiny_book):
    r = ask.ask(con, tiny_book, "How fast do barges travel through a turbine?", use_llm=False)
    assert not r["answered"]


def test_urdu_question_answers_from_english_book(con, sample_book):
    r = ask.ask(con, sample_book, "موم بتی کیوں جلتی ہے؟", use_llm=False)
    assert r["answered"] and r["analysis"]["language"] == "ur"
    assert {"candl", "burn"} <= set(r["analysis"]["terms"])
    r2 = ask.ask(con, sample_book, "pani kaise banta hai", use_llm=False)
    assert r2["answered"] and r2["analysis"]["language"] == "roman-ur"


def test_llm_answer_keeps_only_verified_quotes(con, tiny_book):
    good = "A delta is a flat area of land shaped like a triangle and made of deposited sediment."
    fake = FakeLLM(
        {
            "supported": True,
            "answer": "A delta is a triangular flat of sediment.",
            "quotes": [
                {"passage": 1, "quote": good},
                {"passage": 1, "quote": "Deltas were invented by Napoleon."},
            ],
        }
    )
    r = ask.ask(con, tiny_book, "What is a delta?", client=fake)
    assert r["mode"] == "llm:fake" and r["answer"].startswith("A delta is a triangular")
    assert [c["quote"] for c in r["citations"]] == [good]
    assert r["dropped_quotes"] == 1


def test_llm_with_only_fabricated_quotes_falls_back_to_extractive(con, tiny_book):
    fake = FakeLLM(
        {
            "supported": True,
            "answer": "Deltas are magic.",
            "quotes": [{"passage": 1, "quote": "Deltas are magic and eternal."}],
        }
    )
    r = ask.ask(con, tiny_book, "What is a delta?", client=fake)
    assert r["answered"] and r["mode"] == "extractive" and r["dropped_quotes"] == 1
    assert "magic" not in r["answer"]


def test_llm_saying_unsupported_abstains(con, tiny_book):
    fake = FakeLLM({"supported": False, "answer": "", "quotes": []})
    r = ask.ask(con, tiny_book, "What is a delta?", client=fake)
    assert not r["answered"]


def test_llm_garbage_or_failure_falls_back(con, tiny_book):
    r = ask.ask(con, tiny_book, "What is a levee?", client=FakeLLM("not json at all"))
    assert r["mode"] == "extractive" and r["answered"]

    class Boom(FakeLLM):
        def complete(self, *a, **k):
            raise llm.LLMError("connection refused")

    r = ask.ask(con, tiny_book, "What is a levee?", client=Boom({}))
    assert r["answered"] and r["mode"] == "extractive" and "unavailable" in r["message"]


def test_llm_prompt_contains_only_book_passages(con, tiny_book):
    fake = FakeLLM({"supported": False})
    ask.ask(con, tiny_book, "What is a lock?", client=fake)
    assert "chamber with gates" in fake.prompts[0] and "Question: What is a lock?" in fake.prompts[0]


def test_question_is_logged_to_memory(con, tiny_book):
    ask.ask(con, tiny_book, "What is a levee?", use_llm=False)
    assert con.execute("SELECT COUNT(*) FROM events WHERE kind='ask'").fetchone()[0] == 1


def test_llm_status_without_env(monkeypatch):
    monkeypatch.delenv("STUDYLOOP_LLM", raising=False)
    assert llm.get_client() is None and llm.status()["configured"] is False
    monkeypatch.setenv("STUDYLOOP_LLM", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.get_client() is None and "missing" in llm.status()["note"]
    monkeypatch.setenv("STUDYLOOP_LLM", "ollama")
    assert llm.get_client().name == "ollama"


def test_parse_json_variants():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json("Sure! [1, 2] done") == [1, 2]
    assert llm.parse_json("nothing") is None
