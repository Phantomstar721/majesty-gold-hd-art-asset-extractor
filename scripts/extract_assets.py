from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from enum import Enum

import ffmpeg_support
from imaging import Image, ImageDraw


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Majesty HD")
DEFAULT_OUT = TOOL_ROOT / "output" / "assets"


class ExtractionMode(str, Enum):
    """User-facing extraction presets."""

    ALL_RAW = "all-raw"
    RELEVANT_RAW = "relevant-raw"
    RELEVANT_ART = "relevant-art"

    @property
    def exhaustive(self) -> bool:
        return self is ExtractionMode.ALL_RAW

    @property
    def clean_art(self) -> bool:
        return self is ExtractionMode.RELEVANT_ART


MODE_LABELS = {
    ExtractionMode.ALL_RAW: "All raw content",
    ExtractionMode.RELEVANT_RAW: "Relevant sprites and menu art (raw)",
    ExtractionMode.RELEVANT_ART: "Relevant art (clean PNGs)",
}

MAGIC = b"CYLBPC  \x01\x00\x01\x00"
ANIM_HEADER_SIZE = 0x14
IMAGE_SET_ENTRY_SIZE = 8
DIR_HEADER_SIZE = 0x30
DIR_GEOMETRY_OFF = 0x14
N_DIRECTION_SLOTS = 8

IMAGE_SET_NAMES = {
    1: "Walk",
    2: "Walk-2",
    3: "Walk-3",
    4: "Walk-4",
    8: "Stand",
    16: "Attack",
    17: "Attack-2",
    18: "Attack-3",
    19: "Attack-4",
    64: "Special",
    65: "Special-2",
    66: "Special-3",
    67: "Special-4",
    80: "Build",
    81: "Build-2",
    82: "Build-3",
    83: "Build-4",
    96: "Die",
    97: "Die-2",
    98: "Die-3",
    99: "Die-4",
    100: "Die-5",
    101: "Die-6",
    102: "Die-7",
    103: "Die-8",
    128: "Cast",
    129: "Cast-2",
    130: "Cast-3",
    131: "Cast-4",
    144: "Carry",
    145: "Carry-2",
    146: "Carry-3",
    147: "Carry-4",
    160: "Recoil",
    161: "Recoil-2",
    162: "Recoil-3",
    163: "Recoil-4",
    176: "Stand-to-Walk",
    177: "Walk-to-Stand",
    178: "Turn-Right",
    179: "Turn-Left",
    192: "Active",
    193: "Active-2",
    194: "Active-3",
    195: "Active-4",
    208: "Inactive",
    209: "Inactive-2",
    210: "Inactive-3",
    211: "Inactive-4",
    224: "Dead",
    240: "Crumble",
    256: "High-Power-Active",
    257: "High-Power-Idle",
    272: "Low-Power-Active",
    273: "Low-Power-Idle",
    288: "Unpowered",
    300: "Minimap",
    316: "Damage",
    332: "Assimilate",
    400: "Hotspot",
    500: "Selection-Underlay",
    550: "Selection-Overlay",
    1000: "Interface",
    1001: "Interface-01",
    1002: "Interface-02",
    2000: "Particle-Birth",
    2100: "Particle-Midlife",
    2200: "Particle-Death",
    4000: "UnitTexture",
}

CURATED_INTERFACE_RECORDS = {
    "INBw": "icons/weapons",
    "INBa": "icons/armor",
    "INTC": "icons/items",
    "INTn": "icons/spells",
    "IX92": "icons/monsters",
    "IX94": "icons/monsters",
    "IX93": "icons/items",
    # Main menus, option/score/name screens, and quest selection chrome.
    "DEM2": "menus",
    "INDa": "menus/options",
    "INDh": "menus/high-scores",
    "INDk": "menus/options",
    "INDm": "menus/main",
    "INDn": "menus/quest",
    "INDp": "menus/options",
    "INDq": "menus/options",
    "INDz": "menus/main",
    "INFs": "menus/freestyle",
    "INkm": "menus/main",
    "IX22": "menus/main",
    "IX33": "menus/quest",
    "IX34": "menus/quest",
    "IX50": "menus/main",
    "IX51": "menus/main",
    "DX31": "menus/quest",
    "IXD1": "menus/quest",
    # Quest-map chrome and map backgrounds/stretch layers.
    "INQc": "maps/interface",
    "INQd": "maps/interface",
    "INx2": "maps/interface",
    "IX10": "maps/interface",
    # Pre-quest, close-up, downloadable, and expansion segue art.
    "DXS0": "segues",
    "INDb": "segues",
    "INDg": "segues",
    "INPq": "segues",
    "INse": "segues",
    "INTM": "segues",
    "INTP": "segues",
    "IX72": "segues",
    "IX73": "segues",
    "IX78": "segues",
    "IXR1": "segues",
    "IXS1": "segues",
    "MX29": "segues",
    # Loading screens and their presentation layers.
    "INDl": "loading_screens/interface",
    "INDo": "loading_screens/interface",
    # Miscellaneous full-screen interface backing used by the menus.
    "INx1": "menus/interface",
}

MAIN_CAM_SOURCES = [
    ("base", Path("Data/maindata.cam")),
    ("expansion", Path("DataMX/mx_maindata.cam")),
]

INTERFACE_CAM_SOURCES = [
    ("base_interface", Path("Data/interfacedata.cam")),
    ("download_interface", Path("Data/addinterface.cam")),
    ("widescreen_interface", Path("Data/addinterface_se.cam")),
    ("expansion_interface", Path("DataMX/mx_interfacedata.cam")),
    ("downloadable_quest_interface", Path("DataMX/XQD1_intro.cam")),
]

PICTURE_CAM_SOURCES = [
    # cinedata1 contains the base intro and QM00-QM18 quest-map/segue movies.
    ("base_presentation", Path("Data/cinedata1.cam")),
    # cinedata3 is the higher-resolution variant of base movies/loading art.
    ("base_presentation_hd", Path("Data/cinedata3.dat")),
    # Expansion maps/segues, movie, and loading screen.
    ("expansion_presentation", Path("DataMX/mx_cinedata1.cam")),
    ("expansion_presentation_hd", Path("DataMX/mx_cinedata3.dat")),
]

PRESENTATION_SAMPLE_FRAMES = 12

KNOWN_BUILDING_SET_IDS = {
    80,
    81,
    82,
    83,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
    103,
    192,
    193,
    194,
    195,
    208,
    209,
    210,
    211,
    224,
    240,
    400,
    1000,
    1002,
}


@dataclass(frozen=True)
class CamEntry:
    name: bytes
    data: bytes
    data_offset: int

    @property
    def display_name(self) -> str:
        return self.name.rstrip(b"\x00").decode("ascii", errors="replace")


@dataclass(frozen=True)
class CamSection:
    extension: str
    entries: tuple[CamEntry, ...]


@dataclass(frozen=True)
class CamArchive:
    sections: tuple[CamSection, ...]


@dataclass(frozen=True)
class CatalogEntry:
    category: str
    source_xml: str
    unit_id: str
    image_id: str
    name: str
    description: str


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def read_cam(path: Path) -> CamArchive:
    data = path.read_bytes()
    if data[: len(MAGIC)] != MAGIC:
        raise ValueError(f"{path} is not a Majesty CAM archive")

    cursor = len(MAGIC)
    section_count = u32(data, cursor)
    cursor += 4
    content_header_length = u32(data, cursor)
    cursor += 4

    extensions: list[str] = []
    section_offsets: list[int] = []
    for _ in range(section_count):
        extensions.append(data[cursor : cursor + 4].decode("ascii", errors="replace").rstrip())
        cursor += 4
        section_offsets.append(u32(data, cursor))
        cursor += 4

    content_header_start = cursor
    content_header_end = content_header_start + content_header_length
    sections_meta: list[list[tuple[bytes, int, int]]] = []

    for section_index in range(section_count):
        if cursor != section_offsets[section_index]:
            raise ValueError(f"{path} section {section_index} header offset mismatch")
        file_count = u32(data, cursor)
        cursor += 8
        entries: list[tuple[bytes, int, int]] = []
        for _ in range(file_count):
            name = data[cursor : cursor + 20]
            cursor += 20
            data_offset = u32(data, cursor)
            cursor += 4
            data_size = u32(data, cursor)
            cursor += 4
            entries.append((name, data_offset, data_size))
        sections_meta.append(entries)

    if cursor != content_header_end:
        raise ValueError(f"{path} content header length mismatch")

    sections: list[CamSection] = []
    for extension, entries_meta in zip(extensions, sections_meta):
        entries = tuple(
            CamEntry(
                name=name,
                data=data[data_offset : data_offset + data_size],
                data_offset=data_offset,
            )
            for name, data_offset, data_size in entries_meta
        )
        sections.append(CamSection(extension=extension, entries=entries))

    return CamArchive(tuple(sections))


def parse_catalog(game: Path) -> dict[str, CatalogEntry]:
    catalog: dict[str, CatalogEntry] = {}
    sources = [
        ("Data/M_Characters.xml", "characters"),
        ("DataMX/MX_Characters.xml", "characters"),
        ("Data/M_Buildings.xml", "buildings"),
        ("DataMX/MX_Buildings.xml", "buildings"),
        ("Data/M_Overlays.xml", "overlays"),
        ("DataMX/MX_Overlays.xml", "overlays"),
    ]
    root = game / "SDK" / "OriginalQuests"

    for rel, kind in sources:
        path = root / rel
        if not path.exists():
            continue
        tree = ET.parse(path)
        for desc in tree.findall(".//Description"):
            image = desc.find(".//ImageIDBase")
            if image is None or "value" not in image.attrib:
                continue
            image_id = image.attrib["value"]
            can_use = {node.attrib.get("value", "") for node in desc.findall(".//CanUse")}
            name = desc.attrib.get("Name", image_id)
            description = desc.attrib.get("Description", name)
            category = classify_xml(kind, image_id, can_use, name)
            catalog[image_id] = CatalogEntry(
                category=category,
                source_xml=rel,
                unit_id=desc.attrib.get("ID", ""),
                image_id=image_id,
                name=name,
                description=description,
            )
    return catalog


