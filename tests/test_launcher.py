import socket

from studyloop import db, launcher


def test_free_port_skips_a_busy_one():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert launcher.free_port(busy) != busy


def test_main_seeds_sample_once_then_serves(tmp_path, monkeypatch):
    served = {}
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kw: served.update(kw))
    path = tmp_path / "x.sqlite3"
    launcher.main(["--no-browser", "--db", str(path), "--port", "8991"])
    con = db.connect(path)
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    launcher.main(["--no-browser", "--db", str(path)])
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    assert served["host"] == "127.0.0.1"
    con.close()


def test_no_sample_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kw: None)
    path = tmp_path / "y.sqlite3"
    launcher.main(["--no-browser", "--no-sample", "--db", str(path)])
    con = db.connect(path)
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
    con.close()
