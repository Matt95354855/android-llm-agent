"""Encodage PNG minimal côté serveur (évite la compression lente faite par Android)."""

from __future__ import annotations

import struct
import zlib


def encode_png(width: int, height: int, data: bytes, channels: int = 3, level: int = 1) -> bytes:
    """`data` : pixels bruts ligne par ligne (RGB si channels=3, RGBA si channels=4)."""
    color_type = {3: 2, 4: 6}[channels]
    stride = width * channels

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + data[y * stride : (y + 1) * stride] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, level))
        + chunk(b"IEND", b"")
    )


def raw_screencap_to_png(raw: bytes) -> bytes | None:
    """Convertit la sortie de `screencap` (sans -p) en PNG ; None si le format n'est pas RGBA_8888."""
    if len(raw) < 12:
        return None
    width, height, fmt = struct.unpack("<III", raw[:12])
    size = width * height * 4
    header = len(raw) - size
    if fmt != 1 or header not in (12, 16) or width == 0 or height == 0:
        return None
    return encode_png(width, height, raw[header:], channels=4)
