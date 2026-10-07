"""Every HTTP endpoint, through the real FastAPI app with a temporary SQLite file."""

from __future__ import annotations

from conftest import TINY_BOOK
from fastapi.testclient import TestClient

from studyloop import ask, net
from studyloop.app import create_app


def _upload(client, name="rivers.md", data=TINY_BOOK.encode(), **form):
    return client.post("/api/books", files={"file": (name, data)}, data=form)


def test_health_and_static_frontend(client):
    assert client.get("/api/health").json()["ok"] is True
    html = client.get("/")
    assert html.status_code == 200 and "StudyLoop" in html.text
    assert client.get("/app.js").status_code == 200 and client.get("/style.css").status_code == 200


def test_empty_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["books"] == [] and d["totals"]["topics"] == 0 and d["review_next"] == []
    assert d["activity"]["streak"] == 0 and d["daily_goal"] == 10


def test_upload_markdown_book_and_read_course(client):
    r = _upload(client)
    assert r.status_code == 202 and r.json()["status"] == "ready"
    bid = r.json()["id"]
    b = client.get(f"/api/books/{bid}").json()
    assert b["title"] == "A Small Book of Rivers" and b["chapters"] == 2
    assert [c["title"] for c in b["course"]] == ["Chapter 1: Water Basics", "Chapter 2: Using Rivers"]
    t = b["course"][0]["topics"][0]
    assert t["concepts"] and t["mastery"]["level"] == "new"
    assert b["suggestions"] and all(s.endswith("?") for s in b["suggestions"])
    assert client.get("/api/books").json()[0]["id"] == bid
    assert client.get(f"/api/books/{bid}/markdown").text == TINY_BOOK
    assert client.get("/api/books/999").status_code == 404


def test_upload_title_override_and_bad_uploads(client):
    assert _upload(client, title="My rivers").status_code == 202
    assert client.get("/api/books").json()[0]["title"] == "My rivers"
    bad = _upload(client, "x.md", b"   ")
    b = client.get(f"/api/books/{bad.json()['id']}").json()
    assert b["status"] == "error" and "no text" in b["error"]
    assert client.post("/api/books").status_code == 400
    assert client.post("/api/books", data={"url": "ftp://x"}).status_code == 400


def test_pdf_upload_end_to_end(client, tmp_path):
    from booktoskill.samplepdf import tiny_book, write_pdf

    pdf = write_pdf(tmp_path / "t.pdf", tiny_book(), title="A Tiny Book")
    r = _upload(client, "t.pdf", pdf.read_bytes())
    b = client.get(f"/api/books/{r.json()['id']}").json()
    assert b["status"] == "ready" and b["source_type"] == "pdf" and b["course"]


def test_url_import_uses_web_to_markdown(client, monkeypatch):
    from test_ingest import HTML

    monkeypatch.setattr(
        "studyloop.net.fetch_page", lambda url: (HTML.encode(), url, "text/html; charset=utf-8"))
    r = client.post("/api/books", data={"url": "https://example.org/rivers"})
    assert r.status_code == 202
    b = client.get(f"/api/books/{r.json()['id']}").json()
    assert b["status"] == "ready" and "Rivers" in b["title"]
    md = client.get(f"/api/books/{b['id']}/markdown").text
    assert "sediment" in md and "Copyright" not in md


def test_url_failure_is_reported(client, monkeypatch):
    def boom(url):
        raise net.FetchFailed("could not fetch: offline")

    monkeypatch.setattr("studyloop.net.fetch_page", boom)
    r = client.post("/api/books", data={"url": "https://example.org/x"})
    assert client.get(f"/api/books/{r.json()['id']}").json()["error"].endswith("offline")


def test_sample_book_endpoint_is_idempotent(client):
    a = client.post("/api/books/sample")
    b = client.post("/api/books/sample")
    assert a.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/books").json()) == 1


def test_background_import_completes(db_path):
    import time

    c = TestClient(create_app(db_path, sync_import=False))
    bid = _upload(c).json()["id"]
    for _ in range(100):
        if c.get(f"/api/books/{bid}").json()["status"] != "processing":
            break
        time.sleep(0.05)
    assert c.get(f"/api/books/{bid}").json()["status"] == "ready"


