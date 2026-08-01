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

The modern lightweight window auto-detects Majesty Gold HD, presents the three
modes as detailed cards, and shows a conservative output estimate alongside
free disk space. Progress and source-audit status stay visible while the
technical log opens separately on demand. The default output is `output\assets`
beside the tool.

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
.\.venv\Scripts\python scripts\extract_assets.py --yes
.\run_extractor.cmd --zip
```

`--full` remains as a backwards-compatible alias for `--mode all-raw`.
`--yes` skips the confirmation shown before an existing output folder is
cleared. `--limit` is a quick sample: it stops early, so it skips presentation
art and the source-pixel audit, and it tells you so.

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

### The output folder is emptied

Generated output goes under `output/` by default and is gitignored.

**Everything in the output folder is deleted at the start of every run.** Three
separate checks stand in front of that:

- Drive roots, Windows system folders, and profile folders such as Documents,
  Desktop and Downloads are refused outright.
- The game installation is refused, along with anything inside it and any
  folder that contains it.
- An existing folder is only cleared when it carries this tool's marker file,
  written by a previous run. **A folder holding your own files is refused**
  rather than emptied, so a mistyped path cannot cost you anything.

The GUI asks before replacing a non-empty folder. The command line asks too,
listing what would be removed; pass `--yes` to skip the prompt in a script.

### Source-pixel audit

A full extraction finishes with a source-pixel occupancy audit. For each
TILE-derived PNG it independently counts the pixels encoded in the archive's v3
RLE runs or v1 raster, then checks the PNG's alpha count against it. Extraction
fails loudly if the renderer drops a stored value, including an explicit
palette-index-zero pixel, or invents an opaque pixel.

Two honest limits. The audit applies the same transparency rules the renderer
does, so it proves the renderer is faithful to those rules rather than proving
the rules are right; it catches dropped and invented pixels, not a wrong policy.
And `--limit` runs stop before it, which they now say out loud.

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

## Tests

The decoders, the output-folder guard and the category routing have unit tests
that need neither the game nor a network:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

## Scope: this tool only reads

The extractor reads your installation and writes PNGs. It does not write to the
game, encode TILEs, or patch CAM archives, and it depends on no other
repository. Cloning this one is enough to run everything in it.

## TILE format

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

16-bit RGB565 art has no alpha channel and no transparent-index field, so
`0x0000` is ambiguous: pure black in a background, or the cutout in a sprite
layer. It is resolved by output category. Backgrounds keep their black; sprite
layers keep their silhouette. Reading it as transparent everywhere punched
17,801 holes through the main menu backdrop while leaving the pixels one step
off black untouched.

See [docs/TILE_V3_RLE_ROOT_CAUSE.md](docs/TILE_V3_RLE_ROOT_CAUSE.md).

### Sprite sheet export

One animation of one unit, laid out a direction per row and aligned on the
hotspots stored in the archive, with a JSON manifest naming the source tile
behind every cell:

```powershell
.\.venv\Scripts\python scripts\export_sprite_sheet.py --record AVB1 --set Stand --out output\sheets\AVB1_Stand
```
