from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import struct
import xml.etree.ElementTree as ET

from PIL import Image


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Majesty HD")
DEFAULT_OUT = TOOL_ROOT / "output" / "assets"

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
}

MAIN_CAM_SOURCES = [
    ("base", Path("Data/maindata.cam")),
    ("expansion", Path("DataMX/mx_maindata.cam")),
]

INTERFACE_CAM_SOURCES = [
    ("base_interface", Path("Data/interfacedata.cam")),
    ("expansion_interface", Path("DataMX/mx_interfacedata.cam")),
]

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
    return "other/main", None


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
        sets.append((set_id, IMAGE_SET_NAMES.get(set_id, f"set-{set_id}"), rel_off))
        pos += IMAGE_SET_ENTRY_SIZE
    return sets


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


def decode_tile_v3(tile_data: bytes) -> dict[str, object] | None:
    """Decode TILE v3 RLE. On-disk x is exclusive end; returned segments use start."""
    if len(tile_data) < 26 or u16(tile_data, 0) != 3:
        return None
    height = u16(tile_data, 2)
    header_width = u16(tile_data, 4)
    palette_id = u32(tile_data, 22)
    offset_base = 26
    if height <= 0 or offset_base + height * 4 > len(tile_data):
        return None

    offsets = [u32(tile_data, offset_base + row * 4) for row in range(height)]
    rows = []
    max_end = 0
    for row in range(height):
        start = offset_base + offsets[row]
        end = offset_base + offsets[row + 1] if row + 1 < height else len(tile_data)
        if start >= len(tile_data) or end > len(tile_data) or start > end:
            rows.append([])
            continue
        row_data = tile_data[start:end]
        segments = []
        pos = 0
        while pos + 4 <= len(row_data):
            x_end = u16(row_data, pos)
            count_word = u16(row_data, pos + 2)
            pos += 4
            count = count_word & 0xFF
            flags = (count_word >> 8) & 0xFF
            if count > 0 and count <= x_end and pos + count <= len(row_data):
                pixels = list(row_data[pos : pos + count])
                pos += count
                x_start = x_end - count
                segments.append((x_start, pixels))
                max_end = max(max_end, x_end)
            if flags & 0x80:
                break
        rows.append(segments)
    width = header_width if header_width > 0 else max_end
    if max_end > width:
        width = max_end
    return {"width": width, "height": height, "palette_id": palette_id, "rows": rows}


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


def tile_v1_to_image(tile_data: bytes, palette_section: CamSection | None) -> Image.Image | None:
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
        return tile_v1_rgb565_to_image(tile_data, width, height, row_stride)
    pixel_count = width * height
    if 26 + pixel_count > len(tile_data):
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
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y in range(height):
        for x in range(width):
            index = pixels[y * width + x]
            if index == transparent_index:
                continue
            red, green, blue = palette[index]
            if red > 150 and green < 80 and blue > 150 and abs(red - blue) < 60:
                continue
            image.putpixel((x, y), (red, green, blue, 255))
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_v1_rgb565_to_image(tile_data: bytes, width: int, height: int, row_stride: int) -> Image.Image | None:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels_start = 26
    for y in range(height):
        row_start = pixels_start + y * row_stride
        for x in range(width):
            value = u16(tile_data, row_start + x * 2)
            if value == 0:
                continue
            red = ((value >> 11) & 0x1F) * 255 // 31
            green = ((value >> 5) & 0x3F) * 255 // 63
            blue = (value & 0x1F) * 255 // 31
            image.putpixel((x, y), (red, green, blue, 255))
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_v3_to_image(tile_data: bytes, palette_section: CamSection | None) -> Image.Image | None:
    decoded = decode_tile_v3(tile_data)
    if decoded is None:
        return None
    width = int(decoded["width"])
    height = int(decoded["height"])
    if width <= 0 or height <= 0:
        return None
    palette = load_palette(palette_section, int(decoded["palette_id"])) if palette_section else None
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y, segments in enumerate(decoded["rows"]):
        for x_start, pixels in segments:
            for dx, index in enumerate(pixels):
                x = x_start + dx
                if x < 0 or x >= width:
                    continue
                if index == 0:
                    continue
                if palette:
                    red, green, blue = palette[index]
                    if index >= 248:
                        continue
                    if red > 150 and green < 80 and blue > 150 and abs(red - blue) < 60:
                        continue
                    image.putpixel((x, y), (red, green, blue, 255))
                else:
                    image.putpixel((x, y), (index, index, index, 255))
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def tile_to_image(tile_data: bytes, palette_section: CamSection | None) -> Image.Image | None:
    version = u16(tile_data, 0) if len(tile_data) >= 2 else 0
    if version == 1:
        return tile_v1_to_image(tile_data, palette_section)
    if version == 3:
        return tile_v3_to_image(tile_data, palette_section)
    return None


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
        return explicit_game

    for candidate in discover_game_paths():
        if is_game_folder(candidate):
            return candidate

    searched = "\n".join(f"  - {path}" for path in discover_game_paths())
    raise SystemExit(
        "Could not find Majesty HD automatically. Use --game with the install folder.\n"
        f"Searched:\n{searched}"
    )


