# TILE v3 RLE Root Cause: Exclusive-End X

## Symptom

Hero (and other) sprites extracted from `maindata.cam` looked horizontally sheared: floating limbs, stair-step silhouettes, and “garbage” frames that still used the right palette colors. The public extractor author’s reaction was that Majesty’s engine must be applying some unknown transform between the on-disk bytes and what you see in game.

That intuition was reasonable given the visuals, but wrong. The on-disk art is ordinary upright pixel art. The extractor was mis-placing every opaque run on the X axis.

## Short answer

Each TILE v3 RLE segment stores:

```text
[u16 x_end] [u8 count] [u8 flags] [count palette indices]
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
| Shadow indices 248–255 stripped | Contributes holes / missing soft edges, **not** the X shear. |
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

Per row, repeat until `flags & 0x80`:

```text
[u16 x_end][u8 count][u8 flags][count × u8 indices]
```

- Index `0` = transparent (not stored; gaps are skips).
- Indices `248–255` = shadow / blend keys (often magic pink in palettes). Extractors may drop them for clean previews; encoders should preserve them when present.

## Why “round-trip verified” looked fine before

Encode and decode were **self-consistent** under the wrong start semantics:

1. Decode as start → wrong image.
2. Re-encode that image writing start → different bytes from the original, or a wrong but stable representation.
3. Simple tiles with **one opaque run per row** look identical under start vs exclusive-end (first run: start == end − count only if you already converted — for a single run, start-interpretation places at `x` while end-interpretation places at `x-count`; they only match if the stored field was already a start).

More importantly: overlays / simple silhouettes with few multi-run rows could look acceptable in crude checks, while heroes and complex buildings (many multi-run rows) looked like garbage when *viewed* with start semantics. Injecting brand-new complex art with start-encoded X would not match what the engine draws.

After the fix, decode converts end → start for callers; encode writes `x_end = start + count`. Pixel round-trip on AVB1 TILE 3794 succeeds.

## Fix checklist

- [x] `Majesty-ModdingToolkit/sprite_extractor.py` — exclusive-end decode; width from header@4 / max end
- [x] `Majesty-ModdingToolkit/sprite_injector.py` — write exclusive end
- [x] `majesty-gold-hd-art-asset-extractor/scripts/extract_assets.py` — same decode
- [x] `CAM_MODDING_GUIDE.md` TILE section corrected
- [x] Validation: AVB1 / AVA1 / ABC1 coherent; roundtrip tile 3794

Commands:

```powershell
cd Majesty-ModdingToolkit
python sprite_injector.py --cam "C:\Program Files (x86)\Steam\steamapps\common\Majesty HD\Data\maindata.cam" --roundtrip --tile-idx 3794
```

## Implications for AI re-art

Correct exclusive-end encode is mandatory if you want AI-edited sheets to render in-game without recreating the garbage. See [AI_SPRITE_REART_WORKFLOW.md](AI_SPRITE_REART_WORKFLOW.md).

Pipeline:

1. Export a normalized sprite sheet + JSON (shared canvas / hotspots).
2. AI regenerates the sheet while keeping the grid and pivots.
3. Quantize to the unit SPLT palette; preserve transparency / optional shadow band.
4. Slice cells → exclusive-end TILE encode → replace TILE entries (keep IMAG indices).
5. Extract again and smoke-test in game.
