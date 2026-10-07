"""``uv run studyloop``: start the server and open the browser."""

from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from . import db, ingest
from .app import create_app


def free_port(preferred: int, host: str = "127.0.0.1") -> int:
    for port in [preferred, *range(preferred + 1, preferred + 40)]:
        with socket.socket() as s:
            if s.connect_ex((host, port)) != 0:
                return port
    raise RuntimeError("no free port found")


def _open_when_ready(url: str) -> None:
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1).read()
            break
        except OSError:
            time.sleep(0.15)
    webbrowser.open(url)


def _warm_up() -> None:
    """Load the Urdu / Roman Urdu tables now, so the first Urdu question is not the slow one."""
    from . import urdu

    for q in ("موم بتی کیسے جلتی ہے؟", "pani kaise banta hai", "what is a flame"):
        try:
            urdu.analyse(q, urdu.book_vocab(["candle", "burn", "water", "flame"]))
        except Exception:  # noqa: BLE001 - a warm-up must never stop the server
            return


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="studyloop", description="Your textbooks, as a personal tutor.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    ap.add_argument("--no-sample", action="store_true", help="do not load the sample book on first run")
    ap.add_argument("--db", help="SQLite file (default: ~/.studyloop/studyloop.sqlite3)")
    a = ap.parse_args(argv)
    path = a.db or db.default_db_path()
    db.init(path)
    con = db.connect(path)
    try:
        if not a.no_sample and con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            ingest.sample_book(con)
    finally:
        con.close()
    port = free_port(a.port, a.host)
    threading.Thread(target=_warm_up, daemon=True).start()
    url = f"http://{a.host}:{port}"
    print(f"StudyLoop on {url}  (data: {path})  Ctrl+C to stop")
    if not a.no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(create_app(path, loopback_only=a.host in ("127.0.0.1", "localhost", "::1")), host=a.host, port=port, log_level="warning")
