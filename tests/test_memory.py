from studyloop import ask, memory


def test_facts_supersede_without_deleting(con, clock):
    memory.set_fact(con, "daily_goal", 10)
    t_old = clock.t
    clock.advance(days=2)
    memory.set_fact(con, "daily_goal", 25)
    assert memory.get_fact(con, "daily_goal") == 25
    assert memory.get_fact(con, "daily_goal", at=t_old + 60) == 10  # what was true then
    hist = memory.fact_history(con, "daily_goal")
    assert [h["value"] for h in hist] == [10, 25] and hist[0]["valid_to"] is not None
    assert memory.settings(con)["daily_goal"] == 25


def test_settings_defaults(con):
    s = memory.settings(con)
    assert s == {"daily_goal": 10, "theme": "auto", "use_llm": True}


def test_sessions_split_on_idle_gap(con, clock):
    a = memory.session(con)
    clock.advance(seconds=600)
    assert memory.session(con) == a
    clock.advance(seconds=memory.SESSION_GAP + 1)
    assert memory.session(con) != a


def test_notes_crud(con, tiny_book):
    tid = con.execute("SELECT id FROM topics WHERE title='Floods'").fetchone()[0]
    n = memory.add_note(con, tiny_book, tid, "  A levee holds water in.  ")
    assert n["text"] == "A levee holds water in." and n["topic"] == "Floods"
    assert [x["id"] for x in memory.list_notes(con, topic_id=tid)] == [n["id"]]
    assert memory.update_note(con, n["id"], "edited")["text"] == "edited"
    assert memory.delete_note(con, n["id"]) and not memory.delete_note(con, n["id"])
    assert memory.update_note(con, 999, "x") is None


def test_question_history_and_recall_across_sessions(con, tiny_book, clock):
    ask.ask(con, tiny_book, "What is a levee?", use_llm=False)
    clock.advance(days=3)
    ask.ask(con, tiny_book, "Who won the 1998 world cup?", use_llm=False)
    memory.add_note(con, tiny_book, None, "Remember that a lock raises boats between river levels.")
    h = memory.question_history(con)
    assert [x["answered"] for x in h] == [False, True] and h[0]["session_id"] != h[1]["session_id"]
    hits = memory.recall(con, "levee")
    assert hits and hits[0]["type"] == "question" and "levee" in hits[0]["question"].lower()
    assert memory.recall(con, "lock boats")[0]["type"] == "note"
    assert memory.recall(con, "zzzzqqq") == [] and memory.recall(con, "the") == []
