# Majesty Gold HD Art Asset Extractor

Tooling for making a private PNG reference library from an installed copy of
**Majesty Gold HD**.

**Important:** this repository contains tooling only. It does not include,
redistribute, or publish Majesty game assets. The extractor reads files from
your own local Majesty HD installation and writes private local output under
`output/`, which is gitignored.

## Scope

The extractor focuses on art that is useful for modding and reference:

- Hero profile portraits, small hero icons, and hero sprites
- Monster profile art, small monster icons, and monster sprites
- Building profile art, small building icons, and building/lair sprites
- Weapon, armor, item, and spell icons
- Spell, projectile, and overlay effect sprites

Known assets are sorted into specific folders. Unknown main/interface records
and most extra animation frames are skipped by default because they produce a
large amount of noisy output; use `--full` if you want exhaustive dumps under
`other/main/` and `other/interface/`.

## Setup

```powershell
cd path\to\majesty-gold-hd-art-asset-extractor
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

On Windows, `run_extractor.cmd` will create/use `.venv`, install requirements,
and run the extractor:

```powershell
.\run_extractor.cmd
```

## Extract

```powershell
.\.venv\Scripts\python scripts\extract_assets.py
```

By default the script auto-discovers Majesty HD from:

- `MAJESTY_HD_DIR`, if that environment variable is set
- the default Steam path, `C:\Program Files (x86)\Steam\steamapps\common\Majesty HD`
- Steam library folders listed in `steamapps\libraryfolders.vdf`

By default, generated output goes to `output\assets` next to the unpacked
extractor folder. In other words, if you unzip this tool to
`D:\Tools\majesty-gold-hd-art-asset-extractor`, the default output is
`D:\Tools\majesty-gold-hd-art-asset-extractor\output\assets`.

Useful options:

```powershell
.\.venv\Scripts\python scripts\extract_assets.py --game "D:\SteamLibrary\steamapps\common\Majesty HD"
.\.venv\Scripts\python scripts\extract_assets.py --out output\assets --zip
.\.venv\Scripts\python scripts\extract_assets.py --limit 5
.\.venv\Scripts\python scripts\extract_assets.py --full
.\run_extractor.cmd --zip
```

The default run is intentionally fast and curated. It exports profile art,
icons, representative hero/monster/building/lair sprites, representative spell
effects, `_previews/`, and `_manifest.csv`. Use `--full` only when you want the
large exhaustive dump of all animation frames, support layers, and uncategorized
records.

Generated output goes under `output/` by default and is gitignored. The extractor
clears the selected output folder each run, and refuses obvious unsafe targets
such as the game folder or repo root.

`--zip` creates a local zip next to the output folder. Keep that zip private
unless you have permission to redistribute the extracted assets.

## Output Layout

```text
output/assets/
  heroes/sprites/
  monsters/sprites/
  buildings/sprites/
  buildings/lairs/
  spell_effects/
  icons/heroes/
  icons/monsters/
  icons/buildings/
  icons/weapons/
  icons/armor/
  icons/items/
  icons/spells/
  profile_art/heroes/
  profile_art/monsters/
  profile_art/buildings/
  _previews/
  _manifest.csv
```

Each extracted record gets its own folder. Animation frames are saved as PNGs
with the image-set name, direction slot, frame number, and source TILE index in
the filename.

`_previews/` contains quick contact-sheet PNGs for sprite-heavy records. These
are not perfect in-game reconstructions, but they upscale representative
standing/active/build frames so a human can quickly recognize a hero, monster,
building, lair, or effect without opening dozens of tiny frame files.

Placed building art is mostly stored as non-directional TILE references rather
than hero-style directional animation frames. The extractor handles both paths:
directional records become frame PNGs, and non-directional building states
become variant PNGs such as `Active_variant00_tile00931.png`.

Building records also contain many numeric image sets that appear to be support
layers, masks, rubble pieces, animation internals, or other not-yet-named data.
Those are skipped during normal extraction instead of being mixed into the
human-readable `buildings/sprites/` folders. Use `--full` to keep those records
under `other/main/`.

## TILE format / AI re-art

TILE v3 RLE stores each opaque run's **exclusive end** column (not start). See:

- [docs/TILE_V3_RLE_ROOT_CAUSE.md](docs/TILE_V3_RLE_ROOT_CAUSE.md)
- [docs/AI_SPRITE_REART_WORKFLOW.md](docs/AI_SPRITE_REART_WORKFLOW.md)

Helpers:

```powershell
python scripts/export_sprite_sheet.py --record AVB1 --set Stand --out output/reart/AVB1_Stand
python scripts/import_sprite_sheet.py --sheet-json output/reart/AVB1_Stand/AVB1Barbarian_Stand_sheet.json --out-tiles output/reart/AVB1_Stand/tiles
```
