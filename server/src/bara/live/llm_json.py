"""Schema-constrained JSON calls for the live engine: Cerebras first, Anthropic second.

Same cascade and key rules as bara.llm (keys from the environment only, hard deadline per
call, local schema validation), with the system prompt passed in so the brief writer and
the part picker can share it. Returns None when no provider answered; callers then use
their deterministic path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from bara.llm import CEREBRAS_URL, LlmResult, anthropic_headers, record_usage

log = logging.getLogger(__name__)


def _check(schema: dict[str, Any], data: Any) -> dict[str, Any]:
    errors = list(Draft202012Validator(schema).iter_errors(data))
    if errors:
        raise ValueError(f"output failed its schema: {errors[0].message[:200]}")
    return data


async def _cerebras(
    system: str, prompt: str, schema: dict[str, Any], name: str, model: str, key: str, t: float
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=t) as client:
        resp = await client.post(
            CEREBRAS_URL, json=body, headers={"Authorization": f"Bearer {key}"}
        )
    resp.raise_for_status()
    record_usage("cerebras", model, name, resp.json().get("usage"))
    return _check(schema, json.loads(resp.json()["choices"][0]["message"]["content"]))


def _for_anthropic(node: Any) -> Any:
    """Anthropic structured output rejects enums on a type list; rewrite them as anyOf."""
    if isinstance(node, list):
        return [_for_anthropic(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _for_anthropic(v) for k, v in node.items()}
    types, enum = out.get("type"), out.get("enum")
    if isinstance(types, list) and enum is not None:
        rest = {k: v for k, v in out.items() if k not in ("type", "enum")}
        values = [e for e in enum if e is not None]
        branches = [{"type": t, "enum": values} for t in types if t != "null"]
        if "null" in types:
            branches.append({"type": "null"})
        return {**rest, "anyOf": branches}
    return out


async def _anthropic(
    system: str, prompt: str, schema: dict[str, Any], name: str, model: str, key: str, t: float
) -> dict[str, Any]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=key, timeout=t, max_retries=0, default_headers=anthropic_headers()
    )
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": _for_anthropic(schema)},
            },
        )
    finally:
        await client.close()
    record_usage("anthropic", model, name, response.usage)
    if response.stop_reason == "refusal":
        raise ValueError(f"model refused the {name} request")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError(f"no text block in the {name} response")
    return _check(schema, json.loads(text))


async def call_json(
    system: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    name: str,
    cerebras_model: str,
    anthropic_model: str,
    timeout_s: float,
) -> tuple[LlmResult | None, list[str]]:
    notes: list[str] = []
    attempts = []
    if os.environ.get("CEREBRAS_API_KEY"):
        attempts.append(("cerebras", cerebras_model, _cerebras, os.environ["CEREBRAS_API_KEY"]))
    if os.environ.get("ANTHROPIC_API_KEY"):
        attempts.append(("anthropic", anthropic_model, _anthropic, os.environ["ANTHROPIC_API_KEY"]))
    for index, (provider, model, call, key) in enumerate(attempts):
        started = time.monotonic()
        try:
            data = await asyncio.wait_for(
                call(system, prompt, schema, name, model, key, timeout_s), timeout=timeout_s
            )
        except TimeoutError:
            notes.append(f"{provider} timed out after {timeout_s:.1f} s")
            continue
        except Exception as exc:  # any provider failure moves to the next provider
            notes.append(f"{provider} failed: {type(exc).__name__}")
            log.warning("live llm %s (%s) failed: %s", provider, name, exc)
            continue
        latency = int((time.monotonic() - started) * 1000)
        return LlmResult(data, provider, model, latency, fallback=index > 0), notes
    if not attempts:
        notes.append("no LLM key set")
    return None, notes
