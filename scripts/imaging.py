"""Just enough imaging, using nothing but the standard library.

This replaces the slice of Pillow the extractor used so the tool needs no
installed packages at all. It is not a general imaging library; it does exactly
what this project asks of it and no more.

Everything is 8-bit RGBA in a flat bytearray. zlib does the compression, which
is where the time would otherwise go, so this is not the slow pure-Python
approach it might sound like. On the largest thing the extractor decodes, the
768x520 main menu backdrop, decoding and writing through this module takes
0.24s against Pillow's 0.45s, and the PNG lands 12% smaller. Building rows as
bytes beats several hundred thousand putpixel calls.

The public names deliberately mirror the Pillow API that was here before
(Image.new, Image.open, img.crop, ImageDraw.Draw, and so on) so call sites read
the same and the diff stayed reviewable.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Iterable, Iterator, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Resampling:
    NEAREST = "nearest"
    LANCZOS = "area"      # box average; see Image.resize
    BILINEAR = "area"


class Transpose:
    FLIP_TOP_BOTTOM = "flip_top_bottom"
    FLIP_LEFT_RIGHT = "flip_left_right"


class _Channel:
    """One 8-bit band, enough for the alpha inspection the previews do."""

    def __init__(self, values: bytearray, width: int, height: int) -> None:
        self._values = values
        self.width = width
        self.height = height

    def getdata(self) -> bytearray:
        return self._values

    def getbbox(self) -> tuple[int, int, int, int] | None:
        """Tight box around the non-zero values.

        Uses strip/lstrip/rstrip so the scanning happens in C. This runs once
        per extracted tile, and a per-pixel Python loop here was costing more
        than the decode it follows.
        """
        width = self.width
        values = bytes(self._values)
        left, top = width, self.height
        right = bottom = 0
        for y in range(self.height):
            row = values[y * width : (y + 1) * width]
            if not row.strip(b"\x00"):
                continue
            row_left = width - len(row.lstrip(b"\x00"))
            row_right = len(row.rstrip(b"\x00"))
            if row_left < left:
                left = row_left
            if row_right > right:
                right = row_right
            if y < top:
                top = y
            bottom = y + 1
        if right == 0:
            return None
        return (left, top, right, bottom)


class Image:
    """An RGBA raster. Coordinates are (x, y), boxes are (left, top, right, bottom)."""

    Resampling = Resampling
    Transpose = Transpose

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width: int, height: int, pixels: bytearray | None = None) -> None:
        self.width = width
        self.height = height
        self.pixels = pixels if pixels is not None else bytearray(width * height * 4)

    # -- construction ------------------------------------------------------

    @staticmethod
    def new(mode: str, size: tuple[int, int], color: Sequence[int] | None = None) -> "Image":
        width, height = size
        image = Image(width, height)
        if color:
            red, green, blue = color[0], color[1], color[2]
            alpha = color[3] if len(color) > 3 else 255
            if (red, green, blue, alpha) != (0, 0, 0, 0):
                image.pixels[:] = bytes((red, green, blue, alpha)) * (width * height)
        return image

    @staticmethod
    def open(path: Path | str) -> "Image":
        return decode_png(Path(path).read_bytes())

    @staticmethod
    def frombytes(mode: str, size: tuple[int, int], data: bytes, decoder: str = "raw", rawmode: str = "RGB") -> "Image":
        """Only the 15-bit BGR loading-screen format the game actually uses."""
        if rawmode != "BGR;15":
            raise ValueError(f"unsupported raw mode: {rawmode}")
        width, height = size
        image = Image(width, height)
        out = image.pixels
        for index in range(width * height):
            value = data[index * 2] | (data[index * 2 + 1] << 8)
            offset = index * 4
            out[offset] = ((value >> 10) & 0x1F) * 255 // 31
            out[offset + 1] = ((value >> 5) & 0x1F) * 255 // 31
            out[offset + 2] = (value & 0x1F) * 255 // 31
            out[offset + 3] = 255
        return image

    # -- basics ------------------------------------------------------------

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def copy(self) -> "Image":
        return Image(self.width, self.height, bytearray(self.pixels))

    def convert(self, mode: str) -> "Image":
        # Everything is already RGBA; RGB requests still round-trip through
        # RGBA because every consumer here writes PNGs with alpha.
        return self

    def __enter__(self) -> "Image":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def _offset(self, x: int, y: int) -> int:
        return (y * self.width + x) * 4

    def getpixel(self, xy: tuple[int, int]) -> tuple[int, int, int, int]:
        offset = self._offset(*xy)
        return tuple(self.pixels[offset : offset + 4])  # type: ignore[return-value]

    def putpixel(self, xy: tuple[int, int], value: Sequence[int]) -> None:
        x, y = xy
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        offset = self._offset(x, y)
        alpha = value[3] if len(value) > 3 else 255
        self.pixels[offset : offset + 4] = bytes((value[0], value[1], value[2], alpha))

    def getdata(self) -> Iterator[tuple[int, int, int, int]]:
        pixels = self.pixels
        for offset in range(0, len(pixels), 4):
            yield tuple(pixels[offset : offset + 4])  # type: ignore[misc]

    def getchannel(self, band: str) -> _Channel:
        index = {"R": 0, "G": 1, "B": 2, "A": 3}[band]
        return _Channel(bytearray(self.pixels[index::4]), self.width, self.height)

    def tobytes(self) -> bytes:
        return bytes(self.pixels)

    # -- geometry ----------------------------------------------------------

    def getbbox(self) -> tuple[int, int, int, int] | None:
        return self.getchannel("A").getbbox()

    def crop(self, box: tuple[int, int, int, int]) -> "Image":
        left, top, right, bottom = box
        width = max(0, right - left)
        height = max(0, bottom - top)
        out = Image(width, height)
        for y in range(height):
            source_y = top + y
            if not (0 <= source_y < self.height):
                continue
            for x in range(width):
                source_x = left + x
                if not (0 <= source_x < self.width):
                    continue
                source = self._offset(source_x, source_y)
                target = (y * width + x) * 4
                out.pixels[target : target + 4] = self.pixels[source : source + 4]
        return out

    def transpose(self, method: str) -> "Image":
        out = Image(self.width, self.height)
        for y in range(self.height):
            target_y = self.height - 1 - y if method == Transpose.FLIP_TOP_BOTTOM else y
            source = y * self.width * 4
            target = target_y * self.width * 4
            row = self.pixels[source : source + self.width * 4]
            if method == Transpose.FLIP_LEFT_RIGHT:
                row = b"".join(
                    bytes(row[x * 4 : x * 4 + 4]) for x in range(self.width - 1, -1, -1)
                )
            out.pixels[target : target + self.width * 4] = row
        return out

    def resize(self, size: tuple[int, int], resample: str = Resampling.NEAREST) -> "Image":
        """Nearest neighbour, or a box average for downscales.

        Pillow's LANCZOS is only used here to shrink thumbnails on contact
        sheets. A box average over the source region is very slightly softer
        and entirely adequate for that; upscales stay nearest so pixel art
        keeps its edges.
        """
        width, height = max(1, size[0]), max(1, size[1])
        out = Image(width, height)
        shrinking = width < self.width or height < self.height
        if resample == Resampling.NEAREST or not shrinking:
            for y in range(height):
                source_y = min(self.height - 1, y * self.height // height)
                base = source_y * self.width
                for x in range(width):
                    source_x = min(self.width - 1, x * self.width // width)
                    source = (base + source_x) * 4
                    target = (y * width + x) * 4
                    out.pixels[target : target + 4] = self.pixels[source : source + 4]
            return out

        x_edges = [x * self.width // width for x in range(width + 1)]
        y_edges = [y * self.height // height for y in range(height + 1)]
        for y in range(height):
            y0, y1 = y_edges[y], max(y_edges[y] + 1, y_edges[y + 1])
            for x in range(width):
                x0, x1 = x_edges[x], max(x_edges[x] + 1, x_edges[x + 1])
                red = green = blue = alpha = count = 0
                for sy in range(y0, min(y1, self.height)):
                    row = sy * self.width
                    for sx in range(x0, min(x1, self.width)):
                        offset = (row + sx) * 4
                        weight = self.pixels[offset + 3]
                        red += self.pixels[offset] * weight
                        green += self.pixels[offset + 1] * weight
                        blue += self.pixels[offset + 2] * weight
                        alpha += weight
                        count += 1
                target = (y * width + x) * 4
                if alpha:
                    out.pixels[target : target + 4] = bytes(
                        (red // alpha, green // alpha, blue // alpha, alpha // max(1, count))
                    )
        return out

    def thumbnail(self, size: tuple[int, int], resample: str = Resampling.LANCZOS) -> None:
        """Shrink in place to fit inside size, preserving aspect ratio."""
        max_width, max_height = size
        if self.width <= max_width and self.height <= max_height:
            return
        scale = min(max_width / self.width, max_height / self.height)
        resized = self.resize(
            (max(1, int(self.width * scale)), max(1, int(self.height * scale))), resample
        )
        self.width, self.height, self.pixels = resized.width, resized.height, resized.pixels

    # -- compositing -------------------------------------------------------

    def paste(self, other: "Image", box: tuple[int, int] | None = None) -> None:
        """Overwrite, ignoring the source alpha, matching Pillow's 2-arg paste."""
        left, top = box or (0, 0)
        for y in range(other.height):
            target_y = top + y
            if not (0 <= target_y < self.height):
                continue
            width = min(other.width, self.width - left)
            if width <= 0:
                continue
            source = y * other.width * 4
            target = (target_y * self.width + left) * 4
            self.pixels[target : target + width * 4] = other.pixels[source : source + width * 4]

    def alpha_composite(self, other: "Image", dest: tuple[int, int] = (0, 0)) -> None:
        """Source-over blend of other onto this image."""
        left, top = dest
        for y in range(other.height):
            target_y = top + y
            if not (0 <= target_y < self.height):
                continue
            for x in range(other.width):
                target_x = left + x
                if not (0 <= target_x < self.width):
                    continue
                source = (y * other.width + x) * 4
                src_alpha = other.pixels[source + 3]
                if not src_alpha:
                    continue
                target = (target_y * self.width + target_x) * 4
                if src_alpha == 255:
                    self.pixels[target : target + 4] = other.pixels[source : source + 4]
                    continue
                inverse = 255 - src_alpha
                for channel in range(3):
                    self.pixels[target + channel] = (
                        other.pixels[source + channel] * src_alpha
                        + self.pixels[target + channel] * inverse
                    ) // 255
                self.pixels[target + 3] = min(
                    255, src_alpha + self.pixels[target + 3] * inverse // 255
                )

    # -- output ------------------------------------------------------------

    def save(self, path: Path | str, optimize: bool = False) -> None:
        Path(path).write_bytes(encode_png(self, level=9 if optimize else 6))


