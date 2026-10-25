"""Apify Actor entry point: read the input, run the scout, push every item to the dataset."""

from __future__ import annotations

from apify import Actor

from .scout import scout


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        if not inp.get("query") and not inp.get("lcscIds"):
            raise ValueError("Give a device description in `query` or LCSC part numbers in `lcscIds`.")
        Actor.log.info("Scouting open hardware for %r", inp.get("query"))
        items = await scout(inp)
        await Actor.push_data(items)
        n = {k: sum(i["type"] == k for i in items) for k in ("design", "part")}
        await Actor.set_status_message(f"{n['design']} open designs, {n['part']} priced parts")
