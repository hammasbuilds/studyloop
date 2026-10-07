"""Hostile inputs: SSRF through URL import, upload limits, cross-site writes, hostile book text."""

from __future__ import annotations

import http.server
import threading
import zlib

import pytest
from conftest import TINY_BOOK
from fastapi.testclient import TestClient

from studyloop import ask, ingest, net
from studyloop.app import create_app

BAD_URLS = [
    "file:///etc/passwd", "file:///C:/Windows/win.ini", "ftp://example.org/x", "gopher://x/",
    "javascript:alert(1)", "http://127.0.0.1/", "http://127.0.0.1:8765/api/dashboard",
    "http://localhost/", "http://LOCALHOST./", "http://foo.localhost/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/", "http://100.64.0.1/",
    "http://user:pw@example.org/", "http://printer.local/", "http:///nohost",
    "http://example.org/\r\nX: y",
]


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("url", BAD_URLS)
def test_url_import_refuses_internal_and_non_http_urls(client, url):
    r = client.post("/api/books", data={"url": url})
    assert r.status_code == 400, url
    assert client.get("/api/books").json() == []  # nothing was queued


def test_odd_ip_spellings_are_refused_after_resolution(monkeypatch):
    # "2130706433" and "0x7f.1" are spellings of 127.0.0.1 that only the resolver reveals
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))])
    for host in ("2130706433", "0x7f.1", "evil.example"):
        with pytest.raises(net.UnsafeURL):
            net.resolve_public(host, 80)


def test_one_private_answer_among_public_ones_refuses(monkeypatch):
    infos = [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.0.0.1", 80))]
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: infos)
    with pytest.raises(net.UnsafeURL):
        net.resolve_public("rebind.example", 80)


def test_redirect_to_internal_address_is_refused():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = _serve(H)
    try:
        # the first hop may reach the test server; the redirect target is vetted all the same
        def resolver(host, port):
            return net.resolve_public(host, port) if host == "169.254.169.254" else ["127.0.0.1"]

        with pytest.raises(net.UnsafeURL):
            net.fetch_page(f"http://public.example:{srv.server_port}/", resolver=resolver)
    finally:
        srv.shutdown()


def test_response_size_is_capped(monkeypatch):
    monkeypatch.setattr(net, "MAX_BYTES", 10_000)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b"x" * 1000)
            except OSError:
                pass

        def log_message(self, *a):
            pass

    srv = _serve(H)
    try:
        with pytest.raises(net.FetchFailed, match="larger"):
            net.fetch_page(f"http://public.example:{srv.server_port}/",
                           resolver=lambda h, p: ["127.0.0.1"])
    finally:
        srv.shutdown()


def test_public_page_is_fetched_when_the_address_is_allowed():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>hello</body></html>")

        def log_message(self, *a):
            pass

    srv = _serve(H)
    try:
        body, final, ctype = net.fetch_page(
            f"http://public.example:{srv.server_port}/a?b=1", resolver=lambda h, p: ["127.0.0.1"])
        assert b"hello" in body and final.endswith("/a?b=1") and "html" in ctype
    finally:
        srv.shutdown()


def test_real_loopback_server_is_never_contacted(client):
    hit = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hit.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><p>secret internal page</p></body></html>")

        def log_message(self, *a):
            pass

    srv = _serve(H)
    try:
        r = client.post("/api/books", data={"url": f"http://127.0.0.1:{srv.server_port}/"})
        assert r.status_code == 400 and not hit
        r = client.post("/api/books", data={"url": f"http://localtest.me:{srv.server_port}/x"})
        if r.status_code == 202:  # the host name resolves to loopback: caught inside the import
            b = client.get(f"/api/books/{r.json()['id']}").json()
            assert b["status"] == "error"
        assert not hit
    finally:
        srv.shutdown()


# ---- uploads ---------------------------------------------------------------------------------


