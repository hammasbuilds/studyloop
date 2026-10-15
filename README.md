# StudyLoop

Turn any textbook, lecture notes or web article into a personal tutor that runs on your own computer, with no GPU, no account and no model required. It is for students and self-learners who want to study a text actively and get answers they can check against the source.

Add a PDF, a markdown or text file, pasted notes or a web address. StudyLoop turns it into a navigable course (chapters, topics, key concepts), answers questions using only the book and shows exactly where every quote sits, quizzes you topic by topic, tracks what you know, tells you what to review next, and remembers your progress, notes and questions between sessions. Questions can be asked in English, Urdu or Roman Urdu.

**See it:** [showcase page with every screen](https://studyloop-iota.vercel.app) · [Kaggle notebook running the engine](https://www.kaggle.com/code/muhammadhammas13/studyloop-demo)

## What it does

- **Library**: add a PDF, markdown, text or HTML file (file picker or drag and drop), paste text, or import a web address.
- **Course outline**: chapters, topics and key concepts; the source's headings are used when it has them, otherwise chapters are split into topics automatically.
- **Ask the book**: questions in English, Urdu or Roman Urdu answered with the book's own sentences, every quote located by line and character, "open in the book" highlighting, and a clear "the book does not say" when it does not.
- **Quizzes**: fill-in-the-blank, multiple choice and true/false per topic, built from the book's sentences, with the source sentence shown after every answer.
- **Review and mastery**: a per-topic knowledge estimate (Bayesian Knowledge Tracing), what to review next and a spaced-review schedule.
- **Memory**: notes, question history, sessions and settings, all searchable.
- **Exports**: notes as markdown, flashcards as CSV for Anki.
- **Dashboard**: progress, streak, accuracy and a live Try-it panel.

## Gallery

Every picture is a real screenshot of the running app, taken by [scripts/gallery.py](scripts/gallery.py) (headless Edge, 1440x900, dark mode unless stated) from the input described in its caption. They follow the order a new user would take. Captions are also in [docs/gallery/CAPTIONS.md](docs/gallery/CAPTIONS.md).

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

Output of the upload: the markdown file is now a book in the list with its chapters and word count, and the form confirms what was added.

![library paste text](docs/gallery/05-library-paste-text.png)

Input: lecture notes with two ## headings pasted into the text box with the title "Volcanoes in brief". Output: "Volcanoes in brief" in the book list with its chapters and words; the form confirms it was added.

![library import url](docs/gallery/06-library-import-url.png)

Input: a web address, here a page served from this machine (the operator switch STUDYLOOP_ALLOW_PRIVATE_URLS=1 is set only for this script; normally private addresses are refused). Output: the article "How deltas form" in the book list, its navigation and footer dropped, with the form confirming it was added.

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

Input: "capillary" typed in the memory search. Output: the past questions that matched with their score; the same question asked on the home page and on the Ask page is one hit marked with how many times it was asked. The notes and question history are below.

![memory search notes](docs/gallery/30-memory-search-notes.png)

Input: "water" typed in the memory search. Output: the note written earlier on the topic page is found, along with matching questions.

![settings](docs/gallery/31-settings.png)

Input: the daily goal changed to 25 answers and Save settings pressed. Output: the "Settings saved" confirmation; the model panel says no language model is configured and everything still works.

### Exports

![export notes](docs/gallery/32-export-notes.png)

Input: the Export my notes button on the book page. Output: the downloaded notes.md, shown as received: a markdown file with the book's topics and the note written above.

![export anki csv](docs/gallery/33-export-anki-csv.png)

Input: the Flashcards (CSV) button. Output: the downloaded flashcards.csv (front, back, source), ready to import into Anki: a card only for a key concept the book defines or makes the subject of a sentence, so the sample's 33,688 words give 10 cards.

### About

![about](docs/gallery/34-about.png)

The About page: what StudyLoop is and does, how to use each input, what it does not do, privacy and the maker.

### Light mode and phone

![home light](docs/gallery/35-home-light.png)

The same home page in light mode (the theme follows the system and has a toggle in the header).

![home phone](docs/gallery/36-home-phone.png)

The home page at phone width (390 px): the six navigation links wrap onto their own row under the logo so every page is one tap away, and the try-it panel reflows to one column.

![library phone](docs/gallery/37-library-phone.png)

The Library at phone width: the nav row, the add-a-book form in one column, and the book list below it.

## Inputs

| Feature | File upload | Drag and drop | Paste | Hint and example |
|---|---|---|---|---|
| Library (add a book) | file picker: PDF, .md, .txt, .html, up to 60 MB, with a progress bar | onto the drop box (one file; a dragged link or text is also taken) | web address, or text (markdown headings kept) | each input shows what it expects and has "Load example"; wrong type, size or empty file is refused in the browser with a clear message |
| Ask the book | not applicable | not applicable | one question, up to 1,000 characters | example chips; to ask about your own passage, paste it as text in the Library, where it becomes a book |
| Notes | not applicable | not applicable | typed or pasted on a topic page | none |

The app also has an **About** page (nav entry and "?" in the header): what it is, how to use each input, limits, privacy, roadmap, the maker.

## Tech stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn, SQLite
- **Ingestion**: pypdf, [book-to-skill](https://github.com/hammasbuilds/book-to-skill) (PDF/markdown to chapters), [web-to-markdown](https://github.com/hammasbuilds/web-to-markdown) (web page to clean markdown)
- **Retrieval and learning**: BM25 passage retrieval with phrase checks, Bayesian Knowledge Tracing, spaced review
- **Urdu and Roman Urdu**: [urdunlp](https://github.com/hammasbuilds/urdu-nlp-toolkit) for script detection, transliteration and question mapping
- **Frontend**: vanilla JavaScript, HTML and CSS, no build step; light and dark themes; strict Content-Security-Policy
- **Optional LLM**: Ollama, Anthropic or any OpenAI-compatible API, with every quote verified against the book
- **Tooling**: uv, pytest, ruff, Playwright for the UI audit and gallery

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

## Licence

MIT. The sample book is Michael Faraday's *The Chemical History of a Candle* (public domain, Project Gutenberg).

Built by Muhammad Hammas · [github.com/hammasbuilds](https://github.com/hammasbuilds)
