# Majesty Gold HD Art Asset Extractor

Turn your own copy of **Majesty Gold HD** into an organised folder of PNG
images: hero and monster sprites, building art, portraits, icons, spell
effects, menus, maps, loading screens and cinematics.

**This repository contains tooling only.** It includes no Majesty game assets
and redistributes none. It reads the copy of the game you already own and
writes to your own machine. Extracted art belongs to the game's owners; keep it
to yourself unless you have permission to share it.

## Getting started

Download `Majesty Art Extractor.exe`, put it in a folder of its own, and
double-click it.

**Nothing to install.** No Python, no pip, no setup. Everything the tool needs
is inside that one file.

The window finds your Majesty installation on its own, offers three levels of
extraction, and shows how much space each will take against the free space on
the drive you have chosen.

### Running from source instead

If you would rather run the Python directly, clone the repository and use the
launcher:

```powershell
.\run_extractor.cmd
```

That needs Python 3.9 or newer and nothing else. If Python is missing, the
launcher offers to install it.

## The three modes

| Mode | What you get |
| --- | --- |
| **Clean art** | Sprites with tidy transparent edges, ready to use. The default. |
| **Untouched colours** | The same pictures exactly as the game stores them, nothing made transparent. |
| **Everything** | All extractable art and animation: every frame, internal art layers and unidentified artwork. Much larger. |

The one idea worth knowing: **the game hides shadow and blending information
inside sprite colours.** Clean art turns those into transparency, which is what
gives sprites their tidy edges. Portraits, icons and menus keep every colour,
because in those the same values are ordinary art rather than instructions.

Untouched colours leaves all of it visible, which is useful if you want to see
what is genuinely stored rather than a tidied picture.

## Cinematics

Majesty stores cinematics and the animated quest maps as Bink video, which
needs FFmpeg. Everything else, including segues and interface maps, extracts
without it.

There is a tick-box for this in the window. It starts switched on if FFmpeg is
already on your machine, and off otherwise. Switch it on and, if you do not
have FFmpeg, you are shown the exact address it would be downloaded from, how
large it is, and where it would be saved, before anything is fetched. Decline
and the rest of the extraction runs normally.

Cinematics become playable MP4 videos with their in-game sound, plus twelve
evenly spaced full-resolution stills and a contact sheet. Quest maps become
stills and contact sheets, which captures the sequence without saving hundreds
of near-identical frames.

## Where the art goes

By default, an `output\assets` folder beside the tool. You can point it
anywhere.

```text
output/assets/
  heroes/sprites/          monsters/sprites/
  buildings/sprites/       buildings/lairs/
  spell_effects/
  icons/heroes/            icons/monsters/      icons/buildings/
  icons/weapons/           icons/armor/         icons/items/     icons/spells/
  profile_art/heroes/      profile_art/monsters/  profile_art/buildings/
  menus/                   maps/interface/      maps/quest/
  cinematics/              segues/              loading_screens/
  _previews/
  _manifest.csv
```

Every record gets its own folder. Animation frames are named with the
animation, direction, frame number and the source tile they came from, so a
file can always be traced back.

`_previews/` holds contact sheets for the sprite-heavy records. They are not
in-game reconstructions; they enlarge a few representative frames so you can
recognise a hero or building at a glance instead of opening dozens of tiny
files.

`_manifest.csv` lists every image with its category, source archive, record and
tile index.

### The output folder is emptied

**Everything in the output folder is deleted at the start of every run**, so it
can be rebuilt cleanly.

Folders that could only ever be a mistake are refused outright: drive roots,
Windows and Program Files, your user folder, Documents, Desktop, Downloads
themselves, and the game installation or anything containing it.

Any other folder is your choice. If it already holds files the tool did not put
there, you are shown what is in it and asked before a single file is removed.
Once a run finishes, the folder is marked as the tool's own and you are not
asked again.

## Every image is checked

After extracting, the tool independently re-reads the game archives, counts the
pixels each image should contain, and compares that against the PNG it wrote.
If anything was dropped or invented, the run fails and says so rather than
quietly handing you damaged art.

Worth being clear about what that proves: the check applies the same rules the
decoder does, so it catches lost and invented pixels, not a rule that is wrong
in the first place. Quick sample runs (`--limit`) stop before it and say so.

