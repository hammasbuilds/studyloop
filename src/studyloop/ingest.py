"""Library: turn a PDF, markdown, text, HTML file or URL into clean markdown, then into a course.

Reuse: PDFs go through ``booktoskill`` (layout repair, chapter detection from font sizes) and web
pages through ``web2md`` (article extraction). Both are path dependencies; neither is modified.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import concepts, db
from .structure import Para, ParsedBook, parse_course, split_long

SAMPLE = Path(__file__).parent / "sample" / "candle.md"
MAX_UPLOAD = 60 * 1024 * 1024


class IngestError(ValueError):
    pass


@dataclass
class Converted:
    markdown: str
    title: str
    source_type: str
    meta: dict


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")


def tidy(md: str) -> str:
    md = md.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


_CHAPTER_LINE = re.compile(
    r"^(?:chapter|lecture|part|unit|lesson|section)\s+(?:[0-9]+|[IVXLC]+|[A-Za-z]+)\b[.:)]?.*$", re.I
)


def text_to_markdown(text: str, title: str) -> str:
    """Plain text -> markdown: hard-wrapped lines are re-joined and "Chapter N" lines get headings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if len(lines) == 1 and len(lines[0]) < 90 and _CHAPTER_LINE.match(lines[0]):
            paras.append("## " + lines[0].rstrip("."))
        elif len(lines) == 1 and len(lines[0]) < 70 and lines[0].isupper() and len(lines[0]) > 3:
            paras.append("## " + lines[0].title())
        elif all(re.match(r"^([-*•]|\d+[.)])\s", ln) for ln in lines):
            paras.append("\n".join(lines))
        else:
            paras.append(" ".join(lines))
    body = "\n\n".join(paras)
    if not re.search(r"^# ", body, re.M):
        body = f"# {title}\n\n{body}"
    return body


def pdf_to_markdown(data: bytes, title: str | None) -> Converted:
    from booktoskill.pipeline import convert, plain_page_texts
    from booktoskill.structure import book_to_markdown

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "book.pdf"
        path.write_bytes(data)
        try:
            conv = convert(path, title=title)
        except Exception as exc:  # pypdf raises many types on damaged files
            raise IngestError(f"could not read the PDF: {exc}") from exc
        chapters = [c for c in conv.book.chapters if c.blocks()]
        meta = {"pages": len(conv.pages), "chapters_detected": len(chapters)}
        if chapters:
            md = book_to_markdown(conv.book)
            meta["method"] = "booktoskill"
        else:
            pages = plain_page_texts(path)
            joined = "\n\n".join(pages)
            if not joined.strip():
                raise IngestError("the PDF has no extractable text (a scan? OCR is not included)")
            md = text_to_markdown(joined, conv.book.title or title or "PDF")
            meta["method"] = "plain-text fallback"
        return Converted(md, conv.book.title or title or "PDF", "pdf", meta)


def html_to_markdown(html: str, url: str | None = None) -> Converted:
    from web2md.convert import convert

    conv = convert(html, url)
    md = conv.markdown.strip()
    if not md:
        raise IngestError("no readable text found on that page")
    title = conv.metadata.title or (url or "Web page")
    if not re.search(r"^# ", md, re.M):
        md = f"# {title}\n\n{md}"
    meta = {"url": url, "tokens_html": conv.tokens_html, "tokens_markdown": conv.tokens_markdown}
    return Converted(md, title, "web", meta)


def convert_upload(filename: str, data: bytes, title: str | None = None) -> Converted:
    if len(data) > MAX_UPLOAD:
        raise IngestError("file is larger than 60 MB")
    if not data:
        raise IngestError("the file is empty")
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip() or "Untitled"
    if ext == ".pdf" or data[:5] == b"%PDF-":
        return pdf_to_markdown(data, title)
    text = _decode(data)
    if ext in (".html", ".htm") or re.match(r"\s*<(!doctype|html)", text[:200], re.I):
        return html_to_markdown(text)
    if ext in (".md", ".markdown"):
        md = text
        source = "markdown"
    elif ext in (".txt", ".text", ""):
        md = text_to_markdown(text, title or stem)
        source = "text"
    else:
        raise IngestError(f"unsupported file type {ext!r}: use PDF, markdown, text or HTML")
    if not md.strip():
        raise IngestError("the file has no text")
    return Converted(md, title or _first_h1(md) or stem, source, {"filename": filename})


