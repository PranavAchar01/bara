# Notes for agents working in this repository

- `server/` is the Python engine (uv, ruff, pytest). `web/` is the Vite + React app (pnpm).
- Generated boards and the hardware gate live in `hardware/`; read `hardware/README.md`.
- The gate is `python3 -m bara.hwci` (stdlib only, needs `kicad-cli` 10). CI runs it in
  `kicad/kicad:10.0`; see `.gitlab-ci.yml`.
- GitLab Duo: the triage flow is `.gitlab/duo/flows/hardware-gate-triage.yml`, the reviewer
  agent is `.gitlab/duo/agents/hardware-reviewer.md`, the MCP server config is
  `.gitlab/duo/mcp.json`.
- Never edit a board to make the gate pass without saying what changed and why. Never invent
  DRC or ERC numbers: quote the gate report.
- Tests: `cd server && uv run pytest -q tests/test_hwci.py`; `cd web && pnpm typecheck && pnpm test`.