def classify_xml(kind: str, image_id: str, can_use: set[str], name: str) -> str:
    if kind == "characters":
        if "Monster" in can_use or image_id.startswith("BV"):
            return "monsters/sprites"
        if image_id.startswith("AV"):
            return "heroes/sprites"
        return "spell_effects"
    if kind == "buildings":
        if "Monster" in can_use or image_id.startswith("BB"):
            return "buildings/lairs"
        return "buildings/sprites"
    if kind == "overlays":
        lower = name.lower()
        if "icon" in lower:
            return "icons/spells"
        return "spell_effects"
    return "uncategorized"


def classify_imag_record(record_name: str, catalog: dict[str, CatalogEntry], full: bool) -> tuple[str, CatalogEntry | None] | None:
    image_id = record_name[:4]
    if image_id in catalog:
        return catalog[image_id].category, catalog[image_id]

    if image_id.startswith("AV"):
        return "heroes/sprites", None
    if image_id.startswith("BV"):
        return "monsters/sprites", None
    if image_id.startswith("AB"):
        return "buildings/sprites", None
    if image_id.startswith("BB"):
        return "buildings/lairs", None
    if image_id[:2] in {"XR", "WR", "CR", "DR", "HR", "MR", "NR", "PR", "QR", "SR", "TR", "LR"}:
        return "spell_effects", None
    if is_loose_spell_effect_record(record_name):
        return "spell_effects", None
    if full:
        return "other/main", None
    return None


def is_loose_spell_effect_record(record_name: str) -> bool:
    image_id = record_name[:4]
    prefix = image_id[:2].upper()
    if prefix == "WP":
        return True
    if prefix != "XL":
        return False
    lower = record_name.lower()
    spell_terms = {
        "adept",
        "blast",
        "breath",
        "chain",
        "earthquake",
        "effect",
        "effct",
        "farseeing",
        "fire",
        "flame",
        "flamming",
        "frost",
        "heal",
        "horrify",
        "meteor",
        "miss",
        "part",
        "placehold_spell",
        "power",
        "project",
        "shock",
        "smoke",
        "spell",
        "storm",
        "teleport",
        "terrify",
        "tower",
        "wind",
        "wiz",
    }
    return any(term in lower for term in spell_terms)


def parse_anim_set(blob: bytes) -> list[tuple[int, str, int]]:
    if len(blob) < ANIM_HEADER_SIZE + 4:
        return []
    entry_count = u32(blob, ANIM_HEADER_SIZE)
    if entry_count <= 0 or entry_count > 256:
        return []
    pos = ANIM_HEADER_SIZE + 4
    sets: list[tuple[int, str, int]] = []
    for _ in range(entry_count):
        if pos + IMAGE_SET_ENTRY_SIZE > len(blob):
            return []
        set_id = u32(blob, pos)
        rel_off = u32(blob, pos + 4)
        if rel_off >= len(blob):
            return []
        normalized_set_id = image_set_base_id(set_id)
        if set_id in IMAGE_SET_NAMES:
            set_name = IMAGE_SET_NAMES[set_id]
        elif normalized_set_id in IMAGE_SET_NAMES:
            set_name = f"{IMAGE_SET_NAMES[normalized_set_id]}-{set_id >> 16}"
        else:
            set_name = f"set-{set_id}"
        sets.append((set_id, set_name, rel_off))
        pos += IMAGE_SET_ENTRY_SIZE
    return sets


def image_set_base_id(set_id: int) -> int:
    base_id = set_id & 0xFFFF
    return base_id if base_id else set_id


def parse_directional_frame_descriptor(blob: bytes, rel_off: int) -> list[dict[str, object]]:
    if rel_off + 0x38 + (N_DIRECTION_SLOTS * 4) > len(blob):
        return []

    raw_offsets = [i32(blob, rel_off + 0x38 + slot * 4) for slot in range(N_DIRECTION_SLOTS)]
    populated = [(slot, offset) for slot, offset in enumerate(raw_offsets) if offset > 0]
    directions: list[dict[str, object]] = []

    for idx, (slot, dir_rel) in enumerate(populated):
        dir_off = rel_off + dir_rel
        if dir_off + DIR_GEOMETRY_OFF + 8 > len(blob):
            continue
        x_off = i16(blob, dir_off + DIR_GEOMETRY_OFF)
        y_off = i16(blob, dir_off + DIR_GEOMETRY_OFF + 2)
        width = u16(blob, dir_off + DIR_GEOMETRY_OFF + 4)
        height = u16(blob, dir_off + DIR_GEOMETRY_OFF + 6)

        if idx + 1 < len(populated):
            next_dir_off = rel_off + populated[idx + 1][1]
            frame_count = (next_dir_off - dir_off - DIR_HEADER_SIZE) // 8
        else:
            frame_count = 0
            for frame in range(128):
                pair_off = dir_off + DIR_HEADER_SIZE + frame * 8
                if pair_off + 8 > len(blob):
                    break
                flag = u32(blob, pair_off)
                tile_idx = u32(blob, pair_off + 4)
                if flag == 0 and 0 < tile_idx < 500000:
                    frame_count += 1
                    continue
                break

        if frame_count <= 0 or frame_count > 128:
            continue

        tile_indices: list[int] = []
        for frame in range(frame_count):
            pair_off = dir_off + DIR_HEADER_SIZE + frame * 8
            if pair_off + 8 > len(blob):
                break
            tile_indices.append(u32(blob, pair_off + 4))

        directions.append(
            {
                "slot": slot,
                "x_off": x_off,
                "y_off": y_off,
                "width": width,
                "height": height,
                "tile_indices": tile_indices,
            }
        )

    return directions


def decode_tile_v3(tile_data: bytes, pixel_size: int | None = None) -> dict[str, object] | None:
    """Decode indexed or RGB565 TILE v3 RLE.

    The packed run word uses 11 low bits for count and upper bits for flags;
    bit 15 ends the row. On-disk X is the exclusive end column.
    """
    if len(tile_data) < 26 or u16(tile_data, 0) != 3:
        return None
    height = u16(tile_data, 2)
    header_width = u16(tile_data, 4)
    palette_id = u32(tile_data, 22)
    offset_base = 26
    if height <= 0 or offset_base + height * 4 > len(tile_data):
        return None

    offsets = [u32(tile_data, offset_base + row * 4) for row in range(height)]
    palette_mode = u16(tile_data, 20)
    data_end = palette_id if palette_mode == 1 and offset_base < palette_id <= len(tile_data) else len(tile_data)

    def parse_rows(bytes_per_pixel: int) -> tuple[list[list[tuple[int, list[int]]]], int] | None:
        parsed_rows: list[list[tuple[int, list[int]]]] = []
        max_end = 0
        for row in range(height):
            start = offset_base + offsets[row]
            end = offset_base + offsets[row + 1] if row + 1 < height else data_end
            if start < offset_base or start > end or end > data_end:
                return None
            row_data = tile_data[start:end]
            segments: list[tuple[int, list[int]]] = []
            pos = 0
            ended = False
            while pos + 4 <= len(row_data):
                x_end = u16(row_data, pos)
                count_flags = u16(row_data, pos + 2)
                count = count_flags & 0x07FF
                pos += 4
                payload_size = count * bytes_per_pixel
                if count > x_end or (header_width > 0 and x_end > header_width) or pos + payload_size > len(row_data):
                    return None
                payload = row_data[pos : pos + payload_size]
                pos += payload_size
                if bytes_per_pixel == 1:
                    pixels = list(payload)
                else:
                    pixels = [u16(payload, index * 2) for index in range(count)]
                if count:
                    segments.append((x_end - count, pixels))
                    max_end = max(max_end, x_end)
                if count_flags & 0x8000:
                    ended = True
                    break
            if not ended or pos != len(row_data):
                return None
            parsed_rows.append(segments)
        return parsed_rows, max_end

    candidates = [pixel_size] if pixel_size in {1, 2} else [1, 2]
    parsed = None
    chosen_pixel_size = 0
    for candidate_size in candidates:
        parsed = parse_rows(candidate_size)
        if parsed is not None:
            chosen_pixel_size = candidate_size
            break
    if parsed is None:
        return None
    rows, max_end = parsed
    width = header_width if header_width > 0 else max_end
    return {
        "width": width,
        "height": height,
        "palette_id": palette_id,
        "pixel_size": chosen_pixel_size,
        "rows": rows,
    }


def load_palette(palette_section: CamSection, palette_id: int) -> list[tuple[int, int, int]] | None:
    if palette_id < 0 or palette_id >= len(palette_section.entries):
        return None
    data = palette_section.entries[palette_id].data
    if len(data) != 1032:
        return None
    return load_embedded_palette(data, 0)


def load_embedded_palette(data: bytes, offset: int) -> list[tuple[int, int, int]] | None:
    if offset < 0 or offset + 1032 > len(data):
        return None
    return [(data[offset + 8 + i * 4], data[offset + 9 + i * 4], data[offset + 10 + i * 4]) for i in range(256)]


