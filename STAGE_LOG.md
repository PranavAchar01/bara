# Bara stage log

Figma track, Cal Hacks 13.0. One log entry per stage, at most 200 words each. Minutes are approximate, reconstructed from file and tool timestamps on Friday 23 October 2026 (Pacific time).

**Prior-work check.** Work in this log started at 17:28 on Friday, during or just after the opening ceremony (16:00 to 18:00). Confirm with a director in #0-ask-directors that this counts as started during the event, or disclose it in the Devpost write-up.

## Files

| What | Figma product | Link |
|---|---|---|
| UX teardown and flow | FigJam | https://www.figma.com/board/e7QBSniO3uaHb5UV7P3eff |
| Design system, 12 screens, type directions | Figma Design | https://www.figma.com/design/Uke0NZXCfmrtUvUP6BbMS5 |
| Explode, focus, ask prototype | Figma Make | https://www.figma.com/make/GUcQ6J52Xc1vU4Kbp9b6Cy |
| Submission deck | Figma Slides | https://www.figma.com/slides/9wco0jIkMMw6qbi9Fwsxqs |

All four must be shared to "Anyone" before submitting.

## Timeline

| Time | What happened |
|---|---|
| 17:28 | Read UI_PLAN.md (written before the event as a plan, no code) |
| 17:38–17:46 | Tokens and type styles in Figma Design through the Figma agent (MCP) |
| 18:12–18:21 | Components and the first workspace screen; hit the Starter plan's agent call limit |
| 18:28–18:47 | Moved to the Go Bears student plan, rebuilt the file, built six screens |
| 18:47–19:16 | Palette pivot to white, Build and Code tabs, command palette, three rounds of type |
| 19:27–19:31 | ASCII limited to a loading skeleton; parts redrawn as simple 3D blocks |
| 19:38–19:46 | FigJam teardown, Figma Make prototype, focus screens |

## Stage 1 · Ideation

**Tools:** FigJam (state diagram plus 26 stickies), Figma Design (type direction boards), both driven by the Figma agent through MCP.

**Why:** we needed to argue about the experience before drawing it. FigJam is fast for a flow and for lists of problems; Design boards let us compare type in the real UI, not in a specimen.

**Minutes:** about 35.

**How well it worked:** 4/5.

**Into the final project:** the teardown named the core problem ("you can't see inside the build") and produced the focus mode: explode, pick one part, ask about it, Esc to step back. Type went through three rounds (popular pairings, then niche ones) and landed on Averia Serif Libre with Atkinson Hyperlegible. A palette review moved us from cream and pastels to white and neutral greys with one blue accent.

**Friction:** generate_diagram makes its own file, so the board started in Drafts. The first type round was rejected as "what everybody uses"; that rework was worth it.

## Stage 2 · Prototyping

**Tools:** Figma Design via the Figma agent (variables, 21 components, 7 part renders, 12 screens), then Figma Make for a clickable prototype.

**Why:** Design for the full set of states the engine can reach (running, clarify, failure, offline, selected, command palette); Make for the one interaction that had to be felt, not looked at: explode, focus, ask.

**Minutes:** about 110.

**How well it worked:** 4/5.

**Into the final project:** every colour and type style is a variable or style, so the white pivot and the font change each restyled all screens in one step. The Make prototype is the demo flow.

**Friction (honest):**
- The Starter plan cut the agent off mid-build; we moved to the student plan and rebuilt from saved scripts in about 20 minutes.
- Bound colours silently dropped their opacity (selection blues came out solid) four times before we found the fix.
- Figma rewrote skew transforms, so the 3D keyboard is now drawn as pre-projected vectors.
- The first ASCII and pastel looks were rejected; ASCII survives only as the loading skeleton.

## Stage 3 · Handoff

**Tools:** Figma Design variables and component descriptions.

**Why:** the engineer building the real UI should not have to measure anything.

**Minutes:** about 10 so far.

**How well it worked:** 3/5. In progress.

**Into the final project:** every variable carries its CSS name (`var(--paper)`, `var(--accent)`, `var(--part-keycap)`), so tokens export straight to CSS. Each component's description says when it appears and how it moves (for example, "ASCII is reserved for this loading state only"). Keyboard keys are documented in the components (Kbd, Tooltip) and in the help overlay.

**Still to do:** Code Connect mappings from Layer Row, Ask Field and Command Palette to the React components once they exist.

## Stage 4 · Code generation

