# Tangible: KiCad checks every board before it ships

## Tagline

Describe a gadget and Tangible builds it from real parts. GitLab CI and a Duo flow check every board with KiCad before anyone orders it.

## Inspiration

Tangible was first shown at Cal Hacks 13.0 (Oct 24-25, 2026); the GitLab integration was built for this hackathon.

Tangible takes one sentence, like "a wireless macropad with a knob", and picks real parts, routes a KiCad board, shapes a printable case and writes the firmware. When we ran KiCad's own checks on the boards it had already made, two of three failed. Unit tests on the Python never saw that, because the mistakes were in the board files: a clearance 0.025 mm under the rule, a net with nothing driving it. We wanted the checks a careful engineer runs before a fab order to happen on every change, with the results somewhere a person would actually read them.

## What it does

Every merge request that touches a board runs the hardware gate in GitLab CI. It runs KiCad 10's Design Rule Check on the PCB and Electrical Rule Check on the schematic. It also traces each footprint to the library it came from and checks that library's licence against a policy file.

The results go where GitLab already shows them:

- one note on the merge request, with each error and its position on the board in millimetres
- a JUnit report for the test widget and a Code Quality report for the diff
- a CycloneDX hardware BOM per board
- a hardware::pass or hardware::fail label

A Duo Agent Platform flow, "Tangible hardware gate triage", picks up from there. Mention it or assign it on a merge request. One agent reads the failing job logs and the gate report. A second writes a plain explanation of each error with the likely fix, and keeps one tracking issue per failing board. It is supervised on purpose: the flow explains and files, and a person changes the board. On merge request !1 the flow read the failing pipeline and posted a note explaining each error in plain words. One example: two output pins share a net at (44.45, 45.72) mm, so the parts would fight each other, and changing one pin's type or removing one connection would fix it. It then commented on the tracking issue for each failing board. It also said what it couldn't see. The carrier board's one ERC error was counted in the report but not listed, so the note sends the reader to the job artifacts instead of guessing.

A custom Duo agent, "Tangible hardware reviewer", is published in the AI Catalog for questions about hardware merge requests in Duo Chat. The same checks run as an MCP server (list_boards, check_board, board_parts, export_fab), so an assistant in the editor can ask which boards fail and where.

The rest of the pipeline covers the lifecycle. GitLab SAST, Secret Detection and Dependency Scanning run on every main pipeline. Gerbers, drill, pick-and-place and BOM go into the package registry. Tag v0.1.0 cut the first release, with the gate report as its notes and links to the three fab zips. The web app deploys to GitLab Pages, and a daily scheduled smoke check opens an incident issue if the site goes down.

## How we built it

Everything below was added on or after Oct 5, for this hackathon:

- bara.hwci, a small stdlib Python package that drives kicad-cli for DRC, ERC and fab export, parses footprints and the board's library table for provenance, and writes the GitLab report formats
- three boards Tangible generated (a WiFi handheld, a macropad, a carrier board), with portable library paths, as test fixtures for the gate
- .gitlab-ci.yml with stages for verify, secure, package, govern, deploy, release and monitor
- a GitLab project runner on a Mac with native KiCad 10 for the hardware jobs, while the security scanners and Duo sessions run on GitLab's hosted runners
- the Duo flow (registry v1 YAML, two agent components with their own prompts and tool sets), the custom agent, .gitlab/duo/agent-config.yml and .gitlab/duo/mcp.json
- a stdio MCP server, tested with the official MCP Python client
- 7 tests for the gate, including a real KiCad run and an MCP round trip

KiCad marks some notices only because a library is missing on the CI image, so the gate tags those as environment issues. They are shown but do not count toward the verdict. Everything else counts.

## Challenges we ran into

Generated boards point at absolute library paths on the machine that built them, so we rewrote them to environment variables before KiCad could open them anywhere else. The first gate run reported 329 library notices that had nothing to do with the design, and we had to separate those from real errors without hiding anything. LCSC footprints carry no licence statement, so the policy sends them to review instead of passing or blocking them. Until the account was verified, neither hosted runners nor Duo sessions would start, so the KiCad jobs moved to a Mac project runner, and they stayed there. The first Duo session then failed because the KiCad image has no curl to fetch the Duo CLI. Sessions now use a Python image, which is enough because the flow only reads GitLab and writes notes.

## Accomplishments that we're proud of

On its first real run the gate found real problems in boards we had already shown:

- the macropad has 2 ERC errors, an undriven input at (29.21, 45.72) mm and two outputs tied together at (44.45, 45.72) mm
- the carrier board has 8 clearance errors, 0.125 mm against a 0.15 mm rule, plus 1 ERC error
- the WiFi handheld passes with 0 DRC and 0 ERC errors

All three boards check in about 7 seconds on a laptop. In CI the hardware:gate job takes about 13 seconds.

## What we learned

Hardware fits merge request review well once the results are in formats GitLab already reads. The agent's note can only be as complete as the job log it reads: the report left one ERC error out, and the agent said so instead of making one up. The useful part of the agent is the translation: "pin_to_pin at (44.45, 45.72)" becomes "two outputs drive the same net here, so the parts would fight each other."

## What's next for Tangible

- feed the gate's errors back into Tangible's board generator, so a failing board is regenerated before anyone sees it
- print every error in the gate report, so the triage note never has to point at the artifacts
- run the gate on every board in Tangible's library
- add a fab-house design-rule profile, so the gate checks a specific manufacturer's limits

## Built with

GitLab CI/CD, GitLab Duo Agent Platform (flows, custom agents, MCP), GitLab Pages, GitLab Package Registry, GitLab Runner, GitLab SAST, Secret Detection, Dependency Scanning, GitLab Releases, KiCad 10, Python, TypeScript, React, Vite, Three.js, CycloneDX, MCP

## Links

- GitLab project: https://gitlab.com/tangible-parts/tangible
- Merge request with the gate and the Duo flow: https://gitlab.com/tangible-parts/tangible/-/merge_requests/1
- Live site (GitLab Pages): https://tangible-c3783a.gitlab.io/
- Original project on GitHub: https://github.com/PranavAchar01/bara
- Demo video: VIDEO_URL
