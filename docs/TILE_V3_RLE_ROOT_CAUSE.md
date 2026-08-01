# TILE v3 RLE Root Cause: Exclusive-End X

## Symptom

Hero (and other) sprites extracted from `maindata.cam` looked horizontally sheared: floating limbs, stair-step silhouettes, and “garbage” frames that still used the right palette colors. The public extractor author’s reaction was that Majesty’s engine must be applying some unknown transform between the on-disk bytes and what you see in game.

That intuition was reasonable given the visuals, but wrong. The on-disk art is ordinary upright pixel art. The extractor was mis-placing every opaque run on the X axis.

## Short answer

Each TILE v3 RLE segment stores:

```text
[u16 x_end] [u16 count_flags] [count palette indices or RGB565 pixels]
```

`x_end` is the **exclusive end column** of the run. Pixels belong in `[x_end - count, x_end)`.

Older tooling treated `x` as an **absolute start** (`draw at x .. x+count`). That shifts every multi-run row by roughly `count` pixels and produces exactly the barbarian contact-sheet garbage.

Header word at byte **4** is the canvas **width**. Correct exclusive-end decode satisfies `max(x_end) == width` on normal tiles.

## Hypotheses tested

| Hypothesis | Result |
|------------|--------|
| Relative skip (“transparent pixels from cursor”) | Ruled out. Treating stored X as skips blew width out and increased gaps. |
| Classic stride / pitch mismatch | Ruled out. TILE v3 has no dense row pitch; each row is sparse RLE. |
| Interlacing / wrong bit depth | Ruled out. 8-bit palette indices decode with coherent colors. |
| Missing IMAG hotspots as cause of *within-frame* shear | Ruled out. Hotspots affect sheet placement only. Geometry inside one TILE was already broken. |
| Sprite control indices stripped | Contributes holes / missing soft edges, **not** the X shear. |
| Docs saying width@+2 / height@+4 / palette@+0x0C | Docs were wrong vs working code; following them alone would also garble sprites. |

## Decisive evidence (AVB1 Barbarian Stand, TILE 3794)

Treating X as **start**:

- Many within-row segment overlaps (negative gaps between consecutive runs).
- Decoded width often ~1.5–2× header width.

Treating X as **exclusive end**:

- **Zero** within-row overlaps.
- Gaps between runs are `>= 0`.
- `max(x_end) == header width` (57 for that tile).
- PNG matches in-game silhouette (rear view, shield, greaves, etc.).

### Hex example (row 14 fragment)

```text
13 00 01 00 a5 | 2d 00 15 00 <21 bytes> | 39 00 09 80 <9 bytes>
x=19  c=1        x=45 c=21                 x=57 c=9  (last)
```

Exclusive-end placement:

- run A → columns `[18, 19)`
- run B → columns `[24, 45)`
- run C → columns `[48, 57)`

No overlap; canvas width 57.

Start placement would put B at `[45, 66)` and C at `[57, 66)` — overlap and stretch past the real width.

## Correct on-disk format

```text
+0x00   u16 version (= 3)
+0x02   u16 height
+0x04   u16 width            ← canvas width (= max exclusive-end X)
+0x06   10 bytes             ← remaining header words (preserve on re-encode)
+0x10   6 bytes zeros
+0x16   u32 palette_id       ← byte 22; index into SPLT
+0x1A   height × u32         ← byte 26; row offsets relative to byte 26
        then RLE row payloads
```

Per row, repeat until `count_flags & 0x8000`:

```text
[u16 x_end][u16 count_flags][count × pixel_size bytes]
```

- `count = count_flags & 0x07FF`; upper bits carry flags.
- Indexed art uses one byte per pixel. The familiar short-run form can be
  written as `[u8 count][u8 flags]`, but that is not the general format because
  full-screen menu rows use counts above 255.
- Palette-less widescreen/interface TILEs use two-byte RGB565 pixels.
- Embedded-palette TILEs store the palette after the final row; that palette is
  not part of the final row payload.

- TILE v3 transparency comes from gaps between stored runs. Every value inside
  a run is an authored pixel, including palette index `0` or RGB565 value `0`.
  Treating explicit zeroes as transparent punches out white highlights and
  surfaces in palettes where entry zero is near-white.
- RGB565 has no transparent-index field, so `0x0000` is ambiguous: pure black in
  a background, or the cutout in a sprite layer. The decoder resolves it by
  output category. Backgrounds keep their black; sprite layers keep their
  silhouette. Reading it as transparent everywhere removed 4.5% of the main
  menu backdrop while leaving the pixels one step off black untouched.
- Some indexed UI and presentation art declares index `255` as transparent
  while also using it for enclosed artwork colors. In full-palette categories,
  the decoder keeps only boundary-connected components of that index
  transparent and restores enclosed components. Sprite layers continue to
  honor the declared transparent index everywhere.
- The indexed 100x100 hero, monster, and building profile paintings are not
  sprite layers. They retain indices `247–255`, including the header's nominal
  transparent index; applying sprite cleanup to them punches visible holes
  through faces and highlights. RGB565/RLE profile layers retain their authored
  transparency.
- In sprite/building palettes, Phantom's Haunt confirmed `247` as a transition/seam control and `248–250` as shadow bands. Magenta key ramps are also controls regardless of index. Indices `251–254` are not universally reserved—the Gazebo palette uses them for white highlights—so they are retained when they are ordinary colors. Full-screen interface, profiles, icons, effects, and sepia palettes use the high range as artwork, so cleaning is category-aware rather than deleting it globally.

## Why “round-trip verified” looked fine before

Encode and decode were **self-consistent** under the wrong start semantics:

1. Decode as start → wrong image.
2. Re-encode that image writing start → different bytes from the original, or a wrong but stable representation.
3. Simple tiles with **one opaque run per row** look identical under start vs exclusive-end (first run: start == end − count only if you already converted — for a single run, start-interpretation places at `x` while end-interpretation places at `x-count`; they only match if the stored field was already a start).

More importantly: overlays / simple silhouettes with few multi-run rows could look acceptable in crude checks, while heroes and complex buildings (many multi-run rows) looked like garbage when *viewed* with start semantics. Injecting brand-new complex art with start-encoded X would not match what the engine draws.

After the fix, decode converts end → start for callers; encode writes `x_end = start + count`. Pixel round-trip on AVB1 TILE 3794 succeeds.

## How the decoder was validated

- Exclusive-end decode, with width taken from header word 2 or the largest run
  end when that word is zero.
- Cross-checked on AVB1, AVA1 and ABC1: multi-run rows are coherent rather than
  sheared.
- Every decoded PNG is re-counted against the source runs by the extractor's
  own occupancy audit, which fails the run on any mismatch.

## If you want to write TILEs

This project only reads. Writing a TILE back into a CAM is a separate problem
and deliberately out of scope here, but the format notes above are what an
encoder needs:

- Store the **exclusive end** column, `x_end = start + count`, not the start.
- Count occupies the low 11 bits of the packed run word; bit 15 ends the row.
- Gaps between runs are the only transparency. Do not emit a run for them.
- A value inside a run is authored artwork even when it is zero, so an encoder
  that reserves index `0` for transparency cannot round-trip art that uses
  index `0` as a real colour.
