#!/usr/bin/env python3
"""Import an AI-edited sprite sheet back into TILE bins (exclusive-end X encode)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLKIT = SCRIPT_DIR.resolve().parents[1] / "Majesty-ModdingToolkit"
sys.path.insert(0, str(SCRIPT_DIR))
if TOOLKIT.is_dir():
    sys.path.insert(0, str(TOOLKIT))

from extract_assets import get_sections, load_palette, read_cam  # noqa: E402
from sprite_codec import encode_tile_v3, quantize_rgba_to_palette  # noqa: E402


def patch_cam(cam_path: Path, replacements: dict[int, bytes], output: Path) -> None:
    """Replace TILE entries and write a new CAM (requires toolkit cam_writer)."""
    from cam_reader import read_cam as toolkit_read_cam
    from cam_writer import repack_cam

    cam_data = cam_path.read_bytes()
    sections = toolkit_read_cam(cam_data)
    # section index 1 is TILE in maindata.cam
    packed = { (1, idx): data for idx, data in replacements.items() }
    output.write_bytes(repack_cam(cam_data, sections, packed))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import sprite sheet JSON+PNG to TILE bins / CAM")
    parser.add_argument("--sheet-json", type=Path, required=True, help="Sidecar JSON from export_sprite_sheet")
    parser.add_argument("--sheet-png", type=Path, default=None, help="Edited sheet PNG (default: path in JSON)")
    parser.add_argument("--cam", type=Path, default=None, help="Source CAM for palettes (default: JSON cam)")
    parser.add_argument("--out-tiles", type=Path, required=True, help="Folder for encoded .tile binaries")
    parser.add_argument("--output-cam", type=Path, default=None, help="Optional patched CAM output path")
    parser.add_argument("--preserve-shadow-indices", action="store_true",
                        help="Allow quantization into sprite shadow indices 247-250 when nearest")
    args = parser.parse_args()

    meta = json.loads(args.sheet_json.read_text(encoding="utf-8"))
    sheet_png = args.sheet_png
    if sheet_png is None:
        sheet_png = args.sheet_json.with_name(meta["sheet_png"])
    if not sheet_png.exists():
        print(f"Sheet PNG not found: {sheet_png}")
        return 1

    cam_path = args.cam or Path(meta["cam"])
    archive = read_cam(cam_path)
    _, tile_section, splt = get_sections(archive)
    if tile_section is None or splt is None:
        print("CAM missing TILE/SPLT")
        return 1

    sheet = Image.open(sheet_png).convert("RGBA")
    cell_w = int(meta["cell_w"])
    cell_h = int(meta["cell_h"])
    expected_w = int(meta["cols"]) * cell_w
    expected_h = int(meta["rows"]) * cell_h
    if sheet.size != (expected_w, expected_h):
        print(
            f"WARNING: sheet size {sheet.size} != expected ({expected_w}, {expected_h}). "
            "Cells will still be sliced by JSON grid; resize the sheet if needed."
        )

    args.out_tiles.mkdir(parents=True, exist_ok=True)
    replacements: dict[int, bytes] = {}
    manifest = []

    for frame in meta["frames"]:
        col = int(frame["col"])
        row = int(frame["row"])
        paste_x = int(frame["paste_x"])
        paste_y = int(frame["paste_y"])
        tile_w = int(frame["tile_w"])
        tile_h = int(frame["tile_h"])
        tile_index = int(frame["tile_index"])
        palette_id = int(frame["palette_id"])
        header = frame["header"]

        cell = sheet.crop((col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h))
        # Extract the original tile canvas region from the cell
        region = cell.crop((paste_x, paste_y, paste_x + tile_w, paste_y + tile_h))
        if region.size != (tile_w, tile_h):
            print(f"FAIL tile {tile_index}: cropped size {region.size}")
            return 1

        palette = load_palette(splt, palette_id)
        if palette is None:
            print(f"FAIL tile {tile_index}: palette {palette_id}")
            return 1

        indices = quantize_rgba_to_palette(
            region,
            palette,
            preserve_shadow_indices=args.preserve_shadow_indices,
        )
        encoded = encode_tile_v3(
            indices,
            palette_id,
            header_w2=int(header.get("width", tile_w)),
            header_w3=int(header.get("w3", 0)),
            header_w4=int(header.get("w4", 32)),
            header_w5=int(header.get("w5", 0)),
            header_w6=int(header.get("w6", 0)),
            header_w7=int(header.get("w7", 1)),
        )

        out_bin = args.out_tiles / f"tile_{tile_index:05d}.tile"
        out_bin.write_bytes(encoded)
        replacements[tile_index] = encoded
        manifest.append(
            {
                "tile_index": tile_index,
                "bin": out_bin.name,
                "dir": frame["dir"],
                "frame": frame["frame"],
                "bytes": len(encoded),
            }
        )
        print(f"Encoded TILE[{tile_index}] -> {out_bin} ({len(encoded)} bytes)")

    man_path = args.out_tiles / "import_manifest.json"
    man_path.write_text(json.dumps({"source_sheet": str(sheet_png), "tiles": manifest}, indent=2), encoding="utf-8")
    print(f"Wrote {man_path}")

    if args.output_cam is not None:
        if not TOOLKIT.is_dir():
            print("Majesty-ModdingToolkit not found next to extractor; cannot patch CAM")
            return 1
        patch_cam(cam_path, replacements, args.output_cam)
        print(f"Wrote patched CAM {args.output_cam}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
