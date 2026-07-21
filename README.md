# Majesty Gold HD Asset Spelunker

Local-only extractor for making a private PNG reference library from an
installed copy of **Majesty Gold HD**.

This repo contains tooling only. Do not commit extracted game art, generated
PNGs, or packaged asset zips.

## Scope

The extractor focuses on art that is useful for modding and reference:

- Hero profile portraits, small hero icons, and hero sprites
- Monster profile art, small monster icons, and monster sprites
- Building profile art, small building icons, and building/lair sprites
- Weapon, armor, item, and spell icons
- Spell, projectile, and overlay effect sprites

It intentionally avoids broad menu dumps, dialog-panel chrome, terrain, and map
tiles unless a specific interface record is needed for icons or profile art.

## Setup

```powershell
cd C:\Users\bterr\source\repos\majesty-gold-hd-asset-spelunker
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Extract

```powershell
.\.venv\Scripts\python scripts\extract_assets.py
```

By default the script looks for the Steam install at:

`C:\Program Files (x86)\Steam\steamapps\common\Majesty HD`

Useful options:

```powershell
.\.venv\Scripts\python scripts\extract_assets.py --game "D:\SteamLibrary\steamapps\common\Majesty HD"
.\.venv\Scripts\python scripts\extract_assets.py --out output\assets --zip
.\.venv\Scripts\python scripts\extract_assets.py --limit 5
.\.venv\Scripts\python scripts\extract_assets.py --full
```

Generated output goes under `output/` by default and is gitignored. The
extractor clears the selected output folder each run, and refuses obvious unsafe
targets such as the game folder or repo root.

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
  _manifest.csv
```

Each extracted record gets its own folder. Animation frames are saved as PNGs
with the image-set name, direction slot, frame number, and source TILE index in
the filename.

## Notes

This uses the same reverse-engineered CAM, IMAG, TILE, and SPLT format knowledge
captured in the local BrandonWill Majesty reference repo and our
`majesty-cam-tool` work. It is currently an extraction/reference workflow, not a
general-purpose editor.
