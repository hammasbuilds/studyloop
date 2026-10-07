"""Per-topic knowledge state: Bayesian Knowledge Tracing plus a spaced-review schedule.

The BKT update is the forward filter from knowledge-tracing (``kt/models/bkt.py``,
``BKT.predict_skills``): after each answer the posterior P(known | answer) is computed with the
guess and slip rates, then the learning transition is applied. As that repo documents, mastery is
judged on P(known), the latent state, never on P(correct), which is capped at 1 - slip.

Differences from the study: the parameters are fixed priors rather than fitted (one learner, a
handful of answers per topic leaves nothing to fit), and the guess rate depends on the question
type: a true/false item is guessed half the time, a typed blank least often, but even a blank can
be filled from the sentence around it, so no type gets a guess rate near zero. BKT with a fixed
slip also barely reacts to a wrong answer once P(known) is near 1, so "mastered" additionally
needs ``MIN_ANSWERS`` answers and ``RECENT_OK`` of the last ``RECENT`` right.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass

from . import db

PRIOR = 0.30
LEARN = 0.10
SLIP = 0.20  # kt: many skills fit slip at its 0.3 bound; 0.1 let one wrong answer in four barely register
GUESS = {"cloze": 0.15, "mcq": 0.30, "tf": 0.55, "llm": 0.30}
MIN_ANSWERS = 8  # "mastered" also needs this many answers: six lucky ones prove little
RECENT = 8  # ...and at least RECENT_OK of the last RECENT answers right
RECENT_OK = 6
REPEAT_GUESS = 0.6  # a question seen before can be answered from memory of the question
MASTERED = 0.95  # the threshold kt uses for P(known)
DAY = 86400.0
RETENTION_AT_DUE = 0.9


def bkt_update(p_known: float, correct: bool, guess: float, slip: float = SLIP, learn: float = LEARN) -> float:
    """One step of the BKT forward filter; returns P(known) after the answer and the learning step."""
    if correct:
        num = p_known * (1 - slip)
        den = num + (1 - p_known) * guess
    else:
        num = p_known * slip
        den = num + (1 - p_known) * (1 - guess)
    post = num / den if den else p_known
    return post + (1 - post) * learn


def p_correct(p_known: float, guess: float, slip: float = SLIP) -> float:
    return p_known * (1 - slip) + (1 - p_known) * guess


def next_interval(p_known: float, correct: bool, prev_days: float, reviews_mastered: int) -> float:
    """Days until the topic should be reviewed again, from the state after an answer."""
    if not correct or p_known < 0.5:
        return 10 / 1440  # ten minutes: not yet known, ask again soon
    if p_known < 0.8:
        return 1.0
    if p_known < MASTERED:
        return 2.0
    return min(90.0, max(4.0, prev_days * 2.2)) if reviews_mastered else 4.0


def recall(p_known: float, last_ts: float | None, interval_days: float, now: float) -> float:
    """P(known) decayed by a forgetting curve whose stability makes recall 0.9 at the due date."""
    if last_ts is None:
        return p_known
    stability = max(interval_days, 10 / 1440) / -math.log(RETENTION_AT_DUE)
    return p_known * math.exp(-max(0.0, now - last_ts) / DAY / stability)


def solid(p_known: float, attempts: int, recent: str) -> bool:
    """P(known) over the bar, enough answers, and a recent record that agrees with it."""
    last = recent[-RECENT:]
    return (
        p_known >= MASTERED and attempts >= MIN_ANSWERS
        and len(last) >= RECENT and last.count("1") >= RECENT_OK
    )


def level(p_known: float, attempts: int, recent: str = "") -> str:
    if attempts == 0:
        return "new"
    if solid(p_known, attempts, recent):
        return "mastered"
    if p_known >= 0.6:
        return "getting there"
    return "learning"


@dataclass
class State:
    topic_id: int
    book_id: int
    p_known: float = PRIOR
    attempts: int = 0
    correct: int = 0
    streak: int = 0
    last_ts: float | None = None
    due_ts: float | None = None
    interval_days: float = 0.0
    reviews_mastered: int = 0
    recent: str = ""  # 1/0 per answer, oldest first, last RECENT kept


def get_state(con: sqlite3.Connection, topic_id: int, book_id: int | None = None) -> State:
    r = con.execute("SELECT * FROM mastery WHERE topic_id=?", (topic_id,)).fetchone()
    if r:
        return State(**{k: r[k] for k in r.keys()})
    if book_id is None:
        book_id = con.execute("SELECT book_id FROM topics WHERE id=?", (topic_id,)).fetchone()[0]
    return State(topic_id, book_id)


def save_state(con: sqlite3.Connection, s: State) -> None:
    con.execute(
        "INSERT OR REPLACE INTO mastery(topic_id, book_id, p_known, attempts, correct, streak, "
        "last_ts, due_ts, interval_days, reviews_mastered, recent) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (s.topic_id, s.book_id, s.p_known, s.attempts, s.correct, s.streak, s.last_ts, s.due_ts,
         s.interval_days, s.reviews_mastered, s.recent),
    )


def observe(
    con: sqlite3.Connection, topic_id: int, kind: str, correct: bool, repeat: bool = False
) -> State:
    """Fold one answer into the topic's state and reschedule its review.

    ``repeat`` marks a question the learner has seen before: a remembered answer is weak evidence
    of knowing the topic, so the guess rate is raised to ``REPEAT_GUESS``.
    """
    s = get_state(con, topic_id)
    now = db.now()
    # Forget first: a review a week late starts from what is still remembered.
    base = recall(s.p_known, s.last_ts, s.interval_days, now) if s.attempts else s.p_known
    guess = max(GUESS.get(kind, 0.25), REPEAT_GUESS) if repeat else GUESS.get(kind, 0.25)
    s.p_known = bkt_update(base, correct, guess)
    s.attempts += 1
    s.correct += int(correct)
    s.streak = s.streak + 1 if correct else 0
    s.recent = (s.recent + ("1" if correct else "0"))[-RECENT:]
    if solid(s.p_known, s.attempts, s.recent) and correct:
        s.reviews_mastered += 1
    elif not correct:
        s.reviews_mastered = 0
    shown = s.p_known if solid(s.p_known, s.attempts, s.recent) else min(s.p_known, MASTERED - 0.01)
    s.interval_days = next_interval(shown, correct, s.interval_days, s.reviews_mastered)
    s.last_ts = now
    s.due_ts = now + s.interval_days * DAY
    save_state(con, s)
    con.commit()
    return s


def describe(s: State, now: float | None = None) -> dict:
    now = db.now() if now is None else now
    eff = recall(s.p_known, s.last_ts, s.interval_days, now)
    due_in = None if s.due_ts is None else (s.due_ts - now) / DAY
    return {
        "p_known": round(s.p_known, 4), "recall": round(eff, 4), "attempts": s.attempts,
        "correct": s.correct, "streak": s.streak, "level": level(s.p_known, s.attempts, s.recent),
        "last_ts": s.last_ts, "due_ts": s.due_ts, "due_in_days": None if due_in is None else round(due_in, 3),
        "due": bool(s.attempts and due_in is not None and due_in <= 0),
        "interval_days": round(s.interval_days, 3),
    }


def topic_rows(con: sqlite3.Connection, book_id: int | None = None) -> list[dict]:
    sql = (
        "SELECT t.id AS topic_id, t.book_id, t.ord, t.title AS topic, c.title AS chapter, "
        "b.title AS book, m.* FROM topics t JOIN chapters c ON c.id=t.chapter_id "
        "JOIN books b ON b.id=t.book_id LEFT JOIN mastery m ON m.topic_id=t.id"
    )
    args: tuple = ()
    if book_id is not None:
        sql += " WHERE t.book_id=?"
        args = (book_id,)
    out = []
    now = db.now()
    for r in con.execute(sql + " ORDER BY t.book_id, t.ord", args):
        s = State(r["topic_id"], r["book_id"]) if r["attempts"] is None else State(
            r["topic_id"], r["book_id"], r["p_known"], r["attempts"], r["correct"], r["streak"],
            r["last_ts"], r["due_ts"], r["interval_days"], r["reviews_mastered"], r["recent"],
        )
        out.append({"topic_id": r["topic_id"], "book_id": r["book_id"], "book": r["book"],
                    "chapter": r["chapter"], "topic": r["topic"], "ord": r["ord"],
                    **describe(s, now)})
    return out


def review_next(con: sqlite3.Connection, book_id: int | None = None, limit: int = 6) -> list[dict]:
    """What to study now: due reviews (weakest and most overdue first), then the next new topic,
    then the topics whose remembered mastery has decayed furthest."""
    rows = topic_rows(con, book_id)
    out: list[dict] = []
    # A topic the learner is failing is worth another go straight away, due date or not.
    due = [r for r in rows if r["due"] or (r["attempts"] and r["p_known"] < 0.6)]
    due.sort(key=lambda r: (r["recall"] - 0.05 * max(0.0, -(r["due_in_days"] or 0)), r["ord"]))
    for r in due:
        late = -(r["due_in_days"] or 0)
        why = "weak, review now" if r["p_known"] < 0.6 else (
            f"due, {late:.1f} days late" if late >= 0.5 else "due for review")
        out.append(r | {"reason": why})
    seen_books: set[int] = set()
    for r in rows:
        if r["attempts"] == 0 and r["book_id"] not in seen_books:
            seen_books.add(r["book_id"])
            out.append(r | {"reason": "next new topic"})
    rest = [r for r in rows if r["attempts"] and not (r["due"] or r["p_known"] < 0.6)]
    rest.sort(key=lambda r: r["recall"])
    for r in rest:
        if r["level"] != "mastered":
            out.append(r | {"reason": "still shaky"})
    return out[:limit]


def schedule(con: sqlite3.Connection, book_id: int | None = None) -> dict:
    """Practised topics grouped by when their next review falls."""
    now = db.now()
    groups: dict[str, list[dict]] = {"overdue": [], "today": [], "this_week": [], "later": []}
    for r in topic_rows(con, book_id):
        if not r["attempts"]:
            continue
        d = r["due_in_days"]
        if d <= 0:
            groups["overdue" if d < -1 else "today"].append(r)
        elif d <= 1:
            groups["today"].append(r)
        elif d <= 7:
            groups["this_week"].append(r)
        else:
            groups["later"].append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["due_ts"])
    return {"now": now, **groups}


def book_progress(con: sqlite3.Connection, book_id: int) -> dict:
    rows = topic_rows(con, book_id)
    n = len(rows)
    practised = [r for r in rows if r["attempts"]]
    return {
        "topics": n,
        "practised": len(practised),
        "mastered": sum(1 for r in rows if r["level"] == "mastered"),
        "due": sum(1 for r in rows if r["due"]),
        "avg_known": round(sum(r["p_known"] if r["attempts"] else 0.0 for r in rows) / n, 4) if n else 0.0,
        "avg_recall": round(sum(r["recall"] if r["attempts"] else 0.0 for r in rows) / n, 4) if n else 0.0,
        "last_ts": max((r["last_ts"] for r in practised if r["last_ts"]), default=None),
    }


def activity(con: sqlite3.Connection, days: int = 14) -> dict:
    """Answers per local calendar day for the last ``days`` days, the current streak, and totals."""
    now = db.now()
    today = time.localtime(now)
    midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
    counts: dict[int, list[int]] = {}
    total = right = 0
    for r in con.execute("SELECT ts, correct FROM attempts"):
        d = int((midnight - _midnight(r["ts"])) / DAY + 0.5)
        c = counts.setdefault(d, [0, 0])
        c[0] += 1
        c[1] += r["correct"]
        total += 1
        right += r["correct"]
    series = []
    for i in range(days - 1, -1, -1):
        c = counts.get(i, [0, 0])
        day = time.localtime(midnight - i * DAY + 3600)
        series.append({"date": time.strftime("%Y-%m-%d", day), "answered": c[0], "correct": c[1]})
    streak = 0
    start = 0 if counts.get(0) else 1  # a quiet today does not break yesterday's streak
    while counts.get(start + streak):
        streak += 1
    return {"series": series, "streak": streak, "total": total, "correct": right,
            "accuracy": round(right / total, 4) if total else None,
            "today": counts.get(0, [0, 0])[0]}


def _midnight(ts: float) -> float:
    t = time.localtime(ts)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
