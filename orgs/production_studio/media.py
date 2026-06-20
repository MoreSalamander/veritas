"""Tiny stdlib media writers/readers — no third-party image library required.

The asset stage must produce REAL, decodable files so the integrity gate checks facts (a true
PNG of the stated size, a WAV of the stated duration), not a mock. PNG and WAV are both writable
and readable with the standard library alone (zlib/struct for PNG, the wave module for WAV), so the
offline stub stays dependency-free. A real image-gen / TTS engine slots in behind the same seam
later; these helpers stay the verification ground truth.
"""

from __future__ import annotations

import struct
import wave
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(typ: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def write_png(path: Path, width: int, height: int, color: tuple[int, int, int] = (120, 120, 120)) -> None:
    """Write a valid solid-color RGB PNG of the given size."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit, color type 2 (RGB)
    row = b"\x00" + bytes(color) * width  # filter byte 0 + the pixels
    idat = zlib.compress(row * height, 9)
    path.write_bytes(PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr)
                     + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b""))


def read_png_size(path: Path) -> tuple[int, int]:
    """Read (width, height) from a PNG's IHDR. Raises ValueError if it isn't a valid PNG."""
    data = path.read_bytes()
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("not a valid PNG")
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def write_wav(path: Path, seconds: float, sample_rate: int = 22050) -> None:
    """Write `seconds` of mono 16-bit silence — a real, playable WAV of the stated length."""
    frames = max(1, int(seconds * sample_rate))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * frames)


def read_wav_duration(path: Path) -> float:
    """Read a WAV's duration in seconds. Raises if it isn't a readable WAV."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        if rate <= 0:
            raise ValueError("WAV has no frame rate")
        return w.getnframes() / float(rate)
