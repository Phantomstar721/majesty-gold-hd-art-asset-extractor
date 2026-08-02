#!/usr/bin/env python3
"""Export one animation of a Majesty unit as a single sprite sheet plus a
manifest describing which source tile each cell came from.

Frames are laid out one direction per row, aligned on the hotspot the archive
stores, so the sheet reads the way the animation plays rather than as a pile of
separately cropped tiles.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from imaging import Image  # noqa: E402

from extract_assets import (  # noqa: E402
    decode_tile_v3,
    get_sections,
    is_palette_key_color,
    load_palette,
    parse_anim_set,
    parse_directional_frame_descriptor,
    read_cam,
    resolve_game_path,
    safe_name,
    u16,
    u32,
)


def header_words(tile_data: bytes) -> dict[str, int]:
    """The TILE header fields this exporter needs."""
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


def render_tile_full(
    tile_data: bytes,
    palette: list[tuple[int, int, int]] | None,
    *,
    drop_shadow: bool = True,
) -> Image.Image | None:
    """Render a TILE v3 onto its full canvas without cropping to content.

    The extractor's own renderer crops to the visible bounding box, which is
    right for a standalone PNG but wrong here: every frame of an animation has
    to stay on a common canvas or the sheet will not line up.
    """
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
                red, green, blue = palette[index]
                if drop_shadow and is_palette_key_color(index, red, green, blue):
                    continue
                image.putpixel((x, y), (red, green, blue, 255))
    return image


def find_imag_entry(imag, prefix: str):
    prefix = prefix.upper()
    for entry in imag.entries:
        name = entry.display_name
        if name.upper().startswith(prefix):
            return entry, name
    return None, None


def build_sheet(
    frames: list[dict],
    cell_w: int,
    cell_h: int,
    cols: int,
    rows: int,
) -> Image.Image:
    sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h), (0, 0, 0, 0))
    for frame in frames:
        img: Image.Image = frame["image"]
        x = frame["col"] * cell_w + frame["paste_x"]
        y = frame["row"] * cell_h + frame["paste_y"]
        sheet.alpha_composite(img, (x, y))
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description="Export IMAG animation to sprite sheet + JSON")
    parser.add_argument("--game", type=Path, default=None, help="Majesty HD install folder")
    parser.add_argument("--cam", type=Path, default=None, help="Override maindata.cam path")
    parser.add_argument("--record", required=True, help="IMAG record prefix, e.g. AVB1")
    parser.add_argument("--set", default="Stand", help="Image set name or numeric setID (default Stand)")
    parser.add_argument("--out", type=Path, required=True, help="Output folder")
    parser.add_argument(
        "--keep-shadow",
        action="store_true",
        help="Keep sprite shadow indices 247-250 and magenta key ramps",
    )
    args = parser.parse_args()

    if args.cam is not None:
        cam_path = args.cam
    else:
        game = resolve_game_path(args.game)
        cam_path = game / "Data" / "maindata.cam"
    if not cam_path.exists():
        print(f"CAM not found: {cam_path}")
        return 1

    archive = read_cam(cam_path)
    imag, tile, splt = get_sections(archive)
    if imag is None or tile is None or splt is None:
        print("CAM missing IMAG/TILE/SPLT")
        return 1

    entry, record_name = find_imag_entry(imag, args.record)
    if entry is None:
        print(f"IMAG record not found: {args.record}")
        return 1

    anim_sets = parse_anim_set(entry.data)
    set_key = args.set
    chosen = None
    if set_key.isdigit():
        set_id = int(set_key)
        chosen = next((s for s in anim_sets if s[0] == set_id), None)
    else:
        chosen = next((s for s in anim_sets if s[1].lower() == set_key.lower()), None)
    if chosen is None:
        names = ", ".join(f"{sid}:{name}" for sid, name, _ in anim_sets)
        print(f"Image set not found: {args.set}. Available: {names}")
        return 1

    set_id, set_name, rel_off = chosen
    directions = parse_directional_frame_descriptor(entry.data, rel_off)
    if not directions:
        print("No directional frames parsed for that set")
        return 1

    # Collect rendered frames and geometry
    raw_frames: list[dict] = []
    for direction in directions:
        slot = int(direction["slot"])
        x_off = int(direction["x_off"])
        y_off = int(direction["y_off"])
        for frame_idx, tile_index in enumerate(direction["tile_indices"]):
            if tile_index < 0 or tile_index >= len(tile.entries):
                continue
            tile_data = tile.entries[tile_index].data
            hdr = header_words(tile_data)
            palette = load_palette(splt, hdr["palette_id"])
            image = render_tile_full(tile_data, palette, drop_shadow=not args.keep_shadow)
            if image is None:
                continue
            raw_frames.append(
                {
                    "dir": slot,
                    "frame": frame_idx,
                    "tile_index": tile_index,
                    "x_off": x_off,
                    "y_off": y_off,
                    "tile_w": image.width,
                    "tile_h": image.height,
                    "palette_id": hdr["palette_id"],
                    "header": hdr,
                    "image": image,
                }
            )

    if not raw_frames:
        print("No frames decoded")
        return 1

    # Shared cell using hotspot alignment: blit at (anchor + hotspot)
    min_x_off = min(f["x_off"] for f in raw_frames)
    min_y_off = min(f["y_off"] for f in raw_frames)
    anchor_x = -min_x_off
    anchor_y = -min_y_off
    cell_w = max(anchor_x + f["x_off"] + f["tile_w"] for f in raw_frames)
    cell_h = max(anchor_y + f["y_off"] + f["tile_h"] for f in raw_frames)

    dirs = sorted({f["dir"] for f in raw_frames})
    max_frames = max(f["frame"] for f in raw_frames) + 1
    dir_to_row = {d: i for i, d in enumerate(dirs)}

    for frame in raw_frames:
        frame["row"] = dir_to_row[frame["dir"]]
        frame["col"] = frame["frame"]
        frame["paste_x"] = anchor_x + frame["x_off"]
        frame["paste_y"] = anchor_y + frame["y_off"]

    cols = max_frames
    rows = len(dirs)
    sheet = build_sheet(raw_frames, cell_w, cell_h, cols, rows)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{safe_name(record_name)}_{safe_name(set_name)}"
    sheet_path = out_dir / f"{stem}_sheet.png"
    json_path = out_dir / f"{stem}_sheet.json"
    sheet.save(sheet_path)

    meta = {
        "record": record_name,
        "record_prefix": args.record,
        "cam": str(cam_path),
        "set_id": set_id,
        "set_name": set_name,
        "cell_w": cell_w,
        "cell_h": cell_h,
        "cols": cols,
        "rows": rows,
        "layout": "rows=directions, cols=frames",
        "anchor_x": anchor_x,
        "anchor_y": anchor_y,
        "keep_shadow": bool(args.keep_shadow),
        "sheet_png": sheet_path.name,
        "frames": [
            {
                "col": f["col"],
                "row": f["row"],
                "dir": f["dir"],
                "frame": f["frame"],
                "tile_index": f["tile_index"],
                "x_off": f["x_off"],
                "y_off": f["y_off"],
                "tile_w": f["tile_w"],
                "tile_h": f["tile_h"],
                "paste_x": f["paste_x"],
                "paste_y": f["paste_y"],
                "palette_id": f["palette_id"],
                "header": f["header"],
            }
            for f in raw_frames
        ],
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {sheet_path} ({sheet.size[0]}x{sheet.size[1]})")
    print(f"Wrote {json_path} ({len(raw_frames)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
