#!/usr/bin/env python3
"""Writes grid-32x24.png: four flat quadrants (red, green, blue, white), 8-bit RGB,
no ancillary chunks, so its pixels can be checked exactly after a round trip; and
white-320x160.png, a plain white canvas for the Type tool (any dark pixel is text).
layered-64x48.psd is not generated here: it is PhotoCraft's own output (see README.md)."""
import struct
import zlib
from pathlib import Path

COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]


def pixel(x, y, w=32, h=24):
    return COLOURS[(1 if x >= w // 2 else 0) + (2 if y >= h // 2 else 0)]


def png(w, h, colour=pixel):
    raw = b"".join(b"\0" + b"".join(bytes(colour(x, y, w, h)) for x in range(w)) for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    Path(__file__).with_name("grid-32x24.png").write_bytes(png(32, 24))
    Path(__file__).with_name("white-320x160.png").write_bytes(png(320, 160, lambda *_: (255, 255, 255)))