def test_oversized_upload_is_rejected_without_importing(client, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_UPLOAD", 50_000)
    r = client.post("/api/books", files={"file": ("big.md", b"word " * 20_000)})
    assert r.status_code == 413
    assert client.get("/api/books").json() == []


@pytest.mark.parametrize("name", ["../../etc/passwd.md", "..\\..\\evil.md", "a/b/c.md", "x\x00y.md"])
def test_upload_filename_is_reduced_to_a_safe_label(client, name):
    r = client.post("/api/books", files={"file": (name, TINY_BOOK.encode())})
    assert r.status_code == 202
    ref = client.get(f"/api/books/{r.json()['id']}").json()["source_ref"]
    assert "/" not in ref and "\\" not in ref and ".." not in ref and "\x00" not in ref


def test_clean_filename():
    assert ingest.clean_filename("C:\\Users\\x\\..\\book.pdf") == "book.pdf"
    assert ingest.clean_filename("") == "upload" and len(ingest.clean_filename("a" * 999)) == 120


def test_pdf_with_too_many_pages_is_refused(monkeypatch, tmp_path):
    from booktoskill.samplepdf import tiny_book, write_pdf

    pdf = write_pdf(tmp_path / "t.pdf", tiny_book(), title="T")
    monkeypatch.setattr(ingest, "MAX_PDF_PAGES", 1)
    with pytest.raises(ingest.IngestError, match="pages"):
        ingest.convert_upload("t.pdf", pdf.read_bytes())


def _flate_bomb(inflated_mb: int) -> bytes:
    payload = zlib.compress(b"BT /F1 12 Tf (x) Tj ET\n" + b" " * (inflated_mb * 1024 * 1024), 9)
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length " + str(len(payload)).encode() + b"/Filter/FlateDecode>>stream\n"
        + payload + b"\nendstream endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R/Size 6>>\n%%EOF"
    )


def test_pdf_flate_bomb_fails_cleanly_with_bounded_memory():
    import resource_guard

    pdf = _flate_bomb(600)
    assert len(pdf) < 2_000_000

    def attempt():
        try:
            ingest.convert_upload("b.pdf", pdf)
        except ingest.IngestError:
            pass

    assert resource_guard.run_and_measure(attempt) < 400


def test_text_over_the_character_limit_is_refused(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_MARKDOWN_CHARS", 1000)
    with pytest.raises(ingest.IngestError, match="too long"):
        ingest.convert_upload("a.md", ("# T\n\n" + "A sentence of words here. " * 100).encode())


# ---- cross-site and headers ------------------------------------------------------------------


def test_foreign_host_header_is_refused(db_path):
    c = TestClient(create_app(db_path, sync_import=True), base_url="http://evil.example")
    assert c.get("/api/dashboard").status_code == 403  # DNS rebinding


def test_cross_site_writes_are_refused(client):
    for hdr in ({"Origin": "http://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
        assert client.post("/api/books/sample", headers=hdr).status_code == 403, hdr
        r = client.post("/api/books", data={"url": "https://example.org"}, headers=hdr)
        assert r.status_code == 403
    assert client.get("/api/books").json() == []
    ok = client.post("/api/books/sample", headers={"Origin": "http://testserver"})
    assert ok.status_code == 201


def test_security_headers_on_every_response(client):
    for path in ("/", "/api/health", "/app.js"):
        h = client.get(path).headers
        assert "script-src 'self'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
    assert "<script>" not in client.get("/").text  # no inline script: the CSP would block it


# ---- hostile book text and the off-book question ---------------------------------------------

EVIL = """# <img src=x onerror=alert(1)>

## Chapter 1: <script>alert(1)</script>

### <b onmouseover=alert(2)>Topic</b>

A [link](javascript:alert(3)) and [ok](https://example.org/a"onclick="alert(4)) and ![x](x" onerror="alert(5)).
The word <iframe src="javascript:alert(6)"> is plain text inside this sentence about rivers and deltas.
`<script>alert(7)</script>` and **<u>bold</u>** and | <svg onload=alert(8)> | cell |
"""


def test_hostile_markdown_round_trips_as_data(client):
    """The API returns book text untouched; app.js escapes it (checked in a real browser by
    scripts/xss_check.py)."""
    r = client.post("/api/books", files={"file": ("evil.md", EVIL.encode())})
    assert r.status_code == 202
    md = client.get(f"/api/books/{r.json()['id']}/markdown")
    assert md.headers["content-type"].startswith("text/plain")
    assert "<script>alert(1)</script>" in md.text
    assert md.headers["x-content-type-options"] == "nosniff"


def test_off_book_question_with_scattered_words_abstains(sample_book, con):
    for q in ("What is the boiling point of mercury?", "What is the melting point of iron in a candle?"):
        r = ask.ask(con, sample_book, q, use_llm=False)
        assert not r["answered"] and r["citations"] == [], q


@pytest.mark.parametrize("q", [
    "Why does a candle burn?", "How does the candle produce light?",
    "What happens when a candle burns in oxygen?", "How is water formed when a candle burns?",
    "What gas is produced by the burning of carbon?", "How does a lamp bring oil up to the flame?",
    "What is the composition of water?", "What is the product of burning hydrogen?",
])
def test_on_book_paraphrases_still_answer(sample_book, con, q):
    assert ask.ask(con, sample_book, q, use_llm=False)["answered"], q
