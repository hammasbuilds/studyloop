"""Drive the real UI in a headless browser and take the README screenshots.

    uv run studyloop --no-browser --port 8799 --db <tmp.sqlite3>        # in one shell
    uv run --with playwright python scripts/ui_tour.py http://127.0.0.1:8799 <tmp.sqlite3> docs/screenshots

It answers quiz questions through the interface (reading the correct answers from the SQLite
file so that a fixed share can be answered wrongly on purpose), asks English, Urdu and Roman Urdu
questions, and fails if the page logs a console error or a request fails.
"""

from __future__ import annotations

import http.server
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, DB, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
problems: list[str] = []

RIVERS_MD = (Path(__file__).resolve().parent.parent / "tests" / "conftest.py").read_text(encoding="utf-8").split('TINY_BOOK = """')[1].split('"""')[0]
RIVERS_HTML = """<html><head><title>Rivers explained</title></head><body><nav>Home | About</nav><article><h1>Rivers explained</h1>
<p>A river is a natural stream of fresh water that flows toward an ocean, a lake or another river. Rivers carry sediment from the land and build deltas where they meet the sea, which is why deltas are so fertile.</p>
<h2>Floods</h2><p>A flood happens when a river carries more water than its channel can hold, usually after heavy rain or when snow melts quickly in the spring. Levees are built beside rivers to hold the water in.</p>
</article><footer>Copyright</footer></body></html>"""


def answer_for(prompt: str) -> tuple[str, str]:
    con = sqlite3.connect(DB)
    row = con.execute("SELECT answer, kind FROM questions WHERE prompt=? LIMIT 1", (prompt,)).fetchone()
    con.close()
    return row


