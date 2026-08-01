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
- Main menus, options, quest selection, and other full-screen interface art
- Quest maps and animated quest-segue illustrations
- Cinematic sample frames and contact sheets
- Base and expansion loading screens

Known assets are sorted into specific folders. Unknown main/interface records
and most extra animation frames are skipped by default because they produce a
large amount of noisy output; use `--mode all-raw` if you want exhaustive dumps under
`other/main/` and `other/interface/`.

## Setup

```powershell
cd path\to\majesty-gold-hd-art-asset-extractor
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

On Windows, double-click `run_extractor.cmd`. It creates/uses a small local
virtual environment and opens the extractor window:

```powershell
.\run_extractor.cmd
```

The window auto-detects Majesty Gold HD, lets you choose an output folder and
one of three extraction modes, shows a conservative space estimate and free
disk space, and keeps a live progress log. The default output is
`output\assets` beside the tool.

### Extraction modes

1. **All raw content** exports every recognized frame, support layer, and
   uncategorized art record. Palette-control pixels are left visible. This is
   the slowest and largest option.
2. **Relevant sprites and menu art (raw)** keeps useful sprites, menus, maps,
   cinematics, segues, and loading screens but leaves Majesty's raw
   shadow/blend/transition palette colors visible.
3. **Relevant art (clean PNGs)** is the default. It keeps useful sprites,
   effects, profiles, icons, menus, maps, cinematics, segues, and loading
   screens while making engine-only controls transparent in sprite palettes.
   Profiles, icons, effects, and presentation/UI palettes are preserved because
   their high indices are real colors rather than sprite shadow controls.

Here, “raw” means a directly decoded PNG, not a proprietary `.TILE` file. PNGs
remain easy to inspect while faithfully showing the pixels stored for the game
engine.

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
.\.venv\Scripts\python scripts\extract_assets.py --mode relevant-raw
.\.venv\Scripts\python scripts\extract_assets.py --mode all-raw
.\.venv\Scripts\python scripts\extract_assets.py --limit 5
.\run_extractor.cmd --zip
```

`--full` remains as a backwards-compatible alias for `--mode all-raw`.

The default run is curated. It exports profile art, icons, representative
hero/monster/building/lair sprites, spell effects, presentation art, `_previews/`,
and `_manifest.csv`. Cinematics become playable H.264 MP4 videos as well as
twelve evenly spaced full-resolution PNG samples and contact sheets. Raw modes
also retain the original embedded `.bik` cinematics. Quest-map movies become
twelve samples plus contact sheets; this captures their visual sequence without
dumping every near-duplicate frame. Use `--mode all-raw` when you want the large
exhaustive dump of sprite animation frames, support layers, and uncategorized
records.

The MP4s include their in-game sound. MV02, MV04, and MV07 carry native Bink
audio, which is preserved and converted to AAC. MV01 and MV06 are silent credit
reels in the archives; Majesty plays the menu's `GeneralTheme.mp3` alongside
them at runtime, so the extractor adds that theme to those two MP4s and trims
it at the end of the video. Raw modes still preserve the untouched `.bik`
files, including their original audio-stream layout.

Generated output goes under `output/` by default and is gitignored. The GUI asks
before replacing a non-empty output folder. The command-line extractor clears
the selected output folder each run. Both refuse obvious unsafe targets such as
the game folder or repo root.

Every normal extraction now finishes with a source-pixel occupancy audit. For
each TILE-derived PNG, it independently counts pixels encoded in the archive's
v3 RLE runs or v1 raster and verifies the PNG alpha count after only the
category's documented transparency/control rules. Extraction fails loudly if
the renderer drops a stored value—including an explicit palette-index-zero
pixel—or invents an opaque pixel.

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
  menus/
  maps/interface/
  maps/quest/
  cinematics/              # MP4 + samples; raw modes also include BIK
  segues/
  loading_screens/
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
human-readable `buildings/sprites/` folders. Use `--mode all-raw` to keep those records
under `other/main/`.

## TILE format / AI re-art

TILE v3 RLE stores each opaque run's **exclusive end** column (not start). Its
packed run word uses eleven low count bits and upper flag bits, allowing wide
menu rows; palette-less variants store RGB565 pixels instead of indices. Gaps
between runs are transparent, while every explicitly stored value—including
palette index zero—is artwork. Clean
sprite extraction treats index `247` as the transition/seam control and
`248-250` as shadow bands, as confirmed by Phantom's Haunt. Magenta key ramps
are also removed by color. Indices `251-254` remain visible when they hold
ordinary colors, as they do in the Gazebo's white highlights. Full-screen
Profiles, icons, effects, and sepia/menu palettes use the high range as ordinary
colors and therefore retain it. Indexed UI and presentation art is also checked
for a legacy transparent-index collision: only pixels connected to the image
edge remain transparent, while enclosed artwork pixels are restored. Indexed,
full-background profile portraits are decoded as opaque full-palette paintings
rather than applying sprite shadow/control-index removal to their facial colors.
See:

- [docs/TILE_V3_RLE_ROOT_CAUSE.md](docs/TILE_V3_RLE_ROOT_CAUSE.md)
- [docs/AI_SPRITE_REART_WORKFLOW.md](docs/AI_SPRITE_REART_WORKFLOW.md)

Helpers:

```powershell
python scripts/export_sprite_sheet.py --record AVB1 --set Stand --out output/reart/AVB1_Stand
python scripts/import_sprite_sheet.py --sheet-json output/reart/AVB1_Stand/AVB1Barbarian_Stand_sheet.json --out-tiles output/reart/AVB1_Stand/tiles
```
