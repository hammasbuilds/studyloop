"""Draw the StudyLoop icon (a loop arrow with an amber spark on a violet tile) and write assets/studyloop.ico.

Pure standard library: the pixels are computed here and stored as PNG entries inside the .ico.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SS = 4  # supersampling per axis


def inside_tile(x: float, y: float, s: float) -> bool:
    r = s * 0.22
    cx = min(max(x, r), s - r)
    cy = min(max(y, r), s - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def in_arrow(x: float, y: float, s: float) -> bool:
    c, R, w = s / 2, s * 0.25, s * 0.085
    dx, dy = x - c, y - c
    d = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx)) % 360
    # ring open between 300 and 345 degrees (upper right); the arrow head sits at 345 pointing back
    if abs(d - R) <= w and not (300 < ang < 345):
        return True
    a = math.radians(345)
    tip = (c + (R + 0) * math.cos(a) + math.sin(a) * s * 0.07, c + R * math.sin(a) - math.cos(a) * s * 0.07)
    base1 = (c + (R + s * 0.13) * math.cos(a), c + (R + s * 0.13) * math.sin(a))
    base2 = (c + (R - s * 0.13) * math.cos(a), c + (R - s * 0.13) * math.sin(a))
    return _in_tri((x, y), tip, base1, base2)


def _in_tri(p, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = sign(p, a, b), sign(p, b, c), sign(p, c, a)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def render(size: int) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            tile = arrow = amber = coral = 0
            for sy in range(SS):
                for sx in range(SS):
                    x, y = px + (sx + 0.5) / SS, py + (sy + 0.5) / SS
                    if inside_tile(x, y, size):
                        tile += 1
                        if in_arrow(x, y, size):
                            arrow += 1
                        elif (x - size * 0.5) ** 2 + (y - size * 0.5) ** 2 <= (size * 0.1) ** 2:
                            amber += 1
                        elif (x - size * 0.765) ** 2 + (y - size * 0.235) ** 2 <= (size * 0.065) ** 2:
                            coral += 1
            n = SS * SS
            if tile == 0:
                row += bytes([0, 0, 0, 0])
                continue
            t = (125, 89, 247)  # violet, fading to a deeper indigo towards the bottom right
            g = (74, 47, 196)
            mix = min(1.0, max(0.0, (px + py) / (2 * size)))
            base = [t[i] * (1 - mix) + g[i] * mix for i in range(3)]
            a_share, am_share, co_share = arrow / tile, amber / tile, coral / tile
            rgb = list(base)
            for share, col in ((a_share, (255, 255, 255)), (am_share, (255, 182, 39)), (co_share, (255, 106, 85))):
                rgb = [rgb[i] * (1 - share) + col[i] * share for i in range(3)]
            rgb = [round(c) for c in rgb]
            row += bytes([*rgb, round(255 * tile / n)])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main(out: str) -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    pngs = [render(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, png in zip(sizes, pngs, strict=True):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(pngs))
    path.with_suffix(".png").write_bytes(pngs[-1])
    print(f"wrote {path} ({path.stat().st_size} bytes, sizes {sizes})")


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "assets/studyloop.ico")