def test_topic_quiz_answer_flow_updates_mastery(client):
    bid = client.post("/api/books/sample").json()["id"]
    course = client.get(f"/api/books/{bid}").json()["course"]
    tid = course[2]["topics"][3]["id"]
    t = client.get(f"/api/topics/{tid}").json()
    assert t["text"] and t["n_questions"] >= 6 and t["mastery"]["attempts"] == 0
    assert t["prev"] and t["next"] and t["chapter"] == course[2]["title"]
    qs = client.get(f"/api/topics/{tid}/quiz?n=4").json()["questions"]
    assert len(qs) == 4 and all("answer" not in q for q in qs)
    q = next(x for x in qs if x["kind"] == "mcq")
    wrong = client.post("/api/quiz/answer", json={"question_id": q["id"], "response": "zzz"}).json()
    assert wrong["correct"] is False and wrong["quote"] and wrong["mastery"]["attempts"] == 1
    right = client.post("/api/quiz/answer", json={"question_id": q["id"], "response": wrong["answer"]}).json()
    assert right["correct"] is True and right["mastery"]["attempts"] == 2
    assert client.post("/api/quiz/answer", json={"question_id": "nope", "response": "x"}).status_code == 404
    assert client.get("/api/topics/99999").status_code == 404
    assert client.get("/api/topics/99999/quiz").status_code == 404
    assert client.get(f"/api/topics/{tid}/quiz?n=0").status_code == 422
    book = client.get(f"/api/books/{bid}").json()
    m = book["course"][2]["topics"][3]["mastery"]
    assert m["attempts"] == 2 and book["progress"]["practised"] == 1


def test_generate_questions_needs_a_model(client, monkeypatch):
    monkeypatch.delenv("STUDYLOOP_LLM", raising=False)
    bid = client.post("/api/books/sample").json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][0]["id"]
    assert client.post(f"/api/topics/{tid}/quiz/generate").status_code == 409
    assert client.get("/api/llm").json()["configured"] is False


def test_ask_endpoint_answers_abstains_and_validates(client):
    bid = _upload(client).json()["id"]
    r = client.post("/api/ask", json={"book_id": bid, "question": "What is a levee?", "use_llm": False}).json()
    assert r["answered"] and r["citations"][0]["quote"].startswith("A levee is a raised bank")
    r = client.post("/api/ask", json={"book_id": bid, "question": "Who won the 1998 world cup?"}).json()
    assert r["answered"] is False
    assert client.post("/api/ask", json={"book_id": bid, "question": ""}).status_code == 422
    assert client.post("/api/ask", json={"book_id": 999, "question": "x"}).status_code == 404


def test_ask_endpoint_urdu_and_history(client):
    bid = client.post("/api/books/sample").json()["id"]
    r = client.post("/api/ask", json={"book_id": bid, "question": "پانی کیا ہے؟"}).json()
    assert r["analysis"]["language"] == "ur" and r["answered"]
    h = client.get(f"/api/history?book_id={bid}").json()
    assert h[0]["question"] == "پانی کیا ہے؟" and h[0]["language"] == "ur"


def test_review_endpoints(client):
    bid = client.post("/api/books/sample").json()["id"]
    nxt = client.get("/api/review/next").json()
    assert nxt[0]["reason"] == "next new topic"
    tid = nxt[0]["topic_id"]
    for q in client.get(f"/api/topics/{tid}/quiz?n=3").json()["questions"]:
        client.post("/api/quiz/answer", json={"question_id": q["id"], "response": "zzz"})
    sched = client.get(f"/api/review/schedule?book_id={bid}").json()
    assert len(sched["today"]) + len(sched["overdue"]) == 1
    assert client.get(f"/api/review/next?book_id={bid}&limit=1").json()[0]["topic_id"] == tid


def test_notes_endpoints(client):
    bid = _upload(client).json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][0]["id"]
    n = client.post("/api/notes", json={"topic_id": tid, "text": "deltas are fertile"})
    assert n.status_code == 201
    nid = n.json()["id"]
    assert client.get(f"/api/notes?topic_id={tid}").json()[0]["text"] == "deltas are fertile"
    assert client.put(f"/api/notes/{nid}", json={"text": "deltas are very fertile"}).json()["text"].endswith("fertile")
    assert client.get(f"/api/topics/{tid}").json()["notes"][0]["id"] == nid
    assert client.post("/api/notes", json={"book_id": bid, "text": "book-level"}).status_code == 201
    assert client.post("/api/notes", json={"text": "orphan"}).status_code == 400
    assert client.post("/api/notes", json={"topic_id": 999, "text": "x"}).status_code == 404
    assert client.delete(f"/api/notes/{nid}").json() == {"deleted": nid}
    assert client.delete(f"/api/notes/{nid}").status_code == 404
    assert client.put("/api/notes/999", json={"text": "x"}).status_code == 404


def test_memory_search_sessions_and_events(client):
    bid = _upload(client).json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][1]["id"]
    client.post("/api/ask", json={"book_id": bid, "question": "What is a levee?", "use_llm": False})
    client.post("/api/notes", json={"topic_id": tid, "text": "levee notes for exam"})
    assert client.post("/api/events", json={"kind": "read", "topic_id": tid}).json() == {"ok": True}
    assert client.post("/api/events", json={"kind": "read", "topic_id": 999}).status_code == 404
    assert client.post("/api/events", json={"kind": "bogus", "topic_id": tid}).status_code == 422
    kinds = {r["type"] for r in client.get("/api/memory/search?q=levee").json()}
    assert kinds == {"note", "question"}
    assert client.get("/api/memory/search").status_code == 422
    s = client.get("/api/memory/sessions").json()
    assert len(s) == 1 and s[0]["questions"] == 1


