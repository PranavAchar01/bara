# Bara UI build plan

Written 2026-10-22. Owner: Nithin. Plan only, no code (PLAN.md section 0). The UI is written at the event in the new repo, against SPEC.md v1.1.1. This doc only decides the order, the layout and which fixture proves each piece.

Where this doc and SPEC.md disagree, SPEC.md wins.

Sections 1 to 7 cover what gets built and in what order. Section 2 is the layout, modelled on Figma with Tinkercad's view cube. Section 8 is the design brief: colour, type, motion, the agent, the homepage, and what each event looks like on screen.

---

## 1. Ground rules

- **Mock first.** Every component is built against `?mock=1` and a named fixture (SPEC section 13) before it ever sees the real backend. Pranav's engine and the UI meet only at the WebSocket contract.
- **One store, spec reducer.** The Build store follows SPEC section 9 exactly. View state (stage status, candidates per slot, pending edit, selection, explode amount, camera) lives in separate stores, rebuilt from the same events.
- **No mock-only code paths** beyond the fake socket and the REST stub (SPEC 13, last bullet).
- **Labels come from `GET /v1/vocab`** (`rest/vocab`), not hard-coded strings. Stage budgets come from `stage.started.budget_ms`.
- **Never block on assets.** A part with no GLB draws its `bbox_mm` as a translucent labelled box (SPEC 11.4). The bbox path is built first, so the viewport works before any GLB exists.
- **Server text renders as text**, never HTML.
- Stack, per the spec: Vite, React, React Three Fiber, plus the app shell and panels from Nithin's public UI skill library (disclosed in the Devpost line). Types are generated from `spec/schemas/` at H0 so the contract is checked by the compiler.

---

## 2. Layout

**Model: Figma.** The workspace is laid out like Figma's editor: a layers panel on the left, a properties panel on the right, the canvas in the middle, and a floating toolbar at the bottom centre. People who have used Figma (most designers and many engineers) already know where everything is. One thing is kept from Tinkercad: the **view cube in the top-right corner of the canvas**, because a 3D canvas needs it and Figma has no equivalent.

Target screen is the demo laptop at 1440 x 900 or larger. No phone layout in v1 (the QR room view is an open question, section 7).

**This moves components, not the contract.** Every SPEC 11.2 component, event and state stays as specified. Only the "Where" column of SPEC 11.2 and the screen description in SPEC 11.1 change. Section 2.7 maps each component to its new home. SPEC is frozen, so this needs Pranav's yes as a UI-only note (open question 7).

The working prototype in `ui/` still uses the earlier three-column layout. This section is the target for the next pass.

### 2.1 Home

```
+--------------------------------------------------------------------------------------------+
| Bara                                                                          design system |
|                                                                                            |
|  Engineer                                        ___________________                       |
|  *anything*.                                   /  ASCII-print Corne  \    <- Pro Micro       |
|                                               |   (real parts, drawn  |   <- OLED            |
|  Say what you want. Bara finds real open       |   in type on pastel)  |                      |
|  parts, wires them, and wraps them in a case.   \_____________________/   <- open PCB · MIT  |
|  +-----------------------------------------+                                                |
|  | (o o)  a wireless split keyboard ...  (^)|                         hover to see it rendered|
|  +-----------------------------------------+                                                |
|  [icon keyboard] [icon split + OLED] [icon desk gadget] [icon 60% Choc]                       |
+--------------------------------------------------------------------------------------------+
| EVERY PART IS REAL   [tile] Corne v3 PCB  [tile] Pro Micro  [tile] Gateron Yellow  [tile] ... |
+--------------------------------------------------------------------------------------------+
```

- Left: the display line, one sentence, the prompt (C02) with the agent's eyes inside it, and the example chips (C03).
- Right: the homepage stage (section 8.6). Bottom: a strip of real part tiles with their licences.
- Sending a prompt moves to the workspace on `ack` (SPEC 11.1).

### 2.2 Workspace, build running

```
+-----------------------------+---------------------------------------------------------+------------------------------+
| (Bara v)  a keyboard v      |  ==== stage progress line along the top edge ======     | (o o)Bara  [Export]  [>]  86%v|
| ● ● ◐ ○ ○ ○ ○ ○  Find design|                                                         +------------------------------+
+-----------------------------+                                              +-------+  |  Design    Build    Code     |
|  Layers      Assets         |                                              |  TOP  |  +------------------------------+
+-----------------------------+                                              | FRONT |  | Build (nothing selected)     |
| BUILDS                      |                                              +-------+  |  input device › keyboard     |
|  ● a keyboard          r1   |                                               (home)   |  [wireless] [split] [oled]   |
+-----------------------------+                                               (fit)    | Design                       |
| v ▦ PCB               ×2    |        canvas: workplane grid, parts arrive    (+)     |  Corne (crkbd)   EXACT       |
|      PCB left               |        in type and resolve into the render     (-)     | Case                         |
|      PCB right              |                                                         |  wall 2.5  fillet 1.5 mm     |
| v ▦ Controller        ×2    |              ↖ Bara · picking switches                  | Checks          4 ok · 0 ✕   |
| > ▦ Switches         ×42  ✕ |              (the agent's multiplayer cursor)           | Export                       |
| > ▦ Keycaps          ×42    |                                                         |  [STL v]  [Export]           |
|   ▦ Display           ×2  ◌ |                                                         |                              |
|   ▦ Case foam          -    |                 [toast stack: warnings, edit status]    |                              |
|                             |  +----------------------------------------------------+ |                              |
|                             |  | V  H  O | ⧉ explode --o  iso top front side | + ⌁ |  (o o) Ask Bara…       ⌘K |  |
|                             |  +----------------------------------------------------+ |                              |
|                             |                                          0.26 s   (?)   |                              |
+-----------------------------+---------------------------------------------------------+------------------------------+
```

