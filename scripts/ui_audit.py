"""Exhaustive UI audit: every control on every page, at three viewports, with real input.

    uv run --with playwright python scripts/ui_audit.py [--quick]

Starts its own server on a free port in 8800-8899 with a temporary data directory, loads the
sample book plus a small markdown book through the API, and drives headless Edge at 1440x900 dark,
1440x900 light and 390x844 (phone). For each page it queries the DOM for every link, button,
input, select, checkbox, textarea, file input, drop zone, chip and summary, then clicks, fills or
chooses each one with a realistic value, waits for the response and records:

  console errors, page errors, failed requests (4xx/5xx other than the intended refusals listed in
  EXPECTED), elements that overflow the viewport or their box, text clipped mid-word, NaN /
  undefined / null / [object Object] on screen, an error page, a stale result left after a refused
  request, and spinners that never stop.

Controls that appear only after an action (quiz options, Next, note edit/delete) are exercised in
the same pass. It prints one row per action, the denominator (controls found vs exercised) and
exits non-zero on any problem. Only the server process it started is stopped.
"""

from __future__ import annotations

import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
QUICK = "--quick" in sys.argv
PORT = next(p for p in range(8800, 8900) if socket.socket().connect_ex(("127.0.0.1", p)) != 0)
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path(tempfile.mkdtemp(prefix="studyloop_audit_"))
DB = HOME / "studyloop.sqlite3"
WORK = Path(tempfile.mkdtemp(prefix="studyloop_audit_files_"))
TINY = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8").split('TINY_BOOK = """')[1].split('"""')[0]
(WORK / "rivers.md").write_text(TINY, encoding="utf-8")

# Refusals the app is meant to give; a matching response is an expected outcome, not a problem.
EXPECTED = [
    ("POST", r"/api/ask$", 422),  # the over-long question probe below
]
VALUES = {  # realistic input per field, from the shipped sample book
    "q": "What is hydrogen?", "tryq": "What is capillary attraction?", "mq": "water",
    "pasted": "# Tides\n\n## Why tides happen\n\nThe Moon pulls on the oceans, and the water bulges on the side "
              "facing it. As the Earth turns, a coast passes through two bulges a day, so most places have two "
              "high tides.",
    "title": "Audit throwaway", "goal": "20", "newnote": "Hydrogen burns to make water.",
    "url": "",  # filled in once the local article server is known
}
CONFIGS = [("desktop-dark", 1440, 900, "dark"), ("desktop-light", 1440, 900, "light"), ("phone", 390, 844, "dark")]
if QUICK:
    CONFIGS = CONFIGS[2:]

CONTROLS_JS = r"""
() => {
  const sel = 'a[href], button, input, select, textarea, [role=button], details > summary, .chip[data-q], .chip[data-i]';
  const seen = new Map(), out = [];
  document.querySelectorAll('[data-audit]').forEach((e) => e.removeAttribute('data-audit'));
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('.toast')) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    const fileInput = el.type === 'file';
    const visible = fileInput || (r.width > 0 && r.height > 0 && cs.visibility !== 'hidden');
    if (!visible) continue;
    if (el.disabled) continue;
    const field = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName); const txt = ((field ? (el.getAttribute('aria-label') || el.placeholder || el.name || el.type) : (el.innerText || el.getAttribute('aria-label'))) || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    const base = [el.tagName.toLowerCase(), el.type && el.tagName !== 'A' ? el.type : '', el.id ? '#' + el.id : '',
                  el.getAttribute('href') || '', el.dataset.q || el.dataset.i || el.dataset.o || el.dataset.del || el.dataset.edit || el.dataset.rm || el.dataset.jump || el.dataset.mode || '', txt].join('|');
    const n = (seen.get(base) || 0) + 1; seen.set(base, n);
    out.push({ key: base + '|' + n, tag: el.tagName.toLowerCase(), type: el.type || '', id: el.id, href: el.getAttribute('href') || '',
               download: el.hasAttribute('download'), target: el.target || '', text: txt, cls: el.className || '' });
  }
  return out;
}
"""
MARK_JS = r"""
(key) => {
  const sel = 'a[href], button, input, select, textarea, [role=button], details > summary, .chip[data-q], .chip[data-i]';
  const seen = new Map();
  document.querySelectorAll('[data-audit]').forEach((e) => e.removeAttribute('data-audit'));
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('.toast')) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    const visible = el.type === 'file' || (r.width > 0 && r.height > 0 && cs.visibility !== 'hidden');
    if (!visible || el.disabled) continue;
    const field = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName); const txt = ((field ? (el.getAttribute('aria-label') || el.placeholder || el.name || el.type) : (el.innerText || el.getAttribute('aria-label'))) || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    const base = [el.tagName.toLowerCase(), el.type && el.tagName !== 'A' ? el.type : '', el.id ? '#' + el.id : '',
                  el.getAttribute('href') || '', el.dataset.q || el.dataset.i || el.dataset.o || el.dataset.del || el.dataset.edit || el.dataset.rm || el.dataset.jump || el.dataset.mode || '', txt].join('|');
    const n = (seen.get(base) || 0) + 1; seen.set(base, n);
    if (base + '|' + n === key) { el.setAttribute('data-audit', '1'); return true; }
  }
  return false;
}
"""
LAYOUT_JS = r"""
() => {
  const out = [], vw = document.documentElement.clientWidth;
  const path = (el) => { const p = []; for (let e = el; e && e !== document.body && p.length < 4; e = e.parentElement) p.unshift(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.classList[0] ? '.' + e.classList[0] : '')); return p.join('>'); };
  if (document.documentElement.scrollWidth > vw + 1) out.push('page scrolls sideways (' + document.documentElement.scrollWidth + ' > ' + vw + ')');
  const clips = (el) => { for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) { const o = getComputedStyle(a).overflowX; if (o !== 'visible') return true; } return false; };
  for (const el of document.querySelectorAll('header.top *, #app *')) {
    if (el instanceof SVGElement) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.position === 'fixed') continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    if (r.right > vw + 1 && !clips(el)) out.push('past the right edge: ' + path(el) + ' (right ' + Math.round(r.right) + ' > ' + vw + ')');
    // text that runs past the element's own box: measured on the text itself with a Range, so
    // padding, ripples and pseudo-elements do not count
    if (['TEXTAREA', 'INPUT', 'SELECT', 'PRE', 'CODE'].includes(el.tagName) || cs.textOverflow === 'ellipsis') continue;
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      const tr = rg.getBoundingClientRect();
      if (tr.width && (tr.right > r.right + 1 || tr.left < r.left - 1)) {
        out.push((cs.overflowX === 'visible' ? 'text overflows its box: ' : 'text clipped: ') + path(el) + ' "' + n.textContent.trim().slice(0, 30) + '"');
        break;
      }
    }
  }
  const clone = document.getElementById('app').cloneNode(true);
  clone.querySelectorAll('article.reading, .quote, .ans, .answer-box, textarea').forEach((e) => e.remove());
  const t = document.querySelector('header.top').innerText + ' ' + clone.innerText;
  const bad = t.match(/\b(NaN|undefined|null)\b|\[object Object\]|Infinity%/);
  if (bad) out.push('bad value on screen: "' + bad[0] + '"');
  if (/Something went wrong|Page not found/.test(document.getElementById('app').innerText)) out.push('error page: ' + document.querySelector('#app h2')?.innerText);
  return [...new Set(out)];
}
"""
BUSY_JS = "() => [...document.querySelectorAll('.spinner, .btn.loading, .skel')].filter((e) => e.getBoundingClientRect().width > 0).length"


def wait_js(page, fn: str, timeout: float = 20) -> None:
    """Poll a predicate with evaluate: wait_for_function needs eval, which the app's CSP forbids
    (and the audit runs with the real CSP on)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.evaluate(fn):
                return
        except PWError:
            pass
        page.wait_for_timeout(100)
    raise TimeoutError(f"timed out waiting for {fn}")