def discover_game_paths() -> list[Path]:
    candidates: list[Path] = []

    env_game = os.environ.get("MAJESTY_HD_DIR")
    if env_game:
        candidates.append(Path(env_game))

    candidates.append(DEFAULT_GAME)

    for steam_root in steam_roots():
        candidates.append(steam_root / "steamapps" / "common" / "Majesty HD")
        library_vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        for library in steam_libraries_from_vdf(library_vdf):
            candidates.append(library / "steamapps" / "common" / "Majesty HD")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def steam_roots() -> list[Path]:
    roots = [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
    ]
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(env_name)
        if root:
            roots.append(Path(root) / "Steam")
    return roots


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
            images = interface_images_for_set(record.data, rel_off, next_off, interface_category, tile_section, splt_section)
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

        export_category = classify_main_sprite_set(category, set_id)
        record_dir = output_root / export_category / folder_name
        directions = parse_directional_frame_descriptor(record.data, rel_off)
        directional_written = 0
        for direction in directions:
            slot = int(direction["slot"])
            for frame_index, tile_index in enumerate(direction["tile_indices"]):
                if tile_index < 0 or tile_index >= len(tile_section.entries):
                    continue
                image = tile_to_image(tile_section.entries[tile_index].data, splt_section)
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
                images = building_state_images_for_set(record.data, rel_off, next_off, tile_section, splt_section)
            else:
                images = interface_images_for_set(record.data, rel_off, next_off, export_category, tile_section, splt_section)
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


def classify_main_sprite_set(category: str, set_id: int) -> str:
    if category.startswith("buildings/") and set_id not in KNOWN_BUILDING_SET_IDS:
        return "other/main"
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
) -> int:
    image_sets = parse_anim_set(record.data)
    if not image_sets:
        return 0

    folder_name = safe_name(record.display_name)
    record_dir = output_root / category / folder_name
    written = 0

    for set_index, (set_id, set_name, rel_off) in enumerate(image_sets):
        next_off = image_sets[set_index + 1][2] if set_index + 1 < len(image_sets) else len(record.data)
        images = interface_images_for_set(record.data, rel_off, next_off, category, tile_section, palette_section)
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
        image = tile_to_image(tile_section.entries[tile_index].data, palette_section)
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
            image = tile_to_image(tile_section.entries[tile_index].data, palette_section)
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


def extract_assets(game: Path, output_root: Path, full: bool, limit: int | None) -> int:
    catalog = parse_catalog(game)
    validate_output_root(game, output_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    total = 0
    records_done = 0

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
            )
            if count:
                total += count
                records_done += 1
                if limit is not None and records_done >= limit:
                    write_manifest(output_root, manifest)
                    create_previews(output_root, manifest)
                    create_guide_art(output_root, manifest)
                    return total

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
                category = "other/interface"
            if category is None:
                category = "other/interface"
            count = export_interface_record(source_label, record, category, tile, effective_palette, output_root, manifest)
            if count:
                total += count
                records_done += 1
                if limit is not None and records_done >= limit:
                    write_manifest(output_root, manifest)
                    create_previews(output_root, manifest)
                    create_guide_art(output_root, manifest)
                    return total

    write_manifest(output_root, manifest)
    create_previews(output_root, manifest)
    create_guide_art(output_root, manifest)
    return total


def validate_output_root(game: Path, output_root: Path) -> None:
    resolved_output = output_root.resolve()
    resolved_game = game.resolve()
    resolved_cwd = Path.cwd().resolve()
    drive_root = Path(resolved_output.anchor).resolve()

    blocked = {drive_root, resolved_game, resolved_game.parent, resolved_cwd, resolved_cwd.parent}
    if resolved_output in blocked:
        raise ValueError(f"Refusing to clear unsafe output folder: {output_root}")


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
        selected = select_preview_rows(rows)
        if not selected:
            continue
        images = []
        for row in selected:
            path = output_root / str(row["png"])
            if not path.exists():
                continue
            try:
                images.append((row, Image.open(path).convert("RGBA")))
            except OSError:
                continue
        if not images:
            continue
        preview = build_contact_sheet(images)
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
    from PIL import ImageDraw

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
        label = f"{row['set']} {row['frame']}"
        draw_label(sheet, label[:24], x + 4, y + cell_h + 2)
    return sheet


def draw_label(image: Image.Image, text: str, x: int, y: int) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.text((x, y), text, fill=(230, 230, 230, 255))


def make_zip(output_root: Path) -> Path:
    archive_base = output_root.parent / output_root.name
    archive_path = shutil.make_archive(str(archive_base), "zip", output_root)
    return Path(archive_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract local Majesty Gold HD art assets to PNG.")
    parser.add_argument("--game", type=Path, help="Majesty Gold HD install folder; auto-discovered if omitted")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder")
    parser.add_argument("--full", action="store_true", help="Also extract uncategorized/main interface records")
    parser.add_argument("--limit", type=int, help="Stop after this many IMAG records with extracted PNGs")
    parser.add_argument("--zip", action="store_true", help="Create a local zip next to the output folder")
    args = parser.parse_args()

    game = resolve_game_path(args.game)
    output = args.out if args.out.is_absolute() else TOOL_ROOT / args.out

    total = extract_assets(game, output, args.full, args.limit)
    print(f"Game folder: {game}")
    print(f"Extracted {total} PNG files to {output}")
    if args.zip:
        zip_path = make_zip(output)
        print(f"Wrote local zip: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
