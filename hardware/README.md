# Hardware gate

Tangible turns a sentence into a gadget: parts, a KiCad schematic and PCB, and a printed shell.
This folder holds boards Tangible generated, and the gate every board passes before it ships.

- `boards/<board>/` holds `main.kicad_pcb`, `main.kicad_sch`, `main.kicad_pro` and `fp-lib-table`.
  Library paths use `${TANGIBLE_ROOT}`, `${TANGIBLE_SOURCES}` and `${KICAD10_FOOTPRINT_DIR}`.
- `policy.json` sets the gate (0 DRC errors, 0 ERC errors, 0 unconnected items, 0 blocked parts)
  and maps each footprint library to its source and licence.

Run it locally (needs `kicad-cli` 10):

```sh
PYTHONPATH=server/src python3 -m bara.hwci check hardware/boards --policy hardware/policy.json
PYTHONPATH=server/src python3 -m bara.hwci fab hardware/boards --out hw-fab
```

`check` writes `hw-report/`: `results.json`, `gate.md` (the merge request note), `junit.xml`,
`gl-code-quality-report.json` and a CycloneDX hardware BOM per board in `hbom/`.

The same checks are an MCP server for GitLab Duo (`.gitlab/duo/mcp.json`):

```sh
PYTHONPATH=server/src python3 -m bara.hwci.mcp_server --root hardware/boards --policy hardware/policy.json
```

Tools: `list_boards`, `check_board`, `board_parts`, `export_fab`.