def is_palette_key_color(index: int, red: int, green: int, blue: int) -> bool:
    """Return True for engine control pixels that should not appear in clean art.

    Phantom's Haunt confirmed that 247 is the transition/seam control and
    248-250 are shadow bands. Indices 251-254 are not universally reserved:
    some building palettes use them for ordinary highlights, while other
    palettes put magenta control ramps there.
    """
    if 247 <= index <= 250:
        return True
    if red > 150 and green < 80 and blue > 150 and abs(red - blue) < 60:
        return True
    return green == 0 and red == blue and 120 <= red <= 140


def edge_connected_index_offsets(
    pixels: bytes,
    width: int,
    height: int,
    row_stride: int,
    index: int,
) -> set[int]:
    """Return pixels of one index connected to the image boundary.

    Indexed interface art sometimes reuses its nominal transparent index for
    real colors inside the image. Only the connected exterior region is true
    transparency; enclosed components are palette-index collisions.
    """
    pending: list[tuple[int, int]] = []
    for x in range(width):
        if pixels[x] == index:
            pending.append((x, 0))
        bottom = (height - 1) * row_stride + x
        if height > 1 and pixels[bottom] == index:
            pending.append((x, height - 1))
    for y in range(1, height - 1):
        left = y * row_stride
        if pixels[left] == index:
            pending.append((0, y))
        right = left + width - 1
        if width > 1 and pixels[right] == index:
            pending.append((width - 1, y))

    connected: set[int] = set()
    while pending:
        x, y = pending.pop()
        offset = y * row_stride + x
        if offset in connected or pixels[offset] != index:
            continue
        connected.add(offset)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < width and 0 <= ny < height:
                    pending.append((nx, ny))
    return connected


def tile_v1_to_image(
    tile_data: bytes,
    palette_section: CamSection | None,
    *,
    clean_art: bool = True,
    preserve_full_palette: bool = False,
    force_opaque_palette: bool = False,
    recover_enclosed_transparency: bool = False,
) -> Image.Image | None:
    if len(tile_data) < 26 or u16(tile_data, 0) != 1:
        return None

    height = u16(tile_data, 2)
    width = u16(tile_data, 4)
    row_stride = u16(tile_data, 6)
    transparent_index = u16(tile_data, 16) & 0xFF
    palette_mode = u16(tile_data, 20)
    palette_value = u32(tile_data, 22)

    if width <= 0 or height <= 0:
        return None
    if row_stride == width * 2 and 26 + height * row_stride <= len(tile_data):
        # Full-background art keeps its black. Sprite-shaped art continues to
        # read 0x0000 as the cutout, which is what gives it a silhouette.
        return tile_v1_rgb565_to_image(
            tile_data,
            width,
            height,
            row_stride,
            black_is_transparent=not preserve_full_palette,
        )
    pixel_count = row_stride * height
    if row_stride < width or 26 + pixel_count > len(tile_data):
        return None

    if palette_mode == 1:
        palette = load_embedded_palette(tile_data, palette_value)
    elif palette_section is not None:
        palette = load_palette(palette_section, palette_value)
    else:
        palette = None
    if palette is None:
        return None

    pixels = tile_data[26 : 26 + pixel_count]
    transparent_offsets: set[int] | None = None
    if force_opaque_palette:
        transparent_offsets = set()
    elif preserve_full_palette and recover_enclosed_transparency:
        transparent_offsets = edge_connected_index_offsets(
            pixels, width, height, row_stride, transparent_index
        )
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # Written straight into the buffer. These loops run over every pixel of
    # every tile in the game, and a per-pixel method call is the difference
    # between a fast extraction and a slow one.
    out = image.pixels
    for y in range(height):
        row = y * row_stride
        target = y * width * 4
        for x in range(width):
            pixel_offset = row + x
            index = pixels[pixel_offset]
            if index == transparent_index and (
                transparent_offsets is None or pixel_offset in transparent_offsets
            ):
                continue
            red, green, blue = palette[index]
            if clean_art and is_palette_key_color(index, red, green, blue):
                continue
            offset = target + x * 4
            out[offset] = red
            out[offset + 1] = green
            out[offset + 2] = blue
            out[offset + 3] = 255
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_v1_rgb565_to_image(
    tile_data: bytes,
    width: int,
    height: int,
    row_stride: int,
    *,
    black_is_transparent: bool = True,
) -> Image.Image | None:
    """Decode a 16-bit RGB565 version 1 TILE.

    RGB565 has no alpha channel and no transparent-index field, so 0x0000 has
    to serve double duty: it is both pure black and the only value a sprite can
    use for its cutout. Which one it means depends on the art.

    For full-screen backgrounds it means black, and dropping it punches holes
    through the artwork. The main menu backdrop stores 17,801 such pixels, and
    treating them as transparent removed 4.5% of the image, while the 28,237
    pixels that are one step off black survived. Callers pass
    black_is_transparent=False for background art to keep it whole.
    """
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    out = image.pixels
    pixels_start = 26
    for y in range(height):
        row_start = pixels_start + y * row_stride
        target = y * width * 4
        for x in range(width):
            low = tile_data[row_start + x * 2]
            value = low | (tile_data[row_start + x * 2 + 1] << 8)
            if value == 0 and black_is_transparent:
                continue
            offset = target + x * 4
            out[offset] = ((value >> 11) & 0x1F) * 255 // 31
            out[offset + 1] = ((value >> 5) & 0x3F) * 255 // 63
            out[offset + 2] = (value & 0x1F) * 255 // 31
            out[offset + 3] = 255
    if not black_is_transparent:
        # Every pixel is opaque, so a bbox crop would only ever be a no-op that
        # risks trimming legitimately black edges.
        return image
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_v3_to_image(
    tile_data: bytes,
    palette_section: CamSection | None,
    *,
    clean_art: bool = True,
) -> Image.Image | None:
    palette_mode = u16(tile_data, 20) if len(tile_data) >= 26 else 0
    palette_value = u32(tile_data, 22) if len(tile_data) >= 26 else 0
    if palette_mode == 1:
        palette = load_embedded_palette(tile_data, palette_value)
    elif palette_section is not None:
        palette = load_palette(palette_section, palette_value)
    else:
        palette = None
    decoded = decode_tile_v3(tile_data, pixel_size=1 if palette is not None else None)
    if decoded is None:
        return None
    width = int(decoded["width"])
    height = int(decoded["height"])
    if width <= 0 or height <= 0:
        return None
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # Buffer writes rather than putpixel; the branch is hoisted out of the
    # inner loop because it is constant for the whole tile.
    out = image.pixels
    sixteen_bit = int(decoded["pixel_size"]) == 2
    for y, segments in enumerate(decoded["rows"]):
        row = y * width * 4
        for x_start, pixels in segments:
            for dx, index in enumerate(pixels):
                x = x_start + dx
                if x < 0 or x >= width:
                    continue
                offset = row + x * 4
                if sixteen_bit:
                    out[offset] = ((index >> 11) & 0x1F) * 255 // 31
                    out[offset + 1] = ((index >> 5) & 0x3F) * 255 // 63
                    out[offset + 2] = (index & 0x1F) * 255 // 31
                elif palette:
                    red, green, blue = palette[index]
                    if clean_art and is_palette_key_color(index, red, green, blue):
                        continue
                    out[offset] = red
                    out[offset + 1] = green
                    out[offset + 2] = blue
                else:
                    out[offset] = out[offset + 1] = out[offset + 2] = index
                out[offset + 3] = 255
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_to_image(
    tile_data: bytes,
    palette_section: CamSection | None,
    *,
    clean_art: bool = True,
    preserve_full_palette: bool = False,
    force_opaque_palette: bool = False,
    recover_enclosed_transparency: bool = False,
) -> Image.Image | None:
    version = u16(tile_data, 0) if len(tile_data) >= 2 else 0
    if version == 1:
        return tile_v1_to_image(
            tile_data,
            palette_section,
            clean_art=clean_art,
            preserve_full_palette=preserve_full_palette,
            force_opaque_palette=force_opaque_palette,
            recover_enclosed_transparency=recover_enclosed_transparency,
        )
    if version == 3:
        return tile_v3_to_image(tile_data, palette_section, clean_art=clean_art)
    return None


def tile_to_category_image(
    tile_data: bytes,
    palette_section: CamSection | None,
    category: str,
    *,
    clean_art: bool = True,
) -> Image.Image | None:
    """Decode a TILE using cleanup semantics appropriate to its output role."""
    preserve_full_palette = should_preserve_full_palette(category)
    return tile_to_image(
        tile_data,
        palette_section,
        clean_art=clean_art and not preserve_full_palette,
        preserve_full_palette=preserve_full_palette,
        force_opaque_palette=category.startswith("profile_art/"),
        recover_enclosed_transparency=should_recover_enclosed_transparency(category),
    )


def safe_name(value: str) -> str:
    value = value.strip().replace("\x00", "")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("._-") or "unnamed"


def get_sections(archive: CamArchive) -> tuple[CamSection | None, CamSection | None, CamSection | None]:
    by_ext = {section.extension: section for section in archive.sections}
    return by_ext.get("IMAG"), by_ext.get("TILE"), by_ext.get("SPLT") or by_ext.get("PALT")


def resolve_game_path(explicit_game: Path | None) -> Path:
    if explicit_game is not None:
        # Checked here rather than left to fail deep inside the extraction with
        # a confusing missing-file error.
        if not is_game_folder(explicit_game):
            raise SystemExit(
                f"That folder does not look like a Majesty HD installation:\n  {explicit_game}\n"
                "Expected it to contain Data\\maindata.cam and Data\\interfacedata.cam."
            )
        return explicit_game

    for candidate in discover_game_paths():
        if is_game_folder(candidate):
            return candidate

    searched = "\n".join(f"  - {path}" for path in discover_game_paths())
    raise SystemExit(
        "Could not find Majesty HD automatically. Use --game with the install folder.\n"
        f"Searched:\n{searched}"
    )


