"""Tangible hardware tools over MCP (stdio, JSON-RPC 2.0), for GitLab Duo's MCP client.

    python -m bara.hwci.mcp_server --root hardware/boards --policy hardware/policy.json

Duo Agentic Chat in the IDE or the Duo CLI reads `.gitlab/duo/mcp.json`, starts this server
and can then list the boards, run KiCad DRC/ERC on one, read its part provenance and build its
fab package, all on the developer's machine with their own KiCad."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import kicad, provenance, report
from .__main__ import boards

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "list_boards",
        "description": "List the KiCad boards in the repository that the hardware gate checks.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_board",
        "description": "Run KiCad DRC and ERC plus the licence check on one board and return "
        "the gate verdict with every design error and its position in mm.",
        "inputSchema": {
            "type": "object",
            "properties": {"board": {"type": "string", "description": "board folder name"}},
            "required": ["board"],
        },
    },
    {
        "name": "board_parts",
        "description": "Every footprint on a board with its source library and licence.",
        "inputSchema": {
            "type": "object",
            "properties": {"board": {"type": "string"}},
            "required": ["board"],
        },
    },
    {
        "name": "export_fab",
        "description": "Write the board's gerbers, drill, pick-and-place and BOM to a zip.",
        "inputSchema": {
            "type": "object",
            "properties": {"board": {"type": "string"}, "out": {"type": "string"}},
            "required": ["board"],
        },
    },
]


class Server:
    def __init__(self, root: Path, policy: Path) -> None:
        self.root = root.resolve()
        self.policy = provenance.load_policy(policy)

    def board(self, name: str) -> Path:
        found = {b.name: b for b in boards(self.root)}
        if name not in found:
            raise ValueError(f"unknown board {name!r}; boards: {', '.join(sorted(found))}")
        return found[name]

    def call(self, name: str, args: dict[str, Any]) -> Any:
        if name == "list_boards":
            return [b.name for b in boards(self.root)]
        b = self.board(str(args.get("board", "")))
        if name == "board_parts":
            return provenance.check(b, self.policy)["parts"]
        if name == "export_fab":
            out = Path(str(args.get("out") or f"hw-fab/{b.name}-fab.zip"))
            return {"zip": str(out), "files": kicad.fab(b, out)}
        if name == "check_board":
            res: dict[str, Any] = {
                "name": b.name,
                "path": str(b),
                "drc": kicad.drc(b),
                "erc": kicad.erc(b),
                "provenance": provenance.check(b, self.policy),
            }
            res["gate"] = report.gate(res, self.policy)
            for k in ("drc", "erc"):
                res[k]["violations"] = [v for v in res[k]["violations"] if not v["environment"]]
            res["provenance"]["parts"] = [
                p for p in res["provenance"]["parts"] if p["verdict"] != "ok"
            ]
            return res
        raise ValueError(f"unknown tool {name!r}")

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification
            return None
        if method == "initialize":
            result: Any = {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tangible-hardware", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                data = self.call(p.get("name", ""), p.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(data, indent=1)}]}
            except (ValueError, RuntimeError, OSError) as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": f"no method {method}"}}  # fmt: skip
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bara.hwci.mcp_server")
    ap.add_argument("--root", type=Path, default=Path("hardware/boards"))
    ap.add_argument("--policy", type=Path, default=Path("hardware/policy.json"))
    a = ap.parse_args(argv)
    srv = Server(a.root, a.policy)
    for line in sys.stdin:
        if not line.strip():
            continue
        reply = srv.handle(json.loads(line))
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
