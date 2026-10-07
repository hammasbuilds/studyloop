"""Offline end-to-end demo with no server and no model: sample book -> course -> ask -> quiz -> mastery.

    uv run python demo.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from studyloop import ask, db, ingest, mastery, quiz

sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS = [
    "What is capillary attraction?",
    "Why does a candle burn?",
    "What is hydrogen?",
    "موم بتی کیوں جلتی ہے؟",
    "pani kaise banta hai",
    "ہائیڈروجن کیا ہے؟",
    "Who won the 1998 world cup?",
    "How do I train a neural network?",
    "What is the capital of France?",
]


def main() -> None:
    path = Path(tempfile.mkdtemp(prefix="studyloop_demo_")) / "demo.sqlite3"
    db.init(path)
    con = db.connect(path)
    bid = ingest.sample_book(con)
    book = con.execute("SELECT title, n_words FROM books WHERE id=?", (bid,)).fetchone()
    chapters = con.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    topics = con.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    passages = con.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    print(f"Input : {book['title']} ({book['n_words']:,} words, markdown)")
    print(f"Output: {chapters} chapters, {topics} topics, {passages} retrieval passages\n")

    print("Course outline (first chapter)")
    first = con.execute("SELECT id, title FROM chapters ORDER BY ord LIMIT 1").fetchone()
    for t in con.execute("SELECT * FROM topics WHERE chapter_id=? ORDER BY ord", (first["id"],)):
        terms = ", ".join(c["term"] for c in json.loads(t["concepts"])[:4])
        print(f"  {first['title']} > {t['title']}  [{t['n_words']} words]  concepts: {terms}")

    print("\nAsk the book")
    md = con.execute("SELECT markdown FROM books").fetchone()[0]
    answered = 0
    for q in QUESTIONS:
        r = ask.ask(con, bid, q, use_llm=False)
        answered += r["answered"]
        if r["answered"]:
            c = r["citations"][0]
            assert md[c["start"] : c["end"]] == c["quote"]
            print(f"  {r['analysis']['language']:<8} {q}\n           -> line {c['line']}, chars {c['start']}-{c['end']}, "
                  f"{c['topic']}: \"{c['quote'][:90]}...\"")
        else:
            print(f"  {r['analysis']['language']:<8} {q}\n           -> not in the book")
    print(f"  {answered} of {len(QUESTIONS)} answered, every quote verified against the markdown")

    print("\nQuiz and mastery (topic: Hydrogen, answering 8 of 12 correctly on purpose)")
    tid = con.execute("SELECT id FROM topics WHERE title='Hydrogen'").fetchone()[0]
    quiz.ensure_pool(con, tid)
    kinds = con.execute("SELECT kind, COUNT(*) FROM questions WHERE topic_id=? GROUP BY kind", (tid,)).fetchall()
    print("  question pool:", ", ".join(f"{k} {n}" for k, n in kinds))
    n = 0
    for _ in range(2):
        for q in quiz.pick(con, tid, 6):
            ans = con.execute("SELECT answer FROM questions WHERE id=?", (q["id"],)).fetchone()[0]
            r = quiz.answer(con, q["id"], ans if n % 3 != 2 else "zzz")
            n += 1
            m = r["mastery"]
            print(f"  answer {n:>2} {q['kind']:<5} {'right' if r['correct'] else 'wrong'}  P(known) {m['p_known']:.3f}  {m['level']}")
    s = mastery.get_state(con, tid)
    print(f"  next review in {mastery.describe(s)['due_in_days']:.2f} days; review list:")
    for r in mastery.review_next(con, limit=3):
        print(f"    {r['topic']}: {r['reason']}")


if __name__ == "__main__":
    main()
