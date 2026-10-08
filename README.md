# StudyLoop

Turn any textbook or web page into a personal tutor that runs on your own computer, with no GPU, no account and no model required. It is for students and self-learners who have a textbook, lecture notes or an article and want to study it actively, and for anyone who needs answers they can check against the source.

You add a PDF, a markdown or text file, or a web address. StudyLoop converts it to clean notes, builds a navigable course (chapters, topics, key concepts), answers questions using only the book and shows exactly where every quote sits in the source, quizzes you topic by topic, tracks what you know with Bayesian Knowledge Tracing, tells you what to review next, and remembers your progress, notes and questions between sessions. Questions can be asked in English, Urdu or Roman Urdu.

**Showcase page:** [studyloop-iota.vercel.app](https://studyloop-iota.vercel.app) shows every feature as captioned screenshots. The app itself runs on your own computer (see Run it).

## What it does

- **Library**: add a PDF, markdown, text or HTML file, paste text, or import a web address (from [book-to-skill](../book-to-skill) and [web-to-markdown](../web-to-markdown)).
- **Course outline**: chapters, topics and key concepts as a navigable outline; headings are used when the source has them, otherwise a chapter is cut into topics by lexical cohesion.
- **Ask the book**: English, Urdu or Roman Urdu questions answered with the book's own sentences, every quote located in the source (line and character offsets), "open in the book" highlighting, and an honest "the book does not say".
- **Quizzes**: cloze, multiple choice and true/false per topic, generated from the book's own sentences, deterministic without a model, with the source sentence shown after every answer.
- **Review and mastery**: per-topic Bayesian Knowledge Tracing, what to review next and a spaced-review schedule.
- **Memory**: notes, question history, sessions and versioned settings in SQLite, searchable.
- **Exports**: notes as markdown, flashcards as CSV for Anki.
- **Try it**: the home page runs the real app live (ask or quiz me) on the shipped sample book.

## Gallery

Every picture is a real screenshot of the running app, taken by [scripts/gallery.py](scripts/gallery.py) (headless Chromium, 1440x900, dark mode unless stated) from the input described in its caption. They follow the order a new user would take. Captions are also in [docs/gallery/CAPTIONS.md](docs/gallery/CAPTIONS.md).

### Home and Try it

![home](docs/gallery/09-home.png)

The home page on first visit: the try-it panel has already answered its default question from the sample book, with the timing, above the progress overview.

![tryit english](docs/gallery/10-tryit-english.png)

Input: the English question "What is capillary attraction?" typed in the Ask box. Output: the book's own sentences as the answer, with the verified quote, its line and character range, and the time taken.

![tryit urdu](docs/gallery/11-tryit-urdu.png)

Input: an Urdu question (why does a candle burn?) typed against an English book. Output: what it understood (Urdu), the English search terms it mapped to, and a verified quote.

![tryit quiz me](docs/gallery/12-tryit-quiz-me.png)

Input: the Quiz me tab with the topic word "hydrogen". Output: a question generated from the book's own sentence, waiting for an answer.

![tryit quiz answered](docs/gallery/13-tryit-quiz-answered.png)

Input: the correct option clicked. Output: green verdict, the correct answer, the source sentence with its book line, and the knowledge estimate for the topic.

### Library

![library empty](docs/gallery/01-library-empty.png)

The Library on a fresh install: the drop box, a web address field, a paste box and a book list that says there are no books yet.

![library sample loaded](docs/gallery/02-library-sample-loaded.png)

Input: a click on "Load the sample book" (Faraday's The Chemical History of a Candle, shipped offline). Output: the book card with its chapter and word counts.

![library upload file](docs/gallery/03-library-upload-file.png)

Input: the file a-small-book-of-rivers.md chosen with the file picker. Output: the upload message and progress bar while it is sent; the book is converted in the background.

![library upload done](docs/gallery/04-library-upload-done.png)

Output of the upload: the markdown file is now a book in the list with its chapters and word count.

![library paste text](docs/gallery/05-library-paste-text.png)

Input: lecture notes pasted into the text box with the title "Volcanoes in brief". Output: the form reports that the text is being sent and converted.

![library import url](docs/gallery/06-library-import-url.png)

Input: a web address, here a page served from this machine (the operator switch STUDYLOOP_ALLOW_PRIVATE_URLS=1 is set only for this script; normally private addresses are refused). Output: the import is accepted and converted.

![library all books](docs/gallery/07-library-all-books.png)

Output after a markdown file, pasted text, a web page and a PDF were added: five books in the list, each with chapters, words and source type.

![library refused](docs/gallery/08-library-refused.png)

Input: an .exe file chosen by mistake. Output: the browser refuses it at once with a clear message; nothing is uploaded.

### Course outline

![course outline](docs/gallery/14-course-outline.png)

Input: the sample book opened from the Library. Output: its chapters, topics, one-line summaries, key concepts and the export buttons, with per-topic mastery.

### Ask the book

![ask english](docs/gallery/15-ask-english.png)

Input: "What is capillary attraction?". Output: the answer as the book's own sentences, numbered sources, and each quote verified at exact character offsets.

![ask urdu](docs/gallery/16-ask-urdu.png)

Input: an Urdu question about why a candle burns. Output: the language detected, the words mapped to English search terms, and verified quotes from the English book.

![ask roman urdu](docs/gallery/17-ask-roman-urdu.png)

Input: a Roman Urdu question (how is water made). Output: the question understood as Roman Urdu, the mapped terms, and the passage about water from combustion.

![ask not in book](docs/gallery/18-ask-not-in-book.png)

Input: a question the book cannot answer. Output: "The book does not say" with closest topics, rather than an invented answer.

![ask with quote](docs/gallery/19-ask-with-quote.png)

Input: "What is hydrogen?". Output: the quote with its chapter, topic, line number and character range, and the "open in the book" link that is clicked next.

![open in book](docs/gallery/20-open-in-book.png)

Input: a click on "open in the book". Output: the topic page scrolled to the exact quote, highlighted in the source text.

### Quiz

![topic note](docs/gallery/21-topic-note.png)

Input: a note typed under a topic. Output: the note saved below the reading text, ready to appear in Memory and in the notes export.

![quiz question](docs/gallery/22-quiz-question.png)

Input: Start quiz on the topic. Output: the first generated question, built from a sentence of the topic text.

![quiz correct](docs/gallery/23-quiz-correct.png)

Input: the correct answer given. Output: green feedback, the source sentence with its line, and the topic's updated knowledge estimate.

![quiz wrong](docs/gallery/24-quiz-wrong.png)

Input: a deliberately wrong answer. Output: red feedback showing the right answer, the source sentence it came from, and a lower knowledge estimate.

![quiz summary](docs/gallery/25-quiz-summary.png)

Output of finishing the round: the summary with the score for this topic and the options to go again or move on.

### Review and mastery

![review](docs/gallery/26-review.png)

Input: the quizzes taken so far. Output: what to review next, in order, with the knowledge level for each, and the spaced-review schedule with the next due dates.

![mastery outline](docs/gallery/27-mastery-outline.png)

Output: mastery per topic after the quizzes: counts of mastered, practised and due topics, and for each practised topic the knowledge percentage and answers right.

![home progress](docs/gallery/28-home-progress.png)

Output: the home page progress overview after studying: topics mastered ring, reviews due, streak, accuracy, questions asked and the daily activity chart.

### Memory, notes and settings

![memory search](docs/gallery/29-memory-search.png)

Input: "capillary" typed in the memory search. Output: the past questions that matched, with their score, plus the notes and question history below.

![memory search notes](docs/gallery/30-memory-search-notes.png)

Input: "water" typed in the memory search. Output: the note written earlier on the topic page is found, along with matching questions.

![settings](docs/gallery/31-settings.png)

Input: the daily goal changed to 25 answers and Save settings pressed. Output: the "Settings saved" confirmation; the model panel says no language model is configured and everything still works.

### Exports

![export notes](docs/gallery/32-export-notes.png)

Input: the Export my notes button on the book page. Output: the downloaded notes.md, shown as received: a markdown file with the book's topics and the note written above.

![export anki csv](docs/gallery/33-export-anki-csv.png)

Input: the Flashcards (CSV) button. Output: the downloaded flashcards.csv, one card per concept the book defines (front, back, source), ready to import into Anki.

### About

![about](docs/gallery/34-about.png)

The About page: what StudyLoop is and does, how to use each input, what it does not do, privacy and the maker.

### Light mode and phone

![home light](docs/gallery/35-home-light.png)

The same home page in light mode (the theme follows the system and has a toggle in the header).

![home phone](docs/gallery/36-home-phone.png)

The home page at phone width (390 px): the navigation and the try-it panel reflow to one column.

## Inputs

| Feature | File upload | Drag and drop | Paste | Hint and example |
|---|---|---|---|---|
| Library (add a book) | file picker: PDF, .md, .txt, .html, up to 60 MB, with a progress bar | onto the drop box (one file; a dragged link or text is also taken) | web address, or text (markdown headings kept) | each input shows what it expects and has "Load example"; wrong type, size or empty file is refused in the browser with a clear message |
| Ask the book | not applicable | not applicable | one question, up to 1,000 characters | example chips; to ask about your own passage, paste it as text in the Library, where it becomes a book |
| Notes | not applicable | not applicable | typed or pasted on a topic page | none |

The app also has an **About** page (nav entry and "?" in the header): what it is, how to use each input, limits, privacy, roadmap, the maker.

## Run it

```
uv run studyloop            # starts the server, opens http://127.0.0.1:8765, loads the sample book on first run
```

or double-click `run.bat`. Options: `--port`, `--no-browser`, `--no-sample`, `--db FILE`. Data lives in `~/.studyloop/studyloop.sqlite3` (set `STUDYLOOP_HOME` to move it). Python 3.11+ and [uv](https://docs.astral.sh/uv/); everything runs on the CPU and works offline.

Optional language model (never required): set before launching

```
STUDYLOOP_LLM=ollama      STUDYLOOP_LLM_MODEL=qwen2.5:3b          # CPU Ollama on localhost:11434
STUDYLOOP_LLM=anthropic   ANTHROPIC_API_KEY=...                   # STUDYLOOP_LLM_MODEL defaults to claude-haiku-4-5
STUDYLOOP_LLM=openai      OPENAI_API_KEY=...  STUDYLOOP_OPENAI_BASE_URL=...
```

With a model, answers are written in prose and quizzes can add model-written questions. Neither is trusted: a quote that is not found in the book is dropped, and a model question is kept only when its supporting quote is found in the topic. If the model is down, the extractive answer is shown instead.

Tests and checks:

```
uv run pytest -q            # 153 tests
uv run ruff check .
uv run python demo.py       # offline end-to-end demo (output below)
uv run python scripts/ask_check.py
uv run --with playwright python scripts/xss_check.py http://127.0.0.1:8799   # hostile book text in a real browser
uv run --with playwright python scripts/gallery.py   # recreates every shot in docs/gallery/ (own server on a free port 8800-8899, temp data dir)
uv run --with playwright python scripts/ui_tour.py http://127.0.0.1:8799 <db> docs/screenshots   # drives the real UI, regenerates the screenshots
```

## Input / Output

`uv run python demo.py`, no server and no model (full text in [docs/demo-output.txt](docs/demo-output.txt)):

```
Input : The Chemical History of a Candle (33,688 words, markdown)
Output: 6 chapters, 26 topics, 364 retrieval passages

Ask the book
  en       What is capillary attraction?
           -> line 29, chars 15635-15874, Mobility: "There is a beautiful point about that—capillary attraction[4]. “Capillary attraction!” you..."
  ur       موم بتی کیوں جلتی ہے؟
           -> line 63, chars 38175-38484, Brightness of the Flame: "We have the case of the combustion of a candle; we have the case of a candle being put out..."
  roman-ur pani kaise banta hai
           -> line 95, chars 59761-59855, Products: Water from the Combustion: "Here, again [holding another bottle], is some water produced by the combustion of an oil-l..."
  en       Who won the 1998 world cup?
           -> not in the book
  6 of 9 answered, every quote verified against the markdown
```

The sample is Michael Faraday's *The Chemical History of a Candle* (six lectures, 1848), public domain, from Project Gutenberg ebook 14474 and shipped in the package so the demo works offline. `scripts/prepare_sample.py` shows how the markdown was made from the Gutenberg text.

## How it works

```mermaid
flowchart LR
    A["PDF / md / txt / HTML / URL"] --> B["clean markdown<br/>(book-to-skill, web-to-markdown)"]
    B --> C["course: chapters, topics<br/>headings or cohesion tiling"]
    C --> D["key concepts<br/>tf-idf, emphasis, definitions"]
    C --> E["passages with<br/>character offsets"]
    E --> F["BM25 (agent-memory)"]
    Q["question: en / ur / roman-ur"] --> U["urdunlp normalise<br/>glossary, sound match"] --> F
    F --> G["extractive answer<br/>or LLM answer"] --> V["every quote located<br/>in the source (rag-forge rule)"]
    D --> Z["cloze / choice / true-false"] --> K["BKT per topic<br/>(knowledge-tracing)"] --> R["review next, schedule"]
    K --> M[("SQLite memory<br/>(agent-memory ideas)")]
```

### What is reused from the other repos

| Repo | How | What for |
|---|---|---|
| `book-to-skill` | path dependency, unmodified | PDF text, layout repair, chapter and section detection |
| `web-to-markdown` (`web2md`) | path dependency, unmodified | fetch and article extraction |
| `urdu-nlp-toolkit` (`urdunlp`) | vendored read-only copy in `src/studyloop/_vendor/urdunlp` | normalisation, `roman_key`, stemming, stopwords, transliteration. One local patch: its data files are looked up with `resources.files(__package__)` so they resolve inside this package (noted in `_vendor/NOTICE`). |
| `agent-memory` | vendored `bm25.py`, ideas for the store | retrieval; sessions, event log, versioned facts ("a newer value supersedes the old one") |
| `rag-forge` | re-implemented (its code needs Postgres and torch) | quote location: a quote is accepted only when found in the source, tolerant of whitespace and case only |
| `knowledge-tracing` | re-implemented (the BKT forward filter) | per-topic P(known); mastery judged on P(known), threshold 0.95, never on P(correct) |

The sibling repos belong to other sessions and were only read. Source commits are listed in `src/studyloop/_vendor/NOTICE`.

### Mastery and review

P(known) starts at 0.30 and is updated after every answer with the BKT filter (learn 0.10, slip 0.20; guess 0.15 for a typed blank, 0.30 for four options, 0.55 for true/false). A question you have already seen counts less (guess 0.60), because a remembered answer is weak evidence. A topic is **mastered** only when P(known) is at least 0.95, you have given at least 8 answers and at least 6 of the last 8 were right. Review dates come from P(known): ten minutes when below 0.5 or after a miss, one day below 0.8, two days below 0.95, then 4 days growing by 2.2 times per successful review up to 90. "What you are expected to remember today" is P(known) times a forgetting curve whose stability puts recall at 0.9 on the due date.

## What the checks show

Every number below is printed by the code in this repository.

| Check | Result |
|---|---|
| Sample book import (markdown to course, concepts, passages) | 6 chapters, 26 topics, 364 passages in about 0.3 s |
| Quiz pool for the sample (rule-based, all 26 topics) | 381 questions: 125 cloze, 125 multiple choice, 131 true/false; 3 to 21 per topic, none without |
| Ask, on-book (26 questions, "What does the book say about X?", X = each topic's top concept) | 26 answered, 26 with a cited quote containing the concept's words. This is easy by construction: the question is built from the text. |
| Ask, off-book (24 questions the book cannot answer, `scripts/ask_check.py`) | 24 abstained. Before the phrase check one of the first 20 was answered ("What is the boiling point of mercury?"); the other 4 were added after the fix, so 24/24 is partly tuned and partly unseen. |
| Tests | 153 passing, ruff clean |
| UI tour in a real browser | uploads a markdown file, a PDF and a web page; plays quizzes; asks in three languages; opens a quote; changes settings; deletes a book. No console error or failed request. |

## Security (2026-10 review, details in [docs/REVIEW.md](docs/REVIEW.md))

- **URL import cannot reach your machine or network.** Only http(s); no `user:pass@`; `localhost`, `.local`, private, loopback, link-local (cloud metadata), CGNAT and IPv4-mapped IPv6 addresses are refused; every address a name resolves to is checked, the socket is opened to the checked address (no second lookup), each redirect is re-checked, and size (20 MB), time (30 s) and redirects (5) are capped. `STUDYLOOP_ALLOW_PRIVATE_URLS=1` is an operator-only switch for a local test server.
- **Uploads** are read in pieces and refused past 60 MB; the file name is reduced to a label and never used as a path; PDFs over 3,000 pages or password-protected are refused; extracted text over 8 million characters is refused; a 600 MB flate bomb in a 600 KB PDF fails cleanly (test).
- **Book text is escaped** before the UI builds HTML, links only allow http(s), and a Content-Security-Policy forbids inline script. `scripts/xss_check.py` imports a book of payloads and visits every page in a real browser.
- **Other websites cannot drive the local server**: requests whose Host is not localhost (DNS rebinding) and cross-site writes (Origin / Sec-Fetch-Site) get 403. Started with `--host 0.0.0.0` this guard is off, and there is still no login.

## What it does NOT do

- **No OCR.** A scanned PDF with no text layer is rejected with a message; so are other binary formats.
- **PDF structure is only as good as the PDF.** book-to-skill finds chapters from font sizes; a PDF with unusual fonts may come out as one flat chapter, which StudyLoop then cuts by cohesion.
- **Urdu support is for questions, not for books.** The book is read in English (or any language the retrieval tokeniser handles as Latin text); an Urdu book is not indexed properly. The question mapping is a glossary of 70 study words plus sound matching against the book's vocabulary, not a translator: a word it cannot resolve is shown as "not understood" rather than guessed.
- **The extractive answer is not a summary.** It returns the best-matching sentences verbatim, so a "why" question gets the passages that talk about the subject, not a reasoned explanation. A model can write one, with verified quotes.
- **Concepts and quiz sentences are heuristics.** Some key concepts are odd (a noun phrase picked by frequency), and some cloze blanks are answerable from context. Questions test recognition of the text you just read, not transfer.
- **BKT parameters are fixed priors, not fitted.** One learner and a few answers per topic leave nothing to fit, so the knowledge estimate is a sensible default rather than a calibrated probability.
- **Phrase check is a heuristic.** Questions of three or more content words must have two neighbouring question words close together in one passage. It stops "boiling point of mercury" matching a book that only boils mercury; a legitimate question phrased with the words far apart can now abstain.
- **One user, one machine.** No accounts, no sync, no multi-user locking beyond SQLite's.
- **No model is bundled** and the optional LLM path was tested against fakes and failure cases, not against a live model in this build.

## Problems hit while building this

- **Gallery pass 2026-10-08.** Driving every section found two things: pressing Start quiz and leaving the topic before the questions arrived raised a script error (the quiz box was gone); and the Memory page squeezed the question history into a narrow third column at desktop width. Both fixed.
- **Review pass 2026-10-07.** The off-book answer above, a URL importer that fetched `http://127.0.0.1:8765/api/...` for anyone who could submit a form, an unbounded upload read, and an "Export notes" button that exported the whole book. All fixed with tests; new: notes export (markdown), flashcards (CSV for Anki, formula-safe), paste-text import, and imports interrupted by a restart now show as failed instead of "processing" forever.

- **A lecture has no headings.** The sample's chapters are single speeches with a title such as "The Flame - Its Sources - Structure - Mobility - Brightness". Splitting on paragraphs gave topics of 2,500 words next to topics of 100 because the paragraphs are enormous. Fix: long paragraphs are cut at sentence boundaries into units of about 90 words before tiling, cuts need a minimum size relative to the chapter, and the title's own list names the topics.
- **BKT said "mastered" after six answers.** With a guess rate of 0.05 for a typed blank, one correct blank and one correct choice took P(known) to 0.97, and with slip 0.10 a wrong answer barely moved it. Fixed in three steps: higher guess rates (a blank can be filled from the sentence around it), slip 0.20, and a mastery rule that also needs 8 answers and 6 of the last 8 right. Repeating a question you have already answered now counts as weak evidence.
- **Every abstention test passed except the ones that mattered.** The first version computed "support" as the share of question terms found in the chosen sentences, and treated words absent from the book as weightless, so "Who won the 1998 world cup?" scored 1.0 on the single word "cup". Absent words now count as the rarest possible terms, and support is judged on a single passage, not the union of sentences.
- **Roman Urdu is noisy to detect.** urdunlp's token tagger calls "candle" Urdu, and its `roman_key` maps `jalna` to a different word from `jalti`. Detection is now by function words, and glossary matching uses the key and the stem together.
- **A vendored package that finds its data by name.** urdunlp loads its tables with `resources.files("urdunlp")`, which fails once the package is nested under another name; one line changed in each of two files.
- **Cloze and multiple choice share a sentence.** The UI tour could not tell which stored question it was looking at from the prompt alone; it now reads the kind from the page.
- **Ten minutes is not "due".** After a failed quiz the topic was scheduled in ten minutes, so "what to review next" skipped it. A practised topic below 0.6 is now offered immediately.
- **Smooth scrolling was cancelled by the router.** "Open in the book" scrolled, then the page's own scroll reset undid it; the reset is skipped when a highlight is requested.

## Layout

```
src/studyloop/
  net.py         safe URL fetch (no private addresses, bounded)
  exports.py     notes as markdown, flashcards as CSV
  ingest.py      PDF / md / text / HTML / URL -> markdown -> course
  structure.py   headings or cohesion tiling -> chapters, topics, paragraphs with offsets
  concepts.py    key concepts, definitions, one-line summaries
  ask.py         retrieval, extractive and LLM answers, quote verification
  urdu.py        question normalisation, glossary, sound matching
  quiz.py        cloze / choice / true-false generation, grading, optional model questions
  mastery.py     BKT, forgetting curve, review order, schedule, activity
  memory.py      sessions, event log, notes, versioned facts, recall
  llm.py         optional Ollama / Anthropic / OpenAI-compatible client (stdlib only)
  app.py         FastAPI endpoints, background import
  static/        the single-page app (HTML, CSS, JS; no build step)
  sample/        Faraday, The Chemical History of a Candle (public domain)
  _vendor/       read-only copies, see NOTICE
tests/           153 tests: units for every module, API tests for every endpoint
scripts/         gallery.py, ui_tour.py, xss_check.py, ask_check.py, make_icon.py, prepare_sample.py
```

Licence: MIT for the code. The sample text is in the public domain; the vendored urdunlp keeps its own MIT licence and CC BY-SA data licence in `src/studyloop/_vendor/urdunlp/`.

## Interaction

Every control gives feedback: buttons lift, press down with a spring and ripple from the pointer, and show a spinner
while a request runs; cards lift with a pointer spotlight (stat and book cards also tilt a few degrees); inputs get an
animated focus ring and a green edge once filled; lists enter with a staggered rise; KPI numbers count up and bars
grow from zero; toasts slide in. Two delight moments: a confetti burst on a correct answer (bigger at mastery or a
perfect round) and a gentle shake on a wrong one. Everything honours `prefers-reduced-motion`. Research and the numbers
used are in [docs/MOTION.md](docs/MOTION.md).

![Answer feedback](docs/screenshots/19-motion-answer-feedback.png)
![Button loading](docs/screenshots/20-motion-button-loading.png)
