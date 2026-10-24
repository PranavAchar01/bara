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

## Render quality bar (2026-10-24 ~00:30 PT, his words: "every single element of this fails so make sure they are all actually rendered to the quality i expect")
Engine-level, applies to every build; a build that misses a row reports a failing render.* check instead of shipping.
| # | Element | Bar | Check |
|---|---|---|---|
| E10 | Parts | every placed part renders its real 3D model (KiCad 3D library, LCSC/EasyEDA fetch, generated tier); zero placeholder boxes | render.placeholders = 0 |
| E11 | Board | GLB shows mask, copper tracks and pads, vias, plated holes, silkscreen, board edge; matches `kicad-cli pcb render` of the same board | side-by-side diff per build |
| E12 | Case | openings follow the feature shape (round wells, cross, round buttons, slots) with clearance, never square pocket holes; real caps (domed buttons, concave stick top with ring, cross d-pad, triggers/bumpers); screen glass under a bezel; split-line seam; satin plastic PBR | vision judge + geometry tests |
| E13 | Exploded view | pieces separate along the assembly axis in order: bottom shell, bottom parts, board, top parts, top shell, caps/glass; case and board share one frame (fix the y-down mirror at the source) | explode tests + screenshots |
| E14 | Presentation | studio light, soft contact shadow, AA, no z-fighting or black faces; comparable to the etch explore tiles (scratchpad ref/etch-explore.png) | contact sheet vs Etch + real photos |

### 2026-10-24 ~01:25 PT
- His verdict: form inference is accurate, shell is ugly. Shell surface rules (solid skin, parting line, continuous fillets, blended bosses, taper from thickness profile, satin two-tone, decimated GLB) assigned to bara-quality under E12.
- ~01:35 iteration: adea742 merged (no silent fallback, mating roles, stabilizer depth, board-v4). Suite on adea742 running under heavy lock. bara-quality still on E10-E14 + shell surface. bara-gaps/bara-render stay stopped.

## Overnight goal (his ask, 2026-10-24 ~01:45 PT, up ~08:00)
His words: "do like recursive loops of self-improvement... envision a very solid end goal... once you're done, go into more objects... keep going", plus merge Nithin's code into one working Vercel app; don't rename yet, tone down branding ("I hate the name Bara").

North star (what a finished build looks like, any prompt):
1. Reads instantly as the product from 3 m: silhouette, proportions and control layout match real products of that class.
2. Shell looks injection-moulded: solid walls, one parting line, continuous fillets, blended bosses, satin two-tone, no raw edges, few-MB GLB.
3. Board is a real routed PCB: visible copper, silk, vias, real 3D part models (placeholders = 0), DRC clean, fits inside with bosses + clearance.
4. Exploded view stacks correctly (caps / top shell / board / battery / bottom) with no mirror or float.
5. All checks required and green; failures are loud, never silent fallbacks.

Loop: run suite -> rank worst element across devices -> one engine-level fix (no device names) -> rerun -> log. When the 27 pass, add a new batch of gadgets (prompts only, never engine special cases) and repeat.
Expansion batches: (A) e-reader, digital camera, action camera, walkie-talkie, smart doorbell, thermostat, e-bike light, drone remote; (B) VR controller, stylus, earbuds case, bluetooth tracker, smart ring, baby monitor, label printer, dashcam; (C) mechanical numpad, macro pad, MIDI controller, handheld scanner, kitchen scale, alarm clock, portable fan, power bank.
Web: bara-merge agent merges Nithin's figma-design-in-code / agent-board-3d / figma-stage-log, mutes branding, wires Vercel to the live engine behind a token.