def test_settings_roundtrip_and_validation(client):
    assert client.get("/api/settings").json() == {"daily_goal": 10, "theme": "auto", "use_llm": True}
    r = client.put("/api/settings", json={"daily_goal": 20, "theme": "dark", "use_llm": False}).json()
    assert r == {"daily_goal": 20, "theme": "dark", "use_llm": False}
    assert client.get("/api/dashboard").json()["daily_goal"] == 20
    assert client.put("/api/settings", json={"daily_goal": 0}).status_code == 422
    assert client.put("/api/settings", json={"theme": "pink"}).status_code == 422


def test_use_llm_setting_disables_the_model(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "ask", lambda con, bid, q, use_llm=True, client=None: seen.append(use_llm) or {"ok": 1})
    bid = _upload(client).json()["id"]
    client.put("/api/settings", json={"use_llm": False})
    client.post("/api/ask", json={"book_id": bid, "question": "What is a levee?", "use_llm": True})
    assert seen == [False]


def test_delete_book_removes_everything(client, db_path):
    import sqlite3

    bid = client.post("/api/books/sample").json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][0]["id"]
    q = client.get(f"/api/topics/{tid}/quiz?n=1").json()["questions"][0]
    client.post("/api/quiz/answer", json={"question_id": q["id"], "response": "x"})
    client.post("/api/notes", json={"topic_id": tid, "text": "n"})
    assert client.delete(f"/api/books/{bid}").json() == {"deleted": bid}
    assert client.delete(f"/api/books/{bid}").status_code == 404
    con = sqlite3.connect(db_path)
    for table in ("books", "chapters", "topics", "passages", "questions", "attempts", "mastery", "notes"):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    con.close()
    assert client.get("/api/dashboard").json()["books"] == []


def test_dashboard_with_progress(client):
    bid = client.post("/api/books/sample").json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][0]["id"]
    for q in client.get(f"/api/topics/{tid}/quiz?n=5").json()["questions"]:
        client.post("/api/quiz/answer", json={"question_id": q["id"], "response": "x"})
    d = client.get("/api/dashboard").json()
    assert d["books"][0]["progress"]["practised"] == 1
    assert d["activity"]["today"] == 5 and d["activity"]["streak"] == 1 and d["activity"]["accuracy"] is not None
    assert d["review_next"][0]["topic_id"] == tid


def test_notes_export_and_flashcards_csv(client):
    import csv
    import io

    bid = _upload(client).json()["id"]
    tid = client.get(f"/api/books/{bid}").json()["course"][0]["topics"][0]["id"]
    client.post("/api/notes", json={"topic_id": tid, "text": "remember the delta"})
    client.post("/api/notes", json={"book_id": bid, "text": "=HYPERLINK(whole book)"})
    client.post("/api/ask", json={"book_id": bid, "question": "What is a delta?", "use_llm": False})
    md = client.get(f"/api/books/{bid}/notes.md")
    assert "remember the delta" in md.text and "## Whole book" in md.text
    assert "What is a delta?" in md.text and "attachment" in md.headers["content-disposition"]
    r = client.get(f"/api/books/{bid}/flashcards.csv")
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0] == ["Front", "Back", "Source"] and len(rows) - 1 == int(r.headers["x-cards"]) > 0
    assert all(len(x) == 3 and x[1] for x in rows[1:])
    assert client.get("/api/books/999/flashcards.csv").status_code == 404


def test_csv_cells_cannot_start_a_spreadsheet_formula():
    from studyloop.exports import _cell

    assert _cell("=1+1").startswith("'=") and _cell("@x").startswith("'@") and _cell("ok") == "ok"


def test_pasted_text_becomes_a_book(client):
    r = client.post("/api/books", data={"text": TINY_BOOK, "title": "Pasted rivers"})
    assert r.status_code == 202
    b = client.get(f"/api/books/{r.json()['id']}").json()
    assert b["status"] == "ready" and b["title"] == "Pasted rivers"
    assert client.post("/api/books", data={"text": "   "}).status_code == 400


def test_import_interrupted_by_restart_is_marked_failed(db_path):
    from studyloop import db

    con = db.connect(db_path)
    con.execute("INSERT INTO books(title, source_type, status, added_at) VALUES ('x','web','processing',1)")
    con.commit()
    con.close()
    c = TestClient(create_app(db_path, sync_import=True))
    b = c.get("/api/books").json()[0]
    assert b["status"] == "error" and "restart" in b["error"]
