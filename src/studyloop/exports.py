"""Take your study material out: notes as markdown, definitions as an Anki-ready CSV.

Both are built only from the book's own text and the user's own notes: flashcard answers are the
sentences the book uses to define each concept, never generated text.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3

from . import memory

_FORMULA = re.compile(r"^[=+\-@\t\r]")


def _cell(text: str) -> str:
    """Spreadsheets run a cell that starts with = + - @ as a formula; a leading quote defuses it."""
    text = " ".join(str(text).split())
    return "'" + text if _FORMULA.match(text) else text


def notes_markdown(con: sqlite3.Connection, book_id: int) -> str:
    book = con.execute("SELECT title FROM books WHERE id=?", (book_id,)).fetchone()
    notes = memory.list_notes(con, book_id)
    by_topic: dict[int | None, list[dict]] = {}
    for n in sorted(notes, key=lambda n: n["created"]):
        by_topic.setdefault(n["topic_id"], []).append(n)
    out = [f"# My notes: {book['title']}", ""]
    if not notes:
        out.append("No notes yet.")
    order = [
        (r["id"], r["chapter"], r["title"])
        for r in con.execute(
            "SELECT t.id, t.title, c.title AS chapter FROM topics t JOIN chapters c "
            "ON c.id=t.chapter_id WHERE t.book_id=? ORDER BY t.ord", (book_id,))
    ]
    if None in by_topic:
        out += ["## Whole book", ""] + [f"{n['text']}\n" for n in by_topic[None]]
    for tid, chapter, title in order:
        if tid in by_topic:
            out += [f"## {chapter} / {title}", ""] + [f"{n['text']}\n" for n in by_topic[tid]]
    asked = memory.question_history(con, book_id, 500)
    if asked:
        out += ["## Questions I asked", ""]
        for q in asked:
            out.append(f"- {q['question']} ({'answered' if q['answered'] else 'not in the book'})")
    return "\n".join(out).rstrip() + "\n"


def flashcards_csv(con: sqlite3.Connection, book_id: int) -> tuple[str, int]:
    """Front, Back, Source: one card per concept the book defines. Returns (csv text, cards)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Front", "Back", "Source"])
    n = 0
    seen: set[str] = set()
    for t in con.execute(
        "SELECT t.title, t.concepts, c.title AS chapter FROM topics t JOIN chapters c "
        "ON c.id=t.chapter_id WHERE t.book_id=? ORDER BY t.ord", (book_id,)
    ):
        for c in json.loads(t["concepts"]):
            term, definition = c.get("term"), c.get("definition")
            if not term or not definition or term.lower() in seen:
                continue
            seen.add(term.lower())
            w.writerow([_cell(f"What does the book say {term} is?"), _cell(definition),
                        _cell(f"{t['chapter']} / {t['title']}")])
            n += 1
    return buf.getvalue(), n
