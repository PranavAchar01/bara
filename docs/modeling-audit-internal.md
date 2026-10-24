# Modeling pipeline audit (internal, 2026-10-23 ~20:05 PT)

Read-only trace of prompt to brief to parts to place to board to case to viewer. Two agents were editing runner.py, board/, Viewport3D.tsx during the audit, so some items may be mid-fix.

## Architecture
1. Board planning is keyboard-only: `plan_keyboard` in live/runner.py returns nothing for other devices, giving "parts laid out in a row on a carrier" and Board "skipped". New board/generic.py + `_place_generic` in progress.
2. Brief has no physical shape: brief.py schema is keyboard-centric (keys, stagger, switches). Smartwatch brief has layout_style none, no size or form. Add target size, shape (round, rect, wrist), mounting, screen-facing side; feed board + case.
3. Catalog is closed: 239 hand-curated entries (catalog_build/manifest.py), no online lookup. Spec plans 8-10k records incl. ~13k installed KiCad 3D models. Index installed KiCad libs + Adafruit/SparkFun/Seeed/Espressif; on-demand fetch+convert.
4. Generic board packs for minimum area (generic.py:153-176), outline = bbox. Outline should come from the device shape.

## Assets
5. GLBs are real KiCad exports (median 1,180 tris, 2 materials, 13/181 textured) but many are bare packages, not the modules: bme280_breakout = 2.5 mm LGA chip; AMS1117 = SOT-223 box. Use whole-board module STEPs (Adafruit_CAD_Parts, SparkFun, Seeed OPL).
6. nice!nano mesh is a simplified STEP from an OpenSCAD folder, bbox-aligned. Source a detailed model or export its open KiCad board.
7. 53/239 parts have no mesh (both LiPos, MAX17048, SHT40, MPU6050, 15 dev boards); viewer draws boxes.

## Pipeline
8. Carrier fallback (live/adapters.py:179-232) still runs when the generic board fails; make it a visible failure.
9. Case = offset + straight extrude tray/lid (geometry/case.py:485-552); fallback_enclosure (adapters.py:286) sends only a size and the viewer draws a box.
10. Case colour takes colours[:1] regardless of target (case.py:380-381).
11. Viewer hides board components under separately drawn parts (`duplicatedComponents`, Viewport3D.tsx:509-532), replacing the routed board's detail with cruder catalog GLBs. When a routed board GLB exists, render it as the assembly.

## Rendering
12. Case hides the board: only a "covering" lid goes translucent (Viewport3D.tsx:373-431); tray and fallback box are opaque.
13. shadowMap disabled, RoomEnvironment + Neutral tone mapping (studio.tsx:38-44); fine per recipe, but cannot add detail the meshes lack. Apply material presets (soldermask, gold pads, silkscreen) to the board GLB too.

## External evidence (deep-research run, 2026-10-23, 101 agents, claims 3-vote verified)
- LLM-to-PCB research (pcbGPT arXiv 2606.01188, SchGen 2601.04505, PCBSchemaGen 2602.00510, CircuitLM 2605.30345) stops at the schematic; none places, routes, adds 3D models or a case. A rendered, populated board from one prompt is not solved anywhere we found.
- Unconstrained LLM circuit design fails: HWE-Bench (2603.18102) best model fully correct on 8.15% of 300 board-level tasks. What works: code/DSL output, datasheet-derived schemas, retrieval of canonical parts + pins, deterministic verifiers with repair loops. Supports our direction: model picks only among library survivors; geometry, board and checks are deterministic.
- kicad-cli (via KiBot export_3d, KiCad 9+) is the standard PCB-to-GLB path. Colour fidelity in containerised exports unresolved.
- build123d (Apache-2.0, OCCT) is a sound enclosure kernel; has its own exports.
- Vendor STEP models can carry non-commercial terms: keep per-source licence + provenance.
- Not verified by this run (thin evidence): atopile, tscircuit, Ergogen, Freerouting, JITX, Flux; SnapEDA/easyeda2kicad/Adafruit/SparkFun sources; enclosure generators; STEP/WRL-to-GLB colour handling; three.js PBR and latency numbers.
