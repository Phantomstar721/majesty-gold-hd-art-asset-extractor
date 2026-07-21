# Majesty Gold HD Art Asset Extractor

Local-only extractor for making a private PNG reference library from an
installed copy of **Majesty Gold HD**.

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

Known assets are sorted into specific folders. Records that can be decoded but
do not match a known category are kept under `other/` instead of being thrown
away.

## Setup

```powershell
cd C:\Users\bterr\source\repos\majesty-gold-hd-art-asset-extractor
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
  other/main/
  other/interface/
  _previews/
  guide_art/
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
Those are preserved under `other/main/` instead of being mixed into the
human-readable `buildings/sprites/` folders.

`guide_art/` contains convenience picks for local guide/reference use:

- `guide_art/profiles/` prefers profile/dialog art when the game has it.
- `guide_art/sprites/` picks one representative transparent sprite frame.
- `guide_art/sprite_cards/` places that representative sprite on a neutral
  background so shadows and dark pixels are easier to read.

These guide images are still generated from extracted assets, not screenshots.
They do not fully reproduce Majesty's renderer, especially for placed buildings
whose shadows/blend pixels are treated specially in game.

## Notes

This uses the same reverse-engineered CAM, IMAG, TILE, and SPLT format knowledge
captured in the local BrandonWill Majesty reference repo and our
`majesty-cam-tool` work. It is currently an extraction/reference workflow, not a
general-purpose editor.
