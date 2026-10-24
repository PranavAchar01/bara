# Bara night loop (his ask, 2026-10-23 ~20:15 PT)

His words: "keep going all night until the engine works and any prompt can actually achieve any gadget created. I want it to be a situation where every piece is being weighed to create new and interesting and different pieces. I want genuine intelligence, keep comparing the 3d model rendering to that of https://etch.chat/explore, simply go on the open source section, click on a tile and you can see the quality I expect. I do not want anything other than perfection by tmrw morning."

## Bar for done
- Any gadget prompt (keyboard family, smartwatch, weather station, plant monitor, desk clock, rover, game controller, synth, drone FC, e-reader, novel ones) reaches build.done with 0 failed checks.
- Every build has a real routed, populated KiCad board GLB (soldermask, silkscreen, pads, KiCad 3D models) and a case shaped to the device.
- Part choice is reasoned per prompt: candidates scored on the brief (function fit, size, power, interfaces, cost, novelty), so different prompts get different, interesting parts; reasons shown in decisions.
- Render matches etch.chat/explore open-source tiles: light studio, mm grid, iso camera, full board detail. Screenshot every iteration and compare side by side.

## Rules
- Fresh code only (Cal Hacks). Etch and the v3 POC: ideas only, never copy code.
- One pytest at a time (/tmp/bara-pytest.lock); kill only PIDs I started; heavy-lock for big downloads.
- Commit + push working increments to main (private repo); never make it public.
- Nithin owns web/ except web/src/three.

## Each iteration
1. Check agents (bara-gaps, bara-render); merge + verify + commit what is done.
2. Run the prompt suite through the live server; screenshot via Playwright; compare to an etch.chat open-source tile screenshot.
3. Pick the worst gap, dispatch or fix it.
4. Log results below with time.

## Log
- 10-23 20:06 iter 1: agents bara-gaps (pipeline, v3 logic, any-gadget board, weighted part picks) + bara-render (Etch look) running; Etch refs in docs/ref/; internal audit docs/modeling-audit-internal.md. Next: verify + commit first increments, run suite.
- 10-23 20:11 iter 2: bara-gaps inc 1 committed 619410a (keyboard 97 parts 22.9s, macropad 22, split 78, 60% 124 parts 223s, smartwatch generic board 58x52; all 0 fail, DRC 0/0). Rebased onto Nithin PR #1 (render-quality, meshopt GLBs). Render agent told to merge his web/src/three changes. Next: gadget suite, shape outline, weighted picks, 60% speed.
- 10-23 20:20 iter 3: render inc committed 9fbb519 (Etch studio, board GLB as assembly, translucent case). Found: layout 16 keys vs q48, inverted case normals -> gaps. gaps now on root cause (archetype retrieval + identity checks + vision judge).
- 10-23 20:30 iter 4: render inc 2 committed 5a4e75b (full-width toolbar + compact mode, no-model tags on hover). Smartwatch case 118x126 off-centre -> gaps (case-contains-board invariant). Missing part records/models + case winding -> gaps. Render next: hide inapplicable toggles, case-mismatch chip, tighter Etch framing + contact shadow.
- 10-23 20:45 ROOT CAUSE (his push: "not just a keyboard"): the pipeline only knows what the prompt says; anything unstated comes from hard-coded keyboard-era constants, BOM quantities are set apart from the layout, and nothing checks the result is the device asked for. Fix (gaps): (1) no silent defaults, unknown classes get an LLM spec grounded on nearest archetypes; (2) quantities derived from placed instances; (3) identity check as a build check with one repair pass. Proof: 16 archetypes + 5 no-archetype prompts all green.
- 10-23 22:00 iter 5: blank-board fix committed 24f1093 (mask opacity cap, gold pads, bottom view, floor hidden on bottom). The keyboard circuit lives on B.Cu. Ran his 27-device list live (suite1): 22 done, 2 mains out_of_scope, 1 timeout (glasses), 2 empty DONE (gamecube, touchpad). Every BOM is far below the Etch tile bar: no core-function part (GNSS, Pi, amp, DAC, sensor, modem), x1 lines left ungrouped, and some wrong picks. Dispatched to compose-complete: completeness invariant, missing-part fetch, grouping, HLK mains, never an empty DONE. Next: rerun into suite2 after it merges.
- 10-23 22:20 ROOT CAUSE 2 (his push: "fix the intelligence, don't patch every device"): the engine builds inside out. generic.py packs parts around the MCU and the outline is the packed hull plus a margin; case.py wraps a box around that; nothing models the product's form or where hands touch it. Result: controller = 197x79 slab with buttons in rows. Fix: FORM stage (silhouette + thickness + interaction anchors, grounded on references) -> board = silhouette inset, user-facing parts on anchors -> case from silhouette -> BOM from function blocks that must all resolve -> vision identity judge with one repair. No device-name branches. Comparison image: scratchpad/ref/controller-compare.jpg.