# ---------------------------------------------------------------- PNG codec


def encode_png(image: Image, level: int = 6) -> bytes:
    """RGBA PNG, filter type 0. zlib carries the cost, in C."""
    stride = image.width * 4
    raw = bytearray((image.height * (stride + 1)))
    source = 0
    target = 0
    for _y in range(image.height):
        raw[target] = 0
        raw[target + 1 : target + 1 + stride] = image.pixels[source : source + stride]
        source += stride
        target += stride + 1

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), level))
        + chunk(b"IEND", b"")
    )


def decode_png(data: bytes) -> Image:
    """Read back a PNG. Supports the 8-bit colour types this tool encounters."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG file")

    width = height = 0
    depth = colour_type = 0
    palette = b""
    transparency = b""
    idat = bytearray()
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        tag = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, depth, colour_type = struct.unpack_from(">IIBB", payload, 0)
            interlace = payload[12]
            if interlace:
                raise ValueError("interlaced PNG is not supported")
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"tRNS":
            transparency = payload
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break

    if depth != 8:
        raise ValueError(f"unsupported PNG bit depth: {depth}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise ValueError(f"unsupported PNG colour type: {colour_type}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = Image(width, height)
    previous = bytearray(stride)
    position = 0
    for y in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride
        _unfilter_row(filter_type, line, previous, channels)
        _expand_row(line, out.pixels, y * width * 4, width, colour_type, palette, transparency)
        previous = line
    return out


def _unfilter_row(filter_type: int, line: bytearray, previous: bytearray, channels: int) -> None:
    if filter_type == 0:
        return
    for index in range(len(line)):
        left = line[index - channels] if index >= channels else 0
        up = previous[index]
        if filter_type == 1:
            line[index] = (line[index] + left) & 0xFF
        elif filter_type == 2:
            line[index] = (line[index] + up) & 0xFF
        elif filter_type == 3:
            line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:
            upper_left = previous[index - channels] if index >= channels else 0
            estimate = left + up - upper_left
            distance_left = abs(estimate - left)
            distance_up = abs(estimate - up)
            distance_upper_left = abs(estimate - upper_left)
            if distance_left <= distance_up and distance_left <= distance_upper_left:
                predictor = left
            elif distance_up <= distance_upper_left:
                predictor = up
            else:
                predictor = upper_left
            line[index] = (line[index] + predictor) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter: {filter_type}")


def _expand_row(
    line: bytearray,
    out: bytearray,
    target: int,
    width: int,
    colour_type: int,
    palette: bytes,
    transparency: bytes,
) -> None:
    if colour_type == 6:
        out[target : target + width * 4] = line
        return
    for x in range(width):
        offset = target + x * 4
        if colour_type == 2:
            out[offset : offset + 3] = line[x * 3 : x * 3 + 3]
            out[offset + 3] = 255
        elif colour_type == 0:
            value = line[x]
            out[offset : offset + 4] = bytes((value, value, value, 255))
        elif colour_type == 4:
            value = line[x * 2]
            out[offset : offset + 4] = bytes((value, value, value, line[x * 2 + 1]))
        else:  # colour_type == 3, palette
            index = line[x]
            out[offset : offset + 3] = palette[index * 3 : index * 3 + 3]
            out[offset + 3] = transparency[index] if index < len(transparency) else 255


# ------------------------------------------------------------------ drawing

# A 5x7 bitmap face covering the characters the preview labels use. Each glyph
# is five column bytes, low bit at the top. Shipping this beats depending on a
# font file that may not exist on the machine.
_GLYPHS = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00), "!": (0x00, 0x00, 0x5F, 0x00, 0x00),
    "-": (0x08, 0x08, 0x08, 0x08, 0x08), ".": (0x00, 0x60, 0x60, 0x00, 0x00),
    "/": (0x20, 0x10, 0x08, 0x04, 0x02), ":": (0x00, 0x36, 0x36, 0x00, 0x00),
    "_": (0x40, 0x40, 0x40, 0x40, 0x40), "#": (0x14, 0x7F, 0x14, 0x7F, 0x14),
    "(": (0x00, 0x1C, 0x22, 0x41, 0x00), ")": (0x00, 0x41, 0x22, 0x1C, 0x00),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E), "1": (0x00, 0x42, 0x7F, 0x40, 0x00),
    "2": (0x42, 0x61, 0x51, 0x49, 0x46), "3": (0x21, 0x41, 0x45, 0x4B, 0x31),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10), "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30), "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36), "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    "A": (0x7E, 0x11, 0x11, 0x11, 0x7E), "B": (0x7F, 0x49, 0x49, 0x49, 0x36),
    "C": (0x3E, 0x41, 0x41, 0x41, 0x22), "D": (0x7F, 0x41, 0x41, 0x22, 0x1C),
    "E": (0x7F, 0x49, 0x49, 0x49, 0x41), "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A), "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
    "I": (0x00, 0x41, 0x7F, 0x41, 0x00), "J": (0x20, 0x40, 0x41, 0x3F, 0x01),
    "K": (0x7F, 0x08, 0x14, 0x22, 0x41), "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F), "N": (0x7F, 0x04, 0x08, 0x10, 0x7F),
    "O": (0x3E, 0x41, 0x41, 0x41, 0x3E), "P": (0x7F, 0x09, 0x09, 0x09, 0x06),
    "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E), "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31), "T": (0x01, 0x01, 0x7F, 0x01, 0x01),
    "U": (0x3F, 0x40, 0x40, 0x40, 0x3F), "V": (0x1F, 0x20, 0x40, 0x20, 0x1F),
    "W": (0x3F, 0x40, 0x38, 0x40, 0x3F), "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07), "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "a": (0x20, 0x54, 0x54, 0x54, 0x78), "b": (0x7F, 0x48, 0x44, 0x44, 0x38),
    "c": (0x38, 0x44, 0x44, 0x44, 0x20), "d": (0x38, 0x44, 0x44, 0x48, 0x7F),
    "e": (0x38, 0x54, 0x54, 0x54, 0x18), "f": (0x08, 0x7E, 0x09, 0x01, 0x02),
    "g": (0x0C, 0x52, 0x52, 0x52, 0x3E), "h": (0x7F, 0x08, 0x04, 0x04, 0x78),
    "i": (0x00, 0x44, 0x7D, 0x40, 0x00), "j": (0x20, 0x40, 0x44, 0x3D, 0x00),
    "k": (0x7F, 0x10, 0x28, 0x44, 0x00), "l": (0x00, 0x41, 0x7F, 0x40, 0x00),
    "m": (0x7C, 0x04, 0x18, 0x04, 0x78), "n": (0x7C, 0x08, 0x04, 0x04, 0x78),
    "o": (0x38, 0x44, 0x44, 0x44, 0x38), "p": (0x7C, 0x14, 0x14, 0x14, 0x08),
    "q": (0x08, 0x14, 0x14, 0x18, 0x7C), "r": (0x7C, 0x08, 0x04, 0x04, 0x08),
    "s": (0x48, 0x54, 0x54, 0x54, 0x20), "t": (0x04, 0x3F, 0x44, 0x40, 0x20),
    "u": (0x3C, 0x40, 0x40, 0x20, 0x7C), "v": (0x1C, 0x20, 0x40, 0x20, 0x1C),
    "w": (0x3C, 0x40, 0x30, 0x40, 0x3C), "x": (0x44, 0x28, 0x10, 0x28, 0x44),
    "y": (0x0C, 0x50, 0x50, 0x50, 0x3C), "z": (0x44, 0x64, 0x54, 0x4C, 0x44),
}
_FALLBACK_GLYPH = (0x7F, 0x41, 0x41, 0x41, 0x7F)

GLYPH_WIDTH = 5
GLYPH_HEIGHT = 7
GLYPH_ADVANCE = 6


class _Draw:
    def __init__(self, image: Image) -> None:
        self.image = image

    def text(self, xy: tuple[int, int], text: str, fill: Sequence[int] = (255, 255, 255, 255), **_kw: object) -> None:
        x, y = xy
        colour = tuple(fill[:3]) + (fill[3] if len(fill) > 3 else 255,)
        for character in text:
            glyph = _GLYPHS.get(character, _FALLBACK_GLYPH)
            for column, bits in enumerate(glyph):
                for row in range(GLYPH_HEIGHT):
                    if bits >> row & 1:
                        self.image.putpixel((x + column, y + row), colour)
            x += GLYPH_ADVANCE

    def rectangle(self, box: Sequence[int], fill: Sequence[int] | None = None, outline: Sequence[int] | None = None, **_kw: object) -> None:
        left, top, right, bottom = (int(value) for value in box)
        if fill:
            colour = tuple(fill[:3]) + (fill[3] if len(fill) > 3 else 255,)
            for y in range(top, bottom + 1):
                for x in range(left, right + 1):
                    self.image.putpixel((x, y), colour)
        if outline:
            colour = tuple(outline[:3]) + (outline[3] if len(outline) > 3 else 255,)
            for x in range(left, right + 1):
                self.image.putpixel((x, top), colour)
                self.image.putpixel((x, bottom), colour)
            for y in range(top, bottom + 1):
                self.image.putpixel((left, y), colour)
                self.image.putpixel((right, y), colour)

    def line(self, box: Sequence[int], fill: Sequence[int] = (255, 255, 255, 255), width: int = 1, **_kw: object) -> None:
        x0, y0, x1, y1 = (int(value) for value in box)
        colour = tuple(fill[:3]) + (fill[3] if len(fill) > 3 else 255,)
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            x = x0 + (x1 - x0) * step // steps
            y = y0 + (y1 - y0) * step // steps
            for offset in range(width):
                self.image.putpixel((x, y + offset), colour)


class ImageDraw:
    @staticmethod
    def Draw(image: Image) -> _Draw:  # noqa: N802 -- mirrors the Pillow name
        return _Draw(image)


def text_width(text: str) -> int:
    return max(0, len(text) * GLYPH_ADVANCE - 1)


def image_from_rgba_rows(width: int, height: int, rows: Iterable[bytes]) -> Image:
    """Build an image from prepared RGBA scanlines."""
    image = Image(width, height)
    stride = width * 4
    offset = 0
    for row in rows:
        image.pixels[offset : offset + stride] = row
        offset += stride
    return image
