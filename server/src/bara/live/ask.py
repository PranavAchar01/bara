"""One structured Anthropic call with a long deadline, for the stages that need real reasoning
(function blocks, product form, identity judge). The brief writer keeps its 5 s cascade; these
stages run once per build, so they get a budget that fits a thinking answer and may carry images.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from bara.live.llm_json import _for_anthropic

log = logging.getLogger(__name__)
DEFAULT_MODEL = "claude-sonnet-5-5"
FAST_MODEL = "claude-sonnet-5-5"  # part picks need the same judgment as the reasoning stages
# answers by question: the same question (prompt, schema, images, model) is answered once
CACHE = Path(__file__).resolve().parents[3] / "data/cache/llm"


def model_name(fast: bool = False) -> str:
    if fast:
        return os.environ.get("BARA_FAST_MODEL", FAST_MODEL)
    return os.environ.get("BARA_FORM_MODEL", DEFAULT_MODEL)


def _cache_path(model: str, system: str, prompt: str, schema: dict, images: list[bytes]) -> Path:
    h = hashlib.sha256()
    for part in (model, system, prompt, json.dumps(schema, sort_keys=True)):
        h.update(part.encode())
        h.update(b"\0")
    for img in images:
        h.update(hashlib.sha256(img).digest())
    return CACHE / f"{h.hexdigest()}.json"


async def ask_json(
    system: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    name: str,
    timeout_s: float = 60.0,
    max_tokens: int = 4096,
    images: list[bytes] | None = None,
    fast: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """(data, note). data is None with a reason in note when no answer was usable. `fast` asks
    the small model: for short checks and picks, not for the reasoning stages."""
    model = model_name(fast)
    cached = _cache_path(model, system, prompt, schema, images or [])
    try:
        return json.loads(cached.read_text()), "ok (cached)"
    except (OSError, ValueError):
        pass
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, "no ANTHROPIC_API_KEY"
    from anthropic import AsyncAnthropic

    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(img).decode(),
            },
        }
        for img in images or []
    ]
    content.append({"type": "text", "text": prompt})
    client = AsyncAnthropic(api_key=key, timeout=timeout_s, max_retries=1)
    try:
        # An answer cut off by the token cap is unparseable JSON; ask again with room to finish.
        for budget in (max_tokens, max_tokens * 2, max_tokens * 4):
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=budget,
                    system=system,
                    messages=[{"role": "user", "content": content}],
                    output_config={
                        "effort": "high",
                        "format": {"type": "json_schema", "schema": _for_anthropic(schema)},
                    },
                ),
                timeout=timeout_s,
            )
            if response.stop_reason != "max_tokens":
                break
    except Exception as exc:  # any failure is reported, the caller decides what it means
        log.warning("ask_json %s failed: %s", name, exc)
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    finally:
        await client.close()
    if response.stop_reason == "refusal":
        return None, "model refused"
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        return None, "no text in the answer"
    try:
        data = json.loads(text)
        errors = list(Draft202012Validator(schema).iter_errors(data))
    except ValueError as exc:
        return None, f"bad JSON: {exc}"
    if errors:
        return None, f"schema: {errors[0].message[:160]}"
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data))
    except OSError:
        log.warning("ask_json %s: answer not cached", name)
    return data, "ok"
