"""The StudyLoop web app: a FastAPI backend serving the single-page frontend in ``static/``."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ask as ask_mod
from . import db, exports, ingest, mastery, memory, net, quiz
from . import llm as llm_mod

STATIC = Path(__file__).parent / "static"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
_import_slots = threading.BoundedSemaphore(2)  # imports are CPU-heavy: two at a time


class AskBody(BaseModel):
    book_id: int
    question: str = Field(min_length=1, max_length=1000)
    use_llm: bool = True
    log: bool = True  # False: a preview (the home page's try-it panel) that is not recorded as a question


class AnswerBody(BaseModel):
    question_id: str
    response: str = Field(default="", max_length=500)


class NoteBody(BaseModel):
    book_id: int | None = None
    topic_id: int | None = None
    text: str = Field(min_length=1, max_length=20000)


class EventBody(BaseModel):
    kind: str = Field(pattern="^(read)$")
    topic_id: int


class SettingsBody(BaseModel):
    daily_goal: int | None = Field(default=None, ge=1, le=500)
    theme: str | None = Field(default=None, pattern="^(auto|light|dark)$")
    use_llm: bool | None = None


def _host_of(netloc: str) -> str:
    h = netloc.strip().lower()
    if h.startswith("["):
        return h[1 : h.find("]")]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


async def _read_limited(file: UploadFile) -> bytes:
    """Read an upload in pieces and stop as soon as it is over the limit."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf += chunk
        if len(buf) > ingest.MAX_UPLOAD:
            raise HTTPException(413, "file is larger than 60 MB")
    return bytes(buf)


