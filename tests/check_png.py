#!/usr/bin/env python3
"""Checks a PNG (8-bit RGB or RGBA, non-interlaced) against an expected picture.

    check_png.py FILE grid|redbox [--size WxH]

grid:   tests/fixtures/grid-32x24.png's quadrants (any size, compared by quadrant centres).
redbox: white with a #ff0000 rectangle x 10..29, y 8..23 (the layered fixture, flattened).
Prints one line per check and exits 1 on any failure."""
import struct
import sys
import zlib


def decode(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError(f"unsupported PNG: depth {depth} colour {colour} interlace {interlace}")
            bpp = 3 if colour == 2 else 4
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    raw, rows, prev, p = zlib.decompress(idat), [], bytearray(w * bpp), 0
    for _ in range(h):
        f, line = raw[p], bytearray(raw[p + 1:p + 1 + w * bpp])
        p += 1 + w * bpp
        for x in range(len(line)):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], (prev[x - bpp] if x >= bpp else 0)
            line[x] = (line[x] + [0, a, b, (a + b) // 2, a if abs(b - c) <= min(abs(a - c), abs(a + b - 2 * c)) else (b if abs(a - c) <= abs(a + b - 2 * c) else c)][f]) & 255
        rows.append(line)
        prev = line
    return w, h, lambda x, y: tuple(rows[y][x * bpp:x * bpp + 3])


def main():
    path, kind = sys.argv[1], sys.argv[2]
    w, h, px = decode(path)
    checks = []
    if "--size" in sys.argv:
        ew, eh = map(int, sys.argv[sys.argv.index("--size") + 1].split("x"))
        checks.append(("size", (w, h) == (ew, eh), f"{w}x{h}"))
    if kind == "grid":
        for name, (x, y), want in [("top-left", (w // 4, h // 4), (255, 0, 0)), ("top-right", (3 * w // 4, h // 4), (0, 255, 0)),
                                   ("bottom-left", (w // 4, 3 * h // 4), (0, 0, 255)), ("bottom-right", (3 * w // 4, 3 * h // 4), (255, 255, 255))]:
            checks.append((name, px(x, y) == want, f"{px(x, y)}"))
    elif kind == "redbox":
        inside = all(px(x, y) == (255, 0, 0) for x in range(10, 30) for y in range(8, 24))
        outside = all(px(x, y) == (255, 255, 255) for x in range(w) for y in range(h) if not (10 <= x < 30 and 8 <= y < 24))
        checks += [("box-red", inside, ""), ("rest-white", outside, "")]
    failed = 0
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
        failed += not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