## Command line

The packaged executable is intended for the graphical window. Because it is a
Windows GUI application, a command shell does not wait for it like a normal
console program. For reliable command-line use, run the source launcher:

```powershell
.\run_extractor.cmd --out D:\art
.\run_extractor.cmd --game "D:\SteamLibrary\steamapps\common\Majesty HD"
.\run_extractor.cmd --mode all-raw --cinematics
.\run_extractor.cmd --limit 5
```

The same options also work through `py -3 scripts\extract_assets.py`.

| Option | Effect |
| --- | --- |
| `--game` | Where Majesty is installed, if it is not found automatically |
| `--out` | Where to write the art |
| `--mode` | `relevant-art` (default), `relevant-raw`, or `all-raw` |
| `--cinematics` | Include cinematics and quest maps; offers to fetch FFmpeg if needed |
| `--download-ffmpeg` | Include cinematics and, if needed, download FFmpeg without asking |
| `--limit N` | Stop after N records. A quick sample: skips video and the image check |
| `--zip` | Also write a zip beside the output folder |
| `--yes` | Do not ask before clearing the output folder |

`--full` still works as an older name for `--mode all-raw`.

The game is found automatically from `MAJESTY_HD_DIR`, the Steam registry
entry, the default Steam path, and any Steam library folders you have
configured, including installs whose folder has been renamed.

## Sprite sheets

One animation of one unit on a single sheet, a direction per row, aligned on
the hotspots stored in the archive, with a manifest naming the source tile
behind every cell:

```powershell
py -3 scripts\export_sprite_sheet.py --record AVB1 --set Stand --out output\sheets\AVB1_Stand
```

## For developers

### No dependencies

Everything except cinematics runs on the Python standard library. There is no
`requirements.txt` because there are no requirements.

`scripts/imaging.py` provides what the tool needs: an RGBA buffer, a PNG
encoder and decoder over `zlib`, nearest and box resampling, compositing, and a
small embedded bitmap font for contact-sheet labels. It is not a general
imaging library.

Bink video is the exception, being proprietary. Exactly two categories are
affected:

| Category | Without FFmpeg |
| --- | --- |
| `cinematics` | skipped |
| `maps/quest` | skipped |
| everything else | extracted normally |

FFmpeg already on `PATH`, or named by the `MAJESTY_FFMPEG` environment
variable, is used automatically.

### This tool only reads

It does not write to the game, encode tiles, or modify archives, and it depends
on no other repository. Cloning this one is enough to run everything in it.

### Tests

```powershell
py -3 -m unittest discover -s tests
```

They need neither the game nor a network.

### Building the executable

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Build-Exe.ps1
```

PyInstaller is installed into a separate `.venv-build`, so `.venv` stays a
faithful test of the no-dependencies claim. FFmpeg is deliberately not bundled:
it is larger than everything else combined and only two categories need it.

### TILE format

TILE v3 stores run-length rows where each run records its **exclusive end**
column, so pixels belong in `[x_end - count, x_end)`. Count occupies the low
eleven bits of the packed run word, which allows the wide runs full-screen menu
art needs, and bit 15 ends the row. Gaps between runs are the only
transparency: every value stored inside a run is artwork, including palette
index zero.

Cleaning is category-aware, because the same palette index means different
things in different art. In sprite and building palettes, `247` is a
transition and seam control and `248-250` are shadow bands; magenta key ramps
are controls at any index. `251-254` are not universally reserved and are kept
when they hold ordinary colours, as in the Gazebo's white highlights.
Full-screen interface art, portraits, icons and effects use the high range as
real colour and keep all of it.

Two further cases are handled separately. Some indexed interface art declares
index `255` transparent while also using it inside the picture, so only regions
connected to the image edge stay transparent. And 16-bit RGB565 art has no
transparency field at all, making `0x0000` ambiguous between pure black and a
sprite cutout; it is resolved by category, so backgrounds keep their black and
sprite layers keep their silhouette.

See [docs/TILE_V3_RLE_ROOT_CAUSE.md](docs/TILE_V3_RLE_ROOT_CAUSE.md) for the
evidence behind the exclusive-end reading.

## Licence

MIT, for the tooling. See [LICENSE](LICENSE). It grants nothing over Majesty
Gold HD or its assets, which belong to their respective owners.
