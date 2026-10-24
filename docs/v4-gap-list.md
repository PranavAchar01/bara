# v4 gap list (bara-gaps, started 2026-10-23)

Plain checklist. Status words: done, partial, missing. File references are to server/src/bara unless noted.

## Root cause: archetype + identity

The symptom: a bare "a keyboard" came out as a 48-key ortho grid in the parts list and a 16-key column block on the board and in the viewport. In other gadgets the same thing shows up as a smartwatch that is just a rectangle of parts, or an e-reader with no display.

What the code was doing:

1. No archetype. Anything the prompt left out was filled in by hard-coded heuristics, and those were spread over three places that did not agree with each other:
   - live/brief.py: the model prompt says "fill gaps with the most common hobby choice", and the rules fallback has no layout at all.
   - live/layout.py CONSTANTS: unibody defaults to 4 rows x 12 cols, so 48 ortho keys.
   - board/layout.py normalize_brief: with no key_count it uses rows 4 x cols 4, so 16 keys.

   Nothing looked at what real devices of that class look like.
2. Two sources of truth for the arrangement. The compose stage emitted the 48-key layout. The place stage then re-emitted the board's 16-key layout under the same layout_id (live/runner.py place, layout_from_keys), while the switch and keycap instances kept quantity 48. The viewport drew 16 to 17 caps.
3. No identity check. Nothing checked that:
   - the result resembles the device that was asked for;
   - a multi-quantity instance has N distinct, non-overlapping poses;
   - the number of rendered elements equals the declared quantity.
4. Instance integrity outside keyboards. The generic place path kept one pose per instance (live/runner.py _place_generic, `seen`), so 4 buttons sat stacked on one spot.

The fix (generic, no per-device branches in code):

- data/archetypes.json holds a small library of real open designs per device class, each with source URL and licence. The fields are:
  - the brief defaults (layout preset, key count, stagger, functions with counts);
  - the physical form (shape, size, mount);
  - the arrangement (which face each role sits on);
  - a conformance size range.
- live/archetype.py picks the closest archetype for the prompt and brief, and fills only the fields the prompt left unstated. The reuse.decided event names the archetype as the compose skeleton and lists the fields it filled.
- One arrangement source. The live layout is the only key arrangement. The board stage places switches at exactly those keys (explicit key list in the board brief), so compose, board and viewport agree by construction.
- Identity checks on every build:
  - (a) structural: every arrayed instance has quantity distinct poses with no overlap, and the layout key count equals the quantity;
  - (b) archetype conformance: board and case size fall within the archetype's range;
  - (c) vision judge: a hero render sent to the model with "is this recognisably a <device>?". This one is still missing, see below.

## Checklist

(filled in at the end of the pass)