def create_app(
    db_path: str | Path | None = None, sync_import: bool = False, loopback_only: bool = True
) -> FastAPI:
    """``sync_import`` runs imports inline (tests); the default imports in a background thread.

    ``loopback_only`` (the default) answers only requests addressed to localhost / 127.0.0.1 and
    refuses cross-site writes, which closes DNS-rebinding and drive-by form posts from other
    websites. Start with ``--host 0.0.0.0`` and it is switched off (there is no login either way).
    """
    path = Path(db_path) if db_path else db.default_db_path()
    db.init(path)
    _con = db.connect(path)
    try:  # an import killed by a restart would otherwise show "processing" forever
        _con.execute("UPDATE books SET status='error', error='import interrupted by a restart; "
                     "add it again' WHERE status='processing'")
        _con.commit()
    finally:
        _con.close()
    app = FastAPI(title="StudyLoop", version="0.1.0")
    app.state.db_path = path
    app.state.sync_import = sync_import

    def get_con() -> Iterator[sqlite3.Connection]:
        con = db.connect(path)
        try:
            yield con
        finally:
            con.close()

    Con = Depends(get_con)  # noqa: N806

    @app.middleware("http")
    async def guard(request: Request, call_next):
        from fastapi.responses import JSONResponse

        if loopback_only:
            if _host_of(request.headers.get("host", "")) not in LOOPBACK_HOSTS:
                return JSONResponse({"detail": "unexpected Host header"}, status_code=403)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                site = request.headers.get("sec-fetch-site")
                if site in ("cross-site", "same-site") or (
                    origin and origin != "null"
                    and origin.split("://", 1)[-1].lower() != request.headers.get("host", "").lower()
                ) or origin == "null":
                    return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def need_book(con: sqlite3.Connection, book_id: int) -> sqlite3.Row:
        r = con.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "no such book")
        return r

    def need_topic(con: sqlite3.Connection, topic_id: int) -> sqlite3.Row:
        r = con.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "no such topic")
        return r

    def book_card(con: sqlite3.Connection, b: sqlite3.Row) -> dict:
        d = {
            "id": b["id"], "title": b["title"], "source_type": b["source_type"],
            "source_ref": b["source_ref"], "status": b["status"], "error": b["error"],
            "n_words": b["n_words"], "added_at": b["added_at"], "meta": json.loads(b["meta"]),
        }
        if b["status"] == "ready":
            d["chapters"] = con.execute(
                "SELECT COUNT(*) FROM chapters WHERE book_id=?", (b["id"],)).fetchone()[0]
            d["progress"] = mastery.book_progress(con, b["id"])
        return d

    # ---- system ------------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": app.version}

    @app.get("/api/llm")
    def llm_status() -> dict:
        return llm_mod.status()

    @app.get("/api/settings")
    def get_settings(con: sqlite3.Connection = Con) -> dict:
        return memory.settings(con)

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, con: sqlite3.Connection = Con) -> dict:
        for k, v in body.model_dump(exclude_none=True).items():
            memory.set_fact(con, k, v)
        return memory.settings(con)

    @app.get("/api/dashboard")
    def dashboard(con: sqlite3.Connection = Con) -> dict:
        books = [book_card(con, b) for b in con.execute("SELECT * FROM books ORDER BY added_at DESC")]
        act = mastery.activity(con)
        ready = [b for b in books if b["status"] == "ready"]
        topics = sum(b["progress"]["topics"] for b in ready)
        mastered = sum(b["progress"]["mastered"] for b in ready)
        settings = memory.settings(con)
        return {
            "books": books,
            "totals": {
                "books": len(books), "topics": topics, "mastered": mastered,
                "due": sum(b["progress"]["due"] for b in ready),
                "notes": con.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
                "questions_asked": con.execute(
                    "SELECT COUNT(*) FROM events WHERE kind='ask'").fetchone()[0],
            },
            "activity": act,
            "daily_goal": settings["daily_goal"],
            "review_next": mastery.review_next(con, limit=6),
            "llm": llm_mod.status(),
        }

    # ---- library -----------------------------------------------------------------------------

    @app.get("/api/books")
    def list_books(con: sqlite3.Connection = Con) -> list[dict]:
        return [book_card(con, b) for b in con.execute("SELECT * FROM books ORDER BY added_at DESC")]

    def _run_import(book_id: int, convert, user_title: str | None = None) -> None:
        con = db.connect(path)
        try:
            try:
                with _import_slots:
                    conv = convert()
                if user_title:
                    conv.title = user_title
                ingest.add_book(con, conv, con.execute(
                    "SELECT source_ref FROM books WHERE id=?", (book_id,)).fetchone()[0] or "",
                    book_id=book_id)
                ask_mod.invalidate(book_id)
                memory.record(con, "import", book_id=book_id, payload={"title": conv.title})
            except Exception as exc:
                con.rollback()
                msg = str(exc) if isinstance(exc, ingest.IngestError) else f"{type(exc).__name__}: {exc}"
                con.execute("UPDATE books SET status='error', error=? WHERE id=?", (msg[:500], book_id))
                con.commit()
        finally:
            con.close()

    def _start_import(
        con: sqlite3.Connection, title: str, source_type: str, ref: str, convert,
        user_title: str | None = None,
    ) -> dict:
        cur = con.execute(
            "INSERT INTO books(title, source_type, source_ref, status, added_at) VALUES (?,?,?,?,?)",
            (title, source_type, ref, "processing", db.now()),
        )
        con.commit()
        book_id = cur.lastrowid
        if app.state.sync_import:
            _run_import(book_id, convert, user_title)
        else:
            threading.Thread(target=_run_import, args=(book_id, convert, user_title), daemon=True).start()
        return {"id": book_id, "status": con.execute(
            "SELECT status FROM books WHERE id=?", (book_id,)).fetchone()[0]}

    @app.post("/api/books", status_code=202)
    async def add_book(
        file: UploadFile | None = File(default=None),
        url: str | None = Form(default=None),
        title: str | None = Form(default=None),
        text: str | None = Form(default=None),
        con: sqlite3.Connection = Con,
    ) -> dict:
        title = (title or "").strip() or None
        if file is not None and file.filename:
            data = await _read_limited(file)
            name = ingest.clean_filename(file.filename)
            return _start_import(
                con, title or Path(name).stem, "upload", name,
                lambda: ingest.convert_upload(name, data, title), title,
            )
        if url and url.strip():
            u = url.strip()
            try:
                net.check_url_syntax(u)  # scheme, credentials, literal private IPs; DNS is checked later
            except net.UnsafeURL as exc:
                raise HTTPException(400, str(exc)) from exc
            return _start_import(con, title or u, "web", u, lambda: ingest.convert_url(u), title)
        if text and text.strip():
            body = text.encode("utf-8")
            if len(body) > ingest.MAX_UPLOAD:
                raise HTTPException(413, "text is larger than 60 MB")
            # pasted markdown (lines starting with #) is kept as markdown; anything else is plain text
            looks_md = re.search(r"^#{1,3} \S", text, re.M) is not None
            name = (title or "Pasted text") + (".md" if looks_md else ".txt")
            return _start_import(
                con, title or "Pasted text", "upload", "pasted text",
                lambda: ingest.convert_upload(name, body, title), title,
            )
        raise HTTPException(400, "send a file, a url or some text")

    @app.post("/api/books/sample", status_code=201)
    def add_sample(con: sqlite3.Connection = Con) -> dict:
        bid = ingest.sample_book(con)
        ask_mod.invalidate(bid)
        return {"id": bid, "status": "ready"}

    @app.get("/api/books/{book_id}")
    def get_book(book_id: int, con: sqlite3.Connection = Con) -> dict:
        b = need_book(con, book_id)
        d = book_card(con, b)
        if b["status"] != "ready":
            return d
        rows = {r["topic_id"]: r for r in mastery.topic_rows(con, book_id)}
        chapters = []
        for c in con.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY ord", (book_id,)):
            topics = []
            for t in con.execute("SELECT * FROM topics WHERE chapter_id=? ORDER BY ord", (c["id"],)):
                m = rows[t["id"]]
                topics.append({
                    "id": t["id"], "title": t["title"], "ord": t["ord"], "n_words": t["n_words"],
                    "summary": t["summary"], "concepts": json.loads(t["concepts"]),
                    "mastery": {k: m[k] for k in (
                        "p_known", "recall", "attempts", "correct", "level", "due", "due_in_days")},
                })
            chapters.append({"id": c["id"], "title": c["title"], "ord": c["ord"], "topics": topics})
        d["course"] = chapters
        asks: list[str] = []
        for ch in chapters:
            cons = [c for tp in ch["topics"] for c in tp["concepts"]]
            if cons:
                asks.append(f"What does the book say about {cons[0]['term']}?")
        d["suggestions"] = asks[:6]
        return d

    @app.get("/api/books/{book_id}/markdown", response_class=PlainTextResponse)
    def book_markdown(book_id: int, con: sqlite3.Connection = Con) -> str:
        return need_book(con, book_id)["markdown"]

    @app.get("/api/books/{book_id}/notes.md", response_class=PlainTextResponse)
    def book_notes_export(book_id: int, con: sqlite3.Connection = Con) -> PlainTextResponse:
        need_book(con, book_id)
        return PlainTextResponse(
            exports.notes_markdown(con, book_id),
            headers={"Content-Disposition": f'attachment; filename="notes-{book_id}.md"'})

    @app.get("/api/books/{book_id}/flashcards.csv")
    def book_flashcards(book_id: int, con: sqlite3.Connection = Con):
        from fastapi.responses import Response

        need_book(con, book_id)
        text, n = exports.flashcards_csv(con, book_id)
        return Response(
            "﻿" + text, media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="flashcards-{book_id}.csv"',
                     "X-Cards": str(n)})

    @app.delete("/api/books/{book_id}")
    def delete_book(book_id: int, con: sqlite3.Connection = Con) -> dict:
        need_book(con, book_id)
        db.delete_book(con, book_id)
        ask_mod.invalidate(book_id)
        return {"deleted": book_id}

    # ---- topics, reading, quizzes ------------------------------------------------------------

    @app.get("/api/topics/{topic_id}")
    def get_topic(topic_id: int, con: sqlite3.Connection = Con) -> dict:
        t = need_topic(con, topic_id)
        b = need_book(con, t["book_id"])
        ch = con.execute("SELECT title FROM chapters WHERE id=?", (t["chapter_id"],)).fetchone()
        neighbours = con.execute(
            "SELECT id, title, ord FROM topics WHERE book_id=? AND ord IN (?,?)",
            (t["book_id"], t["ord"] - 1, t["ord"] + 1),
        ).fetchall()
        prev = next((dict(n) for n in neighbours if n["ord"] == t["ord"] - 1), None)
        nxt = next((dict(n) for n in neighbours if n["ord"] == t["ord"] + 1), None)
        state = mastery.describe(mastery.get_state(con, topic_id, t["book_id"]))
        return {
            "id": t["id"], "book_id": t["book_id"], "book": b["title"], "chapter": ch["title"],
            "title": t["title"], "start": t["start"], "end": t["end"], "n_words": t["n_words"],
            "text": b["markdown"][t["start"] : t["end"]], "summary": t["summary"],
            "concepts": json.loads(t["concepts"]), "mastery": state, "prev": prev, "next": nxt,
            "notes": memory.list_notes(con, topic_id=topic_id),
            "n_questions": quiz.ensure_pool(con, topic_id),
        }

    @app.post("/api/events")
    def post_event(body: EventBody, con: sqlite3.Connection = Con) -> dict:
        t = need_topic(con, body.topic_id)
        memory.record(con, body.kind, book_id=t["book_id"], topic_id=t["id"])
        return {"ok": True}

    @app.get("/api/topics/{topic_id}/quiz")
    def get_quiz(topic_id: int, n: int = Query(6, ge=1, le=20), con: sqlite3.Connection = Con) -> dict:
        need_topic(con, topic_id)
        return {"topic_id": topic_id, "questions": quiz.pick(con, topic_id, n)}

    @app.post("/api/topics/{topic_id}/quiz/generate")
    def gen_quiz(topic_id: int, con: sqlite3.Connection = Con) -> dict:
        need_topic(con, topic_id)
        client = llm_mod.get_client()
        if client is None:
            raise HTTPException(409, "no LLM configured: the built-in questions are already available")
        return quiz.llm_generate(con, topic_id, client)

    @app.post("/api/quiz/answer")
    def post_answer(body: AnswerBody, con: sqlite3.Connection = Con) -> dict:
        r = quiz.answer(con, body.question_id, body.response)
        if r is None:
            raise HTTPException(404, "no such question")
        return r

    # ---- ask ---------------------------------------------------------------------------------

    @app.post("/api/ask")
    def post_ask(body: AskBody, con: sqlite3.Connection = Con) -> dict:
        b = need_book(con, body.book_id)
        if b["status"] != "ready":
            raise HTTPException(409, "that book is still being processed")
        use = body.use_llm and memory.settings(con)["use_llm"]
        return ask_mod.ask(con, body.book_id, body.question, use_llm=use, log=body.log)

    # ---- mastery & review --------------------------------------------------------------------

    @app.get("/api/review/next")
    def review_next(book_id: int | None = None, limit: int = Query(8, ge=1, le=50),
                    con: sqlite3.Connection = Con) -> list[dict]:
        return mastery.review_next(con, book_id, limit)

    @app.get("/api/review/schedule")
    def review_schedule(book_id: int | None = None, con: sqlite3.Connection = Con) -> dict:
        return mastery.schedule(con, book_id)

    # ---- memory ------------------------------------------------------------------------------

    @app.get("/api/notes")
    def get_notes(book_id: int | None = None, topic_id: int | None = None,
                  con: sqlite3.Connection = Con) -> list[dict]:
        return memory.list_notes(con, book_id, topic_id)

    @app.post("/api/notes", status_code=201)
    def post_note(body: NoteBody, con: sqlite3.Connection = Con) -> dict:
        if body.topic_id is not None:
            t = need_topic(con, body.topic_id)
            book_id = t["book_id"]
        elif body.book_id is not None:
            need_book(con, body.book_id)
            book_id = body.book_id
        else:
            raise HTTPException(400, "give a topic_id or a book_id")
        return memory.add_note(con, book_id, body.topic_id, body.text)

    @app.put("/api/notes/{note_id}")
    def put_note(note_id: int, body: NoteBody, con: sqlite3.Connection = Con) -> dict:
        n = memory.update_note(con, note_id, body.text)
        if n is None:
            raise HTTPException(404, "no such note")
        return n

    @app.delete("/api/notes/{note_id}")
    def del_note(note_id: int, con: sqlite3.Connection = Con) -> dict:
        if not memory.delete_note(con, note_id):
            raise HTTPException(404, "no such note")
        return {"deleted": note_id}

    @app.get("/api/history")
    def history(book_id: int | None = None, limit: int = Query(100, ge=1, le=500),
                con: sqlite3.Connection = Con) -> list[dict]:
        return memory.question_history(con, book_id, limit)

    @app.get("/api/memory/search")
    def memory_search(q: str = Query(min_length=1), book_id: int | None = None,
                      con: sqlite3.Connection = Con) -> list[dict]:
        return memory.recall(con, q, book_id)

    @app.get("/api/memory/sessions")
    def sessions(con: sqlite3.Connection = Con) -> list[dict]:
        rows = con.execute(
            "SELECT s.id, s.started, s.last_seen, "
            "(SELECT COUNT(*) FROM events e WHERE e.session_id=s.id AND e.kind='ask') AS questions, "
            "(SELECT COUNT(*) FROM events e WHERE e.session_id=s.id AND e.kind='quiz') AS answers "
            "FROM sessions s ORDER BY s.id DESC LIMIT 30"
        ).fetchall()
        return [dict(r) for r in rows]

    @app.exception_handler(ingest.IngestError)
    async def ingest_error(_: Request, exc: ingest.IngestError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=400)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def app_from_env() -> FastAPI:  # pragma: no cover - uvicorn factory
    return create_app()