**Tools:** Claude Code wrote the prototype's HTML, CSS and JS; Figma Make imported it (send_code_to_figma).

**Why:** the prototype had to run, with voice, keys and live state, which a click-through prototype can't do.

**Minutes:** about 15, including two bugs found by testing in a browser (an overlay that ignored `hidden`, and clicks lost because hover redrew the element under the pointer).

**How well it worked:** 4/5.

**Into the final project:** the projection maths and part data in `app.js` are the same ones the Design screens use, so the real canvas can reuse them.

**Not done yet:** the real React app against the WebSocket contract. Plan: generate components from the Design frames with the Figma agent's design context, then wire them to the mock fixtures.

## Design into the real app (log, newest last)

Branch `figma-design-in-code`, pushed after each step so the backend work can continue alongside.

### 21:09 · Tokens and fonts

**Tools:** Figma agent `get_variable_defs` on the Build running frame, then hand-mapped into `web/src/styles/tokens.css`.

**What moved:** every colour (paper, ink, accent `#0a6cff`, status, part greys), the Float shadow, radius 8, panel widths 248 and 300, and the three typefaces (Averia Serif Libre, Atkinson Hyperlegible Next and Mono) in `index.html`. The Figma names sit next to the app's older names (`--bg`, `--text`…), so all 1,700 lines of existing CSS restyled without edits.

**Small CSS edits:** body 14 px / 1.5, Averia for the brand and the Home headline (−3% tracking, 0.95 leading), mono uppercase labels with 8% tracking for panel headings and status pills, amber fill for over-budget stage bars.

**Friction:** the Figma warn colour `#e0a030` fails AA as text on white, so text uses a darker `#b7791f` and only bars use the Figma value. Dark mode no longer follows the OS; the plan says light only for the demo.

**Minutes:** about 12. **Rating:** 5/5; the variable names carried straight over.

### 21:14 · Workspace shell

**Tools:** the Figma frames (02 Build running, 07 Build tab, 08 Code tab) as the reference, read through the Figma agent; code written by Claude Code against the existing React components. No component was rewritten, only moved.

**What moved:**
- Columns are now 248 / canvas / 300 px, as in Figma, with flat paper panels and hairlines between sections instead of cards (`web/src/styles/shell.css`, loaded after `app.css`).
- Left panel: a compact **step player** (eight dots, the active one stretched into a bar, the stage name in mono caps) above **Layers**, which is the old Parts list.
- Right panel: five tabs (Parts, Wiring, Board, Firmware, Checks) became Figma's three: **Design** (clarify, spec, design reuse, checks), **Build** (pipeline, decisions) and **Code** (a Wiring / Board / Firmware switch). ⌥1–⌥3 switch tabs; the failing-check badges now count per tab.
- Layers rows show name and quantity; licence and provenance drop onto a second line on hover or selection, as the Figma row hover card does. The unverified flag stays in the hover line.

**Checked:** typecheck, lint and the 45 web tests pass; a mock build (`?mock=1`) renders every tab.

**Friction:** at 248 px the old rows (name, qty, provenance, licence, Remove) did not fit; the Figma answer, hover for detail, was the fix. The step player's "Done · 8 stages" label truncated, now "Done". New styles went in a separate file because another session is editing the end of `app.css`.

**Not yet:** the top bar still holds build id, status, model and Export (Figma moves them into the panel headers); the floating bottom toolbar with Ask, the view cube and the part inspector are still the old components.

**Minutes:** about 25. **Rating:** 4/5.

### 21:24 · Top bar into the panel headers

**Tools:** Figma frame 02 (left header "Build meta", right toolbar) as the reference; Claude Code split the existing `TopBar` into two components that reuse its pieces.

**What moved:**
- Left panel header (`FileHeader`): **Bara / prompt**, then **build id + status pill** (+ mock), then **connection dot · model**, with provider and fallback in the hover title. This is the live-site information the coverage audit found missing from the first Figma pass, now in the real app.
- Right panel toolbar (`PanelToolbar`): Home, then **Export** as the one primary action. The Export menu and its seven formats are unchanged.
- The top bar now shows only on Home, so the workspace canvas runs the full window height.
- Primary buttons are ink, as in the Figma Button component; blue is kept for selection and live state.

**Checked:** typecheck, lint, 45 tests; mock build renders both headers.

**Friction:** none worth noting; the top bar was already split into small pieces.

**Minutes:** about 10. **Rating:** 5/5.

### 21:31 · Floating dock with the Ask field

