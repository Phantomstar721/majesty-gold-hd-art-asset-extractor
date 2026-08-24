# IMAG Descriptor Root Cause: Declared Counts and End-Anchored Streams

## Symptoms

The old extractor could emit six directions for an eight-direction hero, turn
six or seven authored frames into eight, repeat unrelated TILEs as late frames,
and omit coupled effect layers. A full extraction also allowed archive-local
TILE identities to overwrite one another when base and expansion records
happened to produce the same relative output path.

## Stock mechanism

The retail `maindata.cam` and `mx_maindata.cam` IMAG records are the authority.
The independent stock-authority parser in the building-art pipeline provided a
second implementation to compare against. Ordinary directional sets use this
complete lifecycle:

1. An IMAG record owns an ordered table of raw set IDs and set-relative offsets.
2. Each set owns its direction count at set `+0x00`.
3. The ordered relative direction pointers begin at set `+0x40`.
4. Each direction owns a count word at direction `+0x04`:
   - high 16 bits: playback-frame count;
   - low 16 bits: coupled-stream count.
5. The direction ends at the next direction pointer, or at the next set for the
   final direction.
6. Its stream table begins at
   `direction_end - frame_count * stream_count * 8`. Words before that table are
   control metadata and have no universal fixed length.
7. Each eight-byte frame entry stores a metadata word followed by a reference
   word. The reference's low 16 bits select the archive-local TILE; its high 16
   bits are flags and remain metadata.
8. Streams and frames stay in declared order. Repeated TILE references are
   authored holds, not padding to discard.

The IMAG data owns construction, state selection, direction ordering, timing,
layer ownership and playback cancellation by set transition. Extraction is a
read-only projection of that state. There are no extractor callbacks, timers,
or cleanup state to invent; UI refresh is simply the completion of each PNG,
manifest and preview write.

Directionless interface/effect families do not satisfy this shape and continue
through their existing family-specific readers.

## What was wrong

The old reader began the pointer array at `+0x38`, eight bytes early. It treated
two control words as empty direction slots and therefore lost the final two of
eight real pointers. It then guessed frame count from pointer spacing after
subtracting a fixed `0x30` header. Stock direction blocks have variable control
metadata and may own multiple streams, so the guess was commonly off by one or
could read far into another table. The final direction used a zero-word scan,
which also rejected valid metadata and flagged references.

The fixed reader copies the stock fields literally and rejects a set as
directionless when the declared shape does not validate.

## Archive-local output identity

TILE numbers are positional within one CAM archive. `base:TILE:3` and
`expansion:TILE:3` are unrelated assets even if their IMAG record and set names
also match. Every extracted record now lives below its source label, and the
audit rejects any duplicate manifest output path. This prevents a later archive
from silently replacing an earlier archive's PNG.

## Validation

Retail checks after the fix include:

- Barbarian Walk: eight directions, eight declared frames in every direction.
- Healer Cast: eight directions, nine frames, two coupled streams per direction.
- Ranger Die: the stock asymmetry is retained—one direction has 15 frames and
  the other seven have 16.
- Flagged reference words resolve through their low 16-bit TILE identity.
- Synthetic tests vary control-metadata length to prove the table is anchored
  from the direction end rather than a guessed header size.
- An exhaustive `all-raw` extraction audits each decoded PNG against its source
  TILE occupancy and rejects duplicate output identities.