def play_quiz(page, miss_every: int = 3, shot: str | None = None, start: str = "#startq") -> None:
    page.click(start)
    n = 0
    while True:
        page.wait_for_selector(".q-prompt")
        prompt = page.inner_text(".q-prompt").replace("\n", " ")
        con = sqlite3.connect(DB)
        rows = con.execute("SELECT prompt, answer, kind FROM questions").fetchall()
        con.close()
        norm = lambda s: " ".join(s.replace("_____", "").split())  # noqa: E731
        kind = "cloze" if page.query_selector("#resp") else (
            "mcq" if page.query_selector(".q-prompt .blank") else "tf")
        match = next((r for r in rows if norm(r[0]) == norm(prompt) and r[2] == kind), None)
        assert match, f"no stored {kind} question for {prompt!r}"
        answer = match[1]
        wrong = (n % miss_every) == miss_every - 1
        if kind == "cloze":
            page.fill("#resp", "wrong" if wrong else answer)
            page.click("#submit")
        else:
            opts = page.query_selector_all(".opt")
            pick = next((o for o in opts if (o.get_attribute("data-o") or "").lower() != answer.lower()), opts[0]) if wrong \
                else next(o for o in opts if (o.get_attribute("data-o") or "").lower() == answer.lower())
            pick.click()
        page.wait_for_selector("#next")
        if shot and n == 1:
            page.screenshot(path=str(OUT / shot))
        page.click("#next")
        n += 1
        page.wait_for_function("!document.querySelector('#next')")
        if page.query_selector("#quizbox h2") and "Done" in page.inner_text("#quizbox h2"):
            break


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url}"))
    page.on("response", lambda r: problems.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)

    # Library: upload a markdown file, a PDF and a web page through the UI.
    work = Path(tempfile.mkdtemp(prefix="studyloop_tour_"))
    (work / "rivers.md").write_text(RIVERS_MD, encoding="utf-8")
    (work / "article.html").write_text(RIVERS_HTML, encoding="utf-8")
    from booktoskill.samplepdf import tiny_book, write_pdf

    write_pdf(work / "tiny.pdf", tiny_book(), title="A Tiny Book")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(work), **k)  # noqa: E731
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    page.goto(BASE + "/#/library")
    page.wait_for_selector("#drop")
    for name in ("rivers.md", "tiny.pdf"):
        page.set_input_files("#file", str(work / name))
        page.wait_for_selector(f"text={name.split('.')[0].replace('rivers', 'A Small Book of Rivers').replace('tiny', 'A Tiny Book')}", timeout=20000)
    page.fill("#url", f"http://127.0.0.1:{web.server_address[1]}/article.html")
    page.click("#addurl")
    page.wait_for_selector("text=Rivers explained", timeout=20000)
    page.wait_for_function("!document.querySelector('#books .spinner')", timeout=20000)
    page.screenshot(path=str(OUT / "02-library.png"))
    n_books = len(page.query_selector_all("#books .li"))
    assert n_books == 4, f"expected 4 books, saw {n_books}"
    # Remove the web page again through the UI (confirm dialog accepted).
    page.once("dialog", lambda d: d.accept())
    page.click("#books .li:has-text('Rivers explained') [data-del]")
    page.wait_for_function("document.querySelectorAll('#books .li').length === 3")
    web.shutdown()

    page.goto(BASE + "/#/book/1")
    page.wait_for_selector(".topic-row")
    page.screenshot(path=str(OUT / "03-course-outline.png"), full_page=False)

    topic_ids = [int(a.get_attribute("href").split("/")[-1]) for a in page.query_selector_all(".topic-row a.t")]
    # Study four topics through the UI.
    for k, tid in enumerate(topic_ids[1:5]):
        page.goto(f"{BASE}/#/topic/{tid}")
        page.wait_for_selector("#startq")
        if k == 0:
            page.fill("#newnote", "Faraday's key idea: the candle's products are water and carbonic acid.")
            page.click("#addnote")
            page.wait_for_selector("[data-note]")
        play_quiz(page, miss_every=3 if k % 2 == 0 else 4, shot="04-quiz-feedback.png" if k == 0 else None)
        if k == 0:
            page.screenshot(path=str(OUT / "05-quiz-done.png"))
        if k < 2:  # a second round on the first two topics: new questions, then repeats
            play_quiz(page, miss_every=5, start="#again")
    page.goto(BASE + f"/#/topic/{topic_ids[2]}")
    page.wait_for_selector(".reading")
    page.screenshot(path=str(OUT / "06-reading-topic.png"))

    page.goto(BASE + "/#/ask/1")
    page.wait_for_selector("#q")
    for q, shot in (("What is capillary attraction?", "07-ask-english.png"),
                    ("موم بتی کیوں جلتی ہے؟", "08-ask-urdu.png"),
                    ("pani kaise banta hai", "09-ask-roman-urdu.png"),
                    ("Who won the 1998 world cup?", "10-ask-not-in-book.png")):
        page.fill("#q", q)
        page.click("#go")
        page.wait_for_selector(".answer-box")
        page.screenshot(path=str(OUT / shot))
    page.fill("#q", "What is hydrogen?")
    page.click("#go")
    page.wait_for_selector(".cite a")
    page.click(".cite a >> nth=0")
    page.wait_for_selector("mark.hl")
    page.wait_for_timeout(900)  # let the smooth scroll land on the highlighted quote
    page.screenshot(path=str(OUT / "11-quote-located.png"))

    page.goto(BASE + "/#/")
    page.wait_for_selector(".book-card")
    page.screenshot(path=str(OUT / "01-dashboard.png"))
    page.goto(BASE + "/#/review")
    page.wait_for_selector(".sched")
    page.screenshot(path=str(OUT / "12-review.png"))
    page.goto(BASE + "/#/memory")
    page.wait_for_selector("#save")
    page.fill("#goal", "30")
    page.click("#save")
    page.wait_for_selector("text=Settings saved")
    page.fill("#mq", "capillary")
    page.click("#msearch")
    page.wait_for_selector("#mres .cite")
    page.screenshot(path=str(OUT / "13-memory.png"))

    page.goto(BASE + "/#/")
    page.wait_for_selector(".book-card")
    page.click("#theme")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "14-dashboard-dark.png"))
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(BASE + "/#/book/1")
    page.wait_for_selector(".topic-row")
    page.screenshot(path=str(OUT / "15-mobile-outline.png"))
    browser.close()

print("problems:", problems or "none")
sys.exit(1 if problems else 0)