MAJESTY_STEAM_APP_ID = "73230"


def discover_game_paths() -> list[Path]:
    candidates: list[Path] = []

    env_game = os.environ.get("MAJESTY_HD_DIR")
    if env_game:
        candidates.append(Path(env_game))

    candidates.append(DEFAULT_GAME)

    for steam_root in steam_roots():
        for library in [steam_root, *steam_libraries_from_vdf(
            steam_root / "steamapps" / "libraryfolders.vdf"
        )]:
            steamapps = library / "steamapps"
            candidates.append(steamapps / "common" / "Majesty HD")
            # The folder is only called "Majesty HD" by default. The app
            # manifest records what it is actually called, which is the only
            # way to find a renamed install.
            installdir = steam_installdir(steamapps / f"appmanifest_{MAJESTY_STEAM_APP_ID}.acf")
            if installdir:
                candidates.append(steamapps / "common" / installdir)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def steam_roots() -> list[Path]:
    roots: list[Path] = []

    # The registry is authoritative when Steam is installed somewhere unusual.
    for hive, subkey, value in (
        ("HKCU", r"Software\Valve\Steam", "SteamPath"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ("HKLM", r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        path = read_registry_path(hive, subkey, value)
        if path:
            roots.append(path)

    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(env_name)
        if root:
            roots.append(Path(root) / "Steam")

    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    roots.append(Path(r"C:\Program Files\Steam"))
    return roots


def read_registry_path(hive: str, subkey: str, value_name: str) -> Path | None:
    """Read one registry string. Returns None whenever anything is missing."""
    try:
        import winreg
    except ImportError:
        return None
    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, value_name)
    except OSError:
        return None
    return Path(value) if value else None


def steam_installdir(manifest_path: Path) -> str | None:
    """Read "installdir" out of a Steam appmanifest_<id>.acf."""
    if not manifest_path.is_file():
        return None
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r'"installdir"\s+"([^"]+)"', text, re.IGNORECASE)
    return match.group(1) if match else None


def steam_libraries_from_vdf(path: Path) -> list[Path]:
    if not path.exists():
        return []
    libraries: list[Path] = []
    pattern = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for match in pattern.finditer(text):
        libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def is_game_folder(path: Path) -> bool:
    return (path / "Data" / "maindata.cam").exists() and (path / "Data" / "interfacedata.cam").exists()


def export_imag_record(
    source_label: str,
    record: CamEntry,
    category: str,
    catalog_entry: CatalogEntry | None,
    tile_section: CamSection,
    splt_section: CamSection | None,
    output_root: Path,
    manifest: list[dict[str, object]],
    full: bool,
    clean_art: bool,
) -> int:
    image_sets = parse_anim_set(record.data)
    if not image_sets:
        return 0

    folder_name = safe_name(f"{record.display_name[:4]}_{catalog_entry.name if catalog_entry else record.display_name[4:]}")
    written = 0

    for set_index, (set_id, set_name, rel_off) in enumerate(image_sets):
        interface_category = classify_main_interface_set(category, set_id)
        if interface_category:
            next_off = image_sets[set_index + 1][2] if set_index + 1 < len(image_sets) else len(record.data)
            images = interface_images_for_set(
                record.data, rel_off, next_off, interface_category,
                tile_section, splt_section, clean_art=clean_art,
            )
            written += write_images(
                source_label,
                record,
                interface_category,
                catalog_entry,
                set_name,
                images,
                output_root,
                manifest,
                folder_name,
            )
            continue

        export_category = classify_main_sprite_set(category, set_id, full)
        if export_category is None:
            continue
        record_dir = output_root / export_category / folder_name
        directions = parse_directional_frame_descriptor(record.data, rel_off)
        directional_written = 0
        for direction in directions:
            slot = int(direction["slot"])
            for frame_index, tile_index in enumerate(direction["tile_indices"]):
                if not full and frame_index > 0:
                    continue
                if tile_index < 0 or tile_index >= len(tile_section.entries):
                    continue
                image = tile_to_category_image(
                    tile_section.entries[tile_index].data,
                    splt_section,
                    export_category,
                    clean_art=clean_art,
                )
                if image is None:
                    continue
                record_dir.mkdir(parents=True, exist_ok=True)
                file_name = f"{safe_name(set_name)}_dir{slot}_frame{frame_index:03d}_tile{tile_index:05d}.png"
                out_path = record_dir / file_name
                image.save(out_path)
                manifest.append(
                    {
                        "category": export_category,
                        "source": source_label,
                        "image_id": record.display_name[:4],
                        "record": record.display_name,
                        "display_name": catalog_entry.description if catalog_entry else record.display_name[4:],
                        "set": set_name,
                        "direction": slot,
                        "frame": frame_index,
                        "tile_index": tile_index,
                        "png": out_path.relative_to(output_root).as_posix(),
                    }
                )
                written += 1
                directional_written += 1
        if directional_written == 0:
            next_off = image_sets[set_index + 1][2] if set_index + 1 < len(image_sets) else len(record.data)
            if category.startswith("buildings/") and export_category == category:
                images = building_state_images_for_set(
                    record.data, rel_off, next_off, tile_section, splt_section,
                    clean_art=clean_art,
                )
            else:
                images = interface_images_for_set(
                    record.data, rel_off, next_off, export_category,
                    tile_section, splt_section, clean_art=clean_art,
                )
            if not full:
                images = images[:4]
            written += write_images(
                source_label,
                record,
                export_category,
                catalog_entry,
                set_name,
                images,
                output_root,
                manifest,
                folder_name,
            )
    return written


def classify_main_sprite_set(category: str, set_id: int, full: bool) -> str | None:
    normalized_set_id = image_set_base_id(set_id)
    if category.startswith("buildings/") and normalized_set_id not in KNOWN_BUILDING_SET_IDS:
        return "other/main" if full else None
    if full:
        return category
    if category in {"heroes/sprites", "monsters/sprites"}:
        return category if normalized_set_id == 8 else None
    if category in {"buildings/sprites", "buildings/lairs"}:
        return category if normalized_set_id in {80, 192, 208} else None
    if category == "spell_effects":
        return category if normalized_set_id in {1, 8, 16, 128, 192, 2000, 2100, 2200} else None
    return category


def classify_main_interface_set(sprite_category: str, set_id: int) -> str | None:
    group = sprite_category.split("/", 1)[0]
    if group not in {"heroes", "monsters", "buildings"}:
        return None
    if set_id == 1000:
        return f"profile_art/{group}"
    if set_id == 1002:
        return f"icons/{group}"
    return None


def write_images(
    source_label: str,
    record: CamEntry,
    category: str,
    catalog_entry: CatalogEntry | None,
    set_name: str,
    images: list[tuple[int, Image.Image]],
    output_root: Path,
    manifest: list[dict[str, object]],
    folder_name: str,
) -> int:
    record_dir = output_root / category / folder_name
    written = 0
    for variant_index, (tile_index, image) in enumerate(images):
        record_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{safe_name(set_name)}_variant{variant_index:02d}_tile{tile_index:05d}.png"
        out_path = record_dir / file_name
        image.save(out_path)
        manifest.append(
            {
                "category": category,
                "source": source_label,
                "image_id": record.display_name[:4],
                "record": record.display_name,
                "display_name": catalog_entry.description if catalog_entry else record.display_name[4:],
                "set": set_name,
                "direction": "",
                "frame": variant_index,
                "tile_index": tile_index,
                "png": out_path.relative_to(output_root).as_posix(),
            }
        )
        written += 1
    return written


def export_interface_record(
    source_label: str,
    record: CamEntry,
    category: str,
    tile_section: CamSection,
    palette_section: CamSection | None,
    output_root: Path,
    manifest: list[dict[str, object]],
    clean_art: bool,
) -> int:
    image_sets = parse_anim_set(record.data)
    if not image_sets:
        return 0

    folder_name = safe_name(record.display_name)
    record_dir = output_root / category / folder_name
    written = 0
    # Full-screen presentation palettes use the high index range as ordinary
    # sepia/menu colors. Treating 247+ as sprite shadow controls punches holes
    # through paintings, maps, and menu backgrounds.
    preserve_full_palette = should_preserve_full_palette(category)
    effective_clean_art = clean_art and not preserve_full_palette

    for set_index, (set_id, set_name, rel_off) in enumerate(image_sets):
        next_off = image_sets[set_index + 1][2] if set_index + 1 < len(image_sets) else len(record.data)
        images = interface_images_for_set(
            record.data, rel_off, next_off, category, tile_section,
            palette_section, clean_art=effective_clean_art,
        )
        for variant_index, (tile_index, image) in enumerate(images):
            record_dir.mkdir(parents=True, exist_ok=True)
            file_name = f"{safe_name(set_name)}_variant{variant_index:02d}_tile{tile_index:05d}.png"
            out_path = record_dir / file_name
            image.save(out_path)
            manifest.append(
                {
                    "category": category,
                    "source": source_label,
                    "image_id": record.display_name[:4],
                    "record": record.display_name,
                    "display_name": record.display_name[4:],
                    "set": set_name,
                    "direction": "",
                    "frame": variant_index,
                    "tile_index": tile_index,
                    "png": out_path.relative_to(output_root).as_posix(),
                }
            )
            written += 1
    return written


def interface_images_for_set(
    blob: bytes,
    rel_off: int,
    next_off: int,
    category: str,
    tile_section: CamSection,
    palette_section: CamSection | None,
    *,
    clean_art: bool = True,
) -> list[tuple[int, Image.Image]]:
    if rel_off < 0 or next_off <= rel_off or next_off > len(blob):
        return []

    scan_start = rel_off + 80
    if rel_off + 68 <= next_off:
        nested_offset = u32(blob, rel_off + 64)
        nested_start = rel_off + nested_offset
        if rel_off < nested_start < next_off:
            scan_start = max(scan_start, nested_start + 20)

    found: list[tuple[int, Image.Image]] = []
    seen: set[int] = set()
    for offset in range(scan_start, max(scan_start, next_off - 3), 4):
        tile_index = u32(blob, offset)
        if tile_index == 0 or tile_index in seen or tile_index >= len(tile_section.entries):
            continue
        image = tile_to_category_image(
            tile_section.entries[tile_index].data,
            palette_section,
            category,
            clean_art=clean_art,
        )
        if image is None or not looks_like_interface_asset(category, image):
            continue
        seen.add(tile_index)
        found.append((tile_index, image))
    return found


def building_state_images_for_set(
    blob: bytes,
    rel_off: int,
    next_off: int,
    tile_section: CamSection,
    palette_section: CamSection | None,
    *,
    clean_art: bool = True,
) -> list[tuple[int, Image.Image]]:
    if rel_off < 0 or next_off <= rel_off or next_off > len(blob):
        return []
    if next_off - rel_off < 100:
        return []

    tile_count = max(1, min(32, u16(blob, rel_off + 74)))
    found: list[tuple[int, Image.Image]] = []
    seen: set[int] = set()
    cursor = next_off - 4

    while cursor >= rel_off + 88 and len(found) < tile_count:
        tile_index = u32(blob, cursor)
        prefix = u32(blob, cursor - 4) if cursor - 4 >= rel_off else 0
        if 0 < tile_index < len(tile_section.entries) and prefix == 0 and tile_index not in seen:
            image = tile_to_image(
                tile_section.entries[tile_index].data,
                palette_section,
                clean_art=clean_art,
            )
            if image is not None and image.width >= 16 and image.height >= 16:
                found.append((tile_index, image))
                seen.add(tile_index)
                cursor -= 8
                continue
        cursor -= 4

    found.reverse()
    return found


def looks_like_interface_asset(category: str, image: Image.Image) -> bool:
    width, height = image.size
    if category.startswith("profile_art"):
        return width >= 96 and height >= 96
    if category.startswith("icons"):
        return 8 <= width <= 128 and 8 <= height <= 128
    return True


def presentation_category(record_name: str) -> str | None:
    upper = record_name.upper()
    if upper.startswith("QM"):
        return "maps/quest"
    if upper.startswith("MV"):
        return "cinematics"
    if upper.startswith("SPLH"):
        return "loading_screens"
    return None


def decode_splash_picture(data: bytes) -> Image.Image | None:
    """Decode the 15-bit BGR loading picture stored in PICT/SPLH records."""
    if len(data) < 48 or u32(data, 0) != 1:
        return None
    width = u16(data, 16)
    height = u16(data, 18)
    pixel_size = width * height * 2
    if width <= 0 or height <= 0 or 48 + pixel_size > len(data):
        return None
    image = Image.frombytes("RGB", (width, height), data[48 : 48 + pixel_size], "raw", "BGR;15")
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def bink_sample_frame_indices(data: bytes, sample_count: int = PRESENTATION_SAMPLE_FRAMES) -> list[int]:
    if len(data) < 40 or data[4:7] != b"BIK":
        return []
    frame_count = u32(data, 12)
    if frame_count <= 0:
        return []
    count = min(sample_count, frame_count)
    if count == 1:
        return [0]
    return sorted({round(index * (frame_count - 1) / (count - 1)) for index in range(count)})


def bink_dimensions(data: bytes) -> tuple[int, int] | None:
    """Frame size from the Bink header, needed to slice FFmpeg's raw output.

    Offsets are relative to the whole PICT record, which prefixes the Bink
    stream with four bytes, so the Bink magic sits at 4 and its width and
    height fields at 24 and 28.
    """
    if len(data) < 32 or data[4:7] != b"BIK":
        return None
    width = u32(data, 24)
    height = u32(data, 28)
    if not (0 < width <= 8192 and 0 < height <= 8192):
        return None
    return width, height


def decode_bink_samples(data: bytes, ffmpeg: Path) -> list[tuple[int, Image.Image]]:
    """Decode evenly spaced Bink frames.

    FFmpeg is asked for raw RGBA rather than PNG files: it skips an encode and
    a decode, needs no temporary output files, and the bytes drop straight into
    an image buffer.
    """
    frame_indices = bink_sample_frame_indices(data)
    size = bink_dimensions(data)
    if not frame_indices or size is None:
        return []
    width, height = size

    with tempfile.TemporaryDirectory(prefix="majesty-art-") as temp_value:
        source_path = Path(temp_value) / "source.bik"
        source_path.write_bytes(data[4:])  # PICT prepends a four-byte type value.
        expression = "+".join(f"eq(n\\,{frame})" for frame in frame_indices)
        command = [
            str(ffmpeg),
            "-v", "error",
            "-y",
            "-i", str(source_path),
            "-an",
            "-vf", f"select={expression}",
            "-fps_mode", "vfr",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-",
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"Could not decode Bink presentation art: {message}")

    frame_bytes = width * height * 4
    decoded: list[tuple[int, Image.Image]] = []
    for sequence, frame_index in enumerate(frame_indices):
        start = sequence * frame_bytes
        chunk = result.stdout[start : start + frame_bytes]
        if len(chunk) < frame_bytes:
            break
        decoded.append((frame_index, Image(width, height, bytearray(chunk))))
    return decoded


def cinematic_soundtrack_path(game: Path, record_name: str) -> Path | None:
    """Return the runtime music used by a video-only cinematic, if known.

    MV01 and MV06 are the original and expansion credit reels. Their Bink
    records intentionally contain no audio; in game they are reached from the
    menu while the general theme supplies the soundtrack.
    """
    if record_name.upper() not in {"MV01", "MV06"}:
        return None
    soundtrack = game / "Music" / "GeneralTheme.mp3"
    return soundtrack if soundtrack.is_file() else None


def transcode_bink_video(
    data: bytes, output_path: Path, ffmpeg: Path, soundtrack_path: Path | None = None
) -> None:
    """Write an embedded Bink stream as a broadly playable, audible MP4."""
    if not bink_sample_frame_indices(data, sample_count=1):
        raise ValueError("PICT record does not contain a supported Bink stream")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="majesty-video-") as temp_value:
        source_path = Path(temp_value) / "source.bik"
        source_path.write_bytes(data[4:])
        command = [
            str(ffmpeg),
            "-v",
            "error",
            "-y",
            "-i",
            str(source_path),
        ]
        if soundtrack_path is not None:
            command.extend(["-i", str(soundtrack_path)])
        command.extend([
            "-map",
            "0:v:0",
            "-map",
            "1:a:0" if soundtrack_path is not None else "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
        ])
        if soundtrack_path is not None:
            # The menu theme is longer than either credit reel. Stop the mux
            # when the video ends, matching the lifetime of the in-game view.
            command.append("-shortest")
        command.append(str(output_path))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Could not convert Bink cinematic: {result.stderr.strip()}")


