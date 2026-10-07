import pytest

from studyloop import db, mastery, quiz


def test_bkt_update_matches_hand_calculation():
    # prior .3, correct mcq (guess .25, slip .1), learn .15
    post = 0.3 * 0.9 / (0.3 * 0.9 + 0.7 * 0.25)
    assert mastery.bkt_update(0.3, True, 0.25, slip=0.1, learn=0.15) == pytest.approx(
        post + (1 - post) * 0.15
    )
    wrong = 0.3 * 0.1 / (0.3 * 0.1 + 0.7 * 0.75)
    assert mastery.bkt_update(0.3, False, 0.25, slip=0.1, learn=0.15) == pytest.approx(
        wrong + (1 - wrong) * 0.15
    )


def test_correct_raises_wrong_lowers_and_guessable_questions_count_less():
    p = 0.5
    assert mastery.bkt_update(p, True, 0.05) > mastery.bkt_update(p, True, 0.25) > mastery.bkt_update(p, True, 0.5)
    assert mastery.bkt_update(p, True, 0.25) > p
    assert mastery.bkt_update(0.9, False, 0.25) < 0.9


def test_p_known_can_reach_mastery_but_p_correct_is_capped():
    p = 0.3
    for _ in range(14):
        p = mastery.bkt_update(p, True, 0.05)
    assert p >= mastery.MASTERED
    assert mastery.p_correct(p, 0.05) <= 1 - mastery.SLIP + 0.05


def test_interval_ladder():
    f = mastery.next_interval
    assert f(0.2, True, 0, 0) < 0.01 and f(0.9, False, 5, 2) < 0.01
    assert f(0.7, True, 0, 0) == 1.0 and f(0.9, True, 0, 0) == 2.0
    assert f(0.99, True, 0, 0) == 4.0
    assert f(0.99, True, 4.0, 1) == pytest.approx(8.8) and f(0.99, True, 80.0, 3) == 90.0


def test_recall_decays_to_point_nine_at_the_due_date(clock):
    p = 0.95
    assert mastery.recall(p, 0.0, 4.0, 0.0) == p
    at_due = mastery.recall(p, 0.0, 4.0, 4 * 86400)
    assert at_due == pytest.approx(p * 0.9)
    assert mastery.recall(p, 0.0, 4.0, 40 * 86400) < at_due


def _answer_all(con, topic, correct, n=6):
    for q in quiz.pick(con, topic, n):
        row = con.execute("SELECT answer FROM questions WHERE id=?", (q["id"],)).fetchone()
        quiz.answer(con, q["id"], row[0] if correct else "zzz")


def test_topic_state_flows_into_review_and_schedule(con, tiny_book, clock):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    assert mastery.topic_rows(con, tiny_book)[0]["level"] == "new"
    _answer_all(con, t, correct=False)
    row = next(r for r in mastery.topic_rows(con, tiny_book) if r["topic_id"] == t)
    assert row["level"] == "learning" and row["p_known"] < 0.5
    clock.advance(seconds=900)
    nxt = mastery.review_next(con, tiny_book)
    assert nxt[0]["topic_id"] == t and nxt[0]["due"]
    sched = mastery.schedule(con, tiny_book)
    assert [r["topic_id"] for r in sched["today"]] == [t]


def test_mastered_topic_leaves_the_due_list_until_its_date(con, tiny_book, clock):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    for _ in range(4):
        _answer_all(con, t, correct=True)
        clock.advance(seconds=60)
    row = next(r for r in mastery.topic_rows(con, tiny_book) if r["topic_id"] == t)
    assert row["level"] == "mastered" and not row["due"] and row["due_in_days"] > 1
    assert t not in [r["topic_id"] for r in mastery.review_next(con, tiny_book) if r["due"]]
    clock.advance(days=row["interval_days"] + 1)
    later = next(r for r in mastery.topic_rows(con, tiny_book) if r["topic_id"] == t)
    assert later["due"] and later["recall"] < later["p_known"]


def test_repeating_a_question_counts_less_than_a_new_one(con, tiny_book):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    q = quiz.pick(con, t, 1)[0]
    ans = con.execute("SELECT answer FROM questions WHERE id=?", (q["id"],)).fetchone()[0]
    first = quiz.answer(con, q["id"], ans)["mastery"]["p_known"]
    before = first
    again = quiz.answer(con, q["id"], ans)["mastery"]["p_known"]
    fresh = mastery.bkt_update(before, True, mastery.GUESS[q["kind"]])
    assert again < fresh  # the repeat moved the estimate less than a first sighting would


def test_activity_streak_and_series(con, tiny_book, clock):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    _answer_all(con, t, correct=True, n=3)
    a = mastery.activity(con, days=7)
    assert a["today"] == 3 and a["streak"] == 1 and a["total"] == 3 and a["accuracy"] == 1.0
    assert len(a["series"]) == 7 and a["series"][-1]["answered"] == 3
    clock.advance(days=1)
    assert mastery.activity(con)["streak"] == 1  # a quiet today does not break yesterday's streak
    clock.advance(days=1)
    assert mastery.activity(con)["streak"] == 0


def test_book_progress_counts(con, tiny_book):
    p = mastery.book_progress(con, tiny_book)
    assert p["topics"] == 4 and p["practised"] == 0 and p["mastered"] == 0 and db.now() > 0


def test_a_short_streak_is_not_mastery(con, tiny_book):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    for _ in range(mastery.MIN_ANSWERS - 1):
        mastery.observe(con, t, "cloze", True)
    s = mastery.get_state(con, t)
    assert s.p_known >= mastery.MASTERED and mastery.describe(s)["level"] == "getting there"
    assert s.interval_days <= 2.0
    mastery.observe(con, t, "cloze", True)
    assert mastery.describe(mastery.get_state(con, t))["level"] == "mastered"


def test_a_poor_recent_record_blocks_mastery_even_when_bkt_is_high(con, tiny_book):
    t = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    for i in range(12):
        mastery.observe(con, t, "cloze", i % 3 != 2)  # one wrong answer in three
    s = mastery.get_state(con, t)
    assert s.p_known >= mastery.MASTERED  # BKT with a fixed slip shrugs the misses off...
    assert mastery.describe(s)["level"] == "getting there"  # ...the recent record does not
    assert s.recent.count("1") == 5 and len(s.recent) == mastery.RECENT
