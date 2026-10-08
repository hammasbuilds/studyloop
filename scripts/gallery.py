"""Recreate every README gallery screenshot from the real UI (docs/gallery/NN-section.png).

    uv run --with playwright python scripts/gallery.py

Starts its own server on a free port in 8800-8899 with a temporary data directory and no sample
book (so the empty Library is shown first), drives headless Chromium, and stops only the server
process it started. Fails if the page logs a console error or a request fails.
Captions are written to docs/gallery/CAPTIONS.md.
"""

from __future__ import annotations

import http.server
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gallery"
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.png"):
    old.unlink()

PORT = next(p for p in range(8800, 8900) if socket.socket().connect_ex(("127.0.0.1", p)) != 0)
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path(tempfile.mkdtemp(prefix="studyloop_gallery_"))
DB = HOME / "studyloop.sqlite3"
WORK = Path(tempfile.mkdtemp(prefix="studyloop_gallery_files_"))

TINY = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8").split('TINY_BOOK = """')[1].split('"""')[0]
ARTICLE = """<html><head><title>How deltas form</title></head><body><nav>Home | About</nav><article><h1>How deltas form</h1>
<p>A delta is a landform that builds up where a river slows down as it enters the sea or a lake and drops the sediment it was carrying. Over centuries the sediment piles into fan-shaped land.</p>
<h2>Why deltas are fertile</h2><p>Deltas are fertile because each flood leaves a fresh layer of silt rich in minerals, which is why many of the world's oldest farming societies grew up on them.</p>
</article><footer>Copyright</footer></body></html>"""
NOTE = "Faraday's main point: a candle burns to make water and carbonic acid, so the flame is a chemical process."

captions: list[tuple[str, str, str]] = []  # (group, file, caption)
problems: list[str] = []
n_shot = 0


def shot(page, name: str, group: str, caption: str, full: bool = False, clip: dict | None = None, wait: int = 700) -> None:
    global n_shot
    n_shot += 1
    fn = f"{n_shot:02d}-{name}.png"
    page.wait_for_timeout(wait)  # let entrance animations finish
    page.screenshot(path=str(OUT / fn), full_page=full, clip=clip)
    captions.append((group, fn, caption))
    print("shot", fn)


def settled(page, title: str) -> None:
    """Wait until an import has finished: the book is listed, the form says it was added, and the
    toast has gone, so the shot shows the outcome rather than a message from the way there."""
    try:
        page.wait_for_selector(f"#books a:has-text('{title}')", timeout=60000)
    except Exception:
        raise SystemExit(f"import of {title!r} did not finish: msg={page.inner_text('#msg')!r} books={page.inner_text('#books')!r}") from None
    page.wait_for_function("!document.querySelector('#books .spinner')", timeout=30000)
    page.wait_for_selector("#msg:has-text('Added')", timeout=30000)
    page.wait_for_function("!document.querySelector('#toast.show')", timeout=10000)
    page.wait_for_timeout(700)


def correct_answer(prompt: str, kind: str) -> str:
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT prompt, answer, kind FROM questions").fetchall()
    con.close()
    norm = lambda s: " ".join(s.replace("_____", "").split())  # noqa: E731
    return next(r[1] for r in rows if norm(r[0]) == norm(prompt) and r[2] == kind)


def quiz_kind(page) -> str:
    return "cloze" if page.query_selector("#resp") else ("mcq" if page.query_selector(".q-prompt .blank") else "tf")


def answer_current(page, right: bool) -> None:
    prompt = page.inner_text(".q-prompt").replace("\n", " ")
    kind = quiz_kind(page)
    ans = correct_answer(prompt, kind)
    if kind == "cloze":
        page.fill("#resp", ans if right else "wrongword")
        page.click("#submit")
    else:
        opts = page.query_selector_all(".opt")
        want = [o for o in opts if ((o.get_attribute("data-o") or "").lower() == ans.lower()) == right]
        want[0].click()
    page.wait_for_selector("#next")
    page.wait_for_timeout(1100)


server = subprocess.Popen(
    [sys.executable, "-c", f"from studyloop.launcher import main; main(['--no-browser','--no-sample','--port','{PORT}','--db',r'{DB}'])"],
    env={**os.environ, "STUDYLOOP_HOME": str(HOME), "STUDYLOOP_ALLOW_PRIVATE_URLS": "1"},
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
web = None
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1).read()
            break
        except OSError:
            time.sleep(0.2)
    else:
        raise SystemExit("server did not start")

    (WORK / "a-small-book-of-rivers.md").write_text(TINY, encoding="utf-8")
    (WORK / "article.html").write_text(ARTICLE, encoding="utf-8")
    from booktoskill.samplepdf import tiny_book, write_pdf

    write_pdf(WORK / "a-tiny-book.pdf", tiny_book(), title="A Tiny Book")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(WORK), **k)  # noqa: E731
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", bypass_csp=True)
        page = ctx.new_page()
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e} at {page.url} after shot {n_shot} {getattr(e, 'stack', '')}"))
        page.on("requestfailed", lambda r: problems.append(f"requestfailed: {r.url}"))
        page.on("response", lambda r: problems.append(f"http {r.status}: {r.url}") if r.status >= 400 else None)

        # ---------- Library ----------
        G = "Library"
        page.goto(BASE + "/#/library")
        page.wait_for_selector("#drop")
        shot(page, "library-empty", G, "The Library on a fresh install: the drop box, a web address field, a paste box and a book list that says there are no books yet.", full=True)
        page.click("#sample")
        page.wait_for_selector("#books a:has-text('Chemical History')", timeout=30000)
        page.wait_for_function("!document.querySelector('#books .spinner')", timeout=30000)
        shot(page, "library-sample-loaded", G, "Input: a click on \"Load the sample book\" (Faraday's The Chemical History of a Candle, shipped offline). Output: the book card with its chapter and word counts.", full=True)

        # upload a file: show the input in flight (slowed request), then the result
        held: list = []  # requests held back so the form still shows the input while the shot is taken
        page.route("**/api/books", lambda r: held.append(r) if r.request.method == "POST" else r.continue_())

        def release():
            while not held:
                page.wait_for_timeout(50)
            held.pop().continue_()

        page.wait_for_function("!document.querySelector('#toast.show')", timeout=10000)  # no stale "Sample book loaded"
        page.wait_for_timeout(700)  # and its fade-out has finished
        page.set_input_files("#file", str(WORK / "a-small-book-of-rivers.md"))
        page.wait_for_selector("#msg:has-text('Uploading')")
        shot(page, "library-upload-file", G, "Input: the file a-small-book-of-rivers.md chosen with the file picker. Output: the upload message and progress bar while it is sent; the book is converted in the background.", full=True, wait=0)
        release()
        settled(page, "A Small Book of Rivers")
        shot(page, "library-upload-done", G, "Output of the upload: the markdown file is now a book in the list with its chapters and word count, and the form confirms what was added.", full=True)

        pasted = "# Volcanoes\n\n## How a volcano erupts\n\nA volcano erupts when magma rises through the crust and escapes at the surface as lava, ash and gas. Pressure from dissolved gases drives the eruption.\n\n## Types of volcano\n\nA shield volcano is broad and gently sloping because its lava is runny, while a stratovolcano is steep because its lava is thick and sticky."
        page.fill("#title", "Volcanoes in brief")
        page.fill("#pasted", pasted)
        page.unroute("**/api/books")
        page.click("#addtext")
        settled(page, "Volcanoes in brief")
        page.fill("#title", "Volcanoes in brief")
        page.fill("#pasted", pasted)  # put the input back in the box so the shot shows input and output together
        shot(page, "library-paste-text", G, "Input: lecture notes with two ## headings pasted into the text box with the title \"Volcanoes in brief\". Output: \"Volcanoes in brief\" in the book list with its chapters and words; the form confirms it was added.", full=True)

        page.fill("#url", f"http://127.0.0.1:{web.server_address[1]}/article.html")
        page.fill("#title", "")  # the paste shot put its title back in the box; the article names itself
        page.click("#addurl")
        settled(page, "How deltas form")
        page.fill("#url", f"http://127.0.0.1:{web.server_address[1]}/article.html")
        shot(page, "library-import-url", G, "Input: a web address, here a page served from this machine (the operator switch STUDYLOOP_ALLOW_PRIVATE_URLS=1 is set only for this script; normally private addresses are refused). Output: the article \"How deltas form\" in the book list, its navigation and footer dropped, with the form confirming it was added.", full=True)
        page.set_input_files("#file", str(WORK / "a-tiny-book.pdf"))
        settled(page, "A Tiny Book")
        shot(page, "library-all-books", G, "Output after a markdown file, pasted text, a web page and a PDF were added: five books in the list, each with chapters, words and source type.", full=True)

        # refusal of a wrong file type
        (WORK / "photo.exe").write_bytes(b"MZ")
        page.set_input_files("#file", str(WORK / "photo.exe"))
        page.wait_for_selector("#msg:has-text('Could not add')")
        shot(page, "library-refused", G, "Input: an .exe file chosen by mistake. Output: the browser refuses it at once with a clear message; nothing is uploaded.", full=True)

        # ---------- Home / Try it ----------
        G = "Home and Try it"
        page.goto(BASE + "/#/")
        page.wait_for_selector("#tryout .anim")
        page.wait_for_timeout(1400)
        shot(page, "home", G, "The home page on first visit: the try-it panel has already answered its default question from the sample book, with the timing, above the progress overview.")
        page.fill("#tryq", "What is capillary attraction?")
        page.click("#tryrun")
        page.wait_for_selector("#tryout .verified")
        page.wait_for_timeout(900)
        shot(page, "tryit-english", G, "Input: the English question \"What is capillary attraction?\" typed in the Ask box. Output: the book's own sentences as the answer, with the verified quote, its line and character range, and the time taken.", clip={"x": 0, "y": 0, "width": 1440, "height": 900})
        page.fill("#tryq", "موم بتی کیوں جلتی ہے؟")
        page.click("#tryrun")
        page.wait_for_function("document.querySelector('#tryout .verified') && document.querySelector('#tryout').innerText.includes('Urdu')")
        page.wait_for_timeout(900)
        shot(page, "tryit-urdu", G, "Input: an Urdu question (why does a candle burn?) typed against an English book. Output: what it understood (Urdu), the English search terms it mapped to, and a verified quote.")
        page.click("#try .seg button[data-mode=quiz]")
        page.fill("#tryq", "hydrogen")
        page.click("#tryrun")
        page.wait_for_selector("#tryout .opt, #tryout #tryresp")
        page.wait_for_timeout(900)
        shot(page, "tryit-quiz-me", G, "Input: the Quiz me tab with the topic word \"hydrogen\". Output: a question generated from the book's own sentence, waiting for an answer.")
        tprompt = page.inner_text(".tq-prompt").replace(chr(10), " ")
        t_ans = correct_answer(tprompt, "cloze" if page.query_selector("#tryresp") else ("mcq" if "_____" in tprompt or page.query_selector(".tq-prompt .blank") else "tf"))
        if page.query_selector("#tryresp"):
            page.fill("#tryresp", t_ans)
            page.click("#trycheck")
        else:
            next(o for o in page.query_selector_all("#tryout .opt") if (o.get_attribute("data-o") or "").lower() == t_ans.lower()).click()
        page.wait_for_selector("#tryfb .feedback")
        page.wait_for_timeout(1300)
        shot(page, "tryit-quiz-answered", G, "Input: the correct option clicked. Output: green verdict, the correct answer, the source sentence with its book line, and the knowledge estimate for the topic.")

        # ---------- Course outline ----------
        G = "Course outline"
        page.goto(BASE + "/#/library")
        page.wait_for_selector("#books a:has-text('Chemical History')")
        page.click("#books a:has-text('Chemical History')")
        page.wait_for_selector(".topic-row")
        page.wait_for_timeout(500)
        shot(page, "course-outline", G, "Input: the sample book opened from the Library. Output: its chapters, topics, one-line summaries, key concepts and the export buttons, with per-topic mastery.")
        topic_ids = [int(a.get_attribute("href").split("/")[-1]) for a in page.query_selector_all(".topic-row a.t")]
        book_id = int(page.url.rsplit("/", 1)[-1])

        # ---------- Ask the book ----------
        G = "Ask the book"
        page.goto(f"{BASE}/#/ask/{book_id}")
        page.wait_for_selector("#q")
        for q, name, cap in (
            ("What is capillary attraction?", "ask-english", "Input: \"What is capillary attraction?\". Output: the answer as the book's own sentences, numbered sources, and each quote verified at exact character offsets."),
            ("موم بتی کیوں جلتی ہے؟", "ask-urdu", "Input: an Urdu question about why a candle burns. Output: the language detected, the words mapped to English search terms, and verified quotes from the English book."),
            ("pani kaise banta hai", "ask-roman-urdu", "Input: a Roman Urdu question (how is water made). Output: the question understood as Roman Urdu, the mapped terms, and the passage about water from combustion."),
            ("Who won the 1998 world cup?", "ask-not-in-book", "Input: a question the book cannot answer. Output: \"The book does not say\" with closest topics, rather than an invented answer."),
        ):
            page.fill("#q", q)
            page.click("#go")
            page.wait_for_selector(".answer-box")
            page.wait_for_timeout(500)
            shot(page, name, G, cap, full=True)
        page.fill("#q", "What is hydrogen?")
        page.click("#go")
        page.wait_for_selector(".cite a")
        shot(page, "ask-with-quote", G, "Input: \"What is hydrogen?\". Output: the quote with its chapter, topic, line number and character range, and the \"open in the book\" link that is clicked next.", full=True)
        page.click(".cite a >> nth=0")
        page.wait_for_selector("mark.hl")
        page.wait_for_timeout(1300)
        shot(page, "open-in-book", G, "Input: a click on \"open in the book\". Output: the topic page scrolled to the exact quote, highlighted in the source text.")

        # ---------- Quiz ----------
        G = "Quiz"
        page.goto(f"{BASE}/#/topic/{topic_ids[3]}")
        page.wait_for_selector("#startq")
        page.fill("#newnote", NOTE)
        page.click("#addnote")
        page.wait_for_selector("[data-note]")
        page.wait_for_timeout(500)
        shot(page, "topic-note", G, "Input: a note typed under a topic. Output: the note saved below the reading text, ready to appear in Memory and in the notes export.")
        page.wait_for_function("!document.querySelector('#toast.show')", timeout=10000)  # no stale "Note saved"
        page.click("#startq")
        page.wait_for_selector(".q-prompt")
        page.wait_for_timeout(500)
        shot(page, "quiz-question", G, "Input: Start quiz on the topic. Output: the first generated question, built from a sentence of the topic text.")
        answer_current(page, True)
        shot(page, "quiz-correct", G, "Input: the correct answer given. Output: green feedback, the source sentence with its line, and the topic's updated knowledge estimate.")
        page.click("#next")
        page.wait_for_selector(".q-prompt")
        answer_current(page, False)
        shot(page, "quiz-wrong", G, "Input: a deliberately wrong answer. Output: red feedback showing the right answer, the source sentence it came from, and a lower knowledge estimate.")
        page.click("#next")
        rounds = 0
        while not (page.query_selector("#quizbox h2") and "Done" in page.inner_text("#quizbox h2")) and rounds < 40:
            page.wait_for_selector(".q-prompt, #quizbox h2")
            if page.query_selector(".q-prompt"):
                answer_current(page, rounds % 3 != 2)
                page.click("#next")
                page.wait_for_function("!document.querySelector('#next')")
            rounds += 1
        page.wait_for_selector("#quizbox h2")
        shot(page, "quiz-summary", G, "Output of finishing the round: the summary with the score for this topic and the options to go again or move on.")
        # a couple more topics so Review and mastery have data
        for k, tid in enumerate(topic_ids[4:7]):
            page.goto(f"{BASE}/#/topic/{tid}")
            page.wait_for_selector("#startq")
            page.wait_for_timeout(800)
            page.click("#startq")
            for i in range(30):
                page.wait_for_selector(".q-prompt, #again")
                if not page.query_selector(".q-prompt"):
                    break
                answer_current(page, (i + k) % 3 != 2)
                page.click("#next")
                page.wait_for_function("!document.querySelector('#next')")

        # ---------- Review / mastery ----------
        G = "Review and mastery"
        page.goto(BASE + "/#/review")
        page.wait_for_selector(".sched .li")
        page.wait_for_timeout(500)
        shot(page, "review", G, "Input: the quizzes taken so far. Output: what to review next, in order, with the knowledge level for each, and the spaced-review schedule with the next due dates.")
        page.goto(f"{BASE}/#/book/{book_id}")
        page.wait_for_selector(".topic-row")
        page.wait_for_timeout(1300)
        shot(page, "mastery-outline", G, "Output: mastery per topic after the quizzes: counts of mastered, practised and due topics, and for each practised topic the knowledge percentage and answers right.")
        page.goto(BASE + "/#/")
        page.wait_for_selector(".book-card")
        page.wait_for_selector("#tryout .anim")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, 560)")
        page.wait_for_timeout(500)
        shot(page, "home-progress", G, "Output: the home page progress overview after studying: topics mastered ring, reviews due, streak, accuracy, questions asked and the daily activity chart.")

        # ---------- Memory ----------
        G = "Memory, notes and settings"
        page.goto(BASE + "/#/memory")
        page.wait_for_selector("#msearch")
        page.fill("#mq", "capillary")
        page.click("#msearch")
        page.wait_for_selector("#mres .cite")
        shot(page, "memory-search", G, "Input: \"capillary\" typed in the memory search. Output: the past questions that matched with their score; the same question asked on the home page and on the Ask page is one hit marked with how many times it was asked. The notes and question history are below.", full=True)
        page.fill("#mq", "water")
        page.click("#msearch")
        page.wait_for_function("document.querySelector('#mres .cite') && document.querySelector('#mres').innerText.includes('carbonic')")
        shot(page, "memory-search-notes", G, "Input: \"water\" typed in the memory search. Output: the note written earlier on the topic page is found, along with matching questions.", full=True)
        page.fill("#goal", "25")
        page.click("#save")
        page.wait_for_selector("text=Settings saved")
        page.locator("#goal").scroll_into_view_if_needed()
        shot(page, "settings", G, "Input: the daily goal changed to 25 answers and Save settings pressed. Output: the \"Settings saved\" confirmation; the model panel says no language model is configured and everything still works.")

        # ---------- Exports ----------
        G = "Exports"
        page.goto(f"{BASE}/#/book/{book_id}")
        page.wait_for_selector(".topic-row")
        for path, name, cap in (
            ("notes.md", "export-notes", "Input: the Export my notes button on the book page. Output: the downloaded notes.md, shown as received: a markdown file with the book's topics and the note written above."),
            ("flashcards.csv", "export-anki-csv", "Input: the Flashcards (CSV) button. Output: the downloaded flashcards.csv (front, back, source), ready to import into Anki: a card only for a key concept the book defines or makes the subject of a sentence, so the sample's 33,688 words give CARDS cards."),
        ):
            with page.expect_download() as dl:
                page.click(f"a[href$='{path}']")
            f = dl.value
            tmp = WORK / f"dl-{path}"
            f.save_as(str(tmp))
            text = tmp.read_text(encoding="utf-8-sig")
            cap = cap.replace("CARDS", str(len(text.splitlines()) - 1))
            import html as _h

            sheet = ctx.new_page()
            sheet.set_viewport_size({"width": 1440, "height": 900})
            sheet.set_content(
                "<body style='margin:0;background:#12162b;color:#e8e9f3;font:15px Inter,Segoe UI,sans-serif'>"
                f"<div style='padding:14px 24px;background:#1d2342;border-bottom:1px solid #3a4170'>Clicked <b>{'Export my notes' if path == 'notes.md' else 'Flashcards (CSV)'}</b> &rarr; downloaded <b>{f.suggested_filename}</b> ({len(text):,} characters, first 40 lines)</div>"
                f"<pre style='margin:0;padding:18px 24px;white-space:pre-wrap;font:14px Consolas,monospace;line-height:1.5'>{_h.escape(chr(10).join(text.splitlines()[:40]))}</pre></body>")
            shot(sheet, name, G, cap)
            sheet.close()

        # ---------- About ----------
        G = "About"
        page.goto(BASE + "/#/about")
        page.wait_for_selector(".about")
        page.wait_for_timeout(500)
        shot(page, "about", G, "The About page: what StudyLoop is and does, how to use each input, what it does not do, privacy and the maker.")

        # ---------- light + phone ----------
        G = "Light mode and phone"
        lp = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
        lp.goto(BASE + "/#/")
        lp.wait_for_selector("#tryout .anim")
        lp.wait_for_timeout(1500)
        shot(lp, "home-light", G, "The same home page in light mode (the theme follows the system and has a toggle in the header).")
        ph = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", device_scale_factor=2).new_page()
        ph.goto(BASE + "/#/")
        ph.wait_for_selector("#tryout .anim")
        ph.wait_for_timeout(1500)
        shot(ph, "home-phone", G, "The home page at phone width (390 px): the six navigation links wrap onto their own row under the logo so every page is one tap away, and the try-it panel reflows to one column.", clip={"x": 0, "y": 0, "width": 390, "height": 844})
        ph.goto(BASE + "/#/library")
        ph.wait_for_selector("#books a")
        ph.wait_for_timeout(900)
        shot(ph, "library-phone", G, "The Library at phone width: the nav row, the add-a-book form in one column, and the book list below it.", full=True)
        browser.close()
finally:
    if web:
        web.shutdown()
    server.terminate()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()

lines = ["# Gallery captions", "", "Produced by `scripts/gallery.py` from the real UI (1440x900, dark unless stated).", ""]
last = None
for group, fn, cap in captions:
    if group != last:
        lines += [f"## {group}", ""]
        last = group
    lines += [f"### {fn}", "", f"![{fn}]({fn})", "", cap, ""]
(OUT / "CAPTIONS.md").write_text("\n".join(lines), encoding="utf-8")
print("problems:", problems or "none")
sys.exit(1 if problems else 0)