**Tools:** Figma Bottom Toolbar and Ask Field components as the reference. Instead of building the agent's eyes, we merged the teammate branch `bot-alive`, which already puts an animated BaraBot inside the prompt bar; that is the Figma Ask field with the eyes. Styling only after that; no JSX changed in this step.

**What moved:**
- The prompt bar is now the **Ask pill**: paper with a hairline and the Float shadow, BaraBot on the left, a soft paper-2 field, an ink Build button, all fully rounded.
- The view toolbar under it matches the Figma toolbar: mono caps labels, ink explode slider, borderless segments with a paper-3 active state instead of blue.
- Both float over the canvas with the same shadow, so they read as one dock.

**Checked:** typecheck and 50 web tests (the merge brought 5 bot tests) pass; mock build renders the dock.

**Friction (for the 3D owner):** after merging `bot-alive`, mock mode without a backend shows an empty canvas: every `/assets/parts/*.glb` request returns 500 and the viewer no longer falls back to boxes as it did before the merge. Not caused by this step (CSS only), not fixed here, because `Viewport3D.tsx` is being changed on the other branch. Why not a single bar as in Figma: the view toolbar lives inside `Viewport3D.tsx`, so it stays a separate pill to avoid conflicts.

**Minutes:** about 12. **Rating:** 4/5.

### 21:40 · Part inspector

**Tools:** the Figma Inspector frame (focus screens 14–16) as the reference; Claude Code reordered the existing `PartInspector` with the same data and handlers.

**What moved:**
- Order now follows Figma: summary and key specs, three fact tiles (qty, placed by, locked or free), the action row, **Position**, **Why this part**, **Checks**, **Source**.
- Actions show their keys (Swap `S`, Recolour `R`, Move `M`) and the keys work while the inspector is open on a finished build; Remove sits apart on the right.
- Position is X / Y / Z mono fields plus rotation, instead of one comma list.
- Source holds provenance, licence, attribution, links and interfaces (was "Details" at the bottom with provenance at the top).
- Flat paper panel with hairline sections and mono caps headings, Averia for the part name.

**Checked:** typecheck, lint, 50 web tests; mock build, selected a Layers row, pressed R and the colour picker opened inline.

**Friction:** at 300 px the four actions wrapped; tighter button padding keeps them on one line. The mock canvas rendered placeholder blocks this time, so the earlier blank-canvas note may have been a cold start; worth a recheck by the 3D owner.

**Minutes:** about 12. **Rating:** 4/5.

### Trust fixes from the live-site audit

The coverage audit of the live site found three places where the UI said two contradicting things. Each is now one honest statement. Tools: Claude Code against the existing components; the Figma status colours (warn amber) for the new states.

**Stages over budget.** A stage that finished past its budget showed an amber time and the word "ok" ("Find design 123 / 30 ms ok"). Now the status reads "over 4.1×", the dot turns amber, and hovering says it finished but took 123 ms against 30. Running and failed stages are unchanged.

**Unexplained model switch.** The header named the configured model while the build's calls could have gone to the backup. Now the header reads the models the build actually used (classifier and decisions): if any call fell back, it shows ~~llama-4-scout~~ → claude-haiku-5-5 BACKUP in amber, with the server's fallback warning as the hover reason.

**Firmware "Compiled" and "compile skipped" together.** The server's `mode: compiled` means the source was generated for this board, not that a binary exists. The badges now read "Generated source" and "not built" (amber, with the reason on hover); the other states read "build queued", "building", "binary built", "build failed".

**Checked:** typecheck, lint, 50 tests; mock build shows "over 4.1×" on Find design and "Prebuilt · not built" on firmware; the backup-model header was checked by setting a fallback classifier in the store, since the mock never falls back.

**Minutes:** about 20. **Rating:** 4/5.

### Four new features: Figma first

**Tools:** Figma Design through the Figma agent (use_figma), reusing the Agent, Chip, Kbd and Ask Field components and the colour and type variables. Five new frames on the Screens page:
- 17 Focus · isolated part, with 17a Focus · motion
- 18 Explode · view-aware labels
- 19 Voice · talk to Bara
- 20 Case · match the library parts

