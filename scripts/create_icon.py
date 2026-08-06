"""Create the small native application icon without external image tooling."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ICON_PATH = ROOT / "src-tauri" / "icons" / "icon.ico"
SIZE = 256


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def pixel(x: int, y: int) -> tuple[int, int, int, int]:
    margin = 16
    radius = 42
    left = margin
    right = SIZE - margin - 1
    top = margin
    bottom = SIZE - margin - 1

    def outside_corner(cx: int, cy: int) -> bool:
        return (x - cx) ** 2 + (y - cy) ** 2 > radius**2

    if x < left or x > right or y < top or y > bottom:
        return (0, 0, 0, 0)
    if x < left + radius and y < top + radius and outside_corner(left + radius, top + radius):
        return (0, 0, 0, 0)
    if x > right - radius and y < top + radius and outside_corner(right - radius, top + radius):
        return (0, 0, 0, 0)
    if x < left + radius and y > bottom - radius and outside_corner(left + radius, bottom - radius):
        return (0, 0, 0, 0)
    if x > right - radius and y > bottom - radius and outside_corner(right - radius, bottom - radius):
        return (0, 0, 0, 0)

    glow = int(14 * (1 - y / SIZE))
    background = (17 + glow, 30 + glow, 53 + glow, 255)

    document_left, document_top = 70, 52
    document_right, document_bottom = 186, 204
    if document_left <= x <= document_right and document_top <= y <= document_bottom:
        fold = 34
        if x >= document_right - fold and y <= document_top + fold:
            if x + y >= document_right + document_top:
                return background
        if x == document_right - fold and y <= document_top + fold:
            return (125, 211, 252, 255)
        if x >= document_left + 20 and x <= document_right - 20:
            for line_y in (116, 142, 168):
                if line_y <= y <= line_y + 7:
                    return (125, 211, 252, 255)
        return (224, 242, 254, 255)

    return background


def png_bytes() -> bytes:
    rows = []
    for y in range(SIZE):
        row = bytearray([0])
        for x in range(SIZE):
            row.extend(pixel(x, y))
        rows.append(bytes(row))
    raw = b"".join(rows)
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico_bytes() -> bytes:
    image = png_bytes()
    directory = struct.pack("<HH", 0, 1)
    directory += struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(image), 22)
    return directory + image


if __name__ == "__main__":
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICON_PATH.write_bytes(ico_bytes())
    print(f"created {ICON_PATH} ({ICON_PATH.stat().st_size} bytes)")
