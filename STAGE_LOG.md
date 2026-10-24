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