def make_presentation_contact_sheet(frames: list[tuple[int, Image.Image]]) -> Image.Image:

    thumb_width = 240
    label_height = 24
    columns = min(4, len(frames))
    rows = (len(frames) + columns - 1) // columns
    thumbs: list[tuple[int, Image.Image]] = []
    cell_height = 0
    for frame_index, source in frames:
        image = source.copy()
        image.thumbnail((thumb_width, 180), Image.Resampling.LANCZOS)
        cell_height = max(cell_height, image.height + label_height)
        thumbs.append((frame_index, image))

    sheet = Image.new("RGB", (columns * thumb_width, rows * cell_height), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (frame_index, image) in enumerate(thumbs):
        column = index % columns
        row = index // columns
        x = column * thumb_width + (thumb_width - image.width) // 2
        y = row * cell_height
        sheet.paste(image, (x, y))
        draw.text((column * thumb_width + 6, y + image.height + 4), f"Frame {frame_index}", fill=(235, 235, 235))
    return sheet


def export_presentation_art(
    game: Path,
    output_root: Path,
    manifest: list[dict[str, object]],
    *,
    keep_original_video: bool = False,
    ffmpeg: Path | None = None,
) -> int:
    """Export loading screens, and, when FFmpeg is available, video records.

    Loading screens are a plain 15-bit raster this tool decodes itself. Maps,
    segues and cinematics are Bink, so without FFmpeg they are skipped rather
    than failing the run.
    """
    written = 0
    if ffmpeg is None:
        print(
            "Extracting loading screens (cinematics, maps and segues need FFmpeg)...",
            flush=True,
        )
    else:
        print("Extracting maps, cinematics, segues, and loading screens...", flush=True)
    for source_label, rel_path in PICTURE_CAM_SOURCES:
        path = game / rel_path
        if not path.exists():
            continue
        archive = read_cam(path)
        picture_section = next((section for section in archive.sections if section.extension == "PICT"), None)
        if picture_section is None:
            continue
        for record in picture_section.entries:
            category = presentation_category(record.display_name)
            if category is None:
                continue
            if category == "loading_screens":
                image = decode_splash_picture(record.data)
                frames = [(0, image)] if image is not None else []
            elif ffmpeg is None:
                continue  # Bink record, and nothing here can read it.
            else:
                frames = decode_bink_samples(record.data, ffmpeg)

            record_dir = output_root / category / safe_name(f"{source_label}_{record.display_name}")
            record_dir.mkdir(parents=True, exist_ok=True)

            if category == "cinematics":
                transcode_bink_video(
                    record.data,
                    record_dir / f"{safe_name(record.display_name)}.mp4",
                    ffmpeg,
                    cinematic_soundtrack_path(game, record.display_name),
                )
                if keep_original_video:
                    (record_dir / f"{safe_name(record.display_name)}.bik").write_bytes(record.data[4:])

            for sample_index, (frame_index, image) in enumerate(frames):
                name = f"sample{sample_index:02d}_frame{frame_index:05d}.png"
                output_path = record_dir / name
                image.save(output_path)
                manifest.append(
                    {
                        "category": category,
                        "source": source_label,
                        "image_id": record.display_name,
                        "record": record.display_name,
                        "display_name": record.display_name,
                        "set": "Presentation",
                        "direction": "",
                        "frame": frame_index,
                        "tile_index": "",
                        "png": output_path.relative_to(output_root).as_posix(),
                    }
                )
                written += 1

            if len(frames) > 1:
                contact_dir = output_root / "_previews" / category
                contact_dir.mkdir(parents=True, exist_ok=True)
                make_presentation_contact_sheet(frames).save(
                    contact_dir / f"{safe_name(source_label)}_{safe_name(record.display_name)}.png"
                )
    return written


def should_preserve_full_palette(category: str) -> bool:
    """Non-sprite art uses high indices as colors, not sprite controls."""
    return category.startswith(
        ("profile_art", "icons", "spell_effects", "menus", "maps", "segues", "loading_screens")
    )


def should_recover_enclosed_transparency(category: str) -> bool:
    """UI/presentation art may reuse its transparent index inside the artwork."""
    return category.startswith(("icons", "menus", "maps", "segues", "loading_screens"))


def expected_tile_opaque_pixels(
    tile_data: bytes,
    palette_section: CamSection | None,
    category: str,
    *,
    clean_art: bool,
) -> int | None:
    """Count source pixels that a decoded TILE PNG must keep opaque.

    This intentionally derives occupancy from the source encoding rather than
    calling the image renderer. It catches shared clean/raw decoder losses such
    as treating an explicitly stored TILE v3 palette index zero as a gap.
    """
    version = u16(tile_data, 0) if len(tile_data) >= 2 else 0
    preserve_full_palette = should_preserve_full_palette(category)

    if version == 3:
        palette_mode = u16(tile_data, 20) if len(tile_data) >= 26 else 0
        palette_value = u32(tile_data, 22) if len(tile_data) >= 26 else 0
        if palette_mode == 1:
            palette = load_embedded_palette(tile_data, palette_value)
        elif palette_section is not None:
            palette = load_palette(palette_section, palette_value)
        else:
            palette = None
        decoded = decode_tile_v3(tile_data, pixel_size=1 if palette is not None else 2)
        if decoded is None:
            return None
        values = [value for row in decoded["rows"] for _x, pixels in row for value in pixels]
        if not clean_art or preserve_full_palette or palette is None:
            return len(values)
        return sum(not is_palette_key_color(value, *palette[value]) for value in values)

    if version != 1 or len(tile_data) < 26:
        return None
    height = u16(tile_data, 2)
    width = u16(tile_data, 4)
    row_stride = u16(tile_data, 6)
    if width <= 0 or height <= 0:
        return None
    if row_stride == width * 2 and 26 + height * row_stride <= len(tile_data):
        # Mirrors tile_v1_rgb565_to_image: background art keeps its black
        # pixels, so every stored pixel is opaque.
        if preserve_full_palette:
            return width * height
        return sum(u16(tile_data, 26 + y * row_stride + x * 2) != 0 for y in range(height) for x in range(width))
    if row_stride < width or 26 + height * row_stride > len(tile_data):
        return None

    palette_mode = u16(tile_data, 20)
    palette_value = u32(tile_data, 22)
    if palette_mode == 1:
        palette = load_embedded_palette(tile_data, palette_value)
    elif palette_section is not None:
        palette = load_palette(palette_section, palette_value)
    else:
        palette = None
    if palette is None:
        return None

    pixels = tile_data[26 : 26 + height * row_stride]
    transparent_index = u16(tile_data, 16) & 0xFF
    if category.startswith("profile_art/"):
        transparent_offsets: set[int] = set()
    elif should_recover_enclosed_transparency(category):
        transparent_offsets = edge_connected_index_offsets(
            pixels, width, height, row_stride, transparent_index
        )
    else:
        transparent_offsets = {
            y * row_stride + x
            for y in range(height)
            for x in range(width)
            if pixels[y * row_stride + x] == transparent_index
        }

    opaque = 0
    for y in range(height):
        for x in range(width):
            offset = y * row_stride + x
            index = pixels[offset]
            if index == transparent_index and offset in transparent_offsets:
                continue
            if clean_art and not preserve_full_palette and is_palette_key_color(index, *palette[index]):
                continue
            opaque += 1
    return opaque


def audit_extracted_tile_occupancy(
    game: Path,
    output_root: Path,
    manifest: list[dict[str, object]],
    *,
    clean_art: bool,
) -> int:
    """Verify every TILE-derived PNG against independently counted source pixels."""
    sources: dict[str, tuple[CamSection | None, CamSection | None]] = {}
    for source_label, rel_path in MAIN_CAM_SOURCES:
        _imag, tile, palette = get_sections(read_cam(game / rel_path))
        sources[source_label] = (tile, palette)

    palette_fallback: CamSection | None = None
    for source_label, rel_path in INTERFACE_CAM_SOURCES:
        path = game / rel_path
        if not path.exists():
            continue
        _imag, tile, palette = get_sections(read_cam(path))
        if palette is not None:
            palette_fallback = palette
        sources[source_label] = (tile, palette or palette_fallback)

    checked = 0
    failures: list[str] = []
    for row in manifest:
        tile_value = row.get("tile_index", "")
        source_value = str(row.get("source", ""))
        if tile_value in {"", None} or source_value not in sources:
            continue
        tile_section, palette_section = sources[source_value]
        tile_index = int(tile_value)
        if tile_section is None or not 0 <= tile_index < len(tile_section.entries):
            failures.append(f"{row.get('png')}: invalid source TILE {tile_index}")
            continue
        expected = expected_tile_opaque_pixels(
            tile_section.entries[tile_index].data,
            palette_section,
            str(row.get("category", "")),
            clean_art=clean_art,
        )
        if expected is None:
            failures.append(f"{row.get('png')}: could not independently count source TILE {tile_index}")
            continue
        output_path = output_root / str(row["png"])
        if not output_path.exists():
            failures.append(f"{row.get('png')}: output PNG is missing")
            continue
        with Image.open(output_path) as image:
            actual = sum(alpha > 0 for alpha in image.convert("RGBA").getchannel("A").getdata())
        checked += 1
        if actual != expected:
            failures.append(f"{row.get('png')}: expected {expected} opaque pixels, found {actual}")

    if failures:
        details = "\n  - ".join(failures[:20])
        extra = f"\n  ... and {len(failures) - 20} more" if len(failures) > 20 else ""
        raise RuntimeError(f"Source-pixel audit failed:\n  - {details}{extra}")
    return checked


def finish_limited_run(output_root: Path, manifest: list[dict[str, object]], total: int) -> int:
    """Wrap up a --limit run.

    A limited run stops partway through the archives, so presentation art is
    never reached and the source-pixel audit has nothing complete to check.
    Both are skipped, and both are said out loud: a partial run that printed
    nothing about the audit would read as though it had passed.
    """
    print(f"Writing manifest and previews for {total} files...", flush=True)
    write_manifest(output_root, manifest)
    create_previews(output_root, manifest)
    print(
        "\nThis was a --limit sample run. Presentation art was not extracted and\n"
        "the source-pixel audit did not run. Use a full run to verify output.",
        flush=True,
    )
    return total


def extract_assets(
    game: Path,
    output_root: Path,
    full: bool = False,
    limit: int | None = None,
    *,
    clean_art: bool = True,
    ffmpeg: Path | None = None,
) -> int:
    started = time.perf_counter()
    catalog = parse_catalog(game)
    validate_output_root(game, output_root)
    if output_root.exists():
        print(f"Clearing previous output: {output_root}", flush=True)
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    # Written before any art so an interrupted run still marks the folder as
    # ours, which is what lets the next run clear it.
    (output_root / OUTPUT_MARKER).write_text(OUTPUT_MARKER_TEXT, encoding="utf-8")

    manifest: list[dict[str, object]] = []
    total = 0
    records_done = 0

    print("Extracting game art records...", flush=True)
    for source_label, rel_path in MAIN_CAM_SOURCES:
        archive = read_cam(game / rel_path)
        imag, tile, splt = get_sections(archive)
        if imag is None or tile is None:
            continue
        for record in imag.entries:
            classified = classify_imag_record(record.display_name, catalog, full)
            if classified is None:
                continue
            category, catalog_entry = classified
            count = export_imag_record(
                source_label,
                record,
                category,
                catalog_entry,
                tile,
                splt,
                output_root,
                manifest,
                full,
                clean_art,
            )
            if count:
                total += count
                records_done += 1
                if limit is not None and records_done >= limit:
                    return finish_limited_run(output_root, manifest, total)

    print("Extracting curated interface records...", flush=True)
    interface_palette_fallback: CamSection | None = None
    for source_label, rel_path in INTERFACE_CAM_SOURCES:
        archive = read_cam(game / rel_path)
        imag, tile, palette = get_sections(archive)
        if imag is None or tile is None:
            continue
        if palette is not None:
            interface_palette_fallback = palette
        effective_palette = palette or interface_palette_fallback
        for record in imag.entries:
            category = CURATED_INTERFACE_RECORDS.get(record.display_name[:4])
            if category is None and not full:
                continue
            if category is None:
                category = "other/interface"
            count = export_interface_record(
                source_label, record, category, tile, effective_palette,
                output_root, manifest, clean_art,
            )
            if count:
                total += count
                records_done += 1
                if limit is not None and records_done >= limit:
                    return finish_limited_run(output_root, manifest, total)

    total += export_presentation_art(
        game,
        output_root,
        manifest,
        keep_original_video=not clean_art,
        ffmpeg=ffmpeg,
    )
    if ffmpeg is None:
        for line in ffmpeg_support.skip_notice():
            print(line, flush=True)

    print("Auditing decoded TILE pixels against source runs...", flush=True)
    audited = audit_extracted_tile_occupancy(
        game,
        output_root,
        manifest,
        clean_art=clean_art,
    )
    print(f"Source-pixel audit passed for {audited} TILE-derived PNGs.", flush=True)
    print(f"Writing manifest for {total} files...", flush=True)
    write_manifest(output_root, manifest)
    print("Creating preview sheets...", flush=True)
    create_previews(output_root, manifest)
    print(f"Extraction stages finished in {time.perf_counter() - started:.1f}s", flush=True)
    return total


OUTPUT_MARKER = ".majesty-art-extractor-output"

OUTPUT_MARKER_TEXT = (
    "This folder is managed by the Majesty Gold HD art asset extractor.\n"
    "Everything in it is deleted and rebuilt at the start of each run.\n"
    "Do not store anything here that you want to keep.\n"
)


def protected_output_roots() -> list[Path]:
    """Folders that must never be handed to rmtree.

    Windows-only, matching the game. Resolution failures are ignored so a
    missing OneDrive or relocated profile folder cannot break the check.
    """
    candidates: list[Path] = []

    for name in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))

    profile = os.environ.get("USERPROFILE")
    if profile:
        home = Path(profile)
        candidates.append(home)
        candidates.extend(
            home / child
            for child in (
                "Desktop", "Documents", "Downloads", "Pictures",
                "Music", "Videos", "OneDrive", "AppData", "Saved Games",
            )
        )

    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(Path(public))

    resolved: list[Path] = []
    for candidate in candidates:
        try:
            resolved.append(candidate.resolve())
        except OSError:
            continue
    return resolved


