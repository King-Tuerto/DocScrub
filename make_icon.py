#!/usr/bin/env python3
"""
Generate assets/docscrub.ico — a 32x32 teal "D" icon, stdlib only.

Run once:  python make_icon.py
Output:    assets/docscrub.ico
"""
import struct
from pathlib import Path

# DocScrub brand teal: #0D9488 stored as BGRA
_TEAL = (0x88, 0x94, 0x0D, 0xFF)
_WHITE = (0xFF, 0xFF, 0xFF, 0xFF)
_CLEAR = (0x00, 0x00, 0x00, 0x00)


def _is_d(col: int, row: int, size: int) -> bool:
    """Return True if (col, row) is part of the white "D" glyph."""
    pad = 2
    top = pad + 1
    bot = size - pad - 2
    left = pad + 2
    bar_r = left + 3           # right edge of vertical bar

    # Left vertical bar
    if left <= col <= bar_r and top <= row <= bot:
        return True

    # D curve: right-hand semi-ellipse minus hollow interior
    cx = float(left)
    cy = (top + bot) / 2.0
    a_out = size * 0.44          # outer horizontal radius
    b_out = (bot - top) / 2.0   # outer vertical radius
    a_in  = a_out * 0.60         # inner horizontal radius
    b_in  = b_out * 0.60         # inner vertical radius

    dx = col - cx
    dy = row - cy

    if dx <= 0:
        return False

    in_outer = (dx / a_out) ** 2 + (dy / b_out) ** 2 <= 1.0
    in_inner = (dx / a_in)  ** 2 + (dy / b_in)  ** 2 <= 1.0

    return in_outer and not in_inner


def _make_32() -> bytes:
    size = 32

    # Build pixel grid (BGRA)
    rows: list[list[tuple]] = []
    for r in range(size):
        row_pixels = []
        for c in range(size):
            # Rounded-square background: clip corners by 3px
            cx2 = (size - 1) / 2.0
            dx = abs(c - cx2) - (size / 2.0 - 3.5)
            dy = abs(r - cx2) - (size / 2.0 - 3.5)
            outside = (max(dx, 0) ** 2 + max(dy, 0) ** 2) > 3.5 ** 2

            if outside:
                row_pixels.append(_CLEAR)
            elif _is_d(c, r, size):
                row_pixels.append(_WHITE)
            else:
                row_pixels.append(_TEAL)
        rows.append(row_pixels)

    # ICO stores rows bottom-to-top
    pixel_data = b"".join(
        bytes(px)
        for row in reversed(rows)
        for px in row
    )

    # AND mask: 1 bit/pixel, rows padded to 4-byte boundary (all 0 = opaque)
    row_bytes = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (row_bytes * size)

    bih = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2,  # biSize, biWidth, biHeight (doubled for ICO)
        1, 32,               # biPlanes, biBitCount
        0, len(pixel_data),  # biCompression=BI_RGB, biSizeImage
        0, 0, 0, 0,          # pels/meter x/y, clrUsed, clrImportant
    )
    image_data = bih + pixel_data + and_mask

    # 6-byte ICO header + 16-byte directory entry
    ico_header = struct.pack("<HHH", 0, 1, 1)   # reserved, type=ICO, count=1
    dir_entry = struct.pack(
        "<BBBBHHII",
        size, size,           # width, height
        0, 0,                 # color count, reserved
        1, 32,                # planes, bit count
        len(image_data),
        6 + 16,               # data offset (header + one dir entry)
    )

    return ico_header + dir_entry + image_data


if __name__ == "__main__":
    Path("assets").mkdir(exist_ok=True)
    data = _make_32()
    out = Path("assets/docscrub.ico")
    out.write_bytes(data)
    print(f"Created {out}  ({len(data):,} bytes)")
