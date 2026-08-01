"""TILE v3 encode helpers (exclusive-end X) for AI re-art import."""

from __future__ import annotations

import struct

from PIL import Image


def is_transparent_color(r: int, g: int, b: int) -> bool:
    return r > 150 and g < 80 and b > 150 and abs(r - b) < 60


def encode_tile_v3(
    pixel_indices: list[list[int]] | object,
    palette_id: int,
    *,
    header_w2: int = 0,
    header_w3: int = 0,
    header_w4: int = 32,
    header_w5: int = 0,
    header_w6: int = 0,
    header_w7: int = 1,
) -> bytes:
    """
    Encode a (height, width) grid of palette indices into TILE v3 bytes.
    On-disk X is exclusive end: x_end = start + count.
    """
    pixels = [[int(value) & 0xFF for value in row] for row in pixel_indices]
    height = len(pixels)
    width = max((len(row) for row in pixels), default=0)
    if height <= 0 or width <= 0:
        raise ValueError("Cannot encode an empty TILE v3 image")
    for row in pixels:
        if len(row) != width:
            raise ValueError("Cannot encode ragged TILE v3 rows")
    if header_w2 <= 0:
        header_w2 = width

    row_blobs: list[bytes] = []
    for y in range(height):
        row_blobs.append(_encode_row(pixels[y]))

    table_size = height * 4
    offsets: list[int] = []
    current = table_size
    for blob in row_blobs:
        offsets.append(current)
        current += len(blob)

    header = struct.pack(
        "<HHHHHHHH",
        3,
        height,
        header_w2,
        header_w3,
        header_w4,
        header_w5,
        header_w6,
        header_w7,
    )
    padding = b"\x00" * 6
    pal = struct.pack("<I", palette_id)
    offset_table = b"".join(struct.pack("<I", o) for o in offsets)
    return header + padding + pal + offset_table + b"".join(row_blobs)


def _encode_row(row) -> bytes:
    segments: list[tuple[int, list[int]]] = []
    width = len(row)
    x = 0
    while x < width:
        if row[x] == 0:
            x += 1
            continue
        x_start = x
        run: list[int] = []
        while x < width and row[x] != 0 and len(run) < 80:
            run.append(int(row[x]))
            x += 1
        segments.append((x_start, run))

    if not segments:
        return struct.pack("<HBB", 0, 0, 0x80)

    parts: list[bytes] = []
    for i, (x_start, pixels) in enumerate(segments):
        flags = 0x80 if i == len(segments) - 1 else 0x00
        count = len(pixels)
        x_end = x_start + count
        parts.append(struct.pack("<HBB", x_end, count, flags) + bytes(pixels))
    return b"".join(parts)


def quantize_rgba_to_palette(
    image: Image.Image,
    palette: list[tuple[int, int, int]],
    *,
    preserve_shadow_indices: bool = True,
) -> list[list[int]]:
    """Quantize RGBA image to palette indices. Alpha < 128 → 0."""
    img = image.convert("RGBA")
    width, height = img.size
    transparent = {0}
    for i, (r, g, b) in enumerate(palette):
        if is_transparent_color(r, g, b):
            transparent.add(i)
        if not preserve_shadow_indices and 247 <= i <= 250:
            transparent.add(i)

    result: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            r, g, b, a = img.getpixel((x, y))
            if a < 128:
                row.append(0)
                continue
            best_idx = 1
            best_dist = 1 << 30
            for i in range(256):
                if i in transparent:
                    continue
                pr, pg, pb = palette[i]
                dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            row.append(best_idx)
        result.append(row)
    return result


def render_tile_full(
    tile_data: bytes,
    palette: list[tuple[int, int, int]] | None,
    *,
    drop_shadow: bool = True,
) -> Image.Image | None:
    """Render TILE v3 to full canvas (no bbox crop)."""
    from extract_assets import decode_tile_v3

    decoded = decode_tile_v3(tile_data)
    if decoded is None:
        return None
    width = int(decoded["width"])
    height = int(decoded["height"])
    if width <= 0 or height <= 0:
        return None
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y, segments in enumerate(decoded["rows"]):
        for x_start, pixels in segments:
            for dx, index in enumerate(pixels):
                x = int(x_start) + dx
                if x < 0 or x >= width:
                    continue
                if palette is None:
                    image.putpixel((x, y), (index, index, index, 255))
                    continue
                r, g, b = palette[index]
                if drop_shadow and 247 <= index <= 250:
                    continue
                if drop_shadow and is_transparent_color(r, g, b):
                    continue
                image.putpixel((x, y), (r, g, b, 255))
    return image


def header_words(tile_data: bytes) -> dict[str, int]:
    from extract_assets import u16, u32

    return {
        "height": u16(tile_data, 2),
        "width": u16(tile_data, 4),
        "w3": u16(tile_data, 6),
        "w4": u16(tile_data, 8),
        "w5": u16(tile_data, 10),
        "w6": u16(tile_data, 12),
        "w7": u16(tile_data, 14),
        "palette_id": u32(tile_data, 22),
    }
