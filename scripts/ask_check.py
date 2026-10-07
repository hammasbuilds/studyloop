"""How often does ask-the-book answer, and from the right place? No model, no server.

On-book questions are built from the book itself: for every topic, "What does the book say about
<its top concept>?" Gold is the topic the concept was extracted from or any topic that contains
the concept's words; a hit means a cited quote contains the concept's words. Off-book questions
are 20 questions the sample book cannot answer; the right outcome is to abstain.

    uv run python scripts/ask_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from studyloop import ask, db, ingest

sys.stdout.reconfigure(encoding="utf-8")

OFF_BOOK = [
    "Who won the 1998 world cup?", "What is the capital of France?",
    "How do I train a neural network?", "What is the boiling point of mercury?",
    "Who wrote Hamlet?", "How many people live in Tokyo?", "What is the speed of light?",
    "How do vaccines work?", "What is inflation?", "Explain the French Revolution.",
    "How do I bake bread?", "What is machine learning?", "Who painted the Mona Lisa?",
    "What is the tallest mountain on Earth?", "How does the stock market work?",
    "What is photosynthesis in detail?", "What causes earthquakes?", "Who invented the telephone?",
    "What is the population of Pakistan?", "How do airplanes fly?",
    "What is the melting point of iron?", "What is the freezing point of mercury?",
    "What is the boiling point of ethanol?", "How hot is the surface of the sun?",
]


def main() -> None:
    path = Path(tempfile.mkdtemp(prefix="studyloop_check_")) / "c.sqlite3"
    db.init(path)
    con = db.connect(path)
    bid = ingest.sample_book(con)
    rows = con.execute("SELECT id, title, concepts FROM topics ORDER BY ord").fetchall()
    answered = hit = total = 0
    for r in rows:
        cons = json.loads(r["concepts"])
        if not cons:
            continue
        term = cons[0]["term"]
        total += 1
        res = ask.ask(con, bid, f"What does the book say about {term}?", use_llm=False)
        if res["answered"]:
            answered += 1
            words = [w.lower() for w in term.split()]
            if any(all(w in c["quote"].lower() for w in words) for c in res["citations"]):
                hit += 1
    print(f"On-book questions : {total}")
    print(f"  answered        : {answered}/{total}")
    print(f"  quote has the concept's words : {hit}/{total}")
    wrong = [q for q in OFF_BOOK if ask.ask(con, bid, q, use_llm=False)["answered"]]
    print(f"Off-book questions: {len(OFF_BOOK)}")
    print(f"  abstained       : {len(OFF_BOOK) - len(wrong)}/{len(OFF_BOOK)}")
    for q in wrong:
        print(f"  answered anyway : {q}")


if __name__ == "__main__":
    main()