**Top of the left panel (Figma's file header)**

- `Bara ▾` opens the main menu: New build (⌘N), Home, Design system, Event log (L), Keyboard shortcuts (⌘/).
- The build's name is the prompt. Clicking it shows the full prompt and the build id.
- Under it, C04 StageTimeline as a compact step player: eight dots, the active one stretched into a filling bar, with the current stage name. A 2 px progress line also runs along the top edge of the canvas while a build runs.

**Left panel: Layers and Assets tabs**

- **Builds** (Figma's Pages) sits at the top of Layers: one row per build this session, with its revision. Clicking one loads it (`GET /v1/builds/{id}`). A failed build shows a ✕.
- **Layers** is C09 PartsList as Figma's layer tree. One group per slot, with the slot's icon and quantity, and a row per instance inside it (left and right halves). Each row has:
  - a status mark from its checks (✕ fail, ▲ warning, ◌ unknown; nothing when everything passes),
  - an eye to hide it in the canvas and a lock that shows `placement.locked`, both on hover, as in Figma,
  - hover highlighting the part in the canvas, and click selecting it.
- **Assets** is the catalog: the rendered part tiles (Tinkercad's shape palette), searchable (`GET /v1/parts`), grouped by function. Dragging one onto the canvas, or clicking +, adds it (C28 AddPartPicker becomes this tab).

**Top of the right panel (Figma's toolbar right)**

- The agent's avatar where Figma shows collaborators: the eyes, live. Clicking it opens the thought log (stage durations and the last decisions).
- **Export** as the one primary button, in ink (Figma's blue Share button). It opens C24 ExportMenu. It's disabled until `build.done`.
- ▷ **Preview**: hides both panels and plays a slow turntable with the parts exploded, for the demo and the video. Esc exits.
- Zoom percentage with a menu: Zoom to fit (⇧1), Zoom to selection (⇧2), 50, 100, 200.

**Right panel: Design, Build and Code tabs** (Figma's Design and Prototype tabs)

- **Design** shows properties of whatever is selected, in Figma's stacked sections. With nothing selected, it shows the build: spec chips (C07), the design and tier (C08), the case (C21 ResizePanel's sliders), a checks summary, and Export. With a part selected, see 2.3.
- **Build** is the reasoning: every stage with its recorded ms (this replaces the floating C05 LatencyHUD, which shrinks to a chip on the canvas), C06 DecisionTrace with draining filter chips and candidate fans, and warnings (C18) as a list.
- **Code** holds C16 FirmwareView, C15 BoardView and C14 ConnectionView as three sections.
- The tab badge counts failing checks for that tab, as before.

**Canvas**

- The workplane grid, the parts and the case. The selected part gets Figma's selection treatment: a thin teal bounding box with corner handles and a size label under it ("132.0 × 93.0 mm"). Hover draws a thin outline.
- **View cube, top right** (Tinkercad). Under it, the camera group: home, fit, zoom in, zoom out. Clicking a cube face eases the camera to that view.
- **The agent's cursor.** While a build runs, the agent appears as a Figma multiplayer cursor with a name tag ("Bara · picking switches"), moving to the part it's working on. Stage, activity and the target part come from the stream.
- Bottom right: the timing chip (time to first part; hover shows per-stage ms) and the ? button for keyboard shortcuts, where Figma keeps its help.
- Right-click a part or a layer for a context menu: Swap…, Recolour…, Hide, Lock, Zoom to selection, Remove. Every command also lives in a panel or the toolbar, so nothing is right-click only.

**Bottom toolbar (Figma UI3's floating toolbar)**

Three groups, then Ask:

| Group | Tools |
|---|---|
| Navigate | Select (V), Pan (H), Orbit (O) |
| View | Explode slider (E toggles), view presets iso, top, front, side (1 to 4) |
| Make | Add part (A, opens Assets), Connect (C, C23 ConnectDialog: click two ports) |
| Ask | The agent's eyes and an "Ask Bara…" field (⌘K). Typing a new prompt sends `build.start`; the field grows into C02 PromptBar. While a build runs, its send button is Stop |

- The agent's speech bubble rises from the Ask field.
- Toasts (C18 warnings and C19 EditStatus with its Undo button) stack just above the toolbar, centred, as Figma does.

### 2.3 Part selected

```
                                                                     +------------------------------+
                                                                     |  Design    Build    Code     |
        +-------------------+                                        +------------------------------+
        |  [ switches ]     |  <- selection box, corner handles      | [render]  Switches left      |
        +-------------------+                                        |           Gateron Yellow ▾   |  <- instance swap
           294.6 × 81.0 mm                                           |             Cherry MX2A Brown|
                                                                     |             Kailh Choc v1  ✕ |
                                                                     | Position                     |
                                                                     |  X -132.0  Y 40.0  Z 1.6     |
                                                                     |  ⟲ 0°            🔒 design    |
                                                                     | Colour                       |
                                                                     |  [■] #B9A7E3   plastic ▾     |
                                                                     | Why this part                |
                                                                     |  "From the Corne design."    |
                                                                     | Checks                       |
                                                                     |  ● family match              |
                                                                     | Source                       |
                                                                     |  ✓ geometry   CC-BY-4.0  ↗   |
                                                                     |                    [Remove]  |
                                                                     +------------------------------+
```

- The right panel's Design tab becomes C12 PartInspector, as Figma's stacked sections. No overlay covers the layers or the canvas.
- **Swap is Figma's instance swap.** The part name is a dropdown of C13 SwapDrawer's alternatives, each with a rendered thumbnail and its deltas ("tactile · 55 gf"). Incompatible ones are greyed with the failed check. Both halves swap together when the alternative is compatible.
- **Position** fields edit with drag-to-scrub, like Figma, and send `move` on release (C20 MoveGizmo also works on the canvas).
- **Colour** is C22 ColorPicker inline: a swatch, a hex field and the material.
- Remove sits at the bottom, needs a confirm, and only shows for optional slots.
- Esc clears the selection and returns the panel to the build.

### 2.4 Clarify (vague prompt)

```
                    +--------------------------------------------+
                    | QUESTION 1                        ◔ 0:48   |
                    | What should it do?                          |
                    | [Show the weather] [Be a clock]             |
                    | [Watch a plant] [Be a desk light]           |
                    | [ or say it…                     ]  just pick →|
                    +--------------------------------------------+
   +-----------------------------------------------------------------------+
   | V H O | ⧉ explode ...  | + ⌁ | (o o)  Ask Bara…                         |
   +-----------------------------------------------------------------------+
```

- C30 ClarifyCard pops up from the Ask field, like Figma's AI prompt panel, because that's where the conversation lives. The agent looks confused, and the canvas stays empty.
- After `clarify.resolved`, the card collapses back into the Ask field. Assumptions appear as chips in the Design tab's spec section.

### 2.5 Failure

C25 FailureCard is centred on the canvas: the headline, the two conflicting requirement chips, the explanation, and the suggestion buttons (each sends `build.start`). In the left panel, the dead-end slot's layer shows a ✕, and in Builds the build shows a ✕.

### 2.6 Disconnected

C26 ConnectionBanner is a slim bar across the top of the canvas ("Reconnecting… attempt 3"). The panels stay as they were, editing is disabled, and the agent's eyes go flat (offline) until resync.

### 2.7 Where each component lives now

| ID | Component | Figma-style home |
|---|---|---|
| C01 | TopBar | Split: `Bara ▾` and the build name top-left; avatar, Export, Preview and zoom top-right |
| C02 | PromptBar | Home: centre left. Workspace: the Ask field in the bottom toolbar |
| C03 | ExampleChips | Home, under the prompt |
| C04 | StageTimeline | Left panel header (step player) plus a progress line on the canvas top edge |
| C05 | LatencyHUD | Timing chip, canvas bottom right; full numbers in the Build tab |
| C06 | DecisionTrace | Right panel, Build tab |
| C07 | SpecCard | Right panel, Design tab when nothing is selected |
| C08 | ReuseCard | Right panel, Design tab when nothing is selected |
| C09 | PartsList | Left panel, Layers tab |
| C10 | Viewport3D | Canvas |
| C11 | ViewportToolbar | Bottom toolbar (View group); toggles for case, keycaps and labels move to the View menu under the zoom % |
| C12 | PartInspector | Right panel, Design tab when a part is selected |
| C13 | SwapDrawer | Instance-swap dropdown on the part name |
| C14 | ConnectionView | Right panel, Code tab |
| C15 | BoardView | Right panel, Code tab |
| C16 | FirmwareView | Right panel, Code tab |
| C17 | ChecksPanel | Checks section in the Design tab, plus status marks on layers |
| C18 | WarningBanner | Toast stack above the bottom toolbar; list in the Build tab |
| C19 | EditStatus | Toast above the bottom toolbar, with Undo |
| C20 | MoveGizmo | Canvas, on the selected part; Position fields in the Design tab |
| C21 | ResizePanel | Case section of the Design tab |
| C22 | ColorPicker | Colour section of the Design tab |
| C23 | ConnectDialog | Connect tool (C) in the bottom toolbar |
| C24 | ExportMenu | Export button, top right |
| C25 | FailureCard | Centre of the canvas |
| C26 | ConnectionBanner | Slim bar across the top of the canvas |
| C27 | ProvenanceBadge | Source section in the Design tab, and on Assets tiles |
| C28 | AddPartPicker | Left panel, Assets tab |
| C29 | EventLog | Main menu or L, as a drawer over the left panel |
| C30 | ClarifyCard | Popover from the Ask field |

### 2.8 Keyboard (Figma's where they overlap)

| Action | Key |
|---|---|
| Select, Pan, Orbit | V, H, O |
| Explode | E |
| Views iso, top, front, side | 1 to 4 |
| Zoom to fit, zoom to selection | ⇧1, ⇧2 |
| Ask Bara | ⌘K |
| Undo, redo | ⌘Z, ⇧⌘Z |
| Hide panels | ⌘\ |
| Clear selection | Esc |
| Add part, Connect | A, C |
| Shortcuts | ⌘/ or ? |
| Event log | L |

---

## 3. Build order

Hours line up with PLAN.md section 5 (N column). "Done when" is what proves the milestone; the fixture column is what to play.

| # | Hours | Build | Fixture to mock against | Done when |
|---|---|---|---|---|
| M0 | H0-2 | Repo, types from schemas, fake socket and REST stub (SPEC 13), Build store and reducer (SPEC 9), view stores, C29 EventLog | `exact_keyboard`, `rest/build_exact`, `rest/vocab`, `rest/health` | All 65 steps of `exact_keyboard` show in C29 and the reduced store deep-equals `rest/build_exact` (contract test C6 in the UI) |
| M1 | H2-6 | First visible build: C01 TopBar, C02 PromptBar, C03 ExampleChips, C04 StageTimeline, C10 Viewport3D (bbox fallback first, GLB second), C09 PartsList, C05 LatencyHUD | `exact_keyboard` | Typing "keyboard" goes Home to Workspace, the Corne appears part by part, and the HUD shows time to first part |
| M2 | H6-10 | The reasoning column: C07 SpecCard, C08 ReuseCard, C06 DecisionTrace (filter chips counting down), C27 ProvenanceBadge, C17 ChecksPanel, C18 WarningBanner, C25 FailureCard | `compose_wireless_split_oled`, `failed_critical_missing` | Compose plays with slots narrowing one by one, the optional foam slot ends `none` with a warning, and the 60% Choc prompt ends on the failure card with working suggestion buttons |
| M3 | H10-14 | Edits: C12 PartInspector, C13 SwapDrawer, C19 EditStatus, remove from C09 and C12 | `edit_swap_switches`, `edit_rejected_choc`, `edit_remove_part`, `rest/alternatives`, `rest/part` | Swap to MX2A Brown applies, swap to Choc is rejected with the failed check shown and nothing changed, and removing the left OLED drops its connection and then the part |
| sleep | H14-18 | | | |
| M4 | H18-22 | Rest of the right column and the vague-prompt path: C30 ClarifyCard, C16 FirmwareView (prebuilt badge, compile progress), C14 ConnectionView, C15 BoardView, C11 ViewportToolbar (explode, view presets, toggles), C24 ExportMenu | `clarify_vague_gadget`, `compose_wireless_split_oled` (late compile) | Two clarify rounds play (one answered, one skipped with an assumption chip), the compile progress bar fills after `build.done`, and explode works on the finished Corne |
| M5 | H22-26 | Robustness and the real backend: C26 ConnectionBanner (keepalive, backoff, resume, snapshot), switch off mock, run contract tests C7 and C8 | `resume_gap`, then the real server | Killing the tunnel mid-build shows the banner, keeps the state, and resumes; every fixture plays in mock mode with no console errors (C7); the tolerance replay renders the same final state (C8) |
| M6 | H26-28, stretch | C20 MoveGizmo, C21 ResizePanel, C22 ColorPicker, C23 ConnectDialog, C28 AddPartPicker | real backend only (see 4.2), plus `rest/parts_search` for C28 | Each op round-trips against the real server and shows applying, then applied or rejected |
| polish | H28-32 | Demo pass: camera ease to `scene.camera`, part drop-in animation, HUD styling, empty and skeleton states (SPEC 12 "What the UI shows while waiting"), record the video | all chips, real backend | The three demo prompts run cleanly five times in a row on the venue network |

**Cut order if behind** (first to go first): M6 components, then C23 and C28, then C15 BoardView detail (keep the download link), then C14 detail. Never cut C10, C04, C05, C06, C12 and C13: they are the demo.

---

## 4. Fixture coverage

### 4.1 Which fixture proves which component

| Fixture | Steps | Components it exercises |
|---|---|---|
| `exact_keyboard` | 65 | C01 C02 C03 C04 C05 C07 C08 (exact) C09 C10 C11 C14 C15 C16 (prebuilt) C17 C24 C29; compose shows as skipped |
| `compose_wireless_split_oled` | 101 | C06 (15 slot updates, 6 candidate lists) C08 (compose) C16 (late compile) C18 (2 warnings) and everything in exact |
| `failed_critical_missing` | 17 | C25, C06 `dead_end`, C04 failed row, C02 back to ready |
| `clarify_vague_gadget` | 65 | C30 (2 rounds), C07 assumption chips, C16 compiled mode, generated gray case in C10 |
| `edit_swap_switches` | 8 (after exact) | C12 C13 C19, `part.updated` on both switch arrays |
| `edit_rejected_choc` | 5 (after exact) | C13 rejected state, C19 rejected with failed check |
| `edit_remove_part` | 7 (after exact) | C09 and C12 remove, C14 `connection.removed` before `part.removed` |
| `resume_gap` | 9 (after exact) | C26: ping/pong, `E_RESUME_GAP`, `build.snapshot`, duplicate resume ack |

The edit and resume fixtures chain onto `exact_keyboard` (`requires_fixture`), so the mock replays the keyboard build first.

### 4.2 Gaps the fixtures don't cover

- **Move, resize, recolor, connect, add_part.** No fixture has these ops. In mock mode they play `edit_rejected_choc` with "not available in mock mode", which is why C20 to C23 and C28 sit in M6 and need the real backend.
- **`decision.reverted`.** No fixture sends it (SPEC 14.1). C06 must still handle it. At the event, add a one-line event to a local copy of the compose stream for a quick check. Don't change the frozen fixtures.
- **`build.cancel`.** No fixture covers Stop. Check it against the real server in M5 (SPEC 8.9: ack, open stage fails, `build.failed` with `E_CANCELLED`).
- **Timing.** `exact_keyboard` plays in 267 ms of total delay, which is realistic but too fast to watch while building. Use `?mock_speed=4` or slower while developing and `1` for rehearsal. `compose_wireless_split_oled` runs about 39 s, mostly the late firmware compile.

### 4.3 Assets the mock needs

Mock mode serves `/assets/...` from `public/assets/`. The fixtures reference 21 GLBs (15 parts, 2 Corne design cases, 4 generated cases), 25 PNG thumbnails, 3 `kicad_pcb`, firmware binaries (`.uf2`, `.hex`, `.bin`) and 3 STLs. Converting STEP to GLB is a script, so it waits for the event too. Until the GLBs exist, the bbox fallback carries the demo, which is why it comes first in M1.

---

## 5. Interaction details worth deciding now

- **Parts appearing** is the show. Each `part.added` drops its part in at the pose given as an ASCII silhouette (this is how the provisional state shows), and the part resolves into the solid rendered mesh on `placement.updated` (section 8.7). A layout (`layout.added`, the key grid) fades in as one instanced mesh, not 42 separate drops.
- **Optimistic edits.** A drag or pick shows at once, then is confirmed by `edit.applied` or rolled back by `edit.rejected` (SPEC 12, edit row). C19 tracks each edit by `msg_id` and `edit_id`.
- **Check colours.** Pass and ok are green, critical or error red, warning amber, info and unknown grey (SPEC 11.4). The unknown enum value always gets the neutral style.
- **Keyboard.** Figma's shortcuts where they overlap (section 2.8). None of it is in the spec; it's UI only.
- **Numbers.** mm to one decimal, ms as integers, with the unit taken from the field suffix.

---

## 6. Test hooks at the event

- C6 in the UI: reduce `exact_keyboard`, deep-compare with `rest/build_exact`. This is the first test written, in M0.
- C7: a script that plays every stream fixture headless in mock mode and fails on any console error. Run it on every UI change.
- C8: the tolerance replay (unknown field on every object, one unknown event inserted). Run it once a day.

---

## 7. Open questions

1. **Demo prompts.** PLAN.md section 5 scripts a "handheld weather station with an e-ink screen", but every fixture and the frozen spec are keyboards plus one vague desk gadget. Pick the three rehearsed prompts with Pranav before H28, and make the ExampleChips match them.
2. **Room view on phones** (SPEC 16, still open). If it's in, it's a read-only Workspace at phone width that joins with `build.resume` and `last_seq: 0`. It isn't planned in any milestone yet, so it would come after M5.
3. **Which skill-library shell.** Choose the panel and tab primitives before H0 so M0 doesn't stall on it. Choosing is ideation; writing the shell isn't.
4. **Handwriting face.** Caveat is the pick for annotations (section 8.4). Kalam is the fallback if Caveat reads too loose at small sizes on the projector.
5. **Agent name.** The face is called Bara for now. Decide whether the agent gets its own name or is simply the product.
6. **Homepage stage.** Settled: the Corne from the fixtures, drawn as an ASCII print (section 8.6). No third-party engravings needed.
7. **Figma layout vs SPEC 11.1.** Section 2 moves components to Figma-style homes (2.7). Events and states are unchanged, but SPEC 11.1 and the "Where" column of 11.2 describe the old three columns. Agree with Pranav that this is a UI-only note, not a spec change.
8. **The agent's cursor.** It needs to know which part the agent is on. The stream already says the stage and slot (`slot.updated`, `part.added`); check with Pranav that this is enough, or whether a `subject` on `stage.progress` is worth adding as an additive field.

---

## 8. Design brief

This section is the visual and motion contract for the UI. It sits on top of SPEC.md section 11 and changes no event or state there. It says how each component looks, moves and reacts; section 2 says where it sits.

**Status (2026-10-23).** A local prototype in `ui/` (not the Cal Hacks repo) builds most of this brief against the mock fixtures: tokens, type, the agent, the homepage stage, ASCII generation and the workspace. It still uses the earlier three-column workspace. The Figma layout in section 2 is the target for the next pass.

### 8.1 Direction in one line

A hand-coloured print of real parts, laid out like Figma: cream paper, ink type, pastel washes, one two-eyed agent, and everything joins and separates like liquid.

Three words to check every screen against: **inked, liquid, alive.**

- **Inked:** the base layer is paper and ink. ASCII type, hairlines, a warm old-style serif. Nothing glossy, no glass. The only gradient is the agent's body.
- **Liquid:** anything that connects, disconnects, opens, closes, merges or splits does it like a fluid, on springs, never on a straight timeline.
- **Alive:** something always reacts to what the engine is doing. The agent's eyes, the parts arriving in type, the progress line. The page itself does not chase the cursor.

### 8.2 References and what we take from each

| Reference | What to take | What not to take |
|---|---|---|
| Figma (UI3) | Where everything sits: layers left, properties right in stacked sections, a floating tool bar at the bottom, avatars and the one primary action top right, toasts above the toolbar, multiplayer cursors, instance swap, scrub-to-edit fields, shortcuts | Figma's chrome colours and type. We keep paper, ink and pastels |
| Tinkercad | The view cube in the top-right corner, the camera buttons under it, the blue grid workplane, parts in flat role colours, a palette of shapes (our Assets tab) | The flat untextured rendering. Ours is lit, shadowed and inked |
| Etch (etch.chat) | The agent: two rounded eyes on a soft dark body, states, activities and emotes on springs; the "Ask" pill with the eyes inside it | Its blue and white palette |
| Grok's bot | A character that's always reacting, built from very few shapes | Grok's 3D companions |
| [bencho.dev](https://bencho.dev/) | The motion vocabulary: generate (broad shapes first, detail last), metaball toggles, step player, slosh slider, rolling counter, toast stack, dynamic island | The code. It's a paid library whose licence forbids passing blocks on. The cursor-following ASCII wake, which we tried and dropped |
| [aidanjs.com](https://aidanjs.com/) | Flat cut-paper shapes and a Dr. Seuss sense of play, now only in the homepage blobs and the hand-drawn notes | The eyes-everywhere layout, and Inter |
| The Goudy screenshot ("The Agentic Data Company") | A warm old-style serif for display type | Its body face; ours stays Schibsted Grotesk |
| [diabrowser.com](https://www.diabrowser.com/), [thebrowser.company](https://thebrowser.company/), Arc's year-end video | Human type: a warm serif with one italic word, quiet body text, tracked uppercase mono for small labels, one hand-drawn accent | Their paid fonts (Exposure, ABC Oracle, ABC Favorit Mono, Ivar) |

### 8.3 Colour

Light theme only for the demo. The projector and the video both read better on paper than on black.

**Paper and ink**

| Token | Hex | Use |
|---|---|---|
| `paper` | `#F6F1E7` | Page background everywhere |
| `paper-2` | `#EFE8DA` | Panels, cards, the generated gray case |
| `paper-3` | `#E6DCC8` | Pressed states, dividers on paper-2 |
| `ink` | `#1E1B18` | Text, ASCII, hairlines, the agent's outline |
| `ink-soft` | `#5C554C` | Secondary text, idle ASCII |
| `ink-faint` | `#A39A8C` | Muted labels, grid minor lines |
| `grid` | `#A9CBEA` | Workplane grid major lines (the Tinkercad blue, softened) |

**Pastel accents (decorative and part roles)**

| Token | Hex | Part role it marks |
|---|---|---|
| `teal` | `#7CC6B8` | Controller, MCU |
| `lilac` | `#B9A7E3` | Switches |
| `sky` | `#9EC9EE` | Display |
| `butter` | `#F4D58D` | Power: battery, charger, regulator |
| `mint` | `#A8D8B0` | Plate and structural parts |
| `peach` | `#F6B89A` | Keycaps and user-facing caps |
| `rose` | `#EFA9C2` | Sensors, other I/O |

**Status (reserved, never decorative)**

| Token | Hex | Meaning (SPEC 11.4) |
|---|---|---|
| `ok` | `#2E9E5B` | pass, ok |
| `fail` | `#D64545` | fail with severity critical or error |
| `warn` | `#E0A030` | warning |
| `neutral` | `#9A948A` | info, unknown |

Rules:

- Pastels are soft and status colours are saturated, so a failing check never looks like a part colour. Status is always paired with a shape too (dot, cross, triangle), never colour alone.
- At most two pastels on screen besides the part roles. The page stays mostly paper and ink.
- Washes in the ASCII print use the part's role pastel at 35 to 80 percent, lighter where the surface catches more light.

### 8.4 Type

System A with Sorts Mill Goudy as the display face (the Goudy look from the reference screenshot), plus a handwriting face for annotations. Every face is free under the SIL Open Font Licence and served from Google Fonts. No Inter, Geist, SF Pro or system-ui anywhere.

| Role | Face | Settings | Used for |
|---|---|---|---|
| Display | **Sorts Mill Goudy** (roman and italic) | 400; the one emphasised word in italic; tracking about -1 percent | Homepage hero, screen titles, the failure card headline, empty states |
| Body | **Schibsted Grotesk** | 400 and 500, 15 to 17 px, line height 1.55 | Part names, reasons, inspector text, buttons, prompt bar input |
| Labels, numbers, ASCII | **Fragment Mono** | 400, 11 to 13 px; uppercase with 0.12 em tracking for labels; tabular figures for numbers | Stage names, tab labels, latency HUD, ms and mm values, pin tables, firmware code, all ASCII art |
| Agent voice | **Shantell Sans** (variable: wght, BNCE, INFM, SPAC) | 400, 15 to 17 px; INFM 0 to 100 with the agent's mood; BNCE animated while it speaks | The agent's speech bubble only |
| Annotation hand | **Caveat** | 500, 18 to 26 px, ink or ink-soft | Margin notes and arrows: callouts on the 3D view ("3V3 rail"), the homepage notes on the device's parts, the first-run hint ("click any part to swap or recolour it"), empty states |

Type scale (px): hero 88, h1 40, h2 28, h3 20, body 16, small 14, label 12, smallest 11.

Rules:

- One italic word per heading, at most. It marks the idea ("Engineer *anything*.", "Pick *parts*").
- Anything a machine produced (numbers, ids, units, code, ASCII) is in Fragment Mono. Anything a person would say is in Schibsted Grotesk. The agent speaks in Shantell Sans. Notes in the margin are Caveat.
- Caveat and Shantell Sans never carry data. No part numbers, values or check results in handwriting.
- The display face doesn't animate. Goudy's old-style warmth carries the human feel; motion lives in the parts and the agent.
- Shantell Sans moves: BNCE rises while the speech bubble types out and settles to 0 when it stops. INFM is high when the agent is joking or unsure, low when it's reporting.
- Paid upgrade path, if we ever license: Exposure for Sorts Mill Goudy, ABC Oracle for Schibsted Grotesk, ABC Favorit Mono for Fragment Mono, Ammer Handwriting for Caveat. Trial fonts aren't licensed for a public demo or video, so not for Cal Hacks.

### 8.5 Less text

The screen is carried by the face, rendered parts, icons, numbers and motion. Words come only when asked for.

- **Default view shows:** icons, rendered part thumbnails, numbers with units, one-word labels, the agent's eyes. No sentences.
- **On hover:** the short reason (decision reason, check name, licence).
- **On click:** the full text in C12 PartInspector or C17 ChecksPanel.
- **Allowed sentences by default:** the agent's bubble (one line, under 60 characters), the clarify question, the failure headline, error messages. That's it.
- Every SPEC 11.2 component keeps its data. The text just moves one level down (hover or click), it isn't removed.

### 8.6 Homepage

Built in the prototype (`ui/src/screens/Home.tsx`, `ui/src/viewport/HomeStage.tsx`).

- **The stage** is a real open design, the Corne, rebuilt from the `exact_keyboard` fixture's own stream, so it's the same data a build produces. Every part is drawn as a hand-coloured ASCII print: each screen cell is inked with a glyph picked by how much light that surface catches, on a wash of the part's role colour. It sits on two flat pastel blobs (butter and lilac).
- **Motion:** the device slowly breathes apart into its exploded view and back (about a 15 s cycle) and turns a few degrees either way. Nothing else on the page moves on its own.
- **Margin notes** in Caveat point at the parts: Pro Micro, OLED, 42 MX switches, open PCB · MIT. They ride along with their parts as the device opens.
- **Hover:** a round lens follows the pointer over the print and opens it onto the rendered model underneath. A Caveat note says "hover to see it rendered".
- **Copy:** the hero in Sorts Mill Goudy ("Engineer *anything*."), one sentence under it, and nothing else.
- **The prompt** has the agent's eyes inside it, on the left. While you type, the eyes listen (the userTalking state, with each keystroke as a level pulse). On send, they nod (heard) and the workspace takes over on `ack`.
- **Example chips** are a rendered part icon plus two or three words; the full prompt is the tooltip.
- **The parts strip** along the bottom: rendered tiles of real parts from the fixtures, each with its licence ("licence ?" when it isn't asserted), under the label "every part is real".
- Dropped from the first plan: the classical engraving (it said nothing about the product) and the cursor-following ASCII wake.

### 8.7 Workspace look

The layout is Figma's (section 2). The canvas is Tinkercad's, rendered properly.

- **Panels:** paper with a hairline edge, Figma's widths (left about 248 px, right about 300 px). Section headings in Fragment Mono caps; values in Fragment Mono; names in Schibsted Grotesk. Sections separate with a hairline, not cards.
- **Workplane:** an infinite grid, `grid` blue major lines every 25 mm and warm minor lines every 5 mm, fading with distance. Contact shadows under the build. The plane drops with the case when the build explodes.
- **View cube, top right of the canvas:** a small cube in paper-2 with ink edges and Fragment Mono face labels, drawn in its own tiny canvas that mirrors the main camera every frame. Hovering a face turns it butter; clicking eases the camera to that view. The camera group sits under it.
- **Rendering:** React Three Fiber; clay materials in the part's role colour (roughness about 0.6) with an inverted-hull ink outline; a hemisphere light plus a warm key and a cool rim; neutral tone mapping, which keeps the pastels from washing out to grey or white. Generated parts and the case get the same clay. Real GLBs replace the procedural stand-ins when they exist (SPEC 11.4 fallback until then).
- **Selection (Figma):** a thin teal bounding box with corner handles, a size label in mm under it, and the part's ink outline turning teal. Hovering a layer or a part draws the teal outline only.
- **Icons:** part tiles, Assets and example chips are rendered in-app from the same scene lighting into an offscreen renderer and cached. Toolbar icons stay as line icons (Tabler), borderless inside their groups.
- **Generating (the ASCII layer):** a part arrives as an ASCII-shaded silhouette in its role colour and resolves into the render once placement lands (at least 480 ms in type, then a 520 ms reveal). This is how the provisional state of SPEC 11.2 C10 shows. Hovering a part that is still generating puts a lens over it: the type gets finer and darker inside the lens, a ring marks its edge, and a small ink label says "generating" with the part's name and quantity. The case generates the same way.

### 8.8 The agent

Etch's mascot, carried over: two rounded white eyes on a soft dark body, nothing else. All expression comes from the eyes' shape, size and position, blinks, and the body's squash, stretch and tilt, all on springs, so every change is a morph. The engine is `ui/src/agent/eyes.ts`, a TypeScript port of Etch's `eyes.js`, with the body warmed to Bara's ink (`#34302B` to `#171512`) and the eyes in paper white.

**Where it lives**

- **Ask field**, bottom toolbar: the eyes sit inside it, as in Etch's "Ask Etch" pill. Its speech bubble (Shantell Sans, one line, typed out) rises from there.
- **Avatar**, top right of the right panel, where Figma shows collaborators. Clicking it opens the thought log.
- **Multiplayer cursor** on the canvas while it works, with a name tag saying what it's doing and to which part.
- **Homepage**: inside the prompt bar.

**States** (sustained)

| State | Looks like | Set by |
|---|---|---|
| idle | Open eyes, slow breathing, glances around, follows the cursor gently | `hello`, after edits |
| userTalking | Eyes grow and pulse with each keystroke | Typing in the Ask field or the homepage prompt |
| heard | Happy half-closed eyes, a nod | Prompt sent, `clarify.resolved` |
| working | Eyes narrowed in concentration | `stage.started`, `firmware.progress` |
| thinking | Eyes up, three dots orbiting overhead | Long waits with no activity |
| confused | One eye bigger, head tilted | `clarify.request` |
| success | Eyes arched happy, a hop | `build.done` |
| error | Dimmed, droopy lids, body sags | `build.failed` |
| offline | Eyes flatten to lines, dim | C26 reconnecting or offline |

**Activities** (acted out with the eyes while working)

| Activity | Motion | Stage |
|---|---|---|
| read | Eyes sweep left to right, line by line | classify |
| scan | Fast side to side, with a small teal lens glint | reuse |
| pick | Darts between random points, blinks between picks | compose, `candidates.ready` |
| inspect | One eye squints, small head tilt | place, edits |
| render | Eyes circle slowly | enclose, render |
| route | Figure-of-eight trace | board |
| repair | A quick shake, then steady | firmware |
| export, wait, think | A bounce looking down; a slow drift; looking up | export, idle waits |

**Emotes and kicks** (one-shot)

| Emote | Trigger |
|---|---|
| delight (bounce, happy eyes) | `reuse.decided` exact, `build.done` |
| pleased (nod) | `reuse.decided` compose, `firmware.ready`, `edit.applied` |
| nod | `spec.ready`, `decision.made` |
| shake | `decision.reverted` |
| wince (squish, then shake) | `check.result` with a fail, `edit.rejected` |
| surprise | `warning` above info |
| squish | `part.removed`, cancel |
| yawn | A minute idle |

The full event mapping is `ui/src/agent/moods.ts`. The design system page (`#system`) shows every state, every activity and a button for each emote.

### 8.9 Motion

**Principles**

- Springs, not keyframes. Three presets:
  - `snap`: stiffness 420, damping 32. Presses, toggles, selection.
  - `liquid`: stiffness 180, damping 14. Connect, disconnect, merge, split, panels opening.
  - `soft`: stiffness 110, damping 20. Camera, page transitions.
- **Less is more.** Motion marks something the engine or the user did. Nothing moves just because the cursor passed by: magnetic pull is subtle (about 8 percent of the offset), tiles lift 2 px on hover and never tilt.
- The thing under the cursor never lags it. Only what follows it is liquid (the bencho slosh rule).
- Liquid shapes are metaballs (an SVG blur plus alpha threshold) on small regions only.
- Every motion starts from where the thing came from. A section opens out of its heading, a toast rises from the toolbar, a swap pours in at the same pose.

**Vocabulary**

| Where | Motion |
|---|---|
| Buttons | Press squashes to 0.96 on `snap`; a small ink drop spreads inside the pill |
| Ask field (C02) | Send and Stop are one metaball that morphs; the field grows into the full prompt on focus |
| C03 ExampleChips, C30 options | Lift 2 px on hover; the picked one flows into the field |
| C04 StageTimeline | Step player: the active dot stretches into a bar that fills, then eases to the next dot; the canvas progress line fills in step |
| Timing chip (C05) | Rolling odometer digits; expands into per-stage rows on hover |
| C06 DecisionTrace (Build tab) | Filter chips drain as counts fall; the winner drops into its slot; a dead end shakes |
| C09 Layers | New rows slide in under their slot group; removed rows collapse on `liquid` |
| C10 Canvas | Parts arrive in type and resolve; explode is a spring; the camera eases on view changes |
| C12 Design tab | Sections swap with a short cross-fade when the selection changes; no overlay slides in |
| C13 instance swap | The dropdown opens like a drop from the name; the old part melts out as the new one pours in |
| C14 Wires (Code tab) | Connect: two port blobs fuse with a gooey thread. Disconnect: it pinches off |
| C18, C19 toasts | Stack above the toolbar, peeking; hover fans them into a list; rejected edits shake once |
| C21 Case, explode | Slosh sliders: the handle is rigid, the fill moves like liquid |
| C25 FailureCard | The two conflicting chips bump into each other and bounce apart |
| C26 | The canvas fades to grey; the agent's eyes go flat |
| Agent | Always on springs (section 8.8) |
| C29 EventLog | No motion |

### 8.10 Every step shows something

No event goes by without a visible change. Where SPEC 11.3 says no Build change (view state only), the UI still reacts.

| Event | Agent | Panels and canvas |
|---|---|---|
| `hello` | idle, blink | Ask field enables |
| `ack` for `build.start` | heard | Home hands over to the workspace; a Builds row appears |
| `stage.started` | working + that stage's activity | Step player and progress line advance; the agent's cursor moves |
| `stage.progress` | (activity continues) | The active bar fills |
| `stage.completed` | (none) | Dot settles; its ms rolls into the Build tab and the timing chip |
| `clarify.request` | confused | C30 pops up from the Ask field |
| `clarify.resolved` | heard | The card folds back; assumption chips in the Design tab |
| `spec.ready` | nod | Spec chips in the Design tab |
| `reuse.decided` | delight (exact) or pleased (compose) | Design and tier in the Design tab |
| `slots.ready` | (none) | Layer groups appear, empty |
| `slot.updated`, `candidates.ready` | pick | Filter chips drain in the Build tab |
| `decision.made` | nod | The winner drops into its layer group |
| `decision.reverted` | shake | The decision pops back out |
| `layout.added` | (none) | The key grid appears in type |
| `part.added` | (cursor moves to it) | Layer row slides in; the part arrives in type |
| `part.updated` | (none) | Melt and pour in place |
| `part.removed` | squish | Layer row collapses; the part dissolves |
| `connection.added`, `connection.removed` | (none) | Wire fuses or pinches off in the Code tab |
| `placement.updated` | (none) | Parts glide to their poses and resolve into the render |
| `enclosure.updated` | render | The case arrives in type, then solid |
| `board.updated` | route | Board section fills in the Code tab |
| `firmware.progress` | repair | Compile bar fills in the Code tab |
| `firmware.ready` | pleased | Firmware section with its mode badge |
| `scene.ready` | (none) | Camera eases to `scene.camera` |
| `check.result` fail | wince | Red outline and a ✕ on the layer; the tab badge bumps |
| `warning` | surprise (info: speaks only) | Toast above the toolbar |
| `build.done` | success, delight | Export wakes up; the Builds row settles |
| `build.failed` | error | C25 on the canvas; ✕ on the slot and the build |
| `edit.applied` | pleased | Toast with ms and Undo |
| `edit.rejected` | wince | The optimistic change springs back; toast shows the failed check |
| `build.snapshot` | (wakes from offline) | The canvas returns to colour |
| `error`, `pong` | offline or idle | C26 bar state |
| unknown event | (none) | C29 logs it |

### 8.11 Sound (optional, cut first)

Soft clicks on press, a wet pop on connect, a reverse pop on disconnect, a paper rustle when a part dissolves, a chime on `build.done`. Off by default, toggle in the top bar. Not in the demo video unless it helps.

### 8.12 Performance and accessibility

- 60 fps on the demo laptop while a build streams. Measure with the compose fixture at real speed.
- The ASCII layer is a fragment shader on the parts themselves, so it costs nothing when no part is generating. The homepage stage is the only always-on canvas.
- Goo filters only on small regions (chips, ports, buttons, the Ask field). Never full screen.
- `prefers-reduced-motion`: springs become 120 ms fades, the homepage device holds still, the agent changes state without moving.
- Text contrast AA on paper (ink and ink-soft pass; ink-faint is for non-text only; placeholders use `#8A8174`).
- Status always pairs colour with a shape. Every icon-only button has an accessible label and a tooltip with its shortcut.
- Everything works from the keyboard (section 2.8). Destructive actions confirm; everything else can be undone.

### 8.13 Where the design work lands in the build order

| Milestone | Design work |
|---|---|
| M0 | Colour and type tokens, fonts, spring presets, the eyes engine |
| M1 | Figma shell (left panel, right panel, bottom toolbar), canvas with workplane and the top-right view cube, ASCII arrival, step player |
| M2 | Layers tree, Design tab sections for the build, Build tab with the decision trace, toasts |
| M3 | Selection box and size label, Design tab for a part, instance swap, Undo |
| M4 | Code tab (wires, board, firmware), clarify popover, case sliders, the agent's cursor |
| M5 | Offline state, reduced motion |
| polish | Homepage stage, rendered icons, margin notes, Preview mode, sound if there's time |

**Design cut order** (first to go first): sound, Preview mode, the agent's multiplayer cursor, drag-to-scrub fields, the homepage margin notes. Never cut: the agent reacting to every stage, parts arriving in type and resolving, the Figma layout itself.

### 8.14 Licences and the prior-work rule

- Fonts: Sorts Mill Goudy, Schibsted Grotesk, Fragment Mono, Shantell Sans and Caveat are all SIL OFL. Credit them in SOURCES.md.
- The agent ports Nithin's own Etch code. For the Cal Hacks repo it's rewritten there and listed in the Devpost disclosure as carried over from Etch; ask the organisers first if any Etch code is imported as is (PLAN.md section 0).
- Bencho: references only. No code copied.
- Figma, Tinkercad, Grok and aidanjs: layout and ideas only, no assets.
- The homepage stage is drawn from the fixtures' own parts, so it needs no third-party images.
- Everything in this section is a written brief for the event build (PLAN.md section 0). The `ui/` prototype is a local design study in this repo, not the Cal Hacks code.