def validate_output_root(game: Path, output_root: Path) -> None:
    """Refuse output folders where a full delete would be destructive.

    The output folder is cleared with rmtree at the start of every run, so this
    is the only thing standing between a mistyped --out and real data loss. It
    checks three separate ways rather than matching a short list of exact paths:

    1. The folder must not be a drive root or a known Windows/profile folder.
    2. It must not be, contain, or sit inside the game installation, and it must
       not contain this tool.
    3. If it already exists with contents, it must carry this tool's marker
       file, proving a previous run created it. That is what protects folders
       nobody could enumerate in advance.
    """
    try:
        resolved_output = output_root.resolve()
    except OSError as error:
        raise ValueError(f"Output folder path cannot be resolved: {output_root}") from error
    resolved_game = game.resolve()
    resolved_tool = TOOL_ROOT.resolve()

    def refuse(reason: str) -> None:
        raise ValueError(
            f"Refusing to use this output folder:\n  {resolved_output}\n{reason}\n"
            "Pick an empty folder, or one created by a previous extraction."
        )

    if resolved_output == Path(resolved_output.anchor):
        refuse("  That is the root of a drive.")

    if resolved_output in protected_output_roots():
        refuse("  That is a Windows system or user profile folder.")

    if resolved_output == resolved_game:
        refuse("  That is the game installation.")
    if is_inside(resolved_output, resolved_game):
        refuse("  That is inside the game installation.")
    if is_inside(resolved_game, resolved_output):
        refuse("  The game installation is inside it, so clearing it would delete the game.")
    if is_inside(resolved_tool, resolved_output):
        refuse("  This extractor is inside it, so clearing it would delete the tool.")

    # An existing folder is only cleared when a previous run left its marker.
    if resolved_output.exists():
        if not resolved_output.is_dir():
            refuse("  That path is a file, not a folder.")
        try:
            has_contents = any(resolved_output.iterdir())
        except OSError as error:
            raise ValueError(f"Output folder cannot be read: {resolved_output}") from error
        if has_contents and not (resolved_output / OUTPUT_MARKER).exists():
            refuse(
                "  It already contains files and was not created by this tool.\n"
                "  Everything in the output folder is deleted at the start of a run,\n"
                "  so this is refused rather than risking your files."
            )


