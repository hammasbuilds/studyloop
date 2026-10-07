import json

from studyloop import quiz
from studyloop.textutil import locate


def _topic(con, book, title):
    return con.execute("SELECT id FROM topics WHERE book_id=? AND title=?", (book, title)).fetchone()[0]


def _pool(con, topic):
    quiz.ensure_pool(con, topic)
    return con.execute("SELECT * FROM questions WHERE topic_id=?", (topic,)).fetchall()


def test_pool_has_all_three_kinds_and_is_deterministic(con, sample_book):
    t = _topic(con, sample_book, "Hydrogen")
    rows = _pool(con, t)
    assert {r["kind"] for r in rows} == {"cloze", "mcq", "tf"}
    first = sorted(r["id"] for r in rows)
    con.execute("DELETE FROM questions")
    assert quiz.generate_for_topic(con, t) == len(first)
    assert sorted(r["id"] for r in _pool(con, t)) == first


def test_every_question_points_at_a_real_sentence(con, sample_book):
    md = con.execute("SELECT markdown FROM books").fetchone()[0]
    for tid in [r[0] for r in con.execute("SELECT id FROM topics LIMIT 6")]:
        for q in _pool(con, tid):
            src = md[q["q_start"] : q["q_end"]]
            assert src.endswith(".") and locate(md, src) == (q["q_start"], q["q_end"])
            if q["kind"] in ("cloze", "mcq"):
                assert q["prompt"].count("_____") == 1
                assert q["prompt"].replace("_____", q["answer"]).lower().replace(" ", "") == \
                    src.lower().replace(" ", "") or q["answer"].lower() in src.lower()


def test_mcq_options_contain_the_answer_once_and_are_distinct(con, sample_book):
    t = _topic(con, sample_book, "Hydrogen")
    mcq = [q for q in _pool(con, t) if q["kind"] == "mcq"]
    assert mcq
    for q in mcq:
        opts = json.loads(q["options"])
        assert len(opts) == 4 and len(set(o.lower() for o in opts)) == 4
        assert opts.count(q["answer"]) == 1


def test_true_false_has_both_answers_and_false_ones_are_not_in_the_book(con, sample_book):
    md = con.execute("SELECT markdown FROM books").fetchone()[0]
    answers = set()
    for tid in [r[0] for r in con.execute("SELECT id FROM topics LIMIT 12")]:
        for q in _pool(con, tid):
            if q["kind"] != "tf":
                continue
            answers.add(q["answer"])
            if q["answer"] == "false":
                assert q["prompt"] not in md
            else:
                assert q["prompt"] in md
    assert answers == {"true", "false"}


def test_public_question_never_leaks_the_answer(con, sample_book):
    t = _topic(con, sample_book, "Hydrogen")
    for q in quiz.pick(con, t, 9):
        assert "answer" not in q and "accept" not in q


def test_pick_mixes_kinds_and_rotates_unseen_first(con, sample_book):
    t = _topic(con, sample_book, "Hydrogen")
    first = quiz.pick(con, t, 6)
    assert len({q["kind"] for q in first}) == 3
    for q in first:
        quiz.answer(con, q["id"], "x")
    second = quiz.pick(con, t, 6)
    assert not {q["id"] for q in first} & {q["id"] for q in second}


def test_grading_cloze_is_forgiving_but_not_loose(con, sample_book):
    q = {"kind": "cloze", "answer": "candles", "accept": json.dumps(["candles", "candle"])}
    assert quiz.grade(q, "Candles")
    assert quiz.grade(q, "the candle")
    assert quiz.grade(q, "candels")  # one typo
    assert not quiz.grade(q, "lamps")
    assert not quiz.grade(q, "")
    short = {"kind": "cloze", "answer": "gas", "accept": json.dumps(["gas"])}
    assert not quiz.grade(short, "gap")  # no typo tolerance on short words


def test_grading_mcq_and_tf():
    assert quiz.grade({"kind": "mcq", "answer": "Water", "accept": "[]"}, "water")
    assert not quiz.grade({"kind": "mcq", "answer": "Water", "accept": "[]"}, "fire")
    assert quiz.grade({"kind": "tf", "answer": "true", "accept": "[]"}, "True")
    assert not quiz.grade({"kind": "tf", "answer": "true", "accept": "[]"}, "maybe")


def test_answer_returns_quote_and_updates_mastery_and_history(con, sample_book):
    t = _topic(con, sample_book, "Hydrogen")
    q = next(x for x in _pool(con, t) if x["kind"] == "mcq")
    r = quiz.answer(con, q["id"], q["answer"])
    assert r["correct"] and r["answer"] == q["answer"]
    assert r["quote"].endswith(".") and r["line"] >= 1
    assert r["mastery"]["attempts"] == 1 and r["mastery"]["p_known"] > 0.3
    assert con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM events WHERE kind='quiz'").fetchone()[0] == 1
    assert quiz.answer(con, "nope", "x") is None


class FakeLLM:
    name, model = "fake", "m"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, prompt, system="", max_tokens=700):
        return json.dumps(self.payload)


def test_llm_questions_are_kept_only_with_a_quote_from_the_topic(con, tiny_book):
    t = _topic(con, tiny_book, "Floods")
    good = "A levee is a raised bank built beside a river to keep the water inside the channel."
    payload = [
        {"question": "What does a levee do?", "options": ["Holds water in", "Makes power", "Ties boats", "Mills grain"],
         "answer_index": 0, "quote": good},
        {"question": "Who built the Great Wall?", "options": ["a", "b", "c", "d"], "answer_index": 1,
         "quote": "The Great Wall was built by emperors."},
        {"question": "Broken", "options": ["a", "a"], "answer_index": 5, "quote": good},
    ]
    out = quiz.llm_generate(con, t, FakeLLM(payload))
    assert out["added"] == 1 and out["rejected"] == 2
    row = con.execute("SELECT * FROM questions WHERE source='llm'").fetchone()
    md = con.execute("SELECT markdown FROM books").fetchone()[0]
    assert md[row["q_start"] : row["q_end"]] == good


def test_llm_failure_is_reported_not_raised(con, tiny_book):
    from studyloop.llm import LLMError

    class Boom:
        name, model = "x", "y"

        def complete(self, *a, **k):
            raise LLMError("down")

    out = quiz.llm_generate(con, _topic(con, tiny_book, "Floods"), Boom())
    assert out["added"] == 0 and "down" in out["error"]
