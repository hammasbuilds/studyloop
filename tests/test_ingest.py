import pytest
from booktoskill.samplepdf import tiny_book, write_pdf
from conftest import TINY_BOOK

from studyloop import ingest
from studyloop.ingest import IngestError, convert_upload, text_to_markdown, tidy

HTML = """<html><head><title>Rivers explained</title></head><body><nav>Home | About</nav>
<article><h1>Rivers explained</h1>
<p>A river is a natural stream of fresh water that flows toward an ocean, a lake or another river.
Rivers carry sediment from the land and build deltas where they meet the sea, which is why deltas
are fertile.</p>
<h2>Floods</h2><p>A flood happens when a river carries more water than its channel can hold, usually
after heavy rain or when snow melts quickly in the spring. Levees are built beside rivers to hold
the water in.</p></article>
<footer>Copyright</footer></body></html>"""


def test_markdown_upload_keeps_text_and_title():
    c = convert_upload("rivers.md", TINY_BOOK.encode())
    assert c.source_type == "markdown" and c.title == "A Small Book of Rivers"


def test_text_upload_rejoins_wrapped_lines_and_marks_chapters():
    raw = "Chapter 1\n\nA river flows\ndownhill to the sea.\n\nCHAPTER TWO\n\nIt carries silt.\n"
    md = text_to_markdown(raw, "Notes")
    assert "A river flows downhill to the sea." in md
    assert "## Chapter 1" in md and md.startswith("# Notes")


def test_html_upload_extracts_the_article():
    c = convert_upload("page.html", HTML.encode())
    assert c.source_type == "web"
    assert "sediment" in c.markdown and "Copyright" not in c.markdown


def test_pdf_upload_goes_through_book_to_skill(tmp_path):
    path = write_pdf(tmp_path / "t.pdf", tiny_book(), title="A Tiny Book")
    c = convert_upload("t.pdf", path.read_bytes())
    assert c.source_type == "pdf" and c.meta["method"] == "booktoskill"
    assert "Getting Started" in c.markdown and "Next Steps" in c.markdown


def test_bad_inputs_are_rejected():
    for name, data in (("a.pdf", b"%PDF-1.4 not really"), ("a.md", b""), ("a.xyz", b"data")):
        with pytest.raises(IngestError):
            convert_upload(name, data)


def test_tidy_normalises_newlines():
    assert tidy("a\r\n\r\n\r\n\r\nb  \n") == "a\n\nb\n"


def test_add_book_builds_course_and_passages(con, tiny_book):
    n_topics = con.execute("SELECT COUNT(*) FROM topics WHERE book_id=?", (tiny_book,)).fetchone()[0]
    n_pass = con.execute("SELECT COUNT(*) FROM passages WHERE book_id=?", (tiny_book,)).fetchone()[0]
    assert n_topics == 4 and n_pass >= 5
    md = con.execute("SELECT markdown FROM books WHERE id=?", (tiny_book,)).fetchone()[0]
    for r in con.execute('SELECT start, "end" FROM passages'):
        assert md[r[0] : r[1]].strip()


def test_unusable_source_is_an_error(con):
    with pytest.raises(IngestError):
        ingest.add_book(con, ingest.Converted("# Title only\n", "Title only", "markdown", {}))


def test_sample_is_idempotent_and_public_domain(con):
    a = ingest.sample_book(con)
    assert ingest.sample_book(con) == a
    meta = con.execute("SELECT meta FROM books WHERE id=?", (a,)).fetchone()[0]
    assert "public domain" in meta
    assert con.execute("SELECT COUNT(*) FROM topics WHERE book_id=?", (a,)).fetchone()[0] >= 20