def is_inside(path: Path, parent: Path) -> bool:
    """True when path sits under parent. Windows paths compare case-insensitively."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        pass
    try:
        return os.path.normcase(str(path)).startswith(os.path.normcase(str(parent)) + os.sep)
    except (TypeError, ValueError):
        return False


def write_manifest(output_root: Path, manifest: list[dict[str, object]]) -> None:
    path = output_root / "_manifest.csv"
    fieldnames = ["category", "source", "image_id", "record", "display_name", "set", "direction", "frame", "tile_index", "png"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest)


def create_previews(output_root: Path, manifest: list[dict[str, object]]) -> int:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    preview_categories = {
        "heroes/sprites",
        "monsters/sprites",
        "buildings/sprites",
        "buildings/lairs",
        "spell_effects",
        "other/main",
    }
    for row in manifest:
        category = str(row["category"])
        if category not in preview_categories:
            continue
        groups.setdefault((category, str(row["record"])), []).append(row)

    written = 0
    for (category, record), rows in groups.items():
        images = []
        for row in rows:
            path = output_root / str(row["png"])
            if not path.exists():
                continue
            try:
                images.append((row, Image.open(path).convert("RGBA")))
            except OSError:
                continue
        if not images:
            continue
        selected_images = select_preview_images(images)
        if not selected_images:
            continue
        preview = build_contact_sheet(selected_images)
        out_dir = output_root / "_previews" / category
        out_dir.mkdir(parents=True, exist_ok=True)
        preview.save(out_dir / f"{safe_name(record)}.png")
        written += 1
    return written


def create_guide_art(output_root: Path, manifest: list[dict[str, object]]) -> int:
    written = 0
    by_record: dict[str, list[dict[str, object]]] = {}
    for row in manifest:
        by_record.setdefault(str(row["record"]), []).append(row)

    for record, rows in by_record.items():
        profile_row = pick_guide_profile(rows)
        sprite_row = pick_guide_sprite(rows)
        for label, row in (("profiles", profile_row), ("sprites", sprite_row)):
            if row is None:
                continue
            src = output_root / str(row["png"])
            if not src.exists():
                continue
            try:
                image = Image.open(src).convert("RGBA")
            except OSError:
                continue
            image = scale_guide_image(image)
            group = guide_group(str(row["category"]))
            out_dir = output_root / "guide_art" / label / group
            out_dir.mkdir(parents=True, exist_ok=True)
            image.save(out_dir / f"{safe_name(record)}.png")
            written += 1
            if label == "sprites":
                card_dir = output_root / "guide_art" / "sprite_cards" / group
                card_dir.mkdir(parents=True, exist_ok=True)
                sprite_card(image, str(row["category"])).save(card_dir / f"{safe_name(record)}.png")
                written += 1
    return written


def pick_guide_profile(rows: list[dict[str, object]]) -> dict[str, object] | None:
    profile_rows = [row for row in rows if str(row["category"]).startswith("profile_art/")]
    if not profile_rows:
        return None
    return sorted(profile_rows, key=lambda row: (str(row["set"]) != "Interface", str(row["png"])))[0]


def pick_guide_sprite(rows: list[dict[str, object]]) -> dict[str, object] | None:
    sprite_categories = {"heroes/sprites", "monsters/sprites", "buildings/sprites", "buildings/lairs", "spell_effects"}
    sprite_rows = [row for row in rows if str(row["category"]) in sprite_categories]
    if not sprite_rows:
        return None
    return select_preview_rows(sprite_rows)[0]


def guide_group(category: str) -> str:
    if category == "buildings/lairs":
        return "lairs"
    if category.startswith("profile_art/"):
        return safe_name(category.split("/", 1)[1])
    if "/" in category:
        return safe_name(category.split("/", 1)[0])
    return safe_name(category)


def scale_guide_image(image: Image.Image) -> Image.Image:
    max_dim = max(image.size)
    if 0 < max_dim < 128:
        factor = max(2, min(6, 128 // max_dim))
        return image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)
    return image


def sprite_card(image: Image.Image, category: str) -> Image.Image:
    pad = 24
    bg_color = (92, 110, 64, 255) if category.startswith("buildings/") else (28, 28, 28, 255)
    alt_color = (102, 122, 70, 255) if category.startswith("buildings/") else (36, 36, 36, 255)
    card = Image.new("RGBA", (image.width + pad * 2, image.height + pad * 2), bg_color)

    draw = ImageDraw.Draw(card)
    for y in range(0, card.height, 16):
        for x in range(0, card.width, 16):
            if (x // 16 + y // 16) % 2 == 0:
                draw.rectangle([x, y, x + 15, y + 15], fill=alt_color)
    card.alpha_composite(image, (pad, pad))
    return card


def select_preview_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    priorities = [
        "Stand",
        "Active",
        "Inactive",
        "Walk",
        "Build",
        "Interface",
        "Attack",
        "Cast",
        "Die",
    ]
    by_set: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_set.setdefault(str(row["set"]), []).append(row)

    chosen: list[dict[str, object]] = []
    for prefix in priorities:
        for set_name in sorted(by_set):
            if set_name == prefix or set_name.startswith(f"{prefix}-"):
                chosen.extend(by_set[set_name][:8])
                if len(chosen) >= 8:
                    return chosen[:8]
        if chosen:
            return chosen[:8]
    return rows[:8]


def select_preview_images(images: list[tuple[dict[str, object], Image.Image]]) -> list[tuple[dict[str, object], Image.Image]]:
    rows = [row for row, _ in images]
    selected_rows = select_preview_rows(rows)
    if not selected_rows:
        return []

    selected_ids = {id(row) for row in selected_rows}
    selected_by_set = {str(row["set"]) for row in selected_rows}
    candidates = [
        (row, image)
        for row, image in images
        if id(row) in selected_ids or str(row["set"]) in selected_by_set
    ]
    if not candidates:
        candidates = images

    def sort_key(item: tuple[dict[str, object], Image.Image]) -> tuple[int, int, int, str]:
        row, image = item
        return (
            preview_image_score(image),
            image.width * image.height,
            -int(row.get("frame") or 0),
            str(row["png"]),
        )

    return sorted(candidates, key=sort_key, reverse=True)[:8]


def preview_image_score(image: Image.Image) -> int:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return 0
    left, top, right, bottom = bbox
    bbox_area = (right - left) * (bottom - top)
    visible_count = 0
    for value in alpha.getdata():
        if value:
            visible_count += 1
    return bbox_area + visible_count


def build_contact_sheet(images: list[tuple[dict[str, object], Image.Image]]) -> Image.Image:
    if len(images) == 1:
        cell_w = 360
        cell_h = 280
    else:
        cell_w = 192
        cell_h = 160
    label_h = 18
    cols = min(4, max(1, len(images)))
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell_w, rows * (cell_h + label_h)), (28, 28, 28, 255))

    for index, (row, image) in enumerate(images):
        col = index % cols
        row_index = index // cols
        x = col * cell_w
        y = row_index * (cell_h + label_h)
        tile = Image.new("RGBA", (cell_w, cell_h), (28, 28, 28, 255))
        scaled = image.copy()
        max_dim = max(scaled.size)
        if max_dim and max_dim < 96:
            factor = max(2, min(6, 96 // max_dim))
            scaled = scaled.resize((scaled.width * factor, scaled.height * factor), Image.Resampling.NEAREST)
        scaled.thumbnail((cell_w - 8, cell_h - 8), Image.Resampling.NEAREST)
        tile.alpha_composite(scaled, ((cell_w - scaled.width) // 2, (cell_h - scaled.height) // 2))
        sheet.alpha_composite(tile, (x, y))
        draw_label(sheet, preview_cell_label(row)[:24], x + 4, y + cell_h + 2)
    return sheet


def preview_cell_label(row: dict[str, object]) -> str:
    """Name a preview cell so neighbouring cells are told apart.

    A directional record contributes one cell per facing, and labelling them by
    set and frame alone made every cell of a hero sheet read "Stand 0".
    """
    parts = [str(row.get("set", "")).strip()]
    direction = str(row.get("direction", "")).strip()
    if direction:
        parts.append(f"d{direction}")
    frame = str(row.get("frame", "")).strip()
    if frame:
        parts.append(f"f{frame}")
    return " ".join(part for part in parts if part) or "frame"


def draw_label(image: Image.Image, text: str, x: int, y: int) -> None:

    draw = ImageDraw.Draw(image)
    draw.text((x, y), text, fill=(230, 230, 230, 255))


def make_zip(output_root: Path) -> Path:
    archive_base = output_root.parent / output_root.name
    archive_path = shutil.make_archive(str(archive_base), "zip", output_root)
    return Path(archive_path)


def extract_mode(
    game: Path,
    output_root: Path,
    mode: ExtractionMode | str,
    *,
    limit: int | None = None,
    ffmpeg: Path | None = None,
) -> int:
    """Extract using one of the three user-facing presets."""
    selected = ExtractionMode(mode)
    print(f"Mode: {MODE_LABELS[selected]}", flush=True)
    return extract_assets(
        game,
        output_root,
        full=selected.exhaustive,
        limit=limit,
        clean_art=selected.clean_art,
        ffmpeg=ffmpeg,
    )


def estimate_output_size(game: Path, mode: ExtractionMode | str) -> int:
    """Return a conservative output-size estimate without decoding every TILE.

    The CAMs use compact indexed/RLE art while output PNGs include per-record
    organization, previews, and sometimes repeated referenced frames. These
    ratios intentionally err high and are quick enough to refresh in the GUI.
    """
    selected = ExtractionMode(mode)
    art_source_bytes = sum(
        (game / rel_path).stat().st_size
        for _label, rel_path in MAIN_CAM_SOURCES + INTERFACE_CAM_SOURCES
        if (game / rel_path).exists()
    )
    presentation_source_bytes = sum(
        (game / rel_path).stat().st_size
        for _label, rel_path in PICTURE_CAM_SOURCES
        if (game / rel_path).exists()
    )
    if selected is ExtractionMode.ALL_RAW:
        return int(art_source_bytes * 2.75 + presentation_source_bytes * 1.25)
    if selected is ExtractionMode.RELEVANT_RAW:
        return int(art_source_bytes * 0.55 + presentation_source_bytes * 1.25)
    return int(art_source_bytes * 0.45 + presentation_source_bytes * 0.80)


def confirm_output_clear(output_root: Path, *, assume_yes: bool = False) -> bool:
    """Ask before deleting an existing output folder. True means go ahead.

    Only reached for folders validate_output_root already accepted, so this is
    a second look rather than the safety net. Returns True without asking when
    there is nothing to lose, or when stdin is not a terminal, which keeps the
    GUI and scripted runs working; the GUI asks its own question first.
    """
    if assume_yes or not output_root.exists():
        return True
    try:
        entries = list(output_root.iterdir())
    except OSError:
        return True
    removable = [entry for entry in entries if entry.name != OUTPUT_MARKER]
    if not removable:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        return True

    print(f"\nThis folder already holds {len(removable):,} items and will be emptied first:")
    print(f"  {output_root}")
    for entry in sorted(removable, key=lambda item: item.name)[:8]:
        print(f"    {entry.name}{'/' if entry.is_dir() else ''}")
    if len(removable) > 8:
        print(f"    ... and {len(removable) - 8:,} more")
    try:
        answer = input("Delete this folder's contents and continue? [y/N] ")
    except EOFError:
        # No console to answer on. Cancelling is the safe default; say how to
        # proceed deliberately instead of leaving the user guessing.
        print("\nNo console input available. Re-run with --yes to confirm.")
        return False
    except KeyboardInterrupt:
        print()
        return False
    return answer.strip().lower() in {"y", "yes"}


def resolve_cli_ffmpeg(*, want_cinematics: bool, assume_yes: bool) -> Path | None:
    """Work out which FFmpeg, if any, this command-line run should use.

    An FFmpeg already on the machine is used without asking. A download only
    happens when --cinematics was passed and the person at the keyboard says
    yes, or when --yes made that decision in advance.
    """
    existing = ffmpeg_support.find_ffmpeg()
    if existing is not None:
        print(f"Using FFmpeg: {existing}", flush=True)
        return existing
    if not want_cinematics:
        return None

    def confirm(message: str) -> bool:
        if assume_yes:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            print("\n" + message)
            print("No console input available. Re-run with --yes to accept.")
            return False
        print("\n" + message)
        try:
            return input("[y/N] ").strip().lower() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    try:
        return ffmpeg_support.resolve_ffmpeg(
            allow_download=True,
            confirm=confirm,
            progress=lambda message: print(f"  {message}", flush=True),
        )
    except ffmpeg_support.FFmpegUnavailable as error:
        print(f"\nFFmpeg could not be set up: {error}")
        return None


def format_bytes(size: int) -> str:
    value = float(max(0, size))
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract local Majesty Gold HD art assets to PNG.")
    parser.add_argument("--game", type=Path, help="Majesty Gold HD install folder; auto-discovered if omitted")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ExtractionMode],
        default=ExtractionMode.RELEVANT_ART.value,
        help="Extraction preset (default: relevant-art)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Deprecated alias for --mode all-raw",
    )
    parser.add_argument("--limit", type=int, help="Stop after this many IMAG records with extracted PNGs")
    parser.add_argument("--zip", action="store_true", help="Create a local zip next to the output folder")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt shown before an existing output folder is cleared",
    )
    parser.add_argument(
        "--cinematics",
        action="store_true",
        help=(
            "Include cinematics, maps and segues. These are Bink video and need "
            "FFmpeg; if none is found you will be offered a download."
        ),
    )
    args = parser.parse_args()

    game = resolve_game_path(args.game)
    output = args.out if args.out.is_absolute() else TOOL_ROOT / args.out

    # Checked before the prompt so an unsafe path is rejected outright rather
    # than offered as something the user can confirm their way past.
    validate_output_root(game, output)
    if not confirm_output_clear(output, assume_yes=args.yes):
        print("Cancelled. Nothing was changed.")
        return 1

    ffmpeg = resolve_cli_ffmpeg(want_cinematics=args.cinematics, assume_yes=args.yes)

    mode = ExtractionMode.ALL_RAW if args.full else ExtractionMode(args.mode)
    total = extract_mode(game, output, mode, limit=args.limit, ffmpeg=ffmpeg)
    print(f"Game folder: {game}")
    print(f"Extracted {total} PNG files to {output}")
    if args.zip:
        print("Creating local zip...", flush=True)
        zip_path = make_zip(output)
        print(f"Wrote local zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
