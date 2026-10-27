"""Talk to the Tangible hardware MCP server with the official MCP Python client.

    uv run --with mcp python server/scripts/hwci_mcp_probe.py .

This is the same stdio handshake GitLab Duo's MCP client does with `.gitlab/duo/mcp.json`.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _say(text: str) -> None:
    sys.stdout.write(f"{text}\n")


async def main(root: str) -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", f"{root}/server", "python", "-m", "bara.hwci.mcp_server",
              "--root", f"{root}/hardware/boards", "--policy", f"{root}/hardware/policy.json"],
    )  # fmt: skip
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        _say(f"server: {init.server_info.name} {init.protocol_version}")
        tools = await s.list_tools()
        _say(f"tools: {[t.name for t in tools.tools]}")
        res = await s.call_tool("list_boards", {})
        _say("list_boards: " + res.content[0].text.replace("\n", ""))
        res = await s.call_tool("check_board", {"board": "wifi-macropad"})
        d = json.loads(res.content[0].text)
        errs = [v["type"] for v in d["erc"]["violations"] if v["severity"] == "error"]
        _say(f"check_board wifi-macropad gate: {d['gate']} erc errors: {errs}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "."))