### 2026-10-24 ~02:00 PT: use case + one-to-one benchmark (his ask)
- North star 6: the engine understands each device's use case (jobs -> functions -> blocks -> parts) and organizes or composes new components to meet it; nothing dropped silently. Ledger E15 (compose agent).
- North star 7: every device is compared one-to-one with a real open-source KiCad project of its class (bench/references.json), same kicad-cli renderer both sides, metrics + function recall + side-by-side sheets + UI/UX comparison (bara-bench agent; scripts/compare_reference.py re-scores each iteration).
- ~01:10 E15 part 1 (0a46fcd): use_case (jobs, env, power, mounting) + per-block why; audit chain per slot in server/data/cache/chains/<build>.json; dropped blocks logged. Open: composed sub-circuits for unresolved functions. Suite adea742 rows: controller J1/J_M1 cut case; monitor mains-inlet/fuse/ESD unresolved; one Freerouting 300 s timeout (sent to compose agent).
- ~01:35 suite adea742 5/5 rows failed device.complete (fetch budget, fixed 415d105) + identity on mp3/mp4. Compose agent told to restart server + suite on main. c52dad8 (bara-merge): dev proxy uses the published engine + access key.
- ~01:45 found the "adea742" suite was hitting a server started 23:43 (pre-fix code). Restarted server (pid 21599) on b90088a and the suite (comp/suite.pid). Old rows saved as comp/suite-staleserver.jsonl. Compose agent was stopped by Pranav; main session owns live/* engine work now (E15 part 2 composed recipes pending).
- ~02:10 suite rows on b90088a failed protocol: E15 use-case progress line >120 chars. Fixed 281f189 (clamp). Promising: controller 18 blocks 0 unresolved, MP3 0 unresolved, monitor/mouse 1 each. Restarted server + suite on 281f189.

### 02:35 iteration
- d9e5f0d: composed recipes (E15 part 2). When curated, KiCad, LCSC and relax all miss, a function is met from a generic KiCad primitive keyed by component words (fuse, TVS, IEC inlet, encoder, buzzer, wired off-board load). Never used for sensors. Probe on the real index: rumble motor -> JST PH, mains inlet -> C14, ESD -> USBLC6-2SC6, scroll wheel -> EC11E, optical sensor -> None.
- dcc36a2: monitor failed identity ("flat slab seen from above"). Cause: every product is built face up and the hero camera looks down at it. ProductForm now declares rest_pose (face_up | upright); upright products are stood up (+90 deg about x) and seen from nearer eye height. Generic, no device names. test_live_form 37 passed.
- Suite restarted on dcc36a2 (server 82140, suite 82189).
- Next: controller floating tray/bezel pieces, J1 case cut (bara-quality), mouse optical sensor.
- a7b918f: the controller bezel came out in 2 pieces. Cause: hidden parts above the seat got square through-holes, which left a lattice of holes in the top skin plus loose bars. They now get a blind pocket from inside, with the skin kept. The non-sculpted path is unchanged when a part is taller than the shell. test_case_shell 20 passed, test_geometry_case 15 passed.
- bara-quality was stopped by Pranav (found 02:40). Not relaunched. Main owns the J1 cut, shell surface and lit displays now.
- Suite restarted on a7b918f (server 87104, suite 87144).
- 03:05-03:35 iter: a7b918f rows: controller left only J1 cut (rumble, floating fixed); monitor refused as a mains appliance; mouse missing optical sensor + dongle plug, J1 cut; mp3 FORM_OVERFLOW at 38% density + identity fail. Fixes: 04e6998 cable connectors (usb_in, jack, usb_device, usb_host) go to the board rim with the mouth facing out; e0f94df scope: a low-voltage product behind a wall adapter or certified AC-DC module is in scope, only mains-side appliances out (brief + SPEC); d70bea8 FORM_OVERFLOW names the first part with no free spot. Suite restarted on d70bea8 (server 21516, suite 21555). Next: read the mp3 stuck part, fix placement; mouse optical sensor.
- 03:50 iter: found three leftover suite processes from earlier restarts still writing rows on old code (killing the run3 parent left the uv/python grandchildren). Killed them (own PIDs). scratchpad/stop.sh now stops the whole tree. Rows before 03:50 mixed code versions, so they are not trusted. 1b8e8fe: a case that fails a check keeps its inputs in server/data/cache/enclose/ for offline rebuild, and the cut check gives the z range where the case meets the part (roof or wall). Clean suite restarted on 1b8e8fe (server 46339, suite 46377). Controller cuts seen so far are on sculpted shells only (fixture shells pass the same probe parts).
- 04:00-04:40 iter: a36c01c (shell): every claimed part gets its pocket, finger holes keep part corners clear, port sites know the part height, board-side roles read the part. Saved controller and monitor cases now pass enclosure. Mouse diagnosis on saved cases, three engine fixes:
  - bb2c9fd: the PMW3360 the mouse block named was already in the fetch cache, filed under component.ic, so the cache never served it ("cached miss"). A part number a block names now serves it whatever function the row was first fetched for. Companion devices (receiver dongle, dock, remote) are separate boards and no longer go into the product's BOM (block + audit prompts).
  - a841609: (1) the USBLC6 ESD IC, kept off-board, was read as a USB port because its label says "usb": a part nobody touches is never a port or control. (2) Off-board cells sat at the board centre over the mouse's downward sensor (U1/BT1): every off-board part now moves clear of board parts on its side. (3) "Rubberised scroll wheel" (mech.wheel) became a second EC11 encoder through an LCSC keyword search: touched mechanical blocks only search the part numbers they name, never keywords or recipes, and the case makes them. Cache row re-filed as input.rotary_encoder. (4) A button inside a wheel/stick opening is pressed through it (no own cap).
  - bara-merge and bara-bench were stopped by Pranav (SendMessage says so). Not relaunched.
  - Suite restarted on a841609 (server 93987, suite 94035).

### 04:50-05:00 iter
- Suite on a841609: controller failed "bezel 3 piece" (loose strips between merged openings); monitor failed DRC invalid_outline from the SJ1-3523N jack's own Edge.Cuts (an open notch drawn to splice into a board edge).
- 17d3091: case.py `_drop_slivers` (bezel pieces < 150 mm3 dropped before encoder cuts; the saved controller case now passes every check). libs.py `_edges_close`: a footprint's Edge.Cuts count as a cutout only when every line/arc end meets another; open ones go to User.Comments in kicad_script (the PMW3360 lens slot still cuts). Tests: layout + case 25 passed, ruff clean.
- Suite restarted on 17d3091 (server 24818, suite 24878). Next: read rows, then mp3 overflow / identity / shell surface / lit displays.

### 05:17-05:25 iter
- Suite on 17d3091: monitor PASSES (open Edge.Cuts fix held). Controller: knob M8 box corners cut the bezel, ringed island in the face-button cluster (171 mm3, bezel 2 piece), 1 DRC copper_edge_clearance. Mouse: two PMW3360s (the "lens matched to the sensor" block landed on the sensor) hanging under the board into a solid floor; identity fail. mp3: identity fail.
- bab0c6b: case.py desk-facing (bottom, no trackball) sensors get a pocket plus a floor window; validate.py knobs fit as discs; `_drop_slivers` also drops pieces under 2% of the largest (islands ringed by openings); compose.py `twin_slot`: two catch-all ("other") blocks that land on one part share it. Saved mouse + controller cases now pass every check.
- e181d0c: generic.py packs inside the outline inset 0.5 mm, so pads keep the copper-to-edge clearance (ProMicro pad 12 at 0.03 mm, SKQG pads at 0.25 mm before). Note: the commit also carried 616 new fetched part sources (fetched/src, tracked by design).
- Tests: geometry_case + case_shell + live_form + board_layout 87 passed; ruff clean. Suite restarted on e181d0c (server 57475, suite 57509). Open: identity (mouse, mp3), shell surface, lit displays.

### 05:50-06:00 iter
- Suite on e181d0c: CONTROLLER PASSES every required check (281 s). Monitor: "internal speakers" unresolved. Mouse: sensor + lens unresolved, identity fail. Cause for both: the spec check (vet) rejected the closest real part for good (PMW3360 vs a 26000 DPI line), and the other MPNs are not on LCSC.
- 0564b0a: compose.py `take_closest`: a required block with no candidate left takes the first part vet turned down, with a "falls short" warning. Test added; live_form 42 passed, ruff clean.
- Suite restarted on 0564b0a (server 84898, suite 84920).

### 06:17-06:35 iter
- Suite on 0564b0a: CONTROLLER PASS (297 s), MONITOR PASS (718 s). Mouse FAIL: identity ("wavy, peanut-like outline"), board.drc 8 errors + 1 unconnected.
- Mouse DRC root cause: every asymmetric bottom-side footprint sat half a turn from its plan. KiCad stores a flipped footprint mirrored in y, and SetOrientationDegrees(rot) dropped the 180 deg that makes it the packer's x mirror (layout.Item.world). SW4 (bottom) landed on J_M8.
- f853f67: kicad_script adds 180 deg for bottom parts. New tests/test_kicad_flip.py runs real pcbnew at 0/90/30 deg: 3 passed with the fix, 3 failed without. The board cache key hashes the script, so boards rebuild.
- Suite restarted on f853f67 (server 15812, suite 15876).

### 06:42-07:00 iter
- Suite on f853f67, controller FAIL mech.fit.floating (bezel 2 pieces, board 83% on the floor). Not the flip fix (the case reads plan features, not the board). Cause: the "thumbstick cap" block (mech.knob, filed by the model as input) fetched RKJXV1224005, the stick it fits, by its part number, so the build had four sticks and two hung 21.8 mm off the underside.
- 37c0712: completeness: a touched mech.* block is mechanical whatever its category. fetch: a mechanical need never searches LCSC (made by the case). Test extended; live_form 42 + fetch_lcsc 13 passed, ruff clean.
- Suite restarted on 37c0712 (server 39014, suite 39065). Mouse result on f853f67 never came in (suite stopped first).

### 07:05-07:10 iter
- Suite on 37c0712: MONITOR PASS (707 s). Controller FAIL mech.fit.floating again (bezel 2 pieces, board 93% on the floor). The sticks are off-board module cells; the left one, anchored to the front, overlapped a top part, and `_clear_of` jumped it to the back (side change cost only 2 mm), so it hung 21.8 mm under the board.
- c0684e6: generic._clear_of: an anchored part moves only along its own face; unanchored parts may still use the back. Test added; live_form 43, board_layout + geometry_case 26 passed, ruff clean.
- Suite restarted on c0684e6 (server 63384, suite 63439).

### 07:29-07:32 iter
- Suite on c0684e6: CONTROLLER PASS (439 s, BOM: 2 RKJXV sticks, 13 TL3342, 2 trigger pots, rumble, IMU), MONITOR PASS (718 s). Mouse running.
- Monitor gap even though it passes: HDMI and DisplayPort receptacles resolved to Phoenix screw terminals; the model said "no candidate is an HDMI receptacle" and had to pick anyway.
- 3323217: compose pick may answer NONE; the slot then runs resolve_missing (KiCad generated, LCSC fetch) and takes the new part if it passes the filters. Test added; live_form 44 passed. Not restarted yet so the mouse result on c0684e6 lands first.

### 07:43-07:48 iter
- Mouse on c0684e6: board.drc no longer fails (the f853f67 flip fix cleared its 8 errors). Still FAIL: device.complete (2.4 GHz chip antenna, function component.other, so the nice!nano's built-in radio does not cover it; no LCSC match), 1 unconnected, mech.access.panel (bezel overhangs encoder M5, 2/8 rays), identity ("top mostly open or cut away, showing internal clutter").
- Suite restarted on 16b24f2 (code = 3323217; server 98063, suite 98119).
- Next gaps, in order: antenna covered by a radio module (block function mapping), mouse top shell closing over parts, routing leftover, scroll-wheel overhang. Vercel URL and bench not done (agents stopped).

### 08:15 (code c64242b)
- Suite on 3323217: MONITOR PASS with real HDMI/DP receptacles (Amphenol 10029449, 20455-030E-12), so the NONE pick works. CONTROLLER FAIL: form.fit FORM_OVERFLOW on a 2x AA holder (60x33 mm), board on the floor.
- Cause: BlueMicro840 needs a LiPo (battery interface, chemistry lipo), but the AA holder's battery interface is also "requires", so `_mates` never compared them and the model picked AA.
- Fix c64242b: filters_for adds a chemistry filter on a power.battery slot from every chosen part that requires a battery of a named chemistry. Test added; live_form 45 pass.
- Mouse still running on 3323217; suite restart on c64242b after it finishes.

### 08:45 (code d611c95)
- Suite on 3323217 finished: MONITOR PASS; MOUSE fails only identity now (DRC and device.complete clear); MP3 fails device.complete (2.0" ST7789 TFT missing), identity, enclosure (M3), floating; MP4 fails identity.
- Hero renders (data/assets/cache/hero/b_utXS7hpVFUUM_repaired.png, b_2cSGazugktCI_repaired.png): the case tops are cut open over parts nobody touches.
- Root cause: every LCSC-fetched part (DW01A, LDO, ESD, antenna, switches, sensor) became an off-board "module" with a JST lead, because find_footprint did not resolve easyeda:<C> refs. Fix d611c95: libs resolves fetched/src/<C>/<C>.kicad_mod plus its STEP model and transform. All 213 fetched records load, and their pin maps fit the pads.
- Suite restarted on d611c95 (server 42035, suite 42056).
- Next: identity on mouse/mp4 after the re-run; the mouse rotary encoder shows as a 30 mm bare shaft (needs a wheel cap); identity message cut at 300 chars hides the mismatches.

### 09:05 (code e3fee5c)
- Controller on d611c95: case checks clear, board.drc 60 errors, all from fetched footprints now on the PCB: ESP32-S3-WROOM 0.25 mm thermal vias (drill, clearance) and EasyEDA rings at 0.0999 mm vs 0.1 minimum (SS49E, RKJXV stick and others). 2 track_width necks from the router.
- Fix e3fee5c: kicad_script._fit_holes drops unnumbered PTH vias under the minimum hole and grows thin rings, for any footprint. A dropped pad freed by Python corrupts pcbnew's pad list, so removed pads are kept alive. Unrouted rebuild of that board: 0 DRC errors. Test added (5 pass).
- Open: the controller BOM has both an ESP32-S3 module and a BlueMicro840. Suite restarted on e3fee5c (server 65980, suite 66012).

### 09:35 (cd33090)
- Suite on e3fee5c, controller: battery is now a LiPo (chemistry filter works) and DRC has 0 errors (hole fit works); only fail is board.routing.complete with 3 unconnected, all on U5 = LSM6DS3TR-C (LGA-14, 0.5 mm pitch) pins 6/7/8. All 4 router strategies left the same 3 open.
- Cause: the placer's region allowed a courtyard 0.5 mm from the outline; U5's edge-side pads sat 0.67 mm from the edge keep-out band, so its pins had no way out (only pin 5 escaped, by a via). Parts get 1.2 mm between each other but no channel at the rim.
- Fix cd33090 (generic, no device names): fine-pitch SMD parts (>= 6 pads, min pad spacing < 0.65 mm, not cable connectors) keep EDGE_COPPER_MM + PART_GAP/2 from the edge. Test tests/test_fine_pitch_edge.py; 47 related tests pass.
- Server still runs e3fee5c; suite continues on mouse/mp3/mp4/monitor for the identity re-check. Controller re-check on the next run.

### 09:55 (78230d2)
- Suite on e3fee5c, 5 rows: controller only fails routing (fixed by cd33090), identity PASS; monitor regressed: device.complete (bicolor standby LED missing) + 1 DRC error; mouse fails identity (peanut blob, pockets); mp3 fails identity (two black screen windows over nothing); mp4 fails device.complete (charge LED) + identity (plain slab).
- MP3 cause: keyword LCSC fetch took the first stocked hit for "2.0 in TFT", an FH12 FPC connector, tagged it display.tft; the case cut a screen window for it. LCSC does stock HS20HS072RX (2.0 in ST7789 LCD, 1499 pcs).
- Fix 78230d2: best_stocked skips connector-category hits unless the block is interconnect; FH12-40S, FH12-14S, DF19G-30P rows retagged interconnect.connector (monitor may now flag its panel; check).
- Restarted server 17852 + suite 17889 on 78230d2 (27 devices).
- Next gaps: status LEDs missing on monitor/mp4 (catalog/LED filter), mouse shell identity, pockets breaking through the skin.

### 10:00 iteration
- 90dca15: a spec screen-type requirement (display_type eq tft) only filters screen slots; it was emptying the status-LED slot (8 to 0) on monitor and mp4.
- 078c228: the top skin rises over the tallest hidden part (plate kept at 1.5 mm) instead of a blind pocket opening through it (the mouse's rectangular recesses).
- 61dc051: a product with a desk-facing sensor keeps a flat floor and domes over the board (spread goes to crown, no belly). New `mouse` shell fixture; gamepad output byte-identical.
- 98f210f: new site kind `wheel` (scroll / thumb wheel / roller): a 20 mm wheel on edge in a slot along the plan's long axis; the encoder-access check probes the slot for wheeled encoders.
- Controller on 78230d2: identity PASS, fit PASS, routing fixed (cd33090).
- Suite restarted on 98f210f: server 33627, suite 33676.

### 10:05 iteration
- Monitor DRC: the one error is a 0.18 mm Freerouting neck at 0.12 mm (GND, F.Cu) between two 0.2 mm segments, squeezing past pad 124 of the 0.4 mm-pitch DF19G panel connector. Widening it to the 0.15 minimum after SES import trades it for 2 clearance errors against that pad (0.1488 vs 0.15), so it was not committed. Open: needs a reroute or a placement nudge around fine-pitch cable connectors.
- mp4 identity ("portrait screen, a third of the face") root cause: the EA eDIP TFT43 footprint is drawn portrait (71.5 x 107.3) and kept rotation 0, so the 125x75 form could not hold it and fit repair grew the body to 220x140. Fix f7fc877: a screen >= 20 mm long turns a quarter when its long side runs across the body's long side (test_screen_orientation.py, 59 placement/form tests pass).
- Suite restarted on a7145a5 (has f7fc877): server 42785, suite 42836.
