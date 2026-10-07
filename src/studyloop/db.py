"""SQLite storage. One file holds books, the course, questions, attempts, mastery and memory."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, source_type TEXT NOT NULL, source_ref TEXT,
  status TEXT NOT NULL DEFAULT 'processing', error TEXT, markdown TEXT NOT NULL DEFAULT '',
  n_words INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL, meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS chapters (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, ord INTEGER NOT NULL, title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, chapter_id INTEGER NOT NULL,
  ord INTEGER NOT NULL, title TEXT NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
  n_words INTEGER NOT NULL, summary TEXT NOT NULL DEFAULT '', concepts TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS passages (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, topic_id INTEGER NOT NULL,
  ord INTEGER NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY, book_id INTEGER NOT NULL, topic_id INTEGER NOT NULL, kind TEXT NOT NULL,
  prompt TEXT NOT NULL, options TEXT NOT NULL DEFAULT '[]', answer TEXT NOT NULL,
  accept TEXT NOT NULL DEFAULT '[]', explanation TEXT NOT NULL DEFAULT '',
  q_start INTEGER NOT NULL, q_end INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'rules'
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY, question_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
  book_id INTEGER NOT NULL, session_id INTEGER, response TEXT, correct INTEGER NOT NULL, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mastery (
  topic_id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, p_known REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0,
  streak INTEGER NOT NULL DEFAULT 0, last_ts REAL, due_ts REAL,
  interval_days REAL NOT NULL DEFAULT 0, reviews_mastered INTEGER NOT NULL DEFAULT 0,
  recent TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, topic_id INTEGER, text TEXT NOT NULL,
  created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, started REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, session_id INTEGER, ts REAL NOT NULL, kind TEXT NOT NULL,
  book_id INTEGER, topic_id INTEGER, payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL,
  valid_from REAL NOT NULL, valid_to REAL
);
CREATE INDEX IF NOT EXISTS ix_topics_book ON topics(book_id, ord);
CREATE INDEX IF NOT EXISTS ix_passages_topic ON passages(topic_id);
CREATE INDEX IF NOT EXISTS ix_questions_topic ON questions(topic_id);
CREATE INDEX IF NOT EXISTS ix_attempts_topic ON attempts(topic_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind, ts);
"""


def home() -> Path:
    """Where StudyLoop keeps its data: ``$STUDYLOOP_HOME`` or ``~/.studyloop``."""
    return Path(os.environ.get("STUDYLOOP_HOME") or Path.home() / ".studyloop")


def default_db_path() -> Path:
    return home() / "studyloop.sqlite3"


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")
    return con


def init(path: str | Path) -> None:
    con = connect(path)
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


def now() -> float:
    """The clock every module uses; tests replace ``db.CLOCK`` to move time."""
    return CLOCK()


CLOCK = time.time


def delete_book(con: sqlite3.Connection, book_id: int) -> None:
    for table in ("attempts", "mastery", "questions", "passages", "topics", "chapters", "notes"):
        con.execute(f"DELETE FROM {table} WHERE book_id=?", (book_id,))
    con.execute("DELETE FROM events WHERE book_id=?", (book_id,))
    con.execute("DELETE FROM books WHERE id=?", (book_id,))
    con.commit()
