# Review notes, 2026-10-07

Hostile pass over StudyLoop. Severity: H high, M medium, L low.

## Found and fixed
| Sev | Area | Finding | Fix / test |
|---|---|---|---|
| H | SSRF | URL import used web2md's `urlopen`: `http://127.0.0.1:<port>/`, `169.254.169.254`, redirects to them, DNS names resolving to private IPs all fetched | `net.py` (resolve, check every address, connect to checked IP, re-check redirects, caps); 22 parametrised URL tests plus a real loopback server never contacted |
| H | CSRF / rebinding | No Host or Origin check: any website could POST `url=` or `file` to localhost, and a rebinding page could read all data | Host allow-list + Origin / Sec-Fetch-Site check on writes (403) |
| M | DoS | `await file.read()` loaded any upload into memory before the size check | chunked read, 413 over 60 MB |
| M | DoS | PDF page count, text size unbounded; encrypted PDFs | caps (3000 pages, 8M chars), encrypted refused; flate-bomb memory test |
| L | Path | filename stored raw as `source_ref` (not used as a path, but shown in UI) | `clean_filename` |
| M | XSS | No CSP; inline script in index.html | CSP + nosniff; script moved to theme.js. Renderer was already escaping: verified in a browser with payloads in titles, headings, links, tables, code, questions |
| M | Honesty/answers | "boiling point of mercury" answered from a sentence about boiling mercury | phrase-adjacency check on questions of 3+ words (`ask._phrase_supported`); 8 on-book paraphrases pinned as still answering |
| M | UX | restart during import left books "processing" forever | marked failed at startup |
| L | UX | "Notes as markdown" button exported the book text | renamed "Book text"; real notes export added |

## Checked, no issue
SQL (all parameterised); note/answer text escaped in every template; links limited to http(s); DELETE/PUT need a CORS preflight and are blocked cross-origin; no secrets in logs; LLM keys come from env only.

## Open
- No login: anyone able to reach the port with `--host 0.0.0.0` has full access.
- A DNS name that resolves differently for the checker and the connection is covered (we connect to the checked IP), but an HTTP proxy configured system-wide is bypassed by design.
- Concurrent imports are limited to two at a time but there is no per-import timeout for PDF conversion itself.
- Scanned PDFs (OCR), Urdu-language books, spaced-repetition export of quiz questions.
- Next valuable features: OCR, per-topic flashcard review inside the app, EPUB import, shareable course export, backup/restore.
