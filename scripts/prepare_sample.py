"""Turn the Project Gutenberg plain text of Faraday's *The Chemical History of a Candle*
(ebook 14474, public domain) into the markdown sample shipped with StudyLoop.

    uv run python scripts/prepare_sample.py pg14474.txt src/studyloop/sample/candle.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LECTURE = re.compile(r"^LECTURE (I|II|III|IV|V|VI)\.$")


def smart_title(s: str) -> str:
    small = {"of", "the", "to", "and", "in", "a", "its", "for", "from", "into", "or"}
    parts = []
    for part in s.lower().replace(" op ", " of ").split("—"):
        words = part.split()
        parts.append(" ".join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words)))
    return " — ".join(parts)


def main(src: str, dst: str) -> None:
    lines = Path(src).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("*** START"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("*** END"))
    body = lines[start + 1 : end]
    # The body's second LECTURE I. (after the contents list) opens the text.
    starts = [i for i, ln in enumerate(body) if LECTURE.match(ln.strip())]
    first = starts[6] if len(starts) > 6 else starts[0]
    stop = next(i for i, ln in enumerate(body) if ln.strip() == "LECTURE ON PLATINUM." and i > first)
    body = body[first:stop]
    out = [
        "# The Chemical History of a Candle",
        "",
        "*Michael Faraday, a course of six lectures delivered before a juvenile audience at the "
        "Royal Institution, 1848. Public domain. Text from Project Gutenberg ebook 14474 "
        "(edited by William Crookes, 1908).*",
        "",
    ]
    para: list[str] = []

    def flush() -> None:
        if para:
            text = " ".join(x.strip() for x in para)
            text = re.sub(r"\s+", " ", text).replace("_", "")
            if text and not text.startswith("[Illustration"):
                out.extend([text, ""])
            para.clear()

    i = 0
    while i < len(body):
        ln = body[i].strip()
        m = LECTURE.match(ln)
        if m:
            flush()
            j = i + 1
            while not body[j].strip():
                j += 1
            title: list[str] = []
            while body[j].strip():
                title.append(body[j].strip())
                j += 1
            t = smart_title(" ".join(title).rstrip(".").replace("A CANDLE: ", ""))
            out.extend([f"## Lecture {m.group(1)}: {t}", ""])
            i = j
            continue
        if not ln:
            flush()
        else:
            para.append(ln)
        i += 1
    flush()
    Path(dst).write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {dst}: {len(out)} lines")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
