# AI Sprite Re-art Workflow

Goal: take a **correctly decoded** Majesty sprite sheet, regenerate art (AI or hand), and encode it back so the game renders clean frames — not the old X-sheared garbage.

Prerequisite: TILE v3 exclusive-end X fix. See [TILE_V3_RLE_ROOT_CAUSE.md](TILE_V3_RLE_ROOT_CAUSE.md).

## Pipeline

```text
maindata.cam (IMAG + TILE + SPLT)
        │
        ▼
export_sprite_sheet.py   →  sheet PNG + JSON sidecar
        │
        ▼
AI / editor (same grid, same pivots)
        │
        ▼
import_sprite_sheet.py   →  .tile bins  (+ optional patched CAM)
        │
        ▼
In-game smoke test / re-extract
```

## 1. Export a sheet

```powershell
cd majesty-gold-hd-art-asset-extractor
python scripts/export_sprite_sheet.py --record AVB1 --set Stand --out output/reart/AVB1_Stand
```

Outputs:

- `AVB1Barbarian_Stand_sheet.png` — directions as rows, frames as columns
- `AVB1Barbarian_Stand_sheet.json` — cell size, hotspots, tile indices, palette ids, header words, paste offsets

Frames are placed on a **shared cell** using IMAG hotspots so feet/pivots line up across directions.

Optional: `--keep-shadow` to leave sprite indices 247–250 and magenta key ramps visible (engine transition/shadow/blend controls).

## 2. AI / edit constraints

Prompt the model (or constrain your edit) to:

- Keep the **same sheet dimensions** and cell grid (do not rearrange rows/cols).
- Keep silhouettes roughly aligned to the existing pivots (do not slide characters inside cells).
- Preserve 8-direction consistency and animation readability.
- Opaque body on transparent background (no baked checkerboard).
- Prefer flat / limited colors; avoid heavy JPEG noise and subpixel anti-alias mush.
- Do **not** invent an isometric shear into the pixels — the game already draws upright sprites on an isometric map.

## 3. Import / encode

```powershell
python scripts/import_sprite_sheet.py `
  --sheet-json output/reart/AVB1_Stand/AVB1Barbarian_Stand_sheet.json `
  --sheet-png  output/reart/AVB1_Stand/AVB1Barbarian_Stand_sheet.png `
  --out-tiles  output/reart/AVB1_Stand/tiles
```

This:

1. Slices each cell using JSON paste boxes / tile sizes.
2. Quantizes to the original SPLT palette for that tile.
3. Encodes TILE v3 with **exclusive-end X**.
4. Writes `tile_XXXXX.tile` plus `import_manifest.json`.

Optional CAM patch (requires sibling `Majesty-ModdingToolkit`):

```powershell
python scripts/import_sprite_sheet.py `
  --sheet-json ... `
  --out-tiles output/reart/AVB1_Stand/tiles `
  --output-cam output/reart/AVB1_Stand/maindata_modded.cam
```

Or replace tiles one-by-one with the toolkit:

```powershell
cd ..\Majesty-ModdingToolkit
python cam_writer.py --cam "...\maindata.cam" --replace-tile 3794 path\to\tile_03794.tile --output modded.cam
```

## 4. Verify

1. Re-decode the new `.tile` (or run the extractor against the patched CAM).
2. Confirm geometry matches the edited sheet cells.
3. Drop the modded CAM into a safe mod/test setup and check the unit in game.

## Design rules (v1)

| Rule | Why |
|------|-----|
| Sheet-first | AI keeps style + pivots consistent across directions/frames |
| Preserve IMAG tile indices / hotspots | Avoid rewriting animation tables |
| Quantize to SPLT on import | Game is 8-bit indexed |
| Exclusive-end encode | Engine expects end columns; start encoding recreates garbage |

## Out of scope (v1)

- Training a custom model
- Changing frame counts or direction tables
- Automatic HD upscalers beyond “edit this sheet”
