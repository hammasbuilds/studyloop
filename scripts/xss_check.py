"""Import a book full of HTML/JS payloads and visit every page that renders book text in a real
browser. Fails if a dialog opens, a script runs, an injected element exists, or the console errors.

    uv run studyloop --no-browser --port 8831 --db <tmp.sqlite3>
    uv run --with playwright python scripts/xss_check.py http://127.0.0.1:8831
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
PAY = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>'
EVIL = f"""# {PAY}

## Chapter 1: {PAY}

### <b onmouseover="window.__pwned=1">Topic</b> {PAY}

A [link](javascript:window.__pwned=1) and [ok](https://example.org/a"onclick="window.__pwned=1) and
![x](x" onerror="window.__pwned=1"). The word <iframe src="javascript:window.__pwned=1"> sits in this
sentence about rivers and deltas and levees and sediment.

`{PAY}` and **<u>bold</u>** and a table follows.

| <svg onload="window.__pwned=1"> | cell |
| --- | --- |
| {PAY} | x |

- list item {PAY} about rivers and deltas
"""


def post(path: str, **fields) -> dict:
    boundary = "----x"
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req))


def main() -> int:
    bid = post("/api/books", text=EVIL, title=PAY)["id"]
    problems: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_page()
        page.on("dialog", lambda d: (problems.append("dialog: " + d.message), d.dismiss()))
        page.on("console", lambda m: m.type == "error" and problems.append("console: " + m.text))
        page.on("pageerror", lambda e: problems.append("pageerror: " + str(e)))
        topic = json.load(urllib.request.urlopen(f"{BASE}/api/books/{bid}"))["course"][0]["topics"][0]["id"]
        q = urllib.parse.quote(PAY + " rivers deltas")
        for h in ("#/", "#/library", f"#/book/{bid}", f"#/topic/{topic}", f"#/topic/{topic}?hl=0-200",
                  f"#/ask/{bid}?q={q}", "#/review", "#/memory"):
            page.goto(f"{BASE}/{h}")
            page.wait_for_timeout(700)
            if h.startswith("#/topic") and "window.__pwned" not in page.inner_text("#app"):
                problems.append("payload text was not shown (the check proves nothing)")
            if page.evaluate("window.__pwned") is not None:
                problems.append(f"script ran on {h}")
            n = page.evaluate("document.querySelectorAll('#app img[onerror], #app script, #app iframe,"
                              " #app svg[onload], #app [onmouseover], #app [onclick]').length")
            if n:
                problems.append(f"{n} injected element(s) on {h}")
            for a in page.query_selector_all("#app a[href]"):
                if (a.get_attribute("href") or "").lower().startswith("javascript:"):
                    problems.append(f"javascript: link on {h}")
        b.close()
    urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/books/{bid}", method="DELETE"))
    print("XSS check:", "FAILED" if problems else "no script ran, no injected element, no console error")
    for x in problems:
        print("  -", x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