## Engine issue ledger (2026-10-23 ~23:30 PT, his ask: "take every issue and change the engine itself to make sure this applies to all builds")
Every row is fixed by changing one generic mechanism. No device-name branches, part lists or constants outside tests. A row closes only when the full 27-prompt suite shows the failure class gone.

| # | Failure class (suite evidence) | Generic mechanism to change | Owner |
|---|---|---|---|
| E1 | FORM_OVERFLOW with only 4-16 footprints (mp3, mp4, flipphone, gameboy) | form fit: measure silhouette inset area vs courtyard sum per side; packer must use both sides, rotate parts, pack anchored parts first; silhouette size must come from the declared product dimensions, not a guess | compose |
| E2 | Required block unresolved although real parts exist (ST7789 LCD, DRV8833 h-bridge, display scaler, DisplayPort connector) | block resolver: search curated, then the whole KiCad generated tier, then LCSC fetch, by function + spec numbers, with query relaxation (driver IC name, package family) before failing | compose |
| E3 | "No controller" on large products (monitor, TV) | composition: when the product is module-scale (panel, mains), the engine builds the electronics board plus off-board modules (panel, PSU) as placed modules on the form, not parts on one PCB | compose |
| E4 | Optional slot with no part counted as a failed check | completeness: optional slots that cannot resolve are dropped with a warning, never a fail | compose |
| E5 | Identity judge sees "a scattered exploded assembly" or "flat grey slab" | the judge renders the assembled shell from the product's canonical view, never the exploded view; shell comes from the sculpted form | shell + compose |
| E6 | mech.fit.floating "Tray 1 piece" | case: parts and board seat on bosses/ribs generated from the board outline, every piece connected | shell |
| E7 | DRC errors left on a finished board (controller 2) | board: DRC errors feed back into one re-route pass with wider clearance / alternative footprint before failing | compose |
| E8 | Ungrouped identical BOM lines, unnamed lines | BOM is built from instances grouped by part id with qty; every line carries the resolved part name | compose |
| E9 | Thin BOMs (no MCU, no amp, no DAC, no sensor) | function blocks: every implied function chain (audio out = source + DAC/amp + transducer, input = sensor + MCU) expands to all its blocks | compose |

### 2026-10-24 ~00:00 PT
- E1-E9 engine commits pushed (0c1261c..7956604): fit with both sides + rotation + declared-size redraw, relaxed resolver, optional slots never fail, BOM grouped by function, function-chain audit, DRC wide-rules re-route, off-board modules (E3), identity judge sees assembled parts. KEYBOARD_ONLY filter replaced by "a block must serve a function the brief implies".
- Sculpted shell merged (5980fa7): geometry/shell.py builds the case from ProductForm silhouette, thickness and anchors (crowned top, fillets, stick wells, d-pad, buttons, screen window, port slots, hidden part pockets, ribs so nothing floats). Fixture renders in scratchpad/shell/ read as a gamepad and a phone.
- Device-name grep of both diffs: clean. Server restarted on 5980fa7. Full 27-row suite restarting on 5980fa7; that run is the one reported.
