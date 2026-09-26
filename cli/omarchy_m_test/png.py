"""PNG decoding with the standard library only (zlib and struct).

    image = png.decode(data)          # a screenshot grim took
    red, green, blue = image.pixel(x, y)

Decodes what screenshot tools write: non-interlaced RGB or RGBA, 8 or 16
bits per channel, any of the five row filters. Alpha is dropped and 16-bit
channels are cut to their high byte, so pixels are always 8-bit (r, g, b).
Anything else (palette, greyscale, interlaced, a broken file) raises
PngError.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOUR_CHANNELS = {2: 3, 6: 4}  # colour type -> channels: RGB, RGBA
MAX_PIXELS = 64 * 1024 * 1024  # a screenshot never needs more; a broken header mustn't allocate gigabytes


class PngError(Exception):
    """Not a PNG this decoder reads."""


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    rows: tuple[bytes, ...]  # 8-bit RGB, width * 3 bytes each

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        row = self.rows[y]
        return row[3 * x], row[3 * x + 1], row[3 * x + 2]


def decode(data: bytes) -> Image:
    if not data.startswith(SIGNATURE):
        raise PngError("not a PNG file")
    header = None
    compressed = bytearray()
    position = len(SIGNATURE)
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if len(body) != length:
            raise PngError("the file is cut short")
        position += 12 + length
        if kind == b"IHDR":
            if length != 13:
                raise PngError("the IHDR chunk is the wrong size")
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
    if header is None:
        raise PngError("no IHDR chunk")
    width, height, depth, colour, _compression, _filter, interlace = header
    if colour not in COLOUR_CHANNELS or depth not in (8, 16):
        raise PngError(f"unsupported colour type {colour} at {depth} bits (only 8- or 16-bit RGB and RGBA)")
    if interlace:
        raise PngError("interlaced PNGs aren't supported")
    if not 0 < width * height <= MAX_PIXELS:
        raise PngError(f"unexpected size {width}x{height}")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as error:
        raise PngError(f"the image data is corrupt ({error})") from error

    step = COLOUR_CHANNELS[colour] * depth // 8  # bytes per pixel
    stride = width * step
    if len(raw) < height * (stride + 1):
        raise PngError("the image data is cut short")
    previous = bytearray(stride)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        row = _unfilter(raw[start], bytearray(raw[start + 1:start + 1 + stride]), previous, step)
        rows.append(_rgb8(row, step, depth))
        previous = row
    return Image(width, height, tuple(rows))


def _unfilter(kind: int, row: bytearray, previous: bytearray, step: int) -> bytearray:
    if kind == 0:
        return row
    if kind == 1:  # Sub
        for i in range(step, len(row)):
            row[i] = (row[i] + row[i - step]) & 0xFF
    elif kind == 2:  # Up
        return bytearray((a + b) & 0xFF for a, b in zip(row, previous))
    elif kind == 3:  # Average
        for i in range(len(row)):
            left = row[i - step] if i >= step else 0
            row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif kind == 4:  # Paeth
        for i in range(len(row)):
            a = row[i - step] if i >= step else 0
            b = previous[i]
            c = previous[i - step] if i >= step else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
    else:
        raise PngError(f"unknown row filter {kind}")
    return row


def _rgb8(row: bytearray, step: int, depth: int) -> bytes:
    """One row as 8-bit RGB: alpha dropped, 16-bit channels cut to their high byte."""
    if depth == 8 and step == 3:
        return bytes(row)
    size = depth // 8
    out = bytearray()
    for x in range(0, len(row), step):
        out += row[x:x + 3 * size:size]
    return bytes(out)
