# GitLab Transcend "Life After Code": requirements checklist

Source: https://gitlab-transcend.devpost.com/ (rules page). Deadline Tue 2026-10-27 6:00 AM PT.
Path: B, Bring Your Own (an existing MIT project, extended on or after Oct 5).

Status key: DONE, OPEN (work left), HIS (needs Pranav).

## Submission requirements

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Uses the GitLab Duo Agent Platform (agents, flows or MCP) | DONE: flow ran on MR !1 (session 10098503), posted triage note 4095376337 and commented on issues #1 and #2 | `.gitlab/duo/flows/hardware-gate-triage.yml`, `.gitlab/duo/agents/hardware-reviewer.md`, `.gitlab/duo/mcp.json` |
| 2 | Public GitLab repo | DONE | https://gitlab.com/tangible-parts/tangible |
| 3 | MIT LICENSE visible in About | DONE (GitLab detects MIT) | `LICENSE` |
| 4 | Original project is MIT, URL given | DONE (GitHub detects MIT, commit 3517de3) | https://github.com/PranavAchar01/bara |
| 5 | CI/CD pipeline history visible | DONE: KiCad jobs on a Mac project runner; SAST, Secret Detection and Dependency Scanning on hosted runners (main pipeline 2992410626) | https://gitlab.com/tangible-parts/tangible/-/pipelines/2992379626 |
| 6 | Deployed public URL, live until about Nov 16 | DONE (GitLab Pages from main pipeline 2992391781) | https://tangible-c3783a.gitlab.io/ |
| 7 | Demo video under 3 min, public on YouTube | OPEN | `docs/hackathons/gitlab-transcend/` |
| 8 | Say what was added on or after Oct 5 | DONE in draft | `devpost.md` "How we built it" |
| 9 | Prior-work disclosure (Cal Hacks 13.0, Oct 24-25) | DONE in draft | `devpost.md` |
| 10 | Devpost form filled | Story, tags, links, additional info and attestations saved (3/5); demo video URL OPEN; final Submit by main | Devpost |

## Judging (equal weight) and how this entry answers it

- Technological implementation: real KiCad 10 DRC/ERC in CI, licence provenance per
  footprint, JUnit + Code Quality + CycloneDX reports, an MCP server, a two-agent Duo flow.
- Design: the gate result is one note on the merge request with board positions in mm.
- Impact: generated hardware is checked by the same tools a person would use before a fab order.
- Innovation: CI/CD and Duo agents applied to PCB design files, not only code.
- Presentation: video plus this checklist and evidence screenshots.
- Stage One pass/fail: reasonable use of Duo Agent Platform (flow + agent + MCP).

## Lifecycle stages covered (Most Stages Covered prize)

| Stage | Job or feature |
|---|---|
| Plan | Tracking issues per failing board (`hardware:report`, Duo triage flow) |
| Create | Duo reviewer agent and MCP tools in the editor |
| Verify | `hardware:gate`, `server:test`, `web:test` |
| Package | `hardware:fab` to the Generic Package Registry, `web:build` |
| Secure | SAST, Secret Detection, Dependency Scanning on hosted runners, every main pipeline |
| Release | `release` job on tags; v0.1.0 released with 3 fab zip links and the gate report as notes |
| Configure | `.gitlab/duo/agent-config.yml`, masked CI variable for the gate token |
| Monitor | `monitor:smoke` on the Pages URL, schedule; opens an incident issue on failure |
| Govern | `hardware:provenance` licence policy, CycloneDX hardware BOM |

## Optional

- Google Cloud bonus (+0.2): skipped, it needs a billing account.

## Verified locally (2026-10-26)

- `pytest tests/test_hwci.py tests/test_contract.py`: 13 passed. ruff clean.
- KiCad 10.0.7 gate on the three boards: wifi-handheld pass; wifi-macropad 2 ERC errors
  (pin_not_driven, pin_to_pin); carrier-board 8 DRC clearance errors and 1 ERC error.
- MCP server answered the official MCP Python client (protocol 2025-06-18, four tools).
- `.gitlab-ci.yml` passes GitLab's CI lint API.
- Mock web build (`VITE_MOCK=1 pnpm build`) succeeds.

## Verified on GitLab (2026-10-26 evening)

- MR !1 pipelines 2992379626 and 2992389068: hardware:gate fails on carrier-board (8 DRC, 1 ERC)
  and wifi-macropad (2 ERC), wifi-handheld passes; hardware:report posted the MR note and the
  hardware::fail label; server:test, web:test and hardware:provenance pass; 22 tests in the Tests tab.
- MR !1 merged. Main pipeline 2992391781 passed: fab zips in the package registry (tangible-fab
  0.0.9), issues #1 and #2 for the failing boards, Pages deployed, monitor:smoke passed.
- Daily pipeline schedule 4514143 runs monitor:smoke at 9:00 PT.
- After identity verification: shared runners on. Duo session 10098461 failed (KiCad image has no
  curl); agent-config moved to python:3.12-bookworm. Session 10098503 finished: triage note on MR !1,
  comments on issues #1 and #2. Started with the flow consumer id, not the catalog version id.
- Main pipeline 2992410626 passed, scanners included. Tag v0.1.0 pipeline 2992406317 cut the release.
- Screenshots in evidence/ (taken signed out, public view).
