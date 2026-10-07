"""Memory across sessions: an event log, notes, and versioned settings, all in SQLite.

Ideas taken from agent-memory (D:\\github\\agent-memory): every raw event is kept with its
timestamp and session; settings are *facts* where a newer value supersedes the old one without
deleting it, so "what was true on date X" can be answered; recall is BM25 over the stored text.
"""

from __future__ import annotations

import json
import sqlite3

from . import db
from ._vendor.bm25 import BM25
from .textutil import tokens

SESSION_GAP = 30 * 60  # a new session starts after 30 idle minutes


def session(con: sqlite3.Connection) -> int:
    t = db.now()
    row = con.execute("SELECT id, last_seen FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    if row and t - row["last_seen"] <= SESSION_GAP:
        con.execute("UPDATE sessions SET last_seen=? WHERE id=?", (t, row["id"]))
        con.commit()
        return row["id"]
    cur = con.execute("INSERT INTO sessions(started, last_seen) VALUES (?,?)", (t, t))
    con.commit()
    return cur.lastrowid


def record(
    con: sqlite3.Connection, kind: str, *, book_id: int | None = None,
    topic_id: int | None = None, payload: dict | None = None,
) -> int:
    sid = session(con)
    cur = con.execute(
        "INSERT INTO events(session_id, ts, kind, book_id, topic_id, payload) VALUES (?,?,?,?,?,?)",
        (sid, db.now(), kind, book_id, topic_id, json.dumps(payload or {}, ensure_ascii=False)),
    )
    con.commit()
    return cur.lastrowid


# ---- notes -------------------------------------------------------------------------------

def add_note(con: sqlite3.Connection, book_id: int, topic_id: int | None, text: str) -> dict:
    t = db.now()
    cur = con.execute(
        "INSERT INTO notes(book_id, topic_id, text, created, updated) VALUES (?,?,?,?,?)",
        (book_id, topic_id, text.strip(), t, t),
    )
    con.commit()
    record(con, "note", book_id=book_id, topic_id=topic_id, payload={"note_id": cur.lastrowid})
    return get_note(con, cur.lastrowid)


def get_note(con: sqlite3.Connection, note_id: int) -> dict | None:
    r = con.execute(
        "SELECT n.*, t.title AS topic FROM notes n LEFT JOIN topics t ON t.id = n.topic_id "
        "WHERE n.id=?", (note_id,)
    ).fetchone()
    return dict(r) if r else None


def update_note(con: sqlite3.Connection, note_id: int, text: str) -> dict | None:
    con.execute("UPDATE notes SET text=?, updated=? WHERE id=?", (text.strip(), db.now(), note_id))
    con.commit()
    return get_note(con, note_id)


def delete_note(con: sqlite3.Connection, note_id: int) -> bool:
    cur = con.execute("DELETE FROM notes WHERE id=?", (note_id,))
    con.commit()
    return cur.rowcount > 0


def list_notes(con: sqlite3.Connection, book_id: int | None = None, topic_id: int | None = None) -> list[dict]:
    sql = (
        "SELECT n.*, t.title AS topic, b.title AS book FROM notes n "
        "LEFT JOIN topics t ON t.id = n.topic_id LEFT JOIN books b ON b.id = n.book_id WHERE 1=1"
    )
    args: list = []
    if book_id is not None:
        sql += " AND n.book_id=?"
        args.append(book_id)
    if topic_id is not None:
        sql += " AND n.topic_id=?"
        args.append(topic_id)
    return [dict(r) for r in con.execute(sql + " ORDER BY n.updated DESC", args)]


# ---- question history ----------------------------------------------------------------------

def question_history(con: sqlite3.Connection, book_id: int | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT e.*, b.title AS book FROM events e LEFT JOIN books b ON b.id = e.book_id WHERE e.kind='ask'"
    args: list = []
    if book_id is not None:
        sql += " AND e.book_id=?"
        args.append(book_id)
    out = []
    for r in con.execute(sql + " ORDER BY e.id DESC LIMIT ?", [*args, limit]):
        p = json.loads(r["payload"])
        out.append({
            "id": r["id"], "ts": r["ts"], "book_id": r["book_id"], "book": r["book"],
            "session_id": r["session_id"], "question": p.get("question"),
            "language": p.get("language"), "answered": p.get("answered"), "mode": p.get("mode"),
            "answer": p.get("answer"), "citations": p.get("citations", []),
        })
    return out


# ---- versioned facts (settings) -------------------------------------------------------------

def set_fact(con: sqlite3.Connection, key: str, value) -> None:
    """Supersede, never overwrite: the old row keeps its validity window."""
    t = db.now()
    con.execute("UPDATE facts SET valid_to=? WHERE key=? AND valid_to IS NULL", (t, key))
    con.execute(
        "INSERT INTO facts(key, value, valid_from) VALUES (?,?,?)", (key, json.dumps(value), t)
    )
    con.commit()


def get_fact(con: sqlite3.Connection, key: str, default=None, at: float | None = None):
    if at is None:
        r = con.execute(
            "SELECT value FROM facts WHERE key=? AND valid_to IS NULL ORDER BY id DESC", (key,)
        ).fetchone()
    else:
        r = con.execute(
            "SELECT value FROM facts WHERE key=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) "
            "ORDER BY id DESC", (key, at, at),
        ).fetchone()
    return json.loads(r["value"]) if r else default


def fact_history(con: sqlite3.Connection, key: str) -> list[dict]:
    return [dict(r) | {"value": json.loads(r["value"])} for r in con.execute(
        "SELECT * FROM facts WHERE key=? ORDER BY id", (key,))]


def settings(con: sqlite3.Connection) -> dict:
    out = {"daily_goal": 10, "theme": "auto", "use_llm": True}
    for r in con.execute("SELECT key, value FROM facts WHERE valid_to IS NULL"):
        out[r["key"]] = json.loads(r["value"])
    return out


# ---- recall ---------------------------------------------------------------------------------

def recall(con: sqlite3.Connection, query: str, book_id: int | None = None, k: int = 10) -> list[dict]:
    """BM25 over notes and past questions (and the answers given), best first."""
    items: list[dict] = []
    for n in list_notes(con, book_id):
        items.append({"type": "note", "id": n["id"], "text": n["text"], "book_id": n["book_id"],
                      "topic_id": n["topic_id"], "ts": n["updated"], "book": n.get("book"),
                      "topic": n.get("topic")})
    for h in question_history(con, book_id, limit=500):
        items.append({"type": "question", "id": h["id"],
                      "text": (h["question"] or "") + " " + (h["answer"] or ""),
                      "question": h["question"], "book_id": h["book_id"], "ts": h["ts"],
                      "book": h["book"], "answered": h["answered"]})
    q = tokens(query)
    if not items or not q:
        return []
    bm = BM25([tokens(i["text"]) for i in items])
    scores = bm.scores(q)
    order = sorted(range(len(items)), key=lambda i: -scores[i])
    return [items[i] | {"score": round(scores[i], 3)} for i in order[:k] if scores[i] > 0]