def correct_answer(prompt: str) -> str | None:
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT prompt, answer FROM questions").fetchall()
    con.close()
    norm = lambda s: " ".join(s.replace("_____", "").split())  # noqa: E731
    return next((r[1] for r in rows if norm(r[0]) == norm(prompt)), None)


def api(method: str, path: str, data: bytes | None = None, ctype: str = "application/json") -> bytes:
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": ctype})
    return urllib.request.urlopen(req, timeout=60).read()


rows: list[tuple] = []
found_total = exercised_total = 0
problem_count = 0


def main() -> int:  # noqa: C901 - one linear script
    global found_total, exercised_total, problem_count
    import http.server
    import json
    import threading

    article = ("<html><head><title>How deltas form</title></head><body><article><h1>How deltas form</h1><p>A delta is "
               "a landform built where a river slows as it meets the sea and drops its sediment.</p><h2>Why deltas are "
               "fertile</h2><p>Each flood leaves fresh silt rich in minerals, so deltas are fertile farmland.</p>"
               "</article></body></html>")
    (WORK / "article.html").write_text(article, encoding="utf-8")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(WORK), **k)  # noqa: E731
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    VALUES["url"] = f"http://127.0.0.1:{web.server_address[1]}/article.html"

    server = subprocess.Popen(
        [sys.executable, "-c", f"from studyloop.launcher import main; main(['--no-browser','--port','{PORT}','--db',r'{DB}'])"],
        env={**os.environ, "STUDYLOOP_HOME": str(HOME), "STUDYLOOP_ALLOW_PRIVATE_URLS": "1"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise SystemExit("server did not start")
        sample = json.loads(api("POST", "/api/books/sample"))["id"]
        boundary = "auditboundary"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"rivers.md\"\r\n"
                f"Content-Type: text/markdown\r\n\r\n{TINY}\r\n--{boundary}--\r\n").encode()
        api("POST", "/api/books", body, f"multipart/form-data; boundary={boundary}")
        for _ in range(100):
            if all(b["status"] != "processing" for b in json.loads(api("GET", "/api/books"))):
                break
            time.sleep(0.2)
        book = json.loads(api("GET", f"/api/books/{sample}"))
        topic = next(t["id"] for c in book["course"] for t in c["topics"] if t["title"] == "Hydrogen")
        # some history so Review, Memory and the dashboard have content to show
        for q in ("What is capillary attraction?", "What is capillary attraction?", "Who won the 1998 world cup?"):
            api("POST", "/api/ask", json.dumps({"book_id": sample, "question": q, "use_llm": False}).encode())
        for qq in json.loads(api("GET", f"/api/topics/{topic}/quiz?n=4"))["questions"]:
            api("POST", "/api/quiz/answer", json.dumps({"question_id": qq["id"], "response": "x"}).encode())
        api("POST", "/api/notes", json.dumps({"topic_id": topic, "text": "Water is made of hydrogen and oxygen."}).encode())

        pages = [("Dashboard", "#/"), ("Library", "#/library"), ("Course", f"#/book/{sample}"),
                 ("Topic + quiz", f"#/topic/{topic}"), ("Ask the book", f"#/ask/{sample}"), ("Review", "#/review"),
                 ("Memory", "#/memory"), ("About", "#/about")]

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            for cname, w, h, scheme in CONFIGS:
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, accept_downloads=True)
                page = ctx.new_page()
                events: list[str] = []
                dialog = {"accept_confirm": False}

                def on_response(r, events=events):
                    if r.status < 400:
                        return
                    path = r.url.replace(BASE, "")
                    if any(r.request.method == m and re.search(rx, path) and r.status == st for m, rx, st in EXPECTED):
                        return
                    events.append(f"http {r.status} {r.request.method} {path}")

                # the browser also logs every 4xx/5xx as a console error; those are judged by the
                # response handler (which knows the intended refusals), so they are not counted twice
                page.on("console", lambda m, events=events: events.append(f"console: {m.text}")
                        if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
                page.on("pageerror", lambda e, events=events: events.append(f"pageerror: {e}"))
                page.on("requestfailed", lambda r, events=events: events.append(f"request failed: {r.url} {r.failure}"))
                page.on("response", on_response)

                def on_dialog(d, dialog=dialog):
                    if d.type == "prompt":
                        d.accept("Edited note: hydrogen burns to make water.")
                    elif d.type == "confirm" and dialog["accept_confirm"]:
                        d.accept()
                    else:
                        d.dismiss()

                page.on("dialog", on_dialog)

                def settle(page=page, long: bool = False) -> str | None:
                    page.wait_for_timeout(250)
                    limit = time.time() + (30 if long else 10)
                    while time.time() < limit:
                        try:
                            if page.evaluate(BUSY_JS) == 0:
                                return None
                        except PWError:
                            pass
                        page.wait_for_timeout(150)
                    return "spinner never stopped"

                def go(url: str, page=page) -> None:
                    if page.url == BASE + "/" + url:
                        page.reload()  # same hash: goto would not re-render the page
                    else:
                        page.goto(BASE + "/" + url)
                    wait_js(page, "() => !!document.querySelector('#app') && !document.querySelector('#app .skel')")
                    settle(long=True)

                for pname, url in pages:
                    go(url)
                    page.evaluate("document.querySelectorAll('details').forEach((d) => d.open = true)")
                    controls = page.evaluate(CONTROLS_JS)
                    found_total += len(controls)
                    page_problems = page.evaluate(LAYOUT_JS) + events[:]
                    events.clear()
                    rows.append((cname, pname, "(page)", "load", f"{len(controls)} controls", page_problems))
                    problem_count += len(page_problems)
                    done_keys: set[str] = set()
                    queue = list(controls)
                    dyn_budget = 40  # a quiz keeps producing new controls (Next, options, Another round)
                    while queue:
                        c = queue.pop(0)
                        if c["key"] in done_keys and not c.get("dynamic"):
                            continue
                        done_keys.add(c["key"])
                        if page.url != BASE + "/" + url and not c.get("dynamic"):
                            go(url)
                            page.evaluate("document.querySelectorAll('details').forEach((d) => d.open = true)")
                        page.evaluate("document.querySelectorAll('details').forEach((d) => d.open = true)")
                        if not page.evaluate(MARK_JS, c["key"]) and not c.get("dynamic"):
                            go(url)  # an earlier action replaced it (a new answer, a closed panel): start fresh
                            page.evaluate("document.querySelectorAll('details').forEach((d) => d.open = true)")
                        if not page.evaluate(MARK_JS, c["key"]):
                            if c.get("dynamic"):
                                found_total -= 1  # a transient control that went away (e.g. the old question's options)
                                continue
                            if c["href"].startswith("#/"):
                                # a review or history list re-ordered by answers given earlier on this
                                # page: follow the link itself so the target page is still checked
                                page.goto(BASE + "/" + c["href"])
                                wait_js(page, "() => !document.querySelector('#app .skel')")
                                probs = (["spinner never stopped"] if settle(long=True) else []) + page.evaluate(LAYOUT_JS) + events[:]
                                events.clear()
                                exercised_total += 1
                                rows.append((cname, pname, c["text"][:38], "follow", "list re-ordered; -> " + c["href"][1:40], probs))
                                problem_count += len(probs)
                                continue
                            rows.append((cname, pname, c["text"] or c["key"][:40], "-", "not found after reload", ["control vanished"]))
                            problem_count += 1
                            continue
                        loc = page.locator("[data-audit='1']")
                        before = set(x["key"] for x in page.evaluate(CONTROLS_JS))
                        page.evaluate(MARK_JS, c["key"])
                        action, result, probs = act(page, ctx, c, loc, dialog, settle)
                        exercised_total += 1
                        if probs is None:
                            probs = []
                        busy = settle(long=c["id"] in ("addurl", "addtext", "file", "drop", "exfile", "sample"))
                        if busy:
                            probs.append(busy)
                        try:
                            probs += page.evaluate(LAYOUT_JS)
                        except PWError:
                            pass
                        probs += events[:]
                        events.clear()
                        rows.append((cname, pname, (c["text"] or c["id"] or c["href"])[:38], action, " ".join(result.split())[:60], probs))
                        problem_count += len(probs)
                        if c["id"] == "theme":
                            api("PUT", "/api/settings", json.dumps({"theme": "auto"}).encode())
                            page.evaluate("delete document.documentElement.dataset.theme")
                        # controls that appeared because of this action, on the same page
                        if (page.url == BASE + "/" + url or c.get("dynamic")) and dyn_budget > 0:
                            try:
                                now = page.evaluate(CONTROLS_JS)
                            except PWError:
                                now = []
                            fresh = [dict(x, dynamic=True) for x in now if x["key"] not in before
                                     and not x["href"].startswith("#/topic/") and not x["href"].startswith("#/book/")][:dyn_budget]
                            dyn_budget -= len(fresh)
                            found_total += len(fresh)
                            queue = fresh + queue

                    # probes: refusals must not leave the previous result on screen
                    if pname == "Ask the book":
                        go(url)
                        page.fill("#q", "What is hydrogen?")
                        page.click("#go")
                        page.wait_for_selector("#result .answer-box")
                        page.fill("#q", "why " * 300)
                        page.click("#go")
                        settle()
                        stale = page.query_selector("#result .answer-box") is not None
                        probs = (["stale answer left after the refusal"] if stale else []) + events[:]
                        events.clear()
                        rows.append((cname, pname, "question of 1,200 characters", "submit", "refused (422), result cleared" if not stale else "stale", probs))
                        problem_count += len(probs)
                        found_total += 1
                        exercised_total += 1
                    if pname == "Memory":
                        go(url)
                        page.fill("#mq", "capillary")
                        page.click("#msearch")
                        page.wait_for_selector("#mres .cite")
                        dup = page.inner_text("#mres").count("What is capillary attraction?")
                        page.fill("#mq", "zzqqxx")
                        page.click("#msearch")
                        settle()
                        txt = page.inner_text("#mres")
                        probs = ([] if "Nothing matches" in txt else ["stale hits left after an empty search"])
                        probs += ([] if dup == 1 else [f"repeated question listed {dup} times"]) + events[:]
                        events.clear()
                        rows.append((cname, pname, "search with no match after a hit", "submit", txt.strip()[:40], probs))
                        problem_count += len(probs)
                        found_total += 1
                        exercised_total += 1
                ctx.close()
            browser.close()
    finally:
        web.shutdown()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()

    print(f"{'config':<14} {'page':<13} {'control':<38} {'action':<10} {'result':<44} problems")
    for cname, pname, ctl, action, result, probs in rows:
        print(f"{cname:<14} {pname:<13} {ctl:<38} {action:<10} {result:<44} {'; '.join(probs) if probs else '-'}")
    print(f"\ncontrols found: {found_total}, exercised: {exercised_total}, problems: {problem_count}")
    return 1 if problem_count or exercised_total < found_total else 0


def act(page, ctx, c, loc, dialog, settle):  # noqa: C901
    """Do the realistic thing with one control. Returns (action, result, problems)."""
    tag, typ, cid, href = c["tag"], c["type"], c["id"], c["href"]
    try:
        if typ == "file":
            loc.set_input_files(str(WORK / "rivers.md"))
            settle(long=True)
            return "choose", page.inner_text("#msg") or "chosen", []
        if cid == "drop":
            handle = page.evaluate_handle(
                "() => { const dt = new DataTransfer(); dt.items.add(new File(['# Dropped\\n\\n## A topic\\n\\nA dropped file "
                "becomes a book with one chapter and one topic about dropping.'], 'dropped.md', {type: 'text/markdown'})); return dt; }")
            loc.dispatch_event("drop", {"dataTransfer": handle})
            settle(long=True)
            return "drop file", page.inner_text("#msg") or "dropped", []
        if tag == "select":
            opts = loc.evaluate("(s) => [...s.options].map((o) => o.value)")
            cur = loc.input_value()
            other = next((o for o in opts if o != cur), cur)
            loc.select_option(other)
            settle()
            return "choose", f"option {other} of {len(opts)}", []
        if typ == "checkbox":
            loc.click()
            return "toggle", "checked" if loc.is_checked() else "unchecked", []
        if tag in ("input", "textarea") and typ not in ("button", "submit"):
            if cid == "resp":
                ans = correct_answer(page.inner_text(".q-prompt").replace("\n", " ")) or "carbon"
                loc.fill(ans)
                loc.press("Enter")
                settle()
                return "type+enter", "graded: " + (page.inner_text("#fb")[:30] if page.query_selector("#fb .feedback") else "no feedback"), \
                    [] if page.query_selector("#fb .feedback") else ["typed answer gave no feedback"]
            if cid == "tryresp":
                loc.fill("hydrogen")
                loc.press("Enter")
                settle()
                return "type+enter", "graded" if page.query_selector("#tryfb .feedback") else "no feedback", \
                    [] if page.query_selector("#tryfb .feedback") else ["typed answer gave no feedback"]
            val = VALUES.get(cid, "hydrogen")
            loc.fill(val)
            if cid in ("q", "mq", "url"):
                loc.press("Enter")
                settle(long=cid == "url")
                return "type+enter", {"q": "answer shown", "mq": "search run", "url": "import sent"}[cid], []
            return "type", f"{len(val)} characters", []
        # links
        if tag == "a" and href.startswith("http"):
            return "check href", "external link, well-formed" if re.match(r"https://[\w.-]+/", href) else "bad", \
                [] if re.match(r"https://[\w.-]+/", href) else [f"bad external href {href}"]
        if tag == "a" and href.startswith("/api/"):
            if c["download"]:
                with page.expect_download(timeout=15000) as dl:
                    loc.click()
                path = dl.value.path()
                size = Path(path).stat().st_size if path else 0
                return "download", f"{dl.value.suggested_filename} ({size} bytes)", [] if size > 20 else ["empty download"]
            r = ctx.request.get(BASE + href)
            return "open", f"HTTP {r.status}, {len(r.body())} bytes", [] if r.ok and len(r.body()) > 20 else [f"{href} -> {r.status}"]
        # buttons, chips, hash links, summaries: fill the page's inputs realistically first
        if tag == "button" or c["cls"].find("chip") >= 0 or tag == "summary" or (tag == "a" and not href.startswith("#/")) or (tag == "a" and href == "#/"):
            if cid in ("addurl", "addtext", "msearch", "go", "tryrun", "save", "addnote"):
                for fid in {"addurl": ["url", "title"], "addtext": ["pasted", "title"], "msearch": ["mq"], "go": ["q"],
                            "tryrun": ["tryq"], "save": ["goal"], "addnote": ["newnote"]}[cid]:
                    el = page.query_selector("#" + fid)
                    if el:
                        el.fill(VALUES[fid])
            row_text = loc.evaluate("(e) => (e.closest('.li, .book-card') || e).innerText")
            dialog["accept_confirm"] = "Audit throwaway" in row_text or "Tides" in row_text
            if c["key"].split("|")[5] in ("Delete", "Remove") and not dialog["accept_confirm"]:
                loc.click()
                settle()
                dialog["accept_confirm"] = False
                return "click", "confirm shown and cancelled", []
            loc.click()
            settle(long=cid in ("addurl", "addtext", "exfile", "sample"))
            dialog["accept_confirm"] = False
            msg = page.query_selector("#msg")
            res = (msg.inner_text().strip() if msg and cid in ("addurl", "addtext", "exfile", "sample", "exurl", "extext") else "") \
                or page.url.split("#")[-1]
            return "click", res or "clicked", []
        if tag == "a":
            loc.click()
            wait_js(page, "() => !document.querySelector('#app .skel')")
            return "click", "-> " + page.url.split("#", 1)[-1], []
        loc.click()
        return "click", "clicked", []
    except PWError as e:
        return "error", str(e).splitlines()[0][:60], [f"could not exercise: {str(e).splitlines()[0][:120]}"]


if __name__ == "__main__":
    sys.exit(main())