def convert_url(url: str) -> Converted:
    from web2md.fetch import FetchError, fetch

    try:
        html, final = fetch(url)
    except FetchError as exc:
        raise IngestError(str(exc)) from exc
    return html_to_markdown(html, final)


def _first_h1(md: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else None


def passage_spans(paras: list[Para]) -> list[tuple[int, int]]:
    """Retrieval units: paragraphs, with the very long ones cut at sentence boundaries."""
    out = []
    for p in split_long([q for q in paras if q.kind in ("text", "list", "quote")], 120, 80):
        if len(p.text.split()) >= 4:
            out.append((p.start, p.end))
    return out


def save_course(con: sqlite3.Connection, book_id: int, parsed: ParsedBook, md: str) -> None:
    topics = [t for c in parsed.chapters for t in c.topics]
    cons, summaries = concepts.extract([md[t.start : t.end] for t in topics])
    i = 0
    for c_ord, ch in enumerate(parsed.chapters):
        cur = con.execute(
            "INSERT INTO chapters(book_id, ord, title) VALUES (?,?,?)", (book_id, c_ord, ch.title)
        )
        chapter_id = cur.lastrowid
        for t in ch.topics:
            cur = con.execute(
                'INSERT INTO topics(book_id, chapter_id, ord, title, start, "end", n_words, summary,'
                " concepts) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    book_id, chapter_id, i, t.title, t.start, t.end, t.n_words, summaries[i],
                    json.dumps([c.as_dict() for c in cons[i]]),
                ),
            )
            topic_id = cur.lastrowid
            for p_ord, (a, b) in enumerate(passage_spans(t.paras)):
                con.execute(
                    'INSERT INTO passages(book_id, topic_id, ord, start, "end") VALUES (?,?,?,?,?)',
                    (book_id, topic_id, p_ord, a, b),
                )
            i += 1


def add_book(
    con: sqlite3.Connection, conv: Converted, source_ref: str = "", book_id: int | None = None
) -> int:
    """Store a converted book and build its course. Returns the book id.

    ``book_id`` fills a placeholder row created earlier (a background import).
    """
    md = tidy(conv.markdown)
    parsed = parse_course(md, conv.title)
    if not parsed.chapters or not any(t.paras for c in parsed.chapters for t in c.topics):
        raise IngestError("could not find any study text in that source")
    title = conv.title or parsed.title
    n_words = len(md.split())
    if book_id is None:
        cur = con.execute(
            "INSERT INTO books(title, source_type, source_ref, status, markdown, n_words, added_at,"
            " meta) VALUES (?,?,?,?,?,?,?,?)",
            (title, conv.source_type, source_ref, "ready", md, n_words, db.now(),
             json.dumps(conv.meta)),
        )
        book_id = cur.lastrowid
    else:
        con.execute(
            "UPDATE books SET title=?, source_type=?, source_ref=?, status='ready', error=NULL,"
            " markdown=?, n_words=?, meta=? WHERE id=?",
            (title, conv.source_type, source_ref, md, n_words, json.dumps(conv.meta), book_id),
        )
    save_course(con, book_id, parsed, md)
    con.commit()
    return book_id


def sample_book(con: sqlite3.Connection) -> int:
    """Load the bundled public-domain sample unless it is already in the library."""
    row = con.execute("SELECT id FROM books WHERE source_type='sample'").fetchone()
    if row:
        return row["id"]
    md = SAMPLE.read_text(encoding="utf-8")
    conv = Converted(
        md, "The Chemical History of a Candle", "sample",
        {"author": "Michael Faraday", "licence": "public domain (Project Gutenberg ebook 14474)"},
    )
    return add_book(con, conv, "bundled sample")
