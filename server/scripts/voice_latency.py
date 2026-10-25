# ruff: noqa: T201
"""Time from asking Bara's voice to speak until the first audio byte, cold and from memory.

Run with `uv run python scripts/voice_latency.py`. The key is read from the environment or the
macOS keychain and is never printed. Without a key it says so and exits 0.
"""

from __future__ import annotations

import asyncio
import statistics
import time

from bara import voice

LINES = [
    "Routing the board.",
    "That switch is a tactile one, so each press has a small bump you can feel.",
    "Case closed. Every check passed.",
]


async def first_byte(text: str) -> tuple[float, float]:
    t0 = time.perf_counter()
    client, resp = await voice.open_speech(text)
    gen = voice.relay(client, resp)
    await gen.__anext__()
    first = (time.perf_counter() - t0) * 1000
    async for _ in gen:
        pass
    return first, (time.perf_counter() - t0) * 1000


async def main() -> None:
    if not voice.load_key_from_keychain() and not voice.key():
        print("no OpenAI key in the environment or keychain: nothing to measure")
        return
    print(f"voice settings: {voice.settings()}")
    await first_byte("warm up the connection")  # TLS handshake is paid once per engine run
    cold: list[float] = []
    for line in LINES * 2:
        voice._phrases.clear()
        first, total = await first_byte(line)
        cold.append(first)
        print(f"cold   first byte {first:6.0f} ms  whole line {total:6.0f} ms  {line[:40]}")
    again, _ = await first_byte(LINES[0])
    print(f"again  first byte {again:6.0f} ms  (remembered line)")
    print(f"cold median {statistics.median(cold):.0f} ms over {len(cold)} lines")


asyncio.run(main())