**What we decided in Figma before writing code:**
- **Focus:** clicking a part pulls it to the centre and shrinks everything else onto a shelf on the left. The agent card asks one question with three plain options (Ask about it `A`, Change it `S`, Something else `O`) and three suggested questions. The motion is specified beat by beat (press, pull apart, centre, agent asks, put back).
- **Labels:** a part gets a label only while a ray from the camera hits it first. The line lands on its nearest visible anchor, and hidden parts are counted under the column.
- **Voice:** hold Space to talk; Bara answers out loud with live captions in the Ask pill.
- **Case:** the exploded view showed it as a pale slab whose edges vanished; it becomes graphite with satin plastic, and its edges stay drawn.

**Friction:** the part renders are 1x1 frames with overflowing vectors, so placement had to be measured from the leaf vectors. The case layers carried low layer opacity, which hid the first recolour.

**Minutes:** about 35. **Rating:** 4/5.

### Case on par with the library parts

**What moved:** the default case colour is graphite `#4A4E55` instead of `#D3D1CB`, and the brief's colour still wins. The case material is satin plastic with a light clearcoat and a rim sheen. Crease lines stay drawn in ink when pulled apart instead of fading to nothing.

**Checked:** typecheck; a real keyboard build against the live engine, exploded in ISO view. The case top and bottom read as solid shells next to the KiCad board and the sourced switches.

**Not done:** the darker inner wall from the Figma spec; it needs per-face shading in the shader. **Minutes:** about 15. **Rating:** 4/5.

### Labels that follow what you can see

**What moved:** each label anchor now knows which part it sits on. A few times a second, while the camera or the explode moves, a ray from the camera checks whether that part is the first thing it meets. If another part is in the way, the label waits 150 ms, then fades out over 180 ms; turning the model back fades it in. With several anchors per label, the line uses the visible one nearest the label column. Hidden parts are counted under the column ("+6 behind other parts, turn the model to see them"). See-through shells (the assembled case) don't hide what is inside.

**Checked:** typecheck, lint, tests; a real keyboard build pulled apart. ISO and front show all seven labels; from below only the case bottom keeps its label, with the other six counted as behind. Orbiting between the two brings them back.

**Not done:** the Figma rule "hover a Layers row to show its label anyway". **Minutes:** about 20. **Rating:** 4/5.

### Part focus with the agent card

**Tools:** Figma frames 17 and 17a as the spec; Claude Code for the scene, store and card. The engine got a new route, `POST /v1/builds/{id}/ask`, which answers about one part from the build's own facts (card, why it was chosen, connections, checks). It is short and spoken-style, Cerebras first and Anthropic as backup.

**What moved:**
- Clicking a part in 3D, or its Layers row, pulls it out. It eases to just right of the view's centre and grows to fill about 60% of the view. Every other part shrinks onto a shelf down the left fifth, in stack order. The labels step aside, the floor hides, and the selection outline drops so the part isn't drowned in blue.
- The right column becomes Bara's card: the eyes, the part, one question and three options. **Ask about it** (`A`) opens a question field. **Change it** (`S`) opens swap, or resize for the case and board. **Something else** (`O`) holds details, recolour, move and take it out. Three suggested questions start the chat, and the model's follow-ups replace them after each answer. `←` `→` step through parts; `Esc` closes a drawer first, then puts the part back.
- Footprint models drawn from the KiCad board export (switches, diodes, MCU) focus as their own parts, not as "the board".

**Checked:**
- Typecheck, lint, and 65 tests: 3 new for the focus layout (centred and grown, shelf on the left, split halves kept together) and 3 server tests for the ask route.
- In the browser, on two fresh keyboard builds from the live engine: pulled out the switches, asked "Why this one?", stepped to the keycaps and pressed Esc.

**Friction:**
- The exploded framing shifts the image 20% left for the label column. That shift now relaxes as focus eases in, or the shelf would land off-screen.
- An InstancedMesh's cached bounds were stale after a remount, so focus measures instance by instance.
- The engine on Pranav's machine still runs code without `/ask` (404). The card says when its answer came from the build rather than the model; the route goes live when the engine restarts on this commit.

**Minutes:** about 60. **Rating:** 4/5.

## Before and after

| Change | Before | After |
|---|---|---|
| Restyle every screen (cream to white) | redraw 10 screens | edit 12 colour variables, 1 call |
| Change every font | retype each text layer | edit 15 text styles plus one sweep |
| Rebuild after losing agent access | start over | replay saved scripts, about 20 min |

## Reuse this process

1. Write the plan as a doc first; let the agent read it.
2. Make tokens and text styles before any screen.
3. Build components, then clone screens from one finished screen.
4. Prototype only the interaction that must be felt, in Make.
5. Keep a ledger of node IDs so a lost session can resume.
